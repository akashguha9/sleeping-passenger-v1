"""Background diagnostics snapshot warmer (Kanté Defensive Sprint — Task 1).

The cockpit / API read the derived diagnostics snapshot via
:mod:`scripts.diagnostics_service`.  On a cache *miss* the heavy audits are
recomputed synchronously on the request thread — a latency cliff.  This local
operator utility *warms* the cache ahead of time so a miss is the exception, not
the request-path default.

What it is (and is not)
-----------------------
* A **local script**, not a Windows service / daemon.  ``--loop`` is a simple
  foreground loop the operator starts in a spare terminal and stops with
  Ctrl+C.
* **Read-only with respect to canonical SQLite.**  Its only write is the
  *derived, non-canonical* snapshot under ``runtime/diagnostics_cache/`` (via
  ``diagnostics_snapshot_cache.refresh``) plus a small warmer-status sidecar.
* **No broker call, no order, no execution, no AI execution.**  It only
  recomputes advisory diagnostics into a cache.
* A refresh that *fails* is recorded as ``DEGRADED`` (with the error type) — it
  is **never** written back as fake-clean.

Scoring (printed and in ``--status``)::

    WarmCacheCoverage    = WarmRefreshSuccesses / max(WarmRefreshAttempts, 1)
    CacheStalenessRisk   = 1 - min(1, CacheAgeSeconds / max(CacheTTLSeconds, 1))
    WarmerHealthScore    = 10 * (0.50*WarmCacheCoverage
                               + 0.30*CacheStalenessRisk
                               + 0.20*DegradedFailureVisibility)

``DegradedFailureVisibility`` is 1 when failures are surfaced as DEGRADED
(always true here — that is the whole point), else 0.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import diagnostics_snapshot_cache as _cache
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import diagnostics_snapshot_cache as _cache  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
WARMER_STATUS_FILE = _cache.CACHE_DIR / "warmer_status.json"

# Refusing intervals below this protects against a hot spin loop that would
# hammer SQLite; ``--allow-fast-local-test`` waives it for the test suite.
MIN_INTERVAL_SECONDS = 60

CANONICAL_TRUTH_SOURCE = _cache.CANONICAL_TRUTH_SOURCE  # "sqlite"
CACHE_ROLE = _cache.CACHE_ROLE                          # "derived_non_canonical"

# Status taxonomy for a single warm attempt.
WARM_OK = "OK"
WARM_DEGRADED = "DEGRADED"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: datetime | None = None) -> str:
    return (dt or _now_utc()).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safety_banner() -> dict[str, Any]:
    """The advisory invariants every warmer payload carries."""
    return {
        "ADVISORY_ONLY": True,
        "HUMAN_EXECUTION_REQUIRED": True,
        "NO_BROKER_ACTION_PERFORMED": True,
        "canonical_truth_source": CANONICAL_TRUTH_SOURCE,
        "cache_role": CACHE_ROLE,
        **_contract.advisory_safety_stamps(),
    }


def _read_status() -> dict[str, Any] | None:
    if not WARMER_STATUS_FILE.exists():
        return None
    try:
        return json.loads(WARMER_STATUS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_status(status: dict[str, Any]) -> None:
    """Persist the warmer status sidecar (derived/non-canonical, best-effort)."""
    try:
        _cache.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = WARMER_STATUS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(status, indent=2, default=str), encoding="utf-8")
        tmp.replace(WARMER_STATUS_FILE)
    except OSError:  # pragma: no cover - defensive; never crash the warmer
        return


def warm_once(
    *,
    ttl_seconds: int = _cache.DEFAULT_TTL_SECONDS,
    refresh: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Refresh the derived snapshot once; return a structured warm result.

    A successful refresh yields ``status=OK`` with the count of degraded
    subreports (visible, never hidden).  A refresh that *raises* yields
    ``status=DEGRADED`` with the error type — it is **never** reported clean.
    """
    do_refresh = refresh or _cache.refresh
    t0 = time.perf_counter()
    result: dict[str, Any] = {
        "report": "diagnostics_snapshot_warmer",
        "warmed_at_utc": _utc_iso(),
        **_safety_banner(),
    }
    try:
        snapshot = do_refresh(ttl_seconds=ttl_seconds)
        degraded = list(snapshot.get("degraded_subreports", []))
        result.update({
            "status": WARM_OK,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 3),
            "generated_at_utc": snapshot.get("generated_at_utc"),
            "ttl_seconds": int(snapshot.get("ttl_seconds", ttl_seconds)),
            "degraded_subreports": degraded,
            "subreport_degraded_count": len(degraded),
        })
    except Exception as exc:  # noqa: BLE001 - failure must be VISIBLE, not clean
        result.update({
            "status": WARM_DEGRADED,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 3),
            "error_type": type(exc).__name__,
            "error_detail": str(exc)[:300],
            "recovery_command": "python scripts/diagnostics_snapshot_cache.py --refresh",
            "ttl_seconds": int(ttl_seconds),
        })
    return result


