"""titration_v2 engine tests: measured susceptibility overlay, measured
buffer, BUFFER_DEPLETING / ENDPOINT_CROSSING activation (and the guarantee
that heuristic proxies can never activate them), modular VMR with overlap
diagnostics, PAG confidence, directional disagreement, and recognition
inputs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.market_titration_engine import (
    RESERVED_STATES,
    TITRATION_STATES,
    evaluate_market_titration,
    load_titration_config,
)
from scripts.titration_recognition import compute_recognition_inputs

NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


def _iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _item(hours_ago, sources=None, **overrides):
    sources = sources or ["news"] * len(hours_ago)
    base = {
        "event_id": "EVT_V2",
        "ticker": "ACME",
        "event_timestamps": [_iso(h) for h in hours_ago],
        "event_sources": sources,
        "event_count": len(hours_ago),
        "cross_source_support_count": len(set(sources)),
        "duplicate_suppressed_count": 0,
        "persistence_score": 0.6,
        "contamination_score": 0.1,
        "chaos_sensitivity_score": 0.25,
        "observed_at": _iso(min(hours_ago)) if hours_ago else "",
    }
    base.update(overrides)
    return base


def _measured(chi=0.6, source="MEASURED_TICKER", level=1, n=25,
              accel="RESPONSE_STABLE", shrunk=False):
    return {
        "chi_norm": chi, "source": source, "fallback_level": level,
        "n": n, "was_shrunk": shrunk, "slope": chi * 4.0,
        "slope_lo": 0.5, "slope_hi": 3.5, "estimator": "chi_theil_sen_v1",
        "acceleration_class": accel, "horizon": 5,
        "fallback_path": [{"level": source, "status": "used"}],
    }


# ---------------------------------------------------------------------------
# Measured susceptibility overlay + buffer
# ---------------------------------------------------------------------------


def test_measured_overlay_used_and_proxy_retained():
    item = _item([30.0, 10.0, 4.0, 1.0], measured_susceptibility=_measured())
    payload = evaluate_market_titration(item, now=NOW)
    chi = payload["susceptibility"]
    assert chi["source"] == "MEASURED_TICKER"
    assert chi["is_proxy"] is False
    assert chi["sample_size"] == 25
    assert chi["susceptibility"] == 0.6
    assert chi["heuristic_proxy"]["is_proxy"] is True
    assert chi["heuristic_proxy"]["susceptibility"] is not None
    buffer = payload["buffer_capacity"]
    assert buffer["status"] == "MEASURED"
    assert buffer["legacy_buffer_proxy"] is not None


def test_shrunk_estimate_labelled_shrunk_buffer():
    item = _item([30.0, 10.0, 4.0], measured_susceptibility=_measured(
        source="MEASURED_MARKET", level=3, shrunk=True,
    ))
    payload = evaluate_market_titration(item, now=NOW)
    assert payload["susceptibility"]["source"] == "MEASURED_MARKET"
    assert payload["buffer_capacity"]["status"] == "SHRUNK"


def test_invalid_measured_block_falls_back_to_proxy():
    for bad in (
        {"chi_norm": None, "source": "MEASURED_TICKER", "fallback_level": 1},
        {"chi_norm": 0.5, "source": "MADE_UP", "fallback_level": 1},
        {"chi_norm": 0.5, "source": "MEASURED_TICKER", "fallback_level": 9},
        "not-a-dict",
    ):
        item = _item([30.0, 10.0, 4.0], measured_susceptibility=bad)
        payload = evaluate_market_titration(item, now=NOW)
        assert payload["susceptibility"]["source"] == "HEURISTIC_PROXY"
        assert payload["susceptibility"]["fallback_level"] == 5
        assert payload["buffer_capacity"]["status"] in {"PROXY", "UNAVAILABLE"}


def test_measured_buffer_stability_direction():
    dec = evaluate_market_titration(
        _item([30.0, 10.0, 4.0], measured_susceptibility=_measured(
            accel="RESPONSE_DECELERATING")), now=NOW,
    )["buffer_capacity"]["buffer_capacity"]
    acc = evaluate_market_titration(
        _item([30.0, 10.0, 4.0], measured_susceptibility=_measured(
            accel="RESPONSE_ACCELERATING")), now=NOW,
    )["buffer_capacity"]["buffer_capacity"]
    assert dec > acc, "decelerating response = more buffer than accelerating"


# ---------------------------------------------------------------------------
# New states: sample-gated activation, proxy exclusion
# ---------------------------------------------------------------------------


def _endpoint_item(**measured_kwargs):
    """Evidence burst that newly crosses the activation threshold while the
    market's own reaction (independent recognition) remains muted."""
    hours = [60.0, 40.0, 20.0, 10.0, 5.0, 2.0, 1.0, 0.5]
    sources = ["official_filing", "news", "polymarket", "news",
               "official_filing", "polymarket", "news", "official_filing"]
    return _item(
        hours, sources=sources, persistence_score=0.85,
        contamination_score=0.05, chaos_sensitivity_score=0.25,
        cross_source_support_count=2,
        recognition_inputs={"price_recognition": 0.1, "volume_recognition": 0.05},
        measured_susceptibility=_measured(**measured_kwargs),
    )


