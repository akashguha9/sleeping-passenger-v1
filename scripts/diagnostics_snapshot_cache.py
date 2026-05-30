"""Read-only-safe diagnostics snapshot cache (Enforcement/Scalability Sprint — Task 1D).

Heavy advisory diagnostics (truth-purity, broken-windows, closed-loop,
defensive-alpha, source-independence) are correct but recomputing them on every
cockpit/API hit is wasteful.  This module runs them **once**, stores a JSON
snapshot under ``runtime/diagnostics_cache/`` with a TTL and the DB mtime it was
built against, and lets callers reuse a *valid* snapshot instead of recomputing.

Hard invariants
---------------
* The cache is **derived, never canonical**.  Every snapshot is stamped
  ``canonical_truth_source = "sqlite"`` and ``cache_role = "derived_non_canonical"``.
  SQLite remains the single source of truth; this file is a disposable mirror.
* A subreport that *fails* is recorded as ``status = "DEGRADED"`` with its
  ``error_type`` and a ``recovery_command`` — it is **never** silently replaced
  with fake zeros that would read as "clean".
* Read-only with respect to the runtime DB.  No broker calls, no execution, no
  AI execution.  Writing the cache file is the only side effect.

The cache deliberately stores raw subreport payloads and a per-subreport
``status`` of either ``OK`` (built successfully) or ``DEGRADED`` (raised).  The
*semantic* CLEAN/WARN/BLOCK taxonomy is layered on top by
:mod:`scripts.diagnostics_service`, which keeps this module dumb about meaning.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import threading
import time
from datetime import datetime, timezone
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
CACHE_DIR = REPO_ROOT / "runtime" / "diagnostics_cache"
CACHE_FILE = CACHE_DIR / "diagnostics_snapshot.json"
DEFAULT_TTL_SECONDS = 300

CANONICAL_TRUTH_SOURCE = "sqlite"
CACHE_ROLE = "derived_non_canonical"

# Serializes the final atomic replace of the single shared cache file. Two
# threads writing concurrently (e.g. the cockpit concurrency stress probe
# driving many readers while one recomputes a cold cache) must not collide on
# the destination — on Windows ``os.replace`` into an open/locked file raises
# PermissionError. Each writer stages to its OWN unique temp file (so the
# staging writes never clash), then this lock serializes the rename so the
# replace itself is always single-writer. The cache stays atomic and
# derived/non-canonical.
_WRITE_LOCK = threading.Lock()
_TMP_SEQ = 0

# (subreport_name, module, build_function, recovery_command).  Each builder
# accepts a single ``db_path`` argument and returns a dict.
_HEAVY_DIAGNOSTICS: tuple[tuple[str, str, str, str], ...] = (
    ("truth_purity", "runtime_truth_purity_audit", "build_audit",
     "python scripts/runtime_truth_purity_audit.py"),
    ("broken_windows", "broken_windows_report", "build_report",
     "python scripts/broken_windows_report.py"),
    ("closed_loop", "closed_loop_learning_audit", "build_audit",
     "python scripts/closed_loop_learning_audit.py"),
    ("defensive_alpha", "defensive_alpha_report", "build_report",
     "python scripts/defensive_alpha_report.py"),
    ("source_independence", "source_independence_audit", "build_report",
     "python scripts/source_independence_audit.py"),
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: datetime | None = None) -> str:
    return (dt or _now_utc()).strftime("%Y-%m-%dT%H:%M:%SZ")


def cache_path() -> Path:
    return CACHE_FILE


def resolve_db_path(db_path: Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    return _runtime_config.get_db_path()


def db_mtime(db_path: Path | None = None) -> float | None:
    """Return the runtime DB file mtime, or ``None`` if it does not exist."""
    target = resolve_db_path(db_path)
    try:
        if target.exists():
            return target.stat().st_mtime
    except OSError:
        return None
    return None


def _import_builder(module_name: str, func_name: str) -> Callable[..., Any]:
    """Import ``scripts.<module>`` (with bare-module fallback) and return func."""
    try:
        module = importlib.import_module(f"scripts.{module_name}")
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        module = importlib.import_module(module_name)
    return getattr(module, func_name)


def collect_subreports(db_path: Path | None = None) -> dict[str, Any]:
    """Run every heavy diagnostic once, isolating per-subreport failures.

    A builder that raises is recorded as ``status = "DEGRADED"`` with its
    ``error_type`` and ``recovery_command`` — never as fake-clean zeros.
    """
    target = resolve_db_path(db_path)
    subreports: dict[str, Any] = {}
    for name, module_name, func_name, recovery in _HEAVY_DIAGNOSTICS:
        t0 = time.perf_counter()
        try:
            builder = _import_builder(module_name, func_name)
            # Every heavy diagnostic accepts the runtime DB as a ``db_path``
            # keyword (``source_independence`` takes it keyword-only), so call
            # by keyword uniformly rather than guessing positional arity.
            data = builder(db_path=target)
            subreports[name] = {
                "status": "OK",
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 3),
                "data": data,
            }
        except Exception as exc:  # noqa: BLE001 - we must not crash the cache
            subreports[name] = {
                "status": "DEGRADED",
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 3),
                "error_type": type(exc).__name__,
                "error_detail": str(exc)[:300],
                "recovery_command": recovery,
                "data": None,
            }
    return subreports


def build_snapshot(
    db_path: Path | None = None,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    collector: Callable[[Path | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a fresh snapshot payload (does not write it to disk)."""
    target = resolve_db_path(db_path)
    collect = collector or collect_subreports
    generated = _now_utc()
    snapshot: dict[str, Any] = {
        "report": "diagnostics_snapshot_cache",
        "generated_at_utc": _utc_iso(generated),
        "generated_at_epoch": generated.timestamp(),
        "ttl_seconds": int(ttl_seconds),
        "db_path": str(target),
        "db_available": target.exists(),
        "snapshot_db_mtime": db_mtime(target),
        "canonical_truth_source": CANONICAL_TRUTH_SOURCE,
        "cache_role": CACHE_ROLE,
        "subreports": collect(target),
        **_contract.advisory_safety_stamps(),
    }
    snapshot["degraded_subreports"] = sorted(
        name for name, sub in snapshot["subreports"].items()
        if sub.get("status") == "DEGRADED"
    )
    return snapshot


