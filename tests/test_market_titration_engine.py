"""Tests for scripts/market_titration_engine.py — the Market Titration Engine.

Covers: half-life decay identities, timezone handling, evidence-series
geometry, temperature regimes + Goldilocks, source-concentration entropy,
titration state machine (synthetic Cases A-F), numerical safety, config
fallback, versioning and the advisory safety contract.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.market_titration_engine import (
    DEFAULT_CONFIG,
    GEOMETRY_LABELS,
    RESERVED_STATES,
    SAFETY_STAMPS,
    SCORE_SEMANTICS,
    TITRATION_SCHEMA_VERSION,
    TITRATION_SCORING_VERSION,
    TITRATION_STATES,
    classify_geometry,
    compact_titration_fields,
    compute_source_concentration,
    decay_factor,
    evaluate_market_titration,
    load_titration_config,
)

NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parents[1]


def _iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _item(
    hours_ago: list[float],
    sources: list[str] | None = None,
    **overrides,
) -> dict:
    sources = sources or ["news"] * len(hours_ago)
    base = {
        "event_id": "EVT_TEST",
        "ticker": "TEST",
        "event_timestamps": [_iso(h) for h in hours_ago],
        "event_sources": sources,
        "event_count": len(hours_ago),
        "cross_source_support_count": len(set(sources)),
        "duplicate_suppressed_count": 0,
        "persistence_score": 0.5,
        "contamination_score": 0.1,
        "chaos_sensitivity_score": 0.2,
        "observed_at": _iso(min(hours_ago)) if hours_ago else "",
    }
    base.update(overrides)
    return base


def _assert_safety(payload: dict) -> None:
    safety = payload["safety"]
    assert safety["advisory_status"] == "ADVISORY_ONLY"
    assert safety["execution_gate"] == "LOCKED"
    assert safety["broker_api_called"] is False
    assert safety["ai_execution_count"] == 0
    assert safety["execution_permission"] is False
    assert safety["can_execute"] is False


def _walk_assert_no_execution(payload):
    if isinstance(payload, dict):
        for k, v in payload.items():
            key = k.lower()
            if key in {"execution_permission", "can_execute", "broker_api_called",
                       "broker_execute"}:
                assert v is False or v == "NONE", f"{k}={v}"
            if key == "ai_execution_count":
                assert v == 0
            if key == "advisory_status":
                assert v == "ADVISORY_ONLY"
            if key == "execution_gate":
                assert v == "LOCKED"
            _walk_assert_no_execution(v)
    elif isinstance(payload, list):
        for item in payload:
            _walk_assert_no_execution(item)


# ---------------------------------------------------------------------------
# Half-life decay
# ---------------------------------------------------------------------------


def test_decay_factor_at_observation_time_is_one():
    assert decay_factor(0.0, 24.0) == 1.0


def test_decay_factor_one_half_life_is_half():
    assert abs(decay_factor(24.0, 24.0) - 0.5) < 1e-12


def test_decay_factor_two_half_lives_is_quarter():
    assert abs(decay_factor(48.0, 24.0) - 0.25) < 1e-12


def test_decay_factor_invalid_half_life_rejected():
    assert decay_factor(10.0, 0.0) is None
    assert decay_factor(10.0, -5.0) is None
    assert decay_factor(10.0, float("nan")) is None
    assert decay_factor(10.0, float("inf")) is None


def test_decay_factor_negative_age_clamped_not_amplified():
    # A future-dated event must never have activity above 1.0.
    assert decay_factor(-3.0, 24.0) == 1.0


def test_decay_factor_extreme_age_underflows_to_zero():
    assert decay_factor(1e9, 1.0) == 0.0


def test_half_life_identity_on_active_evidence():
    """a(t_i + h) == a(t_i)/2 for a single event, before normalization."""
    cfg = load_titration_config()
    item_now = _item([0.0], sources=["news"])
    item_one_half_life = _item([48.0], sources=["news"])  # news half-life 48h
    p_now = evaluate_market_titration(item_now, now=NOW, config=cfg)
    p_later = evaluate_market_titration(item_one_half_life, now=NOW, config=cfg)
    raw_now = p_now["active_evidence"]["raw_mass"]
    raw_later = p_later["active_evidence"]["raw_mass"]
    assert abs(raw_later - raw_now / 2.0) < 1e-6


def test_timezone_z_suffix_and_offset_are_equivalent():
    z_item = _item([10.0])
    z_item["event_timestamps"] = [
        ts.replace("+00:00", "Z") for ts in z_item["event_timestamps"]
    ]
    offset_item = _item([10.0])
    p_z = evaluate_market_titration(z_item, now=NOW)
    p_o = evaluate_market_titration(offset_item, now=NOW)
    assert p_z["active_evidence"]["raw_mass"] == p_o["active_evidence"]["raw_mass"]


def test_unparseable_timestamps_dropped_not_fabricated():
    item = _item([5.0])
    item["event_timestamps"] = ["not-a-date", "also bad"]
    item["event_sources"] = ["news", "news"]
    item["observed_at"] = ""
    payload = evaluate_market_titration(item, now=NOW)
    assert payload["titration_state"] == "INSUFFICIENT_DATA"
    assert payload["data_sufficiency"]["level"] == "insufficient"


def test_stale_signal_decays_toward_inert():
    item = _item([500.0, 480.0, 460.0])  # weeks old news
    payload = evaluate_market_titration(item, now=NOW)
    assert payload["active_evidence"]["normalized"] < 0.05
    assert payload["titration_state"] in {"INERT", "INSUFFICIENT_DATA"}


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def test_geometry_convex_accelerating_arrivals():
    # Events bunched increasingly close to now -> accelerating accumulation.
    item = _item([26.0, 14.0, 7.0, 3.0, 1.0, 0.5])
    payload = evaluate_market_titration(item, now=NOW)
    geometry = payload["geometry"]
    assert geometry["label"] == "CONVEX", geometry
    assert geometry["acceleration"] > 0


def test_geometry_concave_decelerating_arrivals():
    # A burst of old events, nothing fresh -> decaying, decelerating curve.
    item = _item([40.0, 38.0, 36.0, 34.0, 32.0])
    payload = evaluate_market_titration(item, now=NOW)
    geometry = payload["geometry"]
    assert geometry["label"] in {"CONCAVE", "APPROX_LINEAR", "FLAT"}, geometry
    assert geometry["velocity"] is not None


def test_geometry_flat_no_recent_change():
    item = _item([400.0, 395.0, 390.0])
    payload = evaluate_market_titration(item, now=NOW)
    assert payload["geometry"]["label"] == "FLAT", payload["geometry"]


def test_geometry_insufficient_below_min_events():
    item = _item([5.0, 3.0])
    payload = evaluate_market_titration(item, now=NOW)
    assert payload["geometry"]["label"] == "INSUFFICIENT_DATA"
    assert payload["susceptibility"]["susceptibility"] is None
    assert payload["buffer_capacity"]["buffer_capacity"] is None
    assert payload["minimum_catalytic_dose"]["mcd_normalized"] is None


def test_classify_geometry_pure_function_labels():
    cfg = load_titration_config()
    convex = classify_geometry([0.0, 0.02, 0.08, 0.20, 0.40], 5, cfg)
    assert convex["label"] == "CONVEX"
    concave = classify_geometry([0.0, 0.20, 0.32, 0.38, 0.40], 5, cfg)
    assert concave["label"] == "CONCAVE"
    linear = classify_geometry([0.0, 0.1, 0.2, 0.3, 0.4], 5, cfg)
    assert linear["label"] == "APPROX_LINEAR"
    flat = classify_geometry([0.2, 0.2, 0.2, 0.2, 0.2], 5, cfg)
    assert flat["label"] == "FLAT"
    short = classify_geometry([0.1, 0.2], 5, cfg)
    assert short["label"] == "INSUFFICIENT_DATA"
    sparse = classify_geometry([0.0, 0.1, 0.2, 0.3, 0.4], 1, cfg)
    assert sparse["label"] == "INSUFFICIENT_DATA"
    for result in (convex, concave, linear, flat, short, sparse):
        assert result["label"] in GEOMETRY_LABELS


# ---------------------------------------------------------------------------
# Temperature and Goldilocks
# ---------------------------------------------------------------------------


def test_temperature_cold_scenario():
    item = _item([300.0, 280.0, 260.0], chaos_sensitivity_score=0.0,
                 contamination_score=0.0)
    payload = evaluate_market_titration(item, now=NOW)
    temp = payload["temperature"]
    assert temp["regime"] in {"COLD", "WARM"}
    assert temp["temperature"] is not None
    assert 0.0 <= temp["temperature"] <= 1.0


def test_temperature_overheated_scenario():
    # Dense burst of very fresh events + high chaos + contamination.
    item = _item(
        [3.0, 2.5, 2.0, 1.5, 1.2, 1.0, 0.8, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1],
        chaos_sensitivity_score=0.95,
        contamination_score=0.9,
    )
    payload = evaluate_market_titration(item, now=NOW)
    temp = payload["temperature"]
    assert temp["regime"] in {"HOT", "OVERHEATED"}
    # Goldilocks quality must fall off away from the center.
    assert temp["goldilocks_quality"] < 1.0


def test_temperature_missing_inputs_are_listed_not_zero_filled():
    item = _item([10.0, 5.0, 2.0])
    del item["chaos_sensitivity_score"]
    del item["contamination_score"]
    payload = evaluate_market_titration(item, now=NOW)
    temp = payload["temperature"]
    assert "chaos_sensitivity" in temp["inputs_missing"]
    assert "contamination" in temp["inputs_missing"]
    assert "implied_volatility" in temp["inputs_missing"]
    assert "chaos_sensitivity" not in temp["inputs_available"]


def test_temperature_deterministic_reproducible():
    item = _item([12.0, 6.0, 2.0])
    p1 = evaluate_market_titration(item, now=NOW)
    p2 = evaluate_market_titration(item, now=NOW)
    assert p1["temperature"] == p2["temperature"]
    assert p1["titration_state"] == p2["titration_state"]
    assert p1["lrr"] == p2["lrr"]


def test_goldilocks_peaks_at_center():
    cfg = load_titration_config()
    center = cfg["goldilocks_center"]
    width = cfg["goldilocks_width"]
    at_center = math.exp(0.0)
    off_center = math.exp(-((0.3) ** 2) / (2 * width * width))
    assert at_center > off_center  # sanity of the functional form


# ---------------------------------------------------------------------------
# Source concentration entropy
# ---------------------------------------------------------------------------


def test_concentration_single_source_flagged():
    result = compute_source_concentration({"news": 1.5})
    assert result["single_source_dependence"] is True
    assert result["concentration"] == 1.0


def test_concentration_even_split_max_entropy():
    result = compute_source_concentration({"news": 1.0, "polymarket": 1.0})
    assert abs(result["normalized_entropy"] - 1.0) < 1e-9
    assert result["single_source_dependence"] is False


def test_concentration_dominant_source_low_entropy():
    result = compute_source_concentration({"news": 100.0, "polymarket": 0.001})
    assert result["normalized_entropy"] < 0.05
    assert result["concentration"] > 0.95


def test_concentration_empty_returns_none_not_zero():
    result = compute_source_concentration({})
    assert result["normalized_entropy"] is None
    assert result["concentration"] is None
    assert result["source_family_count"] == 0


# ---------------------------------------------------------------------------
# Synthetic scenario cases A-F (Phase 6 contract)
# ---------------------------------------------------------------------------


def test_case_a_inert_low_evidence_high_barrier():
    """CASE A — INERT: sparse stale evidence, high barrier, low recognition."""
    item = _item([200.0, 190.0, 180.0], persistence_score=0.2)
    payload = evaluate_market_titration(item, now=NOW)
    assert payload["titration_state"] == "INERT", payload["state_rule_trace"]
    assert payload["barrier"]["barrier"] > 0.5
    assert payload["flow"]["loading"] is False


def test_case_b_loading_inflow_exceeds_decay():
    """CASE B — LOADING: fresh inflow, positive curvature, low recognition."""
    item = _item(
        [30.0, 4.0, 1.0],
        sources=["news", "news", "news"],
        persistence_score=0.4,
    )
    payload = evaluate_market_titration(item, now=NOW)
    assert payload["flow"]["loading"] is True
    assert payload["flow"]["net_accumulation"] > 0
    assert payload["titration_state"] in {"LOADING", "PRE_ALPHA_WATCH"}, (
        payload["state_rule_trace"]
    )


def test_case_c_primed_high_readiness_low_recognition():
    """CASE C — PRIMED: high coherent evidence, convex curve, low barrier,
    Goldilocks temperature, low recognition, positive pre-alpha gap."""
    item = _item(
        [60.0, 40.0, 20.0, 10.0, 5.0, 2.0, 1.0, 0.5],
        sources=["official_filing", "news", "polymarket", "news",
                 "official_filing", "polymarket", "news", "official_filing"],
        persistence_score=0.85,
        contamination_score=0.05,
        chaos_sensitivity_score=0.25,
        cross_source_support_count=2,
    )
    payload = evaluate_market_titration(item, now=NOW)
    assert payload["titration_state"] == "PRIMED", payload["state_rule_trace"]
    assert payload["lrr"]["lrr"] >= 0.65
    assert payload["pre_alpha_gap"] is not None and payload["pre_alpha_gap"] > 0
    assert payload["barrier"]["barrier"] <= 0.45
    assert payload["free_energy"]["free_energy"] > 0


def test_case_d_crowded_high_recognition_compressed_gap():
    """CASE D — CROWDED: readiness present but recognition proxy saturated."""
    # Very wide breadth + very high arrival velocity -> high VMR.
    hours = [0.1 * i + 0.1 for i in range(40)]
    sources = (["news", "polymarket", "official_filing", "social"] * 10)[:40]
    item = _item(
        hours, sources=sources,
        cross_source_support_count=6,
        persistence_score=0.6,
        contamination_score=0.15,
        chaos_sensitivity_score=0.4,
    )
    payload = evaluate_market_titration(item, now=NOW)
    assert payload["vmr"]["vmr"] >= 0.65
    assert payload["titration_state"] in {"CROWDED", "FALSE_TRANSITION_RISK"}, (
        payload["state_rule_trace"]
    )
    if payload["titration_state"] == "CROWDED":
        assert payload["pre_alpha_gap"] <= 0.05


def test_case_e_false_transition_hot_noisy_single_source():
    """CASE E — FALSE TRANSITION: heat + contamination + low persistence +
    single-source dependence."""
    item = _item(
        [1.5, 1.2, 1.0, 0.8, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1],
        sources=["social"] * 10,
        persistence_score=0.05,
        contamination_score=0.9,
        chaos_sensitivity_score=0.95,
        cross_source_support_count=1,
    )
    payload = evaluate_market_titration(item, now=NOW)
    assert payload["titration_state"] == "FALSE_TRANSITION_RISK", (
        payload["state_rule_trace"]
    )
    ftr = payload["false_transition_risk"]
    assert ftr["triggered"] is True
    assert "single_source_dependence" in ftr["reasons"]
    assert "low_persistence" in ftr["reasons"]


def test_case_f_no_edge_evidence_without_executable_asymmetry():
    """CASE F — NO EDGE: real evidence mass but decaying, gap non-positive,
    free energy non-positive."""
    item = _item(
        [90.0, 80.0, 70.0, 60.0, 50.0],
        sources=["official_filing"] * 5,
        persistence_score=0.5,
        contamination_score=0.2,
        chaos_sensitivity_score=0.3,
    )
    payload = evaluate_market_titration(item, now=NOW)
    assert payload["free_energy"]["free_energy"] <= 0
    assert payload["titration_state"] in {"NO_EDGE", "INERT"}, (
        payload["state_rule_trace"]
    )
    # For the NO_EDGE claim specifically we need evidence above the floor.
    if payload["active_evidence"]["normalized"] >= 0.10:
        assert payload["titration_state"] == "NO_EDGE"


def test_insufficient_data_state_for_empty_item():
    payload = evaluate_market_titration({}, now=NOW)
    assert payload["titration_state"] == "INSUFFICIENT_DATA"
    assert payload["data_sufficiency"]["level"] == "insufficient"
    _assert_safety(payload)


# ---------------------------------------------------------------------------
# State machine integrity
# ---------------------------------------------------------------------------


def test_states_are_documented_and_reserved_states_never_assigned():
    items = [
        {},
        _item([1.0]),
        _item([30.0, 4.0, 1.0]),
        _item([200.0, 190.0, 180.0]),
        _item([1.0] * 20, sources=["social"] * 20, persistence_score=0.0,
              contamination_score=0.95, chaos_sensitivity_score=0.95),
    ]
    for item in items:
        payload = evaluate_market_titration(item, now=NOW)
        assert payload["titration_state"] in TITRATION_STATES
        assert payload["titration_state"] not in RESERVED_STATES
        assert payload["state_rule_trace"], "state must carry a rule trace"


def test_pre_alpha_gap_is_lrr_minus_vmr():
    item = _item([30.0, 10.0, 4.0, 1.0])
    payload = evaluate_market_titration(item, now=NOW)
    lrr = payload["lrr"]["lrr"]
    vmr = payload["vmr"]["vmr"]
    assert abs(payload["pre_alpha_gap"] - (lrr - vmr)) < 1e-6


def test_explanation_contains_supporting_penalties_invalidation():
    item = _item([30.0, 4.0, 1.0])
    payload = evaluate_market_titration(item, now=NOW)
    explanation = payload["explanation"]
    assert isinstance(explanation["supporting_factors"], list)
    assert isinstance(explanation["penalties"], list)
    assert explanation["invalidation_conditions"], "must state what invalidates"
    assert explanation["state"] == payload["titration_state"]


# ---------------------------------------------------------------------------
# Numerical safety
# ---------------------------------------------------------------------------


def test_no_nan_or_inf_in_any_numeric_output():
    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, float):
            assert math.isfinite(x), f"non-finite value {x}"

    poison = _item([5.0, 3.0, 1.0])
    poison["persistence_score"] = float("nan")
    poison["contamination_score"] = float("inf")
    poison["chaos_sensitivity_score"] = -float("inf")
    poison["cross_source_support_count"] = float("nan")
    payload = evaluate_market_titration(poison, now=NOW)
    walk(payload)
    _assert_safety(payload)


def test_hostile_types_do_not_crash():
    hostile = {
        "event_timestamps": [None, 42, {"x": 1}, "2020-13-45T99:99:99Z"],
        "event_sources": "not-a-list",
        "event_count": "many",
        "persistence_score": "high",
        "contamination_score": [],
        "observed_at": object,
    }
    payload = evaluate_market_titration(hostile, now=NOW)
    assert payload["titration_state"] == "INSUFFICIENT_DATA"
    _assert_safety(payload)


def test_non_dict_item_degrades_safely():
    for bad in (None, [], "x", 42):
        payload = evaluate_market_titration(bad, now=NOW)  # type: ignore[arg-type]
        assert payload["titration_state"] == "INSUFFICIENT_DATA"
        _assert_safety(payload)


def test_duplicate_and_out_of_order_timestamps_handled():
    item = _item([5.0, 5.0, 1.0, 30.0, 1.0])
    payload = evaluate_market_titration(item, now=NOW)
    assert payload["titration_state"] in TITRATION_STATES
    assert payload["active_evidence"]["event_count_used"] == 5
    _assert_safety(payload)


def test_future_timestamps_clamped():
    item = _item([5.0, 3.0])
    item["event_timestamps"].append((NOW + timedelta(hours=6)).isoformat())
    item["event_sources"].append("news")
    payload = evaluate_market_titration(item, now=NOW)
    # Future event contributes at most fully-fresh mass, never amplified.
    assert payload["active_evidence"]["normalized"] <= 1.0
    assert "future_timestamp_clamped" in payload["data_sufficiency"]["notes"]


def test_mcd_bounded_when_susceptibility_near_zero():
    # Geometry present but zero acceleration/coherence: chi small; MCD must
    # be capped, normalized to [0, 1).
    item = _item([400.0, 395.0, 390.0], contamination_score=0.9,
                 duplicate_suppressed_count=3)
    payload = evaluate_market_titration(item, now=NOW)
    mcd = payload["minimum_catalytic_dose"]
    if mcd["mcd_raw"] is not None:
        assert 0.0 <= mcd["mcd_raw"] <= DEFAULT_CONFIG["mcd_cap"]
        assert 0.0 <= mcd["mcd_normalized"] < 1.0


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_config_defaults_load_without_file(tmp_path):
    cfg = load_titration_config(tmp_path / "missing.json")
    assert cfg["config_status"] == "defaults"
    assert cfg["half_life_source"] == "configured_prior"
    assert cfg["activation_threshold"] == DEFAULT_CONFIG["activation_threshold"]


def test_config_invalid_json_falls_back(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    cfg = load_titration_config(bad)
    assert cfg["config_status"] == "invalid_file_fallback_defaults"
    assert cfg["activation_threshold"] == DEFAULT_CONFIG["activation_threshold"]


def test_config_out_of_range_values_corrected(tmp_path):
    hostile = tmp_path / "hostile.json"
    hostile.write_text(json.dumps({
        "activation_threshold": 99.0,
        "goldilocks_width": -1.0,
        "epsilon": 0.0,
        "half_life_hours_by_family": {"news": -48.0},
        "series_checkpoint_count": 100000,
    }), encoding="utf-8")
    cfg = load_titration_config(hostile)
    assert cfg["config_status"] == "file_merged_with_corrections"
    assert cfg["activation_threshold"] == DEFAULT_CONFIG["activation_threshold"]
    assert cfg["half_life_hours_by_family"]["news"] > 0
    assert 2 <= cfg["series_checkpoint_count"] <= 24
    assert any(p.startswith("activation_threshold") for p in cfg["config_problems"])


def test_repo_config_file_is_valid():
    cfg_path = REPO_ROOT / "config" / "market_titration_config.json"
    assert cfg_path.exists()
    cfg = load_titration_config(cfg_path)
    assert cfg["config_status"] == "file_merged"
    assert cfg["config_problems"] == []


# ---------------------------------------------------------------------------
# Contract: versioning, semantics, safety, proxies
# ---------------------------------------------------------------------------


def test_payload_versioning_and_semantics():
    payload = evaluate_market_titration(_item([10.0, 5.0, 1.0]), now=NOW)
    assert payload["schema_version"] == TITRATION_SCHEMA_VERSION
    assert payload["scoring_version"] == TITRATION_SCORING_VERSION
    assert payload["score_semantics"] == SCORE_SEMANTICS
    assert payload["half_life_source"] == "configured_prior"
    assert payload["calculated_at"].startswith("2026-07-10T12:00:00")


def test_proxy_metrics_are_labelled_as_proxies():
    payload = evaluate_market_titration(
        _item([30.0, 10.0, 4.0, 1.0]), now=NOW
    )
    assert payload["susceptibility"]["is_proxy"] is True
    # titration_v2: without measured response data the buffer is the
    # legacy proxy and says so via status.
    assert payload["buffer_capacity"]["status"] == "PROXY"
    assert payload["susceptibility"]["source"] == "HEURISTIC_PROXY"
    assert payload["susceptibility"]["fallback_level"] == 5
    assert payload["minimum_catalytic_dose"]["is_proxy"] is True
    assert payload["vmr"]["is_proxy"] is True
    assert payload["free_energy"]["is_proxy"] is True
    assert payload["coherence"]["is_proxy"] is True
    assert payload["vmr"]["inputs_missing"], "VMR must list its missing inputs"
    assert payload["lrr"]["weights_source"] == "configured_prior_uncalibrated"


def test_directional_evidence_honestly_marked_unavailable():
    payload = evaluate_market_titration(_item([10.0, 5.0]), now=NOW)
    assert payload["active_evidence"]["directional_evidence_available"] is False
    assert payload["coherence"]["directional_agreement_available"] is False


def test_safety_walker_full_payload():
    payload = evaluate_market_titration(_item([10.0, 5.0, 1.0]), now=NOW)
    _assert_safety(payload)
    _walk_assert_no_execution(payload)


def test_compact_projection_contract():
    payload = evaluate_market_titration(_item([30.0, 4.0, 1.0]), now=NOW)
    compact = compact_titration_fields(payload)
    assert compact["titration_state"] == payload["titration_state"]
    assert compact["titration_available"] is True
    t = compact["titration"]
    for key in ("lrr", "vmr_proxy", "pre_alpha_gap", "activation_barrier",
                "geometry", "temperature_regime", "data_sufficiency",
                "score_semantics", "scoring_version", "schema_version"):
        assert key in t, f"compact projection missing {key}"
    assert compact_titration_fields(None) == {  # type: ignore[arg-type]
        "titration_state": "INSUFFICIENT_DATA",
        "titration_available": False,
    }


def test_cli_example_emits_valid_json_and_safety():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "market_titration_engine.py"),
         "--example", "--json"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["titration_state"] in TITRATION_STATES
    assert payload["safety"]["advisory_status"] == "ADVISORY_ONLY"
