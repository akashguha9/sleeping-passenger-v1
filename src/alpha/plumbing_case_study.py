"""The Plumbing Alpha Case Study — deterministic offline demonstrator.

Thesis: humans need water; homes require showers, sinks, toilets,
pipes, valves, drainage, repair, tools, distribution, and maintenance.
Plumbing is therefore a long-half-life residual-utility system.  The
alpha is not "buy plumbing"; it is finding the value-chain node that
captures durable profit.

Everything here is hardcoded, deterministic, and offline: it exercises
every framework module end-to-end without network access or live data.
All node inputs are illustrative framework parameters, not researched
financial estimates.  Advisory-only; no tickers are recommended.
"""

from __future__ import annotations

from src.alpha import ADVISORY_DISCLAIMER
from src.alpha.adapters.narrative_snapshot_adapter import summarize_narrative_snapshots
from src.alpha.adapters.prediction_market_adapter import (
    convert_to_prediction_market_signal,
    probability_confirmation_score,
)
from src.alpha.autopsy import build_alpha_autopsy
from src.alpha.casino_food_chain import classify_casino_food_chain
from src.alpha.container import recommend_container
from src.alpha.embedded_proof import detect_embedded_proof
from src.alpha.filing_parser import parse_filing_text
from src.alpha.half_life import estimate_half_life
from src.alpha.journal_replay_bridge import journal_replay_report
from src.alpha.opportunity import aggregate_opportunity_score_v2
from src.alpha.residual_utility import score_residual_utility, score_residual_utility_v2
from src.alpha.triangulation import triangulate
from src.alpha.value_chain import ValueChainNode, map_value_chain
from src.alpha.value_chain_graph import build_plumbing_value_chain_graph

THEME = "residential plumbing and water access"

REQUIRED_NODE_NAMES = (
    "raw_materials",
    "pipes",
    "valves",
    "fittings",
    "faucets",
    "sinks_showers_toilets",
    "fixing_tape_sealants",
    "wrenches_tools",
    "plumbers_contractors",
    "distributors_hardware_stores",
    "smart_leak_sensors",
    "water_meters",
    "insurance_water_damage_prevention",
)

