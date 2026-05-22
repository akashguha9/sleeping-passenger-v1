"""Guarded, additive application of cockpit hot-path indexes (Kanté Task 2).

The companion :mod:`scripts.cockpit_hot_path_query_audit` *recommends* indexes
for unindexed cockpit/diagnostics hot paths but never creates them.  This script
is the separate, guarded path that applies them — and only them.

Hard safety rules
-----------------
* **Dry-run by default.**  ``--apply`` is required to write.
* **ADMIN + MIGRATION_WRITE only.**  Index creation is schema migration; it
  routes through :mod:`scripts.operator_permission_guard` which (a) requires the
  ADMIN role and a recent dry-run receipt, (b) re-checks the locked advisory
  invariants, (c) writes a unified audit event, and (d) is re-asserted at the
  write function via :func:`assert_permission_decision_allowed`.
* **Additive only.**  Emits ``CREATE INDEX IF NOT EXISTS`` exclusively, and only
  for an index whose table + columns *already exist*.  It never drops an index,
  never deletes a row, never issues UPDATE/DELETE/INSERT.
* No broker call, no execution.  The index set is sourced from the audit's
  existing-columns-only recommendations, so a column that does not exist can
  never be referenced.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

try:
    from scripts import cockpit_hot_path_query_audit as _audit
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import cockpit_hot_path_query_audit as _audit  # type: ignore[no-redef]

try:
    from scripts import operator_permission_guard as _guard
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import operator_permission_guard as _guard  # type: ignore[no-redef]

try:
    from scripts import runtime_config as _runtime_config
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import runtime_config as _runtime_config  # type: ignore[no-redef]

OPERATION_NAME = "apply_cockpit_hot_path_indexes"
OPERATION_CLASS = _guard.OperationClass.MIGRATION_WRITE

# A safe statement: additive CREATE INDEX IF NOT EXISTS, single statement.
_SAFE_STMT_RE = re.compile(
    r"^\s*CREATE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+\w+\s+ON\s+\w+\s*\([^;()]+\)\s*;?\s*$",
    re.IGNORECASE,
)
_FORBIDDEN_TOKENS = ("DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "REPLACE",
                     "ATTACH", "PRAGMA", "TRIGGER")


def _resolve_db_path(db_path: Path | None) -> Path:
    if db_path is not None:
        return Path(db_path)
    return _runtime_config.get_db_path()


def _is_safe_create_index(stmt: str) -> bool:
    upper = stmt.upper()
    if any(tok in upper for tok in _FORBIDDEN_TOKENS):
        return False
    return bool(_SAFE_STMT_RE.match(stmt))


def planned_indexes(db_path: Path | None = None) -> list[str]:
    """The audit's existing-columns-only CREATE INDEX recommendations, validated."""
    report = _audit.audit_hot_paths(db_path)
    stmts = [s for s in report.get("index_recommendations", [])
             if _is_safe_create_index(s)]
    return stmts


@_guard.guarded_mutation(
    operation_name=OPERATION_NAME,
    operation_class=OPERATION_CLASS,
    expected_role_floor=_guard.OperatorRole.ADMIN,
    require_dry_run=True,
)
def apply_indexes(
    db_path: Path,
    statements: list[str],
    *,
    permission_decision: "_guard.PermissionDecision | None" = None,
) -> dict[str, Any]:
    """Execute the additive CREATE INDEX statements (function-level guarded).

    The :func:`operator_permission_guard.guarded_mutation` decorator (Kanté Task
    B) re-asserts the guard at the write boundary so a direct importer cannot
    bypass the ADMIN + MIGRATION_WRITE requirement.  Refuses any statement that
    is not an additive ``CREATE INDEX IF NOT EXISTS``.
    """
    created: list[str] = []
    refused: list[str] = []
    conn = sqlite3.connect(str(db_path))
    try:
        for stmt in statements:
            if not _is_safe_create_index(stmt):
                refused.append(stmt)
                continue
            conn.execute(stmt)
            created.append(stmt)
        conn.commit()
    finally:
        conn.close()
    return {"created": created, "refused": refused}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="apply_cockpit_hot_path_indexes.py",
        description=(
            "Apply (additive only) the cockpit hot-path index recommendations. "
            "Dry-run by default; --apply requires ADMIN + a dry-run receipt. "
            "CREATE INDEX IF NOT EXISTS only; never drops/deletes; no broker call."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument("--apply", action="store_true",
                   help="Actually create the indexes (ADMIN + dry-run receipt).")
    p.add_argument("--dry-run", action="store_true",
                   help="Explicit dry-run (default); writes a permission receipt.")
    p.add_argument("--operator-role", default=None,
                   help="VIEWER|OPERATOR|ADMIN (default: MVP_OPERATOR_ROLE env). "
                        "--apply requires ADMIN.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = _resolve_db_path(Path(args.db_path) if args.db_path else None)
    stmts = planned_indexes(db_path)

    if not args.apply:
        try:
            _guard.write_dry_run_receipt(
                OPERATION_NAME, target_count=len(stmts), db_path=str(db_path))
        except Exception:  # pragma: no cover - best-effort
            pass
        print(f"[indexes] DRY-RUN — {len(stmts)} additive index(es) planned:")
        for s in stmts:
            print(f"[indexes]   {s}")
        if not stmts:
            print("[indexes]   (none — hot paths already covered)")
        print("[indexes] To apply (PowerShell):")
        print('[indexes]   $env:MVP_OPERATOR_ROLE="ADMIN"')
        print(f"[indexes]   python scripts\\apply_cockpit_hot_path_indexes.py "
              f"--apply --db-path {db_path}")
        return 0

    # CLI request/role/receipt boilerplate collapsed into build_apply_decision
    # (Kanté Task B).  MIGRATION_WRITE is ADMIN-only inside the guard.
    try:
        decision = _guard.build_apply_decision(
            OPERATION_NAME, OPERATION_CLASS, str(db_path),
            operator_role=args.operator_role)
    except PermissionError as exc:
        print(f"[indexes] [DENY] {exc}", file=sys.stderr)
        return 2

    result = apply_indexes(db_path, stmts, permission_decision=decision)
    print(f"[indexes] APPLIED — created {len(result['created'])} index(es):")
    for s in result["created"]:
        print(f"[indexes]   {s}")
    if result["refused"]:
        print(f"[indexes] refused {len(result['refused'])} non-additive statement(s).")
    return 0


__all__ = [
    "OPERATION_NAME",
    "OPERATION_CLASS",
    "planned_indexes",
    "apply_indexes",
]


if __name__ == "__main__":
    raise SystemExit(main())
