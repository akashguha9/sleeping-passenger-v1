"""Leakage-safe outcome resolution for frozen Decision-Twin predictions.

Resolves a `FalsifiablePrediction` against forward OHLCV bars WITHOUT look-ahead:
entry is the first bar strictly after the information cutoff; a window that has not
fully elapsed by the session date is UNRESOLVED (no peeking). The original
prediction is never mutated — resolution produces a separate `ResolvedOutcome`.

Reuses the same leakage discipline as the calibration harness.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]


def _parse(s: Any):
    try:
        return _dt.date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


@dataclass(slots=True)
class ResolvedOutcome:
    prediction_id: str
    twin_id: str
    candidate_id: str
    kind: str
    resolved: bool
    reason: str                    # RESOLVED | LOOKAHEAD | FUTURE_UNRESOLVED | NO_DATA
    entry_date: str = ""
    exit_date: str = ""
    realized_value: float | None = None   # realized prob-target (0/1) or interval value
    predicted_value: float | None = None
    hit: bool | None = None               # did the prediction come true?
    brier_contribution: float | None = None
    adverse: bool = False
    tail: bool = False
    immutability_hash_checked: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__slots__}
        d.update(advisory_safety_stamps())
        return d


def _forward_bars(bars, cutoff, session):
    fwd = []
    for b in bars:
        d = _parse(b.get("date"))
        c = b.get("adjusted_close")
        if c is None:
            c = b.get("close")
        try:
            c = float(c)
        except (TypeError, ValueError):
            continue
        if d is None or c != c:
            continue
        if d <= cutoff or d > session:
            continue  # strictly after cutoff, not beyond session (no look-ahead)
        fwd.append((d, c))
    fwd.sort(key=lambda x: x[0])
    return fwd


def resolve(prediction: dict[str, Any], forward_bars: list[dict[str, Any]],
            session_date: str) -> ResolvedOutcome:
    """Resolve one frozen prediction dict against forward bars, leakage-safe."""
    pid = prediction.get("prediction_id", "")
    tid = prediction.get("twin_id", "")
    cand = prediction.get("candidate_id", "")
    kind = prediction.get("kind", "PROBABILITY")
    window = int(prediction.get("outcome_window_days", 20))
    cutoff = _parse(prediction.get("info_cutoff"))
    session = _parse(session_date)
    out = ResolvedOutcome(prediction_id=pid, twin_id=tid, candidate_id=cand, kind=kind,
                          resolved=False, reason="NO_DATA",
                          immutability_hash_checked=prediction.get("immutability_hash", ""))
    if cutoff is None or session is None:
        return out
    if cutoff + _dt.timedelta(days=window) > session:
        out.reason = "FUTURE_UNRESOLVED"
        return out
    fwd = _forward_bars(forward_bars, cutoff, session)
    if len(fwd) < 2:
        out.reason = "NO_DATA"
        return out

    entry_d, entry_p = fwd[0]
    target_exit = cutoff + _dt.timedelta(days=window)
    within = [(d, c) for d, c in fwd if d <= target_exit]
    if not within:
        within = fwd[:1]
    exit_d, exit_p = within[-1]
    closes = [c for _, c in within]
    ret_end = exit_p / entry_p - 1.0
    max_dd = min(c / entry_p - 1.0 for c in closes)
    daily_rets = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
    rvol = 0.0
    if len(daily_rets) >= 2:
        m = sum(daily_rets) / len(daily_rets)
        rvol = (sum((x - m) ** 2 for x in daily_rets) / (len(daily_rets) - 1)) ** 0.5

    out.resolved = True
    out.reason = "RESOLVED"
    out.entry_date = entry_d.isoformat()
    out.exit_date = exit_d.isoformat()
    out.adverse = max_dd <= -0.05
    out.tail = max_dd <= -0.10

    target = str(prediction.get("target_variable", "")).lower()
    if kind == "PROBABILITY":
        p = float(prediction.get("probability") or 0.0)
        out.predicted_value = p
        if "tail" in target:
            realized = 1.0 if max_dd <= -0.10 else 0.0
        elif "drawdown" in target or "adverse" in target:
            realized = 1.0 if max_dd <= -0.05 else 0.0
        elif "return > 0" in target or " up" in target:
            realized = 1.0 if ret_end > 0 else 0.0
        else:
            realized = 1.0 if ret_end > 0 else 0.0
        out.realized_value = realized
        out.brier_contribution = round((p - realized) ** 2, 6)
        # "hit" = predicted the more-likely side correctly.
        out.hit = (p >= 0.5) == (realized >= 0.5)
    else:  # INTERVAL
        lo = float(prediction.get("interval_low") or 0.0)
        hi = float(prediction.get("interval_high") or 0.0)
        if "volatility" in target:
            realized = rvol
        else:  # drawdown band
            realized = max_dd
        out.realized_value = round(realized, 6)
        out.predicted_value = round((lo + hi) / 2.0, 6)
        out.hit = lo <= realized <= hi
        out.brier_contribution = 0.0 if out.hit else round(min(abs(realized - lo),
                                                               abs(realized - hi)) ** 2, 6)
    return out


__all__ = ["ResolvedOutcome", "resolve"]