# Illustrative node parameters (0-100).  Necessity is near-uniform — the
# system fails without any of these — so the spread comes from urgency,
# pricing power, repeat demand, bottlenecks, and commoditization.
PLUMBING_NODES: list[ValueChainNode] = [
    ValueChainNode(
        name="raw_materials",
        position="upstream_raw_materials",
        role="copper, PVC, brass, steel feedstock",
        necessity_score=90, urgency_score=35, pricing_power_score=30,
        repeat_demand_score=70, bottleneck_strength=45,
        commoditization_risk=85, input_cost_risk=70,
        candidate_company_types=["metal producers", "resin/polymer manufacturers"],
    ),
    ValueChainNode(
        name="pipes",
        position="upstream_components",
        role="bulk water transport inside the structure",
        necessity_score=95, urgency_score=50, pricing_power_score=35,
        repeat_demand_score=65, bottleneck_strength=50,
        commoditization_risk=80, input_cost_risk=60,
        candidate_company_types=["pipe extruders", "building-products manufacturers"],
    ),
    ValueChainNode(
        name="valves",
        position="upstream_components",
        role="flow control; failure cost is flooding",
        necessity_score=92, urgency_score=75, pricing_power_score=60,
        repeat_demand_score=70, bottleneck_strength=70,
        commoditization_risk=45, input_cost_risk=45,
        candidate_company_types=["flow-control specialists", "industrial valve makers"],
    ),
    ValueChainNode(
        name="fittings",
        position="upstream_components",
        role="joints and couplings; every run needs many",
        necessity_score=90, urgency_score=60, pricing_power_score=50,
        repeat_demand_score=80, bottleneck_strength=55,
        commoditization_risk=55, input_cost_risk=45,
        candidate_company_types=["fitting manufacturers", "fastener specialists"],
    ),
    ValueChainNode(
        name="faucets",
        position="downstream_interface",
        role="visible user interface; carries aesthetic premium",
        necessity_score=85, urgency_score=55, pricing_power_score=70,
        repeat_demand_score=60, bottleneck_strength=40,
        commoditization_risk=50, input_cost_risk=40,
        candidate_company_types=["branded fixture makers", "kitchen/bath brands"],
    ),
    ValueChainNode(
        name="sinks_showers_toilets",
        position="downstream_interface",
        role="fixtures; renovation-cycle demand",
        necessity_score=88, urgency_score=45, pricing_power_score=55,
        repeat_demand_score=55, bottleneck_strength=35,
        commoditization_risk=55, input_cost_risk=45,
        candidate_company_types=["sanitaryware manufacturers", "bath brands"],
    ),
    ValueChainNode(
        name="fixing_tape_sealants",
        position="downstream_service",
        role="emergency consumable; bought at panic speed",
        necessity_score=80, urgency_score=90, pricing_power_score=65,
        repeat_demand_score=85, bottleneck_strength=45,
        commoditization_risk=60, input_cost_risk=30,
        candidate_company_types=["adhesives/sealant makers", "consumables brands"],
    ),
    ValueChainNode(
        name="wrenches_tools",
        position="downstream_service",
        role="enablement layer; professional trust and durability",
        necessity_score=75, urgency_score=55, pricing_power_score=60,
        repeat_demand_score=50, bottleneck_strength=40,
        commoditization_risk=50, input_cost_risk=35,
        candidate_company_types=["professional tool brands"],
    ),
    ValueChainNode(
        name="plumbers_contractors",
        position="downstream_service",
        role="labour scarcity and urgency pricing",
        necessity_score=95, urgency_score=95, pricing_power_score=80,
        repeat_demand_score=85, bottleneck_strength=85,
        commoditization_risk=25, input_cost_risk=50,
        candidate_company_types=["home-services platforms", "franchised trade networks"],
    ),
    ValueChainNode(
        name="distributors_hardware_stores",
        position="midstream_distribution",
        role="inventory and access power; the shelf when it floods",
        necessity_score=85, urgency_score=80, pricing_power_score=65,
        repeat_demand_score=90, bottleneck_strength=70,
        commoditization_risk=35, input_cost_risk=40,
        candidate_company_types=["specialty distributors", "trade-counter retailers"],
    ),
    ValueChainNode(
        name="smart_leak_sensors",
        position="downstream_prevention",
        role="prevention/data layer; optional growth sidecar",
        necessity_score=55, urgency_score=60, pricing_power_score=70,
        repeat_demand_score=55, bottleneck_strength=50,
        commoditization_risk=40, input_cost_risk=35,
        candidate_company_types=["IoT water-monitoring firms", "smart-home device makers"],
    ),
    ValueChainNode(
        name="water_meters",
        position="downstream_prevention",
        role="measurement layer; utility-mandated replacement cycles",
        necessity_score=80, urgency_score=50, pricing_power_score=65,
        repeat_demand_score=70, bottleneck_strength=65,
        commoditization_risk=35, input_cost_risk=40,
        candidate_company_types=["metering technology firms", "utility suppliers"],
    ),
    ValueChainNode(
        name="insurance_water_damage_prevention",
        position="downstream_risk_transfer",
        role="failure-cost monetization layer",
        necessity_score=75, urgency_score=70, pricing_power_score=70,
        repeat_demand_score=90, bottleneck_strength=55,
        commoditization_risk=40, input_cost_risk=55,
        candidate_company_types=["property insurers", "risk-prevention services"],
    ),
]

# Conceptual one-line verdict per node type, from the framework reflection.
NODE_CONCEPTUAL_NOTES: dict[str, str] = {
    "raw_materials": "Input layer: real demand but commodity pricing.",
    "pipes": "Permanent demand but possible commoditization.",
    "valves": "Control-node importance and failure-cost relevance.",
    "fittings": "High-count repeat component with moderate differentiation.",
    "faucets": "Interface layer with aesthetic premium.",
    "sinks_showers_toilets": "Fixture layer tied to renovation cycles.",
    "fixing_tape_sealants": "Emergency consumable layer.",
    "wrenches_tools": "Enablement layer with professional trust.",
    "plumbers_contractors": "Labour scarcity and urgency pricing.",
    "distributors_hardware_stores": "Inventory and access power.",
    "smart_leak_sensors": "Prevention/data layer and optional growth.",
    "water_meters": "Measurement layer with mandated replacement cycles.",
    "insurance_water_damage_prevention": "Failure-cost monetization layer.",
}


