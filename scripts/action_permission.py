"""Canonical action-permission resolver.

This module implements the single canonical function that turns a
runtime context (truth origin, evidence summary, policy state, position
integrity, calibration status, chaos veto, etc.) into an
``ActionPermissionResult``.

Rules — in order:

    1. ``external_signal_count == 0`` → ``BLOCK_CAPITAL`` with
       ``NO_EXTERNAL_TRUTH``.
    2. ``truth_origin in {SEEDED, DEMO}`` → demo/research only.
    3. ``position_integrity_state == DIVERGED`` → ``BLOCK_CAPITAL`` with
       ``POSITION_DIVERGED``.
    4. ``policy_state == RESTRICTED`` → ``BLOCK_CAPITAL`` unless
       demo/research.
    5. Chaos veto active → ``BLOCK_CAPITAL`` (or quarantine when state
       supports it).
    6. Calibration missing → no decision-ready claim.
    7. ``contextual_interpretation_enabled is False`` → confidence
       downgrade warning.

Multiple veto reasons may stack; the strongest blocking permission
wins. The resolver is deterministic — same inputs, same output.
"""
from __future__ import annotations

from typing import Any, Iterable

try:
    from scripts.runtime_contracts import (
        ActionPermission,
        ActionPermissionResult,
        EvidenceLedgerSummary,
        PolicyState,
        PositionIntegrityState,
        TruthOrigin,
        VetoReason,
        coerce_policy_state,
        coerce_position_state,
        coerce_truth_origin,
        is_external_truth_origin,
    )
except ModuleNotFoundError:  # pragma: no cover
    from runtime_contracts import (  # type: ignore[no-redef]
        ActionPermission,
        ActionPermissionResult,
        EvidenceLedgerSummary,
        PolicyState,
        PositionIntegrityState,
        TruthOrigin,
        VetoReason,
        coerce_policy_state,
        coerce_position_state,
        coerce_truth_origin,
        is_external_truth_origin,
    )


_BLOCK_CAPITAL_FORBIDDEN_USE: tuple[str, ...] = (
    "capital deployment",
    "investment advice",
    "automated execution",
)
_DEMO_ALLOWED_USE: tuple[str, ...] = (
    "demo/research diagnostics only",
    "internal review",
    "narrative/structure exploration",
)
_RESEARCH_ALLOWED_USE: tuple[str, ...] = (
    "research diagnostics",
    "internal experimentation",
)


def _strongest(*permissions: ActionPermission) -> ActionPermission:
    """Pick the most restrictive permission among the given values.

    Order (most restrictive first): BLOCK_CAPITAL, QUARANTINE,
    DEMO_ONLY, RESEARCH_ONLY, PAPER_TRADING_ONLY,
    DECISION_SUPPORT_ADVISORY, DEPLOY_CAPITAL.
    """

    order = [
        ActionPermission.BLOCK_CAPITAL,
        ActionPermission.QUARANTINE,
        ActionPermission.DEMO_ONLY,
        ActionPermission.RESEARCH_ONLY,
        ActionPermission.PAPER_TRADING_ONLY,
        ActionPermission.DECISION_SUPPORT_ADVISORY,
        ActionPermission.DEPLOY_CAPITAL,
    ]
    for candidate in order:
        if candidate in permissions:
            return candidate
    return ActionPermission.BLOCK_CAPITAL


