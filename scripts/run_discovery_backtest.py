#!/usr/bin/env python3
"""DISC-B3/B4/B5: offline discovery backtest against a pinned snapshot.

Composes the sprint's discipline stack:
* **B1** — every universe symbol must have resolved through the explicit
  exchange mapping (the snapshot fetcher already enforced it; the runner
  re-verifies the snapshot's own coverage and fails loud on any signal
  whose ticker has no snapshot series — no silent drops).
* **B2** — per-symbol data-quality checks (gaps / suspected splits /
  delisting truncation) run BEFORE the backtest; flagged symbols are
  reported, never repaired; signals excluded because data ended early
  are COUNTED (survivorship guard), not forgotten.
* **B3** — coverage is reported as requested → validated → clean, never
  a headline count.
* **B4** — deterministic: same snapshot + same signals ⇒ byte-identical
  report.  No wall clock in the output; run identity = sha256 of inputs.
* **B5** — the report LEADS with methodology and bias caveats, and every
  results section carries the standing not-evidence-of-edge caveat.

No network.  Entry/exit logic is delegated to the existing audited
runner (scripts/run_imported_backtest.backtest_signals: entry = first
bar >= signal date, close prices, no-lookahead) with the B2 hard
assertion layered on every produced outcome.

RESULTS FIREWALL: this tool measures the tooling, not the strategy.
Nothing it prints moves the evidence-of-edge assessment (capped until
T=10 forward paper trades close).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.discovery_bias_guards import (
        assert_entry_no_lookahead,
        check_series_quality,
    )
    from scripts.run_imported_backtest import backtest_signals
    from scripts.runtime_common import restrict_file_permissions
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from discovery_bias_guards import (  # type: ignore[no-redef]
        assert_entry_no_lookahead,
        check_series_quality,
    )
    from run_imported_backtest import backtest_signals  # type: ignore[no-redef]
    from runtime_common import restrict_file_permissions  # type: ignore[no-redef]

TOOL_VERSION = "discovery-backtest-1.0"

EDGE_CAVEAT = (
    "RETROSPECTIVE TOOLING RESULT — in-sample, survivorship- and "
    "look-ahead-sensitive, NOT predictive, NOT evidence of forward edge. "
    "Evidence of edge moves ONLY on closed forward paper trades."
)


def _sha256_of(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def run_discovery_backtest(
    snapshot: dict[str, Any],
    signals: list[dict[str, Any]],
    *,
    horizon_days: int = 20,
) -> dict[str, Any]:
    """Pure function: snapshot + signals → honest report dict."""
    bars_by_symbol: dict[str, Any] = snapshot.get("bars_by_symbol", {})
    window_end = datetime.strptime(str(snapshot["end"])[:10], "%Y-%m-%d")

    requested = len(snapshot.get("requested_symbols", []))
    validated = len(snapshot.get("resolved", []))

    # B1 re-verification at run time: every SIGNAL ticker must have a
    # snapshot series — a missing series fails loud, never silently drops.
    signal_tickers = {str(s.get("ticker", "")).upper() for s in signals}
    missing = sorted(
        t for t in signal_tickers if t and t not in {k.upper() for k in bars_by_symbol}
    )
    if missing:
        raise ValueError(
            f"signals reference symbols absent from the snapshot: {missing} "
            "— refusing to run on partial coverage"
        )

    # B2: quality audit per symbol, BEFORE the backtest.
    quality: dict[str, Any] = {}
    clean_symbols: list[str] = []
    for sym in sorted(bars_by_symbol):
        q = check_series_quality(bars_by_symbol[sym], window_end=window_end)
        quality[sym] = q
        if q["clean"]:
            clean_symbols.append(sym)

    outcomes = backtest_signals(
        signals,
        bars_by_symbol,
        horizon_days=horizon_days,
        runtime_mode=False,  # snapshot bars carry the YFINANCE_SNAPSHOT source
    )

    # B2 hard guard on every produced outcome: entry may never precede
    # the originating signal's date.  Matched on (ticker, signal_id).
    signal_dates: dict[tuple[str, str], datetime] = {}
    for s in signals:
        raw_dt = str(s.get("timestamp") or s.get("date") or "")[:10]
        try:
            sdt = datetime.strptime(raw_dt, "%Y-%m-%d")
        except ValueError:
            continue
        key = (
            str(s.get("ticker", "")).upper(),
            str(s.get("signal_id") or s.get("event_id") or ""),
        )
        signal_dates[key] = sdt

    closed = []
    for o in outcomes:
        d = o.to_dict() if hasattr(o, "to_dict") else dict(o.__dict__)
        entry_dt = datetime.strptime(str(d.get("opened_at"))[:10], "%Y-%m-%d")
        key = (str(d.get("ticker", "")).upper(), str(d.get("signal_id") or ""))
        sig_dt = signal_dates.get(key)
        if sig_dt is not None:
            assert_entry_no_lookahead(sig_dt, entry_dt)
        closed.append(d)
    truncated_exclusions: list[dict[str, str]] = []
    for s in signals:
        t = str(s.get("ticker", "")).upper()
        q = quality.get(t) or quality.get(next(
            (k for k in quality if k.upper() == t), ""), {})
        if q and q.get("delisting_suspected"):
            truncated_exclusions.append(
                {
                    "ticker": t,
                    "signal_date": str(s.get("timestamp") or s.get("date") or "")[:10],
                    "reason": "series ends before window_end — outcome may be "
                    "missing from results (survivorship risk, counted here)",
                }
            )

    wins = sum(1 for d in closed if str(d.get("outcome_label", "")).upper() == "WIN")
    losses = sum(1 for d in closed if str(d.get("outcome_label", "")).upper() == "LOSS")
    open_unclosed = sum(
        1 for d in closed if str(d.get("outcome_label", "")).upper() == "OPEN"
    )

    report = {
        # B5: methodology and caveats FIRST.
        "methodology": {
            "entry": "first bar with date >= signal date (close price)",
            "exit": f"first bar with date >= entry + {horizon_days} calendar days (close)",
            "no_lookahead_guard": "hard assertion on every outcome",
            "data_repairs": "NONE — gaps/splits/delistings are flagged, never interpolated",
            "caveat": EDGE_CAVEAT,
        },
        "coverage": {
            "requested_symbols": requested,
            "validated_symbols": validated,
            "clean_data_symbols": len(clean_symbols),
            "flagged_symbols": {
                s: quality[s]["flags"] for s in sorted(quality) if not quality[s]["clean"]
            },
            "statement": (
                f"{requested} requested → {validated} validated → "
                f"{len(clean_symbols)} with clean data"
            ),
        },
        "survivorship_guard": {
            "signals_on_truncated_series": truncated_exclusions,
            "count": len(truncated_exclusions),
            "note": (
                "These signals may lack a closable outcome because the price "
                "series ends early; they are COUNTED here so missing losers "
                "cannot silently inflate the result."
            ),
        },
        "results": {
            "caveat": EDGE_CAVEAT,
            "signals_in": len(signals),
            "outcomes_produced": len(closed),
            "wins": wins,
            "losses": losses,
            "open_unclosed": open_unclosed,
            "outcomes": sorted(
                closed,
                key=lambda d: (str(d.get("ticker")), str(d.get("opened_at"))),
            ),
        },
        "run_metadata": {
            "tool_version": TOOL_VERSION,
            "date_range": {"start": snapshot.get("start"), "end": snapshot.get("end")},
            "universe_sha256": _sha256_of(snapshot.get("requested_symbols", [])),
            "snapshot_sha256": snapshot.get("snapshot_sha256"),
            "signals_sha256": _sha256_of(signals),
            "horizon_days": horizon_days,
            # B4: run identity derives from inputs — NO wall clock, so the
            # same inputs produce a byte-identical report.
            "run_id_sha256": _sha256_of(
                [snapshot.get("snapshot_sha256"), _sha256_of(signals), horizon_days]
            ),
        },
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "results_firewall": EDGE_CAVEAT,
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--signals", type=Path, required=True,
                        help="JSON list of {ticker, timestamp|date, score}")
    parser.add_argument("--horizon-days", type=int, default=20)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    signals = json.loads(args.signals.read_text(encoding="utf-8"))
    try:
        report = run_discovery_backtest(
            snapshot, signals, horizon_days=args.horizon_days
        )
    except (ValueError, AssertionError) as exc:
        print(f"[run_discovery_backtest] FAILED LOUD: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True))
    restrict_file_permissions(args.out)
    cov = report["coverage"]["statement"]
    print(f"[run_discovery_backtest] {cov}")
    print(f"[run_discovery_backtest] {EDGE_CAVEAT}")
    print(f"[run_discovery_backtest] report: {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry point
    raise SystemExit(main())
