"""Imported backtest runner — signal records + local OHLCV -> evidence.

Runs a no-network, no-lookahead backtest of scored signals against imported
historical OHLCV (the ohlcv_bars store). Produces IMPORTED_BACKTEST outcome
evidence with REAL forward returns.

Conventions (documented):
  * Entry date = first trading bar with date >= the signal timestamp.
  * Exit date  = first trading bar with date >= entry_date + horizon_days
    (calendar days). If none exists, the outcome is OPEN and ineligible.
  * Entry price = close(entry bar); Exit price = close(exit bar).
  * No lookahead: the signal timestamp and score must be <= entry date; price
    data after entry is used ONLY for the exit return; no future bar can
    influence whether a signal is included.

Provenance: outcomes are IMPORTED_BACKTEST only when the bars are non-synthetic.
If any bar source is SYNTHETIC_FIXTURE and runtime_mode is on, those bars are
refused. Backtest evidence calibrates the SCORES; it never lifts real-money
readiness (which keys on real_n).

Pure/IO-light: reads OHLCV via persistence; no broker, no execution.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts import outcome_evidence as oe
    from scripts import ohlcv_import_contract as contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import outcome_evidence as oe  # type: ignore[no-redef]
    import ohlcv_import_contract as contract  # type: ignore[no-redef]

DEFAULT_HORIZON = 20


def _parse(d: Any) -> datetime | None:
    s = contract.parse_date(d)
    if s is None:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


def _bars_are_synthetic(bars: Sequence[dict[str, Any]]) -> bool:
    return any(str(b.get("source", "")).upper() == contract.SYNTHETIC_FIXTURE for b in bars)


def backtest_signals(
    signals: Sequence[dict[str, Any]],
    bars_by_ticker: dict[str, Sequence[dict[str, Any]]],
    *,
    horizon_days: int = DEFAULT_HORIZON,
    default_direction: str = "LONG",
    epsilon: float = oe.DEFAULT_EPSILON,
    runtime_mode: bool = True,
) -> list[oe.OutcomeEvidence]:
    """Backtest scored signals against per-ticker OHLCV bars (sorted ascending)."""
    outcomes: list[oe.OutcomeEvidence] = []
    # Pre-sort + parse bars per ticker.
    parsed: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for tkr, bars in bars_by_ticker.items():
        if runtime_mode and _bars_are_synthetic(bars):
            continue  # refuse synthetic bars in runtime
        rows = []
        for b in bars:
            dt = _parse(b.get("date"))
            if dt is not None:
                rows.append((dt, b))
        rows.sort(key=lambda x: x[0])
        parsed[str(tkr).upper()] = rows

    for idx, sig in enumerate(signals):
        tkr = str(sig.get("ticker", "")).upper()
        sig_dt = _parse(sig.get("timestamp") or sig.get("date") or sig.get("observed_at"))
        score = sig.get("score") if sig.get("score") is not None else sig.get("score_at_entry")
        rows = parsed.get(tkr)
        if not rows or sig_dt is None:
            continue
        # Entry: first bar with date >= signal date (no lookahead).
        entry = next(((dt, b) for dt, b in rows if dt >= sig_dt), None)
        if entry is None:
            continue
        entry_dt, entry_bar = entry
        target = entry_dt + timedelta(days=horizon_days)
        exit_ = next(((dt, b) for dt, b in rows if dt >= target), None)
        direction = str(sig.get("direction", default_direction)).upper()
        provenance_source = str(entry_bar.get("source", ""))
        is_synth = provenance_source.upper() == contract.SYNTHETIC_FIXTURE
        source_type = oe.SYNTHETIC_FIXTURE if is_synth else oe.IMPORTED_BACKTEST

        exit_price = exit_[1].get("close") if exit_ is not None else None
        closed_at = exit_[0].strftime("%Y-%m-%d") if exit_ is not None else None

        outcomes.append(
            oe.build_outcome(
                outcome_id=f"IBT_{tkr}_{idx}",
                source_type=source_type,
                ticker=tkr,
                direction=direction,
                signal_id=str(sig.get("signal_id") or sig.get("event_id") or f"{tkr}@{entry_dt:%Y-%m-%d}"),
                opened_at=entry_dt.strftime("%Y-%m-%d"),
                closed_at=closed_at,
                horizon_days=float(horizon_days),
                entry_price=entry_bar.get("close"),
                exit_price=exit_price,
                leverage=sig.get("leverage", 1.0),
                jurisdiction_group=sig.get("jurisdiction_group", oe.UNKNOWN),
                score_at_entry=score,
                archetype=sig.get("archetype") or sig.get("signal_state"),
                epsilon=epsilon,
            )
        )
    return outcomes


def run_imported_backtest_from_db(
    signals: Sequence[dict[str, Any]],
    *,
    db_path: Path | None = None,
    horizon_days: int = DEFAULT_HORIZON,
    write_evidence: bool = False,
) -> dict[str, Any]:
    """Read OHLCV from the store for the signals' tickers and backtest them."""
    try:
        from scripts import persistence
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        import persistence  # type: ignore[no-redef]
    path = db_path if db_path is not None else persistence.DB_PATH
    tickers = {str(s.get("ticker", "")).upper() for s in signals if s.get("ticker")}
    bars_by_ticker = {t: persistence.get_ohlcv_bars(t, db_path=path) for t in tickers}
    outcomes = backtest_signals(signals, bars_by_ticker, horizon_days=horizon_days)
    prov = oe.provenance_counts(outcomes)
    return {
        "report": "imported_backtest",
        "horizon_days": horizon_days,
        "outcomes": outcomes,
        "outcome_dicts": [o.to_dict() for o in outcomes],
        **prov,
        "advisory_status": "ADVISORY_ONLY",
        "human_execution_required": True,
        "broker_api_called": False,
        "note": "Backtest evidence calibrates scores; real-money readiness keys on real_n.",
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Imported backtest over local OHLCV.")
    p.add_argument("--signals", type=Path, required=True, help="JSON list of signals.")
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--horizon-days", type=int, default=DEFAULT_HORIZON)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    signals = json.loads(Path(args.signals).read_text(encoding="utf-8"))
    rep = run_imported_backtest_from_db(signals, db_path=args.db_path,
                                        horizon_days=args.horizon_days)
    rep.pop("outcomes", None)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(f"backtest_n={rep['backtest_n']} eligible_n={rep['eligible_n']} "
              f"real_n={rep['real_n']} synthetic_n={rep['synthetic_n']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["backtest_signals", "run_imported_backtest_from_db", "DEFAULT_HORIZON"]
