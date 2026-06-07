"""Stage 3 — Mechanical Aggregator.

Reads the five isolated model-lane outputs (Stage 2) and computes agreement,
contradiction, freshness, chaos, concentration and a manual-review score for
each candidate — purely mechanically. It NEVER calls a model and NEVER invents a
candidate. Every candidate it scores must already be in the clean Fresh
Discovery Payload; anything else is excluded.

The scoring vocabulary and weights are fixed (verbatim from the spec) so the
board is reproducible and auditable. Hard overrides guarantee a non-live or
provenance-violating name can never rank above ``RISK_BLOCK``, and when there is
no fresh discovery the consensus board is empty.

Advisory-only. No broker, no order generation, no position sizing, no buy/sell
commands. Pure module: importing it has no side effects.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps, human_only_stamp
    from scripts.daily_payload import normalize_ticker
    from scripts.fresh_discovery_contract import VERIFIED_LIVE
    from scripts.isolated_model_lanes import FRESH_DISCOVERY_OK
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps, human_only_stamp
    from daily_payload import normalize_ticker
    from fresh_discovery_contract import VERIFIED_LIVE
    from isolated_model_lanes import FRESH_DISCOVERY_OK


# ---------------------------------------------------------------------------
# Qualitative -> numeric maps (verbatim from the spec)
# ---------------------------------------------------------------------------

EVIDENCE_NUMERIC: dict[str, float] = {"HIGH": 1.00, "MEDIUM": 0.65, "LOW": 0.30, "MISSING": 0.00}
RISK_NUMERIC: dict[str, float] = {"LOW": 0.00, "MEDIUM": 0.35, "HIGH": 0.75}
CONFIDENCE_NUMERIC: dict[str, float] = {"HIGH": 1.00, "MEDIUM": 0.65, "LOW": 0.30}

# Classification bands on the 0-100 manual-review score.
CLASS_MANUAL = "MANUAL_CONSIDERATION"
CLASS_WATCH = "WATCH"
CLASS_WAIT = "WAIT"
CLASS_AVOID = "AVOID"
CLASS_RISK_BLOCK = "RISK_BLOCK"

# Higher rank = less restrictive. Used to apply "max classification" overrides.
_CLASS_RANK = {
    CLASS_RISK_BLOCK: 0,
    CLASS_AVOID: 1,
    CLASS_WAIT: 2,
    CLASS_WATCH: 3,
    CLASS_MANUAL: 4,
}
_RANK_CLASS = {rank: name for name, rank in _CLASS_RANK.items()}

# Classifications that count as positive support / as avoid pressure.
_POSITIVE = {CLASS_MANUAL, CLASS_WATCH}
_AVOID_PRESSURE = {CLASS_AVOID, CLASS_RISK_BLOCK}

# The output lists a per-candidate item may live in, with its classification.
_OUTPUT_LISTS = {
    "manual_consideration": CLASS_MANUAL,
    "watch": CLASS_WATCH,
    "wait": CLASS_WAIT,
    "avoid": CLASS_AVOID,
    "risk_blocks": CLASS_RISK_BLOCK,
}


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------------------
# Per-model review extraction
# ---------------------------------------------------------------------------

def _ticker_reviews(ticker: str, outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one normalized review record per model that classified ``ticker``.

    A model "reviewed" the ticker if it placed it in any classification list.
    The record carries the classification + numeric grades for that model.
    """
    ticker = normalize_ticker(ticker)
    reviews: list[dict[str, Any]] = []
    for output in outputs:
        model = str(output.get("model") or "").lower()
        found: dict[str, Any] | None = None
        for list_key, classification in _OUTPUT_LISTS.items():
            for item in output.get(list_key) or []:
                if normalize_ticker(item.get("ticker")) == ticker:
                    found = {
                        "model": model,
                        "classification": item.get("classification") or classification,
                        "evidence_strength": str(item.get("evidence_strength") or "LOW").upper(),
                        "model_confidence": str(
                            item.get("model_confidence") or output.get("model_confidence") or "LOW"
                        ).upper(),
                        "contradiction_risk": str(item.get("contradiction_risk") or "LOW").upper(),
                        "chaos_risk": str(item.get("chaos_risk") or "LOW").upper(),
                    }
                    break
            if found:
                break
        if found:
            reviews.append(found)
    return reviews


