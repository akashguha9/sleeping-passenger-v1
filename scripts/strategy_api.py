"""Strategy-engine API surface (pure logic, no FastAPI import).

Thin advisory wrapper around ``src.strategy.final_decision`` following the
repo's established pattern (simulator_api/consent_api). Every response
carries the full advisory safety stamps: verdict labels are research
classifications, never instructions; there is no execution path.
"""

from __future__ import annotations

from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

from src.strategy import STRATEGY_ADVISORY_NOTE, STRATEGY_DOCTRINE
from src.strategy.final_decision import (
    DECISION_CLASSES,
    evaluate_strategy_payload,
)
from src.strategy.predator_nodes import NODE_SIGNATURES
from src.utils.time_utils import utc_now_iso

MAX_BEAR_ATTACKS = 50
MAX_METRICS = 50


def _bounded_payload(payload: dict[str, Any]) -> dict[str, Any]:
    bounded = dict(payload)
    backhand = bounded.get("backhand")
    if isinstance(backhand, dict):
        attacks = backhand.get("bear_attacks")
        if isinstance(attacks, list) and len(attacks) > MAX_BEAR_ATTACKS:
            bounded["backhand"] = {
                **backhand, "bear_attacks": attacks[:MAX_BEAR_ATTACKS],
            }
    distribution = bounded.get("distribution")
    if isinstance(distribution, dict):
        metrics = distribution.get("metrics")
        if isinstance(metrics, dict) and len(metrics) > MAX_METRICS:
            bounded["distribution"] = {
                **distribution,
                "metrics": dict(list(metrics.items())[:MAX_METRICS]),
            }
    return bounded


def evaluate_strategy_candidate(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Run one candidate through the strategy chain. ADVISORY_ONLY."""
    if not isinstance(payload, dict):
        payload = {}
    result = evaluate_strategy_payload(_bounded_payload(payload))
    result["generated_at"] = utc_now_iso()
    result.update(advisory_safety_stamps())
    return result


def strategy_doctrine() -> dict[str, Any]:
    """Static doctrine + node taxonomy surface."""
    return {
        "doctrine": list(STRATEGY_DOCTRINE),
        "advisory_note": STRATEGY_ADVISORY_NOTE,
        "decision_classes": list(DECISION_CLASSES),
        "predator_nodes": {
            name: {"role": sig["role"], "risks": sig["risks"]}
            for name, sig in NODE_SIGNATURES.items()
        },
        "generated_at": utc_now_iso(),
        **advisory_safety_stamps(),
    }
