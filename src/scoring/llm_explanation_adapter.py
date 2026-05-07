"""Deterministic local explanation adapter.

LLMRole = Context + Explanation + Counterargument
FinalDecision = PipelineRules
"""

from __future__ import annotations

from src.models.market import MarketSnapshot
from src.models.signal import SignalScore


class ExplanationAdapter:
    """Generate deterministic local signal explanations without external APIs."""

    @staticmethod
    def explain_signal(market_snapshot: MarketSnapshot, signal_score: SignalScore) -> str:
        return (
            f"{market_snapshot.question} classified as {signal_score.state} because "
            f"EQS={signal_score.evidence_quality_score:.2f}, "
            f"DS={signal_score.durability_score:.2f}, "
            f"LS={signal_score.liquidity_score:.2f}, "
            f"EMS={signal_score.engagement_manipulation_score:.2f}, "
            f"EFS={signal_score.execution_friction_score:.2f}, "
            f"APS={signal_score.admission_priority_score:.2f}. "
            "This explanation is advisory only and never overrides the deterministic pipeline state."
        )
