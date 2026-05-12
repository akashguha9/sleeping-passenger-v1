"""
Tests for the /source-health/summary endpoint and its classifier.

Covers:
  1. _classify_source_status maps known statuses to severities/categories.
  2. CREDITS_EXHAUSTED detection on HTTP 402 / "credit" error messages.
  3. RATE_LIMITED detection on HTTP 429.
  4. AUTH_ERROR detection on HTTP 401/403.
  5. PLACEHOLDER is info-level, not warning.
  6. Sanitizer redacts api_key/token/secret patterns and trims long text.
  7. _get_source_health_summary returns advisory invariants.
  8. Persistence helpers: get_latest_source_run_per_source, count_signal_events_by_source.
"""
from __future__ import annotations

import json
import sqlite3


def _api():
    import scripts.api_server as srv
    return srv


def _p():
    import scripts.persistence as p
    return p


# ---------------------------------------------------------------------------
# 1. Classifier
# ---------------------------------------------------------------------------


def test_classifier_known_statuses():
    srv = _api()
    assert srv._classify_source_status("OK", "", "")["severity"] == "ok"
    assert srv._classify_source_status("OK_FILTERED", "", "")["severity"] == "ok"
    assert srv._classify_source_status("PLACEHOLDER", "", "")["severity"] == "info"
    assert srv._classify_source_status("PLACEHOLDER", "", "")["category"] == "PLACEHOLDER"
    assert srv._classify_source_status("RATE_LIMITED", "", "")["severity"] == "warning"
    assert srv._classify_source_status("TIMEOUT", "", "")["severity"] == "warning"
    assert srv._classify_source_status("ERROR", "", "")["severity"] == "error"


def test_classifier_credits_exhausted_402():
    srv = _api()
    c = srv._classify_source_status("HTTP_ERROR", "", "HTTP 402 credits depleted")
    assert c["category"] == "CREDITS_EXHAUSTED"
    assert c["severity"] == "warning"


def test_classifier_credits_exhausted_error_keyword():
    srv = _api()
    c = srv._classify_source_status("ERROR", "", "xAI credits exhausted for account")
    assert c["category"] == "CREDITS_EXHAUSTED"


def test_classifier_rate_limit_http_429():
    srv = _api()
    c = srv._classify_source_status("HTTP_ERROR", "", "HTTP 429 too many requests")
    assert c["category"] == "RATE_LIMITED"
    assert c["severity"] == "warning"


def test_classifier_auth_error_http_401():
    srv = _api()
    c = srv._classify_source_status("HTTP_ERROR", "", "HTTP 401 unauthorized")
    assert c["category"] == "AUTH_ERROR"


def test_classifier_skipped_missing_api_key():
    srv = _api()
    c = srv._classify_source_status("SKIPPED", "missing api_key in env", "")
    assert c["category"] == "MISSING_API_KEY"


# ---------------------------------------------------------------------------
# 2. Sanitizer
# ---------------------------------------------------------------------------


def test_sanitizer_redacts_api_key():
    srv = _api()
    cleaned = srv._sanitize_error_text("Failed: api_key=sk-secret-12345 bad token")
    assert "sk-secret-12345" not in cleaned
    assert "<redacted>" in cleaned


def test_sanitizer_redacts_bearer_and_secret():
    srv = _api()
    cleaned = srv._sanitize_error_text("Authorization: Bearer ABC.DEF.HIJ secret=xyz")
    assert "ABC.DEF.HIJ" not in cleaned
    assert "xyz" not in cleaned


def test_sanitizer_truncates_long_text():
    srv = _api()
    cleaned = srv._sanitize_error_text("x" * 1000)
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
    srv = _api()
    result = srv._get_source_health_summary()
    # Even if the DB is empty / missing, the response must keep these constants
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_mode"] == "HUMAN_ONLY"
    assert result["ai_execution_count"] == 0
    assert result["human_review_required"] is True
    assert "sources" in result
    assert isinstance(result["sources"], list)


def test_source_health_summary_includes_known_source_labels(tmp_path, monkeypatch):
    srv = _api()
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

    # Route the persistence helpers used by _get_source_health_summary at the
    # temp DB so we don't depend on whatever sits in the real runtime DB.
    original_latest = p.get_latest_source_run_per_source
    original_count = p.count_signal_events_by_source
    monkeypatch.setattr(
        p, "get_latest_source_run_per_source",
        lambda *a, **kw: original_latest(db_path=db),
    )
    monkeypatch.setattr(
        p, "count_signal_events_by_source",
        lambda *a, **kw: original_count(db_path=db),
    )

    result = srv._get_source_health_summary()
    by_source = {s["source_name"]: s for s in result["sources"]}

    assert by_source["gdelt"]["category"] == "RATE_LIMITED"
    assert by_source["gdelt"]["severity"] == "warning"

    assert by_source["asia_disclosure"]["category"] == "PLACEHOLDER"
    assert by_source["asia_disclosure"]["severity"] == "info"

    assert by_source["grok_xai"]["category"] == "CREDITS_EXHAUSTED"
    assert by_source["grok_xai"]["severity"] == "warning"

    for entry in result["sources"]:
        # safety: human_message must not leak the raw error verbatim
        assert "<redacted>" not in entry["human_message"]
        assert "label" in entry and entry["label"]


def test_source_health_summary_counts_warnings():
    srv = _api()
    out = srv._get_source_health_summary()
    # Even when empty, count fields exist with correct types
    assert isinstance(out.get("warning_count"), int)
    assert isinstance(out.get("error_count"), int)
    assert isinstance(out.get("ok_count"), int)
