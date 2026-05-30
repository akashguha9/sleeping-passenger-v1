"""Phase 8 — Brier/ECE evidence pipeline over snapshots + outcomes.

Proves the snapshot->outcome calibration bridge computes Brier/ECE/LogLoss
honestly and that the predictive-claim gate stays LOCKED until N>=200 AND
Brier<=0.25 AND ECE<=0.10 are all satisfied.  We start the evidence pipeline;
we never claim calibration.
"""
from __future__ import annotations

import math

from scripts.calibration_report import brier_score, Observation
from scripts.live_decision_path import run_live_decision_path
from scripts.snapshot_calibration_bridge import (
    attach_outcome,
    build_calibration_dataset_from_snapshots_and_outcomes,
    build_snapshot_calibration_report,
    compute_brier_ece,
)


def _dataset(pairs):
    return [{"p": p, "y": y} for p, y in pairs]


def test_brier_score_computed_from_snapshot_outcome_pairs():
    pairs = [(0.9, 1), (0.1, 0), (0.8, 1), (0.2, 0)]
    res = compute_brier_ece(_dataset(pairs))
    expected = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
    assert res["n"] == 4
    assert math.isclose(res["brier"], round(expected, 6), abs_tol=1e-9)


def test_ece_computed_from_bins():
    pairs = [(0.95, 1), (0.05, 0), (0.9, 1), (0.1, 0)]
    res = compute_brier_ece(_dataset(pairs), n_buckets=10)
    assert res["ece"] is not None
    assert 0.0 <= res["ece"] <= 1.0


def test_logloss_handles_probabilities_safely():
    # p exactly 0/1 must not blow up (clipped internally).
    pairs = [(0.0, 0), (1.0, 1), (0.0, 1), (1.0, 0)]
    res = compute_brier_ece(_dataset(pairs))
    assert res["log_loss"] is not None
    assert not math.isinf(res["log_loss"])
    assert not math.isnan(res["log_loss"])


def test_missing_outcomes_excluded_with_reason(tmp_path):
    db = tmp_path / "cal.db"
    # Two snapshots; only one gets an outcome label.
    d1 = run_live_decision_path(
        signal_id="C1",
        axes={"EMS": 0.6, "EQS": 0.6, "DS": 0.6, "LS": 0.6, "EFS": 0.6, "APS": 0.6},
        ticker="X", country="India", rows_added=5, canonical_age_hours=1.0,
        state="HURACAN", capital=1e6, cash_available=5e5,
        entry_price=100.0, hard_stop_price=95.0, db_path=db,
    )
    run_live_decision_path(
        signal_id="C2",
        axes={"EMS": 0.6, "EQS": 0.6, "DS": 0.6, "LS": 0.6, "EFS": 0.6, "APS": 0.6},
        ticker="X", country="India", rows_added=5, canonical_age_hours=1.0,
        state="HURACAN", capital=1e6, cash_available=5e5,
        entry_price=100.0, hard_stop_price=95.0, db_path=db,
    )
    attach_outcome(db, d1["snapshot_id"], 1)

    built = build_calibration_dataset_from_snapshots_and_outcomes(db)
    assert built["n_total_snapshots"] == 2
    assert built["n_pairs"] == 1               # only the labelled one
    assert built["n_missing_outcome"] == 1     # the unlabelled one, with reason
    assert "missing_outcome" in built["exclusion_reasons"]


def test_n_below_200_insufficient_evidence():
    pairs = [(0.7, 1), (0.3, 0)] * 10  # N=20, far below 200
    res = compute_brier_ece(_dataset(pairs))
    assert res["n"] == 20
    assert res["predictive_claim_allowed"] is False
    assert res["calibration_status"] != "MEASURED"


def test_predictive_claim_allowed_false_until_all_thresholds_pass():
    # N=0 corpus
    empty = compute_brier_ece([])
    assert empty["n"] == 0
    assert empty["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert empty["predictive_claim_allowed"] is False


def test_gate_passes_only_when_n_brier_ece_all_satisfied():
    # Construct a perfectly-calibrated, well-separated synthetic corpus of
    # N=200 so Brier and ECE are tiny — the ONLY case where the gate may open.
    pairs = [(0.99, 1)] * 100 + [(0.01, 0)] * 100  # N=200
    res = compute_brier_ece(_dataset(pairs))
    assert res["n"] == 200
    assert res["n_satisfies_min"] is True
    assert res["brier_satisfies_threshold"] is True
    assert res["ece_satisfies_threshold"] is True
    assert res["predictive_claim_allowed"] is True  # math gate, not a claim about real data

    # Flip the sample size below the floor: gate must lock again even with
    # identical (excellent) metrics.
    small = compute_brier_ece(_dataset([(0.99, 1), (0.01, 0)]))
    assert small["predictive_claim_allowed"] is False


def test_metrics_visible_to_calibration_ui_or_api_if_wired(tmp_path):
    # The combined report (what a card/API would render) carries metrics +
    # corpus accounting + advisory stamps, and is honest on an empty DB.
    db = tmp_path / "cal.db"
    report = build_snapshot_calibration_report(db)
    assert report["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert report["predictive_claim_allowed"] is False
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert "corpus" in report

    # Sanity: brier helper agrees with a hand computation on Observations.
    obs = [Observation(0.9, 1), Observation(0.2, 0)]
    assert math.isclose(brier_score(obs), ((0.9 - 1) ** 2 + (0.2) ** 2) / 2)
