"""Operator review queue — what must be fixed before outcomes calibrate.

KANTE_PAPER_OUTCOME_REVIEW_QUEUE
================================

Kanté Outcome Corpus Hardening Sprint, Workstream C.  Counting staged outcomes
is not enough; an operator needs to know *what is blocking* each one from
becoming calibration-grade, and which blockers to clear first.  This module
reads the canonical ``paper_outcome_staging`` table and emits a ranked,
read-only review queue.

It is the Kanté "show the team where the danger is" work: it never writes, it
never invents an outcome, and it never enables real-money sizing.  It only
surfaces the blockers that already exist in the staged data.

Hard safety contract
--------------------
* :func:`row_blockers` / :func:`build_review_queue` are pure — no I/O.
* The loader is strictly read-only (it reuses
  :func:`paper_outcome_staging.load_staging_rows`).
* No writes by default.  No execution-instruction wording is ever emitted.
* ``real_money_sizing_impact`` is always ``PROHIBITED``.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import paper_outcome_staging as _staging
    from scripts import paper_outcome_intake as _intake
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import paper_outcome_staging as _staging  # type: ignore[no-redef]
    import paper_outcome_intake as _intake  # type: ignore[no-redef]
    import advisory_contract as _contract  # type: ignore[no-redef]


REAL_MONEY_SIZING_IMPACT = "PROHIBITED"
_PROOF = "PAPER_OUTCOME_REVIEW_QUEUE_PAPER_ONLY"
_RETURN_TOLERANCE = 0.05

# The full blocker vocabulary (per the sprint spec).
BLOCKER_KEYS: tuple[str, ...] = (
    "missing_signal_id",
    "bad_return_math",
    "missing_exit_price",
    "missing_entry_price",
    "missing_external_evidence_link",
    "missing_moltbook_record",
    "invalid_time_order",
    "proof_status_weak",
    "duplicate_trade_id",
    "open_trade_not_closed",
)

# A Moltbook learning status that means the outcome has actually been recorded
# into the advisory calibration loop (anything else still needs the record).
_MOLTBOOK_RECORDED = "RECORDED"


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def row_blockers(row: dict[str, Any], *, duplicate_trade_id: bool = False) -> list[str]:
    """Return the list of blockers for one staging row (pure).  Never raises.

    ``duplicate_trade_id`` is passed in by the aggregator because it is a
    cross-row property (the same ``trade_id`` staged under two content keys).
    """
    row = dict(row or {})
    blockers: list[str] = []

    entry_price = _f(row.get("entry_price"))
    exit_price = _f(row.get("exit_price"))
    realized = _f(row.get("realized_return_pct"))

    if not _s(row.get("signal_id")):
        blockers.append("missing_signal_id")
    if entry_price is None:
        blockers.append("missing_entry_price")
    if exit_price is None:
        blockers.append("missing_exit_price")

    # An open trade should never have been staged — if one is present, surface
    # it loudly rather than letting it pass as a closed outcome.
    if exit_price is None or not _s(row.get("exit_timestamp_utc")):
        blockers.append("open_trade_not_closed")

    # Return math: only checkable when both prices + the input return exist.
    if entry_price is not None and exit_price is not None and entry_price > 0:
        expected = 100.0 * (exit_price - entry_price) / entry_price
        if realized is None or abs(realized - expected) > _RETURN_TOLERANCE:
            blockers.append("bad_return_math")

    entry_ts = _parse_ts(row.get("entry_timestamp_utc"))
    exit_ts = _parse_ts(row.get("exit_timestamp_utc"))
    if entry_ts is not None and exit_ts is not None and exit_ts < entry_ts:
        blockers.append("invalid_time_order")

    if _s(row.get("link_status")) != _staging_auto_link():
        blockers.append("missing_external_evidence_link")

    if _s(row.get("moltbook_learning_status")).upper() != _MOLTBOOK_RECORDED:
        blockers.append("missing_moltbook_record")

    proof = _s(row.get("proof_status")).upper()
    if proof not in _intake.ALLOWED_PROOF_STATUSES:
        blockers.append("proof_status_weak")

    if duplicate_trade_id:
        blockers.append("duplicate_trade_id")

    return blockers


def _staging_auto_link() -> str:
    # Kept as a function so the linker constant stays the single source of truth.
    try:
        from scripts.paper_outcome_external_evidence_linker import AUTO_LINK
    except ModuleNotFoundError:  # pragma: no cover
        from paper_outcome_external_evidence_linker import AUTO_LINK  # type: ignore
    return AUTO_LINK


def _blocker_priority_score(counts: dict[str, int], n_rows: int) -> float:
    """Weighted blocker-priority score (per the sprint spec).

    ``0.30*missing_required_price + 0.25*invalid_return_math +
    0.20*missing_signal_link + 0.15*missing_external_evidence_link +
    0.10*weak_proof_status`` — each term a rate over the staged rows.
    """
    denom = float(max(n_rows, 1))
    missing_required_price = (
        counts.get("missing_entry_price", 0) + counts.get("missing_exit_price", 0)
    ) / denom
    invalid_return_math = counts.get("bad_return_math", 0) / denom
    missing_signal_link = counts.get("missing_signal_id", 0) / denom
    missing_evidence_link = counts.get("missing_external_evidence_link", 0) / denom
    weak_proof = counts.get("proof_status_weak", 0) / denom
    return round(
        0.30 * missing_required_price
        + 0.25 * invalid_return_math
        + 0.20 * missing_signal_link
        + 0.15 * missing_evidence_link
        + 0.10 * weak_proof,
        6,
    )


def build_review_queue(rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Aggregate the operator review queue over staged rows (pure).

    Returns per-row review items, the blocker counts, the ranked top blockers,
    the next 5 operator actions, and the calibration-ready / review-required /
    rejected counts.  Never raises; never writes; never enables sizing.
    """
    rows = list(rows or [])
    n_rows = len(rows)

    # Cross-row duplicate trade_id detection (same id under >1 content key).
    id_seen: dict[str, int] = {}
    for r in rows:
        tid = _s(r.get("trade_id"))
        if tid:
            id_seen[tid] = id_seen.get(tid, 0) + 1
    dup_ids = {tid for tid, n in id_seen.items() if n > 1}

    review_items: list[dict[str, Any]] = []
    blocker_counts: dict[str, int] = {k: 0 for k in BLOCKER_KEYS}
    calibration_ready = 0
    review_required = 0
    rejected = 0

    for r in rows:
        tid = _s(r.get("trade_id"))
        blockers = row_blockers(r, duplicate_trade_id=tid in dup_ids)
        for b in blockers:
            blocker_counts[b] = blocker_counts.get(b, 0) + 1

        classification = _s(r.get("classification"))
        is_valid = int(r.get("valid_for_calibration") or 0) == 1
        needs_review = int(r.get("operator_review_required") or 0) == 1
        if classification == _intake.REJECTED_INSUFFICIENT_PROOF:
            rejected += 1
        if is_valid and not needs_review and not blockers:
            calibration_ready += 1
        elif needs_review or blockers:
            review_required += 1

        review_items.append(
            {
                "trade_id": tid,
                "signal_id": _s(r.get("signal_id")),
                "ticker": _s(r.get("ticker")),
                "classification": classification,
                "link_status": _s(r.get("link_status")),
                "blockers": blockers,
                "blocker_count": len(blockers),
            }
        )

    # Rank blockers: most-frequent first, ties broken by spec ordering.
    ranked = sorted(
        ((k, v) for k, v in blocker_counts.items() if v > 0),
        key=lambda kv: (-kv[1], BLOCKER_KEYS.index(kv[0])),
    )
    top_blockers = [{"blocker": k, "count": v} for k, v in ranked]

    out: dict[str, Any] = {
        "report": "paper_outcome_review_queue",
        "staged_outcomes_count": n_rows,
        "review_items": review_items,
        "blocker_counts": blocker_counts,
        "top_blockers": top_blockers[:5],
        "next_5_operator_actions": _next_actions(top_blockers, n_rows),
        "calibration_ready_count": calibration_ready,
        "review_required_count": review_required,
        "rejected_count": rejected,
        "blocker_priority_score": _blocker_priority_score(blocker_counts, n_rows),
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "real_money_weight_allowed": False,
        "proof_status": _PROOF,
    }
    out.update(_contract.advisory_safety_stamps())
    out["advisory_only"] = True
    out["human_execution_required"] = True
    out["operator_execution_required"] = True
    out["real_money_sizing_impact"] = REAL_MONEY_SIZING_IMPACT
    out["real_money_weight_allowed"] = False
    out["proof_status"] = _PROOF
    return out


