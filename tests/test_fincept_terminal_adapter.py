from __future__ import annotations

from pathlib import Path

from scripts.external_adapters.fincept_terminal_adapter import FinceptTerminalAdapter


FIXTURE_ROOT = Path("tests/fixtures/external_adapters/fincept")


def test_fincept_exported_analytics_parsing() -> None:
    adapter = FinceptTerminalAdapter({"enabled": True, "fallback_path": str(FIXTURE_ROOT)})
    evidence = adapter.collect()[0]
    assert evidence.real_execution_allowed is False
    assert evidence.normalized_payload["analytics"]
    assert evidence.license_boundary.startswith("AGPL-3.0/commercial")