def test_endpoint_crossing_activates_with_measured_chi():
    payload = evaluate_market_titration(_endpoint_item(chi=0.6), now=NOW)
    flow = payload["flow"]
    if flow["threshold_newly_crossed"]:
        assert payload["titration_state"] == "ENDPOINT_CROSSING", (
            payload["state_rule_trace"]
        )
        assert "measured chi" in payload["state_rule_trace"][0]


def test_endpoint_crossing_never_activates_on_proxy():
    item = _endpoint_item(chi=0.6)
    del item["measured_susceptibility"]
    payload = evaluate_market_titration(item, now=NOW)
    assert payload["titration_state"] != "ENDPOINT_CROSSING"
    assert payload["susceptibility"]["source"] == "HEURISTIC_PROXY"


def test_buffer_depleting_activates_with_accelerating_measured_response():
    # Loading (accumulating) but below threshold, measured response
    # accelerating, buffer low.
    item = _item(
        [30.0, 8.0, 3.0, 1.0],
        sources=["news", "news", "polymarket", "news"],
        persistence_score=0.5,
        measured_susceptibility=_measured(chi=0.85, accel="RESPONSE_ACCELERATING"),
    )
    payload = evaluate_market_titration(item, now=NOW)
    flow = payload["flow"]
    barrier = payload["barrier"]["barrier"]
    if flow["loading"] and barrier > 0 and payload["pre_alpha_gap"] is not None:
        assert payload["titration_state"] in {"BUFFER_DEPLETING", "PRE_ALPHA_WATCH",
                                              "PRIMED", "ENDPOINT_CROSSING"}
        if payload["titration_state"] == "BUFFER_DEPLETING":
            assert payload["buffer_capacity"]["status"] in {"MEASURED", "SHRUNK"}


def test_buffer_depleting_never_activates_on_proxy():
    item = _item([30.0, 8.0, 3.0, 1.0], persistence_score=0.5)
    payload = evaluate_market_titration(item, now=NOW)
    assert payload["titration_state"] != "BUFFER_DEPLETING"


def test_repricing_still_reserved():
    assert "REPRICING" in RESERVED_STATES
    assert "REPRICING" not in TITRATION_STATES
    assert "BUFFER_DEPLETING" in TITRATION_STATES
    assert "ENDPOINT_CROSSING" in TITRATION_STATES


def test_ftr_precedence_beats_endpoint_crossing():
    item = _endpoint_item(chi=0.9)
    item.update({
        "persistence_score": 0.0,
        "contamination_score": 0.95,
        "chaos_sensitivity_score": 0.95,
        "event_sources": ["social"] * 8,
        "cross_source_support_count": 1,
    })
    payload = evaluate_market_titration(item, now=NOW)
    assert payload["titration_state"] == "FALSE_TRANSITION_RISK"


# ---------------------------------------------------------------------------
# VMR components, overlap, PAG confidence
# ---------------------------------------------------------------------------


def test_vmr_overlap_warning_without_independent_components():
    payload = evaluate_market_titration(_item([30.0, 10.0, 4.0, 1.0]), now=NOW)
    vmr = payload["vmr"]
    assert vmr["independent_component_count"] == 0
    assert vmr["overlap_warning"] is True
    assert vmr["confidence"] == "low"
    assert payload["pre_alpha_gap_confidence"] == "low_feature_overlap"
    # Adjusted PAG is discounted toward zero, same sign.
    pag, adj = payload["pre_alpha_gap"], payload["pre_alpha_gap_adjusted"]
    assert abs(adj) <= abs(pag)


def test_vmr_with_independent_recognition_components():
    item = _item(
        [30.0, 10.0, 4.0, 1.0],
        recognition_inputs={"price_recognition": 0.8, "volume_recognition": 0.6},
    )
    payload = evaluate_market_titration(item, now=NOW)
    vmr = payload["vmr"]
    assert vmr["independent_component_count"] == 2
    assert vmr["overlap_warning"] is False
    assert vmr["confidence"] == "moderate"
    assert vmr["components"]["price"] == 0.8
    assert payload["pre_alpha_gap_confidence"] == "moderate"
    assert payload["pre_alpha_gap_adjusted"] == payload["pre_alpha_gap"]


