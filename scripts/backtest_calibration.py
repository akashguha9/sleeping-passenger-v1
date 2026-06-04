"""Walk-forward backtest -> IMPORTED_BACKTEST outcome evidence.

Turns historical OHLCV bars + a scoring function into resolved outcomes so the
scores can be calibrated against *real forward returns* — the only honest path
to non-synthetic calibration evidence when no real-money trades exist yet.

Honesty guarantees
------------------
* No lookahead: the score at bar t uses only bars[:t+1]; the forward return
  uses bars[t+horizon]. Enforced by construction and tested.
* No invented prices: outcomes come only from bars you supply.
* Provenance is explicit and REQUIRED. ``price_provenance="IMPORTED"`` (real
  historical data) -> source_type IMPORTED_BACKTEST. Anything else ->
  SYNTHETIC_FIXTURE, which is never calibration-eligible. There is no default,
  so synthetic data can never be silently promoted to backtest evidence.
* Backtest evidence calibrates the *scores*; it is NOT real-money proof. The
  real-money readiness gate keys on real_n, never backtest_n.

Pure compute. No broker calls, no execution. Advisory invariants preserved on
every outcome record.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts import outcome_evidence as oe
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import outcome_evidence as oe  # type: ignore[no-redef]

PROV_IMPORTED = "IMPORTED"
PROV_SYNTHETIC = "SYNTHETIC"


def _source_type_for(provenance: str) -> str:
    return oe.IMPORTED_BACKTEST if str(provenance).upper() == PROV_IMPORTED else oe.SYNTHETIC_FIXTURE


def momentum_score(closes: Sequence[float], *, lookback: int = 20) -> float:
    """Default scoring fn: recent return squashed to [0,1].

    Not the point of the harness — it calibrates whatever score it is given.
    Uses only the closes passed (history up to the entry bar).
    """
    if len(closes) < 2:
        return 0.5
    window = closes[-(lookback + 1):]
    base = window[0]
    if base == 0:
        return 0.5
    ret = (window[-1] - base) / base
    # logistic squash centred at 0 with gentle slope.
    import math
    return 1.0 / (1.0 + math.exp(-8.0 * ret))


def backtest_symbol(
    ticker: str,
    bars: Sequence[dict[str, Any]],
    *,
    price_provenance: str,
    horizon: int = 5,
    score_fn: Callable[[Sequence[float]], float] = momentum_score,
    min_history: int = 20,
    jurisdiction_group: str = oe.UNKNOWN,
    epsilon: float = oe.DEFAULT_EPSILON,
) -> list[oe.OutcomeEvidence]:
    """Walk forward over ``bars`` (each {date, close}) producing outcomes.

    ``price_provenance`` is REQUIRED: pass "IMPORTED" only for genuine
    historical prices. Synthetic/test prices must use "SYNTHETIC" and will be
    ineligible for calibration.
    """
    source_type = _source_type_for(price_provenance)
    closes = [float(b["close"]) for b in bars]
    dates = [b.get("date") for b in bars]
    n = len(closes)
    outcomes: list[oe.OutcomeEvidence] = []
    # entry at index i needs >= min_history bars of history and a bar at i+horizon.
    for i in range(min_history - 1, n - horizon):
        history = closes[: i + 1]               # only past+present (no lookahead)
        score = float(score_fn(history))
        entry = closes[i]
        exit_ = closes[i + horizon]             # strictly future bar
        outcomes.append(
            oe.build_outcome(
                outcome_id=f"BT_{ticker}_{i}",
                source_type=source_type,
                ticker=ticker,
                direction="LONG",
                signal_id=f"{ticker}@{dates[i]}",
                opened_at=dates[i],
                closed_at=dates[i + horizon],
                horizon_days=float(horizon),
                entry_price=entry,
                exit_price=exit_,
                score_at_entry=score,
                jurisdiction_group=jurisdiction_group,
                epsilon=epsilon,
            )
        )
    return outcomes


def run_backtest(
    series_by_ticker: dict[str, Sequence[dict[str, Any]]],
    *,
    price_provenance: str,
    horizon: int = 5,
    score_fn: Callable[[Sequence[float]], float] = momentum_score,
) -> dict[str, Any]:
    """Backtest a basket of symbols and summarise the resulting evidence."""
    all_outcomes: list[oe.OutcomeEvidence] = []
    for ticker, bars in series_by_ticker.items():
        all_outcomes.extend(
            backtest_symbol(ticker, bars, price_provenance=price_provenance,
                            horizon=horizon, score_fn=score_fn)
        )
    prov = oe.provenance_counts(all_outcomes)
    return {
        "report": "backtest_calibration",
        "price_provenance": str(price_provenance).upper(),
        "horizon_days": horizon,
        "outcomes": all_outcomes,
        **prov,
        "advisory_status": "ADVISORY_ONLY",
        "human_execution_required": True,
        "broker_api_called": False,
        "note": (
            "Backtest evidence calibrates the SCORES, not real-money readiness. "
            "Real-money readiness keys on real_n, never backtest_n."
        ),
    }


def load_ohlcv_from_db(
    ticker: str, db_path: Path | None = None, *, limit: int = 2000
) -> list[dict[str, Any]]:
    """Read real historical closes for a symbol from the OHLCV store, if present.

    Read-only and defensive. Returns [] when no data — never fabricates bars.
    """
    try:
        try:
            from scripts import persistence
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            import persistence  # type: ignore[no-redef]
        path = db_path if db_path is not None else persistence.DB_PATH
        for fn_name in ("get_ohlcv_history", "get_global_ohlcv", "get_ohlcv"):
            fn = getattr(persistence, fn_name, None)
            if fn is None:
                continue
            try:
                rows = fn(ticker, db_path=path)
            except TypeError:
                rows = fn(ticker)
            bars = []
            for r in rows or []:
                close = r.get("close") or r.get("adj_close") or r.get("close_price")
                date = r.get("date") or r.get("ts") or r.get("bar_date")
                if close is not None:
                    bars.append({"date": date, "close": float(close)})
            if bars:
                return bars[-limit:]
        return []
    except Exception:  # pragma: no cover - defensive
        return []


__all__ = [
    "PROV_IMPORTED", "PROV_SYNTHETIC",
    "momentum_score", "backtest_symbol", "run_backtest", "load_ohlcv_from_db",
]
