"""
Local MVP smoke test — verifies all persistence, safety invariants, and Phase 1
runner behavior WITHOUT placing trades, calling brokers, or touching live APIs.

Usage
-----
    python scripts/local_mvp_smoke_test.py              # run all checks
    python scripts/local_mvp_smoke_test.py --json       # JSON report
    python scripts/local_mvp_smoke_test.py --skip-live-source  # skip network check

Exit codes
----------
    0 — all checks passed
    1 — one or more checks failed

Safety contract
---------------
    advisory_status    = ADVISORY_ONLY  (every record)
    execution_mode     = HUMAN_ONLY     (every record)
    ai_execution_count = 0              (always)
    broker_api_called  = False          (always)
    broker_order_id    = NONE           (always)
"""
from __future__ import annotations

import ast
import csv
import io
import json
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_ADVISORY_ONLY = "ADVISORY_ONLY"
_HUMAN_ONLY = "HUMAN_ONLY"
_AI_EXECUTION_COUNT = 0

_FORBIDDEN_EXEC_FUNCTIONS = {
    "place_order",
    "submit_order",
    "execute_trade",
    "auto_buy",
    "auto_sell",
    "cancel_order",
    "modify_order",
    "broker_execute",
    "live_execute",
    "connect_broker",
    "broker_login",
    "grant_execution",
}

_STATIC_ANALYSIS_TARGETS = [
    _REPO_ROOT / "scripts" / "persistence.py",
    _REPO_ROOT / "scripts" / "live_source_runner.py",
]


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass
class SmokeTestReport:
    checks: list[CheckResult] = field(default_factory=list)
    advisory_status: str = _ADVISORY_ONLY
    ai_execution_count: int = _AI_EXECUTION_COUNT
    broker_api_called: bool = False
    broker_order_id: str = "NONE"

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_passed": self.all_passed,
            "passed": self.passed_count,
            "failed": self.failed_count,
            "advisory_status": self.advisory_status,
            "ai_execution_count": self.ai_execution_count,
            "broker_api_called": self.broker_api_called,
            "broker_order_id": self.broker_order_id,
            "checks": [c.to_dict() for c in self.checks],
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ok(name: str, msg: str = "") -> CheckResult:
    return CheckResult(name=name, passed=True, message=msg or "PASS")


def _fail(name: str, msg: str, detail: str = "") -> CheckResult:
    return CheckResult(name=name, passed=False, message=msg, detail=detail)


def _safe_run(name: str, fn: Callable[[], CheckResult]) -> CheckResult:
    """Call fn() and convert any unexpected exception to a FAIL result."""
    try:
        return fn()
    except Exception as exc:
        return _fail(name, f"Unexpected exception: {exc}", traceback.format_exc())


# ---------------------------------------------------------------------------
# Individual check functions (each returns a CheckResult)
# ---------------------------------------------------------------------------


def check_db_init(db_path: Path) -> CheckResult:
    """DB file is created and all required tables exist after init_schema()."""
    import sqlite3
    from scripts.persistence import init_schema

    init_schema(db_path)
    if not db_path.exists():
        return _fail("db_init", "DB file not created after init_schema()")

    conn = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()

    required = {
        "signal_decisions",
        "user_reflections",
        "ai_discussion_summaries",
        "manual_trades",
        "reconciliation_results",
        "moltbook_entries",
        "source_health",
        "export_logs",
        "signal_events",
        "source_run_log",
    }
    missing = required - tables
    if missing:
        return _fail("db_init", f"Missing tables: {missing}")
    return _ok("db_init", f"DB initialized with {len(tables)} tables")


def check_db_status(db_path: Path) -> CheckResult:
    """get_db_status() returns expected shape and advisory invariants."""
    from scripts.persistence import get_db_status

    status = get_db_status(db_path=db_path)

    if not status.get("db_exists"):
        return _fail("db_status", "db_exists=False after schema init")
    if status.get("advisory_status") != _ADVISORY_ONLY:
        return _fail("db_status", f"advisory_status={status.get('advisory_status')!r}")
    if status.get("ai_execution_count") != 0:
        return _fail("db_status", f"ai_execution_count={status.get('ai_execution_count')}")
    if status.get("broker_api_called") is not False:
        return _fail("db_status", f"broker_api_called={status.get('broker_api_called')}")
    counts = status.get("table_row_counts", {})
    if not isinstance(counts, dict):
        return _fail("db_status", "table_row_counts is not a dict")
    return _ok("db_status", f"DB status OK — {len(counts)} tables tracked")


