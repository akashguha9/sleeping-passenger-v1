"""Market-physics simulator API surface (pure logic, no FastAPI import).

Thin advisory wrapper around ``src.simulator.pipeline`` so the HTTP layer
in ``scripts/api_server.py`` stays a one-line delegate and tests can
exercise the contract without the web framework.

Every response carries the full advisory safety stamps: this endpoint
scores and explains — it never places, sizes, or routes an order.
"""

from __future__ import annotations

from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

from src.simulator import ADVISORY_NOTE, DOCTRINE
from src.simulator.circuit_classifier import CIRCUIT_PROFILES
from src.simulator.pipeline import evaluate_candidate_payload
from src.simulator.signal_tyres import (
    BASE_HALF_LIFE_HOURS,
    SIGNAL_TYPE_COMPOUNDS,
)
from src.utils.time_utils import utc_now_iso

# Bound list inputs so a hostile payload cannot explode the combinatorics
# or response size.
MAX_SIGNALS = 50
MAX_RISK_FACTORS = 25


def _bounded_payload(payload: dict[str, Any]) -> dict[str, Any]:
    bounded = dict(payload)
    signals = bounded.get("signals")
    if isinstance(signals, list) and len(signals) > MAX_SIGNALS:
        bounded["signals"] = signals[:MAX_SIGNALS]
    risks = bounded.get("risk_factors")
    if isinstance(risks, dict) and len(risks) > MAX_RISK_FACTORS:
        bounded["risk_factors"] = dict(list(risks.items())[:MAX_RISK_FACTORS])
    return bounded


def evaluate_simulator_candidate(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Run one candidate through the full simulator chain. ADVISORY_ONLY."""
    if not isinstance(payload, dict):
        payload = {}
    result = evaluate_candidate_payload(_bounded_payload(payload))
    result.update(advisory_safety_stamps())
    result["generated_at"] = utc_now_iso()
    return result


def evaluate_and_record_candidate(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Evaluate one candidate AND persist the verdict for hysteresis memory.

    When the caller does not supply ``previous_state``, the most recent
    persisted ladder state for the same ticker/theme is used, so promotion
    hysteresis survives across sessions. Recording is local SQLite,
    read-only with respect to markets, ADVISORY_ONLY throughout.
    """
    try:
        from scripts import simulator_store
    except ModuleNotFoundError:  # pragma: no cover
        import simulator_store  # type: ignore[no-redef]

    if not isinstance(payload, dict):
        payload = {}
    enriched = dict(payload)
    previous_state_used = enriched.get("previous_state")
    if not previous_state_used:
        stored = simulator_store.get_previous_state(
            str(enriched.get("ticker", "UNKNOWN")),
            str(enriched.get("theme", "")),
        )
        if stored:
            enriched["previous_state"] = stored
            previous_state_used = stored

    result = evaluate_simulator_candidate(enriched)
    evaluation_id = simulator_store.record_evaluation(result)
    result["evaluation_id"] = evaluation_id
    result["previous_state_used"] = previous_state_used
    result["recorded"] = True
    return result


def simulator_history(
    ticker: str | None = None, limit: int = 50
) -> dict[str, Any]:
    """Read-only persisted evaluation history."""
    try:
        from scripts import simulator_store
    except ModuleNotFoundError:  # pragma: no cover
        import simulator_store  # type: ignore[no-redef]

    items = simulator_store.get_history(ticker=ticker, limit=limit)
    return {
        "items": items,
        "count": len(items),
        "generated_at": utc_now_iso(),
        **advisory_safety_stamps(),
    }


def simulator_calibration_report() -> dict[str, Any]:
    """Calibration report over persisted simulator telemetry.

    Honest by construction: with no resolved outcomes this reports
    ``insufficient_data``; with fixture rows it reports ``fixture_replay``;
    only genuinely resolved caller decisions can ever read ``empirical``.
    Recommendations are never auto-applied.
    """
    try:
        from scripts import simulator_store
    except ModuleNotFoundError:  # pragma: no cover
        import simulator_store  # type: ignore[no-redef]

    from src.simulator.calibration_bridge import build_calibration_report

    rows = simulator_store.load_all_telemetry()
    report = build_calibration_report(rows).to_dict()
    report["generated_at"] = utc_now_iso()
    report.update(advisory_safety_stamps())
    return report


def simulator_doctrine() -> dict[str, Any]:
    """Static doctrine + model surface for the dashboard and docs."""
    return {
        "doctrine": list(DOCTRINE),
        "advisory_note": ADVISORY_NOTE,
        "signal_compound_half_lives_hours": dict(BASE_HALF_LIFE_HOURS),
        "signal_type_compounds": dict(SIGNAL_TYPE_COMPOUNDS),
        "circuits": {
            name: profile.to_dict() for name, profile in CIRCUIT_PROFILES.items()
        },
        "generated_at": utc_now_iso(),
        **advisory_safety_stamps(),
    }
