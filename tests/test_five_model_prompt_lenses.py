"""Five-model prompt lens + advisory-only safety tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.advisory_contract import advisory_safety_stamps
from scripts.anti_staleness import build_anti_staleness
from scripts.candidate_executable_split import build_candidate_executable_split
from scripts.daily_payload import load_daily_payload
from scripts.fresh_market_discovery import build_fresh_market_discovery
from scripts.portfolio_truth_gate import build_portfolio_truth_gate

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = REPO_ROOT / "prompts"

MODELS = ["gpt", "claude", "gemini", "grok", "mistral"]

LENS_MARKERS = {
    "gpt": "decision-hygiene analyst",
    "claude": "repo-forensic analyst",
    "gemini": "broad-market scanner",
    "grok": "narrative-pressure analyst",
    "mistral": "macro-sector analyst",
}

COMMON_RULES = [
    "verified_current_holdings",
    "do_not_treat_as_open",
    "DO_NOT_TREAT_AS_OPEN",
    "EXECUTABLE-PAPER-BUY",
    "not executable",
    "block fresh discovery",
    "H = V MINUS (C UNION S UNION D)",
]


@pytest.mark.parametrize("model", MODELS)
def test_prompt_contains_common_truth_rules(model: str) -> None:
    text = (PROMPTS_DIR / f"{model}_daily_prompt.txt").read_text(encoding="utf-8")
    for needle in COMMON_RULES:
        assert needle in text, f"{model} prompt missing rule fragment: {needle!r}"


@pytest.mark.parametrize("model", MODELS)
def test_prompt_contains_model_specific_lens(model: str) -> None:
    text = (PROMPTS_DIR / f"{model}_daily_prompt.txt").read_text(encoding="utf-8")
    assert LENS_MARKERS[model] in text, f"{model} prompt missing its lens marker"


@pytest.mark.parametrize("model", MODELS)
def test_prompt_keeps_advisory_only_language(model: str) -> None:
    text = (PROMPTS_DIR / f"{model}_daily_prompt.txt").read_text(encoding="utf-8").lower()
    assert "advisory only" in text
    assert "no broker" in text
    assert "human review required" in text or "human operator" in text


@pytest.mark.parametrize("model", MODELS)
def test_prompt_requires_fresh_discovery(model: str) -> None:
    text = (PROMPTS_DIR / f"{model}_daily_prompt.txt").read_text(encoding="utf-8")
    assert "Discovery underpowered but not skipped" in text
    assert "fresh buy-candidate" in text.lower() or "fresh candidates to study" in text.lower()


def test_synthesis_runner_has_portfolio_truth_audit() -> None:
    text = (REPO_ROOT / "scripts" / "run_five_model_synthesis.ps1").read_text(encoding="utf-8")
    assert "PORTFOLIO TRUTH AUDIT" in text
    assert "Portfolio Truth Audit" in text
    assert "HISTORICAL CONTEXT ONLY" in text
    assert "Top 5 fresh candidates to study today" in text


def test_module_outputs_carry_advisory_safety_stamps() -> None:
    payload = load_daily_payload()
    gate = build_portfolio_truth_gate(payload=payload)
    discovery = build_fresh_market_discovery(payload=payload, truth_gate=gate)
    split = build_candidate_executable_split(discovery, gate)
    stale = build_anti_staleness(payload, [], gate)

    expected = advisory_safety_stamps()
    for obj in (gate, discovery, split, stale):
        assert obj["safety"] == expected
        assert obj["safety"]["execution_gate"] == "LOCKED"
        assert obj["safety"]["broker_api_called"] is False
        assert obj["safety"]["ai_execution_count"] == 0
        assert obj["safety"]["can_execute"] is False


def test_no_execution_surfaces_in_new_modules() -> None:
    forbidden = ("place_order", "submit_order", "broker.execute", "requests.post(\"https://api.broker")
    scripts_dir = REPO_ROOT / "scripts"
    for name in (
        "daily_payload.py",
        "portfolio_truth_gate.py",
        "fresh_market_discovery.py",
        "candidate_executable_split.py",
        "anti_staleness.py",
        "daily_synthesis_pipeline.py",
    ):
        text = (scripts_dir / name).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{name} must not contain execution token {token!r}"
