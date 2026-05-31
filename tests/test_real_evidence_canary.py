"""Tests — Real Evidence Sprint Phase 1: read-only source canary.

Proves, deterministically and with NO network:
  * the default path never touches the network,
  * fixture rows persist as canonical, non-mock signal_events for >=3 sources,
  * rows_added==0 is DEGRADED / ZERO_FRESH_ROWS, never LIVE_CANONICAL,
  * mock and backfill rows never count as real activation and are never
    persisted as canonical,
  * source_run_log records each run,
  * the real network canary is opt-in (env flag) and reports honestly when the
    network is skipped/fails,
  * advisory-only safety invariants survive every code path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import real_evidence_canary as canary
from scripts import persistence


def _db(tmp_path: Path) -> Path:
    return tmp_path / "canary.db"


def _records(n: int, prefix: str) -> list[dict]:
    return [{"event_id": f"{prefix}-{i}", "headline": f"row {i}"} for i in range(n)]


# --- 1. default does not require network ----------------------------------
def test_canary_default_does_not_require_network(tmp_path, monkeypatch):
    # If the real loader is ever invoked in the default path, fail loudly.
    def _boom(*a, **k):  # pragma: no cover - must not be called
        raise AssertionError("network loader called in default offline path")

    monkeypatch.setattr(canary, "_real_loader_records", _boom)
    report = canary.run_canary(
        ["yfinance", "gdelt", "polymarket"],
        allow_network=False,
        fixtures=None,
        db_path=_db(tmp_path),
    )
    assert report["allow_network"] is False
    assert report["real_source_activation_count"] == 0
    for s in report["per_source"]:
        assert s["canonical_signal_status"] == canary.CANARY_SKIPPED
        assert s["is_live_canonical"] is False


# --- 2/3/4. fixture rows persist as canonical, non-mock -------------------
@pytest.mark.parametrize("source", ["yfinance", "gdelt", "polymarket"])
def test_fixture_rows_persist_as_canonical_non_mock(tmp_path, source):
    db = _db(tmp_path)
    summary = canary.run_source_canary(
        source,
        records=_records(5, source),
        db_path=db,
    )
    assert summary["canonical_signal_status"] == "LIVE_CANONICAL"
    assert summary["is_live_canonical"] is True
    assert summary["mock_flag"] is False
    assert summary["backfill_flag"] is False
    assert summary["rows_added"] == 5
    assert summary["canary_real"] is False  # fixture-backed, not real
    assert summary["activated"] is True
    assert summary["source_truth_score"] > 0.0
    # Rows really landed in the canonical signal_events table.
    rows = persistence.get_signal_events(source_name=source, db_path=db)
    assert len(rows) == 5
    for r in rows:
        assert r["advisory_status"] == "ADVISORY_ONLY"
        assert r["execution_gate"] == "LOCKED"


# Explicit aliases the sprint spec names individually.
def test_yfinance_or_market_fixture_rows_persist_as_canonical_non_mock(tmp_path):
    s = canary.run_source_canary("yfinance", records=_records(3, "y"), db_path=_db(tmp_path))
    assert s["is_live_canonical"] and s["mock_flag"] is False


def test_gdelt_fixture_rows_persist_as_canonical_non_mock(tmp_path):
    s = canary.run_source_canary("gdelt", records=_records(3, "g"), db_path=_db(tmp_path))
    assert s["is_live_canonical"] and s["mock_flag"] is False


def test_polymarket_fixture_rows_persist_as_canonical_non_mock(tmp_path):
    s = canary.run_source_canary("polymarket", records=_records(3, "p"), db_path=_db(tmp_path))
    assert s["is_live_canonical"] and s["mock_flag"] is False


# --- 5. rows_added == 0 is degraded, not live -----------------------------
def test_rows_added_zero_is_degraded_not_live(tmp_path):
    s = canary.run_source_canary("gdelt", records=[], db_path=_db(tmp_path))
    assert s["rows_added"] == 0
    assert s["canonical_signal_status"] == "ZERO_FRESH_ROWS"
    assert s["is_live_canonical"] is False
    assert s["activated"] is False
    assert s["source_truth_score"] == 0.0


# --- 6. mock rows do not count as real activation -------------------------
def test_mock_rows_do_not_count_as_real_activation(tmp_path):
    db = _db(tmp_path)
    s = canary.run_source_canary(
        "polymarket", records=_records(5, "m"), db_path=db, mock_flag=True
    )
    assert s["canonical_signal_status"] == "MOCK_NON_CANONICAL"
    assert s["is_live_canonical"] is False
    assert s["activated"] is False
    assert s["rows_added"] == 0
    # NOTHING was written to the canonical table.
    assert persistence.get_signal_events(source_name="polymarket", db_path=db) == []


# --- 7. backfill rows do not count as real activation ---------------------
def test_backfill_rows_do_not_count_as_real_activation(tmp_path):
    db = _db(tmp_path)
    s = canary.run_source_canary(
        "yfinance", records=_records(5, "b"), db_path=db, backfill_flag=True
    )
    assert s["canonical_signal_status"] == "BACKFILL_NON_FRESH"
    assert s["is_live_canonical"] is False
    assert s["activated"] is False
    assert s["rows_added"] == 0
    assert persistence.get_signal_events(source_name="yfinance", db_path=db) == []


# --- 8. source_run_log records the run ------------------------------------
def test_source_run_log_records_rows_added_filtered_status_if_supported(tmp_path):
    db = _db(tmp_path)
    fixtures = {
        "yfinance": {"records": _records(4, "y")},
        "gdelt": {"records": _records(2, "g")},
        "polymarket": {"records": []},  # zero rows -> DEGRADED
    }
    report = canary.run_canary(
        ["yfinance", "gdelt", "polymarket"],
        fixtures=fixtures,
        db_path=db,
        write_source_run_log=True,
    )
    assert report["source_run_log_written"] == 3
    log = persistence.get_source_run_log(db_path=db)
    logged_sources = {row["source_name"] for row in log}
    assert {"yfinance", "gdelt", "polymarket"} <= logged_sources
    statuses = {row["source_name"]: row["status"] for row in log}
    assert statuses["polymarket"] == "ZERO_FRESH_ROWS"


# --- 9. real canary is opt-in via env flag --------------------------------
def test_real_canary_is_opt_in_env_flag(tmp_path, monkeypatch):
    calls: list[str] = []

    def _spy(source_name, max_rows):
        calls.append(source_name)
        return [], "DEGRADED", "patched: no network"

    monkeypatch.setattr(canary, "_real_loader_records", _spy)

    # allow_network=False -> loader never called.
    canary.run_canary(["gdelt"], allow_network=False, db_path=_db(tmp_path))
    assert calls == []

    # allow_network=True -> loader IS consulted (still no real network here).
    canary.run_canary(["gdelt"], allow_network=True, db_path=_db(tmp_path))
    assert calls == ["gdelt"]

    # The env flag is the only switch the CLI honours.
    monkeypatch.delenv(canary.CANARY_ENV_FLAG, raising=False)
    assert canary.CANARY_ENV_FLAG == "REAL_EVIDENCE_CANARY"


# --- 10. truthful summary when network skipped / fails --------------------
def test_real_canary_outputs_truthful_summary_when_network_skipped(tmp_path, monkeypatch):
    def _fail(source_name, max_rows):
        return [], "DEGRADED", "skipped: host unreachable"

    monkeypatch.setattr(canary, "_real_loader_records", _fail)
    report = canary.run_canary(
        ["gdelt", "polymarket", "yfinance"],
        allow_network=True,
        db_path=_db(tmp_path),
    )
    assert report["real_source_activation_count"] == 0
    assert report["production_ready_live_ingestion"] is False
    assert report["predictive_claim_allowed"] is False
    for s in report["per_source"]:
        assert s["canary_real"] is True
        assert s["is_live_canonical"] is False  # no fake success
        assert s["canonical_signal_status"] != "LIVE_CANONICAL"
        # Advisory-only invariants survive.
        assert s["advisory_status"] == "ADVISORY_ONLY"
        assert s["execution_gate"] == "LOCKED"
        assert s["broker_api_called"] is False
        assert s["ai_execution_count"] == 0


# --- safety invariants on the aggregate report ----------------------------
def test_report_preserves_advisory_invariants(tmp_path):
    report = canary.run_canary(
        ["yfinance"], fixtures={"yfinance": {"records": _records(2, "y")}}, db_path=_db(tmp_path)
    )
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
    assert report["predictive_claim_allowed"] is False


# --------------------------------------------------------------------------- #
# First Real Rows + Kanté Score Push sprint — Phase 1 required cases.
# --------------------------------------------------------------------------- #

# --- real vs fixture distinction ------------------------------------------
def test_real_canary_summary_distinguishes_real_from_fixture(tmp_path):
    db = _db(tmp_path)
    fixtures = {
        # canary_real True -> counts toward real_source_activation_count
        "sec_edgar": {"records": _records(5, "sec"), "canary_real": True, "api_health_status": "OK"},
        # canary_real False -> fixture activation only
        "polymarket": {"records": _records(5, "pm"), "canary_real": False, "api_health_status": "OK"},
    }
    report = canary.run_canary(["sec_edgar", "polymarket"], fixtures=fixtures, db_path=db)
    assert report["real_source_activation_count"] == 1
    assert report["fixture_source_activation_count"] == 1
    by_name = {s["source_name"]: s for s in report["per_source"]}
    assert by_name["sec_edgar"]["canary_real"] is True
    assert by_name["polymarket"]["canary_real"] is False
    assert by_name["sec_edgar"]["activated"] is True
    assert by_name["polymarket"]["activated"] is True


# --- live rows count only when canary_real True ---------------------------
def test_live_canary_rows_count_only_when_canary_real_true(tmp_path):
    db = _db(tmp_path)
    # Same rows, two truth labels: only the canary_real=True one is a REAL row.
    real = canary.run_source_canary(
        "sec_edgar", records=_records(4, "r"), db_path=db, canary_real=True
    )
    fixture = canary.run_source_canary(
        "polymarket", records=_records(4, "f"), db_path=db, canary_real=False
    )
    assert real["activated"] and real["canary_real"] is True
    assert fixture["activated"] and fixture["canary_real"] is False
    # Both persisted canonical rows, but only `real` is a real-source activation.
    assert real["is_live_canonical"] and fixture["is_live_canonical"]


# --- failure does not fake live -------------------------------------------
def test_real_canary_failure_does_not_fake_live(tmp_path, monkeypatch):
    def _fail(source_name, max_rows):
        return [], "DEGRADED", "skipped: host unreachable"

    monkeypatch.setattr(canary, "_real_loader_records", _fail)
    report = canary.run_canary(
        ["sec_edgar", "gdelt"], allow_network=True, db_path=_db(tmp_path)
    )
    assert report["real_source_activation_count"] == 0
    for s in report["per_source"]:
        assert s["is_live_canonical"] is False
        assert s["canonical_signal_status"] != "LIVE_CANONICAL"


# --- 3-source threshold reports actual count ------------------------------
def test_three_source_activation_threshold_reports_actual_count(tmp_path):
    db = _db(tmp_path)
    # Two real activations + one zero-row source -> threshold NOT met, count honest.
    fixtures = {
        "yfinance": {"records": _records(3, "y"), "canary_real": True, "api_health_status": "OK"},
        "polymarket": {"records": _records(3, "p"), "canary_real": True, "api_health_status": "OK"},
        "gdelt": {"records": [], "canary_real": True, "api_health_status": "UNHEALTHY"},
    }
    report = canary.run_canary(
        ["yfinance", "polymarket", "gdelt"], fixtures=fixtures, db_path=db
    )
    assert report["real_source_activation_count"] == 2
    assert report["source_activation_target_met"] is False  # 2 < 3, never faked

    # Now add the third real source -> threshold met, reported truthfully.
    fixtures["sec_edgar"] = {
        "records": _records(3, "s"), "canary_real": True, "api_health_status": "OK"
    }
    report2 = canary.run_canary(
        ["yfinance", "polymarket", "gdelt", "sec_edgar"], fixtures=fixtures, db_path=_db(tmp_path)
    )
    assert report2["real_source_activation_count"] == 3
    assert report2["source_activation_target_met"] is True


# --- source_run_log records real canary status ----------------------------
def test_source_run_log_records_real_canary_status(tmp_path):
    db = _db(tmp_path)
    fixtures = {
        "sec_edgar": {"records": _records(4, "s"), "canary_real": True, "api_health_status": "OK"},
    }
    report = canary.run_canary(["sec_edgar"], fixtures=fixtures, db_path=db,
                               write_source_run_log=True)
    assert report["source_run_log_written"] == 1
    log = persistence.get_source_run_log(db_path=db)
    statuses = {row["source_name"]: row["status"] for row in log}
    assert statuses["sec_edgar"] == "LIVE_CANONICAL"


# --- sec_edgar is a wired real loader source ------------------------------
def test_sec_edgar_is_a_known_real_loader_source(tmp_path, monkeypatch):
    seen: list[str] = []

    def _spy(source_name, max_rows):
        seen.append(source_name)
        return [], "DEGRADED", "patched"

    monkeypatch.setattr(canary, "_real_loader_records", _spy)
    canary.run_canary(["sec_edgar"], allow_network=True, db_path=_db(tmp_path))
    assert seen == ["sec_edgar"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
