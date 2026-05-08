from __future__ import annotations

from typing import Any


class ApolloAbortGuard:
    """Public-domain doctrine reference translated into paper-safe abort logic."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def evaluate(self, signal_context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = signal_context or {}
        alarms: list[dict[str, str]] = []

        def add_alarm(code: str, severity: str, action: str, message: str) -> None:
            alarms.append(
                {
                    "code": code,
                    "severity": severity,
                    "recommended_action": action,
                    "message": message,
                }
            )

        if not context.get("data_truth_origin"):
            add_alarm("A1201_DATA_ORIGIN_MISSING", "CAUTION", "DEGRADE_MODE", "missing data_truth_origin")
        if not context.get("license_boundary"):
            add_alarm("A1202_LICENSE_BOUNDARY_MISSING", "ABORT", "ABORT", "missing license boundary")
        if str(context.get("chaos_state") or "").upper() == "DIABLO" or float(context.get("chaos_score", 0.0) or 0.0) >= float(self.config.get("chaos_threshold", 0.75)):
            add_alarm("A1301_CHAOS_STATE_DIABLO", "ABORT", "NO_NEW_RISK", "chaos veto active")
        if float(context.get("model_disagreement_score", 0.0) or 0.0) >= 0.70:
            add_alarm("A1302_MODEL_DISAGREEMENT_HIGH", "CAUTION", "DEGRADE_MODE", "high disagreement")
        if float(context.get("liquidity_score", 1.0) or 1.0) < 0.25:
            add_alarm("A1401_LIQUIDITY_TOO_LOW", "CAUTION", "NO_NEW_RISK", "liquidity too low")
        if bool(context.get("real_execution_requested", False)):
            add_alarm("A1501_REAL_EXECUTION_REQUESTED", "ABORT", "ABORT", "real execution requested")
        if str(context.get("execution_mode") or "").upper() not in {"PAPER_ONLY", "WATCH_ONLY", "REJECT_ONLY", ""}:
            add_alarm("A1502_EXECUTION_MODE_NOT_PAPER", "ABORT", "ABORT", "execution mode exceeds paper-only boundary")
        if str(context.get("adapter_status") or "").upper() == "ERROR":
            add_alarm("A1601_EXTERNAL_ADAPTER_ERROR", "CAUTION", "DEGRADE_MODE", "adapter status error")
        if not context.get("context_profile"):
            add_alarm("A1701_CONTEXT_PROFILE_MISSING", "CAUTION", "DEGRADE_MODE", "missing context profile")
        if float(context.get("durability_score", 1.0) or 1.0) < float(self.config.get("durability_threshold", 0.65)):
            add_alarm("A1801_DURABILITY_BELOW_THRESHOLD", "CAUTION", "WATCH", "durability below threshold")
        if str(context.get("risk_state") or "").upper() in {"UNSTABLE", "ELEVATED", "CRITICAL"}:
            add_alarm("A1901_RISK_STATE_UNSTABLE", "ABORT", "NO_NEW_RISK", "risk state unstable")

        highest = "CLEAR"
        recommended = "PROCEED_PAPER_ONLY"
        clearance = "CLEAR"
        if any(alarm["severity"] == "ABORT" for alarm in alarms):
            highest = "ABORT"
            recommended = "ABORT"
            clearance = "ABORT"
        elif any(alarm["recommended_action"] == "NO_NEW_RISK" for alarm in alarms):
            highest = "CAUTION"
            recommended = "NO_NEW_RISK"
            clearance = "NO_NEW_RISK"
        elif alarms:
            highest = "CAUTION"
            recommended = "DEGRADE_MODE"
            clearance = "DEGRADED"

        return {
            "apollo_clearance": clearance,
            "alarms": alarms,
            "highest_severity": highest,
            "recommended_action": recommended,
            "real_execution_allowed": False,
        }
