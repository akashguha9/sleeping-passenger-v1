"""Tests for scripts/titration_susceptibility.py — measured response layer.

Covers: Theil–Sen robustness, normalization, shrinkage, sample gates,
hierarchy resolution with fallback paths, response-acceleration windows,
catalytic-convexity gates, and numerical safety.
"""

from __future__ import annotations

from scripts.titration_susceptibility import (
    ACCEL_ACCELERATING,
    ACCEL_DECELERATING,
    ACCEL_INSUFFICIENT,
    ACCEL_STABLE,
    CC_APPROX_LINEAR,
    CC_INSUFFICIENT,
    CC_NEGATIVE,
    CC_POSITIVE,
    CC_UNSTABLE,
    classify_response_acceleration,
    estimate_catalytic_convexity,
    estimate_scope,
    market_for_ticker,
    normalize_susceptibility,
    resolve_susceptibility,
    shrink_slope,
    theil_sen_slope,
)


def _obs(doses, zs):
    return [
        {"dose": d, "z": z, "event_ts": f"2026-01-{i + 1:02d}T00:00:00+00:00"}
        for i, (d, z) in enumerate(zip(doses, zs))
    ]


# ---------------------------------------------------------------------------
# Theil–Sen
# ---------------------------------------------------------------------------


def test_positive_linear_slope_recovered():
    xs = [0.1 * i for i in range(20)]
    ys = [2.0 * x + 0.5 for x in xs]
    fit = theil_sen_slope(xs, ys)
    assert abs(fit["slope"] - 2.0) < 1e-9
    assert fit["n"] == 20


def test_zero_slope():
    xs = [0.1 * i for i in range(15)]
    ys = [1.0] * 15
    assert theil_sen_slope(xs, ys)["slope"] == 0.0


def test_negative_slope():
    xs = [0.1 * i for i in range(15)]
    ys = [-3.0 * x for x in xs]
    assert abs(theil_sen_slope(xs, ys)["slope"] + 3.0) < 1e-9


def test_outlier_robustness():
    xs = [0.1 * i for i in range(21)]
    ys = [1.0 * x for x in xs]
    ys[10] = 500.0  # single wild outlier
    fit = theil_sen_slope(xs, ys)
    assert abs(fit["slope"] - 1.0) < 0.5, "median-of-slopes must resist one outlier"


def test_tiny_sample_returns_none():
    assert theil_sen_slope([1.0, 2.0], [1.0, 2.0])["slope"] is None


def test_constant_dose_unidentifiable():
    xs = [0.5] * 10
    ys = [float(i) for i in range(10)]
    assert theil_sen_slope(xs, ys)["slope"] is None


def test_nan_and_inf_filtered():
    xs = [0.1, 0.2, float("nan"), 0.4, float("inf"), 0.6, 0.7]
    ys = [0.1, 0.2, 0.3, 0.4, 0.5, float("nan"), 0.7]
    fit = theil_sen_slope(xs, ys)
    assert fit["slope"] is not None
    assert fit["n"] == 4  # only fully-finite pairs


def test_slope_clipping():
    xs = [0.0, 1e-9, 2e-9, 3e-9, 4e-9, 5e-9]
    ys = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]
    fit = theil_sen_slope(xs, ys, clip=25.0)
    assert fit["slope"] is not None and abs(fit["slope"]) <= 25.0


def test_ci_band_ordering():
    xs = [0.1 * i for i in range(30)]
    ys = [1.5 * x + (0.1 if i % 3 == 0 else -0.1) for i, x in enumerate(xs)]
    fit = theil_sen_slope(xs, ys)
    assert fit["slope_lo"] <= fit["slope"] <= fit["slope_hi"]


# ---------------------------------------------------------------------------
# Normalization / shrinkage
# ---------------------------------------------------------------------------


def test_normalize_bounds():
    assert normalize_susceptibility(None) is None
    assert normalize_susceptibility(-3.0) == 0.0
    assert normalize_susceptibility(0.0) == 0.0
    assert normalize_susceptibility(2.0, slope_scale=4.0) == 0.5
    assert normalize_susceptibility(100.0, slope_scale=4.0) == 1.0


