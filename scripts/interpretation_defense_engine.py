"""Interpretation Defense Engine — unifies the three P1 modules.

Combines Interpretation Quality Score (IQS), Metric Regime Transfer Risk (MTR)
and Adverse Regime Stress Test (ARST) into a single per-candidate
Interpretation Defense Score (IDS) + grade, plus convenience functions to attach
a compact result onto a clean fresh-discovery payload and to build a board for
the final auditor / runtime artifacts.

    IDS = 0.45*IQS + 0.25*(100 - MTR) + 0.30*(100 - StressFailureRisk)

IDS is a QUALITY/RISK layer, not a trade signal. It can only *demote* — it never
invents a candidate, never overrides the Fresh Discovery Contract, and never
authorises execution. When there is no fresh discovery it skips entirely.
Advisory-only. Pure module.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps, human_only_stamp
    from scripts.adverse_regime_stress_test import (
        GRADE_INSUFFICIENT,
        stress_test_candidate,
    )
    from scripts.audience_misinterpretation_risk import score_audience_misinterpretation
    from scripts.daily_payload import normalize_ticker
    from scripts.distribution_amplification_detector import score_distribution_amplification
    from scripts.fresh_discovery_contract import VERIFIED_LIVE
    from scripts.incentive_who_benefits_analyzer import score_incentive_who_benefits
    from scripts.interpretation_quality_score import score_interpretation_quality
    from scripts.isolated_model_lanes import FRESH_DISCOVERY_OK
    from scripts.metric_regime_transfer_risk import score_metric_regime_transfer_risk
    from scripts.narrative_substance_gap import score_narrative_substance_gap
    from scripts.signal_half_life_estimator import CLASS_SNACK, score_signal_half_life
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps, human_only_stamp
    from adverse_regime_stress_test import GRADE_INSUFFICIENT, stress_test_candidate
    from audience_misinterpretation_risk import score_audience_misinterpretation
    from daily_payload import normalize_ticker
    from distribution_amplification_detector import score_distribution_amplification
    from fresh_discovery_contract import VERIFIED_LIVE
    from incentive_who_benefits_analyzer import score_incentive_who_benefits
    from interpretation_quality_score import score_interpretation_quality
    from isolated_model_lanes import FRESH_DISCOVERY_OK
    from metric_regime_transfer_risk import score_metric_regime_transfer_risk
    from narrative_substance_gap import score_narrative_substance_gap
    from signal_half_life_estimator import CLASS_SNACK, score_signal_half_life


GRADE_CLEAN = "CLEAN"
GRADE_CAUTION = "CAUTION"
GRADE_DEFENSIVE = "DEFENSIVE_REVIEW"
GRADE_BLOCKED = "BLOCKED"

STATUS_COMPLETED = "INTERPRETATION_DEFENSE_COMPLETED"
STATUS_SKIPPED = "SKIPPED_NO_FRESH_DISCOVERY"

_RANK = {GRADE_BLOCKED: 0, GRADE_DEFENSIVE: 1, GRADE_CAUTION: 2, GRADE_CLEAN: 3}


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _cap(grade: str, max_grade: str) -> str:
    return max_grade if _RANK[grade] > _RANK[max_grade] else grade


def _base_grade(ids: float) -> str:
    if ids >= 80:
        return GRADE_CLEAN
    if ids >= 65:
        return GRADE_CAUTION
    if ids >= 45:
        return GRADE_DEFENSIVE
    return GRADE_BLOCKED


def evaluate_candidate(
    candidate: dict[str, Any],
    *,
    run_date: str | None = None,
    reference_regime: dict[str, Any] | None = None,
    fundamentals: dict[str, Any] | None = None,
    model_outputs: list[dict[str, Any]] | None = None,
    aggregator_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full interpretation-defense evaluation for one candidate."""
    ticker = normalize_ticker(candidate.get("ticker"))
    iqs = score_interpretation_quality(
        candidate, run_date=run_date, model_outputs=model_outputs, aggregator_row=aggregator_row
    )
    mtr = score_metric_regime_transfer_risk(
        candidate, reference_regime=reference_regime, model_outputs=model_outputs, run_date=run_date
    )
    stress = stress_test_candidate(candidate, fundamentals=fundamentals, model_outputs=model_outputs)

    iqs_v = float(iqs["interpretation_quality_score"])
    mtr_v = float(mtr["metric_regime_transfer_risk"])
    sfr_v = float(stress["stress_failure_risk"])

    ids = round(0.45 * iqs_v + 0.25 * (100.0 - mtr_v) + 0.30 * (100.0 - sfr_v), 4)
    grade = _base_grade(ids)

    hard_blocks: list[str] = []
    warnings: list[str] = []

    if candidate.get("source_health") != VERIFIED_LIVE:
        grade = GRADE_BLOCKED
        hard_blocks.append("source_health_not_verified_live")
    if candidate.get("allowed_in_fresh_discovery") is not True:
        grade = GRADE_BLOCKED
        hard_blocks.append("not_allowed_in_fresh_discovery")
    if candidate.get("provenance_violation") is True:
        grade = GRADE_BLOCKED
        hard_blocks.append("provenance_violation")
    if iqs_v < 40:
        grade = _cap(grade, GRADE_DEFENSIVE)
        warnings.append("iqs_below_40")
    if mtr_v > 75:
        grade = _cap(grade, GRADE_DEFENSIVE)
        warnings.append("mtr_above_75")
    if stress["grade"] == GRADE_INSUFFICIENT:
        grade = _cap(grade, GRADE_DEFENSIVE)
        warnings.append("stress_insufficient_data")

    return {
        "ticker": ticker,
        "interpretation_quality": iqs,
        "metric_transfer_risk": mtr,
        "adverse_regime_stress": stress,
        "interpretation_defense_score": ids,
        "interpretation_defense_grade": grade,
        "hard_blocks": hard_blocks,
        "warnings": warnings,
        "advisory_only": True,
    }