# Operator-facing remediation phrasing per blocker (advisory wording only — no
# execution / trade CTAs).
_ACTION_FOR_BLOCKER: dict[str, str] = {
    "missing_entry_price": "Fill the missing entry price for staged outcomes (never invent it).",
    "missing_exit_price": "Fill the missing exit price for staged outcomes (never invent it).",
    "bad_return_math": "Reconcile realized_return_pct against (exit-entry)/entry for flagged rows.",
    "missing_signal_id": "Backfill the signal_id linking each outcome to its originating signal.",
    "missing_external_evidence_link": "Link outcomes to external-evidence snapshots via calibration_corpus_builder (dry-run first).",
    "missing_moltbook_record": "Record auto-linked outcomes into the Moltbook calibration loop.",
    "invalid_time_order": "Correct exit-before-entry timestamps for flagged outcomes.",
    "proof_status_weak": "Confirm a PAPER_VERIFIED / OPERATOR_CONFIRMED proof_status for staged outcomes.",
    "duplicate_trade_id": "Deduplicate trade_ids staged under conflicting prices/timestamps.",
    "open_trade_not_closed": "Remove open trades from the corpus — only closed outcomes calibrate.",
}


def _next_actions(top_blockers: list[dict[str, Any]], n_rows: int) -> list[str]:
    """The next (up to 5) operator actions, ordered by blocker frequency."""
    actions: list[str] = []
    if n_rows == 0:
        return [
            "Stage closed paper outcomes via paper_outcome_importer --apply "
            "(dry-run first); target 50-100."
        ]
    for entry in top_blockers:
        msg = _ACTION_FOR_BLOCKER.get(entry["blocker"])
        if msg and msg not in actions:
            actions.append(msg)
        if len(actions) >= 5:
            break
    if not actions:
        actions.append("Corpus clean; keep accumulating toward 50-100 closed outcomes.")
    actions.append("Real-money readiness remains low by design — keep sizing prohibited.")
    deduped: list[str] = []
    for a in actions:
        if a not in deduped:
            deduped.append(a)
    return deduped[:5]


