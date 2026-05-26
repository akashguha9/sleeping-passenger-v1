"""Tests for :mod:`scripts.probability_snapshot`.

Full Role-Uplift Sprint, Phase 1.

These tests pin the probability snapshot math, the additive-only SQLite
schema migration, the dry-run-writes-nothing contract, the advisory
safety stamps, and the explicit
``predictive_claim_allowed=False`` marker that protects against
mistakenly treating an advisory snapshot as a calibrated claim.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import probability_snapshot as ps  # noqa: E402


# ---------------------------------------------------------------------------
# Pure math
# ---------------------------------------------------------------------------


def test_sigmoid_at_zero_is_half():
    assert ps.sigmoid(0.0) == pytest.approx(0.5)


@pytest.mark.parametrize("z", [-10.0, -1.0, 0.0, 1.0, 10.0])
def test_sigmoid_in_open_unit_interval(z):
    p = ps.sigmoid(z)
    assert 0.0 < p < 1.0


@pytest.mark.parametrize("z", [-1e6, -100.0, 100.0, 1e6])
def test_sigmoid_at_extremes_stays_in_closed_unit_interval(z):
    p = ps.sigmoid(z)
    assert 0.0 <= p <= 1.0


def test_axis_weights_sum_to_one():
    total = sum(ps.DEFAULT_AXIS_WEIGHTS[axis] for axis in ps.SCORE_AXES)
    assert math.isclose(total, 1.0, abs_tol=1e-9)


def test_raw_score_respects_weights():
    axes = {axis: 1.0 for axis in ps.SCORE_AXES}
    raw = ps.compute_raw_score(axes)
    # Σ w_i * 1.0 = 1.0; no penalties.
    assert raw == pytest.approx(1.0)


def test_raw_score_rejects_weights_that_do_not_sum_to_one():
    bad = {axis: 0.5 for axis in ps.SCORE_AXES}
    with pytest.raises(ValueError):
        ps.compute_raw_score({}, weights=bad)


def test_raw_score_rejects_negative_weights():
    bad = dict(ps.DEFAULT_AXIS_WEIGHTS)
    bad["EMS"] = -0.1
    bad["EQS"] = 1.0 / 6.0 + 0.1
    with pytest.raises(ValueError):
        ps.compute_raw_score({}, weights=bad)


def test_raw_score_rejects_negative_lambdas():
    with pytest.raises(ValueError):
        ps.compute_raw_score({}, lambda_chaos=-0.01)
    with pytest.raises(ValueError):
        ps.compute_raw_score({}, lambda_stale=-0.01)
    with pytest.raises(ValueError):
        ps.compute_raw_score({}, lambda_mock=-0.01)


def test_probability_clamped_to_unit_interval():
    p_low = ps.compute_model_probability(-1e6)
    p_high = ps.compute_model_probability(1e6)
    assert 0.0 <= p_low <= 1.0
    assert 0.0 <= p_high <= 1.0


def test_raw_score_clamped_to_safety_band():
    axes = {axis: 5.0 for axis in ps.SCORE_AXES}  # caller passed > 1
    raw = ps.compute_raw_score(axes)
    assert raw <= ps.RAW_SCORE_CLAMP
    raw_low = ps.compute_raw_score(
        {axis: 0.0 for axis in ps.SCORE_AXES},
        chaos_risk=1.0,
        staleness_penalty=1.0,
        mock_penalty=1.0,
        lambda_chaos=10.0,
        lambda_stale=10.0,
        lambda_mock=10.0,
    )
    assert raw_low >= -ps.RAW_SCORE_CLAMP


def test_mock_penalty_lowers_probability():
    axes = {axis: 0.5 for axis in ps.SCORE_AXES}
    raw_no_mock = ps.compute_raw_score(axes, mock_penalty=0.0)
    raw_with_mock = ps.compute_raw_score(axes, mock_penalty=1.0)
    assert raw_with_mock < raw_no_mock
    p_no_mock = ps.compute_model_probability(raw_no_mock)
    p_with_mock = ps.compute_model_probability(raw_with_mock)
    assert p_with_mock < p_no_mock


def test_staleness_penalty_lowers_probability():
    axes = {axis: 0.5 for axis in ps.SCORE_AXES}
    raw_fresh = ps.compute_raw_score(axes, staleness_penalty=0.0)
    raw_stale = ps.compute_raw_score(axes, staleness_penalty=1.0)
    assert raw_stale < raw_fresh
    assert ps.compute_model_probability(raw_stale) < ps.compute_model_probability(
        raw_fresh
    )


def test_chaos_risk_lowers_probability():
    axes = {axis: 0.5 for axis in ps.SCORE_AXES}
    raw_calm = ps.compute_raw_score(axes, chaos_risk=0.0)
    raw_chaos = ps.compute_raw_score(axes, chaos_risk=1.0)
    assert raw_chaos < raw_calm
    assert ps.compute_model_probability(raw_chaos) < ps.compute_model_probability(
        raw_calm
    )


# ---------------------------------------------------------------------------
# Snapshot builder + advisory stamps
# ---------------------------------------------------------------------------


def test_build_probability_snapshot_carries_advisory_stamps():
    snap = ps.build_probability_snapshot(
        signal_id="sig-001",
        axes={axis: 0.5 for axis in ps.SCORE_AXES},
    )
    payload = snap.to_dict()
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0


def test_attach_probability_snapshot_to_signal_preserves_keys():
    snap = ps.build_probability_snapshot(
        signal_id="sig-002",
        axes={axis: 0.7 for axis in ps.SCORE_AXES},
    )
    signal = {"event_id": "sig-002", "thesis": "advisory-only"}
    out = ps.attach_probability_snapshot_to_signal(signal, snap)
    assert out["thesis"] == "advisory-only"
    assert out["probability_snapshot"]["signal_id"] == "sig-002"
    assert out["model_probability"] == pytest.approx(snap.model_probability)
    assert out["advisory_status"] == "ADVISORY_ONLY"
    assert out["execution_gate"] == "LOCKED"


# ---------------------------------------------------------------------------
# SQLite schema + insert behaviour
# ---------------------------------------------------------------------------


def _make_signal_events_db(db_path: Path, payloads: list[dict[str, object]]) -> None:
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE signal_events (
                id INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
                human_review_required INTEGER NOT NULL DEFAULT 1,
                execution_gate TEXT NOT NULL DEFAULT 'LOCKED',
                ai_execution_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        for i, payload in enumerate(payloads, start=1):
            cur.execute(
                "INSERT INTO signal_events (event_id, source_name, raw_payload, fetched_at) "
                "VALUES (?,?,?,?)",
                (
                    payload.get("event_id", f"sig-{i:03d}"),
                    payload.get("source_name", "grok_xai"),
                    json.dumps(payload),
                    payload.get("fetched_at", "2026-05-26T10:00:00+00:00"),
                ),
            )
        con.commit()
    finally:
        con.close()


def test_ensure_schema_is_additive_only(tmp_path):
    db = tmp_path / "mvp.db"
    _make_signal_events_db(db, [{"event_id": "sig-1"}])
    con = sqlite3.connect(str(db))
    try:
        ps.ensure_probability_snapshot_schema(con)
        ps.ensure_probability_snapshot_schema(con)  # idempotent
        cur = con.cursor()
        cur.execute(f"PRAGMA table_info({ps.PROBABILITY_SNAPSHOT_TABLE})")
        cols = {row[1] for row in cur.fetchall()}
    finally:
        con.close()
    for axis in ps.SCORE_AXES:
        assert axis in cols
    assert "model_probability" in cols
    assert "probability_formula_version" in cols
    assert "advisory_status" in cols
    assert "execution_gate" in cols


def test_dry_run_does_not_write(tmp_path):
    db = tmp_path / "mvp.db"
    _make_signal_events_db(
        db,
        [{"event_id": "sig-001", "source_name": "grok_xai"}],
    )
    stats = ps.backfill_probability_snapshots(db_path=db, limit=None, dry_run=True)
    con = sqlite3.connect(str(db))
    try:
        cur = con.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {ps.PROBABILITY_SNAPSHOT_TABLE}")
        count = int(cur.fetchone()[0])
    finally:
        con.close()
    assert count == 0
    assert stats["snapshots_created"] == 1  # planned, not persisted
    assert stats["signals_scanned"] == 1


def test_write_mode_only_inserts_new(tmp_path):
    db = tmp_path / "mvp.db"
    _make_signal_events_db(
        db,
        [
            {"event_id": "sig-1", "source_name": "grok_xai"},
            {"event_id": "sig-2", "source_name": "grok_xai", "mock_fallback": True},
        ],
    )
    first = ps.backfill_probability_snapshots(db_path=db, limit=None, dry_run=False)
    second = ps.backfill_probability_snapshots(db_path=db, limit=None, dry_run=False)
    assert first["snapshots_created"] == 2
    assert second["snapshots_created"] == 0
    assert second["snapshots_skipped"] == 2

    con = sqlite3.connect(str(db))
    try:
        cur = con.cursor()
        cur.execute(
            f"SELECT signal_id, advisory_status, execution_gate, broker_api_called, "
            f"ai_execution_count, model_probability, mock_penalty "
            f"FROM {ps.PROBABILITY_SNAPSHOT_TABLE} ORDER BY signal_id"
        )
        rows = cur.fetchall()
    finally:
        con.close()
    assert len(rows) == 2
    for sig_id, status, gate, broker, ai_exec, p, _mock_pen in rows:
        assert status == "ADVISORY_ONLY"
        assert gate == "LOCKED"
        assert int(broker) == 0
        assert int(ai_exec) == 0
        assert 0.0 <= float(p) <= 1.0
    # The mock-flagged signal earns a non-zero mock penalty.
    mock_row = next(r for r in rows if r[0] == "sig-2")
    assert float(mock_row[6]) > 0.0


def test_invalid_probability_count_is_zero_in_normal_path(tmp_path):
    db = tmp_path / "mvp.db"
    _make_signal_events_db(
        db, [{"event_id": f"sig-{i}"} for i in range(5)]
    )
    stats = ps.backfill_probability_snapshots(db_path=db, limit=None, dry_run=True)
    assert stats["invalid_probability_count"] == 0


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def test_report_contains_advisory_stamps_and_predictive_block(tmp_path):
    db = tmp_path / "mvp.db"
    _make_signal_events_db(db, [{"event_id": "sig-1"}])
    report = ps.build_report(db_path=db, dry_run=True, limit=None, write=False)
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
    assert report["predictive_claim_allowed"] is False
    assert "uncalibrated" in report["warning"].lower()
    assert report["formula_version"] == ps.FORMULA_VERSION
    # No forbidden execution language in the human-facing warning.
    for forbidden in (
        "place_order",
        "submit_order",
        "execute_trade",
        "broker_execute",
    ):
        assert forbidden not in report["warning"].lower()


def test_report_handles_missing_db_gracefully(tmp_path):
    db = tmp_path / "does_not_exist.db"
    report = ps.build_report(db_path=db, dry_run=True, limit=None, write=False)
    assert report["signals_scanned"] == 0
    assert report["snapshots_created"] == 0
    assert report["predictive_claim_allowed"] is False
    assert report["evidence_status"] == "DB_MISSING"


def test_report_json_serialisable(tmp_path):
    db = tmp_path / "mvp.db"
    _make_signal_events_db(db, [{"event_id": "sig-1"}])
    report = ps.build_report(db_path=db, dry_run=True, limit=None, write=False)
    payload = json.dumps(report)  # must round-trip
    parsed = json.loads(payload)
    assert parsed["script"] == "probability_snapshot.py"


def test_cli_json_write(tmp_path):
    db = tmp_path / "mvp.db"
    _make_signal_events_db(db, [{"event_id": "sig-1"}])
    out = tmp_path / "report.json"
    rc = ps.main(["--db", str(db), "--dry-run", "--json", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["dry_run"] is True
    assert data["predictive_claim_allowed"] is False
