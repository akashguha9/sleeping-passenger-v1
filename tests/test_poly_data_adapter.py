from __future__ import annotations

from pathlib import Path

from scripts.external_adapters.base import ExternalAdapterStatus, ExternalExecutionPermission
from scripts.external_adapters.poly_data_adapter import PolyDataAdapter


FIXTURE_ROOT = Path("tests/fixtures/external_adapters/poly_data")


def test_poly_data_csv_parsing_and_bad_row_handling() -> None:
    adapter = PolyDataAdapter({"enabled": True, "fallback_path": str(FIXTURE_ROOT), "max_rows": 100})
    evidence = adapter.collect()[0]
    assert evidence.adapter_status == ExternalAdapterStatus.AVAILABLE
    assert evidence.execution_permission == ExternalExecutionPermission.WATCH_ONLY
    assert evidence.real_execution_allowed is False
    assert len(evidence.normalized_payload["markets"]) == 1
    assert len(evidence.normalized_payload["trades"]) >= 2
    assert evidence.warnings


def test_poly_data_missing_path_degrades_gracefully() -> None:
    adapter = PolyDataAdapter({"enabled": True, "fallback_path": "tests/fixtures/external_adapters/missing_poly_data"})
    evidence = adapter.collect()[0]
    assert evidence.adapter_status == ExternalAdapterStatus.UNAVAILABLE
    assert evidence.real_execution_allowed is False
