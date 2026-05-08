from __future__ import annotations

from pathlib import Path
import shutil
import uuid

import pytest
from scripts.external_adapters.base import ExternalAdapterStatus, ExternalExecutionPermission
from scripts.external_adapters.poly_data_adapter import PolyDataAdapter


@pytest.fixture
def tmp_path() -> Path:
    root = Path("runtime/poly_data_test_tmp")
    root.mkdir(parents=True, exist_ok=True)
    temp_dir = root / f"poly_data_{uuid.uuid4().hex[:8]}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_poly_data_csv_parsing_and_bad_row_handling(tmp_path: Path) -> None:
    _write_text(
        tmp_path / "markets.csv",
        "\n".join(
            [
                "market_id,question,price,category",
                "MKT1,Will oil close above 80 this month?,0.62,commodities",
                "MKT2,,0.55,invalid",
                "MKT3,Will inflation cool next quarter?,1.20,macro",
            ]
        ),
    )
    _write_text(
        tmp_path / "trades.csv",
        "\n".join(
            [
                "trade_id,market_question,price,usd_amount,token_amount",
                "T1,Will oil close above 80 this month?,0.61,150,200",
                "T2,Bad negative row,0.40,-10,5",
                "T3,Invalid price row,1.20,20,5",
            ]
        ),
    )
    _write_text(
        tmp_path / "orderFilled.csv",
        "\n".join(
            [
                "id,question,execution_price,usd_amount,token_amount",
                "OF1,Will inflation cool next quarter?,0.48,80,120",
            ]
        ),
    )

    adapter = PolyDataAdapter({"enabled": True, "fallback_path": str(tmp_path), "max_rows": 100})
    evidence = adapter.collect()[0]

    assert evidence.adapter_status == ExternalAdapterStatus.AVAILABLE
    assert evidence.execution_permission == ExternalExecutionPermission.WATCH_ONLY
    assert evidence.real_execution_allowed is False
    assert evidence.license_boundary
    assert evidence.data_truth_origin
    assert len(evidence.normalized_payload["markets"]) == 1
    assert len(evidence.normalized_payload["trades"]) == 2
    assert any("without question" in warning for warning in evidence.warnings)
    assert any("invalid price" in warning for warning in evidence.warnings)
    assert any("negative amounts" in warning for warning in evidence.warnings)


def test_poly_data_missing_path_degrades_gracefully() -> None:
    adapter = PolyDataAdapter(
        {"enabled": True, "fallback_path": "tests/fixtures/external_adapters/missing_poly_data"}
    )
    evidence = adapter.collect()[0]
    assert evidence.adapter_status == ExternalAdapterStatus.UNAVAILABLE
    assert evidence.real_execution_allowed is False


def test_poly_data_empty_csv_degrades_without_crashing(tmp_path: Path) -> None:
    _write_text(
        tmp_path / "markets.csv",
        "market_id,question,price,category\n",
    )
    _write_text(
        tmp_path / "trades.csv",
        "trade_id,market_question,price,usd_amount,token_amount\n",
    )

    adapter = PolyDataAdapter({"enabled": True, "fallback_path": str(tmp_path), "max_rows": 100})
    evidence = adapter.collect()[0]

    assert evidence.adapter_status == ExternalAdapterStatus.DEGRADED
    assert evidence.normalized_payload["markets"] == []
    assert evidence.normalized_payload["trades"] == []
    assert evidence.license_boundary
    assert evidence.data_truth_origin
    assert evidence.real_execution_allowed is False
