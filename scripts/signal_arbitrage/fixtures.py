"""Deterministic case-study fixtures for the signal_arbitrage pipeline.

These are hand-built dossiers, not captured from any live source, so the
package's behavior is reproducible and auditable.  Each maps to a scenario in
the upgrade brief:

  A — real high-vitality signal   -> WATCH / BUY
  B — bot-inflated hype           -> AVOID / NARRATIVE_TRAP
  C — sovereignty pattern         -> Shopify/Substack > Etsy (ownership)
  D — blind-validation failure    -> low purity, fragile
  E — interpretation-gap early    -> WATCH (early opportunity)
"""
from __future__ import annotations

from .opportunity import SignalDossier


def case_a_real_high_vitality() -> SignalDossier:
    """Reddit pain -> X debate -> YouTube explainer -> LinkedIn adoption,
    partial fundamentals.  Dense, low contamination, in transfer window."""
    return SignalDossier(
        signal_id="A_ai_datacenter_power",
        text=(
            "Switched from our old grid setup after the data center kept "
            "hitting power limits. Anyone else struggling with 480V capacity? "
            "We migrated to on-site substations, raised prices 18% and "
            "customers still happy to pay. Gross margin up Q3."
        ),
        platforms=["reddit", "x", "youtube", "linkedin"],
        comments=[
            "We hit the exact same 480V wall, ended up deploying two substations.",
            "Our utility quoted 14 month interconnect — switched to behind-the-meter.",
            "This matches what our ops team reported, adoption is company-wide now.",
        ],
        views=42000, likes=1300, saves=410, conversions=120, followers=22000,
        velocity=200, baseline_velocity=160,
        conversion_strength=0.62, retention_strength=0.58,
        reproduction_strength=0.5, business_confirmation=0.55,
        financial_confirmation=0.45,
        age_days=6.0, price_recognition=0.25, crowding=0.2,
        beholder_adoption=["expert_user", "analyst"],
    )


def case_b_bot_hype() -> SignalDossier:
    """High followers/views/likes, generic duplicated comments, no saves, no
    conversion, no fundamentals.  Synthetic liquidity."""
    return SignalDossier(
        signal_id="B_bot_inflated_meme",
        text="This stock is going to the moon 🚀 next big 10x, can't miss, FOMO!",
        platforms=["tiktok"],
        comments=[
            "🔥🔥🔥", "love this", "so good", "first", "amazing!!!",
            "great", "nice post", "love this", "🔥🔥🔥", "follow back",
            "check my profile", "so good", "great", "love this",
        ],
        views=2_000_000, likes=180_000, saves=20, conversions=0,
        followers=900_000, velocity=9000, baseline_velocity=400,
        conversion_strength=0.02, retention_strength=0.01,
        reproduction_strength=0.05, business_confirmation=0.0,
        financial_confirmation=0.0,
        age_days=2.0, price_recognition=0.1, crowding=0.3,
        beholder_adoption=["retail_customer"],
    )


def case_c_sovereignty_shopify() -> SignalDossier:
    """Owned-customer merchant: Shopify + Substack, email list, repeat."""
    return SignalDossier(
        signal_id="C_shopify_sovereign_merchant",
        text=(
            "Moved off the marketplace to our own Shopify store and email list. "
            "Now we own the customer, first-party data, repeat purchases up. "
            "Raised prices, still worth it for our subscribers."
        ),
        platforms=["shopify", "substack", "instagram"],
        comments=[
            "Been using them for years, renewed my subscription again.",
            "Their direct relationship with buyers is why I trust the brand.",
        ],
        views=12000, likes=600, saves=180, conversions=240, followers=15000,
        velocity=80, baseline_velocity=70,
        conversion_strength=0.6, retention_strength=0.62,
        reproduction_strength=0.45, business_confirmation=0.5,
        financial_confirmation=0.42,
        age_days=20.0, price_recognition=0.3, crowding=0.2,
        beholder_adoption=["expert_user", "long_only"],
    )


def case_c_sovereignty_etsy() -> SignalDossier:
    """Same demand, but Etsy-only: revenue without customer ownership."""
    return SignalDossier(
        signal_id="C_etsy_platform_dependent",
        text=(
            "Sales are great on Etsy but the platform controls ranking and the "
            "buyer relationship. No email list, no repeat customers off platform."
        ),
        platforms=["etsy", "instagram"],
        comments=[
            "Found this shop through Etsy search, nice product.",
            "Etsy reviews look solid.",
        ],
        views=12000, likes=600, saves=120, conversions=210, followers=15000,
        velocity=80, baseline_velocity=70,
        conversion_strength=0.55, retention_strength=0.3,
        reproduction_strength=0.35, business_confirmation=0.4,
        financial_confirmation=0.35,
        age_days=20.0, price_recognition=0.3, crowding=0.2,
        beholder_adoption=["retail_customer"],
    )


