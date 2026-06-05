"""Sprint 2 scorecard v2 (Phase 12): 18 weighted segments + caps.

The harness measures a `before` (Sprint-1 capability on this corpus) and an
`after` (Sprint-2 upgraded capability) score per segment in [0,100].  This
module applies the documented caps, weights them into an overall
simulation-readiness score, and computes deltas.  Everything is SIMULATION_ONLY.

NOTE: the spec's stated segment weights sum to 1.10, not 1.0 (the spec also
says "these weights sum to 1.00").  We preserve the intended emphasis but
normalize to a true simplex so the weighted overall stays on [0,100].
"""
from __future__ import annotations

SEGMENTS: tuple[str, ...] = (
    "local_corpus_accessibility",
    "safe_ingestion_robustness",
    "incremental_reproducibility_cache",
    "dataset_family_classification",
    "parser_coverage",
    "parsed_simulation_volume",
    "evidence_quality",
    "noise_duplicate_handling",
    "source_diversity",
    "market_data_readiness",
    "calibration_hardening",
    "abstention_overconfidence_discipline",
    "high_confidence_failure_handling",
    "delayed_outcome_handling",
    "product_mvp_clarity",
    "advisory_guardrail_preservation",
    "report_dashboard_usefulness",
    "test_coverage",
)

RAW_WEIGHTS_V2: dict[str, float] = {
    "local_corpus_accessibility": 0.06,
    "safe_ingestion_robustness": 0.08,
    "incremental_reproducibility_cache": 0.07,
    "dataset_family_classification": 0.06,
    "parser_coverage": 0.06,
    "parsed_simulation_volume": 0.05,
    "evidence_quality": 0.08,
    "noise_duplicate_handling": 0.06,
    "source_diversity": 0.04,
    "market_data_readiness": 0.06,
    "calibration_hardening": 0.08,
    "abstention_overconfidence_discipline": 0.08,
    "high_confidence_failure_handling": 0.06,
    "delayed_outcome_handling": 0.05,
    "product_mvp_clarity": 0.05,
    "advisory_guardrail_preservation": 0.08,
    "report_dashboard_usefulness": 0.04,
    "test_coverage": 0.04,
}

_RAW_SUM = sum(RAW_WEIGHTS_V2.values())
WEIGHTS_V2: dict[str, float] = {k: v / _RAW_SUM for k, v in RAW_WEIGHTS_V2.items()}

CATEGORY_LABELS: dict[str, str] = {
    "advisory_guardrail_preservation": "GOVERNANCE",
}


def assert_weights_sum_to_one(weights: dict[str, float], *, tol: float = 1e-9) -> None:
    total = sum(weights.values())
    if abs(total - 1.0) > tol:
        raise ValueError(f"scorecard weights must sum to 1.0, got {total}")


def _apply_segment_caps(after: dict[str, float], flags: dict) -> tuple[dict[str, float], list[str]]:
    capped = dict(after)
    notes: list[str] = []

    def cap(seg: str, ceiling: float, why: str) -> None:
        if capped.get(seg, 0.0) > ceiling:
            capped[seg] = ceiling
            notes.append(f"{seg}<= {ceiling} ({why})")

    if not flags.get("provenance_present", True):
        cap("evidence_quality", 50.0, "provenance_missing")
        cap("safe_ingestion_robustness", 60.0, "provenance_missing")
    if not flags.get("has_real_market_data", False):
        cap("market_data_readiness", 60.0, "no_real_market_data_detection_only")
    if not flags.get("has_labelled_outcomes", False):
        cap("calibration_hardening", 75.0, "no_labelled_outcomes_chess_synth_only")
    if not flags.get("has_parsed_records", False):
        for seg in ("parsed_simulation_volume", "evidence_quality", "source_diversity"):
            if capped.get(seg, 0.0) != 0.0:
                capped[seg] = 0.0
                notes.append(f"{seg}=0 (no_parsed_records)")
    return capped, notes


def compute_scorecard_v2(
    before: dict[str, float],
    after: dict[str, float],
    *,
    flags: dict,
    weights: dict[str, float] | None = None,
) -> dict[str, object]:
    weights = weights or WEIGHTS_V2
    assert_weights_sum_to_one(weights)

    after_capped, segment_cap_notes = _apply_segment_caps(after, flags)

    overall_before = round(sum(weights[s] * before.get(s, 0.0) for s in weights), 4)
    overall_after_raw = round(
        sum(weights[s] * after_capped.get(s, 0.0) for s in weights), 4
    )

    overall_caps: list[str] = []
    overall_after = overall_after_raw
    if not flags.get("zip_found", False):
        overall_after = min(overall_after, 40.0)
        overall_caps.append("zip_not_found_cap_40")
    if flags.get("safety_blocked", False):
        overall_after = min(overall_after, 50.0)
        overall_caps.append("safety_blocked_cap_50")
    if not flags.get("tests_pass", True):
        overall_after = min(overall_after, 60.0)
        overall_caps.append("tests_failed_cap_60")
    if not flags.get("guardrails_ok", True):
        overall_after = min(overall_after, 30.0)
        overall_caps.append("guardrails_broken_cap_30")
    overall_after = round(overall_after, 4)

    segments: dict[str, dict] = {}
    for s in weights:
        b = round(before.get(s, 0.0), 4)
        a = round(after_capped.get(s, 0.0), 4)
        delta = round(a - b, 4)
        segments[s] = {
            "before": b,
            "after": a,
            "delta": delta,
            "relative_lift": round(delta / max(b, 1.0), 6),
            "relative_lift_pct": round(100.0 * delta / max(b, 1.0), 4),
            "weight": round(weights[s], 6),
            "label": CATEGORY_LABELS.get(s, "SIMULATION_ONLY"),
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
            "segment_caps": segment_cap_notes,
            "overall_caps": overall_caps,
            "label": "SIMULATION_ONLY",
        },
        "weights": dict(weights),
        "raw_weights": dict(RAW_WEIGHTS_V2),
    }


__all__ = [
    "SEGMENTS",
    "RAW_WEIGHTS_V2",
    "WEIGHTS_V2",
    "assert_weights_sum_to_one",
    "compute_scorecard_v2",
]
