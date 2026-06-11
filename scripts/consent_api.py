"""Customer Consent & Regulatory Fragility API surface (pure logic).

Thin advisory wrapper around ``src.consent.revenue_quality`` so the HTTP
layer stays a one-line delegate and the contract is testable without
FastAPI. Every response carries the full advisory safety stamps; this
endpoint classifies business-model risk patterns for journal research —
it never places an order and never asserts legal guilt.
"""

from __future__ import annotations

from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

from src.consent import CONSENT_ADVISORY_NOTE, CONSENT_DOCTRINE
from src.consent.revenue_quality import (
    evaluate_consent_profile,
    to_simulator_risk_factors,
)
from src.utils.time_utils import utc_now_iso

# Bound complaint-text input so a hostile payload cannot blow up matching.
MAX_COMPLAINT_TEXTS = 200
MAX_TEXT_LENGTH = 2000


def _bounded_payload(payload: dict[str, Any]) -> dict[str, Any]:
    bounded = dict(payload)
    texts = bounded.get("complaint_texts")
    if isinstance(texts, list):
        bounded["complaint_texts"] = [
            str(t)[:MAX_TEXT_LENGTH] for t in texts[:MAX_COMPLAINT_TEXTS]
        ]
    return bounded


def evaluate_consent_candidate(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Run one company payload through the full consent engine."""
    if not isinstance(payload, dict):
        payload = {}
    profile = evaluate_consent_profile(_bounded_payload(payload))
    profile["simulator_risk_factors"] = to_simulator_risk_factors(profile)
    profile["generated_at"] = utc_now_iso()
    profile.update(advisory_safety_stamps())
    return profile


def consent_doctrine() -> dict[str, Any]:
    """Static doctrine surface for docs and dashboard."""
    return {
        "doctrine": list(CONSENT_DOCTRINE),
        "advisory_note": CONSENT_ADVISORY_NOTE,
        "limitations": [
            "complaint data can be biased",
            "personal anecdotes are not statistical proof",
            "intent cannot be inferred without evidence",
            "the model detects risk patterns, not legal guilt",
        ],
        "generated_at": utc_now_iso(),
        **advisory_safety_stamps(),
    }
