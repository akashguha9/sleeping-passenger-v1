"""
Quarantine bad Kalshi records in the canonical ``signal_events`` table.

Dry-run by default.  Walks every Kalshi row in ``runtime/mvp_local.db``
and re-applies the current governance + title rules.  Anything that
would now be quarantined (out-of-scope category, raw outcome-leak title,
KXMVESPORTS-style ticker) is reported.

Use ``--yes`` (alias ``--apply``) to actually rewrite the raw_payload
with ``visible_in_kalshi_feed=false`` and ``quarantine_reason`` set.
The action stamps provenance; it does **not** delete rows, so the audit
trail survives.

Safety
------
- Routed through :mod:`scripts.operator_permission_guard`.  The DB write
  boundary is wrapped in
  :func:`operator_permission_guard.guarded_mutation_context` (REPAIR_WRITE,
  OPERATOR+ floor) so a direct importer that calls the write helper without
  a guard-validated :class:`PermissionDecision` still cannot mutate.
- Dry-run by default; ``--yes`` requires a recent dry-run receipt and
  ``MVP_OPERATOR_ROLE=OPERATOR`` (or ``ADMIN``).
- Never calls a broker API.  Never touches execution state.  Never places
  an order.  Emitted audit rows carry the canonical advisory-only safety
  stamps (advisory_only, human_review_required, execution_locked,
  broker_api_called=false, ai_execution_count=0).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.kalshi_category_governance import normalize_kalshi_category
    from scripts.kalshi_normalizer import (
        build_kalshi_quarantine_record,
        normalize_kalshi_title,
    )
    from scripts.runtime_common import REPO_ROOT, utc_timestamp
except ModuleNotFoundError:  # pragma: no cover
    from kalshi_category_governance import normalize_kalshi_category  # type: ignore[no-redef]
    from kalshi_normalizer import (  # type: ignore[no-redef]
        build_kalshi_quarantine_record,
        normalize_kalshi_title,
    )
    from runtime_common import REPO_ROOT, utc_timestamp  # type: ignore[no-redef]

try:
    from scripts import operator_permission_guard as _guard
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import operator_permission_guard as _guard  # type: ignore[no-redef]


DEFAULT_DB = REPO_ROOT / "runtime" / "mvp_local.db"
DEFAULT_AUDIT = REPO_ROOT / "runtime" / "release" / "kalshi_quarantine_migration.jsonl"

# Operation identity for the central permission guard.  Re-stamping a payload's
# ``visible_in_kalshi_feed`` is a REPAIR_WRITE (OPERATOR+); never a delete and
# never an execution action.
OPERATION_NAME = "quarantine_bad_kalshi_records"
OPERATION_CLASS = _guard.OperationClass.REPAIR_WRITE


def _decide_for(payload: dict[str, Any]) -> tuple[bool, str]:
    """Return ``(should_quarantine, reason)`` for a persisted Kalshi payload.

    Re-applies the governance + title rules so older rows that pre-date
    the hardening get re-evaluated against the current allowlist.
    """
    decision = normalize_kalshi_category(
        payload.get("category") or payload.get("category_raw"),
        ticker=payload.get("source_market_id") or payload.get("ticker"),
    )
    if not decision["category_allowed"]:
        return True, decision["quarantine_reason"]
    title_decision = normalize_kalshi_title(
        {
            "title": payload.get("raw_title") or payload.get("title"),
            "ticker": payload.get("source_market_id"),
        }
    )
    if any("yes_outcome_leak" in w for w in title_decision["title_warnings"]):
        return True, "title_outcome_leak"
    return False, ""


def _iter_kalshi_rows(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT id, event_id, raw_payload FROM signal_events WHERE source_name = ?",
            ("kalshi",),
        )
        for row in cursor:
            try:
                payload = json.loads(row["raw_payload"])
            except (TypeError, ValueError):
                payload = {}
            yield row["id"], row["event_id"], payload
    finally:
        conn.close()


def _mark_quarantined(
    db_path: Path,
    row_id: int,
    payload: dict[str, Any],
    reason: str,
    *,
    permission_decision: "_guard.PermissionDecision | None" = None,
) -> None:
    """Re-stamp the row's payload so the canonical feed drops it.

    Function-level guard: the write is wrapped in
    :func:`operator_permission_guard.guarded_mutation_context` (REPAIR_WRITE,
    OPERATOR+ floor, require_dry_run=True).  A direct importer that calls this
    function without a guard-validated :class:`PermissionDecision` hits the
    context manager's ``__enter__`` and raises :class:`PermissionError` before
    the UPDATE runs.  Read-only callers must not use this function.
    """
    with _guard.guarded_mutation_context(
        permission_decision,
        operation_name=OPERATION_NAME,
        operation_class=OPERATION_CLASS,
        expected_role_floor=_guard.OperatorRole.OPERATOR,
        require_dry_run=True,
    ):
        payload["visible_in_kalshi_feed"] = False
        payload["category_allowed"] = False
        payload["quarantine_reason"] = reason
        payload.setdefault("quarantine_migration_at_utc", utc_timestamp())
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "UPDATE signal_events SET raw_payload = ? WHERE id = ?",
                (json.dumps(payload), row_id),
            )
            conn.commit()
        finally:
            conn.close()


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Quarantine bad Kalshi records.  Dry-run by default.  Re-applies "
            "the current category governance + title rules to every persisted "
            "Kalshi row.  Routed through operator_permission_guard "
            "(REPAIR_WRITE, OPERATOR+).  Never touches broker/execution state."
        )
    )
    parser.add_argument("--db-path", default=str(DEFAULT_DB))
    parser.add_argument(
        "--audit-path",
        default=str(DEFAULT_AUDIT),
        help="Where to append per-row audit JSONL (created if missing).",
    )
    parser.add_argument(
        "--yes",
        "--apply",
        dest="apply",
        action="store_true",
        help=(
            "Actually mark the rows as quarantined (requires "
            "MVP_OPERATOR_ROLE=OPERATOR or ADMIN and a recent dry-run "
            "receipt).  Without this flag the script only prints."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Explicit dry-run (default behaviour); writes a permission "
            "dry-run receipt so a subsequent --yes can proceed."
        ),
    )
    parser.add_argument(
        "--operator-role",
        default=None,
        help=(
            "VIEWER|OPERATOR|ADMIN (default: MVP_OPERATOR_ROLE env, else "
            "VIEWER).  --yes requires OPERATOR or ADMIN."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap the number of rows examined (0 = no cap).",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    audit_path = Path(args.audit_path)
    if not db_path.exists():
        print(f"db not found: {db_path}", file=sys.stderr)
        return 1

    # First pass: enumerate candidates (read-only).  We do this before the
    # permission guard so the dry-run receipt can record an accurate target
    # count and so DENY exits without writing to the audit log at all.
    candidates: list[tuple[int, str, dict[str, Any], str]] = []
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    for row_id, event_id, payload in _iter_kalshi_rows(db_path):
        total += 1
        if args.limit and total > args.limit:
            break
        should_quarantine, reason = _decide_for(payload)
        if should_quarantine:
            candidates.append((row_id, event_id, payload, reason))

    # If --yes (alias --apply) is requested, acquire a guard-validated decision
    # BEFORE we open the audit JSONL or touch any row.  CLI request/role/receipt
    # boilerplate is collapsed into build_apply_decision (Kanté Task B).
    decision = None
    if args.apply:
        try:
            decision = _guard.build_apply_decision(
                OPERATION_NAME,
                OPERATION_CLASS,
                str(db_path),
                operator_role=args.operator_role,
            )
        except PermissionError as exc:
            print(f"[DENY] {exc}", file=sys.stderr)
            return 2

    flagged = 0
    rewrote = 0
    audit_handle = audit_path.open("a", encoding="utf-8")
    try:
        for row_id, event_id, payload, reason in candidates:
            flagged += 1
            audit_row = build_kalshi_quarantine_record(
                payload,
                decision={"quarantine_reason": reason},
                fetched_at_utc=utc_timestamp(),
                extra={"event_id": event_id, "db_row_id": row_id},
            )
            audit_handle.write(json.dumps(audit_row) + "\n")
            if args.apply:
                _mark_quarantined(
                    db_path, row_id, payload, reason,
                    permission_decision=decision,
                )
                rewrote += 1
                action = "MARKED"
            else:
                action = "DRY_RUN"
            print(
                f"[{action}] id={row_id} event_id={event_id} reason={reason} "
                f"category={payload.get('category')} title={(payload.get('title') or '')[:80]!r}"
            )
    finally:
        audit_handle.close()

    if not args.apply:
        # Dry-run is read-only and open to any role; record a receipt so a
        # later --yes (by an authorized OPERATOR+) can prove a dry-run happened.
        try:
            _guard.write_dry_run_receipt(
                OPERATION_NAME, target_count=flagged, db_path=str(db_path),
            )
        except Exception:  # pragma: no cover - receipt is best-effort, never blocks
            pass

    print(
        f"\nKalshi quarantine summary: scanned={total} flagged={flagged} "
        f"rewrote={rewrote} dry_run={not args.apply}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(run())
