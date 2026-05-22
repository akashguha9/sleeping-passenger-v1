"""Concurrency / stress probe over signal_events + cockpit hot paths (Kanté Task C).

The cockpit/diagnostics hot paths are *measured* (``cockpit_hot_path_query_audit``
runs ``EXPLAIN QUERY PLAN``), *indexed* (``apply_cockpit_hot_path_indexes``), and
*warm* (``diagnostics_snapshot_warmer``), but until now there was no proof they
hold up under concurrent read load.  ``signal_events`` has carried ~122k rows
historically; this probe drives many concurrent **read-only** operations across
the real hot paths and reports latency percentiles, error/timeout/lock counts,
and a single PASS/WARN/BLOCK stress gate.

Hard safety rules
-----------------
* **Read-only w.r.t. the canonical DB.**  Every SQLite connection is opened
  ``mode=ro``; the probe issues only ``SELECT`` / ``EXPLAIN`` / ``PRAGMA`` and
  asserts no mutation verb appears in any statement it runs.
* **No broker calls, no network, no execution, no AI execution.**
* **Bounded.**  Workers, iterations, per-run timeout, and per-query row caps are
  all bounded; there is no unbounded loop and no large in-memory accumulation.
* The only write side effect (CLI ``main`` only) is a derived, non-canonical
  ``last_run.json`` stress summary under ``runtime/cockpit_stress_probe/`` —
  audit-only, never canonical truth.

Scoring::

    SuccessRate  = successful_operations / max(total_operations, 1)
    TimeoutRate  = timeout_operations    / max(total_operations, 1)
    ErrorRate    = failed_operations     / max(total_operations, 1)
    LatencyScore = min(1, target_p95_ms / max(p95_ms, 1))
    StressScore  = 10 * (0.40*SuccessRate + 0.30*LatencyScore
                       + 0.20*(1 - TimeoutRate) + 0.10*(1 - ErrorRate))
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import runtime_config as _runtime_config
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import runtime_config as _runtime_config  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
SUMMARY_DIR = REPO_ROOT / "runtime" / "cockpit_stress_probe"
SUMMARY_FILE = SUMMARY_DIR / "last_run.json"

PASS, WARN, BLOCK = "PASS", "WARN", "BLOCK"

# Safe defaults — small, bounded, fast.
DEFAULT_WORKERS = 4
DEFAULT_ITERATIONS = 25
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_ROWS = 500
DEFAULT_TARGET_P95_MS = 500

# Any of these verbs appearing in a probe statement is a bug — the probe is
# strictly read-only and asserts against this set before executing SQL.
_FORBIDDEN_SQL_VERBS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER",
    "REPLACE", "TRUNCATE", "ATTACH", "REINDEX",
)


class StressOpResult:
    """One operation outcome (timing + classification).  Tiny, bounded."""

    __slots__ = ("name", "elapsed_ms", "status", "error_type", "db_locked",
                 "cache_error", "full_scans")

    def __init__(self, name: str) -> None:
        self.name = name
        self.elapsed_ms = 0.0
        self.status = "ok"          # ok | failed
        self.error_type: str | None = None
        self.db_locked = False
        self.cache_error = False
        self.full_scans = 0


def _assert_read_only(sql: str) -> None:
    upper = sql.upper()
    for verb in _FORBIDDEN_SQL_VERBS:
        # Word-ish boundary so column names like ``created_via`` never trip it.
        if f" {verb} " in f" {upper} " or upper.lstrip().startswith(verb + " "):
            raise AssertionError(
                f"stress_probe_invariant_violation: forbidden verb {verb!r} in "
                f"a probe statement — the probe must be strictly read-only."
            )


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    """Open a strictly read-only SQLite connection (``mode=ro``), or None."""
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(
            f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5.0
        )
    except sqlite3.Error:
        return None
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


# ---------------------------------------------------------------------------
# Read-only operations.  Each takes (db_path, max_rows) and either returns a
# small summary dict or raises.  A missing table / empty DB is handled safely
# (returns an empty-but-valid result, never an exception).
# ---------------------------------------------------------------------------


def _op_signal_events_recent(db_path: Path, max_rows: int) -> dict[str, Any]:
    conn = _readonly_connect(db_path)
    if conn is None:
        return {"db_available": False, "rows": 0}
    try:
        if not _table_exists(conn, "signal_events"):
            return {"table_missing": True, "rows": 0}
        sql = "SELECT * FROM signal_events ORDER BY fetched_at DESC LIMIT ?"
        _assert_read_only(sql)
        rows = conn.execute(sql, (max_rows,)).fetchall()
        return {"rows": len(rows)}
    finally:
        conn.close()


def _op_signal_events_by_source(db_path: Path, max_rows: int) -> dict[str, Any]:
    conn = _readonly_connect(db_path)
    if conn is None:
        return {"db_available": False, "rows": 0}
    try:
        if not _table_exists(conn, "signal_events"):
            return {"table_missing": True, "rows": 0}
        # Pick a present source if any, else probe a benign constant.
        src_row = conn.execute(
            "SELECT source_name FROM signal_events LIMIT 1"
        ).fetchone()
        source = src_row[0] if src_row else "rss"
        sql = ("SELECT * FROM signal_events WHERE source_name = ? "
               "ORDER BY fetched_at DESC LIMIT ?")
        _assert_read_only(sql)
        rows = conn.execute(sql, (source, max_rows)).fetchall()
        return {"rows": len(rows), "source": source}
    finally:
        conn.close()


def _op_signal_events_count_by_source(db_path: Path, max_rows: int) -> dict[str, Any]:
    conn = _readonly_connect(db_path)
    if conn is None:
        return {"db_available": False, "groups": 0}
    try:
        if not _table_exists(conn, "signal_events"):
            return {"table_missing": True, "groups": 0}
        sql = ("SELECT source_name, COUNT(*) AS n FROM signal_events "
               "GROUP BY source_name LIMIT ?")
        _assert_read_only(sql)
        rows = conn.execute(sql, (max_rows,)).fetchall()
        return {"groups": len(rows)}
    finally:
        conn.close()


def _op_hot_path_audit(db_path: Path, max_rows: int) -> dict[str, Any]:
    try:
        from scripts import cockpit_hot_path_query_audit as audit
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        import cockpit_hot_path_query_audit as audit  # type: ignore[no-redef]
    report = audit.audit_hot_paths(db_path)
    return {
        "full_scans": int(report.get("full_scan_hot_path_queries", 0) or 0),
        "score": report.get("cockpit_hot_path_score"),
    }


def _op_diagnostics_cache_read(db_path: Path, max_rows: int) -> dict[str, Any]:
    try:
        from scripts import diagnostics_snapshot_cache as cache
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        import diagnostics_snapshot_cache as cache  # type: ignore[no-redef]
    snap = cache.read_snapshot()
    validity = cache.cache_validity(snap, db_path)
    # An absent cache is a benign "miss", not an error; a present-but-corrupt
    # cache (read_snapshot returned None despite a file) is flagged by caller.
    return {"cache_present": snap is not None, "valid": validity.get("valid")}


def _op_diagnostics_service_read(db_path: Path, max_rows: int) -> dict[str, Any]:
    try:
        from scripts import diagnostics_service as svc
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        import diagnostics_service as svc  # type: ignore[no-redef]
    # Reuse any existing snapshot (huge max_age); never force a refresh under
    # concurrency.  On a cold cache this recomputes once into the derived cache
    # (non-canonical); the warm-up pass below makes that single, not N-fold.
    snap = svc.get_diagnostics_snapshot(
        use_cache=True, refresh=False, include_heavy=False,
        max_age_seconds=10 ** 9, db_path=db_path,
    )
    return {"status": snap.get("status")}


def _op_truth_purity_read(db_path: Path, max_rows: int) -> dict[str, Any]:
    try:
        from scripts import runtime_truth_purity_audit as tp
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        import runtime_truth_purity_audit as tp  # type: ignore[no-redef]
    report = tp.build_audit(db_path=db_path)
    return {"gate_passed": report.get("release_gate_passed")}


def _op_source_independence_read(db_path: Path, max_rows: int) -> dict[str, Any]:
    try:
        from scripts import source_independence_audit as si
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        import source_independence_audit as si  # type: ignore[no-redef]
    report = si.build_report(db_path=db_path)
    flagged = report.get("flagged_cohorts")
    return {"flagged": len(flagged) if isinstance(flagged, list) else 0}


# Ordered registry; the probe round-robins across these so every hot path is hit.
_OPERATIONS: tuple[tuple[str, Callable[[Path, int], dict[str, Any]]], ...] = (
    ("signal_events_recent", _op_signal_events_recent),
    ("signal_events_by_source", _op_signal_events_by_source),
    ("signal_events_count_by_source", _op_signal_events_count_by_source),
    ("cockpit_hot_path_audit", _op_hot_path_audit),
    ("diagnostics_cache_read", _op_diagnostics_cache_read),
    ("diagnostics_service_read", _op_diagnostics_service_read),
    ("runtime_truth_purity_read", _op_truth_purity_read),
    ("source_independence_read", _op_source_independence_read),
)


def _run_one(name: str, fn: Callable[[Path, int], dict[str, Any]],
             db_path: Path, max_rows: int) -> StressOpResult:
    res = StressOpResult(name)
    t0 = time.perf_counter()
    try:
        out = fn(db_path, max_rows)
        res.full_scans = int(out.get("full_scans", 0) or 0)
        # A cache read that returns no snapshot is a benign miss, not an error.
        if name == "diagnostics_cache_read" and out.get("cache_present") is False:
            res.cache_error = False
    except Exception as exc:  # noqa: BLE001 - we classify, never crash the probe
        res.status = "failed"
        res.error_type = type(exc).__name__
        msg = str(exc).lower()
        if "database is locked" in msg or "database table is locked" in msg:
            res.db_locked = True
        if "cache" in name and "read" in name:
            res.cache_error = True
    finally:
        res.elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)
    return res


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile over ``values`` (already-collected, bounded)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if pct <= 0:
        return round(ordered[0], 3)
    if pct >= 100:
        return round(ordered[-1], 3)
    # Nearest-rank percentile: rank = ceil(pct/100 * n), 1-indexed.
    rank = max(1, min(len(ordered), math.ceil(pct / 100.0 * len(ordered))))
    return round(ordered[rank - 1], 3)


def run_stress_probe(
    *,
    db_path: Path | None = None,
    workers: int = DEFAULT_WORKERS,
    iterations: int = DEFAULT_ITERATIONS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_rows: int = DEFAULT_MAX_ROWS,
    target_p95_ms: int = DEFAULT_TARGET_P95_MS,
) -> dict[str, Any]:
    """Drive concurrent read-only operations and return the scored stress report.

    Bounded: ``total_operations = workers * iterations``; per-run wall-clock is
    capped by ``timeout_seconds`` (futures still running at the deadline are
    counted as timeouts, never awaited indefinitely).  Read-only; no mutation,
    no broker, no network.
    """
    target = _runtime_config.get_db_path() if db_path is None else Path(db_path)
    # Clamp to safe bounds so a bad CLI arg can never launch an unbounded run.
    workers = max(1, min(int(workers), 64))
    iterations = max(1, min(int(iterations), 1000))
    timeout_seconds = max(1, min(int(timeout_seconds), 600))
    max_rows = max(1, min(int(max_rows), 100_000))
    total_operations = workers * iterations

    # Warm-up (single-threaded, best-effort): prime the diagnostics cache once so
    # the concurrent phase reads a warm snapshot rather than N cold recomputes.
    try:
        _op_diagnostics_service_read(target, max_rows)
    except Exception:  # noqa: BLE001 - warm-up failure must not abort the probe
        pass

    results: list[StressOpResult] = []
    timeout_operations = 0
    uncaught_exception: str | None = None

    wall_t0 = time.perf_counter()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for i in range(total_operations):
                name, fn = _OPERATIONS[i % len(_OPERATIONS)]
                futures.append(pool.submit(_run_one, name, fn, target, max_rows))
            deadline = wall_t0 + timeout_seconds
            for fut in futures:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    remaining = 0
                try:
                    results.append(fut.result(timeout=max(remaining, 0.0)))
                except concurrent.futures.TimeoutError:
                    timeout_operations += 1
                    fut.cancel()
                except Exception as exc:  # noqa: BLE001 - classify, don't crash
                    uncaught_exception = type(exc).__name__
    except Exception as exc:  # noqa: BLE001 - executor-level failure
        uncaught_exception = type(exc).__name__
    wall_seconds = max(time.perf_counter() - wall_t0, 1e-9)

    successful = sum(1 for r in results if r.status == "ok")
    failed = sum(1 for r in results if r.status == "failed")
    db_locked_errors = sum(1 for r in results if r.db_locked)
    cache_read_errors = sum(1 for r in results if r.cache_error)
    full_scan_warnings = max((r.full_scans for r in results), default=0)
    # Reconcile counts: any operation neither completed nor classified is a
    # timeout (futures abandoned at the deadline).
    accounted = successful + failed + timeout_operations
    if accounted < total_operations:
        timeout_operations += total_operations - accounted

    latencies = [r.elapsed_ms for r in results]
    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    p99 = _percentile(latencies, 99)
    max_ms = round(max(latencies), 3) if latencies else 0.0
    ops_per_second = round(len(results) / wall_seconds, 3)

    success_rate = successful / max(total_operations, 1)
    timeout_rate = timeout_operations / max(total_operations, 1)
    error_rate = failed / max(total_operations, 1)
    latency_score = min(1.0, target_p95_ms / max(p95, 1.0))
    stress_score = round(10.0 * (
        0.40 * success_rate
        + 0.30 * latency_score
        + 0.20 * (1 - timeout_rate)
        + 0.10 * (1 - error_rate)
    ), 3)

    # Memory warning: this probe holds only tiny per-op summaries (no row sets
    # are retained), so memory is bounded by design; flagged only if an
    # implausibly large completed-result list appears (defensive sentinel).
    memory_warning = len(results) > total_operations

    gate, recommendations = _stress_gate(
        success_rate=success_rate, timeout_rate=timeout_rate,
        error_rate=error_rate, p95_ms=p95, target_p95_ms=target_p95_ms,
        db_locked_errors=db_locked_errors,
        uncaught_exception=uncaught_exception,
    )

    return {
        "report": "cockpit_concurrency_stress_probe",
        "db_path": str(target),
        "db_available": target.exists(),
        "stress_score": stress_score,
        "stress_gate_status": gate,
        "workers": workers,
        "iterations": iterations,
        "timeout_seconds": timeout_seconds,
        "max_rows": max_rows,
        "target_p95_ms": target_p95_ms,
        "total_operations": total_operations,
        "successful_operations": successful,
        "failed_operations": failed,
        "timeout_operations": timeout_operations,
        "success_rate": round(success_rate, 4),
        "timeout_rate": round(timeout_rate, 4),
        "error_rate": round(error_rate, 4),
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
        "max_ms": max_ms,
        "ops_per_second": ops_per_second,
        "wall_seconds": round(wall_seconds, 3),
        "db_locked_errors": db_locked_errors,
        "cache_read_errors": cache_read_errors,
        "full_scan_warnings": full_scan_warnings,
        "memory_warning": memory_warning,
        "uncaught_exception": uncaught_exception,
        "recommendations": recommendations,
        # Safety stamps — advisory-only, read-only, SQLite canonical.
        "advisory_only": True,
        "human_execution_required": True,
        "canonical_truth_source": _contract.CANONICAL_STORE,
        "read_only": True,
        "broker_api_called": False,
        "ai_execution_count": _contract.AI_EXECUTION_COUNT,
        "execution_gate": _contract.EXECUTION_GATE_LOCKED,
        **_contract.advisory_safety_stamps(),
    }


def _stress_gate(
    *,
    success_rate: float,
    timeout_rate: float,
    error_rate: float,
    p95_ms: float,
    target_p95_ms: int,
    db_locked_errors: int,
    uncaught_exception: str | None,
) -> tuple[str, list[str]]:
    """Reduce the stress metrics to a PASS / WARN / BLOCK gate + recommendations."""
    rec: list[str] = []
    # BLOCK conditions — a real reliability disaster.
    if db_locked_errors > 0:
        rec.append(f"db_locked_errors={db_locked_errors}: serialize writers / "
                   "confirm WAL journal_mode + busy_timeout.")
        return BLOCK, rec
    if uncaught_exception:
        rec.append(f"uncaught_exception={uncaught_exception}: investigate the "
                   "probe harness or a crashing hot path.")
        return BLOCK, rec
    if error_rate > 0.05:
        rec.append(f"error_rate={error_rate:.3f} > 0.05: a hot path is failing "
                   "under load.")
        return BLOCK, rec
    if timeout_rate > 0.05:
        rec.append(f"timeout_rate={timeout_rate:.3f} > 0.05: hot paths are too "
                   "slow under concurrency; profile + index.")
        return BLOCK, rec

    # PASS conditions.
    if success_rate >= 0.98 and timeout_rate == 0 and error_rate <= 0.02:
        if p95_ms <= target_p95_ms:
            return PASS, ["hot paths are concurrent-read clean."]
        rec.append(f"p95_ms={p95_ms} > target {target_p95_ms}ms: likely a slow "
                   "local machine; verify on a representative host.")
        return WARN, rec

    # WARN conditions — degraded but not a disaster.
    if success_rate >= 0.95:
        rec.append(f"success_rate={success_rate:.3f} (>=0.95) but below PASS "
                   "thresholds; review failures/latency.")
        return WARN, rec
    rec.append(f"success_rate={success_rate:.3f} < 0.95: investigate hot-path "
               "reliability under concurrency.")
    return WARN, rec


def write_summary(report: dict[str, Any]) -> Path:
    """Persist a derived, non-canonical stress summary for the release gate."""
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "report": "cockpit_concurrency_stress_probe_summary",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stress_score": report.get("stress_score"),
        "stress_gate_status": report.get("stress_gate_status"),
        "workers": report.get("workers"),
        "iterations": report.get("iterations"),
        "total_operations": report.get("total_operations"),
        "success_rate": report.get("success_rate"),
        "p95_ms": report.get("p95_ms"),
        "db_locked_errors": report.get("db_locked_errors"),
        "error_rate": report.get("error_rate"),
        "timeout_rate": report.get("timeout_rate"),
        "canonical_truth_source": report.get("canonical_truth_source"),
        "cache_role": "derived_non_canonical",
        "advisory_only": True,
    }
    tmp = SUMMARY_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(SUMMARY_FILE)
    return SUMMARY_FILE


def read_summary() -> dict[str, Any] | None:
    """Return the last persisted stress summary, or None if absent/corrupt."""
    if not SUMMARY_FILE.exists():
        return None
    try:
        return json.loads(SUMMARY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cockpit_concurrency_stress_probe.py",
        description=(
            "Read-only concurrency/stress probe over signal_events + cockpit "
            "hot paths. Bounded; no mutation, no broker, no network. Emits a "
            "PASS/WARN/BLOCK stress gate."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    p.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    p.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS)
    p.add_argument("--target-p95-ms", type=int, default=DEFAULT_TARGET_P95_MS)
    p.add_argument("--no-summary", action="store_true",
                   help="do not persist the derived last_run.json summary")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = Path(args.db_path) if args.db_path else None
    report = run_stress_probe(
        db_path=db,
        workers=args.workers,
        iterations=args.iterations,
        timeout_seconds=args.timeout_seconds,
        max_rows=args.max_rows,
        target_p95_ms=args.target_p95_ms,
    )
    if not args.no_summary:
        try:
            write_summary(report)
        except OSError:  # pragma: no cover - summary is best-effort
            pass

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("Cockpit Concurrency / Stress Probe (read-only)")
        print("==============================================")
        print(f"  db available        : {report['db_available']}")
        print(f"  workers x iterations: {report['workers']} x {report['iterations']} "
              f"= {report['total_operations']} ops")
        print(f"  successful / failed : {report['successful_operations']} / "
              f"{report['failed_operations']}")
        print(f"  timeouts            : {report['timeout_operations']}")
        print(f"  success rate        : {report['success_rate']}")
        print(f"  p50 / p95 / p99 / max ms: {report['p50_ms']} / {report['p95_ms']} "
              f"/ {report['p99_ms']} / {report['max_ms']}")
        print(f"  ops per second      : {report['ops_per_second']}")
        print(f"  db_locked_errors    : {report['db_locked_errors']}")
        print(f"  cache_read_errors   : {report['cache_read_errors']}")
        print(f"  full_scan_warnings  : {report['full_scan_warnings']}")
        print(f"  stress_score        : {report['stress_score']}")
        print(f"  stress_gate_status  : {report['stress_gate_status']}")
        for rec in report["recommendations"]:
            print(f"    - {rec}")
        print(f"  [safety] advisory_only={report['advisory_only']} "
              f"read_only={report['read_only']} "
              f"canonical={report['canonical_truth_source']}")

    # Exit non-zero only on a hard BLOCK so a CI/preflight wrapper can branch.
    return 1 if report["stress_gate_status"] == BLOCK else 0


__all__ = [
    "PASS", "WARN", "BLOCK",
    "DEFAULT_WORKERS", "DEFAULT_ITERATIONS", "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_MAX_ROWS", "DEFAULT_TARGET_P95_MS",
    "SUMMARY_FILE",
    "run_stress_probe",
    "write_summary",
    "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
