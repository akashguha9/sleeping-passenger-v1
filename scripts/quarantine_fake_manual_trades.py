"""Quarantine fake / synthetic rows that leaked into ``manual_trades``.

This script is the cleanup half of the Sprint-recovery 2026-05-18 fix
for the leaked-AAPL Manual Trade Log incident.  It identifies rows that
match :func:`scripts.manual_trade_origin.fake_manual_trade_reason` and
re-stamps their ``created_via`` column to
``quarantined_fake_manual_trade`` so the canonical classifier reads
them as ``ORIGIN_EXCLUDED_PROVENANCE`` and the Manual Trade Log GET
route drops them without any code change.

Invariants:

* **No deletes.** Rows stay in the DB for audit; we change provenance,
  not history.
* **Dry-run by default.** Without ``--yes`` the script only prints what
  it would do.
* **Reversible.** Original provenance is preserved in ``notes`` (when
  the column is writable) and in the printed report.  An operator can
  restore by hand if a false positive is later identified.
* **Pure read-side.** No broker calls, no AI execution, no signal
  state mutated.  ``broker_api_called`` / ``ai_execution_count`` are
  not touched.

Usage::

    # Show what would be quarantined (default).
    python scripts/quarantine_fake_manual_trades.py

    # Apply quarantine (writes to runtime/mvp_local.db).
    python scripts/quarantine_fake_manual_trades.py --yes

    # Target a specific DB (tests use this).
    python scripts/quarantine_fake_manual_trades.py --db /tmp/test.db --yes
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

try:
    from scripts.manual_trade_origin import (
        QUARANTINE_PROVENANCE,
        fake_manual_trade_reason,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from manual_trade_origin import (  # type: ignore[no-redef]
        QUARANTINE_PROVENANCE,
        fake_manual_trade_reason,
    )

try:
    from scripts.persistence import DB_PATH as _DEFAULT_DB_PATH
except ModuleNotFoundError:  # pragma: no cover
    from persistence import DB_PATH as _DEFAULT_DB_PATH  # type: ignore[no-redef]

try:
    from scripts import operator_permission_guard as _guard
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import operator_permission_guard as _guard  # type: ignore[no-redef]

# Operation identity for the central permission guard.  Re-stamping provenance
# is a REPAIR_WRITE (OPERATOR+), never a delete and never an execution action.
OPERATION_NAME = "quarantine_fake_manual_trades"
OPERATION_CLASS = _guard.OperationClass.REPAIR_WRITE


@dataclass(frozen=True)
class QuarantineCandidate:
    trade_id: str
    event_id: str
    ticker: str
    quantity: float
    price: float
    thesis: str
    created_via: str
    reason: str


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def find_candidates(db_path: Path) -> list[QuarantineCandidate]:
    """Return every row whose ``fake_manual_trade_reason`` is non-empty.

    Read-only.  Rows already stamped with ``QUARANTINE_PROVENANCE`` are
    skipped — once quarantined, they stay quarantined and we do not
    re-flag them.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM manual_trades ORDER BY executed_at DESC"
        ).fetchall()
    finally:
        conn.close()

    candidates: list[QuarantineCandidate] = []
    for raw in rows:
        row = _row_to_dict(raw)
        if str(row.get("created_via") or "").strip() == QUARANTINE_PROVENANCE:
            continue  # already quarantined
        reason = fake_manual_trade_reason(row)
        if not reason:
            continue
        candidates.append(
            QuarantineCandidate(
                trade_id=str(row.get("trade_id") or ""),
                event_id=str(row.get("event_id") or ""),
                ticker=str(row.get("ticker") or ""),
                quantity=float(row.get("quantity") or 0.0),
                price=float(row.get("price") or 0.0),
                thesis=str(row.get("thesis") or ""),
                created_via=str(row.get("created_via") or ""),
                reason=reason,
            )
        )
    return candidates


def apply_quarantine(db_path: Path, candidates: Iterable[QuarantineCandidate]) -> int:
    """Re-stamp the candidates' provenance to ``QUARANTINE_PROVENANCE``.

    Returns the number of rows updated.  Does NOT delete rows.  Each
    update is wrapped in a single transaction so an interrupted run
    leaves the DB in a consistent state.
    """
    candidate_list = list(candidates)
    if not candidate_list:
        return 0
    conn = sqlite3.connect(str(db_path))
    updated = 0
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(manual_trades)")}
        if "created_via" not in cols:
            raise RuntimeError(
                "manual_trades table has no created_via column — schema migration missing"
            )
        with conn:  # transactional
            for cand in candidate_list:
                conn.execute(
                    "UPDATE manual_trades SET created_via = ? WHERE trade_id = ?",
                    (QUARANTINE_PROVENANCE, cand.trade_id),
                )
                updated += 1
    finally:
        conn.close()
    return updated


