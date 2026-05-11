"""
Phase F — Global Security Master Discovery (advisory-only).

Discovers security metadata for a list of symbols via yfinance and upserts
records into the global_securities SQLite table. Also loads seed data from
configs/global_securities_master.yaml on first run.

yfinance is imported lazily — this module is safe to import in CI and tests
without yfinance installed. Network calls only happen inside discover_symbol().

ADVISORY ONLY — No broker API. No execution. No order placement. No private keys.
Every stored record carries:
  advisory_status      = ADVISORY_ONLY
  execution_gate       = LOCKED
  human_review_required = True
  ai_execution_count   = 0
  broker_api_called    = False
  broker_order_id      = NONE

Usage
-----
    # Discover specific symbols (dry-run, prints JSON):
    python scripts/global_security_master_discovery.py --symbols SBIN.NS,2002.TW

    # Write to DB:
    python scripts/global_security_master_discovery.py --symbols SBIN.NS,2002.TW --write

    # Seed all symbols from YAML config and discover:
    python scripts/global_security_master_discovery.py --seed-from-config --write

    # Discover listed AND known aliases (second run detects newly-listed symbols):
    python scripts/global_security_master_discovery.py --seed-from-config --write --check-aliases
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_GATE = "LOCKED"
_AI_EXECUTION_COUNT = 0

_CONFIG_PATH = REPO_ROOT / "configs" / "global_securities_master.yaml"


# ---------------------------------------------------------------------------
# Config loader (yaml optional — falls back to empty)
# ---------------------------------------------------------------------------

def _load_yaml_config() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        return {}
    try:
        import yaml  # type: ignore[import]
        return yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except ImportError:
        pass
    # Minimal YAML-free fallback: parse only simple key: value lines
    return {}


def get_seed_securities() -> list[dict[str, Any]]:
    """Return the list of seed security dicts from global_securities_master.yaml."""
    cfg = _load_yaml_config()
    raw = cfg.get("securities", [])
    return [s for s in raw if isinstance(s, dict) and s.get("canonical_symbol")]


def get_seed_aliases() -> list[dict[str, Any]]:
    """Return the list of alias dicts from global_securities_master.yaml."""
    cfg = _load_yaml_config()
    raw = cfg.get("aliases", [])
    return [a for a in raw if isinstance(a, dict) and a.get("alias") and a.get("canonical_symbol")]


# ---------------------------------------------------------------------------
# yfinance discovery (lazy import — safe for CI)
# ---------------------------------------------------------------------------

def discover_symbol(
    symbol: str,
) -> dict[str, Any]:
    """Fetch metadata for *symbol* via yfinance.

    Returns an advisory-stamped dict. If yfinance is unavailable or the symbol
    cannot be fetched, returns a minimal stub dict with active=False.
    No network call occurs until this function is called.
    """
    sym = symbol.strip().upper()
    base: dict[str, Any] = {
        "canonical_symbol": sym,
        "yahoo_symbol": sym,
        "name": "",
        "exchange_code": "",
        "exchange_name": "",
        "country": "",
        "currency": None,
        "asset_type": "EQUITY",
        "sector": None,
        "industry": None,
        "isin": None,
        "active": True,
        "source": "yfinance_discovery",
        "advisory_status": _ADVISORY_STATUS,
        "execution_gate": _EXECUTION_GATE,
        "human_review_required": True,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": False,
        "broker_order_id": "NONE",
    }

    try:
        import yfinance as yf  # lazy import — advisory read-only
    except ImportError:
        base["source"] = "yfinance_unavailable"
        base["active"] = False
        return base

    try:
        ticker = yf.Ticker(sym)
        info: dict[str, Any] = ticker.info or {}
    except Exception as exc:
        base["source"] = f"yfinance_error:{exc}"
        base["active"] = False
        return base

    if not info or not isinstance(info, dict):
        base["active"] = False
        return base

    # Conservative stale/delisted detection
    market_state = str(info.get("marketState") or "").upper()
    quote_type = str(info.get("quoteType") or "EQUITY").upper()
    regular_price = info.get("regularMarketPrice") or info.get("currentPrice")

    active = True
    if market_state in {"CLOSED", "PRE", "POST"}:
        active = True  # normal closed-market state
    if regular_price is None:
        active = False  # no price = likely delisted or invalid

    asset_type_map = {
        "EQUITY": "EQUITY",
        "ETF": "ETF",
        "MUTUALFUND": "FUND",
        "INDEX": "INDEX",
        "CRYPTOCURRENCY": "CRYPTO",
        "CURRENCY": "FX",
        "FUTURE": "FUTURE",
        "OPTION": "OPTION",
    }
    asset_type = asset_type_map.get(quote_type, "EQUITY")

    base.update({
        "name": str(info.get("longName") or info.get("shortName") or sym),
        "exchange_code": str(info.get("exchange") or ""),
        "exchange_name": str(info.get("fullExchangeName") or ""),
        "country": str(info.get("country") or ""),
        "currency": info.get("currency"),
        "asset_type": asset_type,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "isin": info.get("isin"),
        "active": active,
        "source": "yfinance_discovery",
    })
    return base


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------

def _upsert_from_dict(
    entry: dict[str, Any],
    db_path: Path | None = None,
) -> bool:
    """Upsert a security from a dict (yaml seed or discovered). Returns True if inserted."""
    try:
        from scripts.persistence import upsert_global_security
    except ModuleNotFoundError:
        from persistence import upsert_global_security  # type: ignore[no-redef]

    kwargs: dict = {} if db_path is None else {"db_path": db_path}
    return upsert_global_security(
        canonical_symbol=str(entry.get("canonical_symbol", "")),
        name=str(entry.get("name", "")),
        exchange_code=str(entry.get("exchange_code", "")),
        exchange_name=str(entry.get("exchange_name", "")),
        country=str(entry.get("country", "")),
        currency=entry.get("currency"),
        asset_type=str(entry.get("asset_type", "EQUITY")),
        sector=entry.get("sector"),
        industry=entry.get("industry"),
        isin=entry.get("isin"),
        economy_rank=entry.get("economy_rank"),
        provider_symbol=str(entry.get("provider_symbol") or entry.get("canonical_symbol", "")),
        yahoo_symbol=str(entry.get("yahoo_symbol") or entry.get("canonical_symbol", "")),
        active=bool(entry.get("active", True)),
        source=str(entry.get("source", "")),
        raw_payload={k: v for k, v in entry.items()
                     if k not in ("advisory_status", "execution_gate",
                                  "human_review_required", "ai_execution_count",
                                  "broker_api_called", "broker_order_id")},
        **kwargs,
    )


def _upsert_alias(
    alias_entry: dict[str, Any],
    db_path: Path | None = None,
) -> bool:
    try:
        from scripts.persistence import upsert_security_alias
    except ModuleNotFoundError:
        from persistence import upsert_security_alias  # type: ignore[no-redef]

    kwargs: dict = {} if db_path is None else {"db_path": db_path}
    return upsert_security_alias(
        alias=str(alias_entry.get("alias", "")),
        canonical_symbol=str(alias_entry.get("canonical_symbol", "")),
        confidence=float(alias_entry.get("confidence", 1.0)),
        source=str(alias_entry.get("source", "config_seed")),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Main discovery logic
# ---------------------------------------------------------------------------

def seed_from_config(
    write: bool = False,
    db_path: Path | None = None,
) -> tuple[int, int]:
    """Load seed securities and aliases from YAML config. Returns (upserted, alias_upserted)."""
    securities = get_seed_securities()
    aliases = get_seed_aliases()
    upserted = 0
    alias_upserted = 0

    if not write:
        for s in securities:
            print(json.dumps(s))
        for a in aliases:
            print(json.dumps(a))
        return len(securities), len(aliases)

    for s in securities:
        try:
            _upsert_from_dict(s, db_path=db_path)
            upserted += 1
        except Exception as exc:
            print(f"  WARNING: seed upsert failed for {s.get('canonical_symbol')}: {exc}", file=sys.stderr)

    for a in aliases:
        try:
            _upsert_alias(a, db_path=db_path)
            alias_upserted += 1
        except Exception as exc:
            print(f"  WARNING: alias upsert failed for {a.get('alias')}: {exc}", file=sys.stderr)

    return upserted, alias_upserted


def discover_and_upsert(
    symbols: list[str],
    write: bool = False,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Discover metadata for *symbols* and optionally write to DB. Returns list of result dicts."""
    results = []
    for sym in symbols:
        result = discover_symbol(sym)
        if not write:
            print(json.dumps(result))
        else:
            try:
                inserted = _upsert_from_dict(result, db_path=db_path)
                result["db_action"] = "inserted" if inserted else "updated"
            except Exception as exc:
                result["db_error"] = str(exc)
            print(f"  {sym}: {result.get('db_action', result.get('db_error', 'dry-run'))}")
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase F: Global security master discovery (advisory-only).\n"
            "Fetches metadata via yfinance and upserts into global_securities table.\n"
            "No broker API. No execution. No order placement."
        ),
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbol list to discover (e.g. SBIN.NS,2002.TW)",
    )
    parser.add_argument(
        "--seed-from-config",
        action="store_true",
        dest="seed_from_config",
        help="Load all securities and aliases from configs/global_securities_master.yaml",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write to DB (default: dry-run, prints JSON to stdout)",
    )
    parser.add_argument(
        "--check-aliases",
        action="store_true",
        dest="check_aliases",
        help="Also discover canonical targets of all known aliases (detects new listings)",
    )
    args = parser.parse_args(argv)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    if not args.write:
        print("[dry-run] No DB writes. Use --write to persist.", file=sys.stderr)

    if args.seed_from_config:
        n_sec, n_alias = seed_from_config(write=args.write)
        print(
            f"Config seed: {n_sec} securities, {n_alias} aliases "
            f"({'written' if args.write else 'dry-run'})."
        )

    if symbols:
        results = discover_and_upsert(symbols, write=args.write)
        print(
            f"Discovery: {len(results)} symbol(s) processed "
            f"({'written' if args.write else 'dry-run'})."
        )

    if args.check_aliases and args.write:
        try:
            from scripts.persistence import search_global_securities
        except ModuleNotFoundError:
            from persistence import search_global_securities  # type: ignore[no-redef]
        # Re-discover all known symbols to detect new listings / delistings
        all_secs = search_global_securities("%", limit=500)
        all_syms = [s["canonical_symbol"] for s in all_secs]
        print(f"Re-discovering {len(all_syms)} known symbols for freshness check...")
        discover_and_upsert(all_syms, write=True)


if __name__ == "__main__":
    main()
