"""Tests — five-model input quorum assertion (P5 of the Kanté defensive sprint).

Proves the synthesis model-input report clearly shows:
  * which model inputs are present,
  * which are missing,
  * whether quorum is satisfied,
  * whether missing evidence downgrades classification.
Advisory only; no execution, no broker, no network.
"""
from __future__ import annotations

import pytest

from scripts import five_model_independence as fmi


def _runs(models):
    return [
        fmi.ModelRun(model_name=m, prompt=f"p-{m}", input_context="c",
                     output=f"o-{m}", run_order=i + 1)
        for i, m in enumerate(models)
    ]


def test_quorum_min_is_majority_of_five():
    assert fmi.MODEL_QUORUM_MIN == 3


def test_full_quorum_when_all_models_present():
    summary = fmi.build_summary()  # all 5, independent
    assert set(summary["models_present"]) == {m.lower() for m in fmi.EXPECTED_MODELS}
    assert summary["models_missing"] == []
    assert summary["quorum_satisfied"] is True
    assert summary["classification_downgraded_for_missing_models"] is False


def test_exactly_three_independent_models_satisfy_quorum():
    summary = fmi.build_summary(_runs(fmi.EXPECTED_MODELS[:3]))
    assert summary["independent_model_count"] == 3
    assert summary["quorum_satisfied"] is True


def test_below_quorum_missing_models_downgrade_classification():
    summary = fmi.build_summary(_runs(fmi.EXPECTED_MODELS[:2]))  # only 2 of 5
    assert summary["independent_model_count"] == 2
    assert summary["quorum_satisfied"] is False
    assert summary["classification_downgraded_for_missing_models"] is True
    assert "mistral" in summary["models_missing"]


def test_synthesis_before_freeze_breaks_quorum_even_with_five():
    runs = list(fmi._fixture_runs())
    runs[0].independent_before_synthesis = False
    summary = fmi.build_summary(runs)
    assert summary["synthesis_before_freeze"] is True
    assert summary["quorum_satisfied"] is False
    assert summary["classification_downgraded_for_missing_models"] is True


def test_quorum_report_renders_presence_missing_quorum_and_downgrade():
    summary = fmi.build_summary(_runs(fmi.EXPECTED_MODELS[:2]))
    md = fmi.render_model_quorum_markdown(summary)
    assert "models_present:" in md
    assert "models_missing:" in md
    assert "quorum_satisfied:" in md
    assert "classification_downgraded" in md
    # Missing models are named in the report.
    assert "mistral" in md
    # Present models are named in the report.
    assert "grok" in md


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
