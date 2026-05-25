"""Single read-only diagnostics service interface (Enforcement Sprint — Task 2).

The cockpit / API previously recomputed heavy audits on every hit and could
fail-soft to zeros, which silently *hides* partial failure (a crashed audit
reads as "clean").  This service is the one interface callers use instead.  It:

* reuses a valid :mod:`scripts.diagnostics_snapshot_cache` snapshot when fresh
  (cache hit → no recomputation), otherwise recomputes once and rewrites it;
* resolves each subreport to an explicit degraded-state taxonomy
  (``CLEAN`` / ``WARN`` / ``BLOCK`` / ``DEGRADED`` / ``UNKNOWN``);
* surfaces a ``partial_failures`` list for any subreport that *raised* — these
  are reported with ``error_type`` + ``safe_recovery_command`` and are **never**
  collapsed into fake-clean zeros;
* propagates degraded/blocked subreports into the top-level ``status`` so a
  failure can never masquerade as a healthy cockpit.

Read-only with respect to the runtime DB.  No broker calls, no execution, no AI
execution.  The snapshot it returns is derived/non-canonical; SQLite remains the
canonical truth source.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import diagnostics_snapshot_cache as _cache
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import diagnostics_snapshot_cache as _cache  # type: ignore[no-redef]

# Degraded-state taxonomy.
CLEAN = "CLEAN"
WARN = "WARN"
BLOCK = "BLOCK"
DEGRADED = "DEGRADED"
UNKNOWN = "UNKNOWN"

# Subreports whose failure/BLOCK must escalate the whole cockpit to BLOCK
# rather than merely DEGRADED.  Truth purity is the canonical-integrity gate.
CRITICAL_SUBREPORTS: frozenset[str] = frozenset({"truth_purity"})


def _status_from_data(name: str, data: Any) -> str:
    """Map a successfully-built subreport's payload to the taxonomy.

    Honest and conservative: a report that built but exposes no blocking signal
    is ``CLEAN``; an unrecognisable payload is ``UNKNOWN`` (never assumed clean).
    """
    if not isinstance(data, dict):
        return UNKNOWN

    # Explicit gate impact wins when present.
    impact = str(data.get("release_gate_impact") or "").strip().upper()
    if impact in {CLEAN, WARN, BLOCK}:
        return impact

    # Boolean release gate (truth purity).
    gate = data.get("release_gate_passed")
    if gate is False:
        return BLOCK
    if gate is True:
        return CLEAN

    # Source independence: any flagged cohort is an advisory WARN.
    flagged = data.get("flagged_cohorts")
    if isinstance(flagged, list) and flagged:
        return WARN

    # Built successfully with no blocking signal → clean.
    return CLEAN


def _resolve_subreports(
    raw: dict[str, Any], *, include_heavy: bool
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Resolve raw cache subreports into taxonomy + a partial-failures list."""
    resolved: dict[str, Any] = {}
    partial_failures: list[dict[str, Any]] = []
    for name, sub in raw.items():
        if not isinstance(sub, dict):
            resolved[name] = {"status": UNKNOWN}
            continue
        if sub.get("status") == "DEGRADED":
            entry = {
                "status": DEGRADED,
                "error_type": sub.get("error_type", "Unknown"),
                "safe_recovery_command": sub.get("recovery_command"),
                "elapsed_ms": sub.get("elapsed_ms"),
            }
            partial_failures.append({
                "subreport": name,
                "error_type": entry["error_type"],
                "safe_recovery_command": entry["safe_recovery_command"],
            })
        else:
            status = _status_from_data(name, sub.get("data"))
            entry = {"status": status, "elapsed_ms": sub.get("elapsed_ms")}
            if include_heavy:
                entry["data"] = sub.get("data")
        resolved[name] = entry
    return resolved, partial_failures


def _top_level_status(resolved: dict[str, Any]) -> str:
    """Collapse subreport statuses into one top-level state."""
    statuses = {name: sub.get("status") for name, sub in resolved.items()}
    crit_bad = any(
        statuses.get(n) in {BLOCK, DEGRADED} for n in CRITICAL_SUBREPORTS
        if n in statuses
    )
    if crit_bad:
        return BLOCK
    values = set(statuses.values())
    if DEGRADED in values:
        return DEGRADED
    if BLOCK in values:
        return BLOCK
    if WARN in values:
        return WARN
    if values and values <= {CLEAN}:
        return CLEAN
    if UNKNOWN in values:
        return UNKNOWN
    return UNKNOWN


