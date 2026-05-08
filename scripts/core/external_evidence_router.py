from __future__ import annotations

from typing import Any

from scripts.core.apollo_abort_guard import ApolloAbortGuard
from scripts.external_adapters.base import ExternalEvidence, ExternalEvidenceType


class ExternalEvidenceRouter:
    def __init__(self, apollo_guard: ApolloAbortGuard | None = None) -> None:
        self.apollo_guard = apollo_guard or ApolloAbortGuard()

    def route(
        self,
        evidence: ExternalEvidence | dict[str, Any],
        pipeline_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = evidence.to_dict() if isinstance(evidence, ExternalEvidence) else dict(evidence)
        pipeline = pipeline_context or {}
        blocked_actions = ["REAL_EXECUTION"]
        apollo = self.apollo_guard.evaluate({**pipeline, **payload})
        evidence_type = str(payload.get("evidence_type") or ExternalEvidenceType.UNKNOWN.value)
        max_allowed_action = "WATCH"
        path: list[str]
        notes: list[str] = []
        if not payload.get("license_boundary"):
            blocked_actions.append("PAPER_TRADE")
            max_allowed_action = "REJECT"
            notes.append("missing license boundary blocks evidence admission")
        if apollo["apollo_clearance"] == "ABORT":
            blocked_actions.append("PAPER_TRADE")
            max_allowed_action = "REJECT"
            notes.append("Apollo ABORT blocks downstream promotion")
        if str(pipeline.get("chaos_state") or "").upper() == "DIABLO":
            blocked_actions.append("PAPER_TRADE")
            max_allowed_action = "REJECT"
            notes.append("DIABLO chaos veto blocks paper trade")

        if evidence_type == ExternalEvidenceType.PREDICTION_MARKET.value:
            path = ["RawSignal", "Contextual Interpretation", "Perception Control", "Murcielago Durability", "Aventador Candidate"]
            max_allowed_action = "WATCH" if max_allowed_action != "REJECT" else max_allowed_action
        elif evidence_type == ExternalEvidenceType.CANDLESTICK_FORECAST.value:
            path = ["TechnicalEvidence", "Contextual Interpretation", "Murcielago Durability"]
            max_allowed_action = "WATCH" if max_allowed_action != "REJECT" else max_allowed_action
            notes.append("Kronos technical evidence alone cannot paper trade")
        elif evidence_type == ExternalEvidenceType.AGENT_COMMITTEE.value:
            path = ["AgentOpinion", "Perception Control", "Murcielago Durability", "Diablo Veto", "Apollo Checklist"]
            max_allowed_action = "PAPER_TRADE" if max_allowed_action != "REJECT" else max_allowed_action
        elif evidence_type == ExternalEvidenceType.NARRATIVE_TREND.value:
            path = ["NarrativeSignal", "Engagement Intent Engine", "Perception Distortion Engine", "Murcielago Durability"]
            max_allowed_action = "WATCH" if max_allowed_action != "REJECT" else max_allowed_action
            notes.append("TrendRadar alone cannot paper trade")
        elif evidence_type == ExternalEvidenceType.MISSION_SAFETY.value:
            path = ["ApolloGuard", "Safety override"]
            max_allowed_action = "REJECT"
        elif evidence_type == ExternalEvidenceType.TERMINAL_ANALYTICS.value:
            path = ["AnalyticsEvidence", "Contextual Interpretation", "Durability Validation"]
            max_allowed_action = "WATCH" if max_allowed_action != "REJECT" else max_allowed_action
        else:
            path = ["UnknownEvidence", "Manual Review"]
            max_allowed_action = "REJECT"

        return {
            "original_source": payload.get("source"),
            "evidence_type": evidence_type,
            "raw_signal_candidate": payload.get("normalized_payload"),
            "recommended_pipeline_path": path,
            "required_gates": [
                "Apollo Checklist",
                "Diablo Clearance",
                "Murcielago Validation",
                "Contextual Interpretation",
            ],
            "blocked_actions": blocked_actions,
            "max_allowed_action": max_allowed_action,
            "real_execution_allowed": False,
            "requires_apollo_checklist": True,
            "requires_diablo_clearance": True,
            "requires_murcielago_validation": True,
            "requires_contextual_interpretation": True,
            "notes": notes,
        }
