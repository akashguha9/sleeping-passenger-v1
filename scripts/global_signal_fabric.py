"""
Global Signal Fabric (Phase 1) — read-only, advisory-only cross-pipeline
observability layer.

Design contract:
- ALL outputs carry advisory_status="ADVISORY_ONLY" and human_review_required=True.
- This module NEVER emits buy/sell signals, modifies execution policy, or touches
  any SCM/position/paper-execution paths.
- No network calls on import.  Missing files return empty collections, not errors.
- API keys are never required; their absence silently degrades to seeded data.
- The only write this module performs is write_json_atomic() on its own output
  path (runtime/global_signal_fabric_report.json), using the same coherence
  stamping as every other runtime artifact.

Integration points (read-only):
  logs/system_snapshots.jsonl           — pipeline run history
  runtime/per_signal_attribution.json   — current per-signal state
  logs/signal_kill_log.jsonl            — rejection history

Output (advisory, stamped):
  runtime/global_signal_fabric_report.json
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        PER_SIGNAL_ATTRIBUTION_PATH,
        RUNTIME_DIR,
        SIGNAL_KILL_LOG_PATH,
        SNAPSHOT_LOG_PATH,
        get_run_id,
        load_json_file,
        utc_timestamp,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (  # type: ignore[no-redef]
        PER_SIGNAL_ATTRIBUTION_PATH,
        RUNTIME_DIR,
        SIGNAL_KILL_LOG_PATH,
        SNAPSHOT_LOG_PATH,
        get_run_id,
        load_json_file,
        utc_timestamp,
        write_json_atomic,
    )

GLOBAL_SIGNAL_FABRIC_REPORT_PATH = RUNTIME_DIR / "global_signal_fabric_report.json"

_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_GATE = "LOCKED"
_SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Canonical dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SignalEvent:
    """Read-only canonical cross-pipeline signal observation.

    No execution fields, no order-placement fields, and no fields that can
    gate or modify execution policy.
    """

    signal_id: str
    ticker: str
    signal_state: str            # WATCHLIST / ACTIVE / REJECTED / UNKNOWN
    entry_type: str              # CLEAN / CHAOS / UNKNOWN
    source_run_id: str           # pipeline run_id this event came from
    observed_at: str             # ISO timestamp
    priority_score: float        # raw ce_score / priority_score from source
    blocker_attribution: str     # GSCE_PHASE_LOCK / REALM_BIS / NONE / UNKNOWN
    source_file: str             # "snapshots" / "attribution" / "kill_log"
    rejection_dimensions: list[str] = field(default_factory=list)
    rejection_reason: str = ""
    # Scoring outputs — populated by score_* / attach_scores, never by loaders
    persistence_score: float = 0.0
    blocker_pressure_score: float = 0.0
    kill_rate_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SnapshotRow:
    """Single pipeline-run snapshot from system_snapshots.jsonl."""

    run_id: str
    timestamp: str
    scm_rate: float
    scm_state: str
    policy_state: str
    allow_new_risk: bool
    blockers_active: list[str]
    clean_entries: int
    chaos_entries: int
    signals_above_threshold: int
    watchlist_count: int
    promotable_watchlist_count: int
    transition_state_rows: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Private coercion helpers
# ---------------------------------------------------------------------------


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _load_jsonl_safe(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file line by line; missing or malformed lines are skipped."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    rows.append(parsed)
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return rows


# ---------------------------------------------------------------------------
# Read-only source loaders — never write, never raise on missing file
# ---------------------------------------------------------------------------


def load_snapshot_rows(path: Path | None = None) -> list[SnapshotRow]:
    """Load pipeline-run snapshots from system_snapshots.jsonl (read-only)."""
    target = path or SNAPSHOT_LOG_PATH
    result: list[SnapshotRow] = []
    for row in _load_jsonl_safe(target):
        result.append(
            SnapshotRow(
                run_id=_text(row.get("run_id")),
                timestamp=_text(
                    row.get("timestamp") or row.get("artifact_written_at")
                ),
                scm_rate=_coerce_float(row.get("scm_rate")),
                scm_state=_text(row.get("scm_state"), "UNKNOWN"),
                policy_state=_text(row.get("policy_state"), "UNKNOWN"),
                allow_new_risk=bool(row.get("allow_new_risk", False)),
                blockers_active=[
                    _text(b)
                    for b in (row.get("blockers_active") or [])
                    if _text(b)
                ],
                clean_entries=_coerce_int(row.get("clean_entries")),
                chaos_entries=_coerce_int(row.get("chaos_entries")),
                signals_above_threshold=_coerce_int(
                    row.get("signals_above_threshold")
                ),
                watchlist_count=_coerce_int(row.get("watchlist_count")),
                promotable_watchlist_count=_coerce_int(
                    row.get("promotable_watchlist_count")
                ),
                transition_state_rows=[
                    t
                    for t in (row.get("transition_state_rows") or [])
                    if isinstance(t, dict)
                ],
            )
        )
    return result


def load_signal_events_from_attribution(
    path: Path | None = None,
) -> list[SignalEvent]:
    """Extract SignalEvents from per_signal_attribution.json (read-only)."""
    target = path or PER_SIGNAL_ATTRIBUTION_PATH
    payload = load_json_file(target, default={}) or {}
    if isinstance(payload, dict):
        rows = payload.get("per_signal_attribution", [])
    else:
        rows = payload if isinstance(payload, list) else []

    observed_at = utc_timestamp()
    run_id = get_run_id()
    events: list[SignalEvent] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = _text(row.get("ticker") or row.get("symbol")).upper()
        if not ticker:
            continue
        events.append(
            SignalEvent(
                signal_id=_text(row.get("signal_id"), f"ATTR_{ticker}"),
                ticker=ticker,
                signal_state=_text(
                    row.get("signal_state") or row.get("status"), "UNKNOWN"
                ).upper(),
                entry_type=_text(row.get("entry_type"), "UNKNOWN").upper(),
                source_run_id=run_id,
                observed_at=observed_at,
                priority_score=_coerce_float(
                    row.get("priority_score") or row.get("ce_score")
                ),
                blocker_attribution=_text(
                    row.get("blocker_attribution"), "NONE"
                ).upper(),
                source_file="attribution",
            )
        )
    return events


def load_signal_events_from_kill_log(
    path: Path | None = None,
) -> list[SignalEvent]:
    """Extract SignalEvents from signal_kill_log.jsonl (read-only)."""
    target = path or SIGNAL_KILL_LOG_PATH
    events: list[SignalEvent] = []
    for row in _load_jsonl_safe(target):
        ticker = _text(row.get("ticker")).upper()
        if not ticker:
            continue
        events.append(
            SignalEvent(
                signal_id=_text(row.get("signal_id"), f"KILL_{ticker}"),
                ticker=ticker,
                signal_state="REJECTED",
                entry_type="UNKNOWN",
                source_run_id=_text(row.get("run_id")),
                observed_at=_text(
                    row.get("timestamp") or row.get("artifact_written_at")
                ),
                priority_score=0.0,
                blocker_attribution="NONE",
                source_file="kill_log",
                rejection_dimensions=[
                    _text(d)
                    for d in (row.get("rejection_dimensions") or [])
                    if _text(d)
                ],
                rejection_reason=_text(row.get("rejection_reason")),
            )
        )
    return events


def load_signal_events_from_snapshots(
    path: Path | None = None,
) -> list[SignalEvent]:
    """Extract per-ticker SignalEvents from transition_state_rows in snapshots."""
    events: list[SignalEvent] = []
    for snap in load_snapshot_rows(path):
        for tsr in snap.transition_state_rows:
            if not isinstance(tsr, dict):
                continue
            ticker = _text(tsr.get("ticker")).upper()
            if not ticker:
                continue
            events.append(
                SignalEvent(
                    signal_id=_text(
                        tsr.get("signal_id"),
                        f"SNAP_{ticker}_{snap.run_id}",
                    ),
                    ticker=ticker,
                    signal_state="WATCHLIST",
                    entry_type="CLEAN",
                    source_run_id=snap.run_id,
                    observed_at=snap.timestamp,
                    priority_score=0.0,
                    blocker_attribution=_text(
                        tsr.get("blocker_attribution"), "GSCE_PHASE_LOCK"
                    ).upper(),
                    source_file="snapshots",
                )
            )
    return events


# ---------------------------------------------------------------------------
# Scoring skeletons — pure functions, no side effects
# ---------------------------------------------------------------------------


def score_persistence(
    ticker: str,
    events: list[SignalEvent],
    *,
    total_run_count: int | None = None,
) -> float:
    """Fraction of observed runs in which this ticker appeared.

    1.0 = appeared in every run in the window.  0.0 = never appeared.
    This is a raw visibility metric, not a prediction.
    """
    ticker_upper = ticker.upper()
    ticker_events = [e for e in events if e.ticker == ticker_upper]
    if not ticker_events:
        return 0.0
    unique_runs_for_ticker = len(
        {e.source_run_id for e in ticker_events if e.source_run_id}
    )
    if total_run_count and total_run_count > 0:
        denominator = total_run_count
    else:
        all_unique_runs = len({e.source_run_id for e in events if e.source_run_id})
        denominator = max(all_unique_runs, unique_runs_for_ticker)
    return round(min(unique_runs_for_ticker / denominator, 1.0), 4)


def score_blocker_pressure(
    ticker: str,
    events: list[SignalEvent],
) -> float:
    """Fraction of this ticker's appearances that carried an active blocker.

    1.0 = every appearance was blocked.  0.0 = no blockers observed.
    """
    ticker_upper = ticker.upper()
    ticker_events = [e for e in events if e.ticker == ticker_upper]
    if not ticker_events:
        return 0.0
    blocked = sum(
        1
        for e in ticker_events
        if e.blocker_attribution not in {"NONE", "", "UNKNOWN"}
    )
    return round(blocked / len(ticker_events), 4)


def score_kill_rate(
    ticker: str,
    events: list[SignalEvent],
) -> float:
    """Fraction of this ticker's appearances that ended in rejection.

    1.0 = every appearance was killed.  0.0 = no rejections on record.
    """
    ticker_upper = ticker.upper()
    ticker_events = [e for e in events if e.ticker == ticker_upper]
    if not ticker_events:
        return 0.0
    killed = sum(1 for e in ticker_events if e.signal_state == "REJECTED")
    return round(killed / len(ticker_events), 4)


def attach_scores(
    events: list[SignalEvent],
    *,
    total_run_count: int | None = None,
) -> list[SignalEvent]:
    """Return a new list with persistence / blocker / kill scores attached.

    Pure: does not mutate the input list.
    """
    return [
        replace(
            e,
            persistence_score=score_persistence(
                e.ticker, events, total_run_count=total_run_count
            ),
            blocker_pressure_score=score_blocker_pressure(e.ticker, events),
            kill_rate_score=score_kill_rate(e.ticker, events),
        )
        for e in events
    ]


# ---------------------------------------------------------------------------
# Bull-state classifier (read-only over snapshot history)
# ---------------------------------------------------------------------------


def classify_fabric_bull_state(
    snapshots: list[SnapshotRow],
) -> dict[str, Any]:
    """Classify cross-pipeline bull state from snapshot history.

    States
    ------
    DORMANT      All signals blocked or absent; low scm_rate; no risk allowed.
    EMERGING     Blockers present but scm_rate improving or promotables growing.
    ACTIVE       Clean entries present; risk allowed in at least one recent run.
    OVEREXTENDED Chaos > clean; restricted policy despite activity (caution flag,
                 not a recommendation).
    UNKNOWN      Insufficient history (fewer than 2 snapshots).

    Returns an advisory dict.  Never returns an action recommendation.
    """
    if len(snapshots) < 2:
        return {
            "fabric_bull_state": "UNKNOWN",
            "rationale": "insufficient snapshot history (need >= 2 runs)",
            "window_run_count": len(snapshots),
            "advisory_note": (
                "Not enough history to classify cross-pipeline state. "
                "This is observational context only and does not affect "
                "execution policy."
            ),
        }

    recent = snapshots[-5:]
    avg_scm_rate = sum(s.scm_rate for s in recent) / len(recent)
    any_risk_allowed = any(s.allow_new_risk for s in recent)
    total_clean = sum(s.clean_entries for s in recent)
    total_chaos = sum(s.chaos_entries for s in recent)
    total_promotable = sum(s.promotable_watchlist_count for s in recent)
    all_blocked = all(len(s.blockers_active) > 0 for s in recent)
    scm_trend = recent[-1].scm_rate - recent[0].scm_rate if len(recent) >= 2 else 0.0

    if any_risk_allowed and total_clean > 0:
        state = "ACTIVE"
        rationale = (
            f"clean_entries={total_clean} in window, risk allowed in at least "
            f"one run, avg_scm_rate={avg_scm_rate:.3f}"
        )
    elif total_chaos > total_clean and total_chaos > 0 and not any_risk_allowed:
        state = "OVEREXTENDED"
        rationale = (
            f"chaos_entries({total_chaos}) > clean_entries({total_clean}), "
            f"policy restricted, avg_scm_rate={avg_scm_rate:.3f}"
        )
    elif scm_trend > 0 or total_promotable > 0:
        state = "EMERGING"
        rationale = (
            f"scm_rate_trend={scm_trend:+.3f}, "
            f"promotable_count={total_promotable}, "
            f"avg_scm_rate={avg_scm_rate:.3f}"
        )
    elif all_blocked and avg_scm_rate < 0.35:
        state = "DORMANT"
        rationale = (
            f"all runs blocked, avg_scm_rate={avg_scm_rate:.3f} < 0.35, "
            f"promotable_count={total_promotable}"
        )
    else:
        state = "DORMANT"
        rationale = (
            f"no clear emerging or active signal, avg_scm_rate={avg_scm_rate:.3f}"
        )

    return {
        "fabric_bull_state": state,
        "rationale": rationale,
        "window_run_count": len(recent),
        "avg_scm_rate": round(avg_scm_rate, 4),
        "scm_rate_trend": round(scm_trend, 4),
        "any_risk_allowed": any_risk_allowed,
        "total_clean_entries": total_clean,
        "total_chaos_entries": total_chaos,
        "total_promotable": total_promotable,
        "all_blocked": all_blocked,
        "advisory_note": (
            "Bull-state classification is observational context only. "
            "It does not enable capital deployment or modify execution policy."
        ),
    }


# ---------------------------------------------------------------------------
# Per-ticker fabric summary
# ---------------------------------------------------------------------------


def _build_ticker_summary(
    ticker: str,
    events: list[SignalEvent],
    total_run_count: int,
) -> dict[str, Any]:
    ticker_events = [e for e in events if e.ticker == ticker]
    if not ticker_events:
        return {}
    latest = max(ticker_events, key=lambda e: e.observed_at or "")
    return {
        "ticker": ticker,
        "event_count": len(ticker_events),
        "persistence_score": score_persistence(
            ticker, events, total_run_count=total_run_count
        ),
        "blocker_pressure_score": score_blocker_pressure(ticker, events),
        "kill_rate_score": score_kill_rate(ticker, events),
        "latest_signal_state": latest.signal_state,
        "latest_blocker": latest.blocker_attribution,
        "latest_observed_at": latest.observed_at,
        "source_files": sorted({e.source_file for e in ticker_events}),
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
    }


# ---------------------------------------------------------------------------
# Main report builder
# ---------------------------------------------------------------------------


def build_global_signal_fabric_report(
    *,
    snapshot_path: Path | None = None,
    attribution_path: Path | None = None,
    kill_log_path: Path | None = None,
    write_runtime: bool = True,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Build the advisory-only global signal fabric report.

    Reads three sources (all read-only, all fail-safe on missing files):
      - system_snapshots.jsonl
      - per_signal_attribution.json
      - signal_kill_log.jsonl

    Returns a stamped advisory dict.  When write_runtime=True writes the result
    to runtime/global_signal_fabric_report.json using write_json_atomic so it
    inherits the runtime coherence layer (run_id, source_mode, timestamps).

    NEVER modifies SCM, execution policy, open positions, or paper-execution
    ledgers.
    """
    snapshots = load_snapshot_rows(snapshot_path)
    attribution_events = load_signal_events_from_attribution(attribution_path)
    kill_events = load_signal_events_from_kill_log(kill_log_path)
    snapshot_events = load_signal_events_from_snapshots(snapshot_path)

    all_events: list[SignalEvent] = attribution_events + kill_events + snapshot_events
    total_run_count = max(len(snapshots), 1)

    bull_state_context = classify_fabric_bull_state(snapshots)

    all_tickers = sorted({e.ticker for e in all_events if e.ticker})
    ticker_summaries = [
        s
        for t in all_tickers
        for s in [_build_ticker_summary(t, all_events, total_run_count)]
        if s
    ]

    killed_count = sum(1 for e in all_events if e.signal_state == "REJECTED")
    blocked_count = sum(
        1
        for e in all_events
        if e.blocker_attribution not in {"NONE", "", "UNKNOWN"}
    )

    report: dict[str, Any] = {
        "report_name": "global_signal_fabric_report",
        "schema_version": _SCHEMA_VERSION,
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_gate": _EXECUTION_GATE,
        "advisory_note": (
            "This report is read-only observational context. It does not emit "
            "buy/sell recommendations, does not modify execution policy, and "
            "does not enable capital deployment. All outputs require human review."
        ),
        "fabric_bull_state_context": bull_state_context,
        "fabric_stats": {
            "total_snapshot_rows": len(snapshots),
            "total_signal_events": len(all_events),
            "total_tickers_observed": len(all_tickers),
            "killed_signal_count": killed_count,
            "blocked_signal_count": blocked_count,
            "attribution_event_count": len(attribution_events),
            "kill_log_event_count": len(kill_events),
            "snapshot_event_count": len(snapshot_events),
        },
        "ticker_summaries": ticker_summaries,
        "source_files": {
            "snapshots": str(snapshot_path or SNAPSHOT_LOG_PATH),
            "attribution": str(attribution_path or PER_SIGNAL_ATTRIBUTION_PATH),
            "kill_log": str(kill_log_path or SIGNAL_KILL_LOG_PATH),
        },
        "generated_at": utc_timestamp(),
    }

    if write_runtime:
        target = output_path or GLOBAL_SIGNAL_FABRIC_REPORT_PATH
        write_json_atomic(target, report)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Global Signal Fabric (Phase 1) — advisory-only report"
    )
    parser.add_argument(
        "--write-runtime",
        action="store_true",
        help="Write report to runtime/global_signal_fabric_report.json",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Print full JSON report to stdout",
    )
    args = parser.parse_args()

    report = build_global_signal_fabric_report(write_runtime=args.write_runtime)

    if args.output_json:
        print(json.dumps(report, indent=2))
    else:
        stats = report["fabric_stats"]
        bull = report["fabric_bull_state_context"]["fabric_bull_state"]
        print("Global Signal Fabric")
        print(f"advisory_status={report['advisory_status']}")
        print(f"execution_gate={report['execution_gate']}")
        print(f"fabric_bull_state={bull}")
        print(
            f"snapshots={stats['total_snapshot_rows']} "
            f"events={stats['total_signal_events']} "
            f"tickers={stats['total_tickers_observed']}"
        )


if __name__ == "__main__":
    _main()


__all__ = [
    "GLOBAL_SIGNAL_FABRIC_REPORT_PATH",
    "SignalEvent",
    "SnapshotRow",
    "load_snapshot_rows",
    "load_signal_events_from_attribution",
    "load_signal_events_from_kill_log",
    "load_signal_events_from_snapshots",
    "score_persistence",
    "score_blocker_pressure",
    "score_kill_rate",
    "attach_scores",
    "classify_fabric_bull_state",
    "build_global_signal_fabric_report",
]