def _cache_age_seconds() -> float | None:
    snapshot = _cache.read_snapshot()
    if not snapshot:
        return None
    generated = snapshot.get("generated_at_epoch")
    if isinstance(generated, (int, float)):
        return max(0.0, time.time() - float(generated))
    return None


def warmer_health_score(
    successes: int,
    attempts: int,
    *,
    cache_age_seconds: float | None,
    cache_ttl_seconds: int,
    degraded_failure_visibility: int = 1,
) -> dict[str, Any]:
    """Compute WarmerHealthScore and its components (see module docstring)."""
    coverage = successes / max(attempts, 1)
    if cache_age_seconds is None:
        staleness_risk = 0.0  # no cache yet → no staleness signal to credit
    else:
        staleness_risk = 1.0 - min(1.0, cache_age_seconds / max(cache_ttl_seconds, 1))
    score = 10.0 * (
        0.50 * coverage
        + 0.30 * staleness_risk
        + 0.20 * float(degraded_failure_visibility)
    )
    return {
        "warm_cache_coverage": round(coverage, 4),
        "cache_staleness_risk": round(staleness_risk, 4),
        "degraded_failure_visibility": int(degraded_failure_visibility),
        "warmer_health_score": round(score, 3),
    }


def _update_running_status(
    last: dict[str, Any], successes: int, attempts: int, ttl_seconds: int
) -> dict[str, Any]:
    health = warmer_health_score(
        successes, attempts,
        cache_age_seconds=_cache_age_seconds(),
        cache_ttl_seconds=ttl_seconds,
        degraded_failure_visibility=1,
    )
    status = {
        "report": "diagnostics_snapshot_warmer_status",
        "updated_at_utc": _utc_iso(),
        "warm_refresh_attempts": attempts,
        "warm_refresh_successes": successes,
        "last_result": last,
        **health,
        **_safety_banner(),
    }
    _write_status(status)
    return status


def run_once(ttl_seconds: int = _cache.DEFAULT_TTL_SECONDS) -> dict[str, Any]:
    """``--once``: warm the cache a single time and persist warmer status."""
    result = warm_once(ttl_seconds=ttl_seconds)
    successes = 1 if result["status"] == WARM_OK else 0
    return _update_running_status(result, successes, 1, ttl_seconds)