# ---------------------------------------------------------------------------
# Component scores
# ---------------------------------------------------------------------------

def compute_model_agreement(candidate: dict[str, Any], outputs: list[dict[str, Any]]) -> dict[str, float]:
    """agreement / manual_support / avoid_pressure for one candidate."""
    n = len(outputs)
    if n == 0:
        return {"agreement": 0.0, "manual_support": 0.0, "avoid_pressure": 0.0, "reviewing_models": 0}
    reviews = _ticker_reviews(candidate.get("ticker"), outputs)
    positive = sum(1 for r in reviews if r["classification"] in _POSITIVE)
    manual = sum(1 for r in reviews if r["classification"] == CLASS_MANUAL)
    avoid = sum(1 for r in reviews if r["classification"] in _AVOID_PRESSURE)
    return {
        "agreement": round(positive / n, 6),
        "manual_support": round(manual / n, 6),
        "avoid_pressure": round(avoid / n, 6),
        "reviewing_models": len(reviews),
    }


def compute_contradiction_score(candidate: dict[str, Any], outputs: list[dict[str, Any]]) -> dict[str, float]:
    """avg contradiction-risk and avg chaos-risk across reviewing models."""
    reviews = _ticker_reviews(candidate.get("ticker"), outputs)
    contradiction = _mean([RISK_NUMERIC.get(r["contradiction_risk"], 0.0) for r in reviews])
    chaos = _mean([RISK_NUMERIC.get(r["chaos_risk"], 0.0) for r in reviews])
    # Split-vote contradiction: both positive support and avoid pressure present.
    has_positive = any(r["classification"] in _POSITIVE for r in reviews)
    has_avoid = any(r["classification"] in _AVOID_PRESSURE for r in reviews)
    return {
        "avg_contradiction_risk": round(contradiction, 6),
        "avg_chaos_risk": round(chaos, 6),
        "split_vote": bool(has_positive and has_avoid),
    }


def compute_evidence_confidence(candidate: dict[str, Any], outputs: list[dict[str, Any]]) -> dict[str, float]:
    reviews = _ticker_reviews(candidate.get("ticker"), outputs)
    evidence = _mean([EVIDENCE_NUMERIC.get(r["evidence_strength"], 0.0) for r in reviews])
    confidence = _mean([CONFIDENCE_NUMERIC.get(r["model_confidence"], 0.0) for r in reviews])
    return {"avg_evidence": round(evidence, 6), "avg_confidence": round(confidence, 6)}


def compute_freshness_score(candidate: dict[str, Any], provenance: dict[str, Any]) -> float:
    """1.0 iff VERIFIED_LIVE and current-session; else 0.0.

    ``provenance`` carries the candidate's source_health / is_live /
    last_live_seen_date plus the run_date to compare against.
    """
    run_date = provenance.get("run_date")
    if provenance.get("source_health") != VERIFIED_LIVE:
        return 0.0
    if provenance.get("is_live") is not True:
        return 0.0
    last = provenance.get("last_live_seen_date")
    if run_date and last and str(last) == str(run_date):
        return 1.0
    return 0.0


def _band_for_share(share: float) -> float:
    if share > 0.75:
        return 0.45
    if share > 0.60:
        return 0.30
    if share > 0.40:
        return 0.15
    return 0.0


def compute_concentration_penalty(candidate: dict[str, Any], all_candidates: list[dict[str, Any]]) -> float:
    """Penalize over-concentration in the candidate's region or theme.

    UNKNOWN region/theme values do not form a concentration bucket, so a board
    of descriptively-unlabelled live names is not penalized for being "all
    UNKNOWN".
    """
    total = len(all_candidates)
    if total <= 1:
        return 0.0
    penalty = 0.0
    for field in ("region", "theme"):
        value = candidate.get(field)
        if not value or str(value).strip().upper() == "UNKNOWN":
            continue
        share = sum(1 for c in all_candidates if c.get(field) == value) / total
        penalty = max(penalty, _band_for_share(share))
    return round(penalty, 6)