def case_d_blind_failure() -> SignalDossier:
    """Strong visible hype, but an explicit blind cohort scores it weak —
    perception-dependent thesis."""
    return SignalDossier(
        signal_id="D_perception_dependent_brand",
        text=(
            "Everyone is talking about this, viral game changer, looks gorgeous, "
            "insane hype, next big thing!"
        ),
        platforms=["instagram", "tiktok"],
        comments=[
            "so aesthetic 😍", "the vibe is everything", "looks amazing",
            "obsessed with the packaging", "iconic",
        ],
        views=600000, likes=50000, saves=900, conversions=40, followers=300000,
        velocity=1500, baseline_velocity=600,
        conversion_strength=0.2, retention_strength=0.15,
        reproduction_strength=0.3, business_confirmation=0.1,
        financial_confirmation=0.05,
        age_days=10.0, price_recognition=0.2, crowding=0.3,
        beholder_adoption=["retail_customer", "creator_influencer"],
        blind_score=0.18,   # double-blind cohort: collapses without the brand
    )


def case_e_interpretation_gap() -> SignalDossier:
    """Early/expert users see real, specific pain; the market hasn't noticed.
    Genuine fundamentals starting, low recognition."""
    return SignalDossier(
        signal_id="E_early_interpretation_gap",
        text=(
            "Switched from the incumbent after repeated outages. Specific bug: "
            "data loss on v2.3 sync. We churned 40% of seats, moved to the "
            "competitor. Their gross margin and adoption are quietly climbing."
        ),
        platforms=["reddit", "discord", "linkedin"],
        comments=[
            "We churned too — the v2.3 sync data loss was the final straw.",
            "Migrated 200 seats to the competitor, retention has been perfect.",
            "Our whole team switched from the incumbent last quarter.",
        ],
        views=9000, likes=300, saves=110, conversions=70, followers=8000,
        velocity=60, baseline_velocity=55,
        conversion_strength=0.55, retention_strength=0.6,
        reproduction_strength=0.4, business_confirmation=0.45,
        financial_confirmation=0.35,
        age_days=8.0, price_recognition=0.15, crowding=0.1,
        beholder_adoption=["expert_user"],
    )


def case_f_crowded_exhausted() -> SignalDossier:
    """Once-real signal, now late: confirmed but the market has crowded in and
    the half-life has elapsed.  The edge is gone even though the thesis was
    true — the classic 'right but too late' case."""
    return SignalDossier(
        signal_id="F_crowded_late_mover",
        text=(
            "The AI data-center power thesis everyone now owns: substations, "
            "interconnect queues, raised prices, margins confirmed. Fully "
            "priced, every analyst has a note out."
        ),
        platforms=["reddit", "x", "youtube", "linkedin"],
        comments=[
            "Old news, this has been consensus for two quarters.",
            "Every fund is already long this, fully priced.",
        ],
        views=80000, likes=2600, saves=300, conversions=140, followers=40000,
        velocity=120, baseline_velocity=130,
        conversion_strength=0.65, retention_strength=0.6,
        reproduction_strength=0.55, business_confirmation=0.7,
        financial_confirmation=0.68,
        age_days=140.0, price_recognition=0.88, crowding=0.82,
        beholder_adoption=["expert_user", "analyst", "institution", "long_only",
                           "retail_customer", "creator_influencer"],
    )


ALL_CASES = {
    "A": case_a_real_high_vitality,
    "B": case_b_bot_hype,
    "C_shopify": case_c_sovereignty_shopify,
    "C_etsy": case_c_sovereignty_etsy,
    "D": case_d_blind_failure,
    "E": case_e_interpretation_gap,
    "F": case_f_crowded_exhausted,
}


__all__ = [
    "case_a_real_high_vitality", "case_b_bot_hype",
    "case_c_sovereignty_shopify", "case_c_sovereignty_etsy",
    "case_d_blind_failure", "case_e_interpretation_gap",
    "case_f_crowded_exhausted", "ALL_CASES",
]
