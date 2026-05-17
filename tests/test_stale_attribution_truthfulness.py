"""Tests for honest stale-source attribution in /live-sources/status.

These tests pin down the contract that:

  * PLANNED_NOT_SCORED sources (e.g. ``asia_disclosure``) MUST NOT be
    counted in ``stale_sources`` and MUST carry ``is_stale=False`` even
    when their freshness_state is ``never_run``.
  * OPTIONAL_CONFIG_MISSING sources (e.g. ``etherscan`` / ``grok_xai``
    without keys) MUST NOT be counted as stale; they belong to the
    ``excluded_from_stale`` list instead, with reason
    ``optional_config_missing``.
  * Genuinely stale active sources (a core source with no successful
    refresh recorded) ARE counted in ``stale_sources``.
  * The response carries advisory-only safety stamps unchanged.
  * Refresh-attempt timestamps and source-event timestamps are separate
    fields — neither overrides the other.

No live API is ever called.  The persistence layer is pointed at an
isolated tmp DB so the test does not perturb runtime/mvp_local.db.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _isolated_db(tmp_path: Path, monkeypatch) -> Path:
    import scripts.persistence as p

    db = tmp_path / "stale_truth.db"
    monkeypatch.setattr(p, "DB_PATH", db)
    p.init_schema(db)
    return db


def _strip_live_keys(monkeypatch) -> None:
    """Remove every credential the registry probes so the test is hermetic."""
    for key in (
        "NEWS_API_KEY",
        "NEWSAPI_KEY",
        "EVENT_REGISTRY_API_KEY",
        "ETHERSCAN_API_KEY",
        "ETHERSCAN_ADDRESS",
        "ETHEREUM_ADDRESS",
        "PUBLIC_ETH_ADDRESS",
        "XAI_API_KEY",
        "GROK_API_KEY",
        "SEC_USER_AGENT",
        "SEC_DEFAULT_CIK",
        "SEC_DEFAULT_WATCHLIST",
        "SEC_USE_DEFAULT_WATCHLIST",
    ):
        monkeypatch.delenv(key, raising=False)


def test_planned_asia_disclosure_is_not_counted_as_stale(tmp_path, monkeypatch):
    """asia_disclosure is adapter_status=planned — never stale, even when never_run."""
    _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    assert "asia_disclosure" not in payload["stale_sources"]

    entry = payload["sources"]["asia_disclosure"]
    assert entry["adapter_status"] == "planned"
    assert entry["is_stale"] is False
    assert entry.get("stale_excluded_reason") == "planned_not_scored"
    assert "planned" in (entry.get("stale_reason") or "").lower()

    excluded = payload.get("excluded_from_stale") or []
    assert any(
        e.get("source") == "asia_disclosure" and e.get("reason") == "planned_not_scored"
        for e in excluded
    ), f"asia_disclosure missing from excluded_from_stale: {excluded!r}"


def test_optional_missing_config_is_not_counted_as_stale(tmp_path, monkeypatch):
    """etherscan/grok_xai are optional — missing keys is informational, not stale."""
    _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    assert "etherscan" not in payload["stale_sources"]
    assert "grok_xai" not in payload["stale_sources"]

    e_eth = payload["sources"]["etherscan"]
    e_grok = payload["sources"]["grok_xai"]
    assert e_eth["is_stale"] is False
    assert e_eth.get("stale_excluded_reason") == "optional_config_missing"
    assert e_grok["is_stale"] is False
    assert e_grok.get("stale_excluded_reason") == "optional_config_missing"

    excluded = payload.get("excluded_from_stale") or []
    excluded_keys = {(e.get("source"), e.get("reason")) for e in excluded}
    assert ("etherscan", "optional_config_missing") in excluded_keys
    assert ("grok_xai", "optional_config_missing") in excluded_keys


def test_genuinely_stale_active_core_source_is_flagged(tmp_path, monkeypatch):
    """A core source whose last successful refresh is older than the threshold
    must remain flagged as stale — the truth filter must not over-correct."""
    import scripts.persistence as p

    db = _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)
    p.log_source_run(
        source_name="polymarket",
        status="ok",
        fetched_count=10,
        skipped_reason="",
        error_message="",
        timestamp_utc="2026-05-11T17:00:00+00:00",
        duration_ms=5,
        db_path=db,
    )
    p.record_live_source_refresh_run(
        run_id="r1",
        source_name="polymarket",
        attempted=True,
        success=True,
        skipped=False,
        started_at="2026-05-11T17:00:00+00:00",
        finished_at="2026-05-11T17:00:01+00:00",
        duration_seconds=1.0,
        rows_before=0,
        rows_after=10,
        rows_added=10,
        db_path=db,
    )

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-14T17:00:00+00:00")
    assert "polymarket" in payload["stale_sources"]
    entry = payload["sources"]["polymarket"]
    assert entry["is_stale"] is True
    assert entry.get("stale_excluded_reason") is None
    assert "stale" in (entry.get("stale_reason") or "").lower() or "older" in (
        entry.get("stale_reason") or ""
    ).lower()


def test_refresh_success_and_source_event_timestamps_are_separate(
    tmp_path, monkeypatch
):
    """``last_refresh_success_at`` (refresh process) and ``last_success_at``
    (latest OK source_run_log row) must both be exposed independently."""
    import scripts.persistence as p

    db = _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)
    # Source event happened earlier than the refresh-process completion.
    p.log_source_run(
        source_name="polymarket",
        status="ok",
        fetched_count=5,
        skipped_reason="",
        error_message="",
        timestamp_utc="2026-05-17T16:55:00+00:00",
        duration_ms=2,
        db_path=db,
    )
    p.record_live_source_refresh_run(
        run_id="r1",
        source_name="polymarket",
        attempted=True,
        success=True,
        skipped=False,
        started_at="2026-05-17T16:54:00+00:00",
        finished_at="2026-05-17T16:55:30+00:00",
        duration_seconds=90.0,
        rows_before=0,
        rows_after=5,
        rows_added=5,
        db_path=db,
    )

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    entry = payload["sources"]["polymarket"]
    assert entry["last_success_at"] == "2026-05-17T16:55:00+00:00"
    assert entry["last_refresh_success_at"] == "2026-05-17T16:55:30+00:00"
    # Different fields, different concepts — both must be present.
    assert entry["last_success_at"] != entry["last_refresh_success_at"]


def test_advisory_invariants_preserved_in_payload(tmp_path, monkeypatch):
    """Stale-attribution changes must not weaken advisory-only stamps."""
    _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["execution_permission"] is False
    assert payload["can_execute"] is False
    assert payload["human_review_required"] is True

    for key, entry in payload["sources"].items():
        assert entry["advisory_status"] == "ADVISORY_ONLY", key
        assert entry["execution_gate"] == "LOCKED", key
        assert entry["broker_api_called"] is False, key
        assert entry["can_execute"] is False, key


def test_timezone_aware_utc_comparison(tmp_path, monkeypatch):
    """now_iso without explicit offset (interpreted UTC) must not flip a fresh
    source into stale.  Guards against naive-vs-aware comparison bugs."""
    import scripts.persistence as p

    db = _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)
    p.log_source_run(
        source_name="polymarket",
        status="ok",
        fetched_count=1,
        skipped_reason="",
        error_message="",
        timestamp_utc="2026-05-17T16:55:00+00:00",
        duration_ms=1,
        db_path=db,
    )
    p.record_live_source_refresh_run(
        run_id="r1",
        source_name="polymarket",
        attempted=True,
        success=True,
        skipped=False,
        started_at="2026-05-17T16:55:00+00:00",
        finished_at="2026-05-17T16:55:01+00:00",
        duration_seconds=1.0,
        rows_before=0,
        rows_after=1,
        rows_added=1,
        db_path=db,
    )

    from scripts.api_server import _build_live_sources_status

    # Naive ISO string — builder must coerce to UTC.
    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00")
    assert "polymarket" not in payload["stale_sources"]
    assert payload["sources"]["polymarket"]["is_stale"] is False


def test_no_execution_routes_introduced():
    """Sanity: this fix must not have added execution endpoints/methods."""
    from scripts import api_server

    forbidden_substrings = (
        "place_order",
        "submit_order",
        "broker_execute",
        "send_to_broker",
        "trade_execute",
    )
    src = Path(api_server.__file__).read_text(encoding="utf-8")
    for token in forbidden_substrings:
        assert token not in src, f"forbidden execution token introduced: {token}"
