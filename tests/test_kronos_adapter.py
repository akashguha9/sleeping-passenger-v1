from __future__ import annotations

from pathlib import Path

from scripts.external_adapters.kronos_adapter import KronosAdapter


FIXTURE_PATH = Path("tests/fixtures/external_adapters/kronos/sample_ohlcv.csv")


def test_kronos_optional_import_and_technical_only_evidence() -> None:
    adapter = KronosAdapter({"enabled": True, "lazy_import": True, "mock_mode": True})
    evidence = adapter.collect({"path": str(FIXTURE_PATH)})[0]
    assert evidence.normalized_payload["technical_evidence_only"] is True
    assert evidence.real_execution_allowed is False
    assert evidence.execution_permission.value == "WATCH_ONLY"


def test_kronos_action_sanitization() -> None:
    adapter = KronosAdapter({"enabled": True, "mock_mode": True})
    evidence = adapter.collect({"path": str(FIXTURE_PATH), "action": "BUY", "validation_flags": True})[0]
    assert evidence.normalized_payload["sanitized_action"] == "WATCH"
