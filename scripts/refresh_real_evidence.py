"""Phase 6 — one-command real-evidence refresh (advisory-only).

Post-match recovery + training automation: a single repeatable routine that
turns the whole evidence pipeline into one deterministic, offline-safe command.
It runs, in order:

    1. real_evidence_canary            (offline fixtures by default; real only with
                                        an explicit flag AND the env opt-in)
    2. run_daily_live_advisory_decisions  (fresh canonical rows -> snapshots)
    3. attach_due_outcomes             (elapsed horizons -> realized outcomes)
    4. real_calibration_evidence       (Brier / ECE on the real-forward corpus)
    5. real_evidence_bundle            (the honest evidence bundle)

Calibration gate (never loosened here):

    Brier = (1/N) Σ (p_i - y_i)^2
    ECE   = Σ_b (n_b/N) |acc(b) - conf(b)|
    CalibrationAllowed = I(N>=200) · I(Brier<=0.25) · I(ECE<=0.10)

Below N=200 the status is ``INSUFFICIENT_EVIDENCE`` and
``predictive_claim_allowed`` is ``False``.  The default path NEVER touches the
network: ``--real-canary`` is required *and* ``REAL_EVIDENCE_CANARY=1`` must be
set for any live fetch.  No broker, no order, no execution — ever.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

try:  # package layout
    from scripts import persistence
    from scripts.real_evidence_canary import CANARY_ENV_FLAG, run_canary, write_report
    from scripts.run_daily_live_advisory_decisions import run_daily_decision_batch
    from scripts.attach_due_outcomes import attach_due_outcomes
    from scripts.real_calibration_evidence import build_calibration_evidence, write_evidence
    from scripts.real_evidence_bundle import build_evidence_bundle, write_bundle
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    import persistence  # type: ignore[no-redef]
    from real_evidence_canary import CANARY_ENV_FLAG, run_canary, write_report  # type: ignore
    from run_daily_live_advisory_decisions import run_daily_decision_batch  # type: ignore
    from attach_due_outcomes import attach_due_outcomes  # type: ignore
    from real_calibration_evidence import build_calibration_evidence, write_evidence  # type: ignore
    from real_evidence_bundle import build_evidence_bundle, write_bundle  # type: ignore
    from advisory_contract import advisory_safety_stamps  # type: ignore

# Step labels — surfaced in order so callers (and tests) can assert sequencing.
STEPS = (
    "real_evidence_canary",
    "run_daily_live_advisory_decisions",
    "attach_due_outcomes",
    "real_calibration_evidence",
    "real_evidence_bundle",
)


def refresh_real_evidence(
    *,
    db_path: Any = None,
    fixtures: Mapping[str, Mapping[str, Any]] | None = None,
    sources: Sequence[str] | None = None,
    real_canary: bool = False,
    write: bool = False,
    evidence_by_id: Mapping[str, Mapping[str, Any]] | None = None,
    now_iso: str | None = None,
    canary_json_path: Any = None,
    calibration_json_path: Any = None,
    bundle_json_path: Any = None,
    bundle_md_path: Any = None,
    tests_green: bool = False,
    max_decisions: int = 50,
) -> dict[str, Any]:
    """Run the full evidence refresh in order and return an honest summary.

    The default path is fully offline.  A real network canary requires BOTH
    ``real_canary=True`` AND ``REAL_EVIDENCE_CANARY=1`` in the environment; if
    the flag is requested without the env opt-in, the canary stays offline and
    the summary records ``real_canary_blocked = True``.
    """
    stamps = advisory_safety_stamps()
    target = db_path if db_path is not None else persistence.DB_PATH
    steps_run: list[str] = []

    # ----- 1. canary ----------------------------------------------------- #
    env_opt_in = os.environ.get(CANARY_ENV_FLAG, "").strip() == "1"
    allow_network = bool(real_canary and env_opt_in)
    real_canary_blocked = bool(real_canary and not env_opt_in)
    canary = run_canary(
        sources or ("yfinance", "gdelt", "polymarket"),
        allow_network=allow_network,
        fixtures=fixtures,
        db_path=target,
        now_iso=now_iso,
        write_source_run_log=True,
    )
    if write:
        canary["report_path"] = write_report(canary, path=canary_json_path)
    steps_run.append(STEPS[0])

    # ----- 2. daily decisions ------------------------------------------- #
    decisions = run_daily_decision_batch(
        db_path=target, max_decisions=max_decisions, now_iso=now_iso, write=write
    )
    steps_run.append(STEPS[1])

    # ----- 3. attach due outcomes --------------------------------------- #
    outcomes = attach_due_outcomes(
        db_path=target, evidence_by_id=evidence_by_id, now_utc=now_iso, write=write
    )
    steps_run.append(STEPS[2])

    # ----- 4. calibration evidence -------------------------------------- #
    calibration = build_calibration_evidence(target, now_utc=now_iso)
    calibration_path = None
    if write:
        calibration_path = write_evidence(calibration, path=calibration_json_path)
    steps_run.append(STEPS[3])

    # ----- 5. evidence bundle ------------------------------------------- #
    bundle = build_evidence_bundle(
        target, canary_report=canary, tests_green=tests_green, now_utc=now_iso
    )
    bundle_paths: dict[str, str] = {}
    if write:
        bundle_paths = write_bundle(
            bundle, json_path=bundle_json_path, md_path=bundle_md_path
        )
    steps_run.append(STEPS[4])

    out = {
        "steps_run": steps_run,
        "steps_expected": list(STEPS),
        "real_canary": bool(real_canary),
        "real_canary_blocked": real_canary_blocked,
        "allow_network": allow_network,
        # source activation
        "real_source_activation_count": canary.get("real_source_activation_count", 0),
        "fixture_source_activation_count": canary.get("fixture_source_activation_count", 0),
        "C_global": canary.get("C_global", 0.0),
        # decisions / calibration
        "n_valid_p": calibration["corpus"]["n_valid_p"],
        "n_real_forward": calibration["n_real_forward"],
        "delta_n_valid_p": decisions["delta_n_valid_p"],
        "delta_n_real_forward": outcomes["delta_n_real_forward"],
        "brier_real_forward": calibration["brier_real_forward"],
        "ece_real_forward": calibration["ece_real_forward"],
        "logloss_real_forward": calibration["logloss_real_forward"],
        "calibration_status": calibration["calibration_status"],
        "predictive_claim_allowed": bool(calibration["predictive_claim_allowed"]),
        # bundle
        "evidence_score": bundle["s_evidence"]["score"],
        "real_money_ready": False,
        "edge_claimed": False,
        "bundle_json_path": bundle_paths.get("json_path"),
        "bundle_markdown_path": bundle_paths.get("markdown_path"),
        "calibration_json_path": calibration_path,
        "wrote_artifacts": bool(write),
    }
    out.update(stamps)
    out["advisory_only"] = True
    out["human_execution_required"] = True
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="One-command real-evidence refresh (advisory-only, offline by default)."
    )
    p.add_argument("--write", action="store_true", help="write all artifacts to runtime/release")
    p.add_argument(
        "--real-canary",
        action="store_true",
        help="enable the REAL network canary (also requires REAL_EVIDENCE_CANARY=1)",
    )
    p.add_argument("--tests-green", action="store_true")
    p.add_argument("--max-decisions", type=int, default=50)
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    persistence.init_schema()
    summary = refresh_real_evidence(
        real_canary=bool(args.real_canary),
        write=bool(args.write),
        tests_green=bool(args.tests_green),
        max_decisions=args.max_decisions,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))


__all__ = ["STEPS", "refresh_real_evidence", "main"]
