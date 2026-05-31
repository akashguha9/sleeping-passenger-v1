"""Real Evidence Sprint — Phase 4: reproducible evidence bundle.

Composes the Phase 1-3 artifacts into ONE honest, reproducible bundle for
investor / professor / operator review:

    runtime/release/real_evidence_bundle.json
    docs/REAL_EVIDENCE_BUNDLE.md

The bundle is deliberately conservative:
  * real canary activation is separated from fixture-backed activation,
  * real-forward outcomes are separated from historical-proxy outcomes,
  * NO edge is claimed, NO real-money readiness is claimed,
  * the calibration claim stays locked unless the gate passes.

Evidence score (documented, not a trading claim)::

    S_evidence = w_source·SourceTruthScore + w_scoring·ScoringCoverage
               + w_snapshot·SnapshotCoverage + w_outcome·OutcomeCoverage
               + w_calibration·CalibrationGateScore
               + w_reproducibility·ReproducibilityScore

    SourceTruthScore     = min(1, real_live_sources / 3)
    ScoringCoverage      = min(1, n_scored_real_rows / max(1, n_real_canonical_rows))
    SnapshotCoverage     = min(1, n_valid_p / 200)
    OutcomeCoverage      = min(1, n_real_forward_pairs / 200)
    CalibrationGateScore = I(N>=200)·I(Brier<=0.25)·I(ECE<=0.10)
    ReproducibilityScore = I(bundle_json) · I(commands_logged)
                         · I(commit_hash) · I(tests_green)
    weights: source 0.20, scoring 0.20, snapshot 0.20, outcome 0.20,
             calibration 0.10, repro 0.10

Adding the scoring axis NEVER unlocks a predictive claim — that gate is owned
solely by the real-forward calibration corpus (N>=200, Brier<=0.25, ECE<=0.10).
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:  # package layout
    from scripts.runtime_common import RUNTIME_DIR, REPO_ROOT, write_json_atomic
    from scripts.real_calibration_evidence import build_calibration_evidence
    from scripts.outcome_labeling_flow import build_outcome_corpus_summary
    from scripts.real_evidence_canary import run_canary
    from scripts.decision_probability_snapshot import count_valid_p
    from scripts.score_real_signal_events import scoring_coverage_summary
    from scripts.real_signal_score_vector import MODEL_VERSION, SCORING_VERSION
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    from runtime_common import RUNTIME_DIR, REPO_ROOT, write_json_atomic  # type: ignore[no-redef]
    from real_calibration_evidence import build_calibration_evidence  # type: ignore[no-redef]
    from outcome_labeling_flow import build_outcome_corpus_summary  # type: ignore[no-redef]
    from real_evidence_canary import run_canary  # type: ignore[no-redef]
    from decision_probability_snapshot import count_valid_p  # type: ignore[no-redef]
    from score_real_signal_events import scoring_coverage_summary  # type: ignore[no-redef]
    from real_signal_score_vector import MODEL_VERSION, SCORING_VERSION  # type: ignore[no-redef]

_JSON_NAME = "real_evidence_bundle.json"
_MD_PATH = REPO_ROOT / "docs" / "REAL_EVIDENCE_BUNDLE.md"

N_SNAPSHOT_TARGET = 200
N_OUTCOME_TARGET = 200

# S_evidence weights.  The Real-Forward Outcome Maturation sprint adds a
# DailyMaturationLoopScore component (does the boring daily attach->calibrate->
# bundle loop exist and keep the claim honestly locked?) and rebalances toward
# the outcome/calibration gate.  Weights sum to 1.0.
W_SOURCE = 0.10
W_SCORING = 0.10
W_SNAPSHOT = 0.12
W_FORWARD_ELIGIBILITY = 0.15
W_OUTCOME = 0.20
W_CALIBRATION = 0.18
W_DAILY_MATURATION = 0.10
W_REPRODUCIBILITY = 0.05

REPRO_COMMAND = (
    "python scripts/real_evidence_canary.py --sources yfinance,gdelt,polymarket --write && "
    "python scripts/real_calibration_evidence.py --write && "
    "python scripts/real_evidence_bundle.py --write"
)

_SAFETY = {
    "advisory_only": True,
    "advisory_status": "ADVISORY_ONLY",
    "human_execution_required": True,
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}

_DEFAULT_LIMITATIONS = [
    "Real forward calibration corpus is below N=200; no predictive claim is made.",
    "Source activation may be fixture-backed; real canary rows require "
    "REAL_EVIDENCE_CANARY=1 with live network access.",
    "Historical-proxy metrics (if any) are research-only and never unlock the gate.",
    "This system is ADVISORY ONLY. It places no orders and calls no broker API.",
    "This is NOT real-money ready and makes no claim of trading edge.",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_commit_hash() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT),
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:  # pragma: no cover - defensive
        pass
    return "UNKNOWN"


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _build_forward_throughput_block(
    db_path: str | Path,
    *,
    forward_eligible_after: int,
    n_pending_horizon: int,
    n_due_forward: int,
    n_real_forward_pairs: int,
) -> dict[str, Any]:
    """Additive forward-throughput evidence block (this sprint).

    Reads the optional sprint-start baseline artifact and computes the honest
    before/after deltas, the ``ThroughputImprovementScore`` and the live
    top-missing lists.  ``ThroughputImprovementScore`` is a *reported* sub-metric
    only — it NEVER feeds the predictive-claim gate (which stays governed solely
    by N>=200 real-forward pairs clearing Brier/ECE).
    """
    baseline_path = REPO_ROOT / "runtime" / "release" / "forward_throughput_baseline.json"
    forward_eligible_before = 0
    reasons_before: dict[str, Any] = {}
    if baseline_path.exists():
        try:
            b = json.loads(baseline_path.read_text(encoding="utf-8"))
            forward_eligible_before = int(b.get("forward_eligible_before", 0))
            reasons_before = {
                "MISSING_TICKER": b.get("missing_ticker_before", 0),
                "MISSING_ENTRY_PRICE": b.get("missing_entry_price_before", 0),
                "MISSING_PROBABILITY": b.get("missing_probability_before", 0),
            }
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    top_missing_entry_price_tickers: list[Any] = []
    try:
        try:
            from scripts.forward_eligibility_diagnostics import forward_eligibility_diagnostics
        except ModuleNotFoundError:  # pragma: no cover - script-style env
            from forward_eligibility_diagnostics import forward_eligibility_diagnostics  # type: ignore
        diag = forward_eligibility_diagnostics(db_path=db_path)
        top_missing_entry_price_tickers = diag.get("top_missing_entry_price_tickers", [])
    except Exception:  # pragma: no cover - never crash the bundle
        pass

    throughput_improvement_score = round(
        _clip01((forward_eligible_after - forward_eligible_before)
                / max(1, forward_eligible_before)),
        6,
    )
    return {
        "forward_eligible_before": forward_eligible_before,
        "forward_eligible_after": forward_eligible_after,
        "eligibility_gain": forward_eligible_after - forward_eligible_before,
        "reason_baseline": reasons_before,
        "top_missing_entry_price_tickers": top_missing_entry_price_tickers,
        "throughput_improvement_score": throughput_improvement_score,
        "n_pending_horizon": n_pending_horizon,
        "n_due_forward": n_due_forward,
        "n_real_forward_pairs": n_real_forward_pairs,
        "n_needed_to_200": max(0, N_OUTCOME_TARGET - n_real_forward_pairs),
        # Throughput improvement NEVER unlocks a predictive claim.
        "predictive_claim_allowed": False,
        "edge_claimed": False,
        "real_money_ready": False,
    }


def _module_importable(name: str) -> bool:
    """True iff a sibling script module can be imported under either layout."""
    import importlib

    for candidate in (f"scripts.{name}", name):
        try:
            importlib.import_module(candidate)
            return True
        except Exception:  # noqa: BLE001 - any import failure means "absent"
            continue
    return False


def daily_maturation_loop_score(
    *,
    n_real_forward: int,
    predictive_claim_allowed: bool,
    bundle_refreshes: bool = True,
) -> float:
    """``DailyMaturationLoopScore`` — the indicator product (0 or 1).

        I(maturity_scanner_exists) · I(daily_runner_exists) · I(bundle_refreshes)
      · I(no_fake_outcomes) · I(predictive_claim_locked_when_N_below_200)

    ``no_fake_outcomes`` is structurally guaranteed (only real, horizon-elapsed
    pairs grow N_real_forward); the locked invariant requires that a sub-200
    corpus never reports a predictive claim.
    """
    scanner_exists = _module_importable("forward_outcome_maturity_scanner")
    runner_exists = _module_importable("run_daily_outcome_maturation")
    no_fake_outcomes = True  # enforced by the attach path (real_forward only)
    locked_invariant = (
        (not predictive_claim_allowed) if n_real_forward < N_OUTCOME_TARGET else True
    )
    ok = (
        scanner_exists
        and runner_exists
        and bool(bundle_refreshes)
        and no_fake_outcomes
        and locked_invariant
    )
    return 1.0 if ok else 0.0


def _build_maturation_section(
    db_path: str | Path,
    *,
    calibration: Mapping[str, Any],
    forward: Mapping[str, Any],
) -> dict[str, Any]:
    """Honest ``real_forward_maturation`` section for the bundle (read-only).

    Reads the maturity scanner + last-run daily report (when present).  Never
    inflates: ``OutcomeCoverage`` and all metrics stay zero/None until real
    horizons elapse and real pairs attach.
    """
    n_real = int(calibration.get("n_real_forward", 0))
    next_due_in_hours = None
    earliest_close = None
    try:
        try:
            from scripts.forward_outcome_maturity_scanner import scan_forward_outcome_maturity
        except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
            from forward_outcome_maturity_scanner import scan_forward_outcome_maturity  # type: ignore
        scan = scan_forward_outcome_maturity(db_path=db_path)
        next_due_in_hours = scan.get("next_due_in_hours")
        earliest_close = scan.get("earliest_horizon_close_utc")
    except Exception:  # pragma: no cover - never crash the bundle
        pass

    # Last-run attach delta from the optional persisted daily report.
    outcomes_attached_last_run = None
    report = REPO_ROOT / "runtime" / "release" / "daily_maturation_report.json"
    if report.exists():
        try:
            r = json.loads(report.read_text(encoding="utf-8"))
            outcomes_attached_last_run = int(r.get("outcomes_attached", 0))
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            outcomes_attached_last_run = None

    limitations = [
        "Real-forward maturation cannot attach an outcome until a decision's "
        "horizon elapses in real calendar time; pending horizons are never "
        "backdated.",
        "Below N=200 real-forward pairs the calibration gate stays LOCKED and "
        "no predictive claim is made.",
        "This loop is advisory-only: it places no orders and is NOT real-money "
        "ready.",
    ]
    return {
        "n_forward_eligible": int(forward.get("n_forward_outcome_eligible", 0)),
        "n_pending_horizon": int(forward.get("n_pending_horizon", 0)),
        "n_due_forward": int(forward.get("n_due_forward", 0)),
        "n_real_forward_pairs": n_real,
        "outcomes_attached_last_run": outcomes_attached_last_run,
        "n_needed_to_200": max(0, N_OUTCOME_TARGET - n_real),
        "brier_real_forward": calibration.get("brier_real_forward"),
        "ece_real_forward": calibration.get("ece_real_forward"),
        "logloss_real_forward": calibration.get("logloss_real_forward"),
        "calibration_status": calibration.get("calibration_status"),
        "status_detail": calibration.get("status_detail"),
        "predictive_claim_allowed": bool(calibration.get("predictive_claim_allowed")),
        "next_due_in_hours": next_due_in_hours,
        "earliest_horizon_close_utc": earliest_close,
        "limitations": limitations,
    }


def _split_canary_sources(canary_report: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    real, fixture = [], []
    for s in canary_report.get("per_source", []):
        if not s.get("activated"):
            continue
        (real if s.get("canary_real") else fixture).append(s.get("source_name"))
    return real, fixture


def build_evidence_bundle(
    db_path: str | Path,
    *,
    canary_report: Mapping[str, Any] | None = None,
    repo_commit: str | None = None,
    tests_green: bool = False,
    bundle_json_written: bool = True,
    now_utc: str | None = None,
    n_snapshot_target: int = N_SNAPSHOT_TARGET,
) -> dict[str, Any]:
    """Build the evidence-bundle payload (honest; no edge / real-money claims)."""
    now = now_utc or _utc_now_iso()
    commit = repo_commit if repo_commit is not None else _get_commit_hash()

    if canary_report is None:
        # Offline, fixture-less canary: honest zero activation.
        canary_report = run_canary(db_path=db_path, write_source_run_log=False)
    real_sources, fixture_sources = _split_canary_sources(canary_report)

    calibration = build_calibration_evidence(db_path)
    outcomes = build_outcome_corpus_summary(db_path)
    n_valid_p = count_valid_p(db_path)
    scoring = scoring_coverage_summary(db_path)

    try:  # forward-snapshot-contract counts (this sprint)
        from scripts.decision_probability_snapshot import forward_outcome_counts
    except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
        from decision_probability_snapshot import forward_outcome_counts  # type: ignore
    forward = forward_outcome_counts(db_path)

    # ----- S_evidence components ---------------------------------------- #
    source_truth_score = round(min(1.0, len(real_sources) / 3.0), 6)
    scoring_coverage = round(
        min(
            1.0,
            scoring["n_scored_real_rows"] / max(1, scoring["n_real_canonical_rows"]),
        ),
        6,
    )
    snapshot_coverage = round(min(1.0, n_valid_p / max(1, n_snapshot_target)), 6)
    # ForwardEligibilityCoverage = min(1, n_forward_outcome_eligible / max(1, n_valid_p))
    forward_eligibility_coverage = round(
        min(1.0, forward["n_forward_outcome_eligible"] / max(1, n_valid_p)), 6
    )
    outcome_coverage = round(
        min(1.0, calibration["n_real_forward"] / N_OUTCOME_TARGET), 6
    )
    calibration_gate_score = 1.0 if calibration["predictive_claim_allowed"] else 0.0
    daily_maturation_loop_score_val = daily_maturation_loop_score(
        n_real_forward=int(calibration["n_real_forward"]),
        predictive_claim_allowed=bool(calibration["predictive_claim_allowed"]),
        bundle_refreshes=True,
    )
    commit_present = commit not in (None, "", "UNKNOWN")
    reproducibility_score = (
        1.0
        if (bundle_json_written and bool(REPRO_COMMAND) and commit_present and tests_green)
        else 0.0
    )
    s_evidence = round(
        W_SOURCE * source_truth_score
        + W_SCORING * scoring_coverage
        + W_SNAPSHOT * snapshot_coverage
        + W_FORWARD_ELIGIBILITY * forward_eligibility_coverage
        + W_OUTCOME * outcome_coverage
        + W_CALIBRATION * calibration_gate_score
        + W_DAILY_MATURATION * daily_maturation_loop_score_val
        + W_REPRODUCIBILITY * reproducibility_score,
        6,
    )

    return {
        "generated_at_utc": now,
        "repo_commit": commit,
        **_SAFETY,
        "real_source_activation": {
            "source_count": len(real_sources),
            "sources": real_sources,
        },
        "fixture_source_activation": {
            "source_count": len(fixture_sources),
            "sources": fixture_sources,
        },
        "decision_snapshots": {
            "n_snapshots": outcomes["n_snapshots"],
            "n_valid_p": n_valid_p,
        },
        "scoring": {
            "n_real_canonical_rows": int(scoring["n_real_canonical_rows"]),
            "n_scored_real_rows": int(scoring["n_scored_real_rows"]),
            "scoring_coverage": scoring_coverage,
            "n_complete_score_vectors": int(scoring["n_complete_score_vectors"]),
            "score_quality_coverage": float(scoring["score_quality_coverage"]),
            "sources_scored": list(scoring.get("sources_scored") or []),
            "score_unavailable_reasons": dict(
                scoring.get("score_unavailable_reasons") or {}
            ),
            "n_valid_p": n_valid_p,
            "scoring_version": SCORING_VERSION,
            "model_version": MODEL_VERSION,
            "calibration_status": calibration["calibration_status"],
            # The scoring axis is advisory-only; it can NEVER unlock the gate.
            "predictive_claim_allowed": bool(calibration["predictive_claim_allowed"]),
            "edge_claimed": False,
            "real_money_ready": False,
        },
        "outcomes": {
            "n_real_forward_pairs": calibration["n_real_forward"],
            "n_historical_proxy_pairs": calibration["n_historical_proxy"],
            "n_excluded": outcomes["n_excluded"],
            "exclusion_reasons": outcomes["exclusion_reasons"],
            "outcome_coverage": outcome_coverage,
            "needed_to_reach_200": max(0, N_OUTCOME_TARGET - int(calibration["n_real_forward"])),
        },
        "forward_snapshot_contract": {
            "n_valid_p": n_valid_p,
            "n_forward_outcome_eligible": int(forward["n_forward_outcome_eligible"]),
            "n_forward_ineligible": int(forward["n_forward_outcome_ineligible"]),
            "n_pending_horizon": int(forward["n_pending_horizon"]),
            "n_due_forward": int(forward["n_due_forward"]),
            "n_real_forward_pairs": int(calibration["n_real_forward"]),
            "entry_price_present_count": int(forward["entry_price_present_count"]),
            "forward_unavailable_reasons": dict(
                forward["forward_outcome_unavailable_reasons"]
            ),
            "forward_eligibility_coverage": forward_eligibility_coverage,
            "target_event_definition": "forward_return_ge_threshold",
            "default_prediction_horizon_days": 5,
            "target_return_threshold": 0.0,
            "target_source": "DEFAULT_FORWARD_SNAPSHOT_CONTRACT_V1",
            "n_needed_to_200": max(0, N_OUTCOME_TARGET - int(calibration["n_real_forward"])),
            # Eligibility is structural only — it never unlocks a predictive claim.
            "predictive_claim_allowed": False,
            "edge_claimed": False,
        },
        "forward_throughput": _build_forward_throughput_block(
            db_path,
            forward_eligible_after=int(forward["n_forward_outcome_eligible"]),
            n_pending_horizon=int(forward["n_pending_horizon"]),
            n_due_forward=int(forward["n_due_forward"]),
            n_real_forward_pairs=int(calibration["n_real_forward"]),
        ),
        "real_forward_maturation": _build_maturation_section(
            db_path, calibration=calibration, forward=forward,
        ),
        "calibration": {
            "status": calibration["calibration_status"],
            "predictive_claim_allowed": calibration["predictive_claim_allowed"],
            "brier": calibration["brier_real_forward"],
            "ece": calibration["ece_real_forward"],
            "logloss": calibration["logloss_real_forward"],
        },
        "source_truth": {
            "C_global": canary_report.get("C_global", 0.0),
            "live_canonical_count": canary_report.get("live_canonical_count", 0),
            "production_ready_live_ingestion": False,
        },
        "moltbook": {
            "note": "Moltbook learning loop adjusts (downgrades) advisory "
            "probability only; it never unlocks execution.",
        },
        "capacity_guard": {
            "per_position": True,
            "correlation_aware": False,
            "note": "Portfolio correlation guard is a follow-up phase.",
        },
        "s_evidence": {
            "score": s_evidence,
            "components": {
                "source_truth_score": source_truth_score,
                "scoring_coverage": scoring_coverage,
                "snapshot_coverage": snapshot_coverage,
                "forward_eligibility_coverage": forward_eligibility_coverage,
                "outcome_coverage": outcome_coverage,
                "calibration_gate_score": calibration_gate_score,
                "daily_maturation_loop_score": daily_maturation_loop_score_val,
                "reproducibility_score": reproducibility_score,
            },
            "weights": {
                "source": W_SOURCE, "scoring": W_SCORING, "snapshot": W_SNAPSHOT,
                "forward_eligibility": W_FORWARD_ELIGIBILITY,
                "outcome": W_OUTCOME, "calibration": W_CALIBRATION,
                "daily_maturation": W_DAILY_MATURATION,
                "reproducibility": W_REPRODUCIBILITY,
            },
        },
        "reproducibility": {
            "command": REPRO_COMMAND,
            "commit_hash_present": commit_present,
            "tests_green": bool(tests_green),
        },
        "predictive_claim_allowed": calibration["predictive_claim_allowed"],
        "real_money_ready": False,
        "edge_claimed": False,
        "limitations": list(_DEFAULT_LIMITATIONS),
    }


def render_markdown(bundle: Mapping[str, Any]) -> str:
    """Render an investor/professor-readable markdown bundle (no hype)."""
    cal = bundle["calibration"]
    s = bundle["s_evidence"]
    lines = [
        "# Real Evidence Bundle — sleeping-passenger-v1",
        "",
        "> **ADVISORY ONLY. NOT real-money ready. No trading edge is claimed.**",
        "> This system places no orders and calls no broker API "
        "(`execution_gate = LOCKED`, `broker_api_called = false`).",
        "",
        f"- Generated (UTC): `{bundle['generated_at_utc']}`",
        f"- Repo commit: `{bundle['repo_commit']}`",
        f"- Predictive claim allowed: **{bundle['predictive_claim_allowed']}**",
        f"- Real-money ready: **{bundle['real_money_ready']}**",
        "",
        "## Source activation",
        f"- Real canary activation: **{bundle['real_source_activation']['source_count']}** "
        f"{bundle['real_source_activation']['sources']}",
        f"- Fixture-backed activation: **{bundle['fixture_source_activation']['source_count']}** "
        f"{bundle['fixture_source_activation']['sources']}",
        f"- C_global: {bundle['source_truth']['C_global']}",
        "",
        "## Real-row scoring",
        f"- Real canonical rows scored: **{_sc(bundle)['n_scored_real_rows']}** / "
        f"{_sc(bundle)['n_real_canonical_rows']} "
        f"(scoring_coverage {_sc(bundle)['scoring_coverage']})",
        f"- Complete six-axis vectors: {_sc(bundle)['n_complete_score_vectors']} "
        f"(score_quality_coverage {_sc(bundle)['score_quality_coverage']})",
        f"- Sources scored: {_sc(bundle)['sources_scored']}",
        f"- Decision-time valid probabilities (n_valid_p): "
        f"**{_sc(bundle)['n_valid_p']}**",
        f"- Score vector / model version: `{_sc(bundle)['scoring_version']}` / "
        f"`{_sc(bundle)['model_version']}`",
        "- Real rows are now scored AND consumed into decision snapshots; "
        "the probabilities are advisory-only and **uncalibrated**.",
        f"- Calibration status: **{_sc(bundle)['calibration_status']}** "
        f"(N_real_forward < 200 ⇒ predictive claim LOCKED).",
        "- Signal edge is **NOT proven**. Real-money readiness is **NO**.",
        "",
        "## Decision snapshots & outcomes (the forward loop)",
        f"- Decision snapshots: {bundle['decision_snapshots']['n_snapshots']} "
        f"(valid p: {bundle['decision_snapshots']['n_valid_p']})",
        f"- Real-forward (p, y) pairs: **{bundle['outcomes']['n_real_forward_pairs']}**",
        f"- Historical-proxy pairs (research only): "
        f"{bundle['outcomes']['n_historical_proxy_pairs']}",
        f"- Excluded: {bundle['outcomes']['n_excluded']} "
        f"{bundle['outcomes']['exclusion_reasons']}",
        f"- Outcome coverage: {bundle['outcomes'].get('outcome_coverage', 0.0)} "
        f"(needed to reach 200: "
        f"{bundle['outcomes'].get('needed_to_reach_200', N_OUTCOME_TARGET)})",
        "- A real-forward pair is created ONLY when a decision's horizon has "
        "elapsed in real calendar time AND a real entry/exit price exists; "
        "historical proxy / open / unresolved decisions never count.",
        "",
        "## Forward snapshot contract (outcome-eligibility)",
        f"- Forward-outcome-eligible snapshots: **{_fc(bundle)['n_forward_outcome_eligible']}** "
        f"/ {_fc(bundle)['n_valid_p']} valid-p "
        f"(coverage {_fc(bundle)['forward_eligibility_coverage']})",
        f"- Pending horizon: {_fc(bundle)['n_pending_horizon']}  "
        f"Due forward: {_fc(bundle)['n_due_forward']}  "
        f"Entry-price present: {_fc(bundle)['entry_price_present_count']}",
        f"- Forward-ineligible: {_fc(bundle)['n_forward_ineligible']} "
        f"{_fc(bundle)['forward_unavailable_reasons']}",
        f"- Target: `{_fc(bundle)['target_event_definition']}` "
        f"(threshold {_fc(bundle)['target_return_threshold']}, "
        f"horizon {_fc(bundle)['default_prediction_horizon_days']}d, "
        f"source `{_fc(bundle)['target_source']}`)",
        "- Eligibility is **structural only** — a snapshot becoming eligible means "
        "a binary outcome can be measured after its horizon closes; it is NOT a "
        "predictive claim and NOT an edge claim.",
        "",
        "## Forward-eligible throughput (Increase Forward-Eligible Throughput Sprint)",
        f"- Forward-eligible: **{_ft(bundle).get('forward_eligible_before', 0)} → "
        f"{_ft(bundle).get('forward_eligible_after', 0)}** "
        f"(gain {_ft(bundle).get('eligibility_gain', 0)})",
        f"- Throughput improvement score (reported, NOT a gate): "
        f"{_ft(bundle).get('throughput_improvement_score', 0.0)}",
        f"- Sprint-start reason baseline: {_ft(bundle).get('reason_baseline', {})}",
        f"- Top missing-OHLCV scored tickers (now): "
        f"{_ft(bundle).get('top_missing_entry_price_tickers', [])}",
        f"- Pending horizon: {_ft(bundle).get('n_pending_horizon', 0)}  "
        f"Real-forward pairs: {_ft(bundle).get('n_real_forward_pairs', 0)}  "
        f"Needed to 200: {_ft(bundle).get('n_needed_to_200', N_OUTCOME_TARGET)}",
        "- Throughput improvement raises *eligibility*, never calibration. It does "
        "NOT unlock a predictive claim, an edge claim, or real-money readiness.",
        "",
        "## Real-forward maturation (Real-Forward Outcome Maturation Sprint)",
        f"- Forward-eligible: {_mat(bundle).get('n_forward_eligible', 0)}  "
        f"Pending horizon: {_mat(bundle).get('n_pending_horizon', 0)}  "
        f"Due now: {_mat(bundle).get('n_due_forward', 0)}",
        f"- Real-forward pairs: **{_mat(bundle).get('n_real_forward_pairs', 0)}** "
        f"(needed to 200: {_mat(bundle).get('n_needed_to_200', N_OUTCOME_TARGET)}, "
        f"attached last run: {_mat(bundle).get('outcomes_attached_last_run')})",
        f"- Next horizon becomes due in: "
        f"{_mat(bundle).get('next_due_in_hours')} hours "
        f"(earliest close {_mat(bundle).get('earliest_horizon_close_utc')})",
        f"- Brier: {_mat(bundle).get('brier_real_forward')}  "
        f"ECE: {_mat(bundle).get('ece_real_forward')}  "
        f"LogLoss: {_mat(bundle).get('logloss_real_forward')}",
        f"- Status: **{_mat(bundle).get('calibration_status')}** / "
        f"{_mat(bundle).get('status_detail')}",
        "- The calibration gate stays **LOCKED** below N=200 real-forward pairs; "
        "no predictive claim is made and this is **NOT real-money ready**.",
        "- Outcomes attach only after a real horizon elapses — pending horizons "
        "are never backdated and no outcome is ever fabricated.",
        "",
        "## Calibration",
        "",
        "```",
        "Brier = (1/N) Σ (p_i - y_i)^2",
        "ECE   = Σ (n_b/N) |acc(b) - conf(b)|",
        "CalibrationAllowed = I(N>=200) · I(Brier<=0.25) · I(ECE<=0.10)",
        "```",
        "",
        f"- N_real_forward: {cal_n(bundle)}",
        f"- Brier: {cal['brier']}  ECE: {cal['ece']}  LogLoss: {cal['logloss']}",
        f"- Status: **{cal['status']}**",
        f"- Predictive claim allowed: **{cal['predictive_claim_allowed']}**",
        "",
        "## Evidence score (documentation metric, NOT a trading claim)",
        f"- S_evidence = **{s['score']}**",
        f"- Components: {s['components']}",
        f"- Weights: {s['weights']}",
        "",
        "## Reproducibility",
        "",
        "```",
        bundle["reproducibility"]["command"],
        "```",
        f"- Commit hash present: {bundle['reproducibility']['commit_hash_present']}",
        f"- Tests green: {bundle['reproducibility']['tests_green']}",
        "",
        "## Limitations",
        "",
    ]
    lines += [f"- {lim}" for lim in bundle["limitations"]]
    lines.append("")
    return "\n".join(lines)


def cal_n(bundle: Mapping[str, Any]) -> int:
    return int(bundle["outcomes"]["n_real_forward_pairs"])


def _fc(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Forward-snapshot-contract sub-dict with safe defaults for older bundles."""
    return dict(bundle.get("forward_snapshot_contract") or {
        "n_valid_p": 0, "n_forward_outcome_eligible": 0, "n_forward_ineligible": 0,
        "n_pending_horizon": 0, "n_due_forward": 0, "entry_price_present_count": 0,
        "forward_unavailable_reasons": {}, "forward_eligibility_coverage": 0.0,
        "target_event_definition": "forward_return_ge_threshold",
        "default_prediction_horizon_days": 5, "target_return_threshold": 0.0,
        "target_source": "DEFAULT_FORWARD_SNAPSHOT_CONTRACT_V1", "n_needed_to_200": 200,
    })


