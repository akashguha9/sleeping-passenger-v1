"""Rejected-candidate learning tracker (advisory-only).

Moltbook must learn from BOTH correct rejections and false negatives — names
the discovery board declined that then ran.  This module classifies the
*quality* of a past rejection once a forward horizon return is known, and emits
an advisory Moltbook review entry.  It scores nothing for real-money sizing and
never recommends a trade.

Classification (5-day horizon)::

    r5  = later_5d_return
    mfe = max_favorable_after_rejection
    mae = max_adverse_after_rejection

    r5 missing                      -> PENDING_HORIZON
    r5 >= 0.05 or mfe >= 0.08        -> FALSE_NEGATIVE_REVIEW
    r5 <= -0.03 and mae <= -0.05     -> CORRECT_REJECTION
    abs(r5) < 0.02                   -> NEUTRAL_REJECTION
    otherwise                        -> INCONCLUSIVE_REVIEW

Contract — pure module: no DB, no network, no broker calls, no AI execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import sys

    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

FALSE_NEGATIVE_REVIEW = "FALSE_NEGATIVE_REVIEW"
CORRECT_REJECTION = "CORRECT_REJECTION"
NEUTRAL_REJECTION = "NEUTRAL_REJECTION"
INCONCLUSIVE_REVIEW = "INCONCLUSIVE_REVIEW"
PENDING_HORIZON = "PENDING_HORIZON"

_LESSON = {
    FALSE_NEGATIVE_REVIEW: (
        "Candidate ran after rejection — review whether the rejection reason was "
        "too strict or mis-scored."
    ),
    CORRECT_REJECTION: "Rejection avoided a drawdown — reason held up.",
    NEUTRAL_REJECTION: "Little movement either way — rejection was low-cost.",
    INCONCLUSIVE_REVIEW: "Mixed signal — keep observing before drawing a lesson.",
    PENDING_HORIZON: "Horizon not yet elapsed — do not score this rejection yet.",
}


@dataclass(frozen=True)
class RejectedCandidate:
    date_rejected: date | None = None
    ticker: str = ""
    country: str = ""
    sector: str | None = None
    discovery_score: float = 0.0
    rejection_reason: str = ""
    later_1d_return: float | None = None
    later_3d_return: float | None = None
    later_5d_return: float | None = None
    later_10d_return: float | None = None
    max_favorable_after_rejection: float | None = None
    max_adverse_after_rejection: float | None = None
    rejection_quality: str | None = None


def classify_rejection_quality(rc: RejectedCandidate) -> str:
    r5 = rc.later_5d_return
    mfe = rc.max_favorable_after_rejection
    mae = rc.max_adverse_after_rejection

    if r5 is None and mfe is None:
        return PENDING_HORIZON
    if (r5 is not None and r5 >= 0.05) or (mfe is not None and mfe >= 0.08):
        return FALSE_NEGATIVE_REVIEW
    if r5 is None:
        return PENDING_HORIZON
    if r5 <= -0.03 and (mae is not None and mae <= -0.05):
        return CORRECT_REJECTION
    if abs(r5) < 0.02:
        return NEUTRAL_REJECTION
    return INCONCLUSIVE_REVIEW


def to_moltbook_entry(rc: RejectedCandidate) -> dict[str, Any]:
    """Build an advisory Moltbook review entry for one rejected candidate."""
    quality = rc.rejection_quality or classify_rejection_quality(rc)
    entry: dict[str, Any] = {
        "event_type": "rejected_candidate_review",
        "date_rejected": rc.date_rejected.isoformat() if rc.date_rejected else None,
        "ticker": rc.ticker,
        "country": rc.country,
        "sector": rc.sector,
        "discovery_score": rc.discovery_score,
        "rejection_reason": rc.rejection_reason,
        "horizon_return": rc.later_5d_return,
        "max_favorable_after_rejection": rc.max_favorable_after_rejection,
        "max_adverse_after_rejection": rc.max_adverse_after_rejection,
        "classification": quality,
        "lesson": _LESSON.get(quality, ""),
        "advisory_only": True,
    }
    entry.update(advisory_safety_stamps())
    entry["human_execution_required"] = True
    return entry


def summarize_rejections(rejections: Iterable[RejectedCandidate]) -> dict[str, Any]:
    counts: dict[str, int] = {
        FALSE_NEGATIVE_REVIEW: 0,
        CORRECT_REJECTION: 0,
        NEUTRAL_REJECTION: 0,
        INCONCLUSIVE_REVIEW: 0,
        PENDING_HORIZON: 0,
    }
    entries: list[dict[str, Any]] = []
    for rc in rejections:
        entry = to_moltbook_entry(rc)
        counts[entry["classification"]] = counts.get(entry["classification"], 0) + 1
        entries.append(entry)
    scored = sum(v for k, v in counts.items() if k != PENDING_HORIZON)
    false_neg_rate = (
        counts[FALSE_NEGATIVE_REVIEW] / scored if scored else None
    )
    out: dict[str, Any] = {
        "total": len(entries),
        "counts": counts,
        "false_negative_rate": round(false_neg_rate, 4) if false_neg_rate is not None else None,
        "entries": entries,
    }
    out.update(advisory_safety_stamps())
    out["human_execution_required"] = True
    return out


__all__ = [
    "FALSE_NEGATIVE_REVIEW",
    "CORRECT_REJECTION",
    "NEUTRAL_REJECTION",
    "INCONCLUSIVE_REVIEW",
    "PENDING_HORIZON",
    "RejectedCandidate",
    "classify_rejection_quality",
    "to_moltbook_entry",
    "summarize_rejections",
]
