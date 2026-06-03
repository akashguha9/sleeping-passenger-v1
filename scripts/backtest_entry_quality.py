"""Validate the entry-quality gate against a real-OHLCV path backtest.

Reads a path-dependent backtest xlsx (the operator's `portfolio_path_backtest.xlsx`
shape, exported from the Excel sheet) and, for every position:

    1. Fetches daily OHLCV via yfinance for the ticker (and a local-market
       index for relative-strength).
    2. Computes the entry-quality score AS OF the buy date — using only
       candles up to and including that date.
    3. Re-walks the position forward from buy-date through `--as-of` (default:
       today) using true daily highs/lows; replays the TP1/TP2/runner/stop
       rules from the xlsx assumption block.
    4. Emits two side-by-side outcome columns: the xlsx "estimated" result and
       the real-OHLCV result, so we can spot divergence.

Output: a JSON report at ``runtime/backtest_entry_quality_report.json`` plus a
human-readable summary printed to stdout. All in-sample metrics are clearly
labeled as directional (n is tiny, one short window). NO threshold tuning is
based on these numbers — the harness exists to verify that the gate is
implementable on real data and to surface the entry-quality score that each
past winner / loser would have received.

Usage (local, with network access to Yahoo):
    python scripts/backtest_entry_quality.py \
        --xlsx /path/to/portfolio_path_backtest.xlsx \
        --as-of 2026-06-03 \
        --out runtime/backtest_entry_quality_report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    from scripts.entry_quality_gate import compute_entry_quality, load_entry_quality_config
    from scripts.execution_cost_model import book_trade_cost, load_cost_config
    from scripts.runtime_common import REPO_ROOT
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from entry_quality_gate import compute_entry_quality, load_entry_quality_config
    from execution_cost_model import book_trade_cost, load_cost_config
    from runtime_common import REPO_ROOT


DEFAULT_OUT = REPO_ROOT / "runtime" / "backtest_entry_quality_report.json"


# ---------------------------------------------------------------------------
# Ticker → yfinance symbol resolution
# ---------------------------------------------------------------------------
# The xlsx stores names like `NSE:BHARTIARTL`, `ETR:SAP`, `KRX:003550`. yfinance
# wants `BHARTIARTL.NS`, `SAP.DE`, `003550.KS`. This table mirrors the suffixes
# used by `configs/global_securities_master.yaml`.

_EXCHANGE_TO_YF_SUFFIX = {
    "NSE": ".NS",
    "BSE": ".BO",
    "ETR": ".DE",
    "EPA": ".PA",
    "AMS": ".AS",
    "LON": ".L",
    "TYO": ".T",
    "KRX": ".KS",
    "KOSDAQ": ".KQ",
    "ASX": ".AX",
    "TSX": ".TO",
    "TSXV": ".V",
    "MIL": ".MI",
    "BIT": ".MI",
    "BME": ".MC",
    "MAD": ".MC",
    "SIX": ".SW",
    "STO": ".ST",
    "OMX": ".ST",
    "WSE": ".WA",
    "VIE": ".VI",
    "BR":  ".BR",  # Euronext Brussels
    "ISE": ".IR",
    "SGX": ".SI",
    "HKEX": ".HK",
    "TWSE": ".TW",
    "B3": ".SA",
    "BMV": ".MX",
}
# US exchanges leave the symbol bare.
_US_EXCHANGES = {"NYSE", "NASDAQ", "NYSEARCA", "AMEX", "ARCA", "BATS"}

# Country code per exchange code.
_EXCHANGE_TO_COUNTRY = {
    "NYSE": "US", "NASDAQ": "US", "NYSEARCA": "US", "AMEX": "US", "ARCA": "US",
    "NSE": "IN", "BSE": "IN",
    "ETR": "DE", "EPA": "FR", "AMS": "NL", "BR": "BE",
    "LON": "GB", "TYO": "JP", "KRX": "KR", "KOSDAQ": "KR",
    "ASX": "AU", "TSX": "CA", "MIL": "IT", "BIT": "IT", "BME": "ES", "MAD": "ES",
    "SIX": "CH", "STO": "SE", "OMX": "SE", "WSE": "PL", "VIE": "AT",
    "ISE": "IE", "SGX": "SG", "HKEX": "HK", "TWSE": "TW", "B3": "BR", "BMV": "MX",
}

# Local-index proxies for relative-strength (yfinance symbols).
_INDEX_FOR_COUNTRY = {
    "US": "^GSPC", "IN": "^NSEI", "DE": "^GDAXI", "FR": "^FCHI",
    "GB": "^FTSE", "JP": "^N225", "KR": "^KS11", "NL": "^AEX",
    "IT": "FTSEMIB.MI", "ES": "^IBEX", "CH": "^SSMI", "AU": "^AXJO",
    "CA": "^GSPTSE", "SE": "^OMX", "PL": "^WIG20", "AT": "^ATX",
    "SG": "^STI", "HK": "^HSI", "TW": "^TWII", "BR": "^BVSP", "MX": "^MXX",
    "IE": "^ISEQ", "BE": "^BFX",
}


def to_yf_symbol(ticker: str) -> tuple[str, str]:
    """`NSE:BHARTIARTL` -> (`BHARTIARTL.NS`, country='IN')."""
    if ":" not in ticker:
        return ticker.strip().upper(), "US"
    exch, sym = ticker.split(":", 1)
    exch_u = exch.strip().upper()
    sym = sym.strip().upper()
    country = _EXCHANGE_TO_COUNTRY.get(exch_u, "?")
    if exch_u in _US_EXCHANGES:
        return sym, country
    suffix = _EXCHANGE_TO_YF_SUFFIX.get(exch_u, "")
    return (sym + suffix) if suffix else sym, country


# ---------------------------------------------------------------------------
# OHLCV fetch (lazy yfinance import)
# ---------------------------------------------------------------------------


def fetch_history(symbol: str, end: date, lookback_days: int = 400) -> list[dict[str, Any]]:
    try:
        import yfinance as yf
    except ImportError:
        print(
            "ERROR: yfinance not installed. Install with `pip install yfinance` "
            "and ensure network access to query.yahoo.com.",
            file=sys.stderr,
        )
        return []

    from datetime import timedelta

    start = end - timedelta(days=lookback_days)
    try:
        hist = yf.Ticker(symbol).history(
            start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
        )
    except Exception as exc:
        print(f"  WARN: yfinance fetch failed for {symbol}: {exc}", file=sys.stderr)
        return []
    if hist is None or hist.empty:
        return []
    candles: list[dict[str, Any]] = []
    for idx, row in hist.iterrows():
        try:
            d = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
        except Exception:
            continue
        candles.append({
            "date": d.isoformat(),
            "open": float(row.get("Open", 0.0) or 0.0),
            "high": float(row.get("High", 0.0) or 0.0),
            "low": float(row.get("Low", 0.0) or 0.0),
            "close": float(row.get("Close", 0.0) or 0.0),
            "volume": float(row.get("Volume", 0.0) or 0.0),
        })
    return candles


# ---------------------------------------------------------------------------
# xlsx parsing
# ---------------------------------------------------------------------------


def parse_backtest_xlsx(path: Path) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Return (strategy_assumptions, positions)."""
    import pandas as pd

    raw = pd.read_excel(path, sheet_name=0, header=None)
    # Header line for positions starts at row 12 (0-indexed) in the operator's
    # template — but we locate it by string match for robustness.
    header_row = None
    for i in range(min(40, len(raw))):
        if str(raw.iloc[i, 0]).strip().lower() == "date":
            header_row = i
            break
    if header_row is None:
        raise ValueError("Could not find position header row in xlsx")

    df = pd.read_excel(path, sheet_name=0, skiprows=header_row + 1, header=None,
                       names=["Date", "Ticker", "Ccy", "Buy", "Current", "HighEst",
                              "LowEst", "Alloc", "ReturnNow", "MaxGainEst",
                              "MaxDrawEst", "Result", "PLpct", "PLeur", "Status"])
    df = df[df["Date"].notna() & df["Ticker"].notna()].copy()
    # Drop the summary block rows that follow the position list.
    df = df[~df["Ticker"].astype(str).str.contains("SUMMARY", case=False, na=False)]
    df = df[df["Buy"].apply(lambda v: _is_num(v))]

    assumptions = {
        "tp1": 0.05, "tp1_book": 0.50,
        "tp2": 0.08, "tp2_book": 0.30,
        "runner": 0.20,
        "stop": -0.05,
        "alloc_eur": 50.0,
    }
    # Try to read assumptions from the header block if present.
    for i in range(header_row):
        k = str(raw.iloc[i, 0]).strip().lower()
        v = raw.iloc[i, 1]
        if not _is_num(v):
            continue
        v = float(v)
        if "tp1 target" in k:
            assumptions["tp1"] = v
        elif "tp1 book" in k:
            assumptions["tp1_book"] = v
        elif "tp2 target" in k:
            assumptions["tp2"] = v
        elif "tp2 book" in k:
            assumptions["tp2_book"] = v
        elif "runner" in k:
            assumptions["runner"] = v
        elif "stop" in k:
            assumptions["stop"] = v
        elif "alloc" in k:
            assumptions["alloc_eur"] = v

    positions: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        try:
            buy_date = _parse_date(row["Date"])
        except Exception:
            continue
        positions.append({
            "buy_date": buy_date.isoformat(),
            "ticker": str(row["Ticker"]).strip(),
            "buy_price": float(row["Buy"]),
            "currency": str(row.get("Ccy") or ""),
            "result_xlsx": str(row.get("Result") or ""),
            "status_xlsx": str(row.get("Status") or ""),
            "max_gain_est_xlsx": float(row["MaxGainEst"]) if _is_num(row["MaxGainEst"]) else None,
            "max_draw_est_xlsx": float(row["MaxDrawEst"]) if _is_num(row["MaxDrawEst"]) else None,
            "pl_pct_xlsx": float(row["PLpct"]) if _is_num(row["PLpct"]) else None,
        })
    return assumptions, positions


