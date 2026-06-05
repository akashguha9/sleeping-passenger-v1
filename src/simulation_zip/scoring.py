"""Segmented before/after simulation-readiness scoring.

Scope: these scores measure the *zip-simulation subsystem's* contribution to
the MVP, NOT total MVP capability and NOT live trading performance.  "Before"
means the subsystem was absent; "after" means it ran.  Every score is
SIMULATION_ONLY.

Scoring is conservative and fail-closed:

* No usable data for a category => that category cannot inflate the after score.
* If the test suite fails        => overall_after capped at 60.
* If advisory guardrails break    => overall_after capped at 30.
* If provenance is missing        => evidence/provenance categories capped at 50.

The same pure formula is applied to the "before" (subsystem-absent) signal set
and the "after" (measured-run) signal set, so deltas are computed, never
hand-entered.
"""
from __future__ import annotations

from src.simulation_zip import metrics

H_TARGET = 50
DELAYED_TARGET = 100
VOLUME_TAU = 1000.0

# The spec's stated category weights.  NOTE: as written they sum to 1.10, not
# 1.0 (the spec is internally inconsistent — it also requires "weights sum to
# 1.00").  We keep the spec's relative emphasis but normalize to a true
# probability simplex so the weighted overall stays on the same [0,100] scale.
RAW_WEIGHTS: dict[str, float] = {
    "evidence_ingestion_robustness": 0.10,
    "data_provenance_completeness": 0.10,
    "parser_coverage": 0.08,
    "simulation_volume": 0.08,
    "noise_handling": 0.08,
    "calibration_hardening": 0.12,
    "high_confidence_failure_handling": 0.10,
    "delayed_outcome_handling": 0.08,
    "product_mvp_clarity": 0.08,
    "advisory_guardrail_preservation": 0.10,
    "reproducibility": 0.10,
    "dashboard_reporting_usefulness": 0.08,
}

_RAW_SUM = sum(RAW_WEIGHTS.values())
DEFAULT_WEIGHTS: dict[str, float] = {
    k: v / _RAW_SUM for k, v in RAW_WEIGHTS.items()
}

CATEGORY_LABELS: dict[str, str] = {
    "advisory_guardrail_preservation": "GOVERNANCE",
}


def _bool(value: object) -> float:
    return 1.0 if value else 0.0


def assert_weights_sum_to_one(weights: dict[str, float], *, tol: float = 1e-9) -> None:
    total = sum(weights.values())
    if abs(total - 1.0) > tol:
        raise ValueError(f"category weights must sum to 1.0, got {total}")


# --- Per-category formulas (operate on a measured signal dict) -------------- #
def score_evidence_ingestion(s: dict) -> float:
    return 100.0 * (
        0.35 * s.get("S_safety", 0.0)
        + 0.25 * _bool(s.get("S_streaming"))
        + 0.25 * _bool(s.get("S_fail_closed"))
        + 0.15 * _bool(s.get("S_memory"))
    )


def score_provenance(s: dict) -> float:
    n = s.get("records_total", 0)
    if n <= 0:
        return 0.0
    return 100.0 * (s.get("records_with_full_provenance", 0) / n)


def score_parser_coverage(s: dict) -> float:
    return 100.0 * s.get("families_parsed", 0) / max(s.get("families_detected", 0), 1)


def score_simulation_volume(s: dict) -> float:
    return metrics.saturating_volume_score(s.get("usable_records", 0), VOLUME_TAU)


def score_noise_handling(s: dict) -> float:
    n_total = max(s.get("candidate_files", 0), 1)
    crash = s.get("parser_crashes", 0)
    return 100.0 * (
        0.40 * (1 - crash / n_total)
        + 0.30 * s.get("safe_skip_rate", 0.0)
        + 0.30 * s.get("unsupported_handling_rate", 0.0)
    )


def score_calibration_hardening(s: dict) -> float:
    return 100.0 * min(
        1.0,
        0.40 * _bool(s.get("has_brier_stress_test"))
        + 0.25 * _bool(s.get("has_ece_or_bin_reliability"))
        + 0.20 * _bool(s.get("has_high_confidence_failure_cases"))
        + 0.15 * _bool(s.get("has_reported_limitations")),
    )


def score_high_confidence_failure(s: dict) -> float:
    return 100.0 * min(
        1.0,
        0.40 * _bool(s.get("detector_exists"))
        + 0.30 * min(1.0, s.get("hcf_cases", 0) / H_TARGET)
        + 0.20 * _bool(s.get("fail_closed_response_exists"))
        + 0.10 * _bool(s.get("tests_exist")),
    )


def score_delayed_outcome(s: dict) -> float:
    return 100.0 * min(
        1.0,
        0.30 * _bool(s.get("delayed_outcome_model_exists"))
        + 0.30 * min(1.0, s.get("delayed_cases", 0) / DELAYED_TARGET)
        + 0.20 * _bool(s.get("open_outcome_state_supported"))
        + 0.20 * _bool(s.get("tests_exist")),
    )