def check_signal_event_persistence(db_path: Path) -> CheckResult:
    """Synthetic signal event persists with all required advisory stamps."""
    from scripts.persistence import insert_signal_event, get_signal_events

    payload = {
        "event_id": "smoke_evt_001",
        "source_name": "synthetic_test",
        "signal_type": "test",
        "title": "Smoke Test Signal — advisory only",
        "advisory_status": _ADVISORY_ONLY,
        "execution_gate": "LOCKED",
        "ai_execution_count": 0,
    }
    inserted = insert_signal_event(
        event_id="smoke_evt_001",
        source_name="synthetic_test",
        raw_payload=payload,
        fetched_at="2026-01-01T00:00:00Z",
        db_path=db_path,
    )

    events = get_signal_events(source_name="synthetic_test", db_path=db_path)
    if not events:
        return _fail("signal_event_persistence", "No signal events returned after insert")

    ev = events[0]
    for field_name, expected in [
        ("advisory_status", _ADVISORY_ONLY),
        ("ai_execution_count", 0),
        ("execution_gate", "LOCKED"),
    ]:
        if ev.get(field_name) != expected:
            return _fail(
                "signal_event_persistence",
                f"{field_name}={ev.get(field_name)!r}, expected {expected!r}",
            )
    if not ev.get("human_review_required"):
        return _fail("signal_event_persistence", "human_review_required is False")

    return _ok("signal_event_persistence", f"inserted={inserted}, advisory stamps verified")


def check_reflection_persistence(db_path: Path) -> CheckResult:
    """Reflection persists and reads back with all advisory invariants."""
    from scripts.persistence import insert_reflection, get_reflections_for_event

    insert_reflection(
        "smoke_ref_001",
        "smoke_evt_001",
        "human",
        "MODERATE",
        "Smoke test reflection — advisory only, no execution",
        "2026-01-01T00:00:00Z",
        db_path=db_path,
    )

    rows = get_reflections_for_event("smoke_evt_001", db_path=db_path)
    if not rows:
        return _fail("reflection_persistence", "No reflections returned after insert")

    r = rows[0]
    for field_name, expected in [
        ("advisory_status", _ADVISORY_ONLY),
        ("execution_mode", _HUMAN_ONLY),
        ("ai_execution_count", 0),
    ]:
        if r.get(field_name) != expected:
            return _fail(
                "reflection_persistence",
                f"{field_name}={r.get(field_name)!r}, expected {expected!r}",
            )
    if not r.get("human_review_required"):
        return _fail("reflection_persistence", "human_review_required is False")

    return _ok("reflection_persistence", "Reflection persisted with correct advisory stamps")


def check_manual_trade_persistence(db_path: Path) -> CheckResult:
    """Manual trade persists with HUMAN_ONLY mode and broker safety locks active."""
    from scripts.persistence import insert_manual_trade, get_all_manual_trades

    insert_manual_trade(
        "smoke_mt_001",
        "smoke_evt_001",
        "AAPL",
        "BUY",
        1.0,
        100.0,
        "2026-01-01T00:00:00Z",
        "Smoke test thesis — HUMAN_ONLY, no broker",
        "no broker API called",
        "human",
        db_path=db_path,
    )

    trades = get_all_manual_trades(db_path=db_path)
    if not trades:
        return _fail("manual_trade_persistence", "No trades returned after insert")

    t = next((x for x in trades if x["trade_id"] == "smoke_mt_001"), None)
    if t is None:
        return _fail("manual_trade_persistence", "smoke_mt_001 not found in trade list")

    for field_name, expected in [
        ("execution_mode", _HUMAN_ONLY),
        ("ai_execution_count", 0),
        ("advisory_status", _ADVISORY_ONLY),
        ("broker_api_called", False),
        ("broker_order_id", "NONE"),
    ]:
        if t.get(field_name) != expected:
            return _fail(
                "manual_trade_persistence",
                f"{field_name}={t.get(field_name)!r}, expected {expected!r}",
            )

    return _ok(
        "manual_trade_persistence",
        "execution_mode=HUMAN_ONLY | broker_api_called=False | broker_order_id=NONE",
    )


