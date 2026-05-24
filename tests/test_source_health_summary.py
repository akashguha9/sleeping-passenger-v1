"""
Tests for the source-health classifier, sanitizer, and summary builder.

Covers:
  1. classify_source_status maps known statuses to severities/categories.
  2. CREDITS_EXHAUSTED detection on HTTP 402 / "credit" error messages.
  3. RATE_LIMITED detection on HTTP 429.
  4. AUTH_ERROR detection on HTTP 401/403.
  5. PLACEHOLDER is info-level, not warning.
  6. Sanitizer redacts api_key/token/secret patterns and trims long text.
  7. Source-health summary preserves advisory invariants.
  8. Persistence helpers: get_latest_source_run_per_source, count_signal_events_by_source.

The pure classifier/sanitizer/summary logic lives in
``scripts.source_health_summary`` so these tests do not require FastAPI to
run.  An additional ``_api()`` helper exists for the API wrapper checks at
the bottom of the file; it skips cleanly when FastAPI is unavailable.
"""
from __future__ import annotations

import json
import sqlite3

import pytest


def _srv():
    """Pure source-health module (no FastAPI dependency)."""
    import scripts.source_health_summary as srv
    return srv


def _api():
    """FastAPI wrapper; skip caller if FastAPI is not installed."""
    try:
        import fastapi  # noqa: F401
    except ImportError:
        pytest.skip("fastapi not installed")
    import scripts.api_server as srv
    return srv


def _p():
    import scripts.persistence as p
    return p


# ---------------------------------------------------------------------------
# 1. Classifier
# ---------------------------------------------------------------------------


def test_classifier_known_statuses():
    srv = _srv()
    assert srv.classify_source_status("OK", "", "")["severity"] == "ok"
    assert srv.classify_source_status("OK_FILTERED", "", "")["severity"] == "ok"
    assert srv.classify_source_status("PLACEHOLDER", "", "")["severity"] == "info"
    assert srv.classify_source_status("PLACEHOLDER", "", "")["category"] == "PLACEHOLDER"
    assert srv.classify_source_status("RATE_LIMITED", "", "")["severity"] == "warning"
    assert srv.classify_source_status("TIMEOUT", "", "")["severity"] == "warning"
    assert srv.classify_source_status("ERROR", "", "")["severity"] == "error"


def test_classifier_credits_exhausted_402():
    srv = _srv()
    c = srv.classify_source_status("HTTP_ERROR", "", "HTTP 402 credits depleted")
    assert c["category"] == "CREDITS_EXHAUSTED"
    assert c["severity"] == "warning"


def test_classifier_credits_exhausted_error_keyword():
    srv = _srv()
    c = srv.classify_source_status("ERROR", "", "xAI credits exhausted for account")
    assert c["category"] == "CREDITS_EXHAUSTED"


def test_classifier_rate_limit_http_429():
    srv = _srv()
    c = srv.classify_source_status("HTTP_ERROR", "", "HTTP 429 too many requests")
    assert c["category"] == "RATE_LIMITED"
    assert c["severity"] == "warning"


def test_classifier_auth_error_http_401():
    srv = _srv()
    c = srv.classify_source_status("HTTP_ERROR", "", "HTTP 401 unauthorized")
    assert c["category"] == "AUTH_ERROR"


def test_classifier_skipped_missing_api_key():
    srv = _srv()
    c = srv.classify_source_status("SKIPPED", "missing api_key in env", "")
    assert c["category"] == "MISSING_API_KEY"


# ---------------------------------------------------------------------------
# 2. Sanitizer
# ---------------------------------------------------------------------------


def test_sanitizer_redacts_api_key():
    srv = _srv()
    cleaned = srv.sanitize_error_text("Failed: api_key=sk-secret-12345 bad token")
    assert "sk-secret-12345" not in cleaned
    assert "<redacted>" in cleaned


def test_sanitizer_redacts_bearer_and_secret():
    srv = _srv()
    cleaned = srv.sanitize_error_text("Authorization: Bearer ABC.DEF.HIJ secret=xyz")
    assert "ABC.DEF.HIJ" not in cleaned
    assert "xyz" not in cleaned


def test_sanitizer_truncates_long_text():
    srv = _srv()
    cleaned = srv.sanitize_error_text("x" * 1000)
    assert len(cleaned) <= 241


