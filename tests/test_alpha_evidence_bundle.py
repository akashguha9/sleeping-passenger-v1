"""Evidence bundle: deterministic, auditable, secret-free."""

from __future__ import annotations

import json
import os

from src.alpha import ADVISORY_DISCLAIMER
from src.alpha.evidence_bundle import build_evidence_bundle

_OPPORTUNITY = {
    "opportunity_score": 45.0,
    "confidence": 60.0,
    "calibration_adjusted_confidence": 30.0,
    "advisory_verdict": "deep_research",
    "trap_flags": ["risk_disclosure_overhang"],
    "why_not_higher": ["evidence_gap_risk is elevated (60/100)"],
    "why_not_lower": ["residual_utility is strong (80/100)"],
    "probability_source": "raw_proxy",
    "raw_event_probability": 0.34,
    "calibrated_event_probability": None,
    "evidence_quality_score": 55.0,
}


def _bundle(**overrides):
    kwargs = dict(
        signal_name="test signal",
        input_snapshot={"residual_utility": 80.0},
        opportunity=_OPPORTUNITY,
        autopsy={"summary": "test autopsy", "disclaimer": ADVISORY_DISCLAIMER},
        filing_lineage=[{"category": "order_backlog", "line_number": 1}],
        calibration_summary={"method": "insufficient_data", "calibration_support": 0.0},
        created_at="2026-06-10T00:00:00Z",
    )
    kwargs.update(overrides)
    return build_evidence_bundle(**kwargs)


def test_bundle_includes_disclaimer_calibration_and_autopsy() -> None:
    bundle = _bundle()
    assert bundle["disclaimer"] == ADVISORY_DISCLAIMER
    assert bundle["calibration_summary"]["method"] == "insufficient_data"
    assert bundle["autopsy"]["summary"] == "test autopsy"
    assert bundle["verdict"] == "deep_research"
    assert bundle["trap_flags"] == ["risk_disclosure_overhang"]


def test_bundle_id_deterministic_when_created_at_fixed() -> None:
    assert _bundle()["bundle_id"] == _bundle()["bundle_id"]
    assert _bundle()["bundle_id"].startswith("EB_")
    # Content changes change the ID.
    assert _bundle()["bundle_id"] != _bundle(signal_name="other signal")["bundle_id"]


def test_bundle_json_roundtrip() -> None:
    bundle = _bundle()
    assert json.loads(json.dumps(bundle)) == bundle


def test_missing_sections_reported_not_invented() -> None:
    bundle = build_evidence_bundle(signal_name="bare", created_at="t0")
    for section in (
        "autopsy",
        "calibration_summary",
        "filing_lineage",
        "narrative_lineage",
        "replay_lineage",
    ):
        assert section in bundle["missing_inputs"]
    assert bundle["verdict"] == "unscored"


def test_bundle_contains_no_environment_leakage() -> None:
    os.environ["FAKE_SECRET_FOR_TEST"] = "super-secret-value"
    try:
        text = json.dumps(_bundle())
        assert "super-secret-value" not in text
        assert "FAKE_SECRET_FOR_TEST" not in text
    finally:
        del os.environ["FAKE_SECRET_FOR_TEST"]


def test_no_execution_language() -> None:
    text = json.dumps(_bundle()).lower()
    for forbidden in ("buy now", "guaranteed", "execute trade", "place order"):
        assert forbidden not in text
    assert _bundle()["advisory_only"] is True