def _classify_score(score_100: float) -> str:
    if score_100 >= 85:
        return CLASS_MANUAL
    if score_100 >= 70:
        return CLASS_WATCH
    if score_100 >= 55:
        return CLASS_WAIT
    if score_100 >= 40:
        return CLASS_AVOID
    return CLASS_RISK_BLOCK


def _cap_classification(classification: str, max_classification: str) -> str:
    """Return the more restrictive of ``classification`` and ``max_classification``."""
    if _CLASS_RANK[classification] > _CLASS_RANK[max_classification]:
        return max_classification
    return classification


def compute_manual_review_score(
    candidate: dict[str, Any],
    outputs: list[dict[str, Any]],
    provenance: dict[str, Any],
    concentration: float,
) -> dict[str, Any]:
    """Mechanical manual-review score (0-100) + classification with overrides.

    Interpretation defense (IDS) is folded in as a positive 0.17 component and as
    hard classification overrides (BLOCKED / DEFENSIVE_REVIEW / CAUTION). A
    candidate with no interpretation_defense attached is RISK_BLOCK (fail-closed).
    """
    agreement = compute_model_agreement(candidate, outputs)
    contradiction = compute_contradiction_score(candidate, outputs)
    ev_conf = compute_evidence_confidence(candidate, outputs)
    freshness = compute_freshness_score(candidate, provenance)

    # Prefer the expanded P2 grade/score when attached; fall back to P1.
    expanded = candidate.get("expanded_interpretation_defense")
    expanded = expanded if isinstance(expanded, dict) else None
    p1_defense = candidate.get("interpretation_defense")
    p1_defense = p1_defense if isinstance(p1_defense, dict) else None
    if expanded:
        ids_grade = expanded.get("expanded_grade")
        ids_score = float(expanded.get("expanded_ids") or 0.0)
        defense_present = True
        using_expanded = True
    elif p1_defense:
        ids_grade = p1_defense.get("interpretation_defense_grade")
        ids_score = float(p1_defense.get("interpretation_defense_score") or 0.0)
        defense_present = True
        using_expanded = False
    else:
        ids_grade, ids_score, defense_present, using_expanded = None, 0.0, False, False
    ids_component = ids_score / 100.0

    raw = (
        0.18 * agreement["agreement"]
        + 0.14 * agreement["manual_support"]
        + 0.14 * ev_conf["avg_evidence"]
        + 0.10 * ev_conf["avg_confidence"]
        + 0.12 * freshness
        + 0.17 * ids_component
        - 0.08 * contradiction["avg_contradiction_risk"]
        - 0.08 * contradiction["avg_chaos_risk"]
        - 0.04 * agreement["avoid_pressure"]
        - concentration
    )
    score_100 = round(100.0 * _clamp01(raw), 4)
    classification = _classify_score(score_100)

    # ----- Hard overrides (fail-closed) -----
    overrides: list[str] = []
    provenance_violation = (
        bool(provenance.get("provenance_violation"))
        or candidate.get("allowed_in_fresh_discovery") is False
    )
    if provenance_violation:
        classification = CLASS_RISK_BLOCK
        overrides.append("provenance_violation->RISK_BLOCK")
    if freshness == 0.0:
        classification = _cap_classification(classification, CLASS_RISK_BLOCK)
        overrides.append("freshness=0->max_RISK_BLOCK")
    if provenance.get("source_health") != VERIFIED_LIVE:
        classification = _cap_classification(classification, CLASS_RISK_BLOCK)
        overrides.append("source_health!=VERIFIED_LIVE->max_RISK_BLOCK")

    # ----- Interpretation-defense overrides (expanded P2 grade wins) -----
    manual_count = round(agreement["manual_support"] * len(outputs))
    no_hard_risk = freshness == 1.0 and provenance.get("source_health") == VERIFIED_LIVE
    caution_quorum = 5 if using_expanded else 4
    tag = "expanded_ids" if using_expanded else "ids"
    if not defense_present:
        classification = CLASS_RISK_BLOCK
        overrides.append("interpretation_defense_missing->RISK_BLOCK")
    elif ids_grade == "BLOCKED":
        classification = CLASS_RISK_BLOCK
        overrides.append(f"{tag}_blocked->RISK_BLOCK")
    elif ids_grade == "DEFENSIVE_REVIEW":
        classification = _cap_classification(classification, CLASS_WAIT)
        overrides.append(f"{tag}_defensive_review->max_WAIT")
    elif ids_grade == "CAUTION":
        if not (manual_count >= caution_quorum and no_hard_risk):
            classification = _cap_classification(classification, CLASS_WATCH)
            overrides.append(f"{tag}_caution->max_WATCH")

    return {
        "ticker": normalize_ticker(candidate.get("ticker")),
        "manual_review_score": score_100,
        "classification": classification,
        "agreement": agreement["agreement"],
        "manual_support": agreement["manual_support"],
        "avoid_pressure": agreement["avoid_pressure"],
        "avg_evidence": ev_conf["avg_evidence"],
        "avg_confidence": ev_conf["avg_confidence"],
        "avg_contradiction_risk": contradiction["avg_contradiction_risk"],
        "avg_chaos_risk": contradiction["avg_chaos_risk"],
        "split_vote": contradiction["split_vote"],
        "freshness": freshness,
        "concentration_penalty": concentration,
        "reviewing_models": agreement["reviewing_models"],
        "interpretation_defense_grade": ids_grade,
        "interpretation_defense_score": ids_score if defense_present else None,
        "interpretation_defense_component": round(ids_component, 6),
        "uses_expanded_defense": using_expanded,
        "expanded_grade": (expanded.get("expanded_grade") if expanded else None),
        "expanded_ids": (expanded.get("expanded_ids") if expanded else None),
        "p2_grades": (
            {
                "distribution_amplification": expanded.get("distribution_amplification_grade"),
                "narrative_substance_gap": expanded.get("narrative_substance_gap_grade"),
                "incentive_risk": expanded.get("incentive_risk_grade"),
                "audience_misinterpretation": expanded.get("audience_misinterpretation_grade"),
            }
            if expanded else None
        ),
        "hard_overrides": overrides,
    }


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------

