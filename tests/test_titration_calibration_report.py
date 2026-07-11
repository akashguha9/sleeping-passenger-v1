"""Tests for scripts/titration_calibration_report.py — refusal-first metrics.

Covers: refusals at zero/small/single-class samples, temporal split with
overlap purge, comparator AUC sanity on a synthetic predictive feature,
per-state transition rates with Wilson intervals, hazard sample gate,
stability warnings, and safety stamps.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scripts.persistence as persistence
from scripts.titration_calibration_report import (
    HAZARD_BLOCKED,
    INSUFFICIENT,
    MIN_EVAL_OBSERVATIONS,
    MIN_OUTCOMES_FOR_HAZARD,
    build_report,
    build_stability_section,
    _auc,
    _evaluate_horizon,
)


def _obs_row(i: int, *, y: int, dose: float, lrr: float, state: str = "LOADING",
             horizon: int = 5, maturation: str = "MATURED") -> dict:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)
    return {
        "obs_id": f"O_{i}_{horizon}",
        "ticker": "ACME",
        "market": "US",
        "sector": None,
        "event_id": f"E_{i}",
        "event_ts": ts.isoformat(),
        "entry_bar_date": ts.date().isoformat(),
        "dose": dose,
        "active_before": 0.1,
        "active_after": 0.1 + dose,
        "lrr": lrr,
        "vmr": 0.3,
        "pag": lrr - 0.3,
        "ftr": 0.2,
        "titration_state": state,
        "horizon": horizon,
        "maturation": maturation,
        "z": 1.5 if y else 0.2,
        "y_absolute": y,
        "y_directional": None,
        "y_benchmark_relative": None,
    }


def test_auc_sanity():
    assert _auc([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0]) == 1.0
    assert _auc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]) == 0.0
    assert _auc([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0]) == 0.5
    assert _auc([0.5, 0.5], [1, 1]) is None  # single class


def test_empty_report_refuses_everything(tmp_path):
    db = tmp_path / "empty.db"
    persistence.init_schema(db_path=db)
    report = build_report(db)
    assert report["calibration_status"] == "UNCALIBRATED"
    assert report["overall_confidence_band"] == "very_low"
    assert report["transition_hazard"]["status"] == HAZARD_BLOCKED
    assert report["transition_hazard"]["additional_outcomes_needed"] == MIN_OUTCOMES_FOR_HAZARD
    assert report["data_inventory"]["observation_rows"] == 0
    assert "no_response_observations_built" in report["stability"]["warnings"]
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert "no_alpha_proven" in report["non_claims"]


def test_small_sample_refusal():
    rows = [_obs_row(i, y=i % 2, dose=0.1 * i, lrr=0.5) for i in range(10)]
    result = _evaluate_horizon(rows, 5)
    assert result["verdict"] == INSUFFICIENT
    assert result["refusal_reason"] == "below_minimum_sample"
    assert result["sample_needed"] == MIN_EVAL_OBSERVATIONS - 10
    assert result["comparators"] == {}


def test_single_class_refusal():
    rows = [_obs_row(i, y=1, dose=0.1, lrr=0.5) for i in range(40)]
    result = _evaluate_horizon(rows, 5)
    assert result["verdict"] == INSUFFICIENT
    assert result["refusal_reason"] == "single_outcome_class"


def test_temporal_evaluation_with_predictive_feature():
    # 80 observations; transition strictly follows high dose -> dose AUC
    # should be near 1.0 out of time; base rate ~0.5.
    rows = []
    for i in range(80):
        y = 1 if i % 2 == 0 else 0
        dose = 0.8 + 0.001 * i if y else 0.1 + 0.001 * i
        rows.append(_obs_row(i, y=y, dose=dose, lrr=0.5))
    result = _evaluate_horizon(rows, 5)
    assert result["verdict"] == "TEMPORAL_OOS_COMPARISON_AVAILABLE"
    assert result["test_n"] >= 15
    assert result["purged_overlap_count"] >= 0
    dose_cmp = result["comparators"]["evidence_dose"]
    assert dose_cmp["auc"] > 0.95
    assert dose_cmp["semantics"] == "rank_statistic_not_probability"
    # A constant feature ranks at chance.
    lrr_cmp = result["comparators"]["lrr"]
    assert abs(lrr_cmp["auc"] - 0.5) < 0.2


def test_purge_drops_training_rows_near_boundary():
    rows = [_obs_row(i, y=i % 2, dose=0.5, lrr=0.5) for i in range(60)]
    result = _evaluate_horizon(rows, 20)  # long horizon -> larger purge window
    if result["verdict"] == "TEMPORAL_OOS_COMPARISON_AVAILABLE":
        assert result["purged_overlap_count"] > 0


def test_state_transition_rates_with_gates(tmp_path):
    db = tmp_path / "states.db"
    persistence.init_schema(db_path=db)
    rows = []
    for i in range(30):
        rows.append(_obs_row(i, y=1 if i < 20 else 0, dose=0.5, lrr=0.7,
                             state="PRIMED" if i < 20 else "INERT"))
    persistence.replace_titration_observations(rows, db_path=db)
    report = build_report(db)
    states = report["state_transition_rates"]["5"]
    assert states["PRIMED"]["n"] == 20
    assert states["PRIMED"]["transition_rate"] == 1.0
    lo, hi = states["PRIMED"]["wilson"]
    assert lo < 1.0 <= hi
    assert states["INERT"]["n"] == 10
    assert states["INERT"]["transition_rate"] == 0.0


def test_hazard_gate_passes_only_with_sample(tmp_path):
    db = tmp_path / "hazard.db"
    persistence.init_schema(db_path=db)
    rows = [_obs_row(i, y=i % 2, dose=0.4, lrr=0.5) for i in range(MIN_OUTCOMES_FOR_HAZARD)]
    persistence.replace_titration_observations(rows, db_path=db)
    report = build_report(db)
    assert report["transition_hazard"]["status"] == "SAMPLE_GATE_PASSED_FIT_PENDING"


def test_stability_warnings():
    section = build_stability_section([], [])
    assert "no_response_observations_built" in section["warnings"]
    assert section["proxy_fallback_expected"] is True

    rows = [_obs_row(i, y=0, dose=0.1, lrr=0.2, state="INERT",
                     maturation="NOT_YET_MATURED") for i in range(20)]
    section2 = build_stability_section(rows, [])
    assert "no_matured_outcomes_yet" in section2["warnings"]
    assert any(w.startswith("state_dominance:INERT") for w in section2["warnings"])


def test_report_full_shape_on_seeded_db(tmp_path):
    db = tmp_path / "full.db"
    persistence.init_schema(db_path=db)
    rows = []
    for i in range(50):
        y = 1 if i % 3 == 0 else 0
        rows.append(_obs_row(i, y=y, dose=0.2 + (0.5 if y else 0.0), lrr=0.5))
    persistence.replace_titration_observations(rows, db_path=db)
    report = build_report(db)
    assert report["report_version"]
    assert report["data_inventory"]["matured_rows"] == 50
    assert "5" in report["horizon_evaluations"]
    assert "5" in report["catalytic_convexity"]
    assert report["catalytic_convexity"]["5"]["is_experimental"] is True
    assert report["limitations"]
    assert report["can_execute"] is False
