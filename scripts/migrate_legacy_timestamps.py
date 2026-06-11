"""Aware-UTC migration for legacy naive timestamps (Pass 6, Phase 2).

New writes stamp aware UTC (`runtime_common.utc_timestamp`); historical
rows may carry naive strings, which the temporal layer now EXCLUDES from
calibration/evaluation. This tool migrates them honestly:

  * DRY-RUN by default — nothing is written without ``--apply``;
  * naive timestamps are converted ONLY with an explicit
    ``--assume-timezone <IANA zone>`` (e.g. Asia/Kolkata, Europe/Berlin):
    the operator asserts what clock the old writer used; the script
    NEVER guesses and refuses silent conversion;
  * unparsable/ambiguous values are left untouched and listed as
    ``temporal_uncertain`` — the evaluation layer already excludes naive
    rows, so "uncertain" stays excluded by construction (no fabricated
    precision, ever);
  * converted values are written as ISO-8601 ``+00:00`` UTC;
  * idempotent: aware rows are never touched again;
  * every applied run writes a migration report and a tamper-evident
    audit event.

Usage:
    python scripts/migrate_legacy_timestamps.py                       # scan only
    python scripts/migrate_legacy_timestamps.py --assume-timezone Asia/Kolkata
    python scripts/migrate_legacy_timestamps.py --assume-timezone Asia/Kolkata --apply
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sqlite3
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from scripts import operator_permission_guard as _guard
except ModuleNotFoundError:  # pragma: no cover - script-style env
    import operator_permission_guard as _guard  # type: ignore[no-redef]

# Kanté write boundary: --apply routes through the central
# operator_permission_guard (MIGRATION_WRITE: authorized role + recent
# dry-run receipt; allow/deny both audited). The dry run writes the
# receipt a later --apply must present.
OPERATION_NAME = "migrate_legacy_timestamps"
OPERATION_CLASS = _guard.OperationClass.MIGRATION_WRITE

# (table, pk_column, timestamp columns)
TARGETS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("manual_trades", "trade_id", ("executed_at", "logged_at")),
    ("reconciliation_results", "reconciliation_id", ("reconciled_at",)),
    ("imported_outcomes", "outcome_id", ("opened_at", "closed_at", "imported_at")),
    ("moltbook_entries", "entry_id", ("logged_at",)),
    ("signal_events", "event_id", ("fetched_at",)),
)


def classify_timestamp(value: str | None) -> str:
    """aware | naive | empty | unparsable."""
    if value is None or not str(value).strip():
        return "empty"
    raw = str(value).strip()
    try:
        dt = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return "unparsable"
    return "aware" if dt.tzinfo is not None else "naive"


def convert_naive(value: str, zone: ZoneInfo) -> str:
    """Attach the operator-asserted zone, normalize to UTC ISO."""
    dt = _dt.datetime.fromisoformat(str(value).strip())
    return dt.replace(tzinfo=zone).astimezone(_dt.timezone.utc).isoformat()


def scan(db_path: Path) -> dict:
    """Classify every targeted timestamp; read-only."""
    result: dict = {"db": str(db_path), "tables": {}, "naive_total": 0,
                    "unparsable_total": 0, "aware_total": 0}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        for table, pk, columns in TARGETS:
            try:
                rows = conn.execute(
                    f"SELECT {pk}, {', '.join(columns)} FROM {table}"  # noqa: S608 — hardcoded TARGETS
                ).fetchall()
            except sqlite3.OperationalError:
                result["tables"][table] = {"error": "table missing"}
                continue
            naive, unparsable, aware = [], [], 0
            for row in rows:
                for col in columns:
                    kind = classify_timestamp(row[col])
                    if kind == "naive":
                        naive.append({"pk": row[pk], "column": col,
                                      "value": str(row[col])})
                    elif kind == "unparsable":
                        unparsable.append({"pk": row[pk], "column": col,
                                           "value": str(row[col])[:40]})
                    elif kind == "aware":
                        aware += 1
            result["tables"][table] = {
                "rows": len(rows), "naive": naive,
                "temporal_uncertain": unparsable, "aware": aware,
            }
            result["naive_total"] += len(naive)
            result["unparsable_total"] += len(unparsable)
            result["aware_total"] += aware
    finally:
        conn.close()
    return result


def migrate(
    db_path: Path,
    *,
    assume_timezone: str | None = None,
    apply: bool = False,
) -> dict:
    """Scan, then (with --apply + an asserted zone) convert naive rows.

    Returns the migration report. Refuses to convert anything without an
    explicit timezone assertion; unparsable rows are never converted.
    """
    report = scan(db_path)
    report["mode"] = "apply" if apply else "dry_run"
    report["assumed_timezone"] = assume_timezone
    report["converted"] = 0
    report["generated_utc"] = _dt.datetime.now(_dt.timezone.utc).isoformat()

    if report["naive_total"] and assume_timezone is None:
        report["refusal"] = (
            f"{report['naive_total']} naive timestamp(s) found but no "
            "--assume-timezone given — REFUSING silent conversion. The "
            "operator must assert which clock the legacy writer used."
        )
        return report
    if not apply or not report["naive_total"]:
        if not apply:
            # Receipt proves a dry-run happened; build_apply_decision
            # requires it before any --apply is authorized.
            try:
                _guard.write_dry_run_receipt(
                    OPERATION_NAME,
                    target_count=report["naive_total"],
                    db_path=str(db_path),
                )
            except Exception:  # pragma: no cover - receipt is best-effort
                pass
        return report

    zone = ZoneInfo(assume_timezone)
    conn = sqlite3.connect(db_path)
    try:
        for table, pk, _columns in TARGETS:
            info = report["tables"].get(table, {})
            for entry in info.get("naive", []):
                new_value = convert_naive(entry["value"], zone)
                conn.execute(
                    f"UPDATE {table} SET {entry['column']} = ? WHERE {pk} = ? "  # noqa: S608
                    f"AND {entry['column']} = ?",
                    (new_value, entry["pk"], entry["value"]),
                )
                entry["converted_to"] = new_value
                report["converted"] += 1
        conn.commit()
    finally:
        conn.close()

    try:
        from scripts.audit_log import append_event
    except ModuleNotFoundError:  # pragma: no cover
        from audit_log import append_event  # type: ignore[no-redef]
    append_event(
        "settings_change", actor="owner", action="migrate_legacy_timestamps",
        outcome=f"converted_{report['converted']}",
        metadata={"assumed_timezone": assume_timezone,
                  "temporal_uncertain": report["unparsable_total"]},
    )
    return report


def write_report(report: dict, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (_REPO_ROOT / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"timestamp_migration_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, default=str) + "\n",
                    encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=None, help="SQLite path (default: runtime DB)")
    parser.add_argument("--assume-timezone", default=None,
                        help="IANA zone the legacy writer used (e.g. Asia/Kolkata)")
    parser.add_argument("--apply", action="store_true",
                        help="write conversions (default: DRY RUN)")
    parser.add_argument("--operator-role", default=None,
                        help="role for the permission guard (else MVP_OPERATOR_ROLE env)")
    args = parser.parse_args(argv)

    if args.apply:
        # Central permission guard: fails closed, audits allow AND deny.
        try:
            _guard.build_apply_decision(
                OPERATION_NAME, OPERATION_CLASS, None,
                operator_role=args.operator_role,
            )
        except PermissionError as exc:
            print(f"[DENY] {exc}", file=sys.stderr)
            print("[hint] run the dry-run first (writes the receipt), then "
                  "re-run --apply as an authorized role "
                  "(MVP_OPERATOR_ROLE=ADMIN or --operator-role ADMIN).",
                  file=sys.stderr)
            return 2

    if args.db:
        db_path = Path(args.db)
    else:
        try:
            from scripts.runtime_config import get_db_path
        except ModuleNotFoundError:  # pragma: no cover
            from runtime_config import get_db_path  # type: ignore[no-redef]
        db_path = get_db_path()
    if not db_path.exists():
        print(f"[error] DB not found: {db_path}", file=sys.stderr)
        return 2

    try:
        report = migrate(db_path, assume_timezone=args.assume_timezone,
                         apply=args.apply)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    path = write_report(report)
    print(f"[{report['mode']}] naive: {report['naive_total']} · "
          f"converted: {report['converted']} · "
          f"temporal_uncertain (never converted): {report['unparsable_total']} · "
          f"report: {path}")
    if "refusal" in report:
        print(f"[refused] {report['refusal']}", file=sys.stderr)
        return 1
    if not args.apply and report["naive_total"]:
        print("[note] DRY RUN — re-run with --apply to convert.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
