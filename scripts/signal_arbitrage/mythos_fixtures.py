"""Deterministic case fixtures for Mythos.  Hand-built, not captured live."""
from __future__ import annotations

from .mythos import MythosObservation


def case_1_theme_only() -> MythosObservation:
    """Shortest-route fallacy: 'growing sector, therefore buy.'"""
    return MythosObservation(
        source="analyst", entity="GENERIC_AI_NAME", claim_type="theme_sector",
        raw_text="Company is in a fast-growing AI sector, therefore buy.",
        reliability=0.6, recency=0.7, independence=0.5, coverage=0.4, noise_level=0.3,
        confidence_prior=0.6,
        demand=0.8, revenue_growth=0.7,        # strong theme/flow
        flow_growth=0.8, capture_rate=0.25, leakage=0.45, pricing_power=0.3,  # weak capture
        attention=0.6, mentions_velocity=0.6, sentiment=0.7, consensus=0.6,
    )


def case_2_revenue_ambiguity() -> MythosObservation:
    """'Revenue grew 35%' with no corroboration -> unresolved explanation."""
    return MythosObservation(
        source="sec_filing", entity="REVCO", claim_type="revenue_growth",
        raw_text="Revenue grew 35% year over year.",
        reliability=0.9, recency=0.8, independence=0.7, coverage=0.5, noise_level=0.1,
        confidence_prior=0.6, revenue_growth=0.7,  # margin/retention/volume unknown
    )


def case_2_revenue_corroborated() -> MythosObservation:
    """Same claim, now corroborated by margin + retention + volume -> organic."""
    return MythosObservation(
        source="sec_filing", entity="REVCO", claim_type="revenue_growth",
        raw_text="Revenue grew 35%, gross margin expanded, cohort retention up.",
        reliability=0.9, recency=0.8, independence=0.7, coverage=0.8, noise_level=0.1,
        confidence_prior=0.7,
        revenue_growth=0.7, margin_trend=0.8, retention=0.8, demand=0.75,
        pricing_power=0.6,
    )


def case_3_narrative_no_reality() -> MythosObservation:
    """X/Grok buzz explodes; no economic data to confirm."""
    return MythosObservation(
        source="x", entity="HYPE_AI", claim_type="narrative_buzz",
        raw_text="Everyone on X is talking about this AI company, it's going viral 🚀",
        reliability=0.4, recency=0.9, independence=0.2, coverage=0.2, noise_level=0.7,
        confidence_prior=0.5,
        attention=0.95, mentions_velocity=0.9, sentiment=0.85, amplification=0.8,
        saturation=0.4, consensus=0.6,
        # economic fields intentionally None -> low coverage / unconfirmed reality
    )


def case_4_reality_up_narrative_down() -> MythosObservation:
    """Retention + margins improving while sentiment stays negative."""
    return MythosObservation(
        source="sec_filing", entity="QUIETCO", claim_type="retention_up",
        raw_text="Customer retention and gross margins improved this quarter.",
        reliability=0.85, recency=0.8, independence=0.7, coverage=0.8, noise_level=0.15,
        confidence_prior=0.65,
        demand=0.6, revenue_growth=0.55, margin_trend=0.8, retention=0.85,
        pricing_power=0.65, customer_adoption=0.7,
        attention=0.2, mentions_velocity=0.15, sentiment=0.25, amplification=0.1,
        saturation=0.1, consensus=0.3,
        evidence_events=(
            {"day": 5, "supports": True, "weight": 0.7, "independent": 0.8},
            {"day": 12, "supports": True, "weight": 0.6, "independent": 0.7},
        ),
    )


def case_5_eta_error() -> MythosObservation:
    """Expected catalyst in 30 days, still absent after 75 days."""
    return MythosObservation(
        source="analyst", entity="LATECO", claim_type="generic",
        raw_text="Expected product catalyst within 30 days.",
        reliability=0.6, recency=0.4, independence=0.5, coverage=0.5, noise_level=0.3,
        confidence_prior=0.6,
        catalyst_eta_days=30.0, catalyst_elapsed_days=75.0,
        demand=0.5, revenue_growth=0.4,
    )


def case_6_food_chain_capture_failure() -> MythosObservation:
    """EV charging: flow rising, but margins worsening + capex/leakage high."""
    return MythosObservation(
        source="sec_filing", entity="CHARGECO", claim_type="generic",
        raw_text="EV adoption rising and charging revenue rising, but margins "
                 "worsening and capex climbing.",
        reliability=0.85, recency=0.8, independence=0.7, coverage=0.7, noise_level=0.2,
        confidence_prior=0.6,
        demand=0.8, revenue_growth=0.75, margin_trend=0.25, customer_adoption=0.7,
        flow_growth=0.85, capture_rate=0.2, leakage=0.7, pricing_power=0.3,
        capex_burden=0.8, dependency=0.6,
    )


def case_7_open_vs_closed_governance() -> MythosObservation:
    """Community (Reddit) says a trend is happening; filings don't confirm yet."""
    return MythosObservation(
        source="reddit", entity="EARLYCO", claim_type="narrative_buzz",
        raw_text="Reddit users report a switching trend away from the incumbent.",
        reliability=0.5, recency=0.85, independence=0.6, coverage=0.4, noise_level=0.4,
        confidence_prior=0.5,
        attention=0.5, mentions_velocity=0.6, sentiment=0.6, consensus=0.4,
        customer_adoption=0.4,
        # no official economic confirmation -> low coverage
    )


