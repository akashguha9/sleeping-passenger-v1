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

    st.markdown("**Opportunity score components**")
    opportunity = case_study["opportunity_score"]
    st.write(
        {
            "opportunity_score": round(float(opportunity["opportunity_score"]), 1),
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
    st.caption(case_study["disclaimer"])
