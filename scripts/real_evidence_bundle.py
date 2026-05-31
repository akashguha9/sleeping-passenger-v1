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

# S_evidence weights (now include a scoring-coverage axis).
W_SOURCE = 0.20
W_SCORING = 0.20
W_SNAPSHOT = 0.20
W_OUTCOME = 0.20
W_CALIBRATION = 0.10
W_REPRODUCIBILITY = 0.10

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
    outcome_coverage = round(
        min(1.0, calibration["n_real_forward"] / N_OUTCOME_TARGET), 6
    )
    calibration_gate_score = 1.0 if calibration["predictive_claim_allowed"] else 0.0
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
        + W_OUTCOME * outcome_coverage
        + W_CALIBRATION * calibration_gate_score
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
        },
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
                "outcome_coverage": outcome_coverage,
                "calibration_gate_score": calibration_gate_score,
                "reproducibility_score": reproducibility_score,
            },
            "weights": {
                "source": W_SOURCE, "scoring": W_SCORING, "snapshot": W_SNAPSHOT,
                "outcome": W_OUTCOME, "calibration": W_CALIBRATION,
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
        "## Decision snapshots & outcomes",
        f"- Decision snapshots: {bundle['decision_snapshots']['n_snapshots']} "
        f"(valid p: {bundle['decision_snapshots']['n_valid_p']})",
        f"- Real-forward (p, y) pairs: **{bundle['outcomes']['n_real_forward_pairs']}**",
        f"- Historical-proxy pairs (research only): "
        f"{bundle['outcomes']['n_historical_proxy_pairs']}",
        f"- Excluded: {bundle['outcomes']['n_excluded']} "
        f"{bundle['outcomes']['exclusion_reasons']}",
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
