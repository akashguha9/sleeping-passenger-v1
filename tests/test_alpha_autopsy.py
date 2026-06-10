"""Alpha autopsy: the system explaining itself to a hostile auditor."""

from __future__ import annotations

from src.alpha.autopsy import build_alpha_autopsy

_REALITY = {
    "narrative_velocity": 30.0,
    "embedded_proof": 80.0,
    "node_strength": 70.0,
    "half_life": 90.0,
    "residual_utility": 85.0,
    "food_chain": 80.0,
    "casino_distortion": 10.0,
}
_HYPE = {
    "narrative_velocity": 95.0,
    "embedded_proof": 20.0,
    "node_strength": 30.0,
    "half_life": 30.0,
    "residual_utility": 25.0,
    "food_chain": 30.0,
    "casino_distortion": 85.0,
}


def test_autopsy_reports_blind_test_survival() -> None:
    autopsy = build_alpha_autopsy(signal_name="plumbing node", components=_REALITY)
    assert autopsy["what_survives_blind_test"]
    assert any("blind score" in item for item in autopsy["what_survives_blind_test"])
    assert "blind test" in autopsy["summary"].lower()


def test_hype_signal_shows_casino_layer_and_inflation() -> None:
    autopsy = build_alpha_autopsy(signal_name="meme theme", components=_HYPE)
    assert autopsy["what_was_only_casino"]
    assert any("casino distortion" in item for item in autopsy["what_was_only_casino"])


def test_missing_proof_is_explicit() -> None:
    autopsy = build_alpha_autopsy(signal_name="x", components=_HYPE)
    assert any("no filing parse" in item for item in autopsy["missing_proof"])


def test_next_evidence_includes_calibration_when_uncalibrated() -> None:
    autopsy = build_alpha_autopsy(
        signal_name="x", components=_REALITY, calibration_support=0.0
    )
    assert any(
        "journal-to-replay" in item for item in autopsy["next_evidence_to_collect"]
    )
    assert "uncalibrated" in autopsy["calibration_state"]


def test_trap_flags_surface_when_present() -> None:
    autopsy = build_alpha_autopsy(
        signal_name="x",
        components=_HYPE,
        opportunity={
            "advisory_verdict": "avoid_trap",
            "trap_flags": ["high_narrative_low_proof"],
            "why_not_higher": ["embedded_proof is weak (20/100)"],
            "missing_inputs": [],
        },
    )
    assert autopsy["trap_flags"] == ["high_narrative_low_proof"]
    assert "avoid_trap" in autopsy["summary"]


def test_filing_lineage_and_negations_flow_into_autopsy() -> None:
    from src.alpha.filing_parser import parse_filing_text

    parsed = parse_filing_text(
        "Order backlog increased to $500m.\n"
        "We do not generate segment revenue from AI.",
        source_type="10-K",
        narrative_claims=["AI growth"],
    )
    autopsy = build_alpha_autopsy(
        signal_name="x", components=_REALITY, filing_parse=parsed
    )
    assert any("order_backlog" in item for item in autopsy["embedded_proof"])
    assert any("explicitly negated" in item for item in autopsy["missing_proof"])


def test_triangulation_weakest_link_drives_next_evidence() -> None:
    autopsy = build_alpha_autopsy(
        signal_name="x",
        components=_REALITY,
        triangulation={
            "triangulation_class": "mixed_evidence",
            "weakest_link": "prediction_market",
            "missing_inputs": ["narrative"],
        },
    )
    assert any(
        "prediction_market" in item for item in autopsy["next_evidence_to_collect"]
    )
    assert any("narrative" in item for item in autopsy["next_evidence_to_collect"])


def test_autopsy_degrades_safely_with_nothing_supplied() -> None:
    autopsy = build_alpha_autopsy(signal_name="bare signal")
    assert autopsy["value_chain_node"] == "unmapped"
    assert autopsy["residual_utility"] == "not assessed"
    assert autopsy["half_life"] == "not assessed"
    assert autopsy["next_evidence_to_collect"]


def test_no_execution_language_in_autopsy() -> None:
    text = str(build_alpha_autopsy(signal_name="x", components=_HYPE)).lower()
    for forbidden in ("buy now", "guaranteed", "execute trade", "place order"):
        assert forbidden not in text
    assert "advisory-only" in text