def build_plumbing_case_study() -> dict[str, object]:
    """Run the full alpha framework over the plumbing thesis, offline."""
    chain = map_value_chain(THEME, PLUMBING_NODES)

    # Casino vs food-chain: plumbing is the canonical food-chain-heavy
    # theme — no meme energy, strong recurring economics.
    layer = classify_casino_food_chain(
        casino_inputs={
            "mention_velocity": 0.10,
            "sentiment_intensity": 0.20,
            "volume_spike": 0.10,
            "options_activity": 0.10,
            "influencer_density": 0.05,
            "headline_intensity": 0.10,
        },
        food_chain_inputs={
            "revenue_quality": 0.80,
            "fcf_quality": 0.75,
            "gross_margin_quality": 0.60,
            "demand_recurrence": 0.90,
            "pricing_power": 0.65,
            "balance_sheet_strength": 0.65,
            "leverage_risk": 0.35,
            "commoditization_risk": 0.55,
        },
    )

    half_life = estimate_half_life(
        "human_necessity",
        source_quality=0.8,
        proof_strength=0.9,
        recurrence=0.95,
    )

    residual = score_residual_utility(
        utility_inputs={
            "recurring_need": 0.95,
            "non_optional": 0.95,
            "retention_without_hype": 0.95,
            "cost_or_safety_advantage": 0.70,
            "unprompted_repeat_demand": 0.85,
            "failure_urgency": 0.90,
        },
        narrative_inputs={
            "brand_dependence": 0.20,
            "promotion_dependence": 0.10,
            "status_premium": 0.15,
            "speculative_interest": 0.05,
        },
        market_price_expectation=45.0,
        core_job_to_be_done="move clean water in and waste water out of every home",
    )

    proof = detect_embedded_proof(
        narrative_claims=[
            "plumbing demand is unavoidable",
            "failure creates urgent, price-insensitive purchases",
        ],
        verified_evidence=[
            "revenue_segment",
            "audited_financials",
            "shipped_product",
            "regulatory_filing",
        ],
        theme_revenue_share=0.9,
        structurally_theme_native=True,
    )

    opportunity = aggregate_opportunity_score_v2(
        {
            "narrative_velocity": 35.0,
            "probability_confirmation": 50.0,
            "embedded_proof": proof["embedded_proof_score"],
            "node_strength": chain["nodes"][0]["node_attractiveness"],
            "half_life": 95.0,
            "residual_utility": residual["residual_utility_score"],
            "food_chain": layer["food_chain_score"],
            "valuation_risk": 45.0,
            "regulatory_risk": 35.0,
            "commoditization_risk": 55.0,
            "casino_distortion": 10.0,
        },
        half_life_days=float(half_life["half_life_days"]),
        # Illustrative: a mature plumbing 10-K carries routine risk-factor
        # disclosures but no overhang-level findings.
        filing_risk_disclosure_score=30.0,
        evidence_quality=proof["embedded_proof_score"],
        source_quality=60.0,
    )

    node_verdicts = []
    for node_row in chain["nodes"]:
        verdict = recommend_container(
            conviction=float(node_row["node_attractiveness"]),
            volatility=30.0,
            half_life_days=float(half_life["half_life_days"]),
            proof_score=proof["embedded_proof_score"],
            valuation_risk=45.0,
        )
        node_verdicts.append(
            {
                "node": node_row["name"],
                "node_attractiveness": node_row["node_attractiveness"],
                "conceptual_note": NODE_CONCEPTUAL_NOTES.get(str(node_row["name"]), ""),
                "recommended_container": verdict["recommended_container"],
                "reason": verdict["reason"],
            }
        )

    return {
        "case_study": "The Plumbing Alpha Case Study",
        "thesis": (
            "Humans need water. Homes require showers, sinks, toilets, pipes, "
            "valves, drainage, repair, tools, distribution, and maintenance. "
            "Plumbing is a long-half-life residual-utility system; the alpha "
            "is the value-chain node that captures durable profit."
        ),
        "value_chain": chain,
        "value_chain_graph": build_plumbing_value_chain_graph(),
        "casino_food_chain": layer,
        "half_life": half_life,
        "residual_utility": residual,
        "embedded_proof": proof,
        "opportunity_score": opportunity,
        "advisory_verdicts_by_node": node_verdicts,
        "data_provenance": (
            "Hardcoded illustrative parameters; deterministic offline "
            "demonstrator, not researched financial estimates."
        ),
        "disclaimer": ADVISORY_DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# v3 — full-stack demonstration: need -> graph -> evidence -> triangulation
#      -> calibration -> opportunity -> autopsy, with per-node profiles.
# ---------------------------------------------------------------------------

# Deterministic narrative snapshot fixture (manual_stub rows).
_NARRATIVE_AS_OF = "2026-06-01T00:00:00"
_NARRATIVE_ROWS: list[dict[str, object]] = [
    {"theme": "residential plumbing", "source": "newspaper", "timestamp": "2026-05-27T00:00:00",
     "mention_count": 14, "sentiment_score": 0.3, "source_quality": 70},
    {"theme": "residential plumbing", "source": "reddit", "timestamp": "2026-05-29T00:00:00",
     "mention_count": 22, "sentiment_score": 0.4, "source_quality": 45},
    {"theme": "residential plumbing", "source": "youtube", "timestamp": "2026-05-30T00:00:00",
     "mention_count": 9, "sentiment_score": 0.2, "source_quality": 55},
    {"theme": "residential plumbing", "source": "newspaper", "timestamp": "2026-05-20T00:00:00",
     "mention_count": 12, "sentiment_score": 0.1, "source_quality": 70},
    {"theme": "residential plumbing", "source": "reddit", "timestamp": "2026-05-21T00:00:00",
     "mention_count": 18, "sentiment_score": 0.2, "source_quality": 45},
]

# Deterministic prediction-market stub: a water-infrastructure catalyst.
_PM_STUB = {
    "event_name": "US municipal water infrastructure bill passes by year-end",
    "yes_bid": 0.32,
    "yes_ask": 0.36,
    "resolution_date": "2026-12-31",
    "source": "manual_stub",
}
_PM_MODEL_PROBABILITY = 0.41

# Deterministic filing excerpt (manual_stub; illustrative, not a real filing).
_FILING_EXCERPT = """Segment revenue from water-management products grew 12% year over year.
Order backlog increased to $310 million at year end.
Free cash flow was $95 million, with cash provided by operating activities of $120 million.
Capital expenditure commitments for valve manufacturing capacity total $25 million.
We are subject to risks from litigation in the ordinary course of business.
There is no material customer concentration in our distribution segment."""

# Per-node profile parameters (illustrative framework inputs).
_NODE_PROFILES: dict[str, dict[str, object]] = {
    "plumbers_contractors": {
        "casino": {"mention_velocity": 0.15, "sentiment_intensity": 0.25,
                   "volume_spike": 0.10, "options_activity": 0.05,
                   "influencer_density": 0.10, "headline_intensity": 0.15},
        "food_chain": {"revenue_quality": 0.80, "fcf_quality": 0.70,
                       "gross_margin_quality": 0.65, "demand_recurrence": 0.95,
                       "pricing_power": 0.85, "balance_sheet_strength": 0.60,
                       "leverage_risk": 0.35, "commoditization_risk": 0.20},
        "residual_v2": dict(
            job_to_be_done="fix failed water systems under time pressure",
            necessity_type="survival", failure_cost_score=90.0,
            substitution_risk_score=20.0, frequency_score=85.0,
            switching_cost_score=55.0, willingness_to_pay_score=85.0,
            boring_but_essential_score=95.0, narrative_dependency_score=10.0,
        ),
        "valuation_risk": 40.0,
        "notes": "High urgency and failure cost; fragmented local labour "
                 "limits scalability — platform aggregators are the equity angle.",
    },
    "valves": {
        "casino": {"mention_velocity": 0.10, "sentiment_intensity": 0.15,
                   "volume_spike": 0.10, "options_activity": 0.10,
                   "influencer_density": 0.05, "headline_intensity": 0.10},
        "food_chain": {"revenue_quality": 0.75, "fcf_quality": 0.70,
                       "gross_margin_quality": 0.70, "demand_recurrence": 0.80,
                       "pricing_power": 0.65, "balance_sheet_strength": 0.70,
                       "leverage_risk": 0.30, "commoditization_risk": 0.45},
        "residual_v2": dict(
            job_to_be_done="control and stop water flow safely",
            necessity_type="compliance", failure_cost_score=85.0,
            substitution_risk_score=30.0, frequency_score=70.0,
            switching_cost_score=65.0, willingness_to_pay_score=65.0,
            boring_but_essential_score=90.0, narrative_dependency_score=10.0,
        ),
        "valuation_risk": 45.0,
        "notes": "Strong bottleneck with industrial scalability; commoditization "
                 "pressure at the low end.",
    },
    "smart_leak_sensors": {
        "casino": {"mention_velocity": 0.55, "sentiment_intensity": 0.50,
                   "volume_spike": 0.35, "options_activity": 0.30,
                   "influencer_density": 0.40, "headline_intensity": 0.45},
        "food_chain": {"revenue_quality": 0.45, "fcf_quality": 0.35,
                       "gross_margin_quality": 0.60, "demand_recurrence": 0.50,
                       "pricing_power": 0.60, "balance_sheet_strength": 0.50,
                       "leverage_risk": 0.40, "commoditization_risk": 0.40},
        "residual_v2": dict(
            job_to_be_done="detect water leaks before damage compounds",
            necessity_type="productivity", failure_cost_score=75.0,
            substitution_risk_score=45.0, frequency_score=45.0,
            switching_cost_score=50.0, willingness_to_pay_score=55.0,
            boring_but_essential_score=55.0, narrative_dependency_score=45.0,
        ),
        "valuation_risk": 65.0,
        "notes": "Stronger narrative/catalyst with optionality in the data "
                 "layer; adoption and proof risk are the gating questions.",
    },
}


def _build_node_profile(
    node_id: str,
    profile: dict[str, object],
    *,
    graph_nodes: dict[str, dict[str, object]],
    narrative: dict[str, object],
    pm_signal: dict[str, object],
    filing: dict[str, object],
    calibration_support: float,
    outcome_coverage: float,
) -> dict[str, object]:
    layer = classify_casino_food_chain(profile["casino"], profile["food_chain"])
    residual_v2 = score_residual_utility_v2(**profile["residual_v2"])
    node_row = graph_nodes[node_id]
    attractiveness = float(node_row["node_attractiveness"])

    proof = detect_embedded_proof(
        narrative_claims=["plumbing demand is unavoidable"],
        verified_evidence=["revenue_segment", "audited_financials", "shipped_product"],
        theme_revenue_share=0.85 if node_id != "smart_leak_sensors" else 0.35,
        structurally_theme_native=node_id != "smart_leak_sensors",
    )

    tri = triangulate(
        narrative={
            "narrative_velocity_score": narrative["narrative_velocity_score"],
            "confidence": narrative["confidence"],
        },
        prediction_market={
            "probability_edge": pm_signal["probability_edge"],
            "confidence": pm_signal["confidence"],
        },
        filing={
            "embedded_proof_score": filing["embedded_proof_score"],
            "filing_risk_disclosure_score": filing["filing_risk_disclosure_score"],
        },
        value_chain={"node_attractiveness": attractiveness},
        replay={"calibration_support": calibration_support},
    )

    components = {
        "narrative_velocity": float(narrative["narrative_velocity_score"]),
        "probability_confirmation": probability_confirmation_score(
            float(pm_signal["probability_edge"]), float(pm_signal["confidence"])
        ),
        "embedded_proof": float(proof["embedded_proof_score"]),
        "node_strength": attractiveness,
        "half_life": 90.0 if node_id != "smart_leak_sensors" else 60.0,
        "residual_utility": float(residual_v2["residual_utility_score"]),
        "food_chain": float(layer["food_chain_score"]),
        "valuation_risk": float(profile["valuation_risk"]),
        "regulatory_risk": 35.0,
        "commoditization_risk": float(profile["food_chain"]["commoditization_risk"]) * 100.0,
        "casino_distortion": float(layer["casino_score"]),
    }
    opportunity = aggregate_opportunity_score_v2(
        components,
        half_life_days=3650.0,
        filing_risk_disclosure_score=float(filing["filing_risk_disclosure_score"]),
        evidence_quality=float(proof["embedded_proof_score"]),
        source_quality=60.0,
        calibration_support=calibration_support,
        outcome_coverage=outcome_coverage,
        triangulation=tri,
    )
    container = recommend_container(
        conviction=float(opportunity["opportunity_score"]),
        volatility=35.0 if node_id != "smart_leak_sensors" else 60.0,
        half_life_days=3650.0,
        proof_score=float(proof["embedded_proof_score"]),
        valuation_risk=float(profile["valuation_risk"]),
    )
    return {
        "node_id": node_id,
        "notes": profile["notes"],
        "casino_score": layer["casino_score"],
        "food_chain_score": layer["food_chain_score"],
        "casino_food_chain_classification": layer["classification"],
        "residual_utility_class": residual_v2["residual_utility_class"],
        "residual_utility_score": residual_v2["residual_utility_score"],
        "embedded_proof_class": proof["classification"],
        "node_attractiveness": attractiveness,
        "triangulation_class": tri["triangulation_class"],
        "triangulation_score": tri["triangulation_score"],
        "trap_flags": opportunity["trap_flags"],
        "opportunity_score": opportunity["opportunity_score"],
        "confidence": opportunity["confidence"],
        "advisory_verdict": opportunity["advisory_verdict"],
        "why_not_higher": opportunity["why_not_higher"],
        "why_not_lower": opportunity["why_not_lower"],
        "advisory_container": container["recommended_container"],
    }


def build_plumbing_case_study_v3() -> dict[str, object]:
    """Full-stack deterministic demonstration of the intelligence pipeline.

    need -> value-chain graph -> residual utility -> narrative snapshot ->
    prediction-market stub -> filing evidence -> triangulation -> replay
    calibration -> opportunity v2 -> alpha autopsy.  All inputs are
    illustrative manual_stub fixtures; journal calibration is read live
    from the (test-isolated) journal DB and is expected to be empty.
    """
    base = build_plumbing_case_study()
    graph_nodes = {
        str(row["node_id"]): row for row in base["value_chain_graph"]["nodes"]
    }

    narrative = summarize_narrative_snapshots(
        _NARRATIVE_ROWS, as_of=_NARRATIVE_AS_OF, window_days=7
    )
    pm_signal = convert_to_prediction_market_signal(
        _PM_STUB, _PM_MODEL_PROBABILITY
    ).to_dict()
    filing = parse_filing_text(
        _FILING_EXCERPT,
        source_type="manual_excerpt",
        narrative_claims=["plumbing demand is unavoidable"],
    )
    journal = journal_replay_report()
    calibration_support = float(journal["calibration_support"])
    outcome_coverage = float(journal["outcome_coverage"])

    node_profiles = {
        node_id: _build_node_profile(
            node_id,
            profile,
            graph_nodes=graph_nodes,
            narrative=narrative,
            pm_signal=pm_signal,
            filing=filing,
            calibration_support=calibration_support,
            outcome_coverage=outcome_coverage,
        )
        for node_id, profile in _NODE_PROFILES.items()
    }

    top_profile = node_profiles["plumbers_contractors"]
    autopsy = build_alpha_autopsy(
        signal_name="residential plumbing / plumbers_contractors node",
        components={
            "narrative_velocity": float(narrative["narrative_velocity_score"]),
            "embedded_proof": float(filing["embedded_proof_score"]),
            "node_strength": float(top_profile["node_attractiveness"]),
            "half_life": 95.0,
            "residual_utility": float(top_profile["residual_utility_score"]),
            "food_chain": float(top_profile["food_chain_score"]),
            "casino_distortion": float(top_profile["casino_score"]),
        },
        opportunity={
            "advisory_verdict": top_profile["advisory_verdict"],
            "trap_flags": top_profile["trap_flags"],
            "why_not_higher": top_profile["why_not_higher"],
            "missing_inputs": [],
        },
        filing_parse=filing,
        triangulation=triangulate(
            narrative={
                "narrative_velocity_score": narrative["narrative_velocity_score"],
                "confidence": narrative["confidence"],
            },
            prediction_market={
                "probability_edge": pm_signal["probability_edge"],
                "confidence": pm_signal["confidence"],
            },
            filing={
                "embedded_proof_score": filing["embedded_proof_score"],
                "filing_risk_disclosure_score": filing["filing_risk_disclosure_score"],
            },
            value_chain={
                "node_attractiveness": top_profile["node_attractiveness"]
            },
            replay={"calibration_support": calibration_support},
        ),
        residual_utility={
            "residual_utility_class": top_profile["residual_utility_class"],
            "residual_utility_score": top_profile["residual_utility_score"],
        },
        half_life=base["half_life"],
        value_chain_node="plumbers_contractors",
        calibration_support=calibration_support,
    )

    return {
        **base,
        "version": "v3",
        "narrative_snapshot": narrative,
        "prediction_market_stub": pm_signal,
        "filing_excerpt_parse": {
            "classification": filing["classification"],
            "embedded_proof_score": filing["embedded_proof_score"],
            "substrate_score": filing["substrate_score"],
            "filing_risk_disclosure_score": filing["filing_risk_disclosure_score"],
            "evidence_count": len(filing["evidence"]),
            "risk_mitigation_count": len(filing["risk_mitigations"]),
        },
        "calibration_state": {
            "calibration_support": calibration_support,
            "outcome_coverage": outcome_coverage,
            "discovered_records": journal["bridge"]["discovered_records"],
            "usable_records": journal["bridge"]["usable_records"],
        },
        "node_profiles": node_profiles,
        "autopsy": autopsy,
    }
