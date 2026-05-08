from __future__ import annotations

from typing import Any


class ApolloChecklistGate:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def evaluate(self, signal_context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = signal_context or {}
        minimum_sources = int(self.config.get("minimum_source_count", 2) or 2)
        chaos_threshold = float(self.config.get("chaos_threshold", 0.75) or 0.75)
        durability_threshold = float(self.config.get("durability_threshold", 0.65) or 0.65)
        evidence_quality_threshold = float(self.config.get("evidence_quality_threshold", 0.60) or 0.60)

        checks = {
            "source_count": int(context.get("source_count", 0) or 0) >= minimum_sources,
            "data_truth_origin": bool(context.get("data_truth_origin")),
            "license_boundary": bool(context.get("license_boundary")),
            "context_profile": bool(context.get("context_profile")),
            "risk_state": bool(context.get("risk_state")),
            "chaos_state": str(context.get("chaos_state") or "").upper() != "DIABLO",
            "chaos_score": float(context.get("chaos_score", 0.0) or 0.0) < chaos_threshold,
            "durability_score": float(context.get("durability_score", 0.0) or 0.0) >= durability_threshold,
            "execution_mode": str(context.get("execution_mode") or "").upper() in {"PAPER_ONLY", "WATCH_ONLY", "REJECT_ONLY"},
            "real_execution_allowed": bool(context.get("real_execution_allowed", False)) is False,
            "real_execution_requested": bool(context.get("real_execution_requested", False)) is False,
            "evidence_quality_score": float(context.get("evidence_quality_score", 0.0) or 0.0) >= evidence_quality_threshold,
            "adapter_status": str(context.get("adapter_status") or "").upper() != "ERROR",
            "abort_alarm_clear": not any(str(code).startswith("A12") or str(code).startswith("A15") for code in context.get("abort_alarm_codes", [])),
            "murcielago_validation": bool(context.get("murcielago_validation_passed", False)),
            "gallardo_paper_only": str(context.get("execution_mode") or "").upper() != "LIVE",
        }
        passed_items = [name for name, passed in checks.items() if passed]
        failed_items = [name for name, passed in checks.items() if not passed]
        warnings = []
        if failed_items and len(failed_items) < 3:
            clearance = "DEGRADED"
            max_allowed_action = "WATCH"
            warnings.append("checklist partially satisfied; degrade to watch-only")
        elif failed_items:
            clearance = "FAIL"
            max_allowed_action = "REJECT"
        else:
            clearance = "PASS"
            max_allowed_action = "PAPER_TRADE" if str(context.get("execution_mode") or "").upper() == "PAPER_ONLY" else "WATCH"
        return {
            "checklist_clearance": clearance,
            "passed_items": passed_items,
            "failed_items": failed_items,
            "warnings": warnings,
            "max_allowed_action": max_allowed_action,
            "real_execution_allowed": False,
        }