def resolve_action_permission(
    *,
    truth_origin: TruthOrigin | str,
    external_signal_count: int,
    position_integrity_state: PositionIntegrityState | str,
    policy_state: PolicyState | str,
    chaos_veto_active: bool = False,
    chaos_veto_quarantine: bool = False,
    calibration_missing: bool = True,
    calibration_heuristic_only: bool = True,
    contextual_interpretation_enabled: bool = True,
    evidence_summary: EvidenceLedgerSummary | None = None,
    jail_mode_active: bool = False,
    extra_veto_reasons: Iterable[VetoReason] | None = None,
) -> ActionPermissionResult:
    """Resolve canonical action permission from runtime inputs."""

    truth_origin_enum = coerce_truth_origin(truth_origin)
    position_state_enum = coerce_position_state(position_integrity_state)
    policy_state_enum = coerce_policy_state(policy_state)

    veto_reasons: list[VetoReason] = []
    warnings: list[str] = []
    permissions: list[ActionPermission] = []
    confidence_downgrade = False
    explanation_bits: list[str] = []

    if extra_veto_reasons:
        for reason in extra_veto_reasons:
            if isinstance(reason, VetoReason) and reason not in veto_reasons:
                veto_reasons.append(reason)

    # Rule 1 — external truth gate
    has_external_truth = bool(external_signal_count) and external_signal_count > 0
    if evidence_summary is not None:
        # Cross-check: trust the typed ledger over a loose integer.
        has_external_truth = (
            has_external_truth and evidence_summary.has_external_truth
        )
    if not has_external_truth:
        veto_reasons.append(VetoReason.NO_EXTERNAL_TRUTH)
        permissions.append(ActionPermission.BLOCK_CAPITAL)
        explanation_bits.append(
            "no external truth observed (LIVE_EXTERNAL or REPLAY_LABELED count is zero)"
        )

    # Rule 2 — seeded/demo truth gate
    if truth_origin_enum == TruthOrigin.SEEDED:
        veto_reasons.append(VetoReason.SEEDED_TRUTH_ONLY)
        permissions.append(ActionPermission.DEMO_ONLY)
        explanation_bits.append("truth_origin=SEEDED so capital deployment is blocked")
    elif truth_origin_enum == TruthOrigin.DEMO:
        veto_reasons.append(VetoReason.DEMO_TRUTH_ONLY)
        permissions.append(ActionPermission.DEMO_ONLY)
        explanation_bits.append("truth_origin=DEMO so capital deployment is blocked")
    elif truth_origin_enum in {TruthOrigin.UNKNOWN, TruthOrigin.REPLAY}:
        # Replay without labels is research-only.
        permissions.append(ActionPermission.RESEARCH_ONLY)
        explanation_bits.append(
            f"truth_origin={truth_origin_enum.value} cannot support capital deployment"
        )

    # Rule 3 — position divergence
    if position_state_enum == PositionIntegrityState.DIVERGED:
        veto_reasons.append(VetoReason.POSITION_DIVERGED)
        permissions.append(ActionPermission.BLOCK_CAPITAL)
        explanation_bits.append("position sources diverge")
    elif position_state_enum in {
        PositionIntegrityState.UNKNOWN,
        PositionIntegrityState.MISSING_SOURCE,
        PositionIntegrityState.STALE_SOURCE,
        PositionIntegrityState.QUANTITY_MISMATCH,
        PositionIntegrityState.PRICE_MISMATCH,
    }:
        veto_reasons.append(VetoReason.POSITION_UNKNOWN)
        permissions.append(ActionPermission.BLOCK_CAPITAL)
        explanation_bits.append(
            f"position_integrity_state={position_state_enum.value} is not RECONCILED"
        )

    # Rule 4 — policy state
    if policy_state_enum == PolicyState.RESTRICTED:
        veto_reasons.append(VetoReason.POLICY_RESTRICTED)
        permissions.append(ActionPermission.BLOCK_CAPITAL)
        explanation_bits.append("policy_state=RESTRICTED")
    elif policy_state_enum in {PolicyState.BLOCKED, PolicyState.DO_NOT_DEPLOY}:
        veto_reasons.append(VetoReason.POLICY_BLOCKED)
        permissions.append(ActionPermission.BLOCK_CAPITAL)
        explanation_bits.append(f"policy_state={policy_state_enum.value}")

    # Rule 5 — chaos veto
    if chaos_veto_active:
        veto_reasons.append(VetoReason.CHAOS_VETO)
        if chaos_veto_quarantine:
            permissions.append(ActionPermission.QUARANTINE)
            explanation_bits.append("chaos veto active → quarantine")
        else:
            permissions.append(ActionPermission.BLOCK_CAPITAL)
            explanation_bits.append("chaos veto active → block capital")

    # Rule 6 — calibration
    if calibration_missing:
        veto_reasons.append(VetoReason.CALIBRATION_MISSING)
        permissions.append(ActionPermission.RESEARCH_ONLY)
        explanation_bits.append(
            "calibration missing — scores are uncalibrated and not decision-ready"
        )
    elif calibration_heuristic_only:
        veto_reasons.append(VetoReason.CALIBRATION_HEURISTIC)
        warnings.append(
            "calibration_heuristic: thresholds are heuristic and not externally"
            " validated against outcome labels."
        )
        confidence_downgrade = True

    # Rule 7 — interpretation disabled
    if not contextual_interpretation_enabled:
        veto_reasons.append(VetoReason.INTERPRETATION_DISABLED)
        warnings.append(
            "contextual_interpretation_disabled: confidence is downgraded because"
            " contextual interpretation is not active."
        )
        confidence_downgrade = True

    if jail_mode_active:
        veto_reasons.append(VetoReason.JAIL_MODE_ACTIVE)
        permissions.append(ActionPermission.BLOCK_CAPITAL)
        explanation_bits.append("jail_mode_active blocks all new-risk deployment")

    if not permissions:
        # No blockers and no demo/research downgrade — but we still
        # require external truth + valid calibration to upgrade beyond
        # advisory.
        permissions.append(ActionPermission.DECISION_SUPPORT_ADVISORY)
        explanation_bits.append(
            "no blocking veto detected, but capital deployment requires"
            " explicit operator approval and calibration coverage"
        )

    canonical = _strongest(*permissions)

    if canonical in {ActionPermission.BLOCK_CAPITAL, ActionPermission.QUARANTINE}:
        if (
            VetoReason.SEEDED_TRUTH_ONLY in veto_reasons
            or VetoReason.DEMO_TRUTH_ONLY in veto_reasons
        ):
            allowed_use = _DEMO_ALLOWED_USE
        else:
            allowed_use = _RESEARCH_ALLOWED_USE
        forbidden_use = _BLOCK_CAPITAL_FORBIDDEN_USE
    elif canonical == ActionPermission.DEMO_ONLY:
        allowed_use = _DEMO_ALLOWED_USE
        forbidden_use = _BLOCK_CAPITAL_FORBIDDEN_USE
    elif canonical == ActionPermission.RESEARCH_ONLY:
        allowed_use = _RESEARCH_ALLOWED_USE
        forbidden_use = _BLOCK_CAPITAL_FORBIDDEN_USE
    elif canonical == ActionPermission.PAPER_TRADING_ONLY:
        allowed_use = ("paper trading only",)
        forbidden_use = ("live capital deployment", "automated execution")
    elif canonical == ActionPermission.DECISION_SUPPORT_ADVISORY:
        allowed_use = (
            "decision support / advisory diagnostics with operator review",
        )
        forbidden_use = ("automated execution", "unsupervised capital deployment")
    else:
        allowed_use = ("operator-approved capital deployment",)
        forbidden_use = ()

    explanation = (
        "; ".join(explanation_bits) if explanation_bits else "all gates passed"
    )

    # Deduplicate veto reasons preserving order.
    seen: list[VetoReason] = []
    for reason in veto_reasons:
        if reason not in seen:
            seen.append(reason)

    return ActionPermissionResult(
        canonical_action_permission=canonical,
        veto_reasons=tuple(seen),
        warnings=tuple(warnings),
        allowed_use=tuple(allowed_use),
        forbidden_use=tuple(forbidden_use),
        explanation=explanation,
        confidence_downgrade=confidence_downgrade,
    )


def format_action_permission_summary(result: ActionPermissionResult) -> list[str]:
    """Format an ActionPermissionResult as health-summary lines."""

    veto = ",".join(reason.value for reason in result.veto_reasons) or "NONE"
    allowed = "; ".join(result.allowed_use) if result.allowed_use else "none"
    forbidden = "; ".join(result.forbidden_use) if result.forbidden_use else "none"
    return [
        f"canonical_action_permission={result.canonical_action_permission.value}",
        f"veto_reasons=[{veto}]",
        f"allowed_use={allowed}",
        f"forbidden_use={forbidden}",
        f"action_permission_explanation={result.explanation}",
    ]


__all__ = [
    "format_action_permission_summary",
    "resolve_action_permission",
]
