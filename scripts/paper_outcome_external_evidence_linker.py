"""Paper-outcome → external-evidence linker (dry-run-first, advisory-only).

KANTE_PAPER_OUTCOME_EXTERNAL_EVIDENCE_LINKER
============================================

Closed Paper Outcome Corpus Sprint, Workstream B.  A validated closed paper
outcome is only calibration-useful if it can be paired with the
*evidence-at-time-t* snapshot(s) that existed when the signal fired.  This
module is the matcher: for each closed outcome it scores every candidate
external-evidence snapshot and classifies the link as AUTO / REVIEW / NO_LINK.

It is pure-recovery, defensive work: it scores, it never writes, and a link can
NEVER affect real-money sizing.  The score is advisory metadata only — the
actual outcome recording (and its guarded write) is performed downstream by
:func:`scripts.external_evidence_moltbook_calibration.record_external_evidence_outcome_for_trade`.

Matching priority (highest signal first)
----------------------------------------
1. ``signal_id`` exact match
2. ``trade_id`` present in the snapshot's context
3. ``ticker`` + 72h pre-entry time window
4. ``ticker`` only  → always REVIEW (human must confirm)

Time window
-----------
    snapshot.generated_at_utc <= entry_timestamp_utc
    snapshot.generated_at_utc >= entry_timestamp_utc - 72h

Link confidence
---------------
    link_confidence =
        0.50 * signal_id_match
      + 0.20 * ticker_match
      + 0.20 * time_window_match
      + 0.10 * source_context_match

Classification
--------------
    AUTO_LINK   if confidence >= 0.90
    REVIEW_LINK if 0.60 <= confidence < 0.90
    NO_LINK     if confidence < 0.60
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import external_evidence_persistence as _eep
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import external_evidence_persistence as _eep  # type: ignore[no-redef]


# --- weights (per the sprint spec) ------------------------------------------
W_SIGNAL_ID = 0.50
W_TICKER = 0.20
W_TIME_WINDOW = 0.20
W_SOURCE_CONTEXT = 0.10

TIME_WINDOW_HOURS = 72

AUTO_LINK = "AUTO_LINK"
REVIEW_LINK = "REVIEW_LINK"
NO_LINK = "NO_LINK"

AUTO_LINK_MIN = 0.90
REVIEW_LINK_MIN = 0.60

REAL_MONEY_SIZING_IMPACT = "PROHIBITED"
_PROOF = "PAPER_OUTCOME_EVIDENCE_LINK_ADVISORY_ONLY"


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _parse_ts(value: Any) -> datetime | None:
    s = _s(value)
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _classify(confidence: float) -> str:
    if confidence >= AUTO_LINK_MIN:
        return AUTO_LINK
    if confidence >= REVIEW_LINK_MIN:
        return REVIEW_LINK
    return NO_LINK


def _snapshot_context_has_trade_id(snapshot: dict[str, Any], trade_id: str) -> bool:
    """True if a non-empty ``trade_id`` appears anywhere in the snapshot context.

    Checks the explicit outcome/candidate id columns; never trusts a blank.
    """
    if not trade_id:
        return False
    for key in ("outcome_trade_id", "candidate_id", "trade_id"):
        if _s(snapshot.get(key)) == trade_id:
            return True
    return False


def score_link(
    outcome: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    time_window_hours: int = TIME_WINDOW_HOURS,
) -> dict[str, Any]:
    """Score one (closed outcome, snapshot) pair (pure).  Never raises.

    Returns the four sub-matches, the weighted ``link_confidence``, the
    ``link_classification``, and the unconditional real-money-prohibited stamp.
    A link is advisory metadata only — it can never affect real-money sizing.
    """
    out_signal = _s(outcome.get("signal_id"))
    out_ticker = _s(outcome.get("ticker")).upper()
    out_trade_id = _s(outcome.get("trade_id"))
    entry_ts = _parse_ts(outcome.get("entry_timestamp_utc"))

    snap_signal = _s(snapshot.get("signal_id"))
    snap_ticker = _s(snapshot.get("ticker")).upper()
    snap_generated = _parse_ts(snapshot.get("generated_at_utc"))

    signal_id_match = 1 if (out_signal and out_signal == snap_signal) else 0
    ticker_match = 1 if (out_ticker and out_ticker == snap_ticker) else 0

    time_window_match = 0
    if entry_ts is not None and snap_generated is not None:
        window_start = entry_ts - timedelta(hours=time_window_hours)
        if window_start <= snap_generated <= entry_ts:
            time_window_match = 1

    source_context_match = (
        1 if _snapshot_context_has_trade_id(snapshot, out_trade_id) else 0
    )

    link_confidence = (
        W_SIGNAL_ID * signal_id_match
        + W_TICKER * ticker_match
        + W_TIME_WINDOW * time_window_match
        + W_SOURCE_CONTEXT * source_context_match
    )
    link_confidence = round(link_confidence, 6)

    return {
        "snapshot_id": _s(snapshot.get("snapshot_id")),
        "trade_id": out_trade_id,
        "signal_id": out_signal,
        "ticker": out_ticker,
        "source_name": _s(snapshot.get("source_name")),
        "signal_id_match": signal_id_match,
        "ticker_match": ticker_match,
        "time_window_match": time_window_match,
        "source_context_match": source_context_match,
        "link_confidence": link_confidence,
        "link_classification": _classify(link_confidence),
        # A link is advisory metadata only — never a sizing input.
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "real_money_weight_allowed": False,
        "proof_status": _PROOF,
    }


def link_outcome_to_snapshots(
    outcome: dict[str, Any],
    snapshots: list[dict[str, Any]] | None,
    *,
    time_window_hours: int = TIME_WINDOW_HOURS,
) -> dict[str, Any]:
    """Score one closed outcome against a list of candidate snapshots (pure).

    Returns a per-outcome link report: the scored candidates (sorted best
    first), the best classification, and the AUTO/REVIEW/NO_LINK counts.  When
    there are no candidate snapshots the result is an honest NO_LINK with zero
    candidates — never an invented match.
    """
    snapshots = list(snapshots or [])
    scored = [
        score_link(outcome, snap, time_window_hours=time_window_hours)
        for snap in snapshots
        if isinstance(snap, dict)
    ]
    scored.sort(key=lambda s: s["link_confidence"], reverse=True)

    auto = [s for s in scored if s["link_classification"] == AUTO_LINK]
    review = [s for s in scored if s["link_classification"] == REVIEW_LINK]

    if auto:
        best_classification = AUTO_LINK
    elif review:
        best_classification = REVIEW_LINK
    else:
        best_classification = NO_LINK

    return {
        "trade_id": _s(outcome.get("trade_id")),
        "signal_id": _s(outcome.get("signal_id")),
        "ticker": _s(outcome.get("ticker")).upper(),
        "candidate_count": len(scored),
        "candidates": scored,
        "best_link_classification": best_classification,
        "best_link_confidence": scored[0]["link_confidence"] if scored else 0.0,
        "auto_link_count": len(auto),
        "review_link_count": len(review),
        "no_link_count": len(scored) - len(auto) - len(review),
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "real_money_weight_allowed": False,
        "proof_status": _PROOF,
    }


# --- read-only DB candidate loader ------------------------------------------


def load_candidate_snapshots(
    outcome: dict[str, Any],
    *,
    db_path: Path | None = None,
    conn: Any = None,
) -> list[dict[str, Any]]:
    """Load unlinked candidate snapshots for an outcome (read-only).

    Reuses :func:`scripts.external_evidence_persistence.load_unlinked_external_evidence_for_trade`
    (signal-id-then-ticker precedence).  Never mutates anything.
    """
    return _eep.load_unlinked_external_evidence_for_trade(
        signal_id=_s(outcome.get("signal_id")),
        ticker=_s(outcome.get("ticker")),
        db_path=db_path,
        conn=conn,
    )


def link_outcome_from_db(
    outcome: dict[str, Any],
    *,
    db_path: Path | None = None,
    conn: Any = None,
    time_window_hours: int = TIME_WINDOW_HOURS,
) -> dict[str, Any]:
    """Load candidate snapshots read-only, then score the links (no writes)."""
    snapshots = load_candidate_snapshots(outcome, db_path=db_path, conn=conn)
    return link_outcome_to_snapshots(
        outcome, snapshots, time_window_hours=time_window_hours
    )


def build_link_report(
    outcomes: list[dict[str, Any]] | None,
    *,
    db_path: Path | None = None,
    conn: Any = None,
) -> dict[str, Any]:
    """Aggregate read-only link reports over many closed outcomes."""
    outcomes = list(outcomes or [])
    per_outcome = [
        link_outcome_from_db(o, db_path=db_path, conn=conn) for o in outcomes
    ]
    auto = sum(1 for r in per_outcome if r["best_link_classification"] == AUTO_LINK)
    review = sum(1 for r in per_outcome if r["best_link_classification"] == REVIEW_LINK)
    no_link = sum(1 for r in per_outcome if r["best_link_classification"] == NO_LINK)
    return {
        "report": "paper_outcome_external_evidence_linker",
        "outcomes_seen": len(per_outcome),
        "linked_auto": auto,
        "linked_review": review,
        "no_link": no_link,
        "per_outcome": per_outcome,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "real_money_weight_allowed": False,
        "proof_status": _PROOF,
    }


# --- CLI --------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="paper_outcome_external_evidence_linker.py",
        description=(
            "Score closed paper outcomes against external-evidence snapshots. "
            "Read-only; advisory-only; a link never affects real-money sizing."
        ),
    )
    p.add_argument(
        "--input",
        required=True,
        help="path to closed-outcome CSV/JSON (uses paper_outcome_intake loader)",
    )
    p.add_argument("--db-path", default=None, help="canonical DB path override")
    p.add_argument("--json", action="store_true", help="emit the JSON report")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        from scripts.paper_outcome_intake import load_records
    except ModuleNotFoundError:  # pragma: no cover
        from paper_outcome_intake import load_records  # type: ignore[no-redef]

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] input not found: {input_path}")
        return 1
    try:
        outcomes = load_records(input_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] could not parse {input_path}: {exc}")
        return 1

    db_path = Path(args.db_path) if args.db_path else None
    report = build_link_report(outcomes, db_path=db_path)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("paper_outcome_external_evidence_linker")
        print(f"  outcomes_seen : {report['outcomes_seen']}")
        print(f"  linked_auto   : {report['linked_auto']}")
        print(f"  linked_review : {report['linked_review']}")
        print(f"  no_link       : {report['no_link']}")
        print(f"  real-money    : {report['real_money_sizing_impact']}")
    return 0


__all__ = [
    "W_SIGNAL_ID",
    "W_TICKER",
    "W_TIME_WINDOW",
    "W_SOURCE_CONTEXT",
    "TIME_WINDOW_HOURS",
    "AUTO_LINK",
    "REVIEW_LINK",
    "NO_LINK",
    "score_link",
    "link_outcome_to_snapshots",
    "load_candidate_snapshots",
    "link_outcome_from_db",
    "build_link_report",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