def write_snapshot(snapshot: dict[str, Any]) -> Path:
    """Persist ``snapshot`` to the cache file (atomically, concurrency-safe).

    Each caller stages to a UNIQUE temp file (pid + thread id + sequence) so
    concurrent writers never overwrite each other's staging file, then the
    final rename is serialized under ``_WRITE_LOCK`` with a small bounded retry
    so a transient Windows file-lock on the destination does not raise. The
    rename remains atomic, so a reader always sees a whole snapshot.
    """
    global _TMP_SEQ
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        _TMP_SEQ += 1
        seq = _TMP_SEQ
    tmp = CACHE_FILE.with_name(
        f"{CACHE_FILE.stem}.{os.getpid()}.{threading.get_ident()}.{seq}.json.tmp"
    )
    tmp.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
    try:
        with _WRITE_LOCK:
            last_exc: OSError | None = None
            for attempt in range(5):
                try:
                    os.replace(tmp, CACHE_FILE)
                    last_exc = None
                    break
                except PermissionError as exc:  # pragma: no cover - timing-dependent
                    last_exc = exc
                    time.sleep(0.02 * (attempt + 1))
            if last_exc is not None:
                raise last_exc
    finally:
        # Best-effort cleanup if our staging file survived (e.g. replace failed).
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:  # pragma: no cover - best-effort
            pass
    return CACHE_FILE