# ---------------------------------------------------------------------------
# 3. Persistence helpers
# ---------------------------------------------------------------------------


def test_get_latest_source_run_per_source_returns_one_row_per_source(tmp_path):
    p = _p()
    db = tmp_path / "sh.db"
    p.init_schema(db)

    # log multiple runs for the same source — latest should win
    p.log_source_run("gdelt", "TIMEOUT", 0, "", "timeout", "2026-05-12T00:00:00Z", 1500, db_path=db)
    p.log_source_run("gdelt", "RATE_LIMITED", 0, "", "HTTP 429", "2026-05-12T00:10:00Z", 1700, db_path=db)
    p.log_source_run(
        "grok_xai", "HTTP_ERROR", 0, "",
        "HTTP 402 credits exhausted", "2026-05-12T00:05:00Z", 800, db_path=db,
    )
    p.log_source_run(
        "asia_disclosure", "PLACEHOLDER", 0, "not implemented", "",
        "2026-05-12T00:00:00Z", 0, db_path=db,
    )

    rows = p.get_latest_source_run_per_source(db_path=db)
    by_source = {r["source_name"]: r for r in rows}
    assert "gdelt" in by_source
    assert "grok_xai" in by_source
    assert "asia_disclosure" in by_source
    assert by_source["gdelt"]["status"] == "RATE_LIMITED"  # newer beat the earlier TIMEOUT


def test_count_signal_events_by_source(tmp_path):
    p = _p()
    db = tmp_path / "events.db"
    p.init_schema(db)
    p.insert_signal_event("EV_1", "gdelt", {"title": "x"}, "2026-05-12T00:00:00Z", db_path=db)
    p.insert_signal_event("EV_2", "gdelt", {"title": "y"}, "2026-05-12T00:00:00Z", db_path=db)
    p.insert_signal_event("EV_3", "polymarket", {"title": "z"}, "2026-05-12T00:00:00Z", db_path=db)

    counts = p.count_signal_events_by_source(db_path=db)
    assert counts.get("gdelt") == 2
    assert counts.get("polymarket") == 1


# ---------------------------------------------------------------------------
# 4. Endpoint shape + advisory invariants
# ---------------------------------------------------------------------------


def test_source_health_summary_advisory_invariants():
    srv = _srv()
    # Pure builder with empty inputs — confirms invariants survive empty state.
    result = srv.build_source_health_summary([], {})
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_mode"] == "HUMAN_ONLY"
    assert result["ai_execution_count"] == 0
    assert result["human_review_required"] is True
    assert "sources" in result
    assert isinstance(result["sources"], list)
    # All configured sources should be reported as NO_RUNS when no rows exist.
    by_source = {s["source_name"]: s for s in result["sources"]}
    assert "asia_disclosure" in by_source
    assert by_source["asia_disclosure"]["category"] == "NO_RUNS"


def test_source_health_summary_includes_known_source_labels(tmp_path):
    srv = _srv()
    p = _p()
    db = tmp_path / "sh.db"
    p.init_schema(db)

    p.log_source_run(
        "gdelt", "RATE_LIMITED", 0, "", "HTTP 429",
        "2026-05-12T00:00:00Z", 1000, db_path=db,
    )
    p.log_source_run(
        "asia_disclosure", "PLACEHOLDER", 0, "not implemented", "",
        "2026-05-12T00:00:00Z", 0, db_path=db,
    )
    p.log_source_run(
        "grok_xai", "HTTP_ERROR", 0, "",
        "HTTP 402 credits depleted",
        "2026-05-12T00:00:00Z", 500, db_path=db,
    )

    latest_rows = p.get_latest_source_run_per_source(db_path=db)
    event_counts = p.count_signal_events_by_source(db_path=db)
    result = srv.build_source_health_summary(latest_rows, event_counts)
    by_source = {s["source_name"]: s for s in result["sources"]}

    assert by_source["gdelt"]["category"] == "RATE_LIMITED"
    assert by_source["gdelt"]["severity"] == "warning"

    assert by_source["asia_disclosure"]["category"] == "PLACEHOLDER"
    assert by_source["asia_disclosure"]["severity"] == "info"
    # Placeholder copy should be source-specific, not generic.
    assert "Asia Disclosure" in by_source["asia_disclosure"]["human_message"]
    assert "PLACEHOLDER" in by_source["asia_disclosure"]["human_message"]

    assert by_source["grok_xai"]["category"] == "CREDITS_EXHAUSTED"
    assert by_source["grok_xai"]["severity"] == "warning"

    for entry in result["sources"]:
        # safety: human_message must not leak the raw error verbatim
        assert "<redacted>" not in entry["human_message"]
        assert "label" in entry and entry["label"]


