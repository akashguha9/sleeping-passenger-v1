"""Shared fixtures for the Daily Governance Gate tests.

Deterministic, offline: every test loads the committed 2026-06-05 five-model
snapshot. No network, no live data.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.governance.daily_gate import evaluate_daily_governance
from scripts.governance.daily_governance_runner import run_from_inputs

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "governance"
    / "five_model_2026_06_05.json"
)

_INPUT_KEYS = (
    "verified_current_holdings",
    "closed_positions",
    "sold_positions",
    "not_owned_do_not_manage",
    "current_prices",
    "today_market_snapshot",
    "today_price_movers",
    "today_news_events",
    "today_filings_events",
    "previous_candidates",
    "model_candidate_votes",
    "model_existing_holding_reviews",
    "trade_log",
)


@pytest.fixture
def gov_inputs() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def gov_result(gov_inputs):
    return run_from_inputs(gov_inputs)


@pytest.fixture
def evaluate():
    """Return a helper that evaluates the gate from a loaded inputs dict."""
    def _run(inputs: dict[str, Any]):
        kwargs = {k: inputs[k] for k in _INPUT_KEYS if k in inputs}
        return evaluate_daily_governance(
            run_date=inputs["run_date"], config=inputs.get("config"), **kwargs
        )
    return _run
