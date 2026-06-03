"""Universe loader filters rows tagged ``needs_provider_mapping`` and preserves
the optional ``sector`` field used by the diversification cap."""
from __future__ import annotations

from pathlib import Path

from scripts.minimum_daily_universe import load_minimum_universe


def _write_yaml(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_provider_mapping_rows_are_dropped(tmp_path: Path) -> None:
    yaml_file = tmp_path / "u.yaml"
    _write_yaml(yaml_file, """
buckets:
  TEST_BUCKET:
    - {ticker: GOOD, name: "Good Co", market: US, country: "United States", sector: Tech, asset_type: equity, default_risk_band: core, notes: "ok"}
    - {ticker: DEAD, name: "Dead Co", market: US, country: "United States", sector: Tech, asset_type: equity, default_risk_band: core, notes: "needs_provider_mapping — yfinance returned no data"}
""")
    resolved = load_minimum_universe(yaml_file)
    tickers = [row["ticker"] for row in resolved["tickers"]]
    assert "GOOD" in tickers
    assert "DEAD" not in tickers


def test_sector_field_is_preserved(tmp_path: Path) -> None:
    yaml_file = tmp_path / "u.yaml"
    _write_yaml(yaml_file, """
buckets:
  TEST_BUCKET:
    - {ticker: AAA, name: "Alpha", market: US, country: "United States", sector: Financials, asset_type: equity, default_risk_band: core, notes: ""}
""")
    resolved = load_minimum_universe(yaml_file)
    row = next(r for r in resolved["tickers"] if r["ticker"] == "AAA")
    assert row["sector"] == "Financials"


def test_missing_sector_defaults_to_empty(tmp_path: Path) -> None:
    yaml_file = tmp_path / "u.yaml"
    _write_yaml(yaml_file, """
buckets:
  TEST_BUCKET:
    - {ticker: AAA, name: "Alpha", market: US, country: "United States", asset_type: equity, default_risk_band: core, notes: ""}
""")
    resolved = load_minimum_universe(yaml_file)
    row = next(r for r in resolved["tickers"] if r["ticker"] == "AAA")
    assert row["sector"] == ""