def _diagnostics_health(resolved: dict[str, Any]) -> float:
    """DiagnosticsHealth = 1 - failed/total - 0.5 * degraded/total.

    ``failed`` = subreports that *raised* (DEGRADED build).  ``degraded`` =
    subreports in a WARN/BLOCK semantic state.  Clamped to ``[0, 1]``.
    """
    total = max(len(resolved), 1)
    failed = sum(1 for s in resolved.values() if s.get("status") == DEGRADED)
    degraded = sum(1 for s in resolved.values() if s.get("status") in {WARN, BLOCK})
    health = 1.0 - (failed / total) - 0.5 * (degraded / total)
    return round(max(0.0, min(1.0, health)), 4)


def get_diagnostics_snapshot(
    *,
    use_cache: bool = True,
    refresh: bool = False,
    include_heavy: bool = False,
    max_age_seconds: int = 300,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Return the resolved diagnostics snapshot with explicit degraded states.

    ``include_heavy`` controls whether each subreport's full raw ``data`` is
    embedded (cockpit lightweight view omits it by default).
    """
    cache_status: str
    snapshot: dict[str, Any] | None

    if refresh:
        snapshot = _cache.refresh(db_path)
        cache_status = "refreshed"
    elif use_cache:
        snapshot = _cache.read_snapshot()
        validity = _cache.cache_validity(snapshot, db_path)
        age = validity.get("age_seconds")
        too_old = isinstance(age, (int, float)) and age > max_age_seconds
        if validity.get("valid") and not too_old:
            cache_status = "hit"
        else:
            snapshot = _cache.refresh(db_path)
            cache_status = "miss_recomputed"
    else:
        snapshot = _cache.refresh(db_path)
        cache_status = "bypassed_recomputed"

    raw_subreports = (snapshot or {}).get("subreports", {})
    resolved, partial_failures = _resolve_subreports(
        raw_subreports, include_heavy=include_heavy
    )
    status = _top_level_status(resolved)

    out: dict[str, Any] = {
        "report": "diagnostics_service",
        "status": status,
        "degraded_state": status,
        "generated_at_utc": (snapshot or {}).get("generated_at_utc"),
        "cache_status": cache_status,
        "diagnostics_health": _diagnostics_health(resolved),
        "partial_failures": partial_failures,
        "subreports": resolved,
        "canonical_truth_source": _cache.CANONICAL_TRUTH_SOURCE,
        "cache_role": _cache.CACHE_ROLE,
        "safety_stamps": _contract.advisory_safety_stamps(),
        "truth_model": _contract.canonical_truth_declaration(),
    }
    # Top-level shorthands so the cockpit cannot read a degraded service as clean.
    out["advisory_status"] = _contract.ADVISORY_STATUS
    out["execution_gate"] = _contract.EXECUTION_GATE_LOCKED
    out["human_review_required"] = True
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="diagnostics_service.py",
        description=(
            "Read-only diagnostics service. Reuses a fresh derived snapshot or "
            "recomputes once; surfaces partial failures explicitly. No broker "
            "calls; no execution."
        ),
    )
    p.add_argument("--refresh", action="store_true",
                   help="force recomputation and rewrite the snapshot")
    p.add_argument("--no-cache", action="store_true",
                   help="bypass the cache and recompute")
    p.add_argument("--include-heavy", action="store_true",
                   help="embed each subreport's full raw payload")
    p.add_argument("--max-age", type=int, default=300,
                   help="treat a cached snapshot older than N seconds as stale")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    snap = get_diagnostics_snapshot(
        use_cache=not args.no_cache,
        refresh=args.refresh,
        include_heavy=args.include_heavy,
        max_age_seconds=args.max_age,
    )
    if args.json:
        print(json.dumps(snap, indent=2, default=str))
    else:
        print("Diagnostics Service (read-only, derived snapshot)")
        print("=================================================")
        print(f"  top-level status   : {snap['status']}")
        print(f"  diagnostics health : {snap['diagnostics_health']}")
        print(f"  cache status       : {snap['cache_status']}")
        print(f"  generated at (utc) : {snap['generated_at_utc']}")
        print(f"  canonical source   : {snap['canonical_truth_source']}")
        for name, sub in snap["subreports"].items():
            print(f"  [{sub['status']:<8}] {name}")
        if snap["partial_failures"]:
            print("  partial failures:")
            for pf in snap["partial_failures"]:
                print(f"    - {pf['subreport']}: {pf['error_type']} "
                      f"-> {pf['safe_recovery_command']}")
    # A degraded/blocked cockpit returns non-zero so a CI/preflight wrapper
    # cannot mistake it for clean.
    return 0 if snap["status"] in {CLEAN, WARN} else 1


__all__ = [
    "CLEAN", "WARN", "BLOCK", "DEGRADED", "UNKNOWN",
    "CRITICAL_SUBREPORTS",
    "get_diagnostics_snapshot",
]


if __name__ == "__main__":
    raise SystemExit(main())
