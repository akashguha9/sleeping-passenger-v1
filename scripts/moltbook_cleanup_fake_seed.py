"""
Narrow, idempotent cleanup of fake/demo Moltbook seed rows.

Background
----------
runtime/mvp_local.db was polluted with thousands of fake/demo Moltbook
entries (FABRIC_SPY / FABRIC_QQQ event_ids, "Persistence above 0.8" theses,
and a residual batch of synthetic SPY "Thesis A" rows).  The write path that
allowed this has been closed (see scripts/moltbook_api.py sentinel guard and
scripts/persistence.py lazy DB_PATH resolution + conftest runtime-DB
isolation).  This script removes the *residual* fake SPY rows that may still
exist, using a deliberately narrow signature so it can never touch a real
user-linked learning entry.

Deletion signature (ALL must match; case-sensitive equality)
------------------------------------------------------------
    ticker                  = 'SPY'
    original_signal_thesis  = 'Thesis A'
    ai_interpretation       = 'Advisory context'
    user_reflection         = 'I paused'
    final_human_decision    = 'No trade'
    lesson_learned          = 'Correct choice under uncertainty'
    manual_trade_log_id     IS NULL or ''   (never linked to a real trade)

Any row with a non-blank manual_trade_log_id, a different ticker, or any
field that differs is left untouched.

Safety
------
- Read-only by default (dry-run).  Pass --apply to actually delete.
- Never deletes broker state, never executes trades.
- Does NOT modify or delete the backup DB
  (runtime/mvp_local.before_moltbook_cleanup.db).
- Idempotent: running twice removes the same zero-or-N rows; a second run
  reports 0 removed.

Usage
-----
    python scripts/moltbook_cleanup_fake_seed.py            # dry-run report
    python scripts/moltbook_cleanup_fake_seed.py --apply    # delete matches
    python scripts/moltbook_cleanup_fake_seed.py --json
    python scripts/moltbook_cleanup_fake_seed.py --db-path runtime/mvp_local.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

# The exact synthetic-row signature.  Kept as data (not inlined) so the test
# suite can import and assert it never widens.
FAKE_SPY_SIGNATURE: dict[str, str] = {
    "ticker": "SPY",
    "original_signal_thesis": "Thesis A",
    "ai_interpretation": "Advisory context",
    "user_reflection": "I paused",
    "final_human_decision": "No trade",
    "lesson_learned": "Correct choice under uncertainty",
}

_WHERE_CLAUSE = (
    " WHERE ticker = :ticker"
    " AND original_signal_thesis = :original_signal_thesis"
    " AND ai_interpretation = :ai_interpretation"
    " AND user_reflection = :user_reflection"
    " AND final_human_decision = :final_human_decision"
    " AND lesson_learned = :lesson_learned"
    " AND COALESCE(NULLIF(TRIM(manual_trade_log_id), ''), '') = ''"
)


def _default_db_path() -> Path:
    try:
        try:
            from scripts.persistence import DB_PATH  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            from persistence import DB_PATH  # type: ignore[no-redef]
        return Path(DB_PATH)
    except Exception:
        return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


def find_fake_seed_rows(db_path: Path) -> list[dict[str, Any]]:
    """Return the rows matching the fake-seed signature (read-only)."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        try:
            rows = conn.execute(
                "SELECT entry_id, event_id, ticker, manual_trade_log_id"
                " FROM moltbook_entries" + _WHERE_CLAUSE,
                FAKE_SPY_SIGNATURE,
            ).fetchall()
        except sqlite3.Error:
            return []
        return [dict(r) for r in rows]
    finally:
        conn.close()


