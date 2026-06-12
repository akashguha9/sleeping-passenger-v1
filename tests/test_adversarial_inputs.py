"""Adversarial input proofs: garbage degrades conservatively, never
optimistically and never with a crash.

Two attack classes found by the forensic audit:

1. **NaN poisoning** — Python's JSON parser accepts NaN/Infinity, and
   NaN defeats comparisons: the naive clamp ``max(lo, min(hi, x))``
   resolves NaN to the OPTIMISTIC bound, so ``"source_quality": NaN``
   used to score as a perfect 1.0 and walk past every
   conservative-wins gate. Non-finite values now coerce to the
   conservative default at the single choke point every engine funnels
   through.

2. **Section-type confusion** — a string or list where a dict belongs
   used to raise AttributeError mid-pipeline (a 500 at the API).
   Sections now degrade to "absent" (conservative) via section_dict.
"""

from __future__ import annotations

import copy
import json
import math

import pytest

from src.simulator.pipeline import evaluate_candidate_payload
from src.utils.math_utils import clamp01, clip
from src.utils.validation_utils import (
    coerce_float,
    normalized_score,
    section_dict,
)
from tests.test_simulator_cherry_pick_pipeline import STRONG_PAYLOAD

NAN = float("nan")
INF = float("inf")


# --- Helper hardening (the choke point) -----------------------------------------
def test_non_finite_values_coerce_to_the_default() -> None:
    assert coerce_float(NAN) == 0.0
    assert coerce_float(INF) == 0.0
    assert coerce_float(-INF) == 0.0
    assert coerce_float(NAN, default=0.5) == 0.5
    assert coerce_float("garbage", default=0.25) == 0.25
    assert coerce_float(0.7) == 0.7  # finite values untouched


def test_nan_clamps_to_the_conservative_bound() -> None:
    # NaN is unequal to itself and defeats comparisons; it must land on
    # the MINIMUM, never the maximum.
    assert clip(NAN, 0.0, 1.0) == 0.0
    assert clip(NAN, -1.0, 1.0) == -1.0
    assert clamp01(NAN) == 0.0
    assert normalized_score(NAN) == 0.0
    assert normalized_score(NAN, default=0.5) == 0.5


def test_section_dict_rejects_non_dicts() -> None:
    assert section_dict({"a": 1}) == {"a": 1}
    for junk in ("a string", ["a", "list"], 42, None, 3.14, True):
        assert section_dict(junk) == {}


# --- NaN poisoning end-to-end -----------------------------------------------------
def test_nan_poisoned_payload_cannot_outscore_its_honest_zero() -> None:
    # The attack: replace strong positive inputs with NaN, hoping the
    # clamp resolves them to 1.0. The defense: NaN == missing, so the
    # poisoned payload must score exactly like the payload with those
    # fields absent — and strictly below the honest original.
    poisoned = copy.deepcopy(STRONG_PAYLOAD)
    poisoned["opportunity_quality"] = NAN
    poisoned["hard_evidence_score"] = NAN
    poisoned["narrative"]["source_quality"] = NAN
    poisoned["signals"][0]["raw_strength"] = NAN

    absent = copy.deepcopy(STRONG_PAYLOAD)
    for key in ("opportunity_quality", "hard_evidence_score"):
        absent.pop(key)
    absent["narrative"].pop("source_quality")
    absent["signals"][0].pop("raw_strength")

    honest = evaluate_candidate_payload(copy.deepcopy(STRONG_PAYLOAD))
    poisoned_out = evaluate_candidate_payload(poisoned)
    absent_out = evaluate_candidate_payload(absent)

    assert poisoned_out["decision"]["final_candidate_score"] == (
        absent_out["decision"]["final_candidate_score"]
    )
    assert poisoned_out["decision"]["final_candidate_score"] < (
        honest["decision"]["final_candidate_score"]
    )


def test_infinity_in_adverse_fields_cannot_zero_out_risk() -> None:
    # Infinity in crowding coerces to the default (absent), not to a
    # blown-up value — and the output stays legal JSON either way.
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["theme_assessment"]["crowding"] = INF
    payload["risk_factors"]["high_valuation"] = NAN
    out = evaluate_candidate_payload(payload)
    json.dumps(out, allow_nan=False)  # raises if NaN/Inf leaked through
    score = out["decision"]["final_candidate_score"]
    assert math.isfinite(score)


def test_nan_never_reaches_the_serialized_output() -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["opportunity_quality"] = NAN
    payload["aero"]["noise_level"] = INF
    payload["lifecycle"] = {"live_edge": NAN, "threshold": NAN}
    out = evaluate_candidate_payload(payload)
    json.dumps(out, allow_nan=False)


# --- Section-type confusion end-to-end ----------------------------------------------
@pytest.mark.parametrize("section", [
    "narrative", "theme_assessment", "exposure", "circuit", "inflection",
    "aero", "risk_factors", "triple_blind", "meal_box", "driver",
    "prediction_market", "games", "opponent", "lifecycle", "strategy",
    "bayes", "consent_inputs",
])
@pytest.mark.parametrize("junk", ["a string", ["a", "list"], 42])
def test_any_section_replaced_with_junk_still_evaluates(
    section: str, junk: object,
) -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload[section] = junk
    out = evaluate_candidate_payload(payload)  # must not raise
    assert out["decision"]["final_state"]
    assert out["advisory_note"]


def test_signals_replaced_with_junk_degrades_to_no_signals() -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["signals"] = "not a list"
    out = evaluate_candidate_payload(payload)
    assert out["breakdown"]["tyres"] == []
    # Conservative direction: junk signals score no better than none.
    assert out["decision"]["final_state"]


def test_junk_subsections_inside_opponent_and_lifecycle() -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["opponent"] = {
        "strengths": "junk", "weaknesses": 7, "niche": ["x"],
        "adaptation": "junk", "capabilities": None,
        "catalyst_plus_one": "junk",
    }
    payload["lifecycle"] = {
        "capacity": "junk", "path": 9, "arbitrage": ["y"],
        "hedge": "junk", "live_edge": 0.5,
    }
    out = evaluate_candidate_payload(payload)  # must not raise
    assert out["opponent"] is not None
    assert out["lifecycle"] is not None


def test_empty_payload_still_dies_conservatively_not_loudly() -> None:
    out = evaluate_candidate_payload({})
    assert out["decision"]["final_state"] in ("reject", "archive",
                                              "watchlist")


def test_extreme_magnitudes_stay_bounded() -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["opportunity_quality"] = 1e300
    payload["signals"][0]["raw_strength"] = -1e300
    payload["theme_assessment"]["valuation_heat"] = -5.0
    out = evaluate_candidate_payload(payload)
    score = out["decision"]["final_candidate_score"]
    assert math.isfinite(score)
    assert 0.0 <= score <= 100.0
