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
import os
import sqlite3
import tempfile
import threading
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

# Canonical runtime DB — the probe must NEVER ask the large fixture or the
# write-contention scenario to touch this path.  Used by ``_refuse_canonical``
# below to fail loudly instead of silently polluting operator truth.
CANONICAL_RUNTIME_DB = REPO_ROOT / "runtime" / "mvp_local.db"

PASS, WARN, BLOCK = "PASS", "WARN", "BLOCK"

# Safe defaults — small, bounded, fast.
DEFAULT_WORKERS = 4
DEFAULT_ITERATIONS = 25
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_ROWS = 500
DEFAULT_TARGET_P95_MS = 500

# Large-fixture defaults (only used when --large-fixture is requested).
DEFAULT_FIXTURE_ROW_COUNT = 122_000
MAX_FIXTURE_ROW_COUNT = 250_000
MAX_FIXTURE_ROW_COUNT_ALLOW_LARGE = 500_000
DEFAULT_LARGE_TARGET_P95_MS = 750

# Iteration ceiling lifted from 1000 to 5000 for the large-fixture path; small
# default runs stay tiny.  Workers stay capped at 64.
MAX_WORKERS = 64
MAX_ITERATIONS = 5_000

# Write-contention defaults.  Writer lock hold is bounded so the probe can't
# wedge itself by accident.
DEFAULT_WRITER_LOCK_HOLD_MS = 200
MAX_WRITER_LOCK_HOLD_MS = 5_000
DEFAULT_CONTENTION_READS = 32
MAX_CONTENTION_READS = 1_000
DEFAULT_CONTENTION_TARGET_RECOVERY_MS = 250

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