def check_reconciliation_persistence(db_path: Path) -> CheckResult:
    """Reconciliation result persists with HUMAN_ONLY and advisory stamps."""
    from scripts.persistence import insert_reconciliation, get_all_reconciliations

    insert_reconciliation(
        "smoke_rec_001",
        "smoke_mt_001",
        "smoke_evt_001",
        "2026-01-02T00:00:00Z",
        101.0,
        1.0,
        "Smoke test outcome — manual reconciliation only",
        1.0,
        "WIN",
        db_path=db_path,
    )

    recs = get_all_reconciliations(db_path=db_path)
    if not recs:
        return _fail("reconciliation_persistence", "No reconciliations returned after insert")

    rec = next((r for r in recs if r["reconciliation_id"] == "smoke_rec_001"), None)
    if rec is None:
        return _fail("reconciliation_persistence", "smoke_rec_001 not found")

    for field_name, expected in [
        ("execution_mode", _HUMAN_ONLY),
        ("ai_execution_count", 0),
        ("advisory_status", _ADVISORY_ONLY),
    ]:
        if rec.get(field_name) != expected:
            return _fail(
                "reconciliation_persistence",
                f"{field_name}={rec.get(field_name)!r}, expected {expected!r}",
            )

    return _ok("reconciliation_persistence", "Reconciliation persisted with advisory stamps")


def check_moltbook_persistence(db_path: Path) -> CheckResult:
    """Moltbook entry persists with all advisory stamps and searchable by ticker."""
    from scripts.persistence import insert_moltbook_entry, get_moltbook_entries

    insert_moltbook_entry(
        "smoke_mb_001",
        "smoke_evt_001",
        "AAPL",
        "Original signal thesis",
        "AI interpretation — advisory only",
        "Human reflection text",
        "no_trade",
        "smoke_mt_001",
        "break-even",
        "late_entry",
        "Enter earlier next time — within first 30 min of signal",
        "confirmation_bias",
        "Wait for volume confirmation",
        "Add volume filter to entry rule",
        "2026-01-01T00:00:00Z",
        db_path=db_path,
    )

    entries = get_moltbook_entries(db_path=db_path)
    if not entries:
        return _fail("moltbook_persistence", "No moltbook entries returned after insert")

    entry = next((e for e in entries if e["entry_id"] == "smoke_mb_001"), None)
    if entry is None:
        return _fail("moltbook_persistence", "smoke_mb_001 not found")

    for field_name, expected in [
        ("advisory_status", _ADVISORY_ONLY),
        ("execution_mode", _HUMAN_ONLY),
        ("ai_execution_count", 0),
    ]:
        if entry.get(field_name) != expected:
            return _fail(
                "moltbook_persistence",
                f"{field_name}={entry.get(field_name)!r}, expected {expected!r}",
            )

    return _ok(
        "moltbook_persistence",
        f"ticker={entry['ticker']}, mistake_type={entry['mistake_type']}",
    )


def check_export_csv_output(db_path: Path) -> CheckResult:
    """Persisted records can be serialized to CSV-compatible output."""
    from scripts.persistence import get_all_manual_trades, get_all_reflections

    trades = get_all_manual_trades(db_path=db_path)
    reflections = get_all_reflections(db_path=db_path)

    if not trades:
        return _fail("export_csv_output", "No trades to export (insert check must run first)")
    if not reflections:
        return _fail("export_csv_output", "No reflections to export (reflection check must run first)")

    # Trades to CSV
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(trades[0].keys()))
    writer.writeheader()
    writer.writerows(trades)
    trades_csv = buf.getvalue()
    if "advisory_status" not in trades_csv:
        return _fail("export_csv_output", "advisory_status column missing from trades CSV")
    if _ADVISORY_ONLY not in trades_csv:
        return _fail("export_csv_output", f"{_ADVISORY_ONLY} not present in trades CSV values")

    # Reflections to CSV
    buf2 = io.StringIO()
    writer2 = csv.DictWriter(buf2, fieldnames=list(reflections[0].keys()))
    writer2.writeheader()
    writer2.writerows(reflections)
    reflections_csv = buf2.getvalue()
    if "advisory_status" not in reflections_csv:
        return _fail("export_csv_output", "advisory_status column missing from reflections CSV")

    return _ok(
        "export_csv_output",
        f"trades_rows={len(trades)}, reflections_rows={len(reflections)} — CSV-serializable",
    )