def build_from_db(db_path: Path | None = None) -> dict[str, Any]:
    """Load staged rows read-only, then build the review queue."""
    rows = _staging.load_staging_rows(db_path)
    return build_review_queue(rows)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="paper_outcome_review_queue.py",
        description=(
            "Show what the operator must fix before staged paper outcomes "
            "become calibration-grade. Read-only; advisory-only; no writes; "
            "real-money sizing PROHIBITED."
        ),
    )
    p.add_argument("--db-path", default=None, help="canonical DB path override")
    p.add_argument("--json", action="store_true", help="print the JSON report")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else None
    report = build_from_db(db_path)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("paper_outcome_review_queue")
        print(f"  staged           : {report['staged_outcomes_count']}")
        print(f"  calibration_ready: {report['calibration_ready_count']}")
        print(f"  review_required  : {report['review_required_count']}")
        print(f"  rejected         : {report['rejected_count']}")
        print("  top blockers     :")
        for entry in report["top_blockers"]:
            print(f"    - {entry['blocker']}: {entry['count']}")
        print("  next actions     :")
        for action in report["next_5_operator_actions"]:
            print(f"    - {action}")
        print(f"  real-money       : {report['real_money_sizing_impact']}")
    return 0


__all__ = [
    "BLOCKER_KEYS",
    "row_blockers",
    "build_review_queue",
    "build_from_db",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