def score_product_clarity(s: dict) -> float:
    comps = s.get("clarity_components")
    if not comps:
        return 0.0
    return 100.0 * (sum(comps) / len(comps))


def score_guardrail(s: dict) -> float:
    if s.get("guardrails_broken"):
        return 0.0
    if s.get("advisory_tests_pass") and not s.get("execution_logic_added"):
        return 100.0
    if s.get("guardrails_exist"):
        return 50.0
    return 0.0


def score_reproducibility(s: dict) -> float:
    comps = [
        _bool(s.get("deterministic_manifest")),
        _bool(s.get("deterministic_scores")),
        _bool(s.get("cli_command_available")),
        _bool(s.get("report_written")),
        _bool(s.get("tests_available")),
    ]
    return 100.0 * (sum(comps) / len(comps))


def score_dashboard(s: dict) -> float:
    comps = [
        _bool(s.get("report_exists")),
        _bool(s.get("segmented_scores_visible")),
        _bool(s.get("provenance_visible")),
        _bool(s.get("limitations_visible")),
        _bool(s.get("no_fake_live_claims")),
    ]
    return 100.0 * (sum(comps) / len(comps))


_SCORERS = {
    "evidence_ingestion_robustness": score_evidence_ingestion,
    "data_provenance_completeness": score_provenance,
    "parser_coverage": score_parser_coverage,
    "simulation_volume": score_simulation_volume,
    "noise_handling": score_noise_handling,
    "calibration_hardening": score_calibration_hardening,
    "high_confidence_failure_handling": score_high_confidence_failure,
    "delayed_outcome_handling": score_delayed_outcome,
    "product_mvp_clarity": score_product_clarity,
    "advisory_guardrail_preservation": score_guardrail,
    "reproducibility": score_reproducibility,
    "dashboard_reporting_usefulness": score_dashboard,
}


def _scores_for(signals: dict[str, dict], *, provenance_present: bool) -> dict[str, float]:
    out: dict[str, float] = {}
    for cat, fn in _SCORERS.items():
        val = round(fn(signals.get(cat, {})), 4)
        # Provenance-missing cap on evidence/provenance categories.
        if not provenance_present and cat in (
            "evidence_ingestion_robustness", "data_provenance_completeness"
        ):
            val = min(val, 50.0)
        out[cat] = round(val, 4)
    return out


def compute_segmented_scores(
    before_signals: dict[str, dict],
    after_signals: dict[str, dict],
    *,
    weights: dict[str, float] | None = None,
    tests_pass: bool,
    guardrails_ok: bool,
    provenance_present: bool,
) -> dict[str, object]:
    """Compute the full segmented before/after score report (deterministic)."""
    weights = weights or DEFAULT_WEIGHTS
    assert_weights_sum_to_one(weights)

    before = _scores_for(before_signals, provenance_present=True)
    after = _scores_for(after_signals, provenance_present=provenance_present)

    overall_before = round(sum(weights[c] * before[c] for c in weights), 4)
    overall_after_raw = round(sum(weights[c] * after[c] for c in weights), 4)

    caps: list[str] = []
    overall_after = overall_after_raw
    if not tests_pass:
        overall_after = min(overall_after, 60.0)
        caps.append("tests_failed_cap_60")
    if not guardrails_ok:
        overall_after = min(overall_after, 30.0)
        caps.append("guardrails_broken_cap_30")
    overall_after = round(overall_after, 4)

    segments: dict[str, dict] = {}
    for cat in weights:
        b, a = before[cat], after[cat]
        delta = round(a - b, 4)
        segments[cat] = {
            "before": b,
            "after": a,
            "delta": delta,
            "relative_lift": round(delta / max(b, 1.0), 6),
            "relative_lift_pct": round(100.0 * delta / max(b, 1.0), 4),
            "weight": weights[cat],
            "label": CATEGORY_LABELS.get(cat, "SIMULATION_ONLY"),
        }

    overall_delta = round(overall_after - overall_before, 4)
    return {
        "segments": segments,
        "overall": {
            "overall_before": overall_before,
            "overall_after": overall_after,
            "overall_after_uncapped": overall_after_raw,
            "overall_delta": overall_delta,
            "overall_relative_lift": round(overall_delta / max(overall_before, 1.0), 6),
            "overall_relative_lift_pct": round(
                100.0 * overall_delta / max(overall_before, 1.0), 4
            ),
            "caps_applied": caps,
            "label": "SIMULATION_ONLY",
        },
        "weights": dict(weights),
    }


__all__ = [
    "DEFAULT_WEIGHTS",
    "CATEGORY_LABELS",
    "H_TARGET",
    "DELAYED_TARGET",
    "VOLUME_TAU",
    "assert_weights_sum_to_one",
    "compute_segmented_scores",
]