def run_loop(
    interval_seconds: int,
    *,
    ttl_seconds: int = _cache.DEFAULT_TTL_SECONDS,
    allow_fast_local_test: bool = False,
    max_iterations: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """``--loop``: warm repeatedly until interrupted (or ``max_iterations``).

    Refuses ``interval_seconds`` below :data:`MIN_INTERVAL_SECONDS` unless
    ``allow_fast_local_test`` is set.  Ctrl+C is handled gracefully — the
    last persisted status reflects every attempt made before the interrupt.
    """
    if interval_seconds < MIN_INTERVAL_SECONDS and not allow_fast_local_test:
        raise ValueError(
            f"interval_seconds={interval_seconds} below minimum "
            f"{MIN_INTERVAL_SECONDS}s; pass --allow-fast-local-test to waive "
            "(local testing only)."
        )
    attempts = 0
    successes = 0
    status: dict[str, Any] = {}
    iteration = 0
    try:
        while max_iterations is None or iteration < max_iterations:
            iteration += 1
            attempts += 1
            result = warm_once(ttl_seconds=ttl_seconds)
            if result["status"] == WARM_OK:
                successes += 1
            status = _update_running_status(result, successes, attempts, ttl_seconds)
            if max_iterations is not None and iteration >= max_iterations:
                break
            sleep(interval_seconds)
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("\n[warmer] interrupted — stopping gracefully.")
    return status


def status_report(ttl_seconds: int = _cache.DEFAULT_TTL_SECONDS) -> dict[str, Any]:
    """``--status``: read cache + warmer metadata only.  Never recomputes.

    Reflects the persisted warmer status when present; otherwise reports the
    current cache age/validity without triggering a heavy recompute.
    """
    persisted = _read_status()
    snapshot = _cache.read_snapshot()
    validity = _cache.cache_validity(snapshot)
    age = _cache_age_seconds()
    out: dict[str, Any] = {
        "report": "diagnostics_snapshot_warmer_status",
        "checked_at_utc": _utc_iso(),
        "cache_present": snapshot is not None,
        "cache_valid": bool(validity.get("valid")),
        "cache_validity_reason": validity.get("reason"),
        "cache_age_seconds": round(age, 3) if age is not None else None,
        "cache_ttl_seconds": int((snapshot or {}).get("ttl_seconds", ttl_seconds)),
        "cache_generated_at_utc": (snapshot or {}).get("generated_at_utc"),
        "snapshot_degraded_subreports": (snapshot or {}).get("degraded_subreports", []),
        **_safety_banner(),
    }
    if persisted:
        out["last_warmer_run"] = {
            k: persisted.get(k) for k in (
                "updated_at_utc", "warm_refresh_attempts", "warm_refresh_successes",
                "warm_cache_coverage", "cache_staleness_risk",
                "warmer_health_score", "last_result",
            )
        }
    else:
        out["last_warmer_run"] = None
    # A current health snapshot computed from cache age (read-only).
    out.update(warmer_health_score(
        successes=int((persisted or {}).get("warm_refresh_successes", 1) or 1),
        attempts=int((persisted or {}).get("warm_refresh_attempts", 1) or 1),
        cache_age_seconds=age,
        cache_ttl_seconds=out["cache_ttl_seconds"],
        degraded_failure_visibility=1,
    ))
    return out


def _print_banner() -> None:
    print("  ADVISORY_ONLY                : true")
    print("  HUMAN_EXECUTION_REQUIRED     : true")
    print("  NO_BROKER_ACTION_PERFORMED   : true")
    print(f"  canonical_truth_source       : {CANONICAL_TRUTH_SOURCE}")
    print(f"  cache_role                   : {CACHE_ROLE}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="diagnostics_snapshot_warmer.py",
        description=(
            "Local background warmer for the derived diagnostics snapshot "
            "cache.  Read-only w.r.t. canonical SQLite; writes only the "
            "derived non-canonical cache.  No broker calls; no execution."
        ),
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true",
                      help="refresh the cache once and exit")
    mode.add_argument("--loop", action="store_true",
                      help="refresh repeatedly until Ctrl+C")
    mode.add_argument("--status", action="store_true",
                      help="read cache + warmer metadata only (no recompute)")
    p.add_argument("--interval-seconds", type=int, default=300,
                   help="loop interval (default 300; minimum 60)")
    p.add_argument("--ttl", type=int, default=_cache.DEFAULT_TTL_SECONDS,
                   help=f"snapshot TTL (default {_cache.DEFAULT_TTL_SECONDS})")
    p.add_argument("--allow-fast-local-test", action="store_true",
                   help="waive the 60s minimum interval (local testing only)")
    p.add_argument("--max-iterations", type=int, default=None,
                   help="stop --loop after N iterations (testing aid)")
    p.add_argument("--json", action="store_true")
    return p


def _emit(payload: dict[str, Any], *, json_mode: bool, title: str) -> None:
    if json_mode:
        print(json.dumps(payload, indent=2, default=str))
        return
    print(title)
    print("=" * len(title))
    print(f"  status                       : {payload.get('status') or payload.get('cache_validity_reason')}")
    if "warmer_health_score" in payload:
        print(f"  warmer_health_score          : {payload['warmer_health_score']}")
        print(f"  warm_cache_coverage          : {payload['warm_cache_coverage']}")
        print(f"  cache_staleness_risk         : {payload['cache_staleness_risk']}")
    if "cache_age_seconds" in payload:
        print(f"  cache_age_seconds            : {payload['cache_age_seconds']}")
    _print_banner()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.status:
        _emit(status_report(ttl_seconds=args.ttl), json_mode=args.json,
              title="Diagnostics Snapshot Warmer — STATUS (read-only)")
        return 0

    if args.loop:
        try:
            status = run_loop(
                args.interval_seconds,
                ttl_seconds=args.ttl,
                allow_fast_local_test=args.allow_fast_local_test,
                max_iterations=args.max_iterations,
            )
        except ValueError as exc:
            print(f"[warmer] REFUSED: {exc}")
            return 2
        _emit(status, json_mode=args.json,
              title="Diagnostics Snapshot Warmer — LOOP stopped")
        return 0

    # Default + explicit --once: warm a single time.
    status = run_once(ttl_seconds=args.ttl)
    last = status.get("last_result", {})
    _emit(last, json_mode=args.json,
          title="Diagnostics Snapshot Warmer — ONCE")
    # DEGRADED warm exits non-zero so a wrapper cannot read a failed warm as OK.
    return 0 if last.get("status") == WARM_OK else 1


__all__ = [
    "MIN_INTERVAL_SECONDS",
    "CANONICAL_TRUTH_SOURCE",
    "CACHE_ROLE",
    "WARM_OK",
    "WARM_DEGRADED",
    "WARMER_STATUS_FILE",
    "warm_once",
    "run_once",
    "run_loop",
    "status_report",
    "warmer_health_score",
]


if __name__ == "__main__":
    raise SystemExit(main())
