"""Real-Forward Outcome Maturation Sprint — Phase 1: due-snapshot maturity scanner.

Kanté work: this module never scores, never attaches an outcome, never moves a
horizon, and never claims calibration.  It is a *read-only* scanner that tells
the operator — honestly — which forward-eligible decision snapshots can have a
real outcome attached *today*, which are still waiting for their horizon to
close, which are already attached, and exactly when the next horizon becomes
due.

For each snapshot ``i`` the maturity classification is a partition::

    HorizonElapsed_i(now) = I(now_utc >= decision_ts_i + horizon_days_i·24h)

    ForwardOutcomeEligible_i = the persisted forward-contract eligibility flag
        (ticker valid · p valid · horizon>0 · price-based target ·
         entry_price>0 · entry_ts<=decision_ts · gate LOCKED)

    DueForward_i     = ForwardOutcomeEligible_i · HorizonElapsed_i(now)
    PendingForward_i = ForwardOutcomeEligible_i · (1 - HorizonElapsed_i(now))
    AlreadyAttached_i = I(y_i in {0,1}) · I(is_real_outcome_i) · I(kind_i == real_forward)

    state_i =
        "ATTACHED"        if AlreadyAttached_i = 1
        "DUE_FORWARD"     if DueForward_i = 1 and AlreadyAttached_i = 0
        "PENDING_HORIZON" if PendingForward_i = 1 and AlreadyAttached_i = 0
        "INELIGIBLE"      if ForwardOutcomeEligible_i = 0

It mutates nothing.  ``predictive_claim_allowed`` is always ``False`` here — a
maturity scan can never unlock a claim.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Sequence

try:  # package layout
    from scripts import persistence
    from scripts.decision_probability_snapshot import TABLE, ensure_forward_columns
    from scripts.attach_due_outcomes import horizon_elapsed, _parse_iso
    from scripts.forward_snapshot_contract import horizon_close_utc
    from scripts.outcome_labeling_flow import REAL_FORWARD, _ensure_outcome_columns
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    import persistence  # type: ignore[no-redef]
    from decision_probability_snapshot import TABLE, ensure_forward_columns  # type: ignore[no-redef]
    from attach_due_outcomes import horizon_elapsed, _parse_iso  # type: ignore[no-redef]
    from forward_snapshot_contract import horizon_close_utc  # type: ignore[no-redef]
    from outcome_labeling_flow import REAL_FORWARD, _ensure_outcome_columns  # type: ignore[no-redef]

STATE_ATTACHED = "ATTACHED"
STATE_DUE_FORWARD = "DUE_FORWARD"
STATE_PENDING_HORIZON = "PENDING_HORIZON"
STATE_INELIGIBLE = "INELIGIBLE"

_ADVISORY = {
    "advisory_status": "ADVISORY_ONLY",
    "human_execution_required": True,
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
    "predictive_claim_allowed": False,
}


def _utc_now_iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid_p(p: Any) -> bool:
    try:
        pf = float(p)
    except (TypeError, ValueError):
        return False
    return 0.0 <= pf <= 1.0


def _resolve_now(now_utc: str | None) -> datetime:
    return _parse_iso(now_utc) or datetime.now(timezone.utc)


def _row_horizon_close(row: dict[str, Any]) -> str | None:
    """Persisted ``horizon_close_utc`` if present, else recompute it honestly."""
    close = row.get("horizon_close_utc")
    if close:
        return str(close)
    return horizon_close_utc(row.get("timestamp_utc"), row.get("prediction_horizon_days"))


def classify_snapshot(row: dict[str, Any], now: datetime) -> str:
    """Return the maturity state for one persisted snapshot row."""
    y = row.get("outcome_label")
    is_real = bool(row.get("is_real_outcome"))
    kind = row.get("outcome_kind")
    if y in (0, 1) and is_real and kind == REAL_FORWARD:
        return STATE_ATTACHED

    eligible = int(row.get("forward_outcome_eligible") or 0) == 1
    if not eligible:
        return STATE_INELIGIBLE

    elapsed = horizon_elapsed(
        decision_ts=row.get("timestamp_utc"),
        horizon_days=row.get("prediction_horizon_days"),
        now_utc=now,
    )
    return STATE_DUE_FORWARD if elapsed else STATE_PENDING_HORIZON


def _load_rows(db_path: Any) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        ensure_forward_columns(conn)
        _ensure_outcome_columns(conn)
        rows = conn.execute(
            f"SELECT snapshot_id, timestamp_utc, prediction_horizon_days,"
            f" model_probability, horizon_close_utc, forward_outcome_eligible,"
            f" forward_outcome_unavailable_reason, outcome_label, is_real_outcome,"
            f" outcome_kind FROM {TABLE}"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def scan_forward_outcome_maturity(
    *,
    db_path: Any = None,
    now_utc: str | None = None,
    rows: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Scan persisted decision snapshots and classify their maturity (read-only).

    ``rows`` lets tests inject an explicit snapshot list; otherwise the live
    ``decision_probability_snapshots`` table is read.  Nothing is mutated.
    """
    now = _resolve_now(now_utc)
    target = db_path if db_path is not None else persistence.DB_PATH
    snap_rows = list(rows) if rows is not None else _load_rows(target)

    n_valid_p = 0
    n_forward_eligible = 0
    n_pending_horizon = 0
    n_due_forward = 0
    n_attached_real_forward = 0
    n_ineligible = 0
    due_snapshot_ids: list[str] = []
    pending_by_date: dict[str, int] = {}
    ineligible_reasons: dict[str, int] = {}
    # Horizon-close timestamps for not-yet-attached eligible snapshots — these are
    # the ones whose maturity we are waiting on.
    open_closes: list[datetime] = []
    earliest_close: datetime | None = None

    for row in snap_rows:
        if _valid_p(row.get("model_probability")):
            n_valid_p += 1
        state = classify_snapshot(row, now)
        if state == STATE_ATTACHED:
            n_attached_real_forward += 1
            continue
        if state == STATE_INELIGIBLE:
            n_ineligible += 1
            reason = row.get("forward_outcome_unavailable_reason") or "UNSPECIFIED"
            ineligible_reasons[reason] = ineligible_reasons.get(reason, 0) + 1
            continue

        # Eligible + not attached -> it counts toward the open maturity window.
        n_forward_eligible += 1
        close_str = _row_horizon_close(row)
        close_dt = _parse_iso(close_str)
        if close_dt is not None:
            open_closes.append(close_dt)
            if earliest_close is None or close_dt < earliest_close:
                earliest_close = close_dt

        if state == STATE_DUE_FORWARD:
            n_due_forward += 1
            sid = row.get("snapshot_id")
            if sid is not None:
                due_snapshot_ids.append(str(sid))
        else:  # PENDING_HORIZON
            n_pending_horizon += 1
            date_key = (close_str or "UNKNOWN")[:10]
            pending_by_date[date_key] = pending_by_date.get(date_key, 0) + 1

    # next_due_in_hours: 0.0 if anything is already due; otherwise the hours
    # until the earliest *future* horizon close.  None when nothing is open.
    next_due_in_hours: float | None
    if n_due_forward > 0:
        next_due_in_hours = 0.0
    else:
        future = sorted(c for c in open_closes if c > now)
        if future:
            next_due_in_hours = round((future[0] - now).total_seconds() / 3600.0, 4)
        else:
            next_due_in_hours = None

    out: dict[str, Any] = {
        "generated_at_utc": _utc_now_iso(now),
        "n_valid_p": n_valid_p,
        "n_forward_eligible": n_forward_eligible,
        "n_pending_horizon": n_pending_horizon,
        "n_due_forward": n_due_forward,
        "n_attached_real_forward": n_attached_real_forward,
        "n_ineligible": n_ineligible,
        "earliest_horizon_close_utc": (
            _utc_now_iso(earliest_close) if earliest_close is not None else None
        ),
        "next_due_in_hours": next_due_in_hours,
        "due_snapshot_ids": due_snapshot_ids,
        "pending_by_date": pending_by_date,
        "ineligible_reasons": ineligible_reasons,
        "n_real_forward_pairs": n_attached_real_forward,
        "n_needed_to_200": max(0, 200 - n_attached_real_forward),
        "can_attach_today": n_due_forward > 0,
    }
    out.update(_ADVISORY)
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Scan forward-eligible snapshots by maturity state (read-only, advisory-only)."
    )
    p.add_argument("--now", default=None, help="override 'now' (ISO UTC) for the scan")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    persistence.init_schema()
    out = scan_forward_outcome_maturity(now_utc=args.now)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))


__all__ = [
    "STATE_ATTACHED",
    "STATE_DUE_FORWARD",
    "STATE_PENDING_HORIZON",
    "STATE_INELIGIBLE",
    "classify_snapshot",
    "scan_forward_outcome_maturity",
    "main",
]
