"""Objective 7 — central admission / veto contract (pure, advisory-only).

State and archetype labels should not merely *describe* risk; some states must
*block* advisory promotion.  Rather than rewrite every state engine, this
module provides one pure gate function the decision path can call.

    G_safety    = I(ADVISORY_ONLY) · I(HUMAN_EXECUTION_REQUIRED)
                · I(execution_gate=LOCKED) · I(broker_api_called=false)
                · I(ai_execution_count=0)
    G_state     = I(state != DIABLO) · I(shock_override != ACTIVE_BLOCK)
                · I(chaos_risk <= chaos_max) · I(data_freshness >= freshness_min)
    G_portfolio = I(leverage_valid) · I(portfolio_capacity_ok)
    G_moltbook  = I(moltbook_block != true)

    FinalAdmission = BaseCandidate · G_safety · G_state · G_portfolio · G_moltbook

Any gate = 0 ⇒ not admitted, with a specific BLOCKED_BY_* advisory class.

The result NEVER carries execution-capable wording.  ``EXECUTABLE_SIGNAL``,
``AUTO_TRADE``, ``PLACE_ORDER``, ``BUY_NOW``, ``SELL_NOW``,
``BROKER_CONNECTED`` are forbidden and asserted-against in the tests.

NOTE (wiring): this is a pure contract.  Integrating it into the live decision
path (chess_archetype_decision_layer / board_control_safety_layer) is a
follow-up — see ``TODO(admission-gates wiring)`` below.  Shipping the contract
+ tests first keeps the change safe and reviewable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

try:
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

# Allowed final advisory classes (none imply execution).
ADVISORY_CANDIDATE = "ADVISORY_CANDIDATE_FOR_HUMAN_REVIEW"
WATCHLIST = "WATCHLIST"
WAIT = "WAIT"
AVOID = "AVOID"
BLOCKED_BY_DIABLO = "BLOCKED_BY_DIABLO"
BLOCKED_BY_FRESHNESS = "BLOCKED_BY_FRESHNESS"
BLOCKED_BY_LEVERAGE_POLICY = "BLOCKED_BY_LEVERAGE_POLICY"
BLOCKED_BY_PORTFOLIO_CAPACITY = "BLOCKED_BY_PORTFOLIO_CAPACITY"
BLOCKED_BY_MOLTBOOK_HISTORY = "BLOCKED_BY_MOLTBOOK_HISTORY"
BLOCKED_BY_SAFETY = "BLOCKED_BY_SAFETY"
BLOCKED_BY_SHOCK = "BLOCKED_BY_SHOCK"
BLOCKED_BY_CHAOS = "BLOCKED_BY_CHAOS"

ALLOWED_ADVISORY_CLASSES: frozenset[str] = frozenset({
    ADVISORY_CANDIDATE, WATCHLIST, WAIT, AVOID,
    BLOCKED_BY_DIABLO, BLOCKED_BY_FRESHNESS, BLOCKED_BY_LEVERAGE_POLICY,
    BLOCKED_BY_PORTFOLIO_CAPACITY, BLOCKED_BY_MOLTBOOK_HISTORY,
    BLOCKED_BY_SAFETY, BLOCKED_BY_SHOCK, BLOCKED_BY_CHAOS,
})

FORBIDDEN_ADVISORY_WORDING: frozenset[str] = frozenset({
    "EXECUTABLE_SIGNAL", "AUTO_TRADE", "PLACE_ORDER",
    "BUY_NOW", "SELL_NOW", "BROKER_CONNECTED",
})

# Defaults — conservative.
DEFAULT_CHAOS_MAX: float = 0.75
DEFAULT_FRESHNESS_MIN: float = 0.30


@dataclass(frozen=True)
class AdmissionGateResult:
    admitted: bool
    advisory_class: str
    blocking_reasons: list[str] = field(default_factory=list)
    gates: dict[str, bool] = field(default_factory=dict)
    stamps: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "admitted": self.admitted,
            "advisory_class": self.advisory_class,
            "blocking_reasons": list(self.blocking_reasons),
            "gates": dict(self.gates),
        }
        out.update(self.stamps)
        out["execution_permission"] = "ADVISORY_ONLY"
        out["human_execution_required"] = True
        return out


def _safety_ok(c: Mapping[str, Any], stamps: Mapping[str, Any]) -> bool:
    return bool(
        stamps.get("execution_gate") == "LOCKED"
        and stamps.get("broker_api_called") is False
        and stamps.get("ai_execution_count") == 0
        and c.get("advisory_only", True) is not False
        and c.get("human_execution_required", True) is not False
    )


def evaluate_admission_gates(
    candidate: Mapping[str, Any],
    *,
    chaos_max: float = DEFAULT_CHAOS_MAX,
    freshness_min: float = DEFAULT_FRESHNESS_MIN,
) -> AdmissionGateResult:
    """Reduce a candidate + risk flags to one admission verdict.

    Recognised candidate fields (all optional, conservative defaults):
      base_candidate(bool), state(str), shock_override(str),
      chaos_risk(float), data_freshness(float), leverage_valid(bool),
      portfolio_capacity_ok(bool), moltbook_block(bool).
    """
    stamps = advisory_safety_stamps()
    reasons: list[str] = []
    gates: dict[str, bool] = {}

    # Safety gate first — non-negotiable.
    g_safety = _safety_ok(candidate, stamps)
    gates["G_safety"] = g_safety
    if not g_safety:
        reasons.append("safety invariants not satisfied")

    # State gate.
    state = str(candidate.get("state") or "").strip().upper()
    shock = str(candidate.get("shock_override") or "").strip().upper()
    chaos_risk = float(candidate.get("chaos_risk") or 0.0)
    freshness = float(candidate.get("data_freshness", 1.0))

    not_diablo = state != "DIABLO"
    not_shock_block = shock != "ACTIVE_BLOCK"
    chaos_ok = chaos_risk <= chaos_max
    fresh_ok = freshness >= freshness_min
    g_state = not_diablo and not_shock_block and chaos_ok and fresh_ok
    gates["G_state"] = g_state

    # Portfolio gate.
    leverage_valid = bool(candidate.get("leverage_valid", True))
    capacity_ok = bool(candidate.get("portfolio_capacity_ok", True))
    g_portfolio = leverage_valid and capacity_ok
    gates["G_portfolio"] = g_portfolio

    # Moltbook gate.
    moltbook_block = bool(candidate.get("moltbook_block", False))
    g_moltbook = not moltbook_block
    gates["G_moltbook"] = g_moltbook

    base_candidate = bool(candidate.get("base_candidate", True))

    # Resolve the most specific blocking class.  Safety dominates.
    if not g_safety:
        return AdmissionGateResult(False, BLOCKED_BY_SAFETY, reasons, gates, stamps)
    if not not_diablo:
        reasons.append("state=DIABLO blocks advisory promotion")
        return AdmissionGateResult(False, BLOCKED_BY_DIABLO, reasons, gates, stamps)
    if not not_shock_block:
        reasons.append("shock_override=ACTIVE_BLOCK")
        return AdmissionGateResult(False, BLOCKED_BY_SHOCK, reasons, gates, stamps)
    if not chaos_ok:
        reasons.append(f"chaos_risk {chaos_risk} > chaos_max {chaos_max}")
        return AdmissionGateResult(False, BLOCKED_BY_CHAOS, reasons, gates, stamps)
    if not fresh_ok:
        reasons.append(f"data_freshness {freshness} < freshness_min {freshness_min}")
        return AdmissionGateResult(False, BLOCKED_BY_FRESHNESS, reasons, gates, stamps)
    if not leverage_valid:
        reasons.append("leverage policy invalid")
        return AdmissionGateResult(False, BLOCKED_BY_LEVERAGE_POLICY, reasons, gates, stamps)
    if not capacity_ok:
        reasons.append("portfolio capacity exhausted")
        return AdmissionGateResult(False, BLOCKED_BY_PORTFOLIO_CAPACITY, reasons, gates, stamps)
    if not g_moltbook:
        reasons.append("moltbook history blocks this pattern")
        return AdmissionGateResult(False, BLOCKED_BY_MOLTBOOK_HISTORY, reasons, gates, stamps)

    if not base_candidate:
        return AdmissionGateResult(False, WAIT, reasons, gates, stamps)

    return AdmissionGateResult(True, ADVISORY_CANDIDATE, reasons, gates, stamps)


# TODO(admission-gates wiring): call evaluate_admission_gates() from
# chess_archetype_decision_layer's final classification so a DIABLO / stale /
# leverage-invalid / capacity-exhausted / moltbook-blocked candidate is forced
# to its BLOCKED_BY_* class.  Deferred to keep this sprint's change reviewable.


__all__ = [
    "ALLOWED_ADVISORY_CLASSES",
    "FORBIDDEN_ADVISORY_WORDING",
    "DEFAULT_CHAOS_MAX",
    "DEFAULT_FRESHNESS_MIN",
    "AdmissionGateResult",
    "evaluate_admission_gates",
    "ADVISORY_CANDIDATE",
    "WATCHLIST",
    "WAIT",
    "AVOID",
    "BLOCKED_BY_DIABLO",
    "BLOCKED_BY_FRESHNESS",
    "BLOCKED_BY_LEVERAGE_POLICY",
    "BLOCKED_BY_PORTFOLIO_CAPACITY",
    "BLOCKED_BY_MOLTBOOK_HISTORY",
]
