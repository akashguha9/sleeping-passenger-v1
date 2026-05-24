"""Daily scoring formulas — CQS -> ACQS -> FCS / ERS and final classification.

Brings together the sprint's signals into one scoring surface:

    CQS(t)   raw candidate quality (scripts/fresh_market_discovery.py)
    ACQS(t)  = CQS(t) * exp(-lambda * days_without_fresh_signal)   (memory decay)
    FCS(t)   final candidate score (cross-model + freshness + why-today + decay)
    ERS(t)   execution readiness score

Final classification requires freshness, memory decay, model disagreement, the
WHY_TODAY gate, source health, and the portfolio-truth exclusion (t ∉ C∪S∪D).
EXECUTABLE is the strictest tier and is always advisory-only / human-executed.

Pure module: no I/O, no broker, no execution.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.candidate_memory_decay import adjusted_cqs
    from scripts.daily_discovery_config import load_discovery_thresholds
    from scripts.daily_payload import normalize_ticker
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from candidate_memory_decay import adjusted_cqs
    from daily_discovery_config import load_discovery_thresholds
    from daily_payload import normalize_ticker


FCS_WEIGHTS = {
    "acqs": 0.25,
    "mean_model_score": 0.20,
    "cross_model_agreement": 0.15,
    "why_today_score": 0.15,
    "data_quality": 0.10,
    "freshness_score": 0.10,
    "liquidity_quality": 0.05,
}
FCS_PENALTIES = {"chaos_risk": 0.10, "normalized_disagreement": 0.10, "portfolio_contamination_penalty": 0.15}

ERS_WEIGHTS = {
    "data_quality": 0.25,
    "source_health_score": 0.20,
    "invalidation_defined": 0.15,
    "position_sizing_defined": 0.15,
    "portfolio_truth_clean": 0.10,
    "why_today_score": 0.10,
    "human_review_ready": 0.05,
}


def _clamp01(value: Any) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, num))


def _flag(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return _clamp01(value)


def compute_acqs(
    cqs: float,
    days_without_fresh_signal: float,
    *,
    fresh_signal_present: bool = False,
    decay_lambda: float | None = None,
    thresholds: dict[str, Any] | None = None,
) -> float:
    """ACQS(t) = CQS(t) * exp(-lambda * d(t))."""
    return adjusted_cqs(
        cqs,
        days_without_fresh_signal,
        fresh_signal_present=fresh_signal_present,
        decay_lambda=decay_lambda,
        thresholds=thresholds,
    )


def compute_fcs(inputs: dict[str, Any] | None) -> dict[str, Any]:
    """Final Candidate Score with per-component breakdown."""
    inputs = dict(inputs or {})
    components = {
        "acqs": _clamp01(inputs.get("acqs")),
        "mean_model_score": _clamp01(inputs.get("mean_model_score")),
        "cross_model_agreement": _clamp01(inputs.get("cross_model_agreement")),
        "why_today_score": _clamp01(inputs.get("why_today_score")),
        "data_quality": _clamp01(inputs.get("data_quality")),
        "freshness_score": _clamp01(inputs.get("freshness_score")),
        "liquidity_quality": _clamp01(inputs.get("liquidity_quality")),
    }
    chaos = _clamp01(inputs.get("chaos_risk"))
    disagreement = _clamp01(inputs.get("normalized_disagreement"))
    contamination = _clamp01(inputs.get("portfolio_contamination_penalty"))
    fcs = sum(FCS_WEIGHTS[k] * components[k] for k in FCS_WEIGHTS)
    fcs -= FCS_PENALTIES["chaos_risk"] * chaos
    fcs -= FCS_PENALTIES["normalized_disagreement"] * disagreement
    fcs -= FCS_PENALTIES["portfolio_contamination_penalty"] * contamination
    return {
        "fcs": round(max(0.0, min(1.0, fcs)), 4),
        "components": components,
        "chaos_risk": chaos,
        "normalized_disagreement": disagreement,
        "portfolio_contamination_penalty": contamination,
    }


def compute_ers(inputs: dict[str, Any] | None) -> dict[str, Any]:
    """Execution Readiness Score with per-component breakdown."""
    inputs = dict(inputs or {})
    components = {
        "data_quality": _clamp01(inputs.get("data_quality")),
        "source_health_score": _clamp01(inputs.get("source_health_score", inputs.get("source_health"))),
        "invalidation_defined": _flag(inputs.get("invalidation_defined")),
        "position_sizing_defined": _flag(inputs.get("position_sizing_defined")),
        "portfolio_truth_clean": _flag(inputs.get("portfolio_truth_clean", 1)),
        "why_today_score": _clamp01(inputs.get("why_today_score")),
        "human_review_ready": _flag(inputs.get("human_review_ready")),
    }
    ers = round(sum(ERS_WEIGHTS[k] * components[k] for k in ERS_WEIGHTS), 4)
    return {"ers": ers, "components": components}


def classify_final(
    *,
    fcs: float,
    ers: float,
    why_today_score: float,
    source_health: float,
    invalidation_defined: Any,
    position_sizing_defined: Any,
    normalized_disagreement: float,
    forbidden_for_execution: bool,
    portfolio_truth: str = "NOT_A_HOLDING",
    chaos_risk: float = 0.0,
    crowding_risk: float = 0.0,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the final classification + reason for one cross-model candidate."""
    t = thresholds or load_discovery_thresholds()
    fcs_min = float(t["fcs_min"])
    ers_min = float(t["ers_min"])
    why_min = float(t.get("why_today_min_for_executable", 0.70))
    sh_min = float(t["source_health_min"])
    dis_high = float(t.get("disagreement_high_min", 0.35))
    watch_min = float(t["watchlist_fcs_min"])

    invalidation_ok = _flag(invalidation_defined) >= 1.0
    sizing_ok = _flag(position_sizing_defined) >= 1.0

    # Verified open holdings: exit review only (never a buy).
    if portfolio_truth == "VERIFIED_OPEN_HOLDING":
        return _verdict("SELL / EXIT REVIEW", "Verified open holding — human exit/TP/stop review only.",
                        fcs, ers, executable=False)

    # Closed/sold/do-not-treat: discovery candidate, never executable.
    if forbidden_for_execution:
        cls = "WATCHLIST" if fcs >= watch_min else "AVOID"
        return _verdict(cls, "Closed/sold/do-not-treat ticker (t ∈ C∪S∪D) — not executable.",
                        fcs, ers, executable=False)

    if chaos_risk >= 0.80 or crowding_risk >= 0.85:
        return _verdict("AVOID", "Chaos/crowding risk too high.", fcs, ers, executable=False)

    executable = (
        fcs >= fcs_min
        and ers >= ers_min
        and why_today_score >= why_min
        and source_health >= sh_min
        and invalidation_ok
        and sizing_ok
        and normalized_disagreement < dis_high
    )
    if executable:
        return _verdict(
            "EXECUTABLE-PAPER-BUY",
            "Clears FCS+ERS, fresh why-today, adequate source health, invalidation "
            "+ sizing defined, disagreement acceptable. Advisory-only paper buy.",
            fcs, ers, executable=True,
        )

    if fcs >= fcs_min:
        missing: list[str] = []
        if ers < ers_min:
            missing.append(f"ERS {ers:.2f} < {ers_min:.2f}")
        if why_today_score < why_min:
            missing.append("Missing sufficient why-today trigger")
        if source_health < sh_min:
            missing.append(f"source_health {source_health:.2f} < {sh_min:.2f}")
        if not invalidation_ok:
            missing.append("invalidation not defined")
        if not sizing_ok:
            missing.append("position sizing not defined")
        if normalized_disagreement >= dis_high:
            missing.append(f"high model disagreement {normalized_disagreement:.2f}")
            return _verdict(
                "RESEARCH_CANDIDATE",
                "High conviction but high cross-model disagreement: " + "; ".join(missing) + ".",
                fcs, ers, executable=False,
            )
        return _verdict(
            "BUY-CANDIDATE / NOT-EXECUTABLE",
            "Good candidate, not executable because " + "; ".join(missing) + ".",
            fcs, ers, executable=False,
        )

    if fcs >= 0.65 and normalized_disagreement >= dis_high:
        return _verdict("RESEARCH_CANDIDATE", "Borderline score with high disagreement — research only.",
                        fcs, ers, executable=False)
    if fcs >= watch_min:
        return _verdict("WATCHLIST", "Below candidate floor — incomplete confirmation.", fcs, ers, executable=False)
    if fcs >= 0.40:
        return _verdict("WAIT", "Insufficient confirmation today.", fcs, ers, executable=False)
    return _verdict("AVOID", "Score below floor / weak edge.", fcs, ers, executable=False)