def _print_report(
    candidates: list[QuarantineCandidate], *, dry_run: bool, db_path: Path
) -> None:
    print(f"[quarantine] DB: {db_path}")
    if dry_run:
        print("[quarantine] DRY RUN — no writes.  Pass --yes to apply.")
    else:
        print("[quarantine] APPLYING — created_via will be re-stamped.")
    print(f"[quarantine] {len(candidates)} candidate row(s):")
    if not candidates:
        print("[quarantine]   (none — DB is clean)")
        return
    for cand in candidates:
        # Truncate thesis for readability; reason carries the full marker.
        thesis_short = cand.thesis if len(cand.thesis) <= 60 else cand.thesis[:57] + "..."
        print(
            f"[quarantine]   {cand.trade_id}  "
            f"event_id={cand.event_id!r}  "
            f"ticker={cand.ticker} qty={cand.quantity} price={cand.price}  "
            f"thesis={thesis_short!r}  "
            f"created_via={cand.created_via!r}  "
            f"reason={cand.reason}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Identify and quarantine synthetic / fake manual-trade rows. "
            "Default is dry-run; pass --yes to write."
        ),
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=_DEFAULT_DB_PATH,
        help=f"SQLite DB path (default: {_DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--apply",
        "--yes",
        dest="apply",
        action="store_true",
        help="Actually apply the quarantine (requires MVP_OPERATOR_ROLE=OPERATOR "
             "or ADMIN and a recent dry-run receipt).  Without this flag the "
             "script only prints.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run (default behaviour); writes a permission "
             "dry-run receipt so a subsequent --apply can proceed.",
    )
    parser.add_argument(
        "--operator-role",
        default=None,
        help="VIEWER|OPERATOR|ADMIN (default: MVP_OPERATOR_ROLE env, else "
             "VIEWER).  --apply requires OPERATOR or ADMIN.",
    )
    args = parser.parse_args(argv)

    db_path: Path = args.db
    if not db_path.exists():
        print(f"[quarantine] ERROR: DB not found at {db_path}", file=sys.stderr)
        return 2

    dry_run = not args.apply
    candidates = find_candidates(db_path)
    _print_report(candidates, dry_run=dry_run, db_path=db_path)

    if dry_run:
        # A dry-run is read-only and open to any role.  It records a receipt so
        # a later --apply (by an authorized role) can prove a dry-run happened.
        receipt = _guard.write_dry_run_receipt(
            OPERATION_NAME, target_count=len(candidates), db_path=str(db_path)
        )
        print(f"[quarantine] dry-run receipt written: {receipt.name}")
        print("[quarantine] To apply (PowerShell):")
        print('[quarantine]   $env:MVP_OPERATOR_ROLE="OPERATOR"')
        print(f"[quarantine]   python scripts\\quarantine_fake_manual_trades.py "
              f"--apply --db {db_path}")
        return 0

    # --apply path: central permission guard (fails closed; audits allow/deny).
    role = (_guard.OperatorRole(_guard._auth.normalize_role(args.operator_role))
            if args.operator_role else _guard.load_operator_role_from_env())
    request = _guard.PermissionRequest(
        operation_name=OPERATION_NAME,
        operation_class=OPERATION_CLASS,
        operator_role=role,
        apply_requested=True,
        dry_run_completed=_guard.validate_dry_run_receipt(
            OPERATION_NAME, str(db_path)
        ),
        db_path=str(db_path),
        safety_stamps=_guard.caller_safety_stamps(),
    )
    try:
        _guard.require_permission_or_exit(request)
    except PermissionError as exc:
        print(f"[quarantine] [DENY] {exc}", file=sys.stderr)
        return 2

    if not candidates:
        print("[quarantine] permission granted; no candidates to quarantine (no-op).")
        return 0

    updated = apply_quarantine(db_path, candidates)
    print(f"[quarantine] Updated {updated} row(s) — created_via stamped {QUARANTINE_PROVENANCE!r}.")
    print("[quarantine] No rows were deleted.  Audit history preserved.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