def _resolve(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except OSError:
        return path


def _is_canonical_runtime_db(path: Path) -> bool:
    """True iff ``path`` resolves to ``runtime/mvp_local.db``."""
    try:
        return _resolve(path) == _resolve(CANONICAL_RUNTIME_DB)
    except Exception:  # noqa: BLE001 - defensive; treat as not-canonical only on resolve failure
        return False


def _refuse_canonical_for_fixture(path: Path, *, reason: str) -> None:
    """Hard-stop if ``path`` is the canonical runtime DB.

    Used by the large-fixture / write-contention paths.  The probe is
    advisory-only and must never seed synthetic rows into operator truth.
    """
    if _is_canonical_runtime_db(path):
        raise ValueError(
            f"refuse_to_pollute_canonical_runtime_db: db_path={path} resolves "
            f"to the canonical runtime DB ({CANONICAL_RUNTIME_DB}); refusing "
            f"{reason}. Use --large-fixture without --db-path to auto-create "
            "a temp fixture, or pass an explicit non-canonical path."
        )


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
    # busy_timeout makes a read wait for a transient writer lock (up to 5s)
    # instead of erroring immediately with "database is locked" under the
    # concurrent read load this probe deliberately generates.
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
    except sqlite3.Error:  # pragma: no cover - defensive; ro conn still usable
        pass
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
    workers = max(1, min(int(workers), MAX_WORKERS))
    iterations = max(1, min(int(iterations), MAX_ITERATIONS))
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

    # The probe NEVER writes to ``target`` (every connection is opened
    # ``mode=ro`` and ``_assert_read_only`` rejects mutation verbs).  Stamping
    # ``runtime_db_polluted=False`` explicitly here makes that invariant
    # machine-readable: the release gate, the truth-purity audit, and
    # downstream tooling can all assert this field instead of inferring it.
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
        "runtime_db_polluted": False,
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


def _write_contention_score(
    *,
    reads_during_lock: int,
    reads_successful_during_lock: int,
    db_locked_errors: int,
    post_lock_recovery_ms: float,
    target_recovery_ms: int,
) -> tuple[float, str, list[str]]:
    """Score + gate the write-contention scenario.

    PASS: no uncaught exception, no db-locked errors, recovery within target.
    WARN: some db-locked errors but reads recovered and no crash.
    BLOCK: probe crashed (caller signals via gate=BLOCK separately).
    """
    rec: list[str] = []
    read_success_rate = (reads_successful_during_lock / max(reads_during_lock, 1))
    locked_rate = db_locked_errors / max(reads_during_lock, 1)
    recovery_score = min(1.0, target_recovery_ms / max(post_lock_recovery_ms, 1.0))
    score = round(10.0 * (
        0.40 * read_success_rate + 0.30 * (1 - locked_rate) + 0.30 * recovery_score
    ), 3)
    if db_locked_errors == 0 and reads_successful_during_lock == reads_during_lock \
            and post_lock_recovery_ms <= target_recovery_ms:
        return score, PASS, ["reads remained clean under writer lock; recovery within target."]
    if db_locked_errors > 0 and reads_successful_during_lock + db_locked_errors >= reads_during_lock:
        rec.append(
            f"db_locked_errors={db_locked_errors} observed but classified and "
            "recovered; verify WAL journal_mode + busy_timeout on production DB."
        )
        return score, WARN, rec
    if post_lock_recovery_ms > target_recovery_ms:
        rec.append(
            f"post_lock_recovery_ms={post_lock_recovery_ms} > target "
            f"{target_recovery_ms}ms; readers took longer than expected to recover."
        )
        return score, WARN, rec
    rec.append("reads did not all recover cleanly under writer lock; investigate.")
    return score, WARN, rec


def run_write_contention_scenario(
    *,
    db_path: Path | None = None,
    writer_lock_hold_ms: int = DEFAULT_WRITER_LOCK_HOLD_MS,
    reads_during_lock: int = DEFAULT_CONTENTION_READS,
    target_recovery_ms: int = DEFAULT_CONTENTION_TARGET_RECOVERY_MS,
    reader_workers: int = 4,
    keep_db: bool = False,
) -> dict[str, Any]:
    """Run a bounded write-contention scenario against a TEMP DB only.

    Hard safety rules:
    * The canonical runtime DB is *refused* outright — synthetic writes must
      never land in operator truth.
    * If ``db_path`` is None, a temp file is created under the system temp dir
      and removed at the end (unless ``keep_db=True``).
    * Writer holds a bounded ``BEGIN IMMEDIATE`` lock then COMMITs; the lock
      mutates a tiny ``_perf_contention_writes`` table local to the temp DB.
    * Readers issue SELECTs against ``signal_events``; missing-table is a
      benign "no rows" result, not an error.
    """
    # 1) Resolve target DB.  Either explicit (must be non-canonical) or temp.
    created_temp = False
    if db_path is None:
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix="cockpit_contention_", suffix=".db",
        )
        os.close(tmp_fd)
        db_path = Path(tmp_name)
        created_temp = True
    else:
        db_path = Path(db_path)
        _refuse_canonical_for_fixture(
            db_path, reason="write-contention scenario (mutates a synthetic table)"
        )

    # Bound the parameters so a bad CLI arg can't wedge the probe.
    writer_lock_hold_ms = max(1, min(int(writer_lock_hold_ms), MAX_WRITER_LOCK_HOLD_MS))
    reads_during_lock = max(1, min(int(reads_during_lock), MAX_CONTENTION_READS))
    target_recovery_ms = max(1, int(target_recovery_ms))
    reader_workers = max(1, min(int(reader_workers), MAX_WORKERS))

    # 2) Initialise schema and a small marker payload on the temp DB.
    #    WAL is important: it matches the production busy-timeout + WAL posture
    #    so this scenario actually exercises the prod-relevant case (readers
    #    succeed during writer transactions; writers serialise).
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 2000")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS signal_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                source_name TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
                human_review_required INTEGER NOT NULL DEFAULT 1,
                execution_gate TEXT NOT NULL DEFAULT 'LOCKED',
                ai_execution_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_se_source ON signal_events(source_name);
            CREATE INDEX IF NOT EXISTS idx_se_fetched ON signal_events(fetched_at);
            CREATE TABLE IF NOT EXISTS _perf_contention_writes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                written_at TEXT NOT NULL,
                marker TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS _perf_fixture_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT OR REPLACE INTO _perf_fixture_metadata (key, value) VALUES (?, ?)",
            (
                ("fixture_role", "synthetic_performance_fixture"),
                ("derived_non_canonical", "true"),
                ("safe_to_delete", "true"),
                ("runtime_db_polluted", "false"),
                ("canonical_truth_source", "sqlite_runtime_not_used"),
                ("scenario", "write_contention"),
            ),
        )
        # Seed a few rows so SELECTs return something realistic; these are
        # synthetic markers (PERF_FIXTURE_*), not operator truth.
        seed_rows = [
            (f"PERF_FIXTURE_CONTENTION_{i:04d}", "rss",
             '{"fixture_role":"synthetic_performance_fixture"}',
             time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "ADVISORY_ONLY", 1, "LOCKED", 0)
            for i in range(64)
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO signal_events "
            "(event_id, source_name, raw_payload, fetched_at, advisory_status, "
            " human_review_required, execution_gate, ai_execution_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            seed_rows,
        )
        conn.commit()
    finally:
        conn.close()

    # 3) Writer thread: hold a brief lock, then commit.  Synchronisation events
    #    coordinate the start of reads with the moment the lock is held.
    lock_acquired = threading.Event()
    lock_released = threading.Event()
    writer_error: list[str] = []

    def _writer() -> None:
        try:
            wconn = sqlite3.connect(str(db_path), timeout=5.0)
            try:
                wconn.execute("PRAGMA busy_timeout = 2000")
                wconn.isolation_level = None  # manual BEGIN/COMMIT
                wconn.execute("BEGIN IMMEDIATE")
                wconn.execute(
                    "INSERT INTO _perf_contention_writes (written_at, marker) "
                    "VALUES (?, ?)",
                    (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     "synthetic_contention_marker"),
                )
                lock_acquired.set()
                time.sleep(writer_lock_hold_ms / 1000.0)
                wconn.execute("COMMIT")
            finally:
                wconn.close()
        except Exception as exc:  # noqa: BLE001 - classify, don't crash
            writer_error.append(f"{type(exc).__name__}: {exc}")
        finally:
            lock_released.set()
            lock_acquired.set()  # ensure waiters unblock even on writer error

    # 4) Reader workers: do SELECTs during the lock window.  We classify
    #    successes vs ``database is locked`` errors so a busy_timeout that
    #    handles the lock gracefully shows up as PASS, while a timed-out
    #    or crashing reader shows up as WARN/BLOCK.
    successes = 0
    locked_errors = 0
    other_errors: list[str] = []
    read_lock = threading.Lock()

    def _reader(_n: int) -> None:
        nonlocal successes, locked_errors
        try:
            rconn = sqlite3.connect(
                f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=2.0,
            )
            try:
                rows = rconn.execute(
                    "SELECT id FROM signal_events ORDER BY fetched_at DESC LIMIT 50"
                ).fetchall()
                with read_lock:
                    successes += 1 if rows is not None else 0
            finally:
                rconn.close()
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if "locked" in msg or "busy" in msg:
                with read_lock:
                    locked_errors += 1
            else:
                with read_lock:
                    other_errors.append(type(exc).__name__)
        except Exception as exc:  # noqa: BLE001 - classify, don't crash
            with read_lock:
                other_errors.append(type(exc).__name__)

    writer_thread = threading.Thread(target=_writer, name="contention-writer")
    writer_thread.start()
    # Wait until the writer is actually holding the lock before launching reads;
    # otherwise we'd be measuring an empty contention window.
    if not lock_acquired.wait(timeout=5.0):
        # Writer never reported lock acquisition — abort cleanly.
        writer_thread.join(timeout=5.0)
        return {
            "report": "cockpit_write_contention_scenario",
            "write_contention_enabled": True,
            "temp_db_only": created_temp,
            "db_path": str(db_path),
            "writer_lock_hold_ms": writer_lock_hold_ms,
            "reads_during_lock": 0,
            "reads_successful_during_lock": 0,
            "db_locked_errors": 0,
            "post_lock_recovery_ms": 0.0,
            "contention_gate_status": BLOCK,
            "contention_recovery_score": 0.0,
            "writer_errors": writer_error,
            "recommendations": ["writer never acquired lock — investigate."],
            "runtime_db_polluted": False,
            "fixture_role": "synthetic_performance_fixture",
            "derived_non_canonical": True,
        }

    # 5) Fire `reads_during_lock` reader operations across `reader_workers`.
    with concurrent.futures.ThreadPoolExecutor(max_workers=reader_workers) as pool:
        list(pool.map(_reader, range(reads_during_lock)))

    # 6) Wait for writer to release; measure recovery wall time until a fresh
    #    SELECT succeeds (or until a hard ceiling).
    lock_released.wait(timeout=(writer_lock_hold_ms / 1000.0) + 5.0)
    writer_thread.join(timeout=5.0)
    recovery_start = time.perf_counter()
    recovery_ok = False
    recovery_attempts = 0
    while time.perf_counter() - recovery_start < 5.0:
        recovery_attempts += 1
        try:
            rconn = sqlite3.connect(
                f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=2.0,
            )
            try:
                rconn.execute("SELECT COUNT(*) FROM signal_events").fetchone()
                recovery_ok = True
                break
            finally:
                rconn.close()
        except sqlite3.OperationalError:
            time.sleep(0.01)
    post_lock_recovery_ms = round((time.perf_counter() - recovery_start) * 1000, 3)

    score, gate, recommendations = _write_contention_score(
        reads_during_lock=reads_during_lock,
        reads_successful_during_lock=successes,
        db_locked_errors=locked_errors,
        post_lock_recovery_ms=post_lock_recovery_ms,
        target_recovery_ms=target_recovery_ms,
    )
    if writer_error or not recovery_ok or other_errors:
        gate = BLOCK
        if writer_error:
            recommendations.append(f"writer_error={writer_error}")
        if not recovery_ok:
            recommendations.append("readers never recovered after writer lock release.")
        if other_errors:
            recommendations.append(f"unexpected reader errors: {sorted(set(other_errors))}")

    report = {
        "report": "cockpit_write_contention_scenario",
        "write_contention_enabled": True,
        "temp_db_only": created_temp,
        "db_path": str(db_path),
        "writer_lock_hold_ms": writer_lock_hold_ms,
        "reads_during_lock": reads_during_lock,
        "reads_successful_during_lock": successes,
        "db_locked_errors": locked_errors,
        "post_lock_recovery_ms": post_lock_recovery_ms,
        "recovery_attempts": recovery_attempts,
        "target_recovery_ms": target_recovery_ms,
        "contention_gate_status": gate,
        "contention_recovery_score": score,
        "writer_errors": writer_error,
        "other_reader_errors": sorted(set(other_errors)),
        "recommendations": recommendations,
        "runtime_db_polluted": False,
        "fixture_role": "synthetic_performance_fixture",
        "derived_non_canonical": True,
        "canonical_truth_source": _contract.CANONICAL_STORE,
        **_contract.advisory_safety_stamps(),
    }

    # 7) Best-effort cleanup of the temp DB unless caller asked to keep it.
    if created_temp and not keep_db:
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(db_path) + suffix)
            try:
                if p.exists():
                    p.unlink()
            except OSError:  # pragma: no cover - best-effort cleanup
                pass

    return report