def test_source_health_summary_counts_warnings():
    srv = _srv()
    out = srv.build_source_health_summary([], {})
    # Even when empty, count fields exist with correct types
    assert isinstance(out.get("warning_count"), int)
    assert isinstance(out.get("error_count"), int)
    assert isinstance(out.get("ok_count"), int)


def test_no_runs_message_uses_phase2_command_for_asia_disclosure():
    """Asia Disclosure runs through run_live_sources_phase2.py — make sure
    the NO_RUNS hint never points at the legacy live_source_runner script.
    """
    srv = _srv()
    result = srv.build_source_health_summary([], {})
    by_source = {s["source_name"]: s for s in result["sources"]}
    asia = by_source["asia_disclosure"]
    assert asia["category"] == "NO_RUNS"
    assert "run_live_sources_phase2.py" in asia["human_message"]
    assert "--source asia_disclosure" in asia["human_message"]
    assert "live_source_runner.py" not in asia["human_message"]


def test_no_runs_message_uses_phase1_command_for_gdelt():
    """GDELT is a Phase 1 source — the CLI hint must use phase1."""
    srv = _srv()
    result = srv.build_source_health_summary([], {})
    by_source = {s["source_name"]: s for s in result["sources"]}
    gdelt = by_source["gdelt"]
    assert gdelt["category"] == "NO_RUNS"
    assert "run_live_sources_phase1.py" in gdelt["human_message"]
    assert "--source gdelt" in gdelt["human_message"]


def test_api_wrapper_returns_same_invariants():
    """The FastAPI wrapper layer should re-export the same advisory shape.

    Skipped when FastAPI is unavailable (e.g. minimal CI without dev deps).
    """
    srv = _api()
    result = srv._get_source_health_summary()
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_mode"] == "HUMAN_ONLY"
    assert result["ai_execution_count"] == 0
    assert result["human_review_required"] is True
    assert isinstance(result.get("sources"), list)


# ---------------------------------------------------------------------------
# Prediction-market disagreement source-health surface
# ---------------------------------------------------------------------------


def test_disagreement_source_appears_in_health_summary_as_never_run():
    srv = _srv()
    result = srv.build_source_health_summary([], {})
    by_source = {s["source_name"]: s for s in result["sources"]}
    assert "prediction_market_disagreement" in by_source, (
        "prediction_market_disagreement should appear with NO_RUNS state when "
        "the scanner has never run"
    )
    entry = by_source["prediction_market_disagreement"]
    assert entry["category"] == "NO_RUNS"
    assert entry["severity"] == "info"
    assert entry["label"] == "Prediction Market Disagreement"
    # Suggested command is the scanner script itself, never phase1/phase2.
    assert "prediction_market_disagreement_scanner.py" in entry["suggested_command"]
    assert "run_live_sources_phase" not in entry["suggested_command"]


def test_disagreement_source_after_scanner_run_uses_log_row(tmp_path):
    srv = _srv()
    p = _p()
    db = tmp_path / "sh_disagreement.db"
    p.init_schema(db)
    p.log_source_run(
        "prediction_market_disagreement",
        "OK",
        3,
        '{"triggered_count": 1, "embedding_provider": "deterministic"}',
        "",
        "2026-05-24T00:00:00Z",
        420,
        db_path=db,
    )
    latest = p.get_latest_source_run_per_source(db_path=db)
    counts = p.count_signal_events_by_source(db_path=db)
    result = srv.build_source_health_summary(latest, counts)
    by_source = {s["source_name"]: s for s in result["sources"]}
    entry = by_source["prediction_market_disagreement"]
    assert entry["status"] == "OK"
    assert entry["category"] == "OK"
    assert entry["fetched_count"] == 3


