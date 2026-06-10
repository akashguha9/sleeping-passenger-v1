"""Streamlit section: Alpha Framework / Plumbing Case Study.

Renders the reflection-derived alpha framework and its deterministic
offline plumbing demonstrator.  Read-only and advisory-only: nothing
here writes state or touches a broker surface.
"""

from __future__ import annotations

from src.alpha import ADVISORY_DISCLAIMER
from src.alpha.plumbing_case_study import build_plumbing_case_study

_FRAMEWORK_SUMMARY = (
    "Markets are casinos sitting on top of real-world food chains. "
    "The framework separates hype (casino layer) from unavoidable "
    "residual utility (food-chain layer), decays every signal by its "
    "half-life, demands embedded proof for theme claims, and maps broad "
    "human needs into the Porter value-chain nodes that actually capture "
    "profit."
)


def render_alpha_framework_section(st) -> None:
    """Render the framework section into an active Streamlit context.

    ``st`` is passed in (rather than imported) so the module stays
    importable and testable without Streamlit installed.
    """
    case_study = build_plumbing_case_study()
    st.subheader("Alpha Framework / Plumbing Case Study")
    st.caption(ADVISORY_DISCLAIMER)
    st.write(_FRAMEWORK_SUMMARY)
    st.write({"thesis": case_study["thesis"]})

    st.markdown("**Value-chain nodes (ranked by attractiveness)**")
    st.dataframe(case_study["value_chain"]["nodes"])

    st.markdown("**Casino vs food-chain classification**")
    layer = case_study["casino_food_chain"]
    st.write(
        {
            "casino_score": round(float(layer["casino_score"]), 1),
            "food_chain_score": round(float(layer["food_chain_score"]), 1),
            "classification": layer["classification"],
        }
    )

    st.markdown("**Opportunity score components (evidence-weighted v2)**")
    opportunity = case_study["opportunity_score"]
    st.write(
        {
            "opportunity_score": round(float(opportunity["opportunity_score"]), 1),
            "confidence": round(float(opportunity.get("confidence", 0.0)), 1),
            "advisory_verdict": opportunity["advisory_verdict"],
            "missing_inputs": opportunity["missing_inputs"],
        }
    )
    st.dataframe(
        [
            {"component": key, "score": round(float(value), 1)}
            for key, value in opportunity["score_components"].items()
        ]
    )

    st.markdown("**Trap flags / why not higher / why not lower**")
    st.write(
        {
            "trap_flags": opportunity.get("trap_flags", []) or ["none raised"],
            "why_not_higher": opportunity.get("why_not_higher", []),
            "why_not_lower": opportunity.get("why_not_lower", []),
        }
    )

    st.markdown("**Value-chain graph (nodes, edges, failure-cost math)**")
    graph = case_study.get("value_chain_graph", {})
    st.write(
        {
            "node_count": graph.get("node_count", 0),
            "edge_count": graph.get("edge_count", 0),
            "graph_valid": graph.get("graph_valid", False),
            "top_node": graph.get("top_node"),
        }
    )
    st.dataframe(
        [
            {
                "node": row["node_id"],
                "position": row["position"],
                "attractiveness": round(float(row["node_attractiveness"]), 1),
                "failure_cost": row["failure_cost_score"],
                "replacement_cycle": row["replacement_cycle_score"],
                "children": ", ".join(row["children"]),
            }
            for row in graph.get("nodes", [])
        ]
    )

    st.markdown("**Advisory verdicts by node**")
    st.dataframe(case_study["advisory_verdicts_by_node"])

    st.markdown("**Residual utility / half-life / embedded proof**")
    st.write(
        {
            "residual_utility_score": round(
                float(case_study["residual_utility"]["residual_utility_score"]), 1
            ),
            "residual_alpha_proxy": round(
                float(case_study["residual_utility"]["residual_alpha_proxy"]), 1
            ),
            "half_life_days": round(float(case_study["half_life"]["half_life_days"]), 1),
            "embedded_proof_classification": case_study["embedded_proof"][
                "classification"
            ],
            "data_provenance": case_study["data_provenance"],
        }
    )

    st.markdown("**Replay metrics (deterministic demo fixtures)**")
    from src.alpha.replay import demo_replay_dataset, evaluate_replay

    replay = evaluate_replay(demo_replay_dataset(), k=2)
    st.write(
        {
            "record_count": replay["record_count"],
            "outcome_counts": replay["outcome_counts"],
            "precision_at_k": replay["precision_at_k"],
            "brier_score": replay["brier_score"],
            "trap_flag_false_positive_rate": replay["trap_flag_false_positive_rate"],
            "calibration_support": replay["calibration_support"],
            "data_provenance": "manual_stub demo fixtures, not live outcomes",
        }
    )
    st.caption(replay["disclaimer"])

    st.markdown("**Filing excerpt parser (offline, deterministic)**")
    filing_text = st.text_area(
        "Paste a filing excerpt to extract evidence with lineage "
        "(parsed locally; nothing is stored or transmitted):",
        value="",
        key="alpha_filing_excerpt",
    )
    if filing_text and filing_text.strip():
        from src.alpha.filing_parser import parse_filing_text

        parsed = parse_filing_text(filing_text[:100_000], source_type="manual_excerpt")
        st.write(
            {
                "classification": parsed["classification"],
                "embedded_proof_score": round(float(parsed["embedded_proof_score"]), 1),
                "substrate_score": round(float(parsed["substrate_score"]), 1),
                "filing_risk_disclosure_score": round(
                    float(parsed["filing_risk_disclosure_score"]), 1
                ),
            }
        )
        st.dataframe(parsed["evidence"] + parsed["risk_disclosures"])

    st.caption(case_study["disclaimer"])