def test_shrinkage_pulls_toward_parent():
    shrunk, was = shrink_slope(4.0, 10, 0.0, shrinkage_k=10.0)
    assert was is True
    assert abs(shrunk - 2.0) < 1e-9  # (10*4 + 10*0)/20
    alone, was2 = shrink_slope(4.0, 10, None)
    assert alone == 4.0 and was2 is False
    parent_only, was3 = shrink_slope(None, 0, 1.5)
    assert parent_only == 1.5 and was3 is True


# ---------------------------------------------------------------------------
# Acceleration
# ---------------------------------------------------------------------------


def test_acceleration_classes():
    # Early half: flat response; late half: steep response -> ACCELERATING.
    doses = [0.1 * (i % 10 + 1) for i in range(20)]
    zs_early = [0.05 * d for d in doses[:10]]
    zs_late = [5.0 * d for d in doses[10:]]
    result = classify_response_acceleration(doses, zs_early + zs_late)
    assert result["acceleration_class"] == ACCEL_ACCELERATING

    result_flat = classify_response_acceleration(doses, [1.0 * d for d in doses])
    assert result_flat["acceleration_class"] == ACCEL_STABLE

    result_dec = classify_response_acceleration(
        doses, [5.0 * d for d in doses[:10]] + [0.05 * d for d in doses[10:]]
    )
    assert result_dec["acceleration_class"] == ACCEL_DECELERATING


def test_acceleration_insufficient_window():
    doses = [0.1, 0.2, 0.3, 0.4]
    zs = [0.1, 0.2, 0.3, 0.4]
    assert classify_response_acceleration(doses, zs)["acceleration_class"] == ACCEL_INSUFFICIENT


# ---------------------------------------------------------------------------
# Scope estimation + hierarchy
# ---------------------------------------------------------------------------


def test_estimate_scope_gate_blocks_small_sample():
    obs = _obs([0.1, 0.2, 0.3], [0.1, 0.2, 0.3])
    assert estimate_scope(obs, scope_type="TICKER", scope_key="X",
                          horizon=5, min_obs=12) is None


def test_estimate_scope_produces_full_record():
    doses = [0.05 * (i % 12 + 1) for i in range(36)]
    zs = [2.0 * d + 0.01 for d in doses]
    est = estimate_scope(_obs(doses, zs), scope_type="TICKER", scope_key="ACME",
                         horizon=5, min_obs=12, parent_slope=0.0)
    assert est is not None
    assert est["scope_type"] == "TICKER"
    assert est["n"] == 36
    assert est["chi_norm"] is not None and 0.0 <= est["chi_norm"] <= 1.0
    assert est["was_shrunk"] is True  # pulled toward parent 0.0
    assert est["raw_slope"] > est["slope"]  # shrinkage reduced it
    assert est["score_semantics"] == "measured_response_slope_not_probability"


def _estimates_fixture():
    return [
        {"scope_type": "TICKER", "scope_key": "ACME", "horizon": 5,
         "chi_norm": 0.6, "n": 20, "slope": 2.4, "slope_lo": 1.0, "slope_hi": 3.5,
         "was_shrunk": True, "estimator": "chi_theil_sen_v1",
         "acceleration_class": "RESPONSE_STABLE"},
        {"scope_type": "MARKET", "scope_key": "US", "horizon": 5,
         "chi_norm": 0.4, "n": 80, "slope": 1.6, "slope_lo": 1.0, "slope_hi": 2.0,
         "was_shrunk": False, "estimator": "chi_theil_sen_v1",
         "acceleration_class": "RESPONSE_STABLE"},
        {"scope_type": "GLOBAL", "scope_key": "GLOBAL", "horizon": 5,
         "chi_norm": 0.3, "n": 200, "slope": 1.2, "slope_lo": 0.9, "slope_hi": 1.5,
         "was_shrunk": False, "estimator": "chi_theil_sen_v1",
         "acceleration_class": "RESPONSE_STABLE"},
    ]