def check_no_execution_permission() -> CheckResult:
    """Static AST check: no forbidden broker/execution functions exist in key files."""
    for target in _STATIC_ANALYSIS_TARGETS:
        if not target.exists():
            return _fail("no_execution_permission", f"File not found: {target}")
        src = target.read_text(encoding="utf-8")
        tree = ast.parse(src)
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        found = _FORBIDDEN_EXEC_FUNCTIONS & defined
        if found:
            return _fail(
                "no_execution_permission",
                f"Forbidden execution functions in {target.name}: {sorted(found)}",
            )

    names = [t.name for t in _STATIC_ANALYSIS_TARGETS]
    return _ok("no_execution_permission", f"No forbidden execution functions in {names}")


def check_ai_execution_count(db_path: Path) -> CheckResult:
    """ai_execution_count is 0 across all records and the DB status endpoint."""
    from scripts.persistence import (
        get_all_manual_trades,
        get_all_reflections,
        get_moltbook_entries,
        get_db_status,
    )

    failures: list[str] = []

    for t in get_all_manual_trades(db_path=db_path):
        if t.get("ai_execution_count") != 0:
            failures.append(f"trade {t['trade_id']}: {t['ai_execution_count']}")

    for r in get_all_reflections(db_path=db_path):
        if r.get("ai_execution_count") != 0:
            failures.append(f"reflection {r['reflection_id']}: {r['ai_execution_count']}")

    for m in get_moltbook_entries(db_path=db_path):
        if m.get("ai_execution_count") != 0:
            failures.append(f"moltbook {m['entry_id']}: {m['ai_execution_count']}")

    status = get_db_status(db_path=db_path)
    if status.get("ai_execution_count") != 0:
        failures.append(f"db_status: {status['ai_execution_count']}")

    if failures:
        return _fail("ai_execution_count", f"Non-zero counts: {failures}")

    return _ok("ai_execution_count", "ai_execution_count=0 across all records and status")


def check_broker_invariants(db_path: Path) -> CheckResult:
    """broker_api_called=False and broker_order_id=NONE on all trades and status."""
    from scripts.persistence import get_all_manual_trades, get_db_status

    failures: list[str] = []

    for t in get_all_manual_trades(db_path=db_path):
        if t.get("broker_api_called") is not False:
            failures.append(f"trade {t['trade_id']}: broker_api_called={t['broker_api_called']}")
        if t.get("broker_order_id") != "NONE":
            failures.append(f"trade {t['trade_id']}: broker_order_id={t['broker_order_id']!r}")

    status = get_db_status(db_path=db_path)
    if status.get("broker_api_called") is not False:
        failures.append(f"db_status: broker_api_called={status['broker_api_called']}")

    if failures:
        return _fail("broker_invariants", f"Broker safety violations: {failures}")

    return _ok(
        "broker_invariants",
        "broker_api_called=False | broker_order_id=NONE | no broker contact",
    )


