"""Release gate — one PASS / WARN / FAIL verdict over the deploy preflight.

Aggregates ``scripts/local_deploy_preflight.py`` into a single gate decision
with exact reasons, so the operator never ships on a broken or unsafe local
state:

* any ``FAIL`` check  -> gate ``FAIL`` (do not release).
* any ``WARN`` check  -> gate ``WARN`` (release only with eyes open).
* otherwise           -> gate ``PASS``.

``INFO`` checks never affect the verdict.  The gate is read-only and never
calls a broker or external trading API; the only optional network touch is the
localhost backend probe inherited from the preflight (off by default).
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
    from scripts import local_deploy_preflight as _preflight
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import local_deploy_preflight as _preflight  # type: ignore[no-redef]

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def evaluate(
    db_path: Path | None = None,
    *,
    check_backend: bool = False,
) -> dict[str, Any]:
    """Run the preflight and reduce it to a single gate verdict + reasons."""
    preflight = _preflight.run_preflight(db_path, check_backend=check_backend)
    checks = preflight["checks"]

    fails = [c for c in checks if c["status"] == _preflight.FAIL]
    warns = [c for c in checks if c["status"] == _preflight.WARN]

    if fails:
        verdict = FAIL
    elif warns:
        verdict = WARN
    else:
        verdict = PASS

    reasons = [f"{c['name']}: {c['detail']}" for c in fails + warns]

    # Surface the Kanté-defensive guard/diagnostics summary at the gate top
    # level (advisory, non-blocking) so the operator sees auth-guard coverage
    # and diagnostics-service availability without digging into the preflight.
    kante = preflight.get("kante_defensive", {})

    return {
        "report": "release_gate",
        "verdict": verdict,
        "db_path": preflight["db_path"],
        "db_exists": preflight["db_exists"],
        "checked_backend": preflight["checked_backend"],
        "fail_count": len(fails),
        "warn_count": len(warns),
        "reasons": reasons,
        "failing_checks": [c["name"] for c in fails],
        "warning_checks": [c["name"] for c in warns],
        # Kanté-defensive advisory summary (does not change the verdict).
        "auth_guard_status": kante.get("auth_guard_status"),
        "operator_permission_guard_available": kante.get(
            "operator_permission_guard_available"),
        "mutation_scripts_guarded": kante.get("mutation_scripts_guarded_count"),
        "mutation_scripts_unguarded": kante.get("mutation_scripts_unguarded_count"),
        "mutation_scripts_unguarded_names": kante.get("mutation_scripts_unguarded"),
        "diagnostics_service_available": kante.get("diagnostics_service_available"),
        "diagnostics_service_status": kante.get("diagnostics_service_status"),
        "release_gate_impact": kante.get("release_gate_impact"),
        "preflight": preflight,
        **_contract.advisory_safety_stamps(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="release_gate.py",
        description=(
            "Aggregate the local deploy preflight into a PASS/WARN/FAIL "
            "release verdict with exact reasons.  Read-only; never calls a "
            "broker."
        ),
    )
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--check-backend", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = evaluate(args.db_path, check_backend=args.check_backend)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"RELEASE GATE: {result['verdict']}")
        print(f"  db: {result['db_path']} (exists={result['db_exists']})")
        print(f"  fails={result['fail_count']} warns={result['warn_count']}")
        for reason in result["reasons"]:
            print(f"  - {reason}")
        if result["verdict"] == PASS:
            print("  (all blocking checks satisfied)")
    # Exit non-zero only on a hard FAIL so CI can branch on it.
    return 1 if result["verdict"] == FAIL else 0


__all__ = ["PASS", "WARN", "FAIL", "evaluate"]


if __name__ == "__main__":
    raise SystemExit(main())
