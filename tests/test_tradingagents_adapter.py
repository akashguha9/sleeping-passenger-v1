from __future__ import annotations

from pathlib import Path

from scripts.external_adapters.tradingagents_adapter import TradingAgentsAdapter


FIXTURE_PATH = Path("tests/fixtures/external_adapters/tradingagents/sample_agent_committee.json")


def test_tradingagents_mock_mode_and_action_sanitization() -> None:
    adapter = TradingAgentsAdapter({"enabled": True, "mode": "mock", "dry_run": True})
    evidence = adapter.collect({"path": str(FIXTURE_PATH)})[0]
    assert evidence.normalized_payload["recommended_action"] == "PAPER_TRADE"
    assert evidence.real_execution_allowed is False
    assert evidence.normalized_payload["paper_execution_max"] is True


def test_tradingagents_without_validation_flags_degrades_buy_to_watch() -> None:
    adapter = TradingAgentsAdapter({"enabled": True, "mode": "mock", "dry_run": True})
    evidence = adapter.collect({"committee_payload": {"recommended_action": "BUY", "confidence": 0.7, "dissent_level": 0.2, "validation_flags": False}})[0]
    assert evidence.normalized_payload["recommended_action"] == "WATCH"
