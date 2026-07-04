"""Real-Forward Outcome Maturation Sprint — Phase 2: the daily maturation runner.

One safe, repeatable, auditable daily command.  Kanté work: it makes the
real-forward outcome loop *boring* — scan maturity, attach outcomes only when a
horizon has truly elapsed, recompute calibration on the real-forward corpus,
refresh the evidence bundle, and report honestly.  It never backdates, never
fabricates an outcome, and never unlocks a predictive claim.

Daily flow::

    1. scan_forward_outcome_maturity(now_utc)
    2. if n_due_forward > 0: attach_due_outcomes(use_real_price_evidence, write)
       else: reason = "NO_DUE_FORWARD_SNAPSHOTS"
    3. real_calibration_evidence  (Brier/ECE on the real-forward corpus)
    4. real_evidence_bundle       (the honest bundle)
    5. emit the daily summary

Mathematics (all honest)::

    N_real_forward_after = N_real_forward_before + outcomes_attached
    n_needed_to_200      = max(0, 200 - N_real_forward_after)
    OutcomeCoverage      = min(1, N_real_forward_after / 200)
    CalibrationAllowed   = I(N>=200) · I(Brier<=0.25) · I(ECE<=0.10)

    If CalibrationAllowed = 0  ->  predictive_claim_allowed = False

Default is **dry-run** unless ``--write`` is passed.  No broker, no order, no
execution — ever.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

try:  # package layout
    from scripts import persistence
    from scripts.forward_outcome_maturity_scanner import scan_forward_outcome_maturity
    from scripts.attach_due_outcomes import attach_due_outcomes
    from scripts.real_calibration_evidence import build_calibration_evidence, write_evidence
    from scripts.real_evidence_bundle import build_evidence_bundle, write_bundle
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.runtime_common import RUNTIME_DIR, write_json_atomic
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    import persistence  # type: ignore[no-redef]
    from forward_outcome_maturity_scanner import scan_forward_outcome_maturity  # type: ignore
    from attach_due_outcomes import attach_due_outcomes  # type: ignore[no-redef]
    from real_calibration_evidence import build_calibration_evidence, write_evidence  # type: ignore
    from real_evidence_bundle import build_evidence_bundle, write_bundle  # type: ignore
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from runtime_common import RUNTIME_DIR, write_json_atomic  # type: ignore[no-redef]

_REPORT_NAME = "daily_maturation_report.json"

N_OUTCOME_GATE = 200

NO_DUE_REASON = "NO_DUE_FORWARD_SNAPSHOTS"


def run_daily_outcome_maturation(
    *,
    db_path: Any = None,
    now_utc: str | None = None,
    write: bool = False,
    use_real_price_evidence: bool = True,
    evidence_by_id: Any = None,
    benchmark_symbol: str | None = None,
    bundle_json_path: Any = None,
    bundle_md_path: Any = None,
    calibration_json_path: Any = None,
    report_json_path: Any = None,
    tests_green: bool = False,
) -> dict[str, Any]:
    """Run the daily maturation loop and return an honest summary.

    Outcomes attach ONLY when the maturity scan reports ``n_due_forward > 0``.
    When nothing is due the runner attaches nothing and records the honest
    reason ``NO_DUE_FORWARD_SNAPSHOTS`` — it never invents a due snapshot.
    """
    stamps = advisory_safety_stamps()
    target = db_path if db_path is not None else persistence.DB_PATH

    # ----- Step 1: scan maturity (read-only) ---------------------------- #
    maturity = scan_forward_outcome_maturity(db_path=target, now_utc=now_utc)
    n_real_forward_before = int(maturity["n_attached_real_forward"])

    # ----- Step 2: attach due outcomes (only when truly due) ------------ #
    attach_reason: str | None = None
    outcomes_attached = 0
    if maturity["n_due_forward"] > 0:
        attached = attach_due_outcomes(
            db_path=target,
            evidence_by_id=evidence_by_id,
            use_real_price_evidence=bool(
                use_real_price_evidence and evidence_by_id is None
            ),
            benchmark_symbol=benchmark_symbol,
            now_utc=now_utc,
            write=write,
        )
        outcomes_attached = int(attached.get("outcomes_attached", 0))
    else:
        attach_reason = NO_DUE_REASON

    # ----- Step 3: real calibration evidence ---------------------------- #
    calibration = build_calibration_evidence(target, now_utc=now_utc)
    calibration_path = None
    if write:
        calibration_path = write_evidence(calibration, path=calibration_json_path)

    n_real_forward_after = int(calibration["n_real_forward"])
    # When dry-running, attach_due_outcomes did not write, so the calibration
    # corpus reflects the pre-run state; report the would-be increment honestly.
    delta_n_real_forward = (
        (n_real_forward_after - n_real_forward_before) if write else outcomes_attached
    )

    # ----- Step 4: refresh the evidence bundle -------------------------- #
    bundle = build_evidence_bundle(
        target, tests_green=tests_green, now_utc=now_utc
    )
    bundle_paths: dict[str, str] = {}
    if write:
        bundle_paths = write_bundle(
            bundle, json_path=bundle_json_path, md_path=bundle_md_path
        )

    # ----- Step 5: honest daily summary --------------------------------- #
    brier = calibration["brier_real_forward"]
    ece = calibration["ece_real_forward"]
    predictive = bool(calibration["predictive_claim_allowed"])
    n_needed = max(0, N_OUTCOME_GATE - n_real_forward_after)
    outcome_coverage = round(min(1.0, n_real_forward_after / N_OUTCOME_GATE), 6)

    out: dict[str, Any] = {
        "run_timestamp_utc": maturity["generated_at_utc"],
        "write_mode": bool(write),
        "n_forward_eligible": int(maturity["n_forward_eligible"]),
        "n_pending_horizon": int(maturity["n_pending_horizon"]),
        "n_due_forward": int(maturity["n_due_forward"]),
        "due_snapshot_ids": list(maturity["due_snapshot_ids"]),
        "outcomes_attached": outcomes_attached,
        "attach_reason": attach_reason,
        "n_real_forward_before": n_real_forward_before,
        "n_real_forward_after": n_real_forward_after,
        "delta_n_real_forward": delta_n_real_forward,
        "brier_real_forward": brier,
        "ece_real_forward": ece,
        "logloss_real_forward": calibration["logloss_real_forward"],
        "outcome_coverage": outcome_coverage,
        "calibration_status": calibration["calibration_status"],
        "predictive_claim_allowed": predictive,
        "n_needed_to_200": n_needed,
        "n_outcome_gate": N_OUTCOME_GATE,
        "next_due_in_hours": maturity["next_due_in_hours"],
        "earliest_horizon_close_utc": maturity["earliest_horizon_close_utc"],
        "evidence_score": bundle["s_evidence"]["score"],
        "evidence_bundle_path": bundle_paths.get("json_path"),
        "evidence_bundle_markdown_path": bundle_paths.get("markdown_path"),
        "calibration_json_path": calibration_path,
        "edge_claimed": False,
        "real_money_ready": False,
    }
    out.update(stamps)
    out["advisory_only"] = True
    out["human_execution_required"] = True

    # Persist the honest daily report so the evidence route can surface the
    # last-run attach delta.  Written only in --write mode.
    if write:
        report_target = report_json_path or (RUNTIME_DIR / "release" / _REPORT_NAME)
        write_json_atomic(report_target, dict(out))
        out["report_json_path"] = str(report_target)
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Daily real-forward outcome maturation (advisory-only; dry-run by default)."
    )
    p.add_argument("--write", action="store_true", help="persist outcomes/calibration/bundle")
    p.add_argument("--now", default=None, help="override 'now' (ISO UTC)")
    p.add_argument("--tests-green", action="store_true")
    p.add_argument("--benchmark-symbol", default=None)
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    persistence.init_schema()
    summary = run_daily_outcome_maturation(
        now_utc=args.now,
        write=bool(args.write),
        tests_green=bool(args.tests_green),
        benchmark_symbol=args.benchmark_symbol,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))


__all__ = ["NO_DUE_REASON", "run_daily_outcome_maturation", "main"]
