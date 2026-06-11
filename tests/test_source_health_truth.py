"""
Tests for ``scripts.live_source_registry.compute_source_freshness``.

Pin
---
- Planned-only and partial sources are reported with their adapter_status
  and never claimed implemented.
- Missing credentials surface as ``skipped`` rather than secret exposure.
- Sources with an OK run within the cadence are ``fresh``.
- Sources whose last run is between 1× and 2× cadence are ``stale``.
- Sources beyond 2× cadence are ``overdue``.
- Sources that have never run are ``never_run``.
- ``next_expected_refresh_at`` is computed from last_success_at + cadence.
- Safety stamps locked on every per-source entry.
- No secret values appear anywhere in the result graph.
"""
from __future__ import annotations

from scripts import live_source_registry as lsr
from tests.helpers import scanner_probes as probes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(epoch: float) -> str:
    return lsr._format_epoch(epoch)


# ---------------------------------------------------------------------------
# Freshness windows
# ---------------------------------------------------------------------------


def test_fresh_within_cadence():
    now = 1_700_000_000.0
    rows = [
        {
            "source_name": "polymarket",
            "status": "OK",
            "timestamp_utc": _iso(now - 3600),  # 1 hour ago
        }
    ]
    result = lsr.compute_source_freshness(rows, cadence_hours=6, now_epoch=now)
    assert result["polymarket"]["freshness_state"] == lsr.FRESHNESS_FRESH
    assert result["polymarket"]["hours_since_last_success"] is not None
    assert result["polymarket"]["next_expected_refresh_at"] is not None


def test_stale_between_one_and_two_cadences():
    now = 1_700_000_000.0
    rows = [
        {
            "source_name": "polymarket",
            "status": "OK",
            "timestamp_utc": _iso(now - 8 * 3600),  # 8 hours ago, cadence=6
        }
    ]
    result = lsr.compute_source_freshness(rows, cadence_hours=6, now_epoch=now)
    assert result["polymarket"]["freshness_state"] == lsr.FRESHNESS_STALE


def test_overdue_beyond_two_cadences():
    now = 1_700_000_000.0
    rows = [
        {
            "source_name": "polymarket",
            "status": "OK",
            "timestamp_utc": _iso(now - 24 * 3600),  # 24 hours ago, cadence=6
        }
    ]
    result = lsr.compute_source_freshness(rows, cadence_hours=6, now_epoch=now)
    assert result["polymarket"]["freshness_state"] == lsr.FRESHNESS_OVERDUE


def test_never_run_when_no_row():
    now = 1_700_000_000.0
    result = lsr.compute_source_freshness([], cadence_hours=6, now_epoch=now)
    assert result["polymarket"]["freshness_state"] == lsr.FRESHNESS_NEVER_RUN
    assert result["polymarket"]["last_success_at"] is None
    assert result["polymarket"]["next_expected_refresh_at"] is None


# ---------------------------------------------------------------------------
# Missing credentials
# ---------------------------------------------------------------------------


def test_missing_credentials_skip_cleanly_without_secret_exposure():
    now = 1_700_000_000.0
    env = {}  # no NEWS_API_KEY
    result = lsr.compute_source_freshness(
        [], cadence_hours=6, now_epoch=now, env=env
    )
    # newsapi requires NEWS_API_KEY
    assert result["newsapi"]["freshness_state"] == lsr.FRESHNESS_SKIPPED
    assert result["newsapi"]["credential_configured"] is False


def test_present_credentials_allow_never_run_state():
    now = 1_700_000_000.0
    env = {"NEWS_API_KEY": "dummy"}
    result = lsr.compute_source_freshness(
        [], cadence_hours=6, now_epoch=now, env=env
    )
    assert result["newsapi"]["freshness_state"] == lsr.FRESHNESS_NEVER_RUN
    assert result["newsapi"]["credential_configured"] is True


# ---------------------------------------------------------------------------
# Planned vs implemented vs partial
# ---------------------------------------------------------------------------


def test_asia_disclosure_is_partial_not_implemented():
    """Asia Disclosure must report PARTIAL — never IMPLEMENTED — because
    only EDINET and OpenDART are real; the rest remain placeholders.
    Without keys, freshness is never_run (no runs yet), which is also
    honest."""
    now = 1_700_000_000.0
    result = lsr.compute_source_freshness([], cadence_hours=6, now_epoch=now)
    assert result["asia_disclosure"]["adapter_status"] == lsr.ADAPTER_PARTIAL
    assert result["asia_disclosure"]["freshness_state"] == lsr.FRESHNESS_NEVER_RUN


def test_partial_source_keeps_its_label():
    now = 1_700_000_000.0
    result = lsr.compute_source_freshness([], cadence_hours=6, now_epoch=now)
    assert result["global_filings"]["adapter_status"] == lsr.ADAPTER_PARTIAL