def test_disagreement_source_in_compute_source_freshness():
    """The freshness map (used by /live-sources/status) should include the
    disagreement source so the frontend never-run/stale/healthy banner
    can render an honest state for the Disagreements tab.
    """
    from scripts.live_source_registry import (
        ALL_SOURCE_KEYS,
        compute_source_freshness,
    )

    assert "prediction_market_disagreement" in ALL_SOURCE_KEYS

    freshness = compute_source_freshness(latest_runs=None, env={})
    assert "prediction_market_disagreement" in freshness
    entry = freshness["prediction_market_disagreement"]
    assert entry["advisory_status"] == "ADVISORY_ONLY"
    assert entry["execution_gate"] == "LOCKED"
    assert entry["broker_api_called"] is False
    assert entry["ai_execution_count"] == 0
    assert entry["execution_permission"] is False
    assert entry["can_execute"] is False
    assert entry["freshness_state"] == "never_run"


def test_disagreement_source_is_advisory_only_in_registry():
    from scripts.live_source_registry import get_source_family

    entry = get_source_family("prediction_market_disagreement")
    assert entry["display_name"] == "Prediction Market Disagreement"
    assert entry["advisory_only"] is True
    assert entry["can_execute"] is False
    assert entry["requires_api_key"] is False
    # No broker/trading keywords leaked into operator-visible fields.
    flat = (
        " ".join(
            [
                str(entry.get("notes", "")),
                str(entry.get("tos_warning", "")),
                str(entry.get("display_name", "")),
            ]
        )
    ).lower()
    for forbidden in ("buy ", " sell ", "place order", "broker_api"):
        assert forbidden not in flat


# ---------------------------------------------------------------------------
# Parent Kalshi source-health surface — closeout-sprint coverage
# ---------------------------------------------------------------------------


def test_classifier_ok_empty_status() -> None:
    """OK_EMPTY (adapter responded but returned zero markets) must read as
    healthy and quiet — distinct from OK_FILTERED."""
    srv = _srv()
    c = srv.classify_source_status("OK_EMPTY", "", "")
    assert c["severity"] == "ok"
    assert c["category"] == "OK_EMPTY"
    assert "no markets" in c["human_message"].lower()


def test_kalshi_appears_as_never_run_until_first_run() -> None:
    """Kalshi must show up in source-health before any run is recorded."""
    srv = _srv()
    result = srv.build_source_health_summary([], {})
    by_source = {s["source_name"]: s for s in result["sources"]}
    assert "kalshi" in by_source
    entry = by_source["kalshi"]
    assert entry["label"] == "Kalshi"
    assert entry["category"] == "NO_RUNS"
    assert entry["severity"] == "info"
    # CLI hint must point at the live source runner with the kalshi flag.
    assert "--source kalshi" in entry["suggested_command"]
    assert "run_live_sources_phase" in entry["suggested_command"]


def test_kalshi_ok_run_surfaces_as_healthy(tmp_path) -> None:
    srv = _srv()
    p = _p()
    db = tmp_path / "kalshi_health.db"
    p.init_schema(db)
    p.log_source_run(
        "kalshi", "ok", 2, "", "", "2026-05-24T01:00:00Z", 150, db_path=db
    )
    latest = p.get_latest_source_run_per_source(db_path=db)
    result = srv.build_source_health_summary(latest, p.count_signal_events_by_source(db_path=db))
    by_source = {s["source_name"]: s for s in result["sources"]}
    entry = by_source["kalshi"]
    assert entry["severity"] == "ok"
    assert entry["category"] == "OK"
    assert entry["fetched_count"] == 2
    assert entry["duration_ms"] == 150


def test_kalshi_ok_filtered_run_remains_healthy(tmp_path) -> None:
    """A run where every fetched row was rejected by the allowlist must
    still read as healthy, with a category that explains the filter."""
    srv = _srv()
    p = _p()
    db = tmp_path / "kalshi_filtered.db"
    p.init_schema(db)
    p.log_source_run(
        "kalshi", "OK_FILTERED", 10, "", "", "2026-05-24T02:00:00Z", 200, db_path=db
    )
    latest = p.get_latest_source_run_per_source(db_path=db)
    result = srv.build_source_health_summary(latest, {})
    entry = next(s for s in result["sources"] if s["source_name"] == "kalshi")
    assert entry["severity"] == "ok"
    assert entry["category"] == "OK_FILTERED"