def _verdict(classification: str, reason: str, fcs: float, ers: float, *, executable: bool) -> dict[str, Any]:
    return {
        "classification": classification,
        "reason": reason,
        "fcs": round(float(fcs), 4),
        "ers": round(float(ers), 4),
        "executable": executable,
    }


def cross_model_agreement(models_mentioning: int, total_models: int = 5) -> float:
    return round(max(0, int(models_mentioning)) / max(1, total_models), 4)


def freshness_score_from_label(label: Any) -> float:
    """Map a freshness label to a 0..1 freshness score."""
    table = {
        "FRESH_TODAY": 1.0,
        "UPDATED_TODAY": 0.85,
        "STALE_24H": 0.40,
        "STALE_48H": 0.20,
        "HISTORICAL_ONLY": 0.10,
        "UNVERIFIED": 0.0,
        "DO_NOT_TREAT_AS_OPEN": 0.0,
        "CLOSED_OR_SOLD": 0.0,
    }
    return table.get(str(label or "").strip().upper(), 0.0)


__all__ = [
    "FCS_WEIGHTS",
    "FCS_PENALTIES",
    "ERS_WEIGHTS",
    "compute_acqs",
    "compute_fcs",
    "compute_ers",
    "classify_final",
    "cross_model_agreement",
    "freshness_score_from_label",
    "normalize_ticker",
]
