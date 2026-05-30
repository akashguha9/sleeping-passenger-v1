"""Tests — 50/100 closed-outcome progress dashboard (Workstream D + E).

Proves the readiness report exposes the 50/100 progress + named calibration
stage, the reliability API surfaces them plus top-missing-fields / next actions
and a LOW-BY-DESIGN real-money readiness ceiling, and that the three new sprint
modules stay in-scope + carry no broker/execution language.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.paper_outcome_collection_readiness import (
    LABEL_COLD_START,
    LABEL_PAPER_CALIBRATED,
    LABEL_PROVISIONAL,
    build_paper_outcome_collection_readiness,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


# --- 13: readiness report exposes 50/100 progress + calibration stage -------
def test_readiness_exposes_50_100_progress():
    cold = build_paper_outcome_collection_readiness(closed_paper_outcomes_count=0)
    assert cold["closed_outcome_progress_50"] == pytest.approx(0.0)
    assert cold["closed_outcome_progress_100"] == pytest.approx(0.0)
    assert cold["calibration_stage"] == LABEL_COLD_START

    half = build_paper_outcome_collection_readiness(closed_paper_outcomes_count=50)
    assert half["closed_outcome_progress_50"] == pytest.approx(1.0)
    assert half["closed_outcome_progress_100"] == pytest.approx(0.5)
    assert half["calibration_stage"] == LABEL_PROVISIONAL

    full = build_paper_outcome_collection_readiness(closed_paper_outcomes_count=120)
    assert full["closed_outcome_progress_50"] == pytest.approx(1.0)
    assert full["closed_outcome_progress_100"] == pytest.approx(1.0)
    assert full["calibration_stage"] == LABEL_PAPER_CALIBRATED


# --- 13b: the reliability API surfaces the progress fields ------------------
def test_reliability_api_surfaces_progress():
    from scripts.api.routers.external_evidence_router import (
        build_external_evidence_reliability_payload,
    )

    payload = build_external_evidence_reliability_payload(
        artifact_path=Path("/nonexistent/__no_artifact__.json")
    )
    readiness = payload.get("paper_outcome_readiness") or {}
    assert "closed_outcome_progress_50" in readiness
    assert "closed_outcome_progress_100" in readiness
    assert "calibration_stage" in readiness
    assert isinstance(payload.get("next_operator_actions"), list)
    assert len(payload["next_operator_actions"]) <= 5
    assert "top_missing_fields" in payload


# --- 14: real-money readiness is LOW BY DESIGN ------------------------------
def test_reliability_api_real_money_low_by_design():
    from scripts.api.routers.external_evidence_router import (
        build_external_evidence_reliability_payload,
    )

    payload = build_external_evidence_reliability_payload(
        artifact_path=Path("/nonexistent/__no_artifact__.json")
    )
    assert payload["real_money_readiness_ceiling"] == "LOW BY DESIGN"
    assert payload["real_money_sizing_impact"] == "PROHIBITED"
    assert payload["real_money_weight_allowed"] is False


# --- 15: the new modules classify in-scope for the private scope guard ------
def test_new_modules_in_scope():
    from scripts import private_scope_guard as guard

    for name in (
        "paper_outcome_importer.py",
        "paper_outcome_external_evidence_linker.py",
        "calibration_corpus_builder.py",
    ):
        assert guard._classify(name) == "in_scope", name


# --- 16/17: no broker / execution language in the new sprint modules --------
def test_new_modules_have_no_execution_language():
    forbidden = (
        "place_order",
        "submit_order",
        "execute_trade",
        "broker_execute",
        "auto-trading",
        "permission to trade",
        "enable_auto_trading",
    )
    for name in (
        "paper_outcome_importer.py",
        "paper_outcome_external_evidence_linker.py",
        "calibration_corpus_builder.py",
    ):
        text = (_REPO_ROOT / "scripts" / name).read_text(encoding="utf-8").lower()
        for phrase in forbidden:
            assert phrase not in text, f"{phrase!r} present in {name}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
