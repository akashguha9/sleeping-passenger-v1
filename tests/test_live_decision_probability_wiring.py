"""Phase 1 — the live decision path actually records a probability snapshot.

Proves the snapshot module is wired into a *live* path (run_live_decision_path),
not just exercised by its own unit tests: a realistic decision through the path
grows ``n_valid_p`` and persists the full snapshot contract, while the
calibration gate stays honestly locked.
"""
from __future__ import annotations

from scripts.decision_probability_snapshot import count_valid_p
from scripts.live_decision_path import run_live_decision_path

# A fresh, live-canonical, well-capitalised candidate.
_AXES = {"EMS": 0.6, "EQS": 0.7, "DS": 0.6, "LS": 0.55, "EFS": 0.5, "APS": 0.6}


def _live_kwargs(**overrides):
    base = dict(
        signal_id="SIG_LIVE_1",
        axes=_AXES,
        ticker="RELIANCE.NS",
        country="India",
        signal_class="momentum",
        source_mix=["yfinance"],
        prediction_horizon_days=3.0,
        api_health_status="OK",
        rows_added=5,
        canonical_age_hours=2.0,
        state="HURACAN",
        shock_override="NONE",
        chaos_risk=0.1,
        capital=1_000_000.0,
        cash_available=500_000.0,
        entry_price=100.0,
        hard_stop_price=95.0,
        leverage=1.0,
        leverage_valid=True,
    )
    base.update(overrides)
    return base


def test_live_advisory_decision_records_probability_snapshot(tmp_path):
    db = tmp_path / "dps.db"
    out = run_live_decision_path(db_path=db, **_live_kwargs())
    assert out["snapshot_persisted"] is True
    assert out["snapshot_id"]
    assert out["model_probability"] is not None
    assert 0.0 <= out["model_probability"] <= 1.0


def test_live_advisory_decision_increments_valid_p_count(tmp_path):
    db = tmp_path / "dps.db"
    assert count_valid_p(db) == 0
    run_live_decision_path(db_path=db, **_live_kwargs(signal_id="SIG_A"))
    assert count_valid_p(db) == 1
    run_live_decision_path(db_path=db, **_live_kwargs(signal_id="SIG_B"))
    assert count_valid_p(db) == 2


def test_snapshot_contains_scoring_version_and_model_version(tmp_path):
    db = tmp_path / "dps.db"
    out = run_live_decision_path(db_path=db, **_live_kwargs())
    assert out["model_version"] == "advisory-logistic-v1"
    assert out["scoring_version"]  # FORMULA_VERSION


def test_snapshot_contains_prediction_horizon_and_target_event(tmp_path):
    db = tmp_path / "dps.db"
    out = run_live_decision_path(
        db_path=db, **_live_kwargs(prediction_horizon_days=7.0)
    )
    assert out["prediction_horizon_days"] == 7.0
    assert out["target_event_definition"]


def test_snapshot_preserves_advisory_only_stamps(tmp_path):
    db = tmp_path / "dps.db"
    out = run_live_decision_path(db_path=db, **_live_kwargs())
    assert out["advisory_status"] == "ADVISORY_ONLY"
    assert out["execution_gate"] == "LOCKED"
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0
    assert out["human_execution_required"] is True


def test_predictive_claim_allowed_remains_false_below_calibration_gate(tmp_path):
    db = tmp_path / "dps.db"
    out = run_live_decision_path(db_path=db, **_live_kwargs())
    assert out["predictive_claim_allowed"] is False
    assert out["calibration_status"] in {
        "INSUFFICIENT_EVIDENCE", "PENDING_OUTCOME_LABELS"
    }


def test_invalid_or_missing_probability_records_reason_not_fake_value(tmp_path):
    db = tmp_path / "dps.db"
    out = run_live_decision_path(db_path=db, **_live_kwargs(axes=None))
    assert out["model_probability"] is None
    assert out["model_probability_reason"] == "NO_SCORE_VECTOR_AT_DECISION"
    # A null-probability decision must not pollute the calibratable count.
    assert count_valid_p(db) == 0


def test_no_side_effect_when_db_path_none():
    out = run_live_decision_path(db_path=None, **_live_kwargs())
    assert out["snapshot_persisted"] is False
    assert out["model_probability"] is not None
