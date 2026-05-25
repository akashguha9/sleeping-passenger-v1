"""Bruce Lee Signal Discipline Report — the operator's single read.

One advisory report that fuses the runtime truth state with the Jeet Kune Do
decision layer.  It is the operator-facing summary that answers: *is this a
disciplined decision, or noise dressed up as conviction?*

It pulls the real runtime state from the existing release-gate audits
(truth-purity, economy-of-motion) and runs the pure JKD / reality / operator-
heat / diablo / BLDQI engines on a signal scenario.  The polymarket-distortion,
news-quality, narrative-quality, triangulation, contradiction, strategic-actor,
firm-incentive, and reflexivity fields are computed by the compact pure helpers
below — the operationalised, consolidated form of the B7/B8/B9 formula families
(the heavier production engines live in narrative_distortion_index.py,
signal_distortion_index.py, narrative_inflation_index.py, etc.; this report is
the synthesis surface, not a duplicate of them).

Always prints:
    ADVISORY_ONLY
    HUMAN_EXECUTION_REQUIRED
    NO_BROKER_ACTION_PERFORMED

Safety
------
Read-only on the DB; pure compute for the rest.  No broker calls, no execution.
Advisory-only.

Usage
-----
    python scripts/bruce_lee_signal_discipline_report.py
    python scripts/bruce_lee_signal_discipline_report.py --json
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
    from scripts.runtime_common import utc_timestamp
    from scripts.runtime_truth_purity_audit import build_audit as _truth_purity
    from scripts.economy_of_motion_audit import build_audit as _economy
    from scripts.jkd_decision_discipline import (
        compute_interception, compute_directness, compute_jkd,
    )
    from scripts.finger_moon_reality_check import compute_reality_confirmation
    from scripts.operator_emotional_content_gate import compute_operator_heat
    from scripts.diablo_narrative_veto import evaluate_veto
    from scripts.bruce_lee_decision_quality_index import (
        compute_signal_efficiency, compute_broken_rhythm, compute_anti_dogma,
        compute_survival_utility, compute_bldqi,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]
    from runtime_common import utc_timestamp  # type: ignore[no-redef]
    from runtime_truth_purity_audit import build_audit as _truth_purity  # type: ignore[no-redef]
    from economy_of_motion_audit import build_audit as _economy  # type: ignore[no-redef]
    from jkd_decision_discipline import (  # type: ignore[no-redef]
        compute_interception, compute_directness, compute_jkd,
    )
    from finger_moon_reality_check import compute_reality_confirmation  # type: ignore[no-redef]
    from operator_emotional_content_gate import compute_operator_heat  # type: ignore[no-redef]
    from diablo_narrative_veto import evaluate_veto  # type: ignore[no-redef]
    from bruce_lee_decision_quality_index import (  # type: ignore[no-redef]
        compute_signal_efficiency, compute_broken_rhythm, compute_anti_dogma,
        compute_survival_utility, compute_bldqi,
    )

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "runtime" / "mvp_local.db"

ADVISORY_DISCLAIMER = (
    "Advisory-only Bruce Lee signal-discipline report. It diagnoses decision "
    "quality; it never authorises or performs a broker action. Every decision "
    "requires a human."
)

# Contradiction classes (Task B8).
CONTRADICTION_NONE = "NO_MATERIAL_CONTRADICTION"
CONTRADICTION_HEALTHY = "HEALTHY_ALPHA_CONTRADICTION"
CONTRADICTION_DANGEROUS = "DANGEROUS_CONTRADICTION"
CONTRADICTION_LAGGING_PRICE = "LAGGING_PRICE_CONTRADICTION"
CONTRADICTION_FAKE_NARRATIVE = "FAKE_NARRATIVE_CONTRADICTION"
CONTRADICTION_PM_DISTORTION = "POLYMARKET_DISTORTION_CONTRADICTION"
CONTRADICTION_DATA_RELIABILITY = "DATA_RELIABILITY_CONTRADICTION"


def _c01(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


# ---------------------------------------------------------------------------
# Consolidated B7/B8/B9 pure helpers (advisory synthesis math).
# ---------------------------------------------------------------------------


def compute_polymarket_distortion(
    *,
    odds_move: float = 0.0, volume_change: float = 0.0, liquidity_depth: float = 0.0,
    open_interest: float = 0.0, trader_dispersion: float = 0.0,
    market_relevance: float = 0.0, resolution_clarity: float = 0.0,
    low_liquidity: float = 0.0, whale_concentration: float = 0.0,
    wide_spread: float = 0.0, low_trader_count: float = 0.0,
    ambiguous_resolution: float = 0.0, sudden_unconfirmed_move: float = 0.0,
) -> dict[str, Any]:
    """PMScore, DistortionRisk and PMCleanSignal (Task B7).  Inputs 0–1."""
    pm_score = (
        0.20 * _c01(odds_move) + 0.18 * _c01(volume_change)
        + 0.16 * _c01(liquidity_depth) + 0.14 * _c01(open_interest)
        + 0.12 * _c01(trader_dispersion) + 0.10 * _c01(market_relevance)
        + 0.10 * _c01(resolution_clarity)
    )
    distortion = (
        0.25 * _c01(low_liquidity) + 0.20 * _c01(whale_concentration)
        + 0.18 * _c01(wide_spread) + 0.15 * _c01(low_trader_count)
        + 0.12 * _c01(ambiguous_resolution) + 0.10 * _c01(sudden_unconfirmed_move)
    )
    return {
        "pm_score": round(pm_score, 4),
        "distortion_risk": round(distortion, 4),
        "pm_clean_signal": round(pm_score - distortion, 4),
    }


def compute_news_quality(
    *, freshness=0.0, source_credibility=0.0, materiality=0.0, novelty=0.0,
    specificity=0.0, market_reaction=0.0, cross_verification=0.0,
) -> float:
    """NewsQuality (0–1) (Task B8)."""
    return round(
        0.20 * _c01(freshness) + 0.18 * _c01(source_credibility)
        + 0.16 * _c01(materiality) + 0.14 * _c01(novelty)
        + 0.12 * _c01(specificity) + 0.10 * _c01(market_reaction)
        + 0.10 * _c01(cross_verification),
        4,
    )


def compute_narrative_quality(
    *, velocity=0.0, breadth=0.0, emotional_intensity=0.0, institutional_adoption=0.0,
    retail_adoption=0.0, persistence=0.0, asset_specificity=0.0,
    crowding=0.0, price_overextension=0.0, weak_fundamental_support=0.0,
    single_source_dependence=0.0, meme_contamination=0.0, contradiction=0.0,
    time_decay=0.0,
) -> dict[str, Any]:
    """NarrativeStrength, NarrativeFragility, NarrativeQuality (Task B8)."""
    strength = (
        0.22 * _c01(velocity) + 0.18 * _c01(breadth)
        + 0.16 * _c01(emotional_intensity) + 0.14 * _c01(institutional_adoption)
        + 0.12 * _c01(retail_adoption) + 0.10 * _c01(persistence)
        + 0.08 * _c01(asset_specificity)
    )
    fragility = (
        0.20 * _c01(crowding) + 0.18 * _c01(price_overextension)
        + 0.16 * _c01(weak_fundamental_support) + 0.14 * _c01(single_source_dependence)
        + 0.12 * _c01(meme_contamination) + 0.10 * _c01(contradiction)
        + 0.10 * _c01(time_decay)
    )
    return {
        "narrative_strength": round(strength, 4),
        "narrative_fragility": round(fragility, 4),
        "narrative_quality": round(strength - fragility, 4),
    }


def compute_triangulation(
    *, price_signal=0.0, news_signal=0.0, polymarket_signal=0.0,
    narrative_signal=0.0, filing_signal=0.0,
    pm_distortion=0.0, fake_narrative_risk=0.0, staleness=0.0,
    source_credibility=0.5, reality_confirmation_01=0.5,
) -> dict[str, Any]:
    """TriangulatedSignal, ContradictionScore, CleanSignal, and the
    contradiction class (Task B8).  Inputs 0–1."""
    p, n, pm, nar, fil = (
        _c01(price_signal), _c01(news_signal), _c01(polymarket_signal),
        _c01(narrative_signal), _c01(filing_signal),
    )
    triangulated = 0.30 * p + 0.25 * n + 0.25 * pm + 0.20 * nar
    contradiction_score = round(statistics.pvariance([n, p, pm, nar, fil]), 4)
    clean = triangulated - _c01(pm_distortion) - _c01(fake_narrative_risk) - _c01(staleness)

    cls = _classify_contradiction(
        price=p, news=n, pm=pm, narrative=nar,
        contradiction_score=contradiction_score, pm_distortion=_c01(pm_distortion),
        fake_narrative_risk=_c01(fake_narrative_risk),
        source_credibility=_c01(source_credibility),
        reality_confirmation_01=_c01(reality_confirmation_01),
    )
    return {
        "triangulated_signal": round(triangulated, 4),
        "contradiction_score": contradiction_score,
        "clean_signal": round(clean, 4),
        "contradiction_class": cls,
    }


def _classify_contradiction(
    *, price, news, pm, narrative, contradiction_score, pm_distortion,
    fake_narrative_risk, source_credibility, reality_confirmation_01,
) -> str:
    """Priority-ordered contradiction classifier (Task B8).

    A contradiction is only *dangerous* when the signals disagree AND reality
    is poorly confirmed.  Moderate dispersion with a confirmed reality anchor
    is not flagged dangerous — that would be ornamental alarm, which economy
    of motion forbids.
    """
    if contradiction_score < 0.05:
        return CONTRADICTION_NONE
    if source_credibility < 0.35:
        return CONTRADICTION_DATA_RELIABILITY
    if pm_distortion >= 0.45:
        return CONTRADICTION_PM_DISTORTION
    if fake_narrative_risk >= 0.45 or (narrative >= 0.6 and price <= 0.3 and news <= 0.3):
        return CONTRADICTION_FAKE_NARRATIVE
    # News/PM/narrative ahead of price.
    if price <= 0.4 and max(news, pm, narrative) >= 0.6:
        if reality_confirmation_01 >= 0.5:
            return CONTRADICTION_HEALTHY if (pm >= 0.5 or news >= 0.5) else CONTRADICTION_LAGGING_PRICE
        return CONTRADICTION_LAGGING_PRICE
    # Signals disagree and reality is weak → dangerous.
    if reality_confirmation_01 < 0.4:
        return CONTRADICTION_DANGEROUS
    # Disagreement but reality is anchored → tolerable divergence.
    return CONTRADICTION_NONE


def compute_strategic_actor_summary(
    *, costliness=0.0, verifiability=0.0, incentive_alignment=0.0,
    historical_accuracy=0.0,
) -> dict[str, Any]:
    """SignalCredibility — costly signals outrank cheap talk (Task B9)."""
    credibility = (
        0.35 * _c01(costliness) + 0.25 * _c01(verifiability)
        + 0.20 * _c01(incentive_alignment) + 0.20 * _c01(historical_accuracy)
    )
    return {
        "signal_credibility": round(credibility, 4),
        "cheap_talk": bool(credibility < 0.35),
    }


def compute_firm_incentive_summary(
    *, firm_quality_inputs: dict[str, float] | None = None,
    agency_risk_inputs: dict[str, float] | None = None,
    adverse_selection_inputs: dict[str, float] | None = None,
) -> dict[str, Any]:
    """FirmQuality, AgencyRisk, AdverseSelectionRisk (Task B9).  Compact:
    each input dict maps the named 0–1 factors; missing → 0."""
    fq = firm_quality_inputs or {}
    ar = agency_risk_inputs or {}
    asr = adverse_selection_inputs or {}
    firm_quality = (
        0.18 * _c01(fq.get("pricing_power")) + 0.15 * _c01(fq.get("margins"))
        + 0.14 * _c01(fq.get("demand_resilience")) + 0.13 * _c01(fq.get("cost_structure"))
        + 0.15 * _c01(fq.get("balance_sheet")) + 0.15 * _c01(fq.get("competitive_position"))
        + 0.10 * _c01(fq.get("management_incentives"))
    )
    agency_risk = (
        0.25 * _c01(ar.get("compensation_misalignment")) + 0.20 * _c01(ar.get("dilution_risk"))
        + 0.20 * _c01(ar.get("debt_abuse")) + 0.15 * _c01(ar.get("empire_building"))
        + 0.10 * _c01(ar.get("insider_selling")) + 0.10 * _c01(ar.get("governance_weakness"))
    )
    adverse_selection = (
        0.25 * _c01(asr.get("insider_selling")) + 0.20 * _c01(asr.get("opaque_accounting"))
        + 0.20 * _c01(asr.get("weak_guidance")) + 0.15 * _c01(asr.get("short_interest"))
        + 0.10 * _c01(asr.get("liquidity_weakness")) + 0.10 * _c01(asr.get("jurisdiction_opacity"))
    )
    return {
        "firm_quality": round(firm_quality, 4),
        "agency_risk": round(agency_risk, 4),
        "adverse_selection_risk": round(adverse_selection, 4),
        "downgrade_flag": bool(agency_risk >= 0.5 or adverse_selection >= 0.5),
    }


def compute_reflexivity(
    *, momentum=0.0, narrative_velocity=0.0, flow_confirmation=0.0,
    drawdown=0.0, leverage=0.0, liquidity_stress=0.0, narrative_decay=0.0,
) -> dict[str, Any]:
    """ReflexivityScore = positive loop - negative loop (Task B9).

    Negative reflexivity raises chaos risk, so the helper also returns a
    ``chaos_contribution`` (0–10) the caller folds into JKD chaos.
    """
    positive = _c01(momentum) * _c01(narrative_velocity) * _c01(flow_confirmation)
    negative = _c01(drawdown) * _c01(leverage) * _c01(liquidity_stress) * (1.0 + _c01(narrative_decay))
    score = positive - negative
    chaos_contribution = round(min(10.0, 10.0 * max(0.0, negative)), 4)
    return {
        "reflexivity_score": round(score, 4),
        "positive_loop": round(positive, 4),
        "negative_loop": round(negative, 4),
        "chaos_contribution": chaos_contribution,
    }


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

# Neutral-but-illustrative default scenario.  This is a representative advisory
# input set, NOT live market data — the report is a discipline lens, and the
# operator supplies real per-signal inputs in practice.
_DEFAULT_SCENARIO: dict[str, Any] = {
    "price_structure_shift": 0.6, "narrative_acceleration": 0.55,
    "volume_confirmation": 0.6, "consensus_delay": 0.5,
    "invalidation_clarity": 0.7, "thesis_specificity": 0.65,
    "source_specificity": 0.6, "time_horizon_clarity": 0.6, "risk_reward_clarity": 0.6,
    "adaptability": 6.5,
    "price_confirmation": 0.6, "vol_conf": 0.6, "source_credibility": 0.65,
    "liquidity_confirmation": 0.6, "filing_confirmation": 0.4, "outcome_confirmation": 0.5,
    "ai_consensus": 0.5, "polymarket_odds": 0.5, "narrative_strength": 0.5,
    "fomo": 0.2, "revenge": 0.0, "overconfidence": 0.2, "urgency": 0.2, "identity": 0.1,
    "noise": 2.0,
}


def build_report(
    db_path: Path | None = None,
    *,
    scenario: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the full advisory discipline report."""
    db = Path(db_path) if db_path is not None else DEFAULT_DB
    sc = dict(_DEFAULT_SCENARIO)
    if scenario:
        sc.update(scenario)

    # --- runtime truth state (real, read-only) --------------------------
    purity = _truth_purity(db)
    economy = _economy(db)

    # --- JKD layer ------------------------------------------------------
    interception = compute_interception(
        sc["price_structure_shift"], sc["narrative_acceleration"],
        sc["volume_confirmation"], sc["consensus_delay"],
    )
    directness = compute_directness(
        sc["invalidation_clarity"], sc["thesis_specificity"],
        sc["source_specificity"], sc["time_horizon_clarity"], sc["risk_reward_clarity"],
    )
    reality = compute_reality_confirmation(
        price_confirmation=sc["price_confirmation"], volume_confirmation=sc["vol_conf"],
        source_credibility=sc["source_credibility"],
        liquidity_confirmation=sc["liquidity_confirmation"],
        filing_or_official_confirmation=sc["filing_confirmation"],
        outcome_or_moltbook_confirmation=sc["outcome_confirmation"],
        ai_consensus=sc["ai_consensus"], polymarket_odds=sc["polymarket_odds"],
        narrative_strength=sc["narrative_strength"],
    )
    heat = compute_operator_heat(
        fomo=sc["fomo"], revenge=sc["revenge"], overconfidence=sc["overconfidence"],
        urgency=sc["urgency"], identity_attachment=sc["identity"],
    )

    # --- synthesis helpers (consolidated B7/B8/B9) ----------------------
    pm = compute_polymarket_distortion(
        odds_move=sc["polymarket_odds"], volume_change=0.4, liquidity_depth=0.5,
        open_interest=0.4, trader_dispersion=0.4, market_relevance=0.5,
        resolution_clarity=0.6, low_liquidity=0.3, whale_concentration=0.3,
        wide_spread=0.2, low_trader_count=0.3, ambiguous_resolution=0.2,
        sudden_unconfirmed_move=0.2,
    )
    news_q = compute_news_quality(
        freshness=0.7, source_credibility=sc["source_credibility"], materiality=0.6,
        novelty=0.5, specificity=0.6, market_reaction=0.5, cross_verification=0.5,
    )
    narrative = compute_narrative_quality(
        velocity=0.5, breadth=0.5, emotional_intensity=0.4, institutional_adoption=0.4,
        retail_adoption=0.4, persistence=0.5, asset_specificity=0.5,
        crowding=0.3, price_overextension=0.3, weak_fundamental_support=0.3,
        single_source_dependence=0.3, meme_contamination=0.2, contradiction=0.2, time_decay=0.2,
    )
    reflex = compute_reflexivity(
        momentum=0.5, narrative_velocity=0.5, flow_confirmation=0.5,
        drawdown=0.2, leverage=0.2, liquidity_stress=0.2, narrative_decay=0.2,
    )
    triangulation = compute_triangulation(
        price_signal=sc["price_confirmation"], news_signal=news_q,
        polymarket_signal=max(0.0, pm["pm_clean_signal"]),
        narrative_signal=max(0.0, narrative["narrative_quality"]),
        filing_signal=sc["filing_confirmation"], pm_distortion=pm["distortion_risk"],
        fake_narrative_risk=narrative["narrative_fragility"], staleness=0.1,
        source_credibility=sc["source_credibility"],
        reality_confirmation_01=reality["reality_confirmation_score"] / 10.0,
    )
    actor = compute_strategic_actor_summary(
        costliness=0.5, verifiability=0.6, incentive_alignment=0.5, historical_accuracy=0.5,
    )
    firm = compute_firm_incentive_summary(
        firm_quality_inputs={"pricing_power": 0.6, "margins": 0.6, "balance_sheet": 0.6,
                             "competitive_position": 0.6, "demand_resilience": 0.5,
                             "cost_structure": 0.5, "management_incentives": 0.5},
        agency_risk_inputs={"compensation_misalignment": 0.2, "dilution_risk": 0.2},
        adverse_selection_inputs={"insider_selling": 0.2, "short_interest": 0.2},
    )

    # Chaos risk folds in negative reflexivity.
    chaos_risk = reflex["chaos_contribution"]

    jkd = compute_jkd(
        interception=interception["interception_score"],
        directness=directness["directness_score"],
        adaptability=sc["adaptability"],
        economy=economy["economy_score"],
        reality_confirmation=reality["reality_confirmation_score"],
        noise=sc["noise"],
        greed_ego=heat["operator_heat"] * 10.0,
        chaos_risk=chaos_risk,
    )

    # --- diablo veto ----------------------------------------------------
    diablo = evaluate_veto(
        signal_strength=triangulation["clean_signal"],
        operator_emotion=heat["operator_heat"], leverage=0.2,
        narrative_virality=narrative["narrative_strength"],
        fundamental_support=firm["firm_quality"],
        polymarket_move_thinness=pm["distortion_risk"],
        asset_impact=0.4, news_age=0.2,
        conviction=triangulation["triangulated_signal"],
        invalidation_clarity=sc["invalidation_clarity"],
        crowding=0.3, liquidity=sc["liquidity_confirmation"],
    )
    diablo_risk_10 = 8.0 if diablo["diablo_veto"] and diablo["veto_state"] == "DIABLO" else (
        5.0 if diablo["diablo_veto"] else 1.0
    )

    # --- anti-dogma + BLDQI synthesis -----------------------------------
    anti_dogma = compute_anti_dogma(
        adaptability=sc["adaptability"], invalidation_clarity=sc["invalidation_clarity"],
        single_source_dependence=0.3,
    )
    signal_efficiency = compute_signal_efficiency(
        expected_value=1.5, confidence=triangulation["triangulated_signal"],
        survival_quality=0.7, assumptions=1.0, data_fragility=0.5, operational_complexity=0.5,
    )
    broken_rhythm = compute_broken_rhythm(
        dislocation=sc["price_structure_shift"], delayed_consensus=sc["consensus_delay"],
        asymmetric_setup=0.5, volatility_compression=0.4, narrative_mismatch=0.3,
    )
    survival_utility = compute_survival_utility(
        return_potential=0.5, survival_quality=0.7, feedback_value=0.6,
        invalidation_clarity=sc["invalidation_clarity"], liquidity=sc["liquidity_confirmation"],
        chaos_risk=chaos_risk / 10.0,
    )
    bldqi = compute_bldqi(
        interception=interception["interception_score"],
        directness=directness["directness_score"],
        adaptability=sc["adaptability"], economy=economy["economy_score"],
        reality_confirmation=reality["reality_confirmation_score"],
        signal_efficiency=signal_efficiency, broken_rhythm=broken_rhythm,
        anti_dogma=anti_dogma, survival_utility=survival_utility,
        operator_heat=heat["operator_heat"] * 10.0, diablo_risk=diablo_risk_10,
    )

    # Final advisory constraint = the tightest of JKD / BLDQI / diablo.
    final_constraint = _tightest_constraint(
        jkd["action_constraint"], bldqi["action_constraint"],
        diablo["diablo_veto"],
    )

    report: dict[str, Any] = {
        "report": "bruce_lee_signal_discipline_report",
        "db_path": str(db),
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        "scenario_is_illustrative": scenario is None,
        "truth_purity_status": {
            "fake_rows_detected": purity["fake_rows_detected"],
            "quarantined_rows_excluded": purity["quarantined_rows_excluded"],
            "truth_purity_score": purity["truth_purity_score"],
            "release_gate_passed": purity["release_gate_passed"],
        },
        "economy_of_motion": {
            "economy_score": economy["economy_score"],
            "system_sharpness": economy["system_sharpness"],
            "release_gate_impact": economy["release_gate_impact"],
        },
        "jkd_decision_score": jkd["jkd_score"],
        "jkd_state": jkd["advisory_state"],
        "interception": interception["interception_score"],
        "directness": directness["directness_score"],
        "adaptability": sc["adaptability"],
        "anti_dogma": anti_dogma,
        "reality_confirmation": reality["reality_confirmation_score"],
        "pointer_dominance_warning": reality["pointer_dominance_warning"],
        "operator_heat": heat["operator_heat"],
        "operator_heat_bucket": heat["heat_bucket"],
        "polymarket_distortion": pm,
        "news_quality": news_q,
        "narrative_quality": narrative,
        "triangulated_signal": triangulation["triangulated_signal"],
        "contradiction_class": triangulation["contradiction_class"],
        "strategic_actor_summary": actor,
        "firm_incentive_summary": firm,
        "reflexivity": reflex,
        "diablo_veto": {
            "diablo_veto": diablo["diablo_veto"],
            "veto_state": diablo["veto_state"],
            "veto_reason": diablo["veto_reason"],
            "recommended_safe_action": diablo["recommended_safe_action"],
        },
        "bldqi_score": bldqi["bldqi_score"],
        "bldqi_state": bldqi["state_recommendation"],
        "dominant_weakness": bldqi["dominant_weakness"],
        "moltbook_feedback_required": bldqi["moltbook_feedback_required"],
        "final_advisory_constraint": final_constraint,
        "human_review_required": True,
        # The three plain-language banners the spec mandates.
        "ADVISORY_ONLY": True,
        "HUMAN_EXECUTION_REQUIRED": True,
        "NO_BROKER_ACTION_PERFORMED": True,
        "generated_at": utc_timestamp(),
    }
    report.update(_contract.advisory_safety_stamps())
    return report


