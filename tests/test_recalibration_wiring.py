"""Tests for recalibration wiring into score contract + signal quality."""
from __future__ import annotations

from scripts import outcome_evidence as oe
from scripts import score_calibration as sc
from scripts import calibration_map as cm
from scripts import score_output_contract as soc
from scripts import signal_quality_report as sq


def _o(label, score, count, source=oe.IMPORTED_BACKTEST):
    out = []
    for i in range(count):
        ex = 110.0 if label == "WIN" else 90.0 if label == "LOSS" else 100.0
        out.append(oe.build_outcome(
            outcome_id=f"{label}{score}_{i}_{id(object())}", source_type=source,
            ticker="X", direction="LONG", entry_price=100.0, exit_price=ex,
            score_at_entry=score, opened_at="a", closed_at="b",
            outcome_label_override=label,
        ))
    return out


def _miscalibrated_outcomes():
    # overconfident: score 0.9 wins 40%, score 0.2 wins 15% -> recalibration helps
    import random
    random.seed(99)
    outs = []
    for _ in range(120):
        outs.append(_o("WIN" if random.random() < 0.4 else "LOSS", 0.9, 1)[0])
    for _ in range(120):
        outs.append(_o("WIN" if random.random() < 0.15 else "LOSS", 0.2, 1)[0])
    return outs


# --- score contract recalibrated_score --------------------------------------

def test_contract_without_map_has_no_recalibrated_score():
    c = soc.build_score_contract(0.9, sc.compute_calibration_metrics([]))
    assert c["recalibrated_score"] is None
    soc.assert_score_contract(c)  # still a valid contract


def test_contract_with_validated_map_recalibrates():
    outs = _miscalibrated_outcomes()
    cmap = cm.fit_from_outcomes(outs)
    assert cmap.improved is True
    summary = sc.compute_score_calibration([])  # status not needed for recal
    c = soc.build_score_contract(0.9, summary, calibration_map=cmap)
    assert c["recalibrated_score"] is not None
    assert c["recalibrated_score"] < 0.9  # overconfident 0.9 pulled down
    assert c["recalibration_method"] in {"isotonic", "platt"}


def test_recalibrated_score_does_not_enable_sizing():
    outs = _miscalibrated_outcomes()
    cmap = cm.fit_from_outcomes(outs)
    c = soc.build_score_contract(0.9, sc.compute_score_calibration([]), calibration_map=cmap)
    # recalibration is advisory only; sizing still requires CALIBRATED + approval
    assert c["should_drive_sizing"] is False
    assert c["calibrated_score"] is None


# --- signal quality credits OOS recalibration + counts backtest --------------

def test_backtest_outcomes_count_for_signal_quality():
    # 60 backtest outcomes, well-calibrated (score 0.9 -> 90% win)
    outs = _o("WIN", 0.9, 54) + _o("LOSS", 0.9, 6)
    metrics = sc.compute_calibration_metrics(outs)
    r = sq.build_signal_quality_report(metrics, coverage_score=1.0,
                                       recommendation={"sample_size": 60},
                                       feedback_human_reviewed=True)
    assert metrics["backtest_n"] == 60
    assert metrics["real_n"] == 0
    assert "no_eligible_outcomes" not in r["caps_applied"]
    # backtest-calibrated scores can exceed 7.5 for SIGNAL QUALITY
    assert r["signal_quality_score"] > 7.5


def test_recalibration_improves_signal_quality_ece_component():
    outs = _miscalibrated_outcomes()
    metrics = sc.compute_calibration_metrics(outs)
    cmap = cm.fit_from_outcomes(outs).to_dict()
    r_no = sq.build_signal_quality_report(metrics, coverage_score=1.0)
    r_yes = sq.build_signal_quality_report(metrics, coverage_score=1.0, calibration_map=cmap)
    assert r_yes["recalibration_applied"] is True
    assert r_yes["components"]["ECE_score"] >= r_no["components"]["ECE_score"]


def test_fixtures_still_capped_even_with_map():
    outs = _o("WIN", 0.9, 60, source=oe.SYNTHETIC_FIXTURE)
    metrics = sc.compute_calibration_metrics(outs)
    r = sq.build_signal_quality_report(metrics, coverage_score=1.0)
    assert r["signal_quality_score"] <= 7.0
    assert "fixtures_only" in r["caps_applied"]


def test_calibration_map_api_endpoint(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from scripts import api_server
    import scripts.persistence as persistence
    monkeypatch.setattr(persistence, "DB_PATH", tmp_path / "cmap_api.db", raising=False)
    client = TestClient(api_server.app)
    r = client.get("/api/calibration-map")
    assert r.status_code == 200, r.text
    data = r.json()
    # Empty DB -> identity, not improved, advisory.
    assert data["method"] == "identity"
    assert data["improved_out_of_sample"] is False
    assert data["broker_api_called"] is False


def test_signal_quality_api_includes_recalibration(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from scripts import api_server
    import scripts.persistence as persistence
    monkeypatch.setattr(persistence, "DB_PATH", tmp_path / "sq_api.db", raising=False)
    client = TestClient(api_server.app)
    r = client.get("/api/signal-quality")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "recalibration_applied" in data
    assert data["broker_api_called"] is False