def _provenance_for(candidate: dict[str, Any], run_date: str | None) -> dict[str, Any]:
    return {
        "source_health": candidate.get("source_health"),
        "is_live": candidate.get("is_live"),
        "last_live_seen_date": candidate.get("last_live_seen_date"),
        "allowed_in_fresh_discovery": candidate.get("allowed_in_fresh_discovery"),
        "run_date": run_date,
    }


def build_candidate_consensus_board(
    outputs: list[dict[str, Any]],
    clean_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Rank ONLY clean-payload candidates. Empty when no fresh discovery."""
    if clean_payload.get("fresh_discovery_status") != FRESH_DISCOVERY_OK:
        return []
    candidates = clean_payload.get("candidates", [])
    run_date = clean_payload.get("run_date")
    board: list[dict[str, Any]] = []
    for candidate in candidates:
        concentration = compute_concentration_penalty(candidate, candidates)
        provenance = _provenance_for(candidate, run_date)
        board.append(
            compute_manual_review_score(candidate, outputs, provenance, concentration)
        )
    board.sort(key=lambda r: (-r["manual_review_score"], r["ticker"]))
    return board


def build_model_vote_matrix(
    outputs: list[dict[str, Any]],
    clean_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Per-candidate, per-model classification matrix (clean payload only)."""
    matrix: list[dict[str, Any]] = []
    for candidate in clean_payload.get("candidates", []):
        ticker = normalize_ticker(candidate.get("ticker"))
        votes: dict[str, str] = {}
        for review in _ticker_reviews(ticker, outputs):
            votes[review["model"]] = review["classification"]
        defense = candidate.get("interpretation_defense") or {}
        expanded = candidate.get("expanded_interpretation_defense") or {}
        matrix.append(
            {
                "ticker": ticker,
                "votes": votes,
                "reviewing_models": len(votes),
                "interpretation_defense_grade": defense.get("interpretation_defense_grade"),
                "interpretation_defense_score": defense.get("interpretation_defense_score"),
                "iqs": defense.get("iqs"),
                "mtr": defense.get("mtr"),
                "stress_failure_risk": defense.get("stress_failure_risk"),
                "expanded_grade": expanded.get("expanded_grade"),
                "expanded_ids": expanded.get("expanded_ids"),
                "distribution_amplification_grade": expanded.get("distribution_amplification_grade"),
                "narrative_substance_gap_grade": expanded.get("narrative_substance_gap_grade"),
                "incentive_risk_grade": expanded.get("incentive_risk_grade"),
                "audience_misinterpretation_grade": expanded.get("audience_misinterpretation_grade"),
            }
        )
    return matrix


def build_contradiction_report(
    board: list[dict[str, Any]],
    matrix: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Surface split-vote candidates (positive support AND avoid pressure)."""
    votes_by_ticker = {row["ticker"]: row["votes"] for row in matrix}
    ids_by_ticker = {
        row["ticker"]: (row.get("expanded_grade") or row.get("interpretation_defense_grade"))
        for row in matrix
    }
    report: list[dict[str, Any]] = []
    for row in board:
        votes = votes_by_ticker.get(row["ticker"], {})
        ids_grade = ids_by_ticker.get(row["ticker"])
        model_promoted = any(v in _POSITIVE for v in votes.values())
        defense_disagreement = bool(
            model_promoted and ids_grade in ("BLOCKED", "DEFENSIVE_REVIEW")
        )
        if not row.get("split_vote") and not defense_disagreement:
            continue
        report.append(
            {
                "ticker": row["ticker"],
                "votes": votes,
                "avg_contradiction_risk": row["avg_contradiction_risk"],
                "manual_review_score": row["manual_review_score"],
                "classification": row["classification"],
                "interpretation_defense_grade": ids_grade,
                "model_vs_interpretation_defense": defense_disagreement,
            }
        )
    return report


def aggregate_model_lane_outputs(
    outputs: list[dict[str, Any]],
    clean_payload: dict[str, Any],
) -> dict[str, Any]:
    """Top-level mechanical aggregation. No model is called; no name invented."""
    status = clean_payload.get("fresh_discovery_status")
    if status != FRESH_DISCOVERY_OK:
        return {
            "status": status,
            "run_date": clean_payload.get("run_date"),
            "valid_model_output_count": len(outputs),
            "candidate_consensus": [],
            "model_vote_matrix": [],
            "contradiction_report": [],
            "manual_consideration": [],
            "watch": [],
            "note": "No fresh discovery; consensus board intentionally empty.",
            "safety": advisory_safety_stamps(),
            "execution": human_only_stamp(),
        }

    board = build_candidate_consensus_board(outputs, clean_payload)
    matrix = build_model_vote_matrix(outputs, clean_payload)
    contradictions = build_contradiction_report(board, matrix)

    manual = [r["ticker"] for r in board if r["classification"] == CLASS_MANUAL]
    watch = [r["ticker"] for r in board if r["classification"] == CLASS_WATCH]

    return {
        "status": FRESH_DISCOVERY_OK,
        "run_date": clean_payload.get("run_date"),
        "valid_model_output_count": len(outputs),
        "candidate_count": len(clean_payload.get("candidates", [])),
        "candidate_consensus": board,
        "model_vote_matrix": matrix,
        "contradiction_report": contradictions,
        "manual_consideration": manual,
        "watch": watch,
        "safety": advisory_safety_stamps(),
        "execution": human_only_stamp(),
    }


__all__ = [
    "EVIDENCE_NUMERIC",
    "RISK_NUMERIC",
    "CONFIDENCE_NUMERIC",
    "CLASS_MANUAL",
    "CLASS_WATCH",
    "CLASS_WAIT",
    "CLASS_AVOID",
    "CLASS_RISK_BLOCK",
    "compute_model_agreement",
    "compute_contradiction_score",
    "compute_evidence_confidence",
    "compute_freshness_score",
    "compute_concentration_penalty",
    "compute_manual_review_score",
    "build_candidate_consensus_board",
    "build_model_vote_matrix",
    "build_contradiction_report",
    "aggregate_model_lane_outputs",
]
