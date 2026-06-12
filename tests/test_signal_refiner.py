"""Signal refiner proofs: echoes are not evidence.

Clustering, redundancy pricing, conservative feeds into self-feed and
lifecycle, and graceful degradation.
"""

from __future__ import annotations

import copy
import json

import pytest

from src.simulator.pipeline import evaluate_candidate_payload
from src.simulator.signal_refiner import refine_signals
from src.simulator.signal_tyres import score_signal_tyre
from tests.test_simulator_cherry_pick_pipeline import STRONG_PAYLOAD


def _tyre(signal_type: str, raw: float = 70.0, age: float = 4.0):
    return score_signal_tyre(
        signal_type=signal_type, raw_strength=raw, signal_age_hours=age,
        reaction_lag_hours=0.0, source_quality=0.7,
        confirmation_multiplier=1.0, circuit_decay_multiplier=1.0,
        track_condition_score=0.6,
    )


def echo_signals() -> list[dict]:
    return [
        {"signal_type": "social_spike", "raw_strength": 80,
         "signal_age_hours": 4, "source_quality": 0.7},
        {"signal_type": "social_spike", "raw_strength": 75,
         "signal_age_hours": 5, "source_quality": 0.6},
        {"signal_type": "social_spike", "raw_strength": 70,
         "signal_age_hours": 6, "source_quality": 0.6},
    ]


# --- Clustering ----------------------------------------------------------------
def test_same_type_without_origins_is_one_cluster() -> None:
    specs = echo_signals()
    tyres = [_tyre("social_spike", s["raw_strength"]) for s in specs]
    refinement = refine_signals(specs, tyres)
    assert refinement.raw_signal_count == 3
    assert refinement.effective_signal_count == 1
    assert refinement.redundancy_penalty == pytest.approx(2 / 3, abs=1e-3)
    assert "SIGNAL_REDUNDANCY_HIGH" in refinement.reason_codes
    assert any("echoes" in r for r in refinement.rationale)


def test_declared_origins_restore_independence() -> None:
    specs = echo_signals()
    for index, spec in enumerate(specs):
        spec["origin"] = f"venue_{index}"
    tyres = [_tyre("social_spike", s["raw_strength"]) for s in specs]
    refinement = refine_signals(specs, tyres)
    assert refinement.effective_signal_count == 3
    assert refinement.redundancy_penalty == 0.0
    assert refinement.reason_codes == []


def test_distinct_types_are_distinct_evidence_channels() -> None:
    specs = [
        {"signal_type": "backlog", "raw_strength": 85},
        {"signal_type": "earnings_beat", "raw_strength": 75},
    ]
    tyres = [_tyre(s["signal_type"], s["raw_strength"]) for s in specs]
    refinement = refine_signals(specs, tyres)
    assert refinement.effective_signal_count == 2
    assert refinement.redundancy_penalty == 0.0


def test_shared_evidence_basis_collapses_across_types() -> None:
    # Two different signal types citing the same origin are one cluster:
    # circular evidence does not multiply by changing channels.
    specs = [
        {"signal_type": "viral_article", "raw_strength": 70,
         "origin": "blog_post_x"},
        {"signal_type": "social_spike", "raw_strength": 80,
         "origin": "blog_post_x"},
    ]
    tyres = [_tyre(s["signal_type"], s["raw_strength"]) for s in specs]
    refinement = refine_signals(specs, tyres)
    assert refinement.effective_signal_count == 1


def test_redundancy_haircut_math() -> None:
    specs = echo_signals()
    tyres = [_tyre("social_spike", s["raw_strength"]) for s in specs]
    refinement = refine_signals(specs, tyres)
    expected = refinement.strongest_effective_strength * (
        1.0 - 0.4 * refinement.redundancy_penalty
    )
    assert refinement.adjusted_strength == pytest.approx(
        expected, abs=1e-3
    )
    assert refinement.adjusted_strength < (
        refinement.strongest_effective_strength
    )


def test_empty_signals_degrade_gracefully() -> None:
    refinement = refine_signals([], [])
    assert refinement.raw_signal_count == 0
    assert refinement.independence == 1.0
    assert refinement.adjusted_strength == 0.0
    assert json.dumps(refinement.to_dict())


# --- Pipeline integration --------------------------------------------------------
def test_pipeline_stamps_redundancy_and_feeds_self_feed() -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["signals"] = echo_signals()
    out = evaluate_candidate_payload(payload)
    refinement = out["breakdown"]["signal_refinement"]
    assert refinement["effective_signal_count"] == 1
    assert "SIGNAL_REDUNDANCY_HIGH" in out["decision"]["reason_codes"]
    # The refiner's haircut won the conservative merge into self-feed.
    assert out["opponent"]["self_feed"]["provenance"][
        "adaptation.signal_strength"
    ] == "signal_refiner.adjusted_strength"


def test_independent_signals_leave_strong_payload_unchanged() -> None:
    out = evaluate_candidate_payload(copy.deepcopy(STRONG_PAYLOAD))
    refinement = out["breakdown"]["signal_refinement"]
    assert refinement["redundancy_penalty"] == 0.0
    assert (
        "SIGNAL_REDUNDANCY_HIGH" not in out["decision"]["reason_codes"]
    )
    assert out["decision"]["final_state"] == "active_watch"
    # No haircut -> tyre-derived strength keeps its provenance.
    assert out["opponent"]["self_feed"]["provenance"][
        "adaptation.signal_strength"
    ] == "signal_tyres.effective_signal_strength"


def test_echoes_thin_the_lifecycle_live_edge() -> None:
    from tests.test_edge_lifecycle import golden_section

    base = copy.deepcopy(STRONG_PAYLOAD)
    base["lifecycle"] = {k: v for k, v in golden_section().items()
                         if k != "live_edge"}
    echoed = copy.deepcopy(base)
    echoed["signals"] = echo_signals()
    base_edge = evaluate_candidate_payload(base)["lifecycle"]["expiry"][
        "live_edge"
    ]
    echo_edge = evaluate_candidate_payload(echoed)["lifecycle"]["expiry"][
        "live_edge"
    ]
    assert echo_edge < base_edge  # an edge built on echoes is thinner