def test_hierarchy_prefers_ticker_when_gated():
    result = resolve_susceptibility(
        ticker="ACME", market="US", sector=None, horizon=5,
        estimates=_estimates_fixture(),
    )
    assert result["source"] == "MEASURED_TICKER"
    assert result["fallback_level"] == 1
    assert result["estimate"]["chi_norm"] == 0.6
    # Sector level records why it was skipped.
    levels = {p["level"]: p["status"] for p in result["fallback_path"]}
    assert levels["MEASURED_TICKER"] == "used"


def test_hierarchy_falls_to_market_below_ticker_gate():
    ests = _estimates_fixture()
    ests[0]["n"] = 5  # below min_obs_ticker=12
    result = resolve_susceptibility(
        ticker="ACME", market="US", sector=None, horizon=5, estimates=ests,
    )
    assert result["source"] == "MEASURED_MARKET"
    assert result["fallback_level"] == 3
    path = {p["level"]: p["status"] for p in result["fallback_path"]}
    assert path["MEASURED_TICKER"] == "below_ticker_gate"
    assert path["SHRUNK_SECTOR"] == "sector_unavailable"


def test_hierarchy_proxy_when_nothing_measured():
    result = resolve_susceptibility(
        ticker="NOPE", market="INDIA", sector=None, horizon=5, estimates=[],
    )
    assert result["source"] == "HEURISTIC_PROXY"
    assert result["fallback_level"] == 5
    assert result["estimate"] is None
    assert result["fallback_path"][-1]["level"] == "HEURISTIC_PROXY"


def test_market_for_ticker():
    assert market_for_ticker("RELIANCE.NS") == "INDIA"
    assert market_for_ticker("TCS.BO") == "INDIA"
    assert market_for_ticker("AAPL") == "US"
    assert market_for_ticker("SAP.DE") == "GLOBAL_OTHER"
    assert market_for_ticker("AAPL", country="IN") == "INDIA"
    assert market_for_ticker("X.NS", country="US") == "US"


# ---------------------------------------------------------------------------
# Catalytic convexity
# ---------------------------------------------------------------------------


def _cc_obs(doses, zs):
    return _obs(doses, zs)


def test_convexity_insufficient_below_gate():
    result = estimate_catalytic_convexity(
        _cc_obs([0.1] * 10, [0.1] * 10), horizon=5
    )
    assert result["state"] == CC_INSUFFICIENT
    assert result["coefficient"] is None


def test_convexity_positive_quadratic():
    doses = [0.02 * (i % 25 + 1) for i in range(100)]
    zs = [10.0 * d * d + 0.2 * d for d in doses]
    result = estimate_catalytic_convexity(_cc_obs(doses, zs), horizon=5)
    assert result["state"] == CC_POSITIVE
    assert result["coefficient"] > 0


def test_convexity_negative_quadratic():
    doses = [0.02 * (i % 25 + 1) for i in range(100)]
    zs = [-8.0 * d * d + 3.0 * d for d in doses]
    result = estimate_catalytic_convexity(_cc_obs(doses, zs), horizon=5)
    assert result["state"] == CC_NEGATIVE


def test_convexity_linear_band():
    doses = [0.02 * (i % 25 + 1) for i in range(100)]
    zs = [1.5 * d for d in doses]
    result = estimate_catalytic_convexity(_cc_obs(doses, zs), horizon=5)
    assert result["state"] == CC_APPROX_LINEAR


def test_convexity_unstable_sign_flip():
    doses = [0.02 * (i % 25 + 1) for i in range(100)]
    zs = [12.0 * d * d for d in doses[:50]] + [-12.0 * d * d + 4 * d for d in doses[50:]]
    result = estimate_catalytic_convexity(_cc_obs(doses, zs), horizon=5)
    assert result["state"] in (CC_UNSTABLE, CC_APPROX_LINEAR)


def test_convexity_insufficient_dose_spread():
    doses = [0.5 + (1e-5 * i) for i in range(60)]
    zs = [d * d for d in doses]
    result = estimate_catalytic_convexity(_cc_obs(doses, zs), horizon=5)
    assert result["state"] == CC_INSUFFICIENT


def test_convexity_is_labelled_experimental():
    result = estimate_catalytic_convexity([], horizon=5)
    assert result["is_experimental"] is True
    assert "not_probability" in result["score_semantics"]
