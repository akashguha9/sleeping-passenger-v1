from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.external_adapters.base import (
    ExternalAdapter,
    ExternalAdapterStatus,
    ExternalEvidence,
    ExternalEvidenceType,
    ExternalExecutionPermission,
    bounded_score,
    safe_float,
    safe_str,
)


class TradingAgentsAdapter(ExternalAdapter):
    source_name = "tradingagents"
    evidence_type = ExternalEvidenceType.AGENT_COMMITTEE
    license_boundary = "Apache-2.0 optional agent committee"
    default_execution_permission = ExternalExecutionPermission.PAPER_ONLY

    @staticmethod
    def _sanitize_recommendation(raw_action: str, validation_flags: bool) -> str:
        action = safe_str(raw_action, "WATCH").upper()
        if action in {"BUY", "EXECUTE"}:
            return "PAPER_TRADE" if validation_flags else "WATCH"
        if action in {"SELL", "SHORT", "LONG", "HOLD", "STRONG_BUY"}:
            return "WATCH"
        if action in {"PAPER_TRADE", "WATCH", "REJECT"}:
            if action == "PAPER_TRADE" and not validation_flags:
                return "WATCH"
            return action
        return "WATCH"

    def _load_payload(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        ctx = context or {}
        if isinstance(ctx.get("committee_payload"), dict):
            return dict(ctx["committee_payload"])
        path_value = safe_str(ctx.get("path"))
        if path_value:
            path = Path(path_value)
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        return {
            "recommended_action": "WATCH",
            "confidence": 0.5,
            "dissent_level": 0.3,
            "agent_votes": [{"agent": "risk", "vote": "WATCH"}],
            "validation_flags": False,
        }

    def collect(self, context: dict[str, Any] | None = None) -> list[ExternalEvidence]:
        if not bool(self.config.get("enabled", False)):
            return []
        payload = self._load_payload(context)
        validation_flags = bool(payload.get("validation_flags", False))
        sanitized_action = self._sanitize_recommendation(
            safe_str(payload.get("recommended_action")),
            validation_flags=validation_flags,
        )
        confidence = bounded_score(payload.get("confidence", 0.5))
        dissent = bounded_score(payload.get("dissent_level", 0.0))
        evidence_quality = bounded_score((confidence * 0.7) + ((1.0 - dissent) * 0.3))
        normalized = {
            "recommended_action": sanitized_action,
            "confidence": confidence,
            "dissent_level": dissent,
            "evidence_quality_score": evidence_quality,
            "agent_votes": payload.get("agent_votes", []),
            "broker_execution_allowed": False,
            "paper_execution_max": True,
            "requires_murcielago_validation": True,
            "requires_apollo_checklist": True,
            "requires_diablo_veto_clearance": True,
        }
        return [
            self.build_evidence(
                normalized_payload=normalized,
                data_truth_origin="llm_agent_committee",
                adapter_status=ExternalAdapterStatus.AVAILABLE if bool(self.config.get("dry_run", True)) else ExternalAdapterStatus.DEGRADED,
                warnings=[],
                errors=[],
                confidence_proxy=confidence,
                evidence_quality_score=evidence_quality,
                context_tags=["agent_committee", "paper_only", "apache_optional"],
            )
        ]