def cleanup(db_path: Path, *, apply: bool) -> dict[str, Any]:
    """Find (and optionally delete) the fake SPY seed rows.

    Returns a structured report; ``removed`` is 0 unless ``apply`` is True.
    """
    matches = find_fake_seed_rows(db_path)
    removed = 0
    if apply and matches:
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.execute(
                "DELETE FROM moltbook_entries" + _WHERE_CLAUSE,
                FAKE_SPY_SIGNATURE,
            )
            removed = cur.rowcount or 0
            conn.commit()
        finally:
            conn.close()
    return {
        "operation": "moltbook_cleanup_fake_seed",
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "applied": bool(apply),
        "matched": len(matches),
        "removed": removed,
        "matched_entry_ids": [m.get("entry_id") for m in matches],
        "signature": FAKE_SPY_SIGNATURE,
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_review_required": True,
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="moltbook_cleanup_fake_seed.py",
        description="Narrowly remove fake SPY 'Thesis A' Moltbook seed rows.",
    )
    p.add_argument("--db-path", type=str, default=None,
                   help="Path to runtime/mvp_local.db (default: persistence module).")
    p.add_argument("--apply", action="store_true",
                   help="Actually delete matches (default: dry-run report only).")
    p.add_argument("--dry-run", action="store_true",
                   help="Explicit dry-run (default behaviour); writes a "
                        "permission dry-run receipt. Read-only.")
    p.add_argument("--operator-role", default=None,
                   help="VIEWER|OPERATOR|ADMIN (default: MVP_OPERATOR_ROLE env). "
                        "--apply requires ADMIN.")
    p.add_argument("--json", action="store_true", help="Emit JSON.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    # Destructive cleanup is an ADMIN-only write-like action; the dry-run
    # report is read-only.  Fail closed for unauthorized roles.
    if args.apply:
        # Authority for the *role* requirement remains the established
        # operator_auth enforcement boundary (cleanup_scripts → ADMIN); the
        # central operator_permission_guard then verifies the advisory safety
        # invariants + DB-path safety and writes the unified audit event.  Both
        # must pass — the more restrictive (ADMIN) wins.
        try:
            try:
                from scripts.operator_audit_log import enforce as _enforce
            except ModuleNotFoundError:  # pragma: no cover - script-style fallback
                from operator_audit_log import enforce as _enforce  # type: ignore[no-redef]
            _enforce("cleanup_scripts", role=args.operator_role,
                     resource="moltbook_entries.fake_seed")
        except PermissionError as exc:
            print(f"[DENY] {exc}")
            return 2
        try:
            try:
                from scripts import operator_permission_guard as _guard
            except ModuleNotFoundError:  # pragma: no cover - script-style fallback
                import operator_permission_guard as _guard  # type: ignore[no-redef]
            role = (_guard.OperatorRole(_guard._auth.normalize_role(args.operator_role))
                    if args.operator_role else _guard.load_operator_role_from_env())
            _guard.require_permission_or_exit(_guard.PermissionRequest(
                operation_name="moltbook_cleanup_fake_seed",
                operation_class=_guard.OperationClass.REPAIR_WRITE,
                operator_role=role,
                apply_requested=True,
                dry_run_completed=_guard.validate_dry_run_receipt(
                    "moltbook_cleanup_fake_seed", str(db_path)),
                db_path=str(db_path),
                safety_stamps=_guard.caller_safety_stamps(),
                # Idempotent narrow-signature delete; default mode is the
                # read-only dry-run report.  No separate receipt is mandated.
                reason=f"{_guard.NO_DRY_RUN_NEEDED}: idempotent narrow-signature "
                       "fake-seed delete; default mode is dry-run.",
            ))
        except PermissionError as exc:
            print(f"[DENY] {exc}")
            return 2
    report = cleanup(db_path, apply=args.apply)
    if not args.apply:
        # Dry-run is read-only and open to any role; record a receipt so a
        # later --apply (by an authorized ADMIN) can prove a dry-run happened.
        try:
            try:
                from scripts import operator_permission_guard as _guard
            except ModuleNotFoundError:  # pragma: no cover - script-style fallback
                import operator_permission_guard as _guard  # type: ignore[no-redef]
            _guard.write_dry_run_receipt(
                "moltbook_cleanup_fake_seed",
                target_count=report["matched"], db_path=str(db_path))
        except Exception:  # pragma: no cover - receipt is best-effort, never blocks
            pass
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        mode = "APPLIED" if report["applied"] else "DRY-RUN"
        print(f"Moltbook fake-seed cleanup [{mode}]")
        print(f"  db_path : {report['db_path']}")
        print(f"  matched : {report['matched']}")
        print(f"  removed : {report['removed']}")
        if report["matched_entry_ids"]:
            print(f"  entry_ids: {report['matched_entry_ids']}")
        if not report["applied"] and report["matched"]:
            print("  (dry-run — re-run with --apply to delete)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
