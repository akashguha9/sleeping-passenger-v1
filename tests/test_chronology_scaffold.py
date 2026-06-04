"""Gap 3: chronology designed-table scaffold + fail-closed detectors.

Verifies the additive v1 tables exist alongside v0 tables, that the scaffold
inserts are fail-closed, and that every T1–T4 detector reports unavailable
(no synthetic fallback). Does NOT assert any chronology *capability* — that is
deliberately observation-gated.
"""

from pathlib import Path

import pytest

from scripts import chronology_detectors as det
from scripts import chronology_store as cs


def _conn(tmp_path: Path):
    conn = cs.get_connection(tmp_path / "chron.db")
    cs.init_schema(conn)
    return conn


def test_designed_tables_exist_alongside_v0(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        tables = set(cs.list_tables(conn))
        # v0 preserved
        assert {"observations", "snapshots"} <= tables
        # v1 designed scaffold present
        assert {"signal_candidates", "chronology_events", "pattern_hit_rates"} <= tables
    finally:
        conn.close()


def test_designed_tables_start_empty(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        for table in ("signal_candidates", "chronology_events", "pattern_hit_rates"):
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0  # nothing populates them yet
    finally:
        conn.close()


def test_scaffold_inserts_are_fail_closed(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        with pytest.raises(ValueError):
            cs.log_signal_candidate(conn, {"ticker": "AAPL"})  # missing keys
        with pytest.raises(ValueError):
            cs.log_chronology_event(conn, {"candidate_id": "c1"})  # missing keys
        with pytest.raises(ValueError):
            cs.upsert_pattern_hit_rate(conn, {"pattern_id": "p1"})  # missing counts
    finally:
        conn.close()


def test_pattern_hit_rate_never_fabricated_with_zero_observations(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        cs.upsert_pattern_hit_rate(
            conn, {"pattern_id": "p1", "observations_count": 0, "hits_count": 0}
        )
        rate = conn.execute(
            "SELECT hit_rate FROM pattern_hit_rates WHERE pattern_id='p1'"
        ).fetchone()[0]
        assert rate is None  # no fake rate from zero observations
    finally:
        conn.close()


def test_detector_readiness_all_four_implemented() -> None:
    summary = det.detector_readiness_summary()
    # T1-T4 are all implemented (observation-only, fail-closed).
    assert summary["implemented_count"] == 4
    assert summary["any_detector_available"] is True
    assert summary["total_detectors"] == 4
    assert summary["detectors"]["T1_event_prior"] == "INSUFFICIENT_DATA"


def test_t2_t3_t4_implemented_and_fail_closed_on_no_args() -> None:
    # Implemented (available) but fail CLOSED (not detected) when given no data.
    for fn, expect_status in (
        (det.detect_t2_asset_attachment, "INSUFFICIENT_DATA"),
        (det.detect_t3_commitment, "INSUFFICIENT_DATA"),
        (det.detect_t4_market_confirmation, "OUTCOME_PENDING"),
    ):
        result = fn()
        assert result.available is True
        assert result.detected is False
        assert result.status == expect_status


def test_t1_no_arg_call_fails_closed() -> None:
    # Called with no observation -> implemented but INSUFFICIENT_DATA (no fire).
    result = det.detect_t1_event_prior()
    assert result.available is True
    assert result.detected is False
    assert result.status == "INSUFFICIENT_DATA"