def _is_num(v: Any) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _parse_date(v: Any) -> date:
    if isinstance(v, datetime):
        return v.date()
    if hasattr(v, "to_pydatetime"):
        return v.to_pydatetime().date()
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date: {v!r}")


# ---------------------------------------------------------------------------
# Path-dependent outcome replay with REAL daily OHLCV
# ---------------------------------------------------------------------------


def walk_position(
    candles_after_buy: list[dict[str, Any]],
    buy_price: float,
    assumptions: dict[str, float],
    *,
    market: str | None = None,
    cost_config: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Replay TP1 / TP2 / runner / stop using true daily highs and lows.

    Convention (mirrors the xlsx):
        * On a day where both the TP and the stop are touched, the stop wins
          (more conservative). This matches the typical operator practice when
          intraday sequence is unknown.
        * The runner remains open until ``--as-of``; its mark is the final
          close in the window. P/L there is unrealized.
    """
    tp1 = assumptions["tp1"]; tp2 = assumptions["tp2"]
    tp1_book = assumptions["tp1_book"]; tp2_book = assumptions["tp2_book"]
    runner = assumptions["runner"]
    stop = assumptions["stop"]
    assert abs(tp1_book + tp2_book + runner - 1.0) < 1e-6, "book + runner must sum to 1.0"

    tp1_hit = False; tp2_hit = False; stopped = False
    max_gain = 0.0; max_draw = 0.0
    realized = 0.0
    open_fraction = 1.0
    days_to_tp1 = None; days_to_tp2 = None; days_to_stop = None

    for i, c in enumerate(candles_after_buy, start=1):
        hi_ret = (c["high"] - buy_price) / buy_price
        lo_ret = (c["low"] - buy_price) / buy_price
        max_gain = max(max_gain, hi_ret)
        max_draw = min(max_draw, lo_ret)

        if not stopped and lo_ret <= stop:
            # Stop hits the remaining open fraction at -5%.
            realized += open_fraction * stop
            open_fraction = 0.0
            stopped = True
            days_to_stop = i
            break

        if not tp1_hit and hi_ret >= tp1:
            realized += tp1_book * tp1
            open_fraction -= tp1_book
            tp1_hit = True
            days_to_tp1 = i
        if not tp2_hit and hi_ret >= tp2:
            realized += tp2_book * tp2
            open_fraction -= tp2_book
            tp2_hit = True
            days_to_tp2 = i

    # Mark the runner / unsold portion at the final close.
    if open_fraction > 1e-9 and candles_after_buy:
        final_ret = (candles_after_buy[-1]["close"] - buy_price) / buy_price
        unrealized = open_fraction * final_ret
    else:
        unrealized = 0.0

    if stopped:
        result = "Stopped"
        status = "Loss"
    elif tp1_hit and tp2_hit:
        result = "TP1+TP2"
        status = "Win"
    elif tp1_hit:
        result = "TP1 only"
        status = "Win"
    elif not candles_after_buy:
        result = "Open +"
        status = "Flat"
    else:
        final_ret = (candles_after_buy[-1]["close"] - buy_price) / buy_price
        if final_ret > 0:
            result, status = "Open +", "Win"
        elif final_ret < 0:
            result, status = "Open -", "Loss"
        else:
            result, status = "Open +", "Flat"

    # ---- Per-fill execution cost model -------------------------------------
    # Build the leg ledger that was ACTUALLY filled, then charge each leg its
    # own commission + minimum + exchange fee + half-spread + slippage, plus
    # a one-time FX round-trip on the lifecycle. This is the C3 fix: a
    # winner produces 3 commissioned exits, not 1.
    alloc = float(assumptions.get("alloc_eur", 50.0))
    tp1_book = assumptions["tp1_book"]; tp2_book = assumptions["tp2_book"]
    runner_frac = assumptions["runner"]
    legs: list[tuple[str, float]] = [("BUY", 1.0)]
    # Each TP that hit was its own commissioned exit, regardless of whether
    # the trade subsequently stopped on the remainder.
    if tp1_hit:
        legs.append(("SELL", tp1_book))
    if tp2_hit:
        legs.append(("SELL", tp2_book))
    if stopped:
        # The stop closes the remaining open fraction at -5% in one fill.
        sold_at_tps = (tp1_book if tp1_hit else 0.0) + (tp2_book if tp2_hit else 0.0)
        remainder = 1.0 - sold_at_tps
        if remainder > 1e-9:
            legs.append(("SELL", remainder))
    else:
        # The runner / unsold portion is marked, not sold, unless the operator
        # closes at as-of. Charge a runner-leg cost so the mark is realistic
        # if/when the position is exited; otherwise we'd be reporting net P/L
        # that ignores the inevitable exit cost.
        if open_fraction > 1e-9:
            legs.append(("SELL", open_fraction))
    cost = None
    cost_eur = 0.0
    if market:
        cost = book_trade_cost(
            alloc_eur=alloc, market=market, leg_fractions=legs,
            config=cost_config,
        )
        cost_eur = cost.total_eur

    strategy_pl_pct_gross = realized + unrealized
    pl_eur_gross = alloc * strategy_pl_pct_gross
    pl_eur_net = pl_eur_gross - cost_eur
    pl_pct_net = pl_eur_net / alloc if alloc else 0.0

    return {
        "result_real": result,
        "status_real": status,
        "realized_pct": round(realized, 6),
        "unrealized_pct": round(unrealized, 6),
        "strategy_pl_pct_real": round(strategy_pl_pct_gross, 6),
        "strategy_pl_eur_real_gross": round(pl_eur_gross, 4),
        "strategy_pl_eur_real_net": round(pl_eur_net, 4),
        "strategy_pl_pct_real_net": round(pl_pct_net, 6),
        "execution_cost_eur": round(cost_eur, 4),
        "execution_cost_detail": cost.as_dict() if cost else None,
        "max_gain_real": round(max_gain, 6),
        "max_draw_real": round(max_draw, 6),
        "tp1_hit": tp1_hit, "tp2_hit": tp2_hit, "stopped": stopped,
        "days_to_tp1": days_to_tp1, "days_to_tp2": days_to_tp2, "days_to_stop": days_to_stop,
        "bars_walked": len(candles_after_buy),
    }


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------


def aggregate_metrics(rows: list[dict[str, Any]], pl_key: str, status_key: str) -> dict[str, Any]:
    moved = [r for r in rows if r.get(status_key) in {"Win", "Loss"}]
    wins = [r[pl_key] for r in moved if r.get(status_key) == "Win"]
    losses = [r[pl_key] for r in moved if r.get(status_key) == "Loss"]
    n = len(moved)
    if n == 0:
        return {"n_moved": 0}
    win_rate = len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss
    pf = (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None
    tp1_touch = sum(1 for r in rows if r.get("tp1_hit"))
    stop_touch = sum(1 for r in rows if r.get("stopped"))
    # Net-of-cost expectancy (per-position EUR / alloc EUR). Computed only
    # when cost rows are populated.
    net_pl_eur = [r.get("strategy_pl_eur_real_net") for r in rows]
    net_pl_eur = [x for x in net_pl_eur if isinstance(x, (int, float))]
    cost_eur = [r.get("execution_cost_eur") for r in rows]
    cost_eur = [x for x in cost_eur if isinstance(x, (int, float))]
    return {
        "n_total": len(rows),
        "n_moved": n,
        "n_wins": len(wins),
        "n_losses": len(losses),
        "win_rate": round(win_rate, 4),
        "avg_win_pct_gross": round(avg_win, 6),
        "avg_loss_pct_gross": round(avg_loss, 6),
        "expectancy_per_trade_gross_pct": round(expectancy, 6),
        "expectancy_per_trade_net_eur": (
            round(sum(net_pl_eur) / len(net_pl_eur), 4) if net_pl_eur else None
        ),
        "avg_cost_per_trade_eur": (
            round(sum(cost_eur) / len(cost_eur), 4) if cost_eur else None
        ),
        "profit_factor_gross": round(pf, 4) if pf is not None else None,
        "tp1_touch_count": tp1_touch,
        "tp1_touch_rate": round(tp1_touch / len(rows), 4) if rows else None,
        "stop_touch_count": stop_touch,
        "stop_touch_rate": round(stop_touch / len(rows), 4) if rows else None,
        "_caveat": "All in-sample. n is tiny, regime-bound; directional only.",
    }


def metrics_with_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """As-if metrics: exclude rows where entry_quality_pass is False."""
    kept = [r for r in rows if r.get("entry_quality_pass") is not False]
    return aggregate_metrics(kept, "strategy_pl_pct_real", "status_real")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def build_report(xlsx: Path, as_of: date) -> dict[str, Any]:
    assumptions, positions = parse_backtest_xlsx(xlsx)
    cfg = load_entry_quality_config()
    cost_cfg = load_cost_config()
    rows: list[dict[str, Any]] = []
    index_cache: dict[str, list[dict[str, Any]]] = {}
    universe_mom_20d_by_date: dict[str, list[float]] = {}
    # Tickers for which yfinance returned no candles. The operator should tag
    # the corresponding minimum_daily_universe.yaml row with
    # ``notes: needs_provider_mapping`` so the loader filters it out.
    no_data: list[dict[str, str]] = []
    no_data_index: list[dict[str, str]] = []

    # First pass: fetch all stock histories so we can compute universe mom_20d
    # per buy-date.
    stock_hist: dict[str, list[dict[str, Any]]] = {}
    for p in positions:
        yf_sym, country = to_yf_symbol(p["ticker"])
        if yf_sym in stock_hist:
            continue
        candles = fetch_history(yf_sym, as_of)
        stock_hist[yf_sym] = candles
        p["_yf_symbol"] = yf_sym
        p["_country"] = country
        if not candles:
            no_data.append({
                "ticker_xlsx": p["ticker"],
                "yf_symbol_tried": yf_sym,
                "country": country,
                "suggestion": "Add `notes: needs_provider_mapping` to the universe yaml row, or correct the yfinance symbol mapping in scripts/backtest_entry_quality.py:_EXCHANGE_TO_YF_SUFFIX.",
            })

    # Index histories per country needed.
    countries = {p.get("_country") or to_yf_symbol(p["ticker"])[1] for p in positions}
    for c in countries:
        idx_sym = _INDEX_FOR_COUNTRY.get(c)
        if idx_sym and idx_sym not in index_cache:
            idx_candles = fetch_history(idx_sym, as_of)
            index_cache[idx_sym] = idx_candles
            if not idx_candles:
                no_data_index.append({"country": c, "index_symbol_tried": idx_sym})

    # Build the universe of 20d returns observed in our sample, keyed by date,
    # for percentile calc. We use the position's own 20d return as one sample;
    # all positions' 20d returns at their buy date make the comparison set.
    for p in positions:
        candles = stock_hist.get(p.get("_yf_symbol") or "")
        if not candles:
            continue
        buy_date = date.fromisoformat(p["buy_date"])
        before = [c for c in candles if date.fromisoformat(c["date"]) <= buy_date]
        if len(before) > 20:
            mom = (before[-1]["close"] - before[-21]["close"]) / before[-21]["close"]
            universe_mom_20d_by_date.setdefault(p["buy_date"], []).append(mom)

    # Second pass: compute entry-quality + walk forward.
    for p in positions:
        yf_sym = p.get("_yf_symbol") or to_yf_symbol(p["ticker"])[0]
        country = p.get("_country") or to_yf_symbol(p["ticker"])[1]
        candles = stock_hist.get(yf_sym) or []
        buy_date = date.fromisoformat(p["buy_date"])

        before = [c for c in candles if date.fromisoformat(c["date"]) <= buy_date]
        after = [c for c in candles if date.fromisoformat(c["date"]) > buy_date]

        idx_sym = _INDEX_FOR_COUNTRY.get(country)
        idx_full = index_cache.get(idx_sym) if idx_sym else None
        idx_before = (
            [c for c in idx_full if date.fromisoformat(c["date"]) <= buy_date]
            if idx_full else None
        )

        eq = compute_entry_quality(
            candles=before,
            index_candles=idx_before,
            universe_mom_20d=universe_mom_20d_by_date.get(p["buy_date"]),
            risk_band="core",
            config=cfg,
        )

        walk = walk_position(
            after, p["buy_price"], assumptions,
            market=country, cost_config=cost_cfg,
        )

        rows.append({
            "ticker": p["ticker"],
            "yf_symbol": yf_sym,
            "country": country,
            "buy_date": p["buy_date"],
            "buy_price": p["buy_price"],
            "currency": p["currency"],
            "entry_quality_pass": eq["entry_quality_pass"],
            "entry_quality_score": eq["entry_quality_score"],
            "entry_quality_reasons": eq["reasons"],
            "entry_quality_components": _summarize_components(eq["components"]),
            # xlsx (estimated) reference values
            "result_xlsx_estimated": p["result_xlsx"],
            "status_xlsx_estimated": p["status_xlsx"],
            "max_gain_xlsx_estimated": p["max_gain_est_xlsx"],
            "max_draw_xlsx_estimated": p["max_draw_est_xlsx"],
            "pl_pct_xlsx_estimated": p["pl_pct_xlsx"],
            # real-OHLCV recomputed values
            **walk,
        })

    overall = aggregate_metrics(rows, "strategy_pl_pct_real", "status_real")
    after_gate = metrics_with_gate(rows)
    # Per-market net expectancy: shows where round-trip cost exceeds the
    # gross per-trade edge (the C3 finding's per-market test).
    by_market: dict[str, dict[str, Any]] = {}
    for r in rows:
        m = r.get("country") or "?"
        by_market.setdefault(m, {"n": 0, "gross_eur": 0.0, "net_eur": 0.0, "cost_eur": 0.0})
        by_market[m]["n"] += 1
        by_market[m]["gross_eur"] += float(r.get("strategy_pl_eur_real_gross") or 0.0)
        by_market[m]["net_eur"] += float(r.get("strategy_pl_eur_real_net") or 0.0)
        by_market[m]["cost_eur"] += float(r.get("execution_cost_eur") or 0.0)
    for m, agg in by_market.items():
        n = agg["n"] or 1
        agg["avg_gross_eur"] = round(agg["gross_eur"] / n, 4)
        agg["avg_net_eur"] = round(agg["net_eur"] / n, 4)
        agg["avg_cost_eur"] = round(agg["cost_eur"] / n, 4)
        agg["cost_exceeds_gross"] = agg["avg_cost_eur"] > max(agg["avg_gross_eur"], 0.0)
    return {
        "as_of": as_of.isoformat(),
        "xlsx_source": str(xlsx),
        "assumptions": assumptions,
        "entry_quality_config_used": cfg,
        "caveats": [
            "n is small (≈29 moved positions) over a single short window; all in-sample "
            "metrics are directional only.",
            "as-if-gate metrics simply drop rows the gate would have blocked — they do NOT "
            "model the next-best name that would have been bought in their place.",
            "Outcomes use TRUE daily highs/lows (yfinance). The xlsx Hi/Lo columns were "
            "operator estimates and are shown for cross-check only.",
            "No threshold tuning has been performed against this report.",
        ],
        "metrics_real_all_positions": overall,
        "metrics_real_after_gate":   after_gate,
        "metrics_by_market":          by_market,
        "no_data_symbols": no_data,
        "no_data_indexes": no_data_index,
        "rows": rows,
    }


def _summarize_components(components: dict[str, Any]) -> dict[str, Any]:
    """Shrink the per-component dict to {name: {pass, raw}} for the report."""
    out: dict[str, Any] = {}
    for k, v in components.items():
        raw = v.get("raw") if isinstance(v, dict) else None
        out[k] = {"pass": v.get("pass") if isinstance(v, dict) else None, "raw": raw}
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_text_summary(report: dict[str, Any]) -> None:
    rows = report["rows"]
    print()
    print(f"Backtest entry-quality validation — as of {report['as_of']}")
    print(f"  positions: {len(rows)}  source: {report['xlsx_source']}")
    print()
    print("=== Metrics (TRUE daily OHLCV) — directional only, n is small ===")
    print(json.dumps(report["metrics_real_all_positions"], indent=2))
    print()
    print("=== Metrics if entry-quality gate had blocked failing names ===")
    print(json.dumps(report["metrics_real_after_gate"], indent=2))
    print()
    print(
        "  Caveat: 'after-gate' just drops rows; it does NOT model replacement "
        "picks. Use as directional, not predictive."
    )
    no_data = report.get("no_data_symbols") or []
    if no_data:
        print()
        print(f"=== yfinance returned NO data for {len(no_data)} symbol(s) ===")
        for nd in no_data:
            print(f"  ✗ {nd['ticker_xlsx']:<22} tried `{nd['yf_symbol_tried']}`  (country={nd['country']})")
        print(
            "  Action: add `notes: needs_provider_mapping` to the corresponding row in\n"
            "  config/minimum_daily_universe.yaml, or fix the suffix in\n"
            "  scripts/backtest_entry_quality.py:_EXCHANGE_TO_YF_SUFFIX. The universe\n"
            "  loader filters out rows carrying that tag, so they won't enter discovery."
        )
    no_data_idx = report.get("no_data_indexes") or []
    if no_data_idx:
        print()
        print(f"=== yfinance returned NO data for {len(no_data_idx)} index(es) ===")
        for nd in no_data_idx:
            print(f"  ✗ {nd['country']:<4}  tried `{nd['index_symbol_tried']}`")
        print("  Action: update scripts/backtest_entry_quality.py:_INDEX_FOR_COUNTRY.")

    print()
    print("=== Per-position entry-quality score (sample, 20 rows) ===")
    fmt = "  {pass_s:1}  {tkr:<18} buy={buy_d}  eq_score={s:>5}  real={real:<10}  xlsx={xls:<10}  pl_real={pl:>+7}"
    for r in rows[:20]:
        print(fmt.format(
            pass_s="✓" if r["entry_quality_pass"] else "✗",
            tkr=r["ticker"], buy_d=r["buy_date"],
            s=f"{r['entry_quality_score']:.2f}" if r["entry_quality_score"] is not None else "n/a",
            real=r["status_real"], xls=r["status_xlsx_estimated"],
            pl=f"{(r['strategy_pl_pct_real'] or 0)*100:.2f}%",
        ))
    if len(rows) > 20:
        print(f"  ... ({len(rows) - 20} more rows in JSON output)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--xlsx", type=Path, required=True,
                   help="Path to the portfolio_path_backtest.xlsx file")
    p.add_argument("--as-of", type=str, default=date.today().isoformat(),
                   help="ISO date to walk positions through (default: today)")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                   help=f"Output JSON path (default: {DEFAULT_OUT})")
    args = p.parse_args(argv)

    as_of = date.fromisoformat(args.as_of)
    report = build_report(args.xlsx, as_of)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    _print_text_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
