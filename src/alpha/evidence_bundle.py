"""Portable evidence bundle: one auditable artifact per advisory verdict.

Bundles the complete chain of custody for a verdict — input snapshot,
scores, trap flags, filing/prediction-market/narrative/value-chain/replay
lineage, calibration summary, and the autopsy — into a single
JSON-serializable object with a deterministic content-derived ID.

No environment reads, no hidden file access, no secrets: the bundle
contains exactly what the caller passed plus what the scoring modules
computed from it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.alpha import ADVISORY_DISCLAIMER


def _content_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return "EB_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def build_evidence_bundle(
    *,
    signal_name: str,
    input_snapshot: dict[str, Any] | None = None,
    opportunity: dict[str, Any] | None = None,
    autopsy: dict[str, Any] | None = None,
    filing_lineage: list[dict[str, Any]] | None = None,
    prediction_market_lineage: list[dict[str, Any]] | None = None,
    narrative_lineage: list[dict[str, Any]] | None = None,
    value_chain_lineage: list[dict[str, Any]] | None = None,
    replay_lineage: list[dict[str, Any]] | None = None,
    calibration_summary: dict[str, Any] | None = None,
    created_at: str = "",
) -> dict[str, Any]:
    """Assemble the auditable bundle.  Deterministic when ``created_at``
    is fixed: the bundle ID is a hash of the content, not a UUID."""
    opportunity = opportunity or {}
    missing_inputs: list[str] = []
    for label, value in (
        ("opportunity", opportunity),
        ("autopsy", autopsy),
        ("calibration_summary", calibration_summary),
    ):
        if not value:
            missing_inputs.append(label)
    for label, lineage in (
        ("filing_lineage", filing_lineage),
        ("prediction_market_lineage", prediction_market_lineage),
        ("narrative_lineage", narrative_lineage),
        ("value_chain_lineage", value_chain_lineage),
        ("replay_lineage", replay_lineage),
    ):
        if not lineage:
            missing_inputs.append(label)

    body: dict[str, Any] = {
        "created_at": created_at,
        "advisory_only": True,
        "signal_name": signal_name,
        "input_snapshot": dict(input_snapshot or {}),
        "scores": {
            "opportunity_score": opportunity.get("opportunity_score"),
            "confidence": opportunity.get("confidence"),
            "calibration_adjusted_confidence": opportunity.get(
                "calibration_adjusted_confidence"
            ),
            "evidence_quality_score": opportunity.get("evidence_quality_score"),
            "probability_source": opportunity.get("probability_source"),
            "raw_event_probability": opportunity.get("raw_event_probability"),
            "calibrated_event_probability": opportunity.get(
                "calibrated_event_probability"
            ),
        },
        "verdict": opportunity.get("advisory_verdict", "unscored"),
        "trap_flags": list(opportunity.get("trap_flags") or []),
        "why_not_higher": list(opportunity.get("why_not_higher") or []),
        "why_not_lower": list(opportunity.get("why_not_lower") or []),
        "evidence_items": list(filing_lineage or []),
        "filing_lineage": list(filing_lineage or []),
        "prediction_market_lineage": list(prediction_market_lineage or []),
        "narrative_lineage": list(narrative_lineage or []),
        "value_chain_lineage": list(value_chain_lineage or []),
        "replay_lineage": list(replay_lineage or []),
        "calibration_summary": dict(calibration_summary or {}),
        "autopsy": dict(autopsy or {}),
        "missing_inputs": missing_inputs,
        "disclaimer": ADVISORY_DISCLAIMER,
    }
    return {"bundle_id": _content_id(body), **body}
