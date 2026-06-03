"""Minimum viable fresh daily universe (set U_static).

The daily discovery pipeline must never go dark. Even when no live price/news/
filing provider is wired, the system needs a *minimum viable* universe of names
to scan, score, and route to research. This module is the single source of that
universe.

    U_static = the tickers returned by :func:`minimum_universe_tickers`

These names are *discovery candidates only*. Universe membership NEVER implies
portfolio ownership — portfolio-management permission still comes solely from
the Portfolio Truth Gate (H = V \\ (C ∪ S ∪ D)). A ticker can be in U_static and
still be DO_NOT_TREAT_AS_OPEN / CLOSED_OR_SOLD (e.g. GLD, TLT, TIP).

Design rules (mirrors ``daily_payload`` conventions):
    * Pure module: importing has no side effects.
    * The canonical universe is embedded as :data:`DEFAULT_UNIVERSE` so the
      discovery gate always has a universe even if the YAML override is missing
      or unparseable. ``config/minimum_daily_universe.yaml`` is an operator-
      editable mirror; when present and valid it is merged over the defaults.
    * Never fabricate live data — the universe carries no price/freshness; those
      are filled by the live builders and labelled honestly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from scripts.daily_payload import normalize_ticker
    from scripts.runtime_common import REPO_ROOT
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from daily_payload import normalize_ticker
    from runtime_common import REPO_ROOT


MINIMUM_UNIVERSE_PATH = REPO_ROOT / "config" / "minimum_daily_universe.yaml"

# Per-bucket defaults applied to every ticker in that bucket unless the ticker
# row overrides them. Keeps the embedded table compact and DRY.
BUCKET_DEFAULTS: dict[str, dict[str, str]] = {
    "US_MEGA_CAP": {"market": "US", "country": "United States", "asset_type": "equity", "default_risk_band": "core"},
    "DEFENSE": {"market": "US", "country": "United States", "asset_type": "equity", "default_risk_band": "core"},
    "ENERGY": {"market": "US", "country": "United States", "asset_type": "equity", "default_risk_band": "core"},
    "SEMIS": {"market": "US", "country": "United States", "asset_type": "equity", "default_risk_band": "core"},
    "INDIA_LARGE_CAP": {"market": "India", "country": "India", "asset_type": "equity", "default_risk_band": "core"},
    "EUROPE_LARGE_CAP": {"market": "Europe", "country": "Europe", "asset_type": "equity", "default_risk_band": "core"},
    "MACRO_ETFS": {"market": "US", "country": "United States", "asset_type": "etf", "default_risk_band": "macro_proxy"},
    "HIGH_BETA_WATCH": {"market": "US", "country": "United States", "asset_type": "equity", "default_risk_band": "high_beta"},
}

# Raw table: bucket -> list of (ticker, name, optional per-ticker overrides).
# Overrides only carry fields that differ from the bucket defaults (mostly the
# country/market of ADRs and the short ``notes`` string).
_RAW: dict[str, list[tuple[str, str, dict[str, str]]]] = {
    "US_MEGA_CAP": [
        ("AAPL", "Apple Inc.", {"notes": "Mega-cap tech bellwether"}),
        ("MSFT", "Microsoft Corp", {"notes": "Mega-cap software/AI"}),
        ("NVDA", "NVIDIA Corp", {"notes": "AI/semiconductor leadership"}),
        ("AMZN", "Amazon.com Inc.", {"notes": "Consumer/cloud mega-cap"}),
        ("META", "Meta Platforms", {"notes": "Ad/AI mega-cap"}),
        ("GOOGL", "Alphabet Inc.", {"notes": "Search/AI mega-cap"}),
        ("TSLA", "Tesla Inc.", {"notes": "High-beta EV/AI"}),
    ],
    "DEFENSE": [
        ("RTX", "RTX Corp", {"notes": "Defense/geopolitical sensitivity"}),
        ("LMT", "Lockheed Martin", {"notes": "Defense prime"}),
        ("NOC", "Northrop Grumman", {"notes": "Defense prime"}),
        ("GD", "General Dynamics", {"notes": "Defense prime"}),
        ("LHX", "L3Harris Technologies", {"notes": "Defense/comms"}),
    ],
    "ENERGY": [
        ("XOM", "Exxon Mobil", {"notes": "Integrated oil major"}),
        ("CVX", "Chevron Corp", {"notes": "Integrated oil major"}),
        ("SHEL", "Shell plc (ADR)", {"country": "United Kingdom", "notes": "Oil major ADR"}),
        ("TTE", "TotalEnergies (ADR)", {"country": "France", "notes": "Oil major ADR"}),
        ("BP", "BP plc (ADR)", {"country": "United Kingdom", "notes": "Oil major ADR"}),
    ],
    "SEMIS": [
        ("TSM", "Taiwan Semiconductor (ADR)", {"country": "Taiwan", "notes": "Foundry leader ADR"}),
        ("ASML", "ASML Holding (ADR)", {"country": "Netherlands", "notes": "EUV litho ADR"}),
        ("AMD", "Advanced Micro Devices", {"notes": "CPU/GPU"}),
        ("AVGO", "Broadcom Inc.", {"notes": "Semis/networking"}),
        ("INTC", "Intel Corp", {"notes": "CPU/foundry turnaround"}),
        ("MU", "Micron Technology", {"notes": "Memory cycle"}),
    ],
    "INDIA_LARGE_CAP": [
        ("RELIANCE.NS", "Reliance Industries", {"notes": "India conglomerate"}),
        ("HDFCBANK.NS", "HDFC Bank", {"notes": "India private bank"}),
        ("ICICIBANK.NS", "ICICI Bank", {"notes": "India private bank"}),
        ("BHARTIARTL.NS", "Bharti Airtel", {"notes": "India telecom"}),
        ("INFY.NS", "Infosys", {"notes": "India IT services"}),
        ("TCS.NS", "Tata Consultancy Services", {"notes": "India IT services"}),
    ],
    "EUROPE_LARGE_CAP": [
        ("SAP.DE", "SAP SE", {"market": "Germany", "country": "Germany", "notes": "EU enterprise software"}),
        ("ASML.AS", "ASML Holding", {"market": "Netherlands", "country": "Netherlands", "notes": "EUV litho (Amsterdam line)"}),
        ("SIE.DE", "Siemens AG", {"market": "Germany", "country": "Germany", "notes": "EU industrials"}),
        ("RHM.DE", "Rheinmetall AG", {"market": "Germany", "country": "Germany", "notes": "EU defense/geopolitical"}),
        ("AIR.PA", "Airbus SE", {"market": "France", "country": "France", "notes": "EU aerospace/defense"}),
    ],
    "MACRO_ETFS": [
        ("GLD", "SPDR Gold Shares", {"notes": "Gold safe-haven proxy"}),
        ("TLT", "20+ Year Treasury ETF", {"notes": "Long-duration proxy"}),
        ("TIP", "TIPS Bond ETF", {"notes": "Inflation-protected bonds proxy"}),
        ("EWG", "Germany ETF", {"notes": "Germany equity proxy"}),
        ("INDA", "India ETF", {"notes": "India equity proxy"}),
        ("FXI", "China Large-Cap ETF", {"notes": "China equity proxy"}),
    ],
    "HIGH_BETA_WATCH": [
        ("ZIM", "ZIM Integrated Shipping", {"notes": "High-beta shipping"}),
        ("ANET", "Arista Networks", {"notes": "High-beta networking/AI"}),
        ("PLTR", "Palantir Technologies", {"notes": "High-beta software"}),
        ("SMCI", "Super Micro Computer", {"notes": "High-beta AI hardware"}),
    ],
}


def _build_default_universe() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bucket, entries in _RAW.items():
        defaults = BUCKET_DEFAULTS[bucket]
        for ticker, name, overrides in entries:
            row = {
                "ticker": normalize_ticker(ticker),
                "name": name,
                "bucket": bucket,
                "market": overrides.get("market", defaults["market"]),
                "country": overrides.get("country", defaults["country"]),
                "asset_type": overrides.get("asset_type", defaults["asset_type"]),
                "default_risk_band": overrides.get("default_risk_band", defaults["default_risk_band"]),
                "notes": overrides.get("notes", ""),
            }
            rows.append(row)
    return rows


# Canonical embedded universe — the always-available fallback.
DEFAULT_UNIVERSE: list[dict[str, Any]] = _build_default_universe()
DEFAULT_BUCKETS: tuple[str, ...] = tuple(_RAW.keys())


def _coerce_rows_from_yaml(data: Any) -> list[dict[str, Any]] | None:
    """Parse the YAML override into the resolved row shape, or None if invalid.

    Accepts a mapping ``buckets: {BUCKET: [ {ticker, name, ...}, ... ]}``. Any
    missing per-ticker field is backfilled from BUCKET_DEFAULTS. Returns None
    when the structure is unusable so the caller falls back to DEFAULT_UNIVERSE.
    """
    if not isinstance(data, dict):
        return None
    buckets = data.get("buckets")
    if not isinstance(buckets, dict) or not buckets:
        return None
    rows: list[dict[str, Any]] = []
    for bucket, entries in buckets.items():
        if not isinstance(entries, list):
            continue
        defaults = BUCKET_DEFAULTS.get(str(bucket), {})
        for entry in entries:
            if isinstance(entry, str):
                entry = {"ticker": entry}
            if not isinstance(entry, dict):
                continue
            ticker = normalize_ticker(entry.get("ticker"))
            if not ticker:
                continue
            notes = str(entry.get("notes") or "")
            # Filter symbols flagged as not yet wired up to a real data
            # provider. The backtest harness writes this tag for tickers
            # yfinance returned no candles for, so they don't silently
            # enter the daily discovery pool.
            if "needs_provider_mapping" in notes:
                continue
            rows.append(
                {
                    "ticker": ticker,
                    "name": str(entry.get("name") or ticker),
                    "bucket": str(bucket),
                    "market": str(entry.get("market") or defaults.get("market", "US")),
                    "country": str(entry.get("country") or defaults.get("country", "United States")),
                    "sector": str(entry.get("sector") or defaults.get("sector", "")),
                    "asset_type": str(entry.get("asset_type") or defaults.get("asset_type", "equity")),
                    "default_risk_band": str(
                        entry.get("default_risk_band") or defaults.get("default_risk_band", "watch")
                    ),
                    "notes": notes,
                }
            )
    return rows or None


def load_minimum_universe(path: Path | None = None) -> dict[str, Any]:
    """Return the resolved minimum universe.

    Tries the YAML override at ``path`` (default
    ``config/minimum_daily_universe.yaml``); on any failure it returns the
    embedded :data:`DEFAULT_UNIVERSE` so the discovery gate is never starved.
    """
    target = path or MINIMUM_UNIVERSE_PATH
    rows: list[dict[str, Any]] | None = None
    source = "embedded_default"
    if target.exists():
        try:
            from src.utils.config_loader import load_yaml_config

            data = load_yaml_config(target)
            rows = _coerce_rows_from_yaml(data)
            if rows:
                source = "yaml_override"
        except Exception:
            rows = None
    if not rows:
        rows = [dict(r) for r in DEFAULT_UNIVERSE]
        source = "embedded_default"

    buckets: dict[str, list[str]] = {}
    for row in rows:
        buckets.setdefault(row["bucket"], [])
        if row["ticker"] not in buckets[row["bucket"]]:
            buckets[row["bucket"]].append(row["ticker"])
    return {
        "source": source,
        "tickers": rows,
        "buckets": buckets,
        "ticker_count": len(rows),
        "bucket_count": len(buckets),
    }


def minimum_universe_tickers(path: Path | None = None) -> list[str]:
    """Ordered, de-duplicated list of normalized tickers in U_static."""
    out: list[str] = []
    for row in load_minimum_universe(path)["tickers"]:
        ticker = row["ticker"]
        if ticker and ticker not in out:
            out.append(ticker)
    return out


def minimum_universe_metadata(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Map normalized ticker -> its universe metadata row."""
    return {row["ticker"]: row for row in load_minimum_universe(path)["tickers"]}