def check_live_source_dry_run(phase1_runner: Any = None) -> CheckResult:
    """Phase 1 runner returns a Phase1RunReport in dry-run mode without crashing."""
    if phase1_runner is None:
        from scripts.live_source_runner import run_phase1 as phase1_runner  # type: ignore[assignment]

    report = phase1_runner(dry_run=True, polymarket_limit=1, gdelt_max_records=1)

    if report is None:
        return _fail("live_source_dry_run", "run_phase1() returned None")
    if not hasattr(report, "dry_run"):
        return _fail("live_source_dry_run", "Report missing 'dry_run' attribute")
    if not report.dry_run:
        return _fail("live_source_dry_run", "dry_run flag is False — expected True")
    if report.ai_execution_count != 0:
        return _fail(
            "live_source_dry_run",
            f"ai_execution_count={report.ai_execution_count}, expected 0",
        )
    if report.advisory_status != _ADVISORY_ONLY:
        return _fail(
            "live_source_dry_run",
            f"advisory_status={report.advisory_status!r}, expected {_ADVISORY_ONLY!r}",
        )
    if report.total_persisted != 0:
        return _fail(
            "live_source_dry_run",
            f"Dry-run persisted {report.total_persisted} events — expected 0",
        )

    return _ok(
        "live_source_dry_run",
        f"dry_run=True | fetched={report.total_fetched} | persisted=0 | advisory_status=ADVISORY_ONLY",
    )


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def run_smoke_tests(
    live_source_runner: Any = None,
    skip_live_source: bool = False,
) -> SmokeTestReport:
    """
    Run all smoke tests using a temporary SQLite DB (never touches runtime/mvp_local.db).

    Parameters
    ----------
    live_source_runner:
        Optional callable with the same signature as ``run_phase1``.  Pass a mock
        here when calling from tests to avoid any network dependency.
    skip_live_source:
        If True, skip the Phase 1 live-source dry-run check entirely.
    """
    report = SmokeTestReport()

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "smoke_test.db"

        # DB-dependent checks — must run in order (init must be first)
        db_checks: list[tuple[str, Callable[[], CheckResult]]] = [
            ("db_init", lambda: check_db_init(db_path)),
            ("db_status", lambda: check_db_status(db_path)),
            ("signal_event_persistence", lambda: check_signal_event_persistence(db_path)),
            ("reflection_persistence", lambda: check_reflection_persistence(db_path)),
            ("manual_trade_persistence", lambda: check_manual_trade_persistence(db_path)),
            ("reconciliation_persistence", lambda: check_reconciliation_persistence(db_path)),
            ("moltbook_persistence", lambda: check_moltbook_persistence(db_path)),
            ("export_csv_output", lambda: check_export_csv_output(db_path)),
            ("ai_execution_count", lambda: check_ai_execution_count(db_path)),
            ("broker_invariants", lambda: check_broker_invariants(db_path)),
        ]
        for name, fn in db_checks:
            report.checks.append(_safe_run(name, fn))

    # Static analysis — no DB needed
    report.checks.append(_safe_run("no_execution_permission", check_no_execution_permission))

    # Live source dry-run — no DB needed, network optional
    if skip_live_source:
        report.checks.append(
            CheckResult(
                name="live_source_dry_run",
                passed=True,
                message="SKIPPED (--skip-live-source)",
            )
        )
    else:
        report.checks.append(
            _safe_run(
                "live_source_dry_run",
                lambda: check_live_source_dry_run(live_source_runner),
            )
        )

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_report(report: SmokeTestReport) -> None:
    width = 64
    print("=" * width)
    print("  Pipeline V5.7 — Local MVP Smoke Test")
    print("=" * width)
    for check in report.checks:
        tag = "PASS" if check.passed else "FAIL"
        print(f"  [{tag}] {check.name}: {check.message}")
        if not check.passed and check.detail:
            for line in check.detail.splitlines()[:6]:
                print(f"         {line}")
    print("-" * width)
    print(f"  {report.passed_count}/{len(report.checks)} checks passed")
    print(f"  advisory_status    = {report.advisory_status}")
    print(f"  ai_execution_count = {report.ai_execution_count}")
    print(f"  broker_api_called  = {report.broker_api_called}")
    print(f"  broker_order_id    = {report.broker_order_id}")
    print("=" * width)
    if report.all_passed:
        print("  RESULT: ALL CHECKS PASSED")
        print("  MVP is advisory-only and broker-free. Safe to demo.")
    else:
        print(f"  RESULT: {report.failed_count} CHECK(S) FAILED — see above.")
    print("=" * width)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Local MVP smoke test — verifies persistence and advisory invariants."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output full report as JSON.",
    )
    parser.add_argument(
        "--skip-live-source",
        action="store_true",
        dest="skip_live_source",
        help="Skip the Phase 1 live-source dry-run check (useful offline).",
    )
    args = parser.parse_args()

    report = run_smoke_tests(skip_live_source=args.skip_live_source)

    if args.output_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_report(report)

    return 0 if report.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
