"""Cockpit truth smoke — the API's honesty contract, end to end in-process.

Open-the-Gate sprint (2026-07-04, spec Item 5).  Boots the REAL FastAPI app
(in-process via TestClient — no port, no race) and verifies the truth
surface the cockpit renders:

* GET /truth-surface responds with every field the cockpit needs;
* the overclaim rules hold on live data:
    - no CALIBRATED claim while N < 200 (or the gate otherwise fails);
    - overall state is never HEALTHY while stops are missing/unconfirmed,
      holdings are stale, or N = 0;
* GET /nbi/cockpit carries artifact_age_minutes (staleness visible).

Exit 0 = every check passed; exit 1 = an honesty violation (with details).
``--dry-run`` prints the checks without booting the app.

Advisory-only, read-only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

# CLI bootstrap: make the repo root importable when run as a script.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

REQUIRED_FIELDS = (
    "overall_operational_state",
    "calibration_status",
    "matured_real_outcome_count",
    "evidence_velocity_7d",
    "maturation_velocity_7d",
    "missing_stop_count",
    "unconfirmed_stop_count",
    "leveraged_without_stop_count",
    "holdings_truth_status",
    "fresh_discovery_status",
    "rows_persisted_status",
    "latest_alerts",
    "next_required_operator_action",
)

CHECKS = (
    "truth-surface responds with all required cockpit fields",
    "calibration_status != CALIBRATED while N < 200",
    "state != HEALTHY while stops missing/unconfirmed or holdings stale or N=0",
    "advisory stamps present (ADVISORY_ONLY / LOCKED)",
    "/nbi/cockpit exposes artifact_age_minutes",
)


def run_smoke() -> dict[str, Any]:
    # The startup preflight fails closed without an owner token; the smoke
    # runs in-process only, so the documented loopback-only override is the
    # sanctioned path (see scripts/runtime_config.py StartupSecurityError).
    os.environ.setdefault("MVP_ALLOW_UNAUTH", "1")
    from fastapi.testclient import TestClient

    from scripts.api_server import app

    failures: list[str] = []
    client = TestClient(app)
    if True:
        r = client.get("/truth-surface")
        if r.status_code != 200:
            failures.append(f"/truth-surface -> HTTP {r.status_code}")
            return {"passed": False, "failures": failures}
        surface = r.json()

        missing = [f for f in REQUIRED_FIELDS if f not in surface]
        if missing:
            failures.append(f"missing truth-surface fields: {missing}")

        n = int(surface.get("matured_real_outcome_count") or 0)
        if n < 200 and surface.get("calibration_status") == "CALIBRATED":
            failures.append(
                f"OVERCLAIM: calibration_status=CALIBRATED with N={n} < 200"
            )
        state = surface.get("overall_operational_state")
        blockers = (
            int(surface.get("missing_stop_count") or 0)
            + int(surface.get("unconfirmed_stop_count") or 0)
        )
        if state == "HEALTHY" and (
            blockers > 0
            or surface.get("holdings_truth_status") != "OK"
            or n == 0
        ):
            failures.append(
                "OVERCLAIM: state=HEALTHY while "
                f"stops_missing_or_unconfirmed={blockers}, "
                f"holdings={surface.get('holdings_truth_status')}, N={n}"
            )
        if surface.get("advisory_status") != "ADVISORY_ONLY" or (
            surface.get("execution_gate") != "LOCKED"
        ):
            failures.append("advisory stamps missing from truth surface")

        rc = client.get("/nbi/cockpit")
        if rc.status_code == 200 and "artifact_age_minutes" not in rc.json():
            failures.append("/nbi/cockpit lacks artifact_age_minutes")

    return {
        "passed": not failures,
        "failures": failures,
        "observed": {
            "state": surface.get("overall_operational_state"),
            "calibration_status": surface.get("calibration_status"),
            "n": surface.get("matured_real_outcome_count"),
            "evidence_velocity_7d": surface.get("evidence_velocity_7d"),
            "missing_stops": surface.get("missing_stop_count"),
            "next_action": surface.get("next_required_operator_action"),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dry-run", action="store_true",
                   help="print the checks without booting the app")
    args = p.parse_args(argv)
    if args.dry_run:
        print(json.dumps({"report": "smoke_cockpit_truth", "dry_run": True,
                          "checks": list(CHECKS)}, indent=2))
        return 0
    result = run_smoke()
    print(json.dumps({"report": "smoke_cockpit_truth", **result},
                     indent=2, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