def minimum_universe_records(path: Path | None = None) -> list[dict[str, Any]]:
    """Return the resolved per-ticker universe rows (full metadata)."""
    return [dict(row) for row in load_minimum_universe(path)["tickers"]]


def universe_by_bucket(path: Path | None = None) -> dict[str, list[str]]:
    """Return ``{bucket: [ticker, ...]}`` for the resolved universe."""
    return dict(load_minimum_universe(path)["buckets"])


def build_static_universe_payload(
    run_date: str,
    generated_at_utc: str,
    path: Path | None = None,
) -> dict[str, Any]:
    """Build the static-universe payload envelope (honestly labelled UNVERIFIED).

    This is the snapshot of U_static the operator can inspect. It carries no
    live price/freshness data, so every record is labelled UNVERIFIED and the
    envelope is is_live=false.
    """
    resolved = load_minimum_universe(path)
    return {
        "run_date": run_date,
        "generated_at_utc": generated_at_utc,
        "source_health": "UNVERIFIED",
        "provider": "STATIC_UNIVERSE_FALLBACK",
        "is_live": False,
        "universe_source": resolved["source"],
        "ticker_count": resolved["ticker_count"],
        "bucket_count": resolved["bucket_count"],
        "buckets": resolved["buckets"],
        "records": resolved["tickers"],
    }


__all__ = [
    "MINIMUM_UNIVERSE_PATH",
    "BUCKET_DEFAULTS",
    "DEFAULT_UNIVERSE",
    "DEFAULT_BUCKETS",
    "load_minimum_universe",
    "minimum_universe_tickers",
    "minimum_universe_metadata",
    "minimum_universe_records",
    "universe_by_bucket",
    "build_static_universe_payload",
]
