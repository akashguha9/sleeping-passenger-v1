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
    from scripts.daily_payload import normalize_ticker
    from scripts.fresh_discovery_contract import VERIFIED_LIVE
    from scripts.interpretation_quality_score import score_interpretation_quality
    from scripts.isolated_model_lanes import FRESH_DISCOVERY_OK
    from scripts.metric_regime_transfer_risk import score_metric_regime_transfer_risk
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps, human_only_stamp
    from adverse_regime_stress_test import GRADE_INSUFFICIENT, stress_test_candidate
    from daily_payload import normalize_ticker
    from fresh_discovery_contract import VERIFIED_LIVE
    from interpretation_quality_score import score_interpretation_quality
    from isolated_model_lanes import FRESH_DISCOVERY_OK
    from metric_regime_transfer_risk import score_metric_regime_transfer_risk


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


__all__ = [
    "GRADE_CLEAN",
    "GRADE_CAUTION",
    "GRADE_DEFENSIVE",
    "GRADE_BLOCKED",
    "STATUS_COMPLETED",
    "STATUS_SKIPPED",
    "evaluate_candidate",
    "run_interpretation_defense",
    "attach_defense_to_payload",
    "enrich_clean_payload",
]