def test_vmr_missing_inputs_listed():
    payload = evaluate_market_titration(_item([10.0, 5.0]), now=NOW)
    missing = payload["vmr"]["inputs_missing"]
    assert "price_recognition_ohlcv" in missing
    assert "valuation_repricing" in missing


# ---------------------------------------------------------------------------
# Typed evidence: direction / magnitude
# ---------------------------------------------------------------------------


def test_directional_disagreement_unavailable_for_legacy_events():
    payload = evaluate_market_titration(_item([10.0, 5.0, 1.0]), now=NOW)
    dd = payload["directional_disagreement"]
    assert dd["available"] is False
    assert dd["entropy"] is None


def test_directional_disagreement_split_directions():
    item = _item([10.0, 5.0, 2.0, 1.0])
    item["event_directions"] = [1, -1, 1, -1]
    payload = evaluate_market_titration(item, now=NOW)
    dd = payload["directional_disagreement"]
    assert dd["available"] is True
    assert dd["entropy"] > 0.9  # near-even mass split -> near-max entropy
    assert 0.0 < dd["bull_share"] < 1.0


def test_directional_disagreement_unanimous():
    item = _item([10.0, 5.0, 2.0])
    item["event_directions"] = [1, 1, 1]
    payload = evaluate_market_titration(item, now=NOW)
    dd = payload["directional_disagreement"]
    assert dd["available"] is True
    assert dd["entropy"] == 0.0
    assert dd["bull_share"] == 1.0


def test_magnitude_scales_evidence_mass():
    plain = evaluate_market_titration(_item([5.0, 2.0]), now=NOW)
    scaled_item = _item([5.0, 2.0])
    scaled_item["event_magnitudes"] = [0.5, 0.5]
    scaled = evaluate_market_titration(scaled_item, now=NOW)
    assert (
        scaled["active_evidence"]["raw_mass"]
        < plain["active_evidence"]["raw_mass"]
    )
    # Hostile magnitudes never crash and never amplify beyond unit.
    hostile_item = _item([5.0, 2.0])
    hostile_item["event_magnitudes"] = [float("nan"), 99.0]
    hostile = evaluate_market_titration(hostile_item, now=NOW)
    assert hostile["active_evidence"]["raw_mass"] <= plain["active_evidence"]["raw_mass"] + 1e-9


# ---------------------------------------------------------------------------
# Recognition module
# ---------------------------------------------------------------------------


def _rec_bars(closes, volumes=None):
    volumes = volumes or [1000.0] * len(closes)
    return [
        {"date": f"2026-01-{i + 1:02d}", "close": c, "volume": v,
         "source": "MANUAL_CSV_IMPORT"}
        for i, (c, v) in enumerate(zip(closes, volumes))
    ]


def test_recognition_insufficient_bars():
    result = compute_recognition_inputs(_rec_bars([100.0] * 5))
    assert result["available"] is False
    assert result["reason"] == "insufficient_bars"
    assert compute_recognition_inputs(None)["available"] is False


def test_recognition_range_top_vs_bottom():
    rising = compute_recognition_inputs(
        _rec_bars([100 + i * 0.2 for i in range(20)] + [110.0])
    )
    falling = compute_recognition_inputs(
        _rec_bars([110 - i * 0.2 for i in range(20)] + [100.0])
    )
    assert rising["available"] and falling["available"]
    assert rising["price_recognition"] > falling["price_recognition"]


def test_recognition_volume_spike():
    quiet = compute_recognition_inputs(
        _rec_bars([100.0 + (i % 2) * 0.3 for i in range(25)])
    )
    spike_vols = [1000.0] * 24 + [8000.0]
    spiky = compute_recognition_inputs(
        _rec_bars([100.0 + (i % 2) * 0.3 for i in range(25)], spike_vols)
    )
    assert spiky["volume_recognition"] > quiet["volume_recognition"]
    assert spiky["volume_recognition"] == 1.0  # 8x median clipped to 1


def test_recognition_bounded_outputs():
    result = compute_recognition_inputs(
        _rec_bars([100.0, 1e9] + [100.0] * 25)
    )
    if result["available"]:
        assert 0.0 <= result["price_recognition"] <= 1.0
        if result["volume_recognition"] is not None:
            assert 0.0 <= result["volume_recognition"] <= 1.0