# ---------------------------------------------------------------------------
# Failed run does not look fresh
# ---------------------------------------------------------------------------


def test_failed_run_marks_failed_not_fresh():
    now = 1_700_000_000.0
    rows = [
        {
            "source_name": "polymarket",
            "status": "FAIL",
            "timestamp_utc": _iso(now - 1800),  # 30 min ago
        }
    ]
    result = lsr.compute_source_freshness(rows, cadence_hours=6, now_epoch=now)
    assert result["polymarket"]["freshness_state"] == lsr.FRESHNESS_FAILED


def test_skip_run_marks_skipped():
    now = 1_700_000_000.0
    rows = [
        {
            "source_name": "polymarket",
            "status": "SKIP",
            "timestamp_utc": _iso(now - 1800),
        }
    ]
    result = lsr.compute_source_freshness(rows, cadence_hours=6, now_epoch=now)
    assert result["polymarket"]["freshness_state"] == lsr.FRESHNESS_SKIPPED


# ---------------------------------------------------------------------------
# next_expected_refresh_at
# ---------------------------------------------------------------------------


def test_next_expected_refresh_at_uses_six_hour_cadence():
    now = 1_700_000_000.0
    last = now - 3600  # 1 hour ago
    rows = [
        {
            "source_name": "polymarket",
            "status": "OK",
            "timestamp_utc": _iso(last),
        }
    ]
    result = lsr.compute_source_freshness(rows, cadence_hours=6, now_epoch=now)
    expected_epoch = last + 6 * 3600
    assert result["polymarket"]["next_expected_refresh_at"] == lsr._format_epoch(
        expected_epoch
    )


# ---------------------------------------------------------------------------
# Safety stamps and secret hygiene
# ---------------------------------------------------------------------------


def test_safety_stamps_locked_on_every_entry():
    now = 1_700_000_000.0
    result = lsr.compute_source_freshness([], cadence_hours=6, now_epoch=now)
    for entry in result.values():
        assert entry["advisory_status"] == "ADVISORY_ONLY"
        assert entry["execution_gate"] == "LOCKED"
        assert entry["broker_api_called"] is False
        assert entry["ai_execution_count"] == 0
        assert entry["execution_permission"] is False
        assert entry["can_execute"] is False
        assert entry["may_execute"] is False
        assert entry["may_call_broker"] is False


def test_no_secret_value_exposed_in_freshness_output():
    """Even if the operator passes a credential into env, the freshness
    helper must not echo the value into the output graph.
    """
    import json

    now = 1_700_000_000.0
    # Values assembled at runtime: literal ones beside *_API_KEY names are
    # generic-api-key scanner bait (tests/helpers/scanner_probes.py).
    leaky_env = {
        "NEWS_API_KEY": probes.sk_style_token("LEAKED-1234567890"),
        "XAI_API_KEY": probes.xai_style_token("LEAKED-ABCDEFGHIJ"),
        "ETHERSCAN_API_KEY": probes.assemble("ES-", "LEAKED", "-XYZ"),
    }
    result = lsr.compute_source_freshness(
        [], cadence_hours=6, now_epoch=now, env=leaky_env
    )
    blob = json.dumps(result)
    for value in leaky_env.values():
        assert value not in blob


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


def test_garbage_timestamp_is_treated_as_no_run():
    now = 1_700_000_000.0
    rows = [
        {
            "source_name": "polymarket",
            "status": "OK",
            "timestamp_utc": "definitely-not-a-timestamp",
        }
    ]
    result = lsr.compute_source_freshness(rows, cadence_hours=6, now_epoch=now)
    assert result["polymarket"]["freshness_state"] in {
        lsr.FRESHNESS_NEVER_RUN,
        lsr.FRESHNESS_SKIPPED,
    }


def test_none_rows_handled():
    result = lsr.compute_source_freshness(None, cadence_hours=6, now_epoch=1.0)
    assert isinstance(result, dict)
    assert result["polymarket"]["freshness_state"] == lsr.FRESHNESS_NEVER_RUN


def test_unknown_source_name_is_ignored():
    now = 1_700_000_000.0
    rows = [
        {"source_name": "nonexistent_source", "status": "OK",
         "timestamp_utc": _iso(now - 1800)},
        {"source_name": "polymarket", "status": "OK",
         "timestamp_utc": _iso(now - 1800)},
    ]
    result = lsr.compute_source_freshness(rows, cadence_hours=6, now_epoch=now)
    # Unknown sources are not invented into the registry
    assert "nonexistent_source" not in result
    assert result["polymarket"]["freshness_state"] == lsr.FRESHNESS_FRESH