def test_kalshi_ok_empty_run_remains_healthy(tmp_path) -> None:
    srv = _srv()
    p = _p()
    db = tmp_path / "kalshi_empty.db"
    p.init_schema(db)
    p.log_source_run(
        "kalshi", "OK_EMPTY", 0, "", "", "2026-05-24T03:00:00Z", 80, db_path=db
    )
    latest = p.get_latest_source_run_per_source(db_path=db)
    result = srv.build_source_health_summary(latest, {})
    entry = next(s for s in result["sources"] if s["source_name"] == "kalshi")
    assert entry["category"] == "OK_EMPTY"
    assert entry["severity"] == "ok"
    assert entry["fetched_count"] == 0


def test_kalshi_freshness_states_via_compute_source_freshness(tmp_path) -> None:
    """compute_source_freshness must transition Kalshi through
    never_run → fresh → stale → overdue based on the source_run_log."""
    from scripts.live_source_registry import compute_source_freshness

    p = _p()
    db = tmp_path / "kalshi_freshness.db"
    p.init_schema(db)

    # 1. No rows yet — Kalshi reads as never_run with the safety stamps.
    freshness = compute_source_freshness([], env={})
    assert "kalshi" in freshness
    entry = freshness["kalshi"]
    assert entry["freshness_state"] == "never_run"
    assert entry["advisory_status"] == "ADVISORY_ONLY"
    assert entry["execution_gate"] == "LOCKED"
    assert entry["broker_api_called"] is False
    assert entry["ai_execution_count"] == 0
    assert entry["can_execute"] is False

    # 2. Fresh recent OK → fresh.
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    recent = (now - _dt.timedelta(hours=1)).isoformat(timespec="seconds")
    fresh = compute_source_freshness(
        [{"source_name": "kalshi", "status": "OK", "timestamp_utc": recent}],
        cadence_hours=6,
    )
    assert fresh["kalshi"]["freshness_state"] == "fresh"

    # 3. Old OK → overdue.
    old = (now - _dt.timedelta(hours=72)).isoformat(timespec="seconds")
    overdue = compute_source_freshness(
        [{"source_name": "kalshi", "status": "OK", "timestamp_utc": old}],
        cadence_hours=6,
    )
    assert overdue["kalshi"]["freshness_state"] == "overdue"


def test_kalshi_registry_advisory_only_and_no_auth() -> None:
    """Registry contract: Kalshi is read-only, advisory-only, no API key
    required at the parent level (mock fixtures opt-in only)."""
    from scripts.live_source_registry import get_source_family

    entry = get_source_family("kalshi")
    assert entry["display_name"] == "Kalshi"
    assert entry["advisory_only"] is True
    assert entry["can_execute"] is False
    assert entry["requires_api_key"] is False
    flat = " ".join(
        [
            str(entry.get("notes", "")),
            str(entry.get("tos_warning", "")),
            str(entry.get("display_name", "")),
        ]
    ).lower()
    for forbidden in ("buy ", " sell ", "place order", "broker api call", "execute trade"):
        assert forbidden not in flat


def test_kalshi_runner_ok_empty_path(monkeypatch) -> None:
    """Direct contract: a Kalshi mock run with zero markets emits ok_empty."""
    from unittest.mock import MagicMock, patch
    from scripts.live_source_runner import run_phase1

    empty = {"markets": []}

    def _mock_resp(payload):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        return resp

    with patch("requests.get", return_value=_mock_resp(empty)):
        report = run_phase1(dry_run=True, sources=["kalshi"], kalshi_limit=5)

    ks = next(s for s in report.sources if s.source_name == "kalshi")
    assert ks.status == "ok_empty"
    assert ks.fetched_count == 0
    assert ks.accepted_count == 0


def test_kalshi_dry_run_does_not_log_source_run() -> None:
    """Dry-run must never call _log_run (no source_run_log row)."""
    from unittest.mock import MagicMock, patch
    from scripts.live_source_runner import run_phase1

    payload = {
        "markets": [
            {
                "ticker": "FED-CUT-JUN-2026",
                "title": "Will the Fed cut at the June meeting?",
                "category": "Economics",
                "yes_ask": 0.31,
            }
        ]
    }
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None

    with patch("requests.get", return_value=resp):
        with patch("scripts.live_source_runner._log_run") as mock_log:
            run_phase1(dry_run=True, sources=["kalshi"], kalshi_limit=5)
            mock_log.assert_not_called()