def case_8_worldview_disagreement() -> MythosObservation:
    """One company update; momentum/value/short/customer all read it differently."""
    # Cross-pressured on purpose: loud momentum + weak margin + heavy
    # capex/regulation + noisy feed -> momentum reads bullish while value /
    # short-seller / risk-first read bearish.  Maximum worldview disagreement.
    return MythosObservation(
        source="news", entity="SPLITCO", claim_type="cost_cutting",
        raw_text="Company is cutting costs and reducing headcount while usage grows.",
        reliability=0.6, recency=0.7, independence=0.5, coverage=0.6, noise_level=0.6,
        confidence_prior=0.55,
        demand=0.7, revenue_growth=0.5, margin_trend=0.3, retention=0.45,
        pricing_power=0.35, customer_adoption=0.5, capex_burden=0.7,
        regulation_risk=0.6,
        attention=0.85, mentions_velocity=0.85, sentiment=0.5, amplification=0.6,
        saturation=0.3, consensus=0.5,
    )


def single_source_reality_baseline() -> MythosObservation:
    """One official source: real retention/margin, quiet narrative."""
    return MythosObservation(
        source="sec_filing", entity="MULTICO", claim_type="retention_up",
        raw_text="Customer retention and gross margins improved this quarter.",
        reliability=0.85, recency=0.8, independence=0.7, coverage=0.8, noise_level=0.15,
        confidence_prior=0.65,
        demand=0.6, revenue_growth=0.55, margin_trend=0.8, retention=0.85,
        pricing_power=0.65, customer_adoption=0.7,
        attention=0.2, mentions_velocity=0.15, sentiment=0.25, consensus=0.3)


def multi_source_reality_cluster() -> list[MythosObservation]:
    """Same thesis corroborated across THREE distinct ecologies
    (linkedin via filing, reddit, youtube via web_traffic)."""
    base = single_source_reality_baseline()
    return [
        base,
        MythosObservation(
            source="reddit", entity="MULTICO", claim_type="retention_up",
            raw_text="Switched to them and stayed; retention has been perfect, recommend.",
            reliability=0.55, recency=0.85, independence=0.6, coverage=0.5, noise_level=0.3,
            confidence_prior=0.55, retention=0.75, customer_adoption=0.65, demand=0.55,
            attention=0.4, mentions_velocity=0.4, sentiment=0.6, consensus=0.35, day=1),
        MythosObservation(
            source="web_traffic", entity="MULTICO", claim_type="retention_up",
            raw_text="Returning-user traffic and engaged sessions climbing.",
            reliability=0.62, recency=0.8, independence=0.7, coverage=0.6, noise_level=0.2,
            confidence_prior=0.6, demand=0.7, customer_adoption=0.68, retention=0.72,
            attention=0.35, mentions_velocity=0.3, sentiment=0.5, consensus=0.35, day=2),
    ]


def same_source_spam_cluster() -> list[MythosObservation]:
    """Three reddit posts -> ONE ecology. Must not fake migration."""
    return [
        MythosObservation(
            source="reddit", entity="SPAMCO", claim_type="retention_up",
            raw_text=f"People are switching and staying, retention strong ({i}).",
            reliability=0.55, recency=0.85, independence=0.6, coverage=0.5, noise_level=0.3,
            confidence_prior=0.55, retention=0.7, customer_adoption=0.6, demand=0.55,
            attention=0.4, sentiment=0.6, consensus=0.35, day=i)
        for i in range(3)
    ]


def social_only_cluster() -> list[MythosObservation]:
    """Multiple social ecologies, zero economic reality -> must stay blocked."""
    return [
        MythosObservation(
            source="x", entity="FAKECO", claim_type="narrative_buzz",
            raw_text="Going to the moon, viral, next big thing 🚀",
            reliability=0.4, recency=0.9, independence=0.2, coverage=0.2, noise_level=0.7,
            confidence_prior=0.5, attention=0.95, mentions_velocity=0.9, sentiment=0.85,
            amplification=0.8, saturation=0.5, consensus=0.6),
        MythosObservation(
            source="reddit", entity="FAKECO", claim_type="narrative_buzz",
            raw_text="Everyone hyping this, can't miss, FOMO",
            reliability=0.45, recency=0.9, independence=0.3, coverage=0.2, noise_level=0.6,
            confidence_prior=0.5, attention=0.8, mentions_velocity=0.85, sentiment=0.8,
            amplification=0.6, saturation=0.5, consensus=0.6, day=1),
    ]


ALL_MYTHOS_CASES = {
    "1_theme_only": case_1_theme_only,
    "2_revenue_ambiguity": case_2_revenue_ambiguity,
    "2b_revenue_corroborated": case_2_revenue_corroborated,
    "3_narrative_no_reality": case_3_narrative_no_reality,
    "4_reality_up_narrative_down": case_4_reality_up_narrative_down,
    "5_eta_error": case_5_eta_error,
    "6_food_chain_capture_failure": case_6_food_chain_capture_failure,
    "7_open_vs_closed_governance": case_7_open_vs_closed_governance,
    "8_worldview_disagreement": case_8_worldview_disagreement,
}


__all__ = (["ALL_MYTHOS_CASES"] + [f.__name__ for f in ALL_MYTHOS_CASES.values()]
           + ["single_source_reality_baseline", "multi_source_reality_cluster",
              "same_source_spam_cluster", "social_only_cluster"])