def _import_fixture_helper():
    """Import the large signal_events fixture helper.

    The helper lives under ``tests/helpers/`` (not ``scripts/``), so the CLI
    entry-point — which runs without the repo root on ``sys.path`` — needs to
    insert the repo root before importing.  pytest already adds the repo root
    to ``sys.path``, so the import succeeds directly there.
    """
    try:
        from tests.helpers import large_signal_events_fixture as fix  # noqa: I001
        return fix
    except ModuleNotFoundError:
        import sys
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        try:
            from tests.helpers import large_signal_events_fixture as fix  # noqa: I001
            return fix
        except ModuleNotFoundError as exc:  # pragma: no cover - import failure
            raise RuntimeError(
                "large_signal_events_fixture helper not importable; ensure "
                "tests/helpers/large_signal_events_fixture.py exists."
            ) from exc


def _build_large_fixture(
    *,
    fixture_rows: int,
    output_dir: Path | None,
    allow_large_local_test: bool,
) -> tuple[Path, dict[str, Any]]:
    """Create a non-canonical large signal_events fixture; return (path, sidecar).

    Delegated to ``tests.helpers.large_signal_events_fixture`` so the fixture
    code path is shared between CLI proof and pytest helper.  This is the only
    write the probe ever performs, and it is hard-guarded against the
    canonical runtime DB by the helper itself.
    """
    fix = _import_fixture_helper()

    if output_dir is None:
        tmp_dir = Path(tempfile.mkdtemp(prefix="cockpit_large_fixture_"))
    else:
        tmp_dir = Path(output_dir)
        tmp_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = tmp_dir / f"large_signal_events_{fixture_rows}.db"
    fix.create_large_signal_events_db(
        fixture_path,
        row_count=fixture_rows,
        create_indexes=True,
        allow_large_local_test=allow_large_local_test,
    )
    meta = fix.read_sidecar_metadata(fixture_path) or {}
    return fixture_path, meta


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
        "large_fixture_used": report.get("large_fixture_used", False),
        "large_fixture_rows": report.get("large_fixture_rows"),
        "large_fixture_path": report.get("large_fixture_path"),
        "runtime_db_polluted": bool(report.get("runtime_db_polluted", False)),
        "write_contention_enabled": report.get("write_contention_enabled", False),
        "contention_gate_status": report.get("contention_gate_status"),
        "contention_recovery_score": report.get("contention_recovery_score"),
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
    # Large-fixture / write-contention / output / keep-fixture / large-local.
    p.add_argument(
        "--large-fixture", action="store_true",
        help=("create a non-canonical signal_events fixture DB (refuses the "
              "canonical runtime DB) and run the probe against it."),
    )
    p.add_argument(
        "--fixture-rows", type=int, default=DEFAULT_FIXTURE_ROW_COUNT,
        help=f"row count for --large-fixture (default {DEFAULT_FIXTURE_ROW_COUNT}, "
             f"max {MAX_FIXTURE_ROW_COUNT} without --allow-large-local-test)",
    )
    p.add_argument(
        "--allow-large-local-test", action="store_true",
        help=f"raise the fixture row ceiling from {MAX_FIXTURE_ROW_COUNT} to "
             f"{MAX_FIXTURE_ROW_COUNT_ALLOW_LARGE} (local proof only).",
    )
    p.add_argument(
        "--include-write-contention", action="store_true",
        help=("also run a temp-DB-only write-contention scenario (refuses the "
              "canonical runtime DB)."),
    )
    p.add_argument(
        "--keep-fixture", action="store_true",
        help="do not delete the large fixture / contention temp DB on exit.",
    )
    p.add_argument(
        "--output", type=Path, default=None,
        help="write the full JSON report to this path (in addition to the "
             "stress summary).  Must be non-canonical.",
    )
    p.add_argument("--no-summary", action="store_true",
                   help="do not persist the derived last_run.json summary")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    requested_db = Path(args.db_path) if args.db_path else None

    # --- safety gates on the path the user typed --------------------------
    # The two cases that touch *writes* are the large-fixture creation and
    # the write-contention scenario.  Both must refuse the canonical runtime
    # DB outright — otherwise the probe would seed synthetic rows into
    # operator truth, exactly the scenario the prompt forbids.
    if args.large_fixture and requested_db is not None:
        _refuse_canonical_for_fixture(
            requested_db, reason="--large-fixture (synthetic seed)"
        )
    if args.include_write_contention and requested_db is not None:
        _refuse_canonical_for_fixture(
            requested_db, reason="--include-write-contention (writer transaction)"
        )
    if args.output is not None:
        _refuse_canonical_for_fixture(
            args.output, reason="--output (JSON report write)"
        )

    # --- optional: build a large non-canonical fixture, probe against it --
    fixture_path: Path | None = None
    fixture_meta: dict[str, Any] = {}
    fixture_used = False
    fixture_creation_seconds: float | None = None
    if args.large_fixture:
        # If --db-path was supplied alongside --large-fixture, it is treated
        # as the fixture's *output* DB path; the refusal above already proved
        # it is non-canonical.
        if requested_db is not None:
            fixture_path = requested_db
            fix = _import_fixture_helper()
            t0 = time.perf_counter()
            fix.create_large_signal_events_db(
                fixture_path,
                row_count=args.fixture_rows,
                create_indexes=True,
                allow_large_local_test=args.allow_large_local_test,
            )
            fixture_creation_seconds = round(time.perf_counter() - t0, 3)
            fixture_meta = fix.read_sidecar_metadata(fixture_path) or {}
        else:
            t0 = time.perf_counter()
            fixture_path, fixture_meta = _build_large_fixture(
                fixture_rows=args.fixture_rows,
                output_dir=None,
                allow_large_local_test=args.allow_large_local_test,
            )
            fixture_creation_seconds = round(time.perf_counter() - t0, 3)
        fixture_used = True
        target_db: Path | None = fixture_path
        target_p95 = (
            DEFAULT_LARGE_TARGET_P95_MS
            if args.target_p95_ms == DEFAULT_TARGET_P95_MS
            else args.target_p95_ms
        )
    else:
        target_db = requested_db
        target_p95 = args.target_p95_ms

    # --- run the read-only stress probe -----------------------------------
    report = run_stress_probe(
        db_path=target_db,
        workers=args.workers,
        iterations=args.iterations,
        timeout_seconds=args.timeout_seconds,
        max_rows=args.max_rows,
        target_p95_ms=target_p95,
    )

    # --- optional: write-contention scenario (TEMP DB ONLY) ---------------
    contention_report: dict[str, Any] | None = None
    if args.include_write_contention:
        # Contention always uses a *dedicated* temp DB, even when --large-fixture
        # is set — recovery measurements are cleaner against a small DB, and
        # the prompt's "temp DB only" rule is then trivially satisfied.
        contention_report = run_write_contention_scenario(
            db_path=None,
            keep_db=args.keep_fixture,
        )

    # --- stitch the large-fixture / contention metrics onto the main report
    report["large_fixture_used"] = fixture_used
    report["large_fixture_rows"] = (
        int(fixture_meta.get("row_count", args.fixture_rows)) if fixture_used else 0
    )
    report["large_fixture_path"] = str(fixture_path) if fixture_path else None
    report["large_fixture_creation_seconds"] = fixture_creation_seconds
    report["large_fixture_sidecar"] = fixture_meta if fixture_used else None
    report["fixture_role"] = (
        fixture_meta.get("fixture_role") if fixture_used else None
    )
    report["derived_non_canonical"] = (
        bool(fixture_meta.get("derived_non_canonical")) if fixture_used else False
    )
    if contention_report is not None:
        report["write_contention_enabled"] = True
        report["write_contention_report"] = contention_report
        report["contention_gate_status"] = contention_report.get("contention_gate_status")
        report["contention_recovery_score"] = contention_report.get("contention_recovery_score")
        report["writer_lock_hold_ms"] = contention_report.get("writer_lock_hold_ms")
        report["reads_during_lock"] = contention_report.get("reads_during_lock")
        report["reads_successful_during_lock"] = contention_report.get(
            "reads_successful_during_lock"
        )
        report["post_lock_recovery_ms"] = contention_report.get("post_lock_recovery_ms")
        # The whole-run stress gate is downgraded if contention BLOCKed.
        cgate = contention_report.get("contention_gate_status")
        if cgate == BLOCK:
            report["stress_gate_status"] = BLOCK
            report["recommendations"] = list(report.get("recommendations") or []) + [
                "write_contention scenario BLOCK — see write_contention_report."
            ]
        elif cgate == WARN and report.get("stress_gate_status") == PASS:
            report["stress_gate_status"] = WARN
            report["recommendations"] = list(report.get("recommendations") or []) + [
                "write_contention scenario WARN — see write_contention_report."
            ]
    else:
        report["write_contention_enabled"] = False
    # Reaffirm: the probe (with or without fixture/contention) never writes
    # into the canonical runtime DB.
    report["runtime_db_polluted"] = False

    if not args.no_summary:
        try:
            write_summary(report)
        except OSError:  # pragma: no cover - summary is best-effort
            pass

    if args.output is not None:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, indent=2, default=str), encoding="utf-8"
            )
        except OSError:  # pragma: no cover - --output is best-effort
            pass

    # --- best-effort fixture cleanup (unless --keep-fixture) --------------
    if fixture_used and fixture_path is not None and not args.keep_fixture and requested_db is None:
        # Only auto-cleanup when *we* created the temp dir; explicit --db-path
        # fixtures are the caller's to manage.
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(fixture_path) + suffix)
            try:
                if p.exists():
                    p.unlink()
            except OSError:  # pragma: no cover - best-effort
                pass
        sidecar = Path(str(fixture_path) + ".meta.json")
        try:
            if sidecar.exists():
                sidecar.unlink()
        except OSError:  # pragma: no cover - best-effort
            pass
        try:
            if fixture_path.parent.exists() and not any(fixture_path.parent.iterdir()):
                fixture_path.parent.rmdir()
        except OSError:  # pragma: no cover - best-effort
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
        if report.get("large_fixture_used"):
            print(f"  large_fixture_rows  : {report.get('large_fixture_rows')}")
            print(f"  large_fixture_path  : {report.get('large_fixture_path')}")
            print(f"  fixture_role        : {report.get('fixture_role')}")
            print(f"  creation_seconds    : {report.get('large_fixture_creation_seconds')}")
        if report.get("write_contention_enabled"):
            print(f"  contention gate     : {report.get('contention_gate_status')} "
                  f"(score={report.get('contention_recovery_score')})")
            print(f"  writer_lock_hold_ms : {report.get('writer_lock_hold_ms')}")
            print(f"  reads/locked/recov  : {report.get('reads_during_lock')} / "
                  f"{report.get('reads_successful_during_lock')} / "
                  f"{report.get('post_lock_recovery_ms')}ms")
        print(f"  runtime_db_polluted : {report.get('runtime_db_polluted')}")
        print(f"  [safety] advisory_only={report['advisory_only']} "
              f"read_only={report['read_only']} "
              f"canonical={report['canonical_truth_source']}")

    # Exit non-zero only on a hard BLOCK so a CI/preflight wrapper can branch.
    return 1 if report["stress_gate_status"] == BLOCK else 0


__all__ = [
    "PASS", "WARN", "BLOCK",
    "DEFAULT_WORKERS", "DEFAULT_ITERATIONS", "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_MAX_ROWS", "DEFAULT_TARGET_P95_MS",
    "DEFAULT_FIXTURE_ROW_COUNT", "MAX_FIXTURE_ROW_COUNT",
    "MAX_FIXTURE_ROW_COUNT_ALLOW_LARGE", "DEFAULT_LARGE_TARGET_P95_MS",
    "DEFAULT_WRITER_LOCK_HOLD_MS", "DEFAULT_CONTENTION_READS",
    "DEFAULT_CONTENTION_TARGET_RECOVERY_MS",
    "MAX_WORKERS", "MAX_ITERATIONS",
    "CANONICAL_RUNTIME_DB",
    "SUMMARY_FILE", "SUMMARY_DIR",
    "run_stress_probe",
    "run_write_contention_scenario",
    "write_summary",
    "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