def read_snapshot() -> dict[str, Any] | None:
    """Return the persisted snapshot, or ``None`` if absent/corrupt."""
    if not CACHE_FILE.exists():
        return None
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def cache_validity(
    snapshot: dict[str, Any] | None,
    db_path: Path | None = None,
    *,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """Evaluate whether ``snapshot`` is still usable.

    Valid iff ``(now - generated_at) <= ttl`` **and** the runtime DB has not
    been modified since the snapshot was built.  A corrupt cache invalidates
    safely rather than raising.
    """
    now = now_epoch if now_epoch is not None else time.time()
    if not snapshot:
        return {"valid": False, "reason": "no_snapshot", "age_seconds": None}
    if snapshot.get("cache_role") != CACHE_ROLE:
        return {"valid": False, "reason": "not_a_diagnostics_cache", "age_seconds": None}

    generated_epoch = snapshot.get("generated_at_epoch")
    ttl = int(snapshot.get("ttl_seconds", DEFAULT_TTL_SECONDS))
    age = None
    if isinstance(generated_epoch, (int, float)):
        age = now - float(generated_epoch)
        if age > ttl:
            return {"valid": False, "reason": "ttl_expired",
                    "age_seconds": round(age, 3), "ttl_seconds": ttl}
    else:
        return {"valid": False, "reason": "missing_timestamp", "age_seconds": None}

    snap_mtime = snapshot.get("snapshot_db_mtime")
    cur_mtime = db_mtime(db_path)
    if (isinstance(snap_mtime, (int, float)) and isinstance(cur_mtime, (int, float))
            and cur_mtime > snap_mtime):
        return {"valid": False, "reason": "db_changed",
                "age_seconds": round(age, 3) if age is not None else None}

    return {"valid": True, "reason": "fresh",
            "age_seconds": round(age, 3) if age is not None else None,
            "ttl_seconds": ttl}


def refresh(
    db_path: Path | None = None,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    collector: Callable[[Path | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a fresh snapshot and persist it."""
    snapshot = build_snapshot(db_path, ttl_seconds=ttl_seconds, collector=collector)
    write_snapshot(snapshot)
    return snapshot


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="diagnostics_snapshot_cache.py",
        description=(
            "Derived, non-canonical diagnostics snapshot cache. Read-only "
            "w.r.t. the runtime DB; no broker calls; no execution."
        ),
    )
    p.add_argument("--refresh", action="store_true",
                   help="recompute heavy diagnostics and rewrite the snapshot")
    p.add_argument("--read", action="store_true",
                   help="print the persisted snapshot and its validity")
    p.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS,
                   help=f"snapshot TTL in seconds (default {DEFAULT_TTL_SECONDS})")
    p.add_argument("--json", action="store_true", help="emit JSON")
    return p


def _print_human(snapshot: dict[str, Any], validity: dict[str, Any]) -> None:
    print("Diagnostics Snapshot Cache (derived / non-canonical)")
    print("====================================================")
    print(f"  canonical truth source : {snapshot.get('canonical_truth_source')}")
    print(f"  cache role             : {snapshot.get('cache_role')}")
    print(f"  generated at (utc)     : {snapshot.get('generated_at_utc')}")
    print(f"  ttl seconds            : {snapshot.get('ttl_seconds')}")
    print(f"  valid                  : {validity.get('valid')} ({validity.get('reason')})")
    print(f"  age seconds            : {validity.get('age_seconds')}")
    subs = snapshot.get("subreports", {})
    for name, sub in subs.items():
        marker = "OK " if sub.get("status") == "OK" else "DEG"
        print(f"  [{marker}] {name:<20} {sub.get('elapsed_ms')}ms")
    degraded = snapshot.get("degraded_subreports", [])
    if degraded:
        print(f"  DEGRADED subreports    : {degraded}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.refresh:
        snapshot = refresh(ttl_seconds=args.ttl)
        validity = cache_validity(snapshot)
    else:
        snapshot = read_snapshot()
        if snapshot is None and not args.read:
            # Default behaviour with no flags: build a fresh snapshot.
            snapshot = refresh(ttl_seconds=args.ttl)
        validity = cache_validity(snapshot)

    if snapshot is None:
        msg = {"report": "diagnostics_snapshot_cache", "snapshot": None,
               "validity": validity}
        if args.json:
            print(json.dumps(msg, indent=2, default=str))
        else:
            print("No diagnostics snapshot present. Run with --refresh.")
        return 1

    if args.json:
        print(json.dumps({"snapshot": snapshot, "validity": validity},
                         indent=2, default=str))
    else:
        _print_human(snapshot, validity)
    return 0


__all__ = [
    "CACHE_DIR",
    "CACHE_FILE",
    "DEFAULT_TTL_SECONDS",
    "CANONICAL_TRUTH_SOURCE",
    "CACHE_ROLE",
    "cache_path",
    "resolve_db_path",
    "db_mtime",
    "collect_subreports",
    "build_snapshot",
    "write_snapshot",
    "read_snapshot",
    "cache_validity",
    "refresh",
]


if __name__ == "__main__":
    raise SystemExit(main())
