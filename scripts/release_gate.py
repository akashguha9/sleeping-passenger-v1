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


def _stress_probe_summary() -> dict[str, Any]:
    """Read the last persisted stress-probe summary (Kanté Task C), WARN-only.

    Read-only and cheap: the release gate never *runs* the probe (that is a
    deliberate, separate operator action) — it only surfaces the last run's
    derived, non-canonical ``last_run.json`` summary if present.  Maps the
    probe's stress gate to a release impact that is WARN-only by default and
    only escalates to FAIL on a real reliability disaster the probe itself
    flagged (a DB-lock under concurrent reads).
    """
    out: dict[str, Any] = {
        "stress_probe_available": False,
        "stress_gate_status": "UNKNOWN",
        "stress_score": None,
        "stress_release_impact": PASS,
    }
    try:
        try:
            from scripts import cockpit_concurrency_stress_probe as probe
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            import cockpit_concurrency_stress_probe as probe  # type: ignore[no-redef]
        out["stress_probe_available"] = True
    except Exception:  # pragma: no cover - defensive
        return out

    summary = probe.read_summary()
    if not summary:
        # Probe exists but has not been run — advisory only, no impact.
        out["stress_gate_status"] = "NOT_RUN"
        return out

    status = str(summary.get("stress_gate_status") or "UNKNOWN").upper()
    out["stress_gate_status"] = status
    out["stress_score"] = summary.get("stress_score")
    db_locked = int(summary.get("db_locked_errors", 0) or 0)

    if status == "BLOCK" and db_locked > 0:
        # The only condition allowed to FAIL the release: a DB-lock disaster the
        # probe directly observed under concurrent reads.
        out["stress_release_impact"] = FAIL
    elif status in {"BLOCK", "WARN"}:
        out["stress_release_impact"] = WARN
    else:
        out["stress_release_impact"] = PASS
    return out


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

    # Kanté-defensive guard/diagnostics summary.  Unlike before, the mutation
    # guard now *participates in the verdict*: an unguarded high-risk mutation
    # script (BLOCK) fails the gate; low-risk unguarded scripts (WARN) downgrade
    # a PASS to WARN.  This is the meaningful enforcement the prior INFO-only
    # surfacing lacked.
    kante = preflight.get("kante_defensive", {})
    mutation_impact = kante.get("mutation_guard_release_impact", PASS)

    if mutation_impact == "BLOCK":
        verdict = FAIL
        reasons.append(
            "mutation_guard: unguarded high-risk mutation script(s) detected "
            f"— {kante.get('mutation_scripts_unguarded_names')} "
            f"(coverage={kante.get('mutation_guard_coverage')}); BLOCK."
        )
    elif mutation_impact == WARN and verdict == PASS:
        verdict = WARN
        reasons.append(
            "mutation_guard: unguarded low-risk mutation script(s) — "
            f"{kante.get('mutation_scripts_unguarded_names')}; WARN."
        )

    # Concurrency/stress probe (Kanté Task C).  WARN-only by default; only a
    # DB-lock disaster the probe itself observed can FAIL the gate.
    stress = _stress_probe_summary()
    stress_impact = stress["stress_release_impact"]
    if stress_impact == FAIL:
        verdict = FAIL
        reasons.append(
            "stress_probe: db_locked_errors under concurrent reads "
            f"(stress_gate_status={stress['stress_gate_status']}); FAIL."
        )
    elif stress_impact == WARN and verdict == PASS:
        verdict = WARN
        reasons.append(
            "stress_probe: last run "
            f"stress_gate_status={stress['stress_gate_status']} "
            f"(score={stress['stress_score']}); WARN."
        )

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
        # Kanté-defensive mutation-guard enforcement (now affects the verdict).
        "auth_guard_status": kante.get("auth_guard_status"),
        "operator_permission_guard_available": kante.get(
            "operator_permission_guard_available"),
        "mutation_guard_coverage": kante.get("mutation_guard_coverage"),
        "mutation_guard_risk": kante.get("mutation_guard_risk"),
        "mutation_scripts_guarded": kante.get("mutation_scripts_guarded_count"),
        "mutation_scripts_unguarded": kante.get("mutation_scripts_unguarded_count"),
        "mutation_scripts_unguarded_names": kante.get("mutation_scripts_unguarded"),
        "mutation_scripts_unguarded_high_severity": kante.get(
            "mutation_scripts_unguarded_high_severity"),
        "mutation_guard_release_impact": mutation_impact,
        "diagnostics_service_available": kante.get("diagnostics_service_available"),
        "diagnostics_service_status": kante.get("diagnostics_service_status"),
        "release_gate_impact": kante.get("release_gate_impact"),
        # Concurrency/stress probe surface (Kanté Task C; WARN-only by default).
        "stress_probe_available": stress["stress_probe_available"],
        "stress_gate_status": stress["stress_gate_status"],
        "stress_score": stress["stress_score"],
        "stress_release_impact": stress_impact,
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
        print(f"  auth_guard_status            : {result['auth_guard_status']}")
        print(f"  mutation_guard_coverage      : {result['mutation_guard_coverage']}")
        print(f"  mutation_scripts_unguarded   : {result['mutation_scripts_unguarded']} "
              f"{result['mutation_scripts_unguarded_names']}")
        print(f"  mutation_guard_release_impact: {result['mutation_guard_release_impact']}")
        for reason in result["reasons"]:
            print(f"  - {reason}")
        if result["verdict"] == PASS:
            print("  (all blocking checks satisfied)")
    # Exit non-zero only on a hard FAIL so CI can branch on it.
    return 1 if result["verdict"] == FAIL else 0


__all__ = ["PASS", "WARN", "FAIL", "evaluate"]


if __name__ == "__main__":
    raise SystemExit(main())