def _compact(full: dict[str, Any]) -> dict[str, Any]:
    return {
        "interpretation_defense_score": full["interpretation_defense_score"],
        "interpretation_defense_grade": full["interpretation_defense_grade"],
        "iqs": full["interpretation_quality"]["interpretation_quality_score"],
        "iqs_grade": full["interpretation_quality"]["grade"],
        "mtr": full["metric_transfer_risk"]["metric_regime_transfer_risk"],
        "stress_failure_risk": full["adverse_regime_stress"]["stress_failure_risk"],
        "stress_grade": full["adverse_regime_stress"]["grade"],
        "hard_blocks": full["hard_blocks"],
        "warnings": full["warnings"],
    }


def run_interpretation_defense(
    clean_payload: dict[str, Any],
    *,
    model_outputs: list[dict[str, Any]] | None = None,
    aggregator: dict[str, Any] | None = None,
    fundamentals_by_ticker: dict[str, dict[str, Any]] | None = None,
    reference_regime_by_ticker: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate every clean-payload candidate. Skips when no fresh discovery."""
    status = clean_payload.get("fresh_discovery_status")
    run_date = clean_payload.get("run_date")
    if status != FRESH_DISCOVERY_OK:
        return {
            "status": STATUS_SKIPPED,
            "run_date": run_date,
            "reason": f"fresh_discovery_status={status}; interpretation defense not run.",
            "board": [],
            "completed_count": 0,
            "blocked_count": 0,
            "safety": advisory_safety_stamps(),
            "execution": human_only_stamp(),
        }

    fundamentals_by_ticker = fundamentals_by_ticker or {}
    reference_regime_by_ticker = reference_regime_by_ticker or {}
    agg_rows = {
        r.get("ticker"): r for r in (aggregator or {}).get("candidate_consensus", [])
    } if aggregator else {}

    board: list[dict[str, Any]] = []
    for candidate in clean_payload.get("candidates", []):
        ticker = normalize_ticker(candidate.get("ticker"))
        board.append(
            evaluate_candidate(
                candidate,
                run_date=run_date,
                reference_regime=reference_regime_by_ticker.get(ticker),
                fundamentals=fundamentals_by_ticker.get(ticker),
                model_outputs=model_outputs,
                aggregator_row=agg_rows.get(ticker),
            )
        )

    blocked = [b for b in board if b["interpretation_defense_grade"] == GRADE_BLOCKED]
    return {
        "status": STATUS_COMPLETED,
        "run_date": run_date,
        "board": board,
        "completed_count": len(board),
        "blocked_count": len(blocked),
        "blocked_tickers": [b["ticker"] for b in blocked],
        "safety": advisory_safety_stamps(),
        "execution": human_only_stamp(),
    }


def attach_defense_to_payload(
    clean_payload: dict[str, Any], defense_result: dict[str, Any]
) -> dict[str, Any]:
    """Return a copy of the clean payload with a compact IDS on each candidate."""
    if defense_result.get("status") != STATUS_COMPLETED:
        return clean_payload
    compact_by_ticker = {
        normalize_ticker(b["ticker"]): _compact(b) for b in defense_result.get("board", [])
    }
    new_payload = dict(clean_payload)
    new_candidates: list[dict[str, Any]] = []
    for candidate in clean_payload.get("candidates", []):
        c = dict(candidate)
        compact = compact_by_ticker.get(normalize_ticker(c.get("ticker")))
        if compact is not None:
            c["interpretation_defense"] = compact
        new_candidates.append(c)
    new_payload["candidates"] = new_candidates
    return new_payload


def enrich_clean_payload(
    clean_payload: dict[str, Any], **opts: Any
) -> dict[str, Any]:
    """Convenience: run defense and attach compact results to the payload."""
    result = run_interpretation_defense(clean_payload, **opts)
    return attach_defense_to_payload(clean_payload, result)


# ---------------------------------------------------------------------------
# P2 — expanded interpretation defense
# ---------------------------------------------------------------------------

STATUS_P2_COMPLETED = "P2_INTERPRETATION_EXPANSION_COMPLETED"

# P2 grades that force at most DEFENSIVE_REVIEW.
_P2_DEFENSIVE_GRADES = {
    "distribution_amplification": "HYPE_LED",
    "narrative_substance_gap": "NARRATIVE_OVERHANG",
    "incentive_who_benefits": "EXIT_LIQUIDITY_RISK",
    "audience_misinterpretation": "MISREAD_LIKELY",
}


def evaluate_candidate_expanded(
    candidate: dict[str, Any],
    *,
    p1_full: dict[str, Any] | None = None,
    run_date: str | None = None,
    reference_regime: dict[str, Any] | None = None,
    fundamentals: dict[str, Any] | None = None,
    attention: dict[str, Any] | None = None,
    ownership: dict[str, Any] | None = None,
    liquidity: dict[str, Any] | None = None,
    crowding: dict[str, Any] | None = None,
    model_outputs: list[dict[str, Any]] | None = None,
    aggregator_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """P1 + four P2 modules + P3 half-life → expanded IDS. Can only demote."""
    ticker = normalize_ticker(candidate.get("ticker"))
    if p1_full is None:
        p1_full = evaluate_candidate(
            candidate, run_date=run_date, reference_regime=reference_regime,
            fundamentals=fundamentals, model_outputs=model_outputs, aggregator_row=aggregator_row,
        )

    da = score_distribution_amplification(
        candidate, attention=attention, fundamentals=fundamentals, model_outputs=model_outputs
    )
    nsg = score_narrative_substance_gap(
        candidate, distribution=da, fundamentals=fundamentals, model_outputs=model_outputs, p1=p1_full
    )
    inc = score_incentive_who_benefits(
        candidate, ownership=ownership, distribution=da, narrative_gap=nsg,
        liquidity=liquidity, model_outputs=model_outputs,
    )
    amr = score_audience_misinterpretation(
        candidate, p1=p1_full, narrative_gap=nsg, distribution=da, model_outputs=model_outputs
    )
    hl = score_signal_half_life(
        candidate, fundamentals=fundamentals, attention=attention,
        crowding=crowding, model_outputs=model_outputs,
    )

    da_score = float(da["distribution_amplification_score"])
    nsg_pos = max(float(nsg["narrative_substance_gap"]), 0.0)
    inc_score = float(inc["incentive_risk_score"])
    amr_score = float(amr["audience_misinterpretation_risk"])
    hl_risk = float(hl["short_half_life_risk"])

    p2_penalty = 0.20 * da_score + 0.25 * nsg_pos + 0.30 * inc_score + 0.25 * amr_score
    p1_ids = float(p1_full["interpretation_defense_score"])
    # P2 penalty first (unchanged math), then layer the P3 half-life demotion so
    # the calibrated four-module formula is untouched. Both only subtract.
    expanded_ids = _clamp01_100(p1_ids - 0.35 * p2_penalty)
    half_life_penalty = round(0.15 * hl_risk, 4)
    expanded_ids = round(_clamp01_100(expanded_ids - half_life_penalty), 4)

    grade = _base_grade(expanded_ids)
    hard_blocks: list[str] = list(p1_full.get("hard_blocks", []))
    warnings: list[str] = []

    if p1_full["interpretation_defense_grade"] == GRADE_BLOCKED:
        grade = GRADE_BLOCKED
        hard_blocks.append("p1_blocked")
    if inc["grade"] == _P2_DEFENSIVE_GRADES["incentive_who_benefits"]:
        grade = _cap(grade, GRADE_DEFENSIVE)
        warnings.append("exit_liquidity_risk")
    if nsg["grade"] == _P2_DEFENSIVE_GRADES["narrative_substance_gap"]:
        grade = _cap(grade, GRADE_DEFENSIVE)
        warnings.append("narrative_overhang")
    if amr["grade"] == _P2_DEFENSIVE_GRADES["audience_misinterpretation"]:
        grade = _cap(grade, GRADE_DEFENSIVE)
        warnings.append("misread_likely")
    if da["grade"] == _P2_DEFENSIVE_GRADES["distribution_amplification"]:
        grade = _cap(grade, GRADE_DEFENSIVE)
        warnings.append("hype_led")
    if hl["half_life_class"] == CLASS_SNACK:
        grade = _cap(grade, GRADE_DEFENSIVE)
        warnings.append("short_half_life")

    # Surface missing P2/P3 data explicitly (not silently ignored).
    for mod in (da, nsg, inc, amr, hl):
        for f in mod.get("missing_fields", []):
            warnings.append(f"missing:{f}")

    return {
        "ticker": ticker,
        "p1_interpretation_defense": p1_full,
        "p2_interpretation_expansion": {
            "distribution_amplification": da,
            "narrative_substance_gap": nsg,
            "incentive_who_benefits": inc,
            "audience_misinterpretation": amr,
        },
        "p3_signal_half_life": hl,
        "expanded_interpretation_defense_score": expanded_ids,
        "expanded_grade": grade,
        "p2_penalty": round(p2_penalty, 4),
        "half_life_penalty": half_life_penalty,
        "hard_blocks": hard_blocks,
        "warnings": sorted(set(warnings)),
        "advisory_only": True,
    }


def _clamp01_100(value: float) -> float:
    return 0.0 if value < 0.0 else 100.0 if value > 100.0 else value


def run_expanded_interpretation_defense(
    clean_payload: dict[str, Any],
    *,
    p1_result: dict[str, Any] | None = None,
    model_outputs: list[dict[str, Any]] | None = None,
    aggregator: dict[str, Any] | None = None,
    fundamentals_by_ticker: dict[str, dict[str, Any]] | None = None,
    attention_by_ticker: dict[str, dict[str, Any]] | None = None,
    ownership_by_ticker: dict[str, dict[str, Any]] | None = None,
    liquidity_by_ticker: dict[str, dict[str, Any]] | None = None,
    crowding_by_ticker: dict[str, dict[str, Any]] | None = None,
    reference_regime_by_ticker: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the four P2 modules + P3 half-life + expanded IDS for every candidate."""
    status = clean_payload.get("fresh_discovery_status")
    run_date = clean_payload.get("run_date")
    if status != FRESH_DISCOVERY_OK:
        return {
            "status": STATUS_SKIPPED,
            "run_date": run_date,
            "reason": f"fresh_discovery_status={status}; P2 expansion not run.",
            "board": [],
            "completed_count": 0,
            "blocked_count": 0,
            "defensive_count": 0,
            "safety": advisory_safety_stamps(),
            "execution": human_only_stamp(),
        }

    fundamentals_by_ticker = fundamentals_by_ticker or {}
    attention_by_ticker = attention_by_ticker or {}
    ownership_by_ticker = ownership_by_ticker or {}
    liquidity_by_ticker = liquidity_by_ticker or {}
    crowding_by_ticker = crowding_by_ticker or {}
    reference_regime_by_ticker = reference_regime_by_ticker or {}
    p1_by_ticker = {
        normalize_ticker(b.get("ticker")): b for b in (p1_result or {}).get("board", [])
    }
    agg_rows = {
        r.get("ticker"): r for r in (aggregator or {}).get("candidate_consensus", [])
    } if aggregator else {}

    board: list[dict[str, Any]] = []
    for candidate in clean_payload.get("candidates", []):
        ticker = normalize_ticker(candidate.get("ticker"))
        board.append(
            evaluate_candidate_expanded(
                candidate,
                p1_full=p1_by_ticker.get(ticker),
                run_date=run_date,
                reference_regime=reference_regime_by_ticker.get(ticker),
                fundamentals=fundamentals_by_ticker.get(ticker),
                attention=attention_by_ticker.get(ticker),
                ownership=ownership_by_ticker.get(ticker),
                liquidity=liquidity_by_ticker.get(ticker),
                crowding=crowding_by_ticker.get(ticker),
                model_outputs=model_outputs,
                aggregator_row=agg_rows.get(ticker),
            )
        )

    blocked = [b for b in board if b["expanded_grade"] == GRADE_BLOCKED]
    defensive = [b for b in board if b["expanded_grade"] == GRADE_DEFENSIVE]
    return {
        "status": STATUS_P2_COMPLETED,
        "run_date": run_date,
        "board": board,
        "completed_count": len(board),
        "blocked_count": len(blocked),
        "defensive_count": len(defensive),
        "blocked_tickers": [b["ticker"] for b in blocked],
        "safety": advisory_safety_stamps(),
        "execution": human_only_stamp(),
    }


def _compact_expanded(full: dict[str, Any]) -> dict[str, Any]:
    p2 = full["p2_interpretation_expansion"]
    hl = full.get("p3_signal_half_life", {})
    return {
        "p1_ids": full["p1_interpretation_defense"]["interpretation_defense_score"],
        "p1_grade": full["p1_interpretation_defense"]["interpretation_defense_grade"],
        "expanded_ids": full["expanded_interpretation_defense_score"],
        "expanded_grade": full["expanded_grade"],
        "distribution_amplification_grade": p2["distribution_amplification"]["grade"],
        "narrative_substance_gap_grade": p2["narrative_substance_gap"]["grade"],
        "incentive_risk_grade": p2["incentive_who_benefits"]["grade"],
        "audience_misinterpretation_grade": p2["audience_misinterpretation"]["grade"],
        "half_life_class": hl.get("half_life_class"),
        "short_half_life_risk": hl.get("short_half_life_risk"),
        "hard_blocks": full["hard_blocks"],
        "warnings": full["warnings"],
    }


def attach_expanded_defense_to_payload(
    clean_payload: dict[str, Any], expanded_result: dict[str, Any]
) -> dict[str, Any]:
    """Attach a compact expanded IDS onto each candidate."""
    if expanded_result.get("status") != STATUS_P2_COMPLETED:
        return clean_payload
    compact_by_ticker = {
        normalize_ticker(b["ticker"]): _compact_expanded(b) for b in expanded_result.get("board", [])
    }
    new_payload = dict(clean_payload)
    new_candidates: list[dict[str, Any]] = []
    for candidate in clean_payload.get("candidates", []):
        c = dict(candidate)
        compact = compact_by_ticker.get(normalize_ticker(c.get("ticker")))
        if compact is not None:
            c["expanded_interpretation_defense"] = compact
        new_candidates.append(c)
    new_payload["candidates"] = new_candidates
    return new_payload


__all__ = [
    "GRADE_CLEAN",
    "GRADE_CAUTION",
    "GRADE_DEFENSIVE",
    "GRADE_BLOCKED",
    "STATUS_COMPLETED",
    "STATUS_SKIPPED",
    "STATUS_P2_COMPLETED",
    "evaluate_candidate",
    "run_interpretation_defense",
    "attach_defense_to_payload",
    "enrich_clean_payload",
    "evaluate_candidate_expanded",
    "run_expanded_interpretation_defense",
    "attach_expanded_defense_to_payload",
]
