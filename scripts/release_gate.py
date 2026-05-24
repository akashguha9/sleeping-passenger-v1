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
import os
import time
from datetime import datetime, timezone
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

# Default TTL for the persisted cockpit stress summary, in hours.  Beyond this
# age the summary is treated as ``STALE`` and downgrades the release verdict
# to WARN — a stale PASS must never be allowed to produce a release PASS.
DEFAULT_STRESS_SUMMARY_TTL_HOURS = 24
# Hard-cap on the env override so a typo (e.g. "100000") can't silently
# disable the freshness check.
MAX_STRESS_SUMMARY_TTL_HOURS = 24 * 30  # 30 days

STRESS_PROBE_RECOMMENDED_CMD = (
    "python scripts/cockpit_concurrency_stress_probe.py "
    "--workers 4 --iterations 25 --json"
)


def _stress_summary_ttl_seconds() -> int:
    """Read ``MVP_STRESS_SUMMARY_TTL_HOURS`` (clamped) → seconds.

    Invalid / negative / absurdly-large values fall back to the default; this
    keeps a bad env var from silently disabling the freshness check.
    """
    raw = os.environ.get("MVP_STRESS_SUMMARY_TTL_HOURS", "").strip()
    if not raw:
        return DEFAULT_STRESS_SUMMARY_TTL_HOURS * 3600
    try:
        hours = float(raw)
    except ValueError:
        return DEFAULT_STRESS_SUMMARY_TTL_HOURS * 3600
    if hours <= 0 or hours > MAX_STRESS_SUMMARY_TTL_HOURS:
        return DEFAULT_STRESS_SUMMARY_TTL_HOURS * 3600
    return int(hours * 3600)


