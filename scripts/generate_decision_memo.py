"""Human decision memo generator (Pass 4).

Renders one advisory signal into a structured markdown memo a human can
act on — or, just as importantly, decline to act on. The memo carries
the evidence, the contradictions, what's missing, what would falsify the
idea, and a blank HUMAN decision line, because the decision is never the
machine's.

Banned phrases (test-pinned): the memo generator REFUSES to emit
"guaranteed", "sure profit", "must buy", "automatic trade", "execute
now" and friends — both from its own templates and from any
caller-supplied text smuggled in.

Output: reports/decision_memos/<ticker>_<timestamp>.md (gitignored).
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
MEMO_DIR = _REPO_ROOT / "reports" / "decision_memos"

BANNED_PHRASES = (
    "guaranteed", "sure profit", "must buy", "must sell", "automatic trade",
    "auto-trade", "execute now", "cannot lose", "risk-free profit",
    "place order", "executing trade",
)


class MemoError(ValueError):
    """Raised when memo content violates the advisory contract."""


def _check_banned(text: str) -> None:
    low = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in low:
            raise MemoError(
                f"banned phrase {phrase!r} — advisory memos never promise "
                "or command execution"
            )


def render_memo(signal: dict) -> str:
    """Render the memo markdown from a signal dict (raises on banned text).

    Expected keys (missing ones render as the honest 'NOT PROVIDED'):
    ticker, signal, confidence, evidence_summary, contradictory_evidence,
    missing_data, temporal_validity, backtest_context, calibration_context,
    risk_notes, falsifiers, review_after_days.
    """
    ticker = str(signal.get("ticker", "")).strip().upper()
    if not ticker:
        raise MemoError("ticker is mandatory")
    confidence = signal.get("confidence")
    if confidence is not None and not (0.0 <= float(confidence) <= 1.0):
        raise MemoError(f"confidence {confidence} outside [0,1]")

    def field(key: str) -> str:
        value = str(signal.get(key, "") or "").strip()
        return value if value else "NOT PROVIDED — treat absence as a warning"

    now = _dt.datetime.now(_dt.timezone.utc)
    review_days = int(signal.get("review_after_days", 30) or 30)
    review_date = (now + _dt.timedelta(days=review_days)).date().isoformat()

    memo = "\n".join([
        f"# Decision memo — {ticker}",
        "",
        f"Ticker: {ticker}",
        f"Timestamp: {now.isoformat()}",
        "Advisory-only status: ADVISORY_ONLY — this memo informs a human "
        "decision; nothing executes, no broker exists in this system.",
        f"Signal: {field('signal')}",
        f"Confidence: {confidence if confidence is not None else 'NOT PROVIDED'}",
        "",
        "## Evidence summary",
        field("evidence_summary"),
        "",
        "## Contradictory evidence",
        field("contradictory_evidence"),
        "",
        "## Known missing data",
        field("missing_data"),
        "",
        "## Temporal validity",
        field("temporal_validity"),
        "",
        "## Backtest context",
        field("backtest_context"),
        "",
        "## Calibration context",
        field("calibration_context"),
        "",
        "## Risk notes",
        field("risk_notes"),
        "",
        "## What would falsify this idea",
        field("falsifiers"),
        "",
        "## Human decision",
        "_(to be filled by the owner — the system never decides)_",
        "",
        f"Post-decision review date: {review_date}",
        "",
    ])
    _check_banned(memo)
    return memo


def write_memo(signal: dict, out_dir: Path | None = None) -> Path:
    memo = render_memo(signal)
    out_dir = out_dir or MEMO_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ticker = re.sub(r"[^A-Z0-9.-]", "", str(signal["ticker"]).upper()) or "UNKNOWN"
    path = out_dir / f"{ticker}_{stamp}.md"
    path.write_text(memo, encoding="utf-8")
    return path
