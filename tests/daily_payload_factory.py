"""Helper for building synthetic data/daily_payload/ trees in tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_daily_payload(
    base: Path,
    *,
    run_date: str = "2026-05-22",
    verified: list[dict[str, Any]] | None = None,
    closed: list[dict[str, Any]] | None = None,
    sold: list[str] | None = None,
    not_owned: list[str] | None = None,
    closed_or_sold: list[str] | None = None,
    movers: list[dict[str, Any]] | None = None,
    news: list[dict[str, Any]] | None = None,
    filings: list[dict[str, Any]] | None = None,
    source_health: str = "MISSING_OR_UNVERIFIED",
    yesterday_final: list[str] | None = None,
    yesterday_watchlist: list[str] | None = None,
    yesterday_avoids: list[str] | None = None,
) -> Path:
    """Write the nine payload files into ``base`` and return ``base``."""
    base.mkdir(parents=True, exist_ok=True)

    def dump(name: str, payload: Any) -> None:
        (base / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    dump("verified_current_holdings.json", {"run_date": run_date, "positions": verified or []})
    dump("closed_positions.json", {"run_date": run_date, "positions": closed or []})
    dump("sold_positions.json", {"run_date": run_date, "tickers": sold or []})
    dump(
        "do_not_treat_as_open.json",
        {
            "run_date": run_date,
            "not_owned_do_not_manage": not_owned or [],
            "closed_or_sold_positions": closed_or_sold or [],
            "operator_note": "test override",
        },
    )
    dump(
        "today_market_snapshot.json",
        {
            "run_date": run_date,
            "snapshot_timestamp_utc": None,
            "source_health": source_health,
            "indices": [],
            "rates": [],
            "commodities": [],
            "fx": [],
            "regime_notes": [],
        },
    )
    dump("today_price_movers.json", {"run_date": run_date, "movers": movers or []})
    dump("today_news_events.json", {"run_date": run_date, "events": news or []})
    dump("today_filings_events.json", {"run_date": run_date, "events": filings or []})
    dump(
        "yesterday_final_candidates.json",
        {
            "run_date": run_date,
            "final_candidates": yesterday_final or [],
            "watchlist": yesterday_watchlist or [],
            "avoids": yesterday_avoids or [],
        },
    )
    return base


def write_stale_ledger(base: Path, open_positions: list[dict[str, Any]], signal_ledger: list[dict[str, Any]]) -> tuple[Path, Path]:
    """Write throwaway stale open_positions/signal_ledger files; return paths."""
    base.mkdir(parents=True, exist_ok=True)
    op = base / "open_positions.json"
    sl = base / "signal_ledger.json"
    op.write_text(json.dumps(open_positions, indent=2), encoding="utf-8")
    sl.write_text(json.dumps(signal_ledger, indent=2), encoding="utf-8")
    return op, sl


def holding(ticker: str, *, status: str = "OPEN") -> dict[str, Any]:
    return {
        "ticker": ticker,
        "normalized_ticker": ticker,
        "status": status,
        "quantity": 1.0,
        "entry_price": 10.0,
        "currency": "USD",
        "human_confirmed": True,
        "broker_confirmed": False,
    }