# Tightening order: most restrictive first.
_CONSTRAINT_RANK = {
    "RECONCILE_OR_WAIT": 5,
    "NO_NEW_RISK_RECOMMENDED": 4,
    "MONITOR_ONLY": 3,
    "WATCHLIST_ONLY": 2,
    "HUMAN_REVIEW_REQUIRED": 1,
}


def _tightest_constraint(jkd_c: str, bldqi_c: str, diablo: bool) -> str:
    if diablo:
        return "RECONCILE_OR_WAIT"
    return max((jkd_c, bldqi_c), key=lambda c: _CONSTRAINT_RANK.get(c, 0))


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bruce_lee_signal_discipline_report.py",
        description=(
            "Advisory-only Bruce Lee signal-discipline report. Read-only DB, "
            "pure synthesis. No broker calls; human execution required."
        ),
    )
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rep = build_report(args.db_path)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print("Bruce Lee Signal Discipline Report (advisory-only)")
        print("=" * 50)
        tp = rep["truth_purity_status"]
        print(f"  truth purity         : score={tp['truth_purity_score']} "
              f"fake={tp['fake_rows_detected']} quarantined={tp['quarantined_rows_excluded']} "
              f"gate_passed={tp['release_gate_passed']}")
        print(f"  economy of motion    : {rep['economy_of_motion']['economy_score']} / 10 "
              f"({rep['economy_of_motion']['release_gate_impact']})")
        print(f"  JKD decision score   : {rep['jkd_decision_score']} ({rep['jkd_state']})")
        print(f"  interception         : {rep['interception']}")
        print(f"  directness           : {rep['directness']}")
        print(f"  adaptability         : {rep['adaptability']}")
        print(f"  anti-dogma           : {rep['anti_dogma']}")
        print(f"  reality confirmation : {rep['reality_confirmation']} / 10  "
              f"(pointer_dominance={rep['pointer_dominance_warning']})")
        print(f"  operator heat        : {rep['operator_heat']} ({rep['operator_heat_bucket']})")
        print(f"  polymarket distortion: clean={rep['polymarket_distortion']['pm_clean_signal']} "
              f"risk={rep['polymarket_distortion']['distortion_risk']}")
        print(f"  news quality         : {rep['news_quality']}")
        print(f"  narrative quality    : {rep['narrative_quality']['narrative_quality']}")
        print(f"  triangulated signal  : {rep['triangulated_signal']}")
        print(f"  contradiction class  : {rep['contradiction_class']}")
        print(f"  strategic actor      : credibility={rep['strategic_actor_summary']['signal_credibility']}")
        print(f"  firm incentive       : quality={rep['firm_incentive_summary']['firm_quality']} "
              f"downgrade={rep['firm_incentive_summary']['downgrade_flag']}")
        print(f"  reflexivity          : {rep['reflexivity']['reflexivity_score']}")
        print(f"  diablo veto          : {rep['diablo_veto']['veto_state']}")
        print(f"  BLDQI score          : {rep['bldqi_score']} ({rep['bldqi_state']})")
        print(f"  dominant weakness    : {rep['dominant_weakness']}")
        print(f"  FINAL CONSTRAINT     : {rep['final_advisory_constraint']}")
        print()
        print("  ADVISORY_ONLY")
        print("  HUMAN_EXECUTION_REQUIRED")
        print("  NO_BROKER_ACTION_PERFORMED")
        print(f"\n  {rep['advisory_disclaimer']}")
    return 0


__all__ = [
    "build_report",
    "compute_polymarket_distortion",
    "compute_news_quality",
    "compute_narrative_quality",
    "compute_triangulation",
    "compute_strategic_actor_summary",
    "compute_firm_incentive_summary",
    "compute_reflexivity",
    "ADVISORY_DISCLAIMER",
]


if __name__ == "__main__":
    raise SystemExit(main())
