"""WHY_TODAY gate — every candidate must answer "why today, not yesterday?".

A name is only executable if there is a fresh, evidence-based reason to act on
it *today*. This module turns a candidate's ``why_today`` text + freshness
signals into a WHY_TODAY_SCORE used by the executable gate.

Scoring (per operator spec):
    live price/news/filing/event change today      -> 1.00
    static-universe fallback only                  -> 0.25
    repeated yesterday watchlist, no fresh change   -> 0.10
    null / empty / generic / purely historical      -> 0.00

Hard executable rule:
    WHY_TODAY_SCORE(t) < why_today_min_for_executable (default 0.70)
        => EXECUTABLE_BUY(t) = 0
    The candidate can still be BUY-CANDIDATE / NOT-EXECUTABLE.

Pure module: no I/O, no fabrication.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.candidate_memory_decay import fresh_signal_from_freshness
    from scripts.daily_discovery_config import load_discovery_thresholds
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from candidate_memory_decay import fresh_signal_from_freshness
    from daily_discovery_config import load_discovery_thresholds


LIVE_TRIGGER_SCORE = 1.0
STATIC_FALLBACK_SCORE = 0.25
STALE_REPEAT_SCORE = 0.10
MISSING_SCORE = 0.0

# Phrases that, on their own, are NOT a fresh "why today" — purely historical /
# generic conviction language. Used to detect a why_today that does not earn
# more than the static-fallback floor.
_GENERIC_MARKERS = (
    "fundamentals",
    "long-term",
    "long term",
    "secular",
    "always",
    "historically",
    "still like",
    "remains attractive",
    "no change",
    "unchanged",
)

# Markers that indicate a genuine fresh trigger occurred today.
_FRESH_MARKERS = (
    "today",
    "breakout",
    "gap up",
    "gap down",
    "earnings",
    "beat",
    "miss",
    "guidance",
    "upgrade",
    "downgrade",
    "filing",
    "8-k",
    "10-q",
    "10-k",
    "halt",
    "spike",
    "fresh",
    "new development",
    "new order",
    "contract win",
    "this morning",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _is_generic_or_historical(text: str) -> bool:
    lowered = text.lower()
    if not lowered:
        return True
    has_generic = any(marker in lowered for marker in _GENERIC_MARKERS)
    has_fresh = any(marker in lowered for marker in _FRESH_MARKERS)
    return has_generic and not has_fresh


def _mentions_fresh_trigger(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _FRESH_MARKERS)


def why_today_score(
    why_today_text: Any = None,
    *,
    freshness: Any = None,
    fresh_signal_present: bool = False,
    has_live_event_today: bool = False,
    in_yesterday: bool = False,
    is_static_universe_only: bool = False,
) -> float:
    """Return WHY_TODAY_SCORE in {0.0, 0.10, 0.25, 1.0}.

    Precedence: live trigger > static fallback > stale repeat > missing.
    """
    text = _text(why_today_text)
    live_trigger = (
        bool(fresh_signal_present)
        or bool(has_live_event_today)
        or fresh_signal_from_freshness(freshness)
        or (bool(text) and _mentions_fresh_trigger(text) and not _is_generic_or_historical(text))
    )
    if live_trigger:
        return LIVE_TRIGGER_SCORE

    # No fresh trigger. A repeated yesterday name with no fresh change is the
    # weakest still-nonzero state.
    if in_yesterday and not is_static_universe_only:
        if not text or _is_generic_or_historical(text):
            return STALE_REPEAT_SCORE

    if is_static_universe_only:
        return STATIC_FALLBACK_SCORE

    if not text or _is_generic_or_historical(text):
        # Static-fallback wording counts as 0.25; otherwise truly missing -> 0.0.
        if text and "minimum viable daily market universe" in text.lower():
            return STATIC_FALLBACK_SCORE
        if in_yesterday:
            return STALE_REPEAT_SCORE
        return MISSING_SCORE

    # Non-generic, non-historical free text with no recognised fresh marker:
    # treat as static-grade context (research only).
    return STATIC_FALLBACK_SCORE


def classify_why_today(score: float) -> str:
    """Human-readable bucket for a WHY_TODAY_SCORE."""
    if score >= LIVE_TRIGGER_SCORE:
        return "LIVE_TRIGGER"
    if score >= STATIC_FALLBACK_SCORE:
        return "STATIC_FALLBACK"
    if score > MISSING_SCORE:
        return "STALE_REPEAT"
    return "MISSING_OR_GENERIC"


def passes_executable_why_today(
    score: float, thresholds: dict[str, Any] | None = None
) -> bool:
    """True iff WHY_TODAY_SCORE clears the executable floor."""
    table = thresholds or load_discovery_thresholds()
    floor = float(table.get("why_today_min_for_executable", 0.70))
    return float(score) >= floor


def score_candidate_why_today(
    record: dict[str, Any],
    *,
    in_yesterday: bool = False,
) -> dict[str, Any]:
    """Score a candidate record (e.g. a price-mover row) and return a summary."""
    provider = _text(record.get("provider")).upper()
    is_static = provider == "STATIC_UNIVERSE_FALLBACK" or bool(record.get("is_static_universe_only"))
    score = why_today_score(
        record.get("why_today"),
        freshness=record.get("freshness"),
        fresh_signal_present=bool(record.get("fresh_signal_present")),
        has_live_event_today=bool(record.get("has_live_event_today")),
        in_yesterday=in_yesterday,
        is_static_universe_only=is_static,
    )
    return {
        "ticker": _text(record.get("ticker")).upper(),
        "why_today": _text(record.get("why_today")),
        "why_today_score": round(score, 4),
        "why_today_class": classify_why_today(score),
    }


__all__ = [
    "LIVE_TRIGGER_SCORE",
    "STATIC_FALLBACK_SCORE",
    "STALE_REPEAT_SCORE",
    "MISSING_SCORE",
    "why_today_score",
    "classify_why_today",
    "passes_executable_why_today",
    "score_candidate_why_today",
]