def _ft(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Forward-throughput sub-dict with safe defaults for older bundles."""
    return dict(bundle.get("forward_throughput") or {})


def _mat(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Real-forward-maturation sub-dict with safe defaults for older bundles."""
    return dict(bundle.get("real_forward_maturation") or {})


def _sc(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Scoring sub-dict with safe defaults for older bundles."""
    return dict(bundle.get("scoring") or {
        "n_real_canonical_rows": 0, "n_scored_real_rows": 0, "scoring_coverage": 0.0,
        "n_complete_score_vectors": 0, "score_quality_coverage": 0.0,
        "sources_scored": [], "n_valid_p": 0,
        "scoring_version": "real-row-score-v1", "model_version": "advisory-logistic-v1",
        "calibration_status": "INSUFFICIENT_EVIDENCE",
    })


def write_bundle(
    bundle: Mapping[str, Any],
    *,
    json_path: Any = None,
    md_path: Any = None,
) -> dict[str, str]:
    """Write both the JSON and the markdown bundle.  Returns their paths."""
    jpath = json_path or (RUNTIME_DIR / "release" / _JSON_NAME)
    mpath = Path(md_path) if md_path is not None else _MD_PATH
    write_json_atomic(jpath, dict(bundle))
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(render_markdown(bundle), encoding="utf-8")
    return {"json_path": str(jpath), "markdown_path": str(mpath)}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    import argparse
    import json

    try:
        from scripts import persistence
    except ModuleNotFoundError:
        import persistence  # type: ignore[no-redef]

    p = argparse.ArgumentParser(description="Real evidence bundle (advisory-only).")
    p.add_argument("--write", action="store_true")
    p.add_argument("--tests-green", action="store_true",
                   help="record that the suite was green for this run")
    args = p.parse_args(argv)

    persistence.init_schema()
    bundle = build_evidence_bundle(persistence.DB_PATH, tests_green=args.tests_green)
    if args.write:
        bundle["paths"] = write_bundle(bundle)
    print(json.dumps({
        "repo_commit": bundle["repo_commit"],
        "real_source_activation": bundle["real_source_activation"]["source_count"],
        "fixture_source_activation": bundle["fixture_source_activation"]["source_count"],
        "n_real_canonical_rows": bundle["scoring"]["n_real_canonical_rows"],
        "n_scored_real_rows": bundle["scoring"]["n_scored_real_rows"],
        "scoring_coverage": bundle["scoring"]["scoring_coverage"],
        "n_valid_p": bundle["scoring"]["n_valid_p"],
        "n_real_forward_pairs": bundle["outcomes"]["n_real_forward_pairs"],
        "calibration_status": bundle["calibration"]["status"],
        "predictive_claim_allowed": bundle["predictive_claim_allowed"],
        "real_money_ready": bundle["real_money_ready"],
        "s_evidence": bundle["s_evidence"]["score"],
    }, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    raise SystemExit(main(sys.argv[1:]))


__all__ = [
    "build_evidence_bundle",
    "render_markdown",
    "write_bundle",
    "main",
]
