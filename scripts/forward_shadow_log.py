"""T7 — forward shadow log for the entry-quality gate.

Records each day's candidates with the gate's verdict and (later) the
realized outcome, so we can build the out-of-sample sample the brief
requires before judging any rule.

Why this exists (audit T7 / "more winners honestly"):
    The 37-trade backtest is too small and lives in a single short
    window. The fix is not to keep tuning against it; it is to start
    collecting OUT-OF-SAMPLE evidence and refuse to update rules until
    we have enough.

Bar to clear (operator policy):
    >= MIN_FORWARD_TRADES (default 100) resolved trades across at least
    MIN_REGIMES (default 2) distinct regime tags (e.g. "trending_up",
    "chop", "drawdown") before any threshold change is considered
    "validated" by the forward log.

Format:
    JSONL at runtime/forward_shadow_log.jsonl. Append-only. Each line is
    one event:
        {"event_type": "pick_decision", "as_of": ..., "ticker": ...,
         "would_have_bought": bool, "gate_pass": bool, "score": ...,
         "components": {...}, "regime_tag": ...}
        {"event_type": "trade_resolved", "ticker": ..., "buy_date": ...,
         "result": ..., "pl_eur_net": ..., "regime_tag": ...}

The log is advisory only. Nothing reads from it to authorize execution.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.runtime_common import REPO_ROOT
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from runtime_common import REPO_ROOT


DEFAULT_LOG_PATH = REPO_ROOT / "runtime" / "forward_shadow_log.jsonl"

# Operator policy. Do NOT lower these to make rule judgments easier --
# the brief's whole point is that 37 trades is not enough.
MIN_FORWARD_TRADES = 100
MIN_REGIMES = 2


@dataclass(frozen=True)
class ReadinessReport:
    """Whether the forward log has accumulated enough evidence to judge
    rules. The operator should refuse to retune entry thresholds until
    ``ready=True``."""
    resolved_trades: int
    distinct_regimes: list[str]
    ready: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "resolved_trades": self.resolved_trades,
            "distinct_regimes": self.distinct_regimes,
            "ready": self.ready,
            "reason": self.reason,
            "thresholds": {
                "min_forward_trades": MIN_FORWARD_TRADES,
                "min_regimes": MIN_REGIMES,
            },
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append(log_path: Path, event: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


def log_pick_decision(
    *,
    as_of: str,
    ticker: str,
    gate_pass: bool,
    entry_quality_score: float,
    components: dict[str, Any],
    would_have_bought: bool,
    regime_tag: str = "unknown",
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Record one daily candidate verdict. ``would_have_bought`` is the
    operator's would-have-acted answer, NOT a broker call. The gate's
    decision and the would-have-bought decision are recorded separately
    so we can analyze gate-blocked-but-good and gate-passed-but-bad cases.
    """
    event = {
        "event_type": "pick_decision",
        "logged_at": _now_iso(),
        "as_of": as_of,
        "ticker": ticker,
        "gate_pass": bool(gate_pass),
        "entry_quality_score": float(entry_quality_score),
        "components": components,
        "would_have_bought": bool(would_have_bought),
        "regime_tag": regime_tag,
        "advisory_status": "ADVISORY_ONLY",
        "broker_api_called": False,
    }
    _append(log_path or DEFAULT_LOG_PATH, event)
    return event


def log_trade_resolved(
    *,
    ticker: str,
    buy_date: str,
    result: str,
    pl_eur_gross: float,
    pl_eur_net: float,
    execution_cost_eur: float,
    regime_tag: str = "unknown",
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Record a resolved (closed or marked-out) shadow trade so it counts
    toward the forward-trades tally."""
    event = {
        "event_type": "trade_resolved",
        "logged_at": _now_iso(),
        "ticker": ticker,
        "buy_date": buy_date,
        "result": result,
        "pl_eur_gross": float(pl_eur_gross),
        "pl_eur_net": float(pl_eur_net),
        "execution_cost_eur": float(execution_cost_eur),
        "regime_tag": regime_tag,
        "advisory_status": "ADVISORY_ONLY",
        "broker_api_called": False,
    }
    _append(log_path or DEFAULT_LOG_PATH, event)
    return event


def read_events(log_path: Path | None = None) -> list[dict[str, Any]]:
    p = log_path or DEFAULT_LOG_PATH
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def readiness(log_path: Path | None = None) -> ReadinessReport:
    """Has the forward log accumulated enough OOS evidence to judge rules?

    Bar: at least ``MIN_FORWARD_TRADES`` resolved trades across at least
    ``MIN_REGIMES`` distinct regime tags. Otherwise the report says NOT
    READY and the operator is expected to refuse threshold changes.
    """
    events = read_events(log_path)
    resolved = [e for e in events if e.get("event_type") == "trade_resolved"]
    regimes = sorted({str(e.get("regime_tag") or "unknown") for e in resolved})
    enough_trades = len(resolved) >= MIN_FORWARD_TRADES
    enough_regimes = len(regimes) >= MIN_REGIMES
    ready = enough_trades and enough_regimes
    if ready:
        reason = (
            f"{len(resolved)} resolved trades across {len(regimes)} regimes "
            f"({regimes}) -- bar cleared."
        )
    else:
        missing = []
        if not enough_trades:
            missing.append(
                f"{len(resolved)} of {MIN_FORWARD_TRADES} forward trades"
            )
        if not enough_regimes:
            missing.append(f"{len(regimes)} of {MIN_REGIMES} regimes")
        reason = "Not ready: still need " + " and ".join(missing) + "."
    return ReadinessReport(
        resolved_trades=len(resolved),
        distinct_regimes=regimes,
        ready=ready,
        reason=reason,
    )


def gate_blocked_but_resolved_wins(
    events: Iterable[dict[str, Any]] | None = None,
    log_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Surface candidates the gate blocked that would have been WINS.

    Returns the join of (pick_decision with gate_pass=False) and the
    matching (trade_resolved with positive net P/L) on (ticker, as_of/
    buy_date). Used by the operator to ask "did the gate cost us money?"
    -- WITHOUT auto-tuning the gate against the answer.
    """
    evs = list(events) if events is not None else read_events(log_path)
    blocked = {
        (e["ticker"], e["as_of"]): e
        for e in evs
        if e.get("event_type") == "pick_decision" and not e.get("gate_pass")
    }
    out: list[dict[str, Any]] = []
    for e in evs:
        if e.get("event_type") != "trade_resolved":
            continue
        if e.get("pl_eur_net", 0.0) <= 0:
            continue
        key = (e.get("ticker"), e.get("buy_date"))
        decision = blocked.get(key)
        if decision is not None:
            out.append({
                "ticker": e["ticker"],
                "buy_date": e.get("buy_date"),
                "pl_eur_net": e.get("pl_eur_net"),
                "gate_score": decision.get("entry_quality_score"),
                "gate_reasons": decision.get("components"),
            })
    return out


__all__ = [
    "MIN_FORWARD_TRADES",
    "MIN_REGIMES",
    "DEFAULT_LOG_PATH",
    "ReadinessReport",
    "log_pick_decision",
    "log_trade_resolved",
    "read_events",
    "readiness",
    "gate_blocked_but_resolved_wins",
]
