"""Model registry guard (Pass 4) — every model declared, owned, and inert.

Fails if any registered model is missing owner, purpose, the execution
capability flag, or the human-required flag — and hard-fails if any model
ever claims execution capability or future-data use.
"""
from __future__ import annotations

import json
from pathlib import Path

_REGISTRY = Path(__file__).resolve().parents[1] / "model_registry.json"

_REQUIRED_FIELDS = (
    "name", "version", "owner", "purpose", "inputs", "outputs",
    "uses_llm", "uses_market_data", "uses_future_data",
    "execution_capable", "human_required", "tests", "known_limits",
)


def _models() -> list[dict]:
    data = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    assert data["advisory_only"] is True
    assert data["execution_capable_models_allowed"] is False
    assert data["owner"] == "Akash Guha"
    return data["models"]


def test_registry_exists_and_is_populated():
    models = _models()
    assert len(models) >= 25, "registry should cover the mapped pipeline"
    names = [m["name"] for m in models]
    assert len(names) == len(set(names)), "duplicate model names"


def test_every_model_has_required_fields():
    for model in _models():
        missing = [f for f in _REQUIRED_FIELDS if f not in model]
        assert missing == [], f"{model.get('name', '?')}: missing {missing}"
        assert str(model["owner"]).strip() == "Akash Guha", model["name"]
        assert str(model["purpose"]).strip(), f"{model['name']}: empty purpose"
        assert "advisory-only" in model["purpose"], model["name"]


def test_no_model_is_execution_capable_or_uses_future_data():
    for model in _models():
        assert model["execution_capable"] is False, (
            f"{model['name']} claims execution capability — forbidden, stop"
        )
        assert model["human_required"] is True, model["name"]
        assert model["uses_future_data"] is False, (
            f"{model['name']} claims future-data use — leakage by design"
        )


def test_llm_models_are_flagged():
    llm_models = [m["name"] for m in _models() if m["uses_llm"]]
    # The known LLM-touching surfaces must be flagged as such.
    for expected in ("ai_report_normalizer", "model_reliability_ledger",
                     "llm_grounding_guard"):
        assert expected in llm_models, expected


def test_pass4_models_registered():
    names = {m["name"] for m in _models()}
    for expected in (
        "evidence_ledger", "temporal_guard", "backtest_advisory_signals",
        "model_calibration_pass4", "llm_grounding_guard",
        "sensitivity_analysis", "decision_memo_generator",
        "post_outcome_review", "model_scorecard",
    ):
        assert expected in names, expected
