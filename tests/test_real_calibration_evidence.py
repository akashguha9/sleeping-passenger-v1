"""Tests — Real Evidence Sprint Phase 3: Brier/ECE evidence (real vs proxy).

Proves:
  * Brier / ECE / LogLoss are computed for the real-forward corpus,
  * LogLoss clips extreme probabilities (never +inf),
  * N below 200 locks the predictive claim,
  * historical proxy never unlocks the predictive claim,
  * real-forward and proxy metrics are kept separate,
  * the evidence JSON carries every required field,
  * the gate passes ONLY when N, Brier and ECE all pass.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import real_calibration_evidence as ev
from scripts import outcome_labeling_flow as flow
from scripts.decision_probability_snapshot import record_decision_probability


_AXES = {"EMS": 0.6, "EQS": 0.55, "DS": 0.5, "LS": 0.45, "EFS": 0.5, "APS": 0.5}


def _db(tmp_path: Path) -> Path:
    return tmp_path / "snap.db"


def _snapshot(db: Path, sid: str, *, with_p: bool = True) -> str:
    snap = record_decision_probability(
        db_path=db, signal_id=sid, axes=_AXES if with_p else None,
        prediction_horizon_days=5,
    )
    return snap["snapshot_id"]


def _seed(db: Path, n: int, kind: str, *, prefix: str) -> None:
    for i in range(n):
        sid = _snapshot(db, f"{prefix}-{i}")
        flow.attach_outcome(db, sid, i % 2, is_real_outcome=True, outcome_kind=kind)


# --- 1/2. Brier & ECE computed for real-forward pairs ---------------------
def test_brier_computed_for_real_forward_pairs(tmp_path):
    db = _db(tmp_path)
    _seed(db, 6, flow.REAL_FORWARD, prefix="rf")
    evidence = ev.build_calibration_evidence(db)
    assert evidence["n_real_forward"] == 6
    assert evidence["brier_real_forward"] is not None
    assert 0.0 <= evidence["brier_real_forward"] <= 1.0


def test_ece_computed_for_real_forward_pairs(tmp_path):
    db = _db(tmp_path)
    _seed(db, 6, flow.REAL_FORWARD, prefix="rf")
    evidence = ev.build_calibration_evidence(db)
    assert evidence["ece_real_forward"] is not None
    assert evidence["ece_real_forward"] >= 0.0


# --- 3. logloss clips extreme probabilities -------------------------------
def test_logloss_clips_extreme_probabilities():
    # p = 1.0 with y = 0 would be +inf without clipping.
    metrics = ev.compute_corpus_metrics(
        [{"p": 1.0, "y": 0}, {"p": 0.0, "y": 1}], n_min=1
    )
    assert metrics["log_loss"] is not None
    assert metrics["log_loss"] < float("inf")


# --- 4. N < 200 locks predictive claim ------------------------------------
def test_n_below_200_locks_predictive_claim(tmp_path):
    db = _db(tmp_path)
    _seed(db, 10, flow.REAL_FORWARD, prefix="rf")
    evidence = ev.build_calibration_evidence(db)  # default n_min = 200
    assert evidence["n_real_forward"] == 10
    assert evidence["predictive_claim_allowed"] is False
    assert evidence["calibration_status"] != "MEASURED"


# --- 5. historical proxy does not unlock predictive claim -----------------
def test_historical_proxy_does_not_unlock_predictive_claim(tmp_path):
    db = _db(tmp_path)
    # A large, perfectly-calibrated PROXY corpus must not unlock the gate.
    _seed(db, 250, flow.HISTORICAL_PROXY, prefix="px")
    evidence = ev.build_calibration_evidence(db)
    assert evidence["n_historical_proxy"] == 250
    assert evidence["n_real_forward"] == 0
    assert evidence["predictive_claim_allowed"] is False
    assert evidence["historical_proxy_status"] == (
        "HISTORICAL_PROXY_NOT_REAL_FORWARD_CALIBRATION"
    )


# --- 6. real-forward and proxy metrics are separated ----------------------
def test_real_forward_and_proxy_metrics_are_separated(tmp_path):
    db = _db(tmp_path)
    _seed(db, 4, flow.REAL_FORWARD, prefix="rf")
    _seed(db, 7, flow.HISTORICAL_PROXY, prefix="px")
    evidence = ev.build_calibration_evidence(db)
    assert evidence["n_real_forward"] == 4
    assert evidence["n_historical_proxy"] == 7
    assert evidence["combined_debug_only"]["n"] == 11


# --- 7. evidence JSON contains required fields ----------------------------
def test_calibration_evidence_json_contains_required_fields(tmp_path):
    db = _db(tmp_path)
    _seed(db, 3, flow.REAL_FORWARD, prefix="rf")
    evidence = ev.build_calibration_evidence(db)
    path = ev.write_evidence(evidence, tmp_path / "calibration_evidence.json")
    assert Path(path).exists()
    required = [
        "n_real_forward", "n_historical_proxy",
        "brier_real_forward", "ece_real_forward", "logloss_real_forward",
        "brier_historical_proxy", "ece_historical_proxy",
        "predictive_claim_allowed", "calibration_status",
        "exclusion_reasons", "generated_at_utc",
        "model_version", "scoring_version",
    ]
    for key in required:
        assert key in evidence, f"missing {key}"
    # advisory invariants survive serialization
    assert evidence["execution_gate"] == "LOCKED"
    assert evidence["broker_api_called"] is False


# --- 8. gate passes only when N, Brier and ECE all pass -------------------
def test_gate_passes_only_when_n_brier_ece_all_pass():
    # A well-calibrated dataset: confident-correct predictions.
    good = [{"p": 0.95, "y": 1} for _ in range(150)] + [{"p": 0.05, "y": 0} for _ in range(150)]
    # With a small n_min the gate can pass (Brier & ECE both tiny).
    passed = ev.compute_corpus_metrics(good, n_min=10)
    assert passed["n_satisfies_min"] is True
    assert passed["brier_satisfies_threshold"] is True
    assert passed["ece_satisfies_threshold"] is True
    assert passed["predictive_claim_allowed"] is True

    # Same data but the real N floor (200 here is met) — force N to fail:
    locked_by_n = ev.compute_corpus_metrics(good, n_min=10_000)
    assert locked_by_n["n_satisfies_min"] is False
    assert locked_by_n["predictive_claim_allowed"] is False

    # Bad calibration (always wrong) fails Brier/ECE even with enough N.
    bad = [{"p": 0.99, "y": 0} for _ in range(300)]
    locked_by_metrics = ev.compute_corpus_metrics(bad, n_min=10)
    assert locked_by_metrics["brier_satisfies_threshold"] is False
    assert locked_by_metrics["predictive_claim_allowed"] is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