def _parse_iso_utc(value: Any) -> float | None:
    """Parse a ``YYYY-MM-DDTHH:MM:SSZ`` UTC string into an epoch float.

    Returns None on any parse failure so the freshness check treats the
    summary as malformed (which downgrades to WARN, never PASS).
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Accept both ``...Z`` and ``...+00:00`` forms.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc).timestamp()
    except (ValueError, TypeError):
        return None


def _stress_probe_summary() -> dict[str, Any]:
    """Read the last persisted stress-probe summary with TTL validation.

    Read-only and cheap: the release gate never *runs* the probe (that is a
    deliberate, separate operator action) — it only surfaces the last run's
    derived, non-canonical ``last_run.json`` summary if present, *and* enforces
    a freshness TTL so a stale PASS cannot mislead the operator.

    Freshness contract (each branch sets ``stress_release_impact``)::

        missing summary       → UNKNOWN  / WARN
        unreadable / malformed → DEGRADED / WARN
        stale (age > TTL)     → STALE    / WARN  (regardless of stored gate)
        fresh + stress PASS   → PASS     / PASS
        fresh + stress WARN   → WARN     / WARN
        fresh + stress BLOCK  → BLOCK    / FAIL  (a stale BLOCK can never PASS)

    The TTL is the env-overridable ``MVP_STRESS_SUMMARY_TTL_HOURS`` (default
    24h, clamped at 30 days).  The recommended command is surfaced for the
    operator so a stale/missing summary has an obvious fix.
    """
    ttl_seconds = _stress_summary_ttl_seconds()
    out: dict[str, Any] = {
        "stress_probe_available": False,
        "stress_gate_status": "UNKNOWN",
        "stress_score": None,
        "stress_release_impact": WARN,
        "stress_summary_path": None,
        "stress_summary_generated_at_utc": None,
        "stress_summary_age_seconds": None,
        "stress_summary_ttl_seconds": ttl_seconds,
        "stress_summary_fresh": False,
        "stress_recommended_command": STRESS_PROBE_RECOMMENDED_CMD,
        "stress_summary_runtime_db_polluted": False,
    }
    try:
        try:
            from scripts import cockpit_concurrency_stress_probe as probe
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            import cockpit_concurrency_stress_probe as probe  # type: ignore[no-redef]
        out["stress_probe_available"] = True
        out["stress_summary_path"] = str(probe.SUMMARY_FILE)
    except Exception:  # pragma: no cover - defensive
        # The probe module itself is missing — surface as UNKNOWN/WARN.
        return out

    summary_path: Path = probe.SUMMARY_FILE
    if not summary_path.exists():
        # Probe exists but has not been run yet — operator must run it before
        # release.  WARN, not silent PASS.
        out["stress_gate_status"] = "UNKNOWN"
        out["stress_release_impact"] = WARN
        return out

    summary = probe.read_summary()
    if not summary:
        # The file exists but is unreadable / malformed — never assume PASS.
        out["stress_gate_status"] = "DEGRADED"
        out["stress_release_impact"] = WARN
        return out

    out["stress_summary_runtime_db_polluted"] = bool(
        summary.get("runtime_db_polluted", False)
    )
    generated_at_utc = summary.get("generated_at_utc")
    out["stress_summary_generated_at_utc"] = generated_at_utc
    generated_epoch = _parse_iso_utc(generated_at_utc)
    if generated_epoch is None:
        # No parseable timestamp → treat as malformed.  This also catches the
        # case of a hand-edited summary missing ``generated_at_utc``.
        out["stress_gate_status"] = "DEGRADED"
        out["stress_release_impact"] = WARN
        return out

    age_seconds = max(0.0, time.time() - generated_epoch)
    out["stress_summary_age_seconds"] = round(age_seconds, 3)
    out["stress_summary_fresh"] = age_seconds <= ttl_seconds

    raw_status = str(summary.get("stress_gate_status") or "UNKNOWN").upper()
    out["stress_score"] = summary.get("stress_score")
    db_locked = int(summary.get("db_locked_errors", 0) or 0)

    # Stale (age > TTL) — STALE/WARN regardless of stored gate.  A stale PASS
    # *must not* be allowed to produce a release PASS.
    if not out["stress_summary_fresh"]:
        out["stress_gate_status"] = "STALE"
        out["stress_release_impact"] = WARN
        return out

    # Fresh.  Map directly.
    out["stress_gate_status"] = raw_status
    if raw_status == "BLOCK":
        # Any fresh BLOCK now fails the release (stricter than the prior
        # "only db_locked BLOCK fails" rule); the db_locked flag is surfaced
        # in the reason text so the operator knows *why* it failed.
        out["stress_release_impact"] = FAIL
        out["stress_summary_db_locked_errors"] = db_locked
    elif raw_status == "WARN":
        out["stress_release_impact"] = WARN
    elif raw_status == "PASS":
        out["stress_release_impact"] = PASS
    else:
        # Unknown gate status word in an otherwise fresh summary — degrade
        # to WARN rather than trust it.
        out["stress_release_impact"] = WARN
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

    # Concurrency/stress probe (Kanté Task C + large-scale TTL).  Freshness
    # is enforced via ``MVP_STRESS_SUMMARY_TTL_HOURS`` (default 24h): a stale
    # PASS now WARNs (never silently passes), and any fresh BLOCK FAILs.
    stress = _stress_probe_summary()
    stress_impact = stress["stress_release_impact"]
    stress_status = stress["stress_gate_status"]
    if stress_impact == FAIL:
        verdict = FAIL
        why = f"stress_probe: fresh BLOCK (stress_gate_status={stress_status}"
        if stress.get("stress_summary_db_locked_errors"):
            why += f", db_locked_errors={stress['stress_summary_db_locked_errors']}"
        why += f"); FAIL. Re-run: {stress['stress_recommended_command']}"
        reasons.append(why)
    elif stress_impact == WARN and verdict == PASS:
        verdict = WARN
        if stress_status in {"UNKNOWN", "STALE", "DEGRADED"}:
            age = stress.get("stress_summary_age_seconds")
            reasons.append(
                f"stress_probe: {stress_status} (age={age}s, ttl="
                f"{stress['stress_summary_ttl_seconds']}s); WARN. "
                f"Re-run: {stress['stress_recommended_command']}"
            )
        else:
            reasons.append(
                "stress_probe: last run "
                f"stress_gate_status={stress_status} "
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
        # Concurrency/stress probe surface (Kanté Task C + TTL).  A stale or
        # missing or malformed summary now WARNs (never silently passes), and
        # any fresh BLOCK FAILs the gate.
        "stress_probe_available": stress["stress_probe_available"],
        "stress_gate_status": stress["stress_gate_status"],
        "stress_score": stress["stress_score"],
        "stress_release_impact": stress_impact,
        "stress_summary_path": stress.get("stress_summary_path"),
        "stress_summary_generated_at_utc": stress.get("stress_summary_generated_at_utc"),
        "stress_summary_age_seconds": stress.get("stress_summary_age_seconds"),
        "stress_summary_ttl_seconds": stress.get("stress_summary_ttl_seconds"),
        "stress_summary_fresh": stress.get("stress_summary_fresh"),
        "stress_recommended_command": stress.get("stress_recommended_command"),
        "stress_summary_runtime_db_polluted": stress.get(
            "stress_summary_runtime_db_polluted", False
        ),
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
        print(f"  stress_gate_status           : {result['stress_gate_status']} "
              f"(impact={result['stress_release_impact']}, fresh="
              f"{result['stress_summary_fresh']}, "
              f"age={result['stress_summary_age_seconds']}s/"
              f"ttl={result['stress_summary_ttl_seconds']}s)")
        for reason in result["reasons"]:
            print(f"  - {reason}")
        if result["verdict"] == PASS:
            print("  (all blocking checks satisfied)")
    # Exit non-zero only on a hard FAIL so CI can branch on it.
    return 1 if result["verdict"] == FAIL else 0


__all__ = [
    "PASS", "WARN", "FAIL",
    "DEFAULT_STRESS_SUMMARY_TTL_HOURS",
    "MAX_STRESS_SUMMARY_TTL_HOURS",
    "STRESS_PROBE_RECOMMENDED_CMD",
    "evaluate",
]


if __name__ == "__main__":
    raise SystemExit(main())
