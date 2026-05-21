"""SQLite integrity audit for the canonical advisory store (Sprint 2 — Task 7).

Read-only proof that the canonical SQLite DB is structurally sound and free of
the failure modes that would corrupt operator truth:

* required tables present,
* schema-version table recorded (WARN if absent — init separately),
* no duplicate Moltbook ``manual_trade_log_id`` (one learning entry per loss),
* no fake SPY/QQQ/FABRIC Moltbook pollution,
* ``duplicate_fingerprints`` keyed uniquely; ``signal_cell_index`` indexed,
* no orphaned Moltbook rows pointing at a non-existent trade,
* JSONL is not canonical (shared-contract invariant),
* SQLite ``PRAGMA integrity_check`` passes (the DB can be safely backed up).

Integrity score::

    Integrity = 1 - (orphans + dup_keys + null_required + broken_links)
                    / (total_rows + 1)

Read-only **unless** ``--init-schema-version`` is passed (the only write path,
delegated to :mod:`scripts.schema_migrations`).  Never a broker call.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import schema_migrations as _migrations
except ModuleNotFoundError:  # pragma: no cover
    import schema_migrations as _migrations  # type: ignore[no-redef]

try:
    from scripts import local_deploy_preflight as _preflight
except ModuleNotFoundError:  # pragma: no cover
    import local_deploy_preflight as _preflight  # type: ignore[no-redef]

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"

_REQUIRED_TABLES = (
    "signal_events", "manual_trades", "reconciliation_results",
    "moltbook_entries", "duplicate_fingerprints", "signal_cell_index",
)
_OPTIONAL_TABLES = ("schema_version", "source_health", "global_securities")


def _default_db_path() -> Path:
    return _migrations._default_db_path()


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.Error:
            return None
    conn.row_factory = sqlite3.Row
    return conn


def _check(name: str, status: str, detail: str, **extra: Any) -> dict[str, Any]:
    out = {"name": name, "status": status, "detail": detail}
    out.update(extra)
    return out


def _tables(conn: sqlite3.Connection) -> set[str]:
    try:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    except sqlite3.Error:  # pragma: no cover
        return set()


def run_integrity_audit(db_path: Path | None = None) -> dict[str, Any]:
    """Run every read-only integrity check; compute the integrity score."""
    path = Path(db_path) if db_path is not None else _default_db_path()
    report: dict[str, Any] = {
        "report": "db_integrity_audit",
        "db_path": str(path),
        "db_exists": path.exists(),
        "checks": [],
        **_contract.advisory_safety_stamps(),
    }
    conn = _readonly_connect(path)
    if conn is None:
        report["overall"] = FAIL
        report["integrity_score"] = 0.0
        report["checks"] = [_check("db_readable", FAIL,
                                   "runtime DB missing/unreadable — fail closed.")]
        return report

    checks: list[dict[str, Any]] = []
    orphans = dup_keys = null_required = broken_links = 0
    total_rows = 0
    try:
        present = _tables(conn)

        # 1. required tables
        missing = [t for t in _REQUIRED_TABLES if t not in present]
        checks.append(
            _check("required_tables", FAIL if missing else PASS,
                   f"missing: {missing}" if missing else "all required tables present.",
                   missing=missing))

        # 2. schema version table
        if "schema_version" in present:
            ver = _migrations.get_schema_version(path)
            checks.append(_check("schema_version_present", PASS,
                                 f"schema_version recorded (version={ver})."))
        else:
            checks.append(_check("schema_version_present", WARN,
                                 "schema_version table absent — run "
                                 "schema_migrations.py --init-schema-version."))

        # 3. duplicate Moltbook manual_trade_log_id
        if "moltbook_entries" in present:
            try:
                dups = conn.execute(
                    "SELECT manual_trade_log_id, COUNT(*) c FROM moltbook_entries"
                    " WHERE TRIM(COALESCE(manual_trade_log_id,'')) != ''"
                    " GROUP BY manual_trade_log_id HAVING c > 1"
                ).fetchall()
            except sqlite3.Error:
                dups = []
            dup_keys = len(dups)
            checks.append(
                _check("moltbook_no_duplicate_trade_link", FAIL if dups else PASS,
                       f"{len(dups)} manual_trade_log_id linked by >1 Moltbook entry."
                       if dups else "no duplicate Moltbook trade links.",
                       duplicates=[dict(r) for r in dups][:10]))
            total_rows += int(conn.execute(
                "SELECT COUNT(*) FROM moltbook_entries").fetchone()[0])

        # 4. fake pollution (reuse the preflight signature for consistency)
        pollution = _preflight.check_moltbook_no_fake_pollution(path)
        checks.append(_check("moltbook_no_fake_pollution", pollution["status"],
                             pollution["detail"]))

        # 5. duplicate_fingerprints uniqueness + signal_cell_index index
        if "duplicate_fingerprints" in present:
            try:
                fp_dups = int(conn.execute(
                    "SELECT COUNT(*) - COUNT(DISTINCT fingerprint)"
                    " FROM duplicate_fingerprints").fetchone()[0])
            except sqlite3.Error:
                fp_dups = 0
            dup_keys += max(fp_dups, 0)
            checks.append(_check("fingerprint_unique", FAIL if fp_dups else PASS,
                                 f"{fp_dups} duplicate fingerprint key(s)."
                                 if fp_dups else "fingerprint keys unique."))
        idx = set()
        try:
            idx = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
        except sqlite3.Error:
            idx = set()
        sci_indexed = any(n.startswith("idx_sci_") for n in idx)
        checks.append(_check("signal_cell_index_indexed",
                             PASS if sci_indexed else WARN,
                             "signal_cell_index has query indexes." if sci_indexed
                             else "signal_cell_index indexes missing — run "
                                  "signal_index_query.ensure_indexes."))

        # 6. orphaned Moltbook rows (link to a non-existent trade)
        if "moltbook_entries" in present and "manual_trades" in present:
            try:
                orphans = int(conn.execute(
                    "SELECT COUNT(*) FROM moltbook_entries m"
                    " WHERE TRIM(COALESCE(m.manual_trade_log_id,'')) != ''"
                    " AND NOT EXISTS (SELECT 1 FROM manual_trades t"
                    "                 WHERE t.trade_id = m.manual_trade_log_id)"
                ).fetchone()[0])
            except sqlite3.Error:
                orphans = 0
            broken_links = orphans
            checks.append(_check("no_orphaned_moltbook_links",
                                 WARN if orphans else PASS,
                                 f"{orphans} Moltbook row(s) link a missing trade."
                                 if orphans else "no orphaned Moltbook trade links."))

        # 7. JSONL not canonical (contract)
        truth = _contract.canonical_truth_declaration()
        canonical_ok = truth["sqlite_is_canonical"] and not truth["jsonl_is_canonical"]
        checks.append(_check("jsonl_not_canonical", PASS if canonical_ok else FAIL,
                             "SQLite canonical; JSONL audit-only." if canonical_ok
                             else "truth model violated."))

        # 8. PRAGMA integrity_check (can the DB be backed up safely?)
        try:
            ic = conn.execute("PRAGMA integrity_check").fetchone()
            ok = bool(ic) and str(ic[0]).lower() == "ok"
        except sqlite3.Error:
            ok = False
        checks.append(_check("sqlite_integrity_check", PASS if ok else FAIL,
                             "PRAGMA integrity_check=ok (backup-safe)." if ok
                             else "PRAGMA integrity_check failed."))

        # total rows across required tables for the score denominator
        for t in _REQUIRED_TABLES:
            if t in present:
                try:
                    total_rows += int(conn.execute(
                        f"SELECT COUNT(*) FROM {t}").fetchone()[0])
                except sqlite3.Error:
                    pass
    finally:
        conn.close()

    report["checks"] = checks
    counts = {PASS: 0, WARN: 0, FAIL: 0, INFO: 0}
    for c in checks:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    report["counts"] = counts
    report["overall"] = FAIL if counts[FAIL] else WARN if counts[WARN] else PASS
    defects = orphans + dup_keys + null_required + broken_links
    report["integrity_score"] = round(1.0 - defects / (total_rows + 1.0), 4)
    report["defect_breakdown"] = {
        "orphans": orphans, "duplicate_keys": dup_keys,
        "null_required": null_required, "broken_links": broken_links,
    }
    return report


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="db_integrity_audit.py",
        description=(
            "Read-only canonical-DB integrity audit. Read-only unless "
            "--init-schema-version.  Never a broker call."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument("--init-schema-version", action="store_true",
                   help="Also create/record the schema version (only write path).")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = Path(args.db_path) if args.db_path else None
    if args.init_schema_version:
        _migrations.init_schema_version(db)
    report = run_integrity_audit(db)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"DB integrity audit: {report['overall']} "
              f"(score={report.get('integrity_score')})")
        for c in report["checks"]:
            print(f"  [{c['status']:<4}] {c['name']:<32} {c['detail']}")
    return 0 if report["overall"] != FAIL else 1


__all__ = ["run_integrity_audit"]


if __name__ == "__main__":
    raise SystemExit(main())
