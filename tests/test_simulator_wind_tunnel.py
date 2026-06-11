"""Wind-tunnel proofs: no-lookahead, determinism, provenance honesty,
outcome resolution, contradiction-hold cohorts, and the full persistence
loop into the calibration report.

The credibility cornerstone is the no-lookahead test: corrupting every
bar AFTER a decision point must not change that decision.
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import pytest

from scripts import persistence
from scripts.simulator_api import run_wind_tunnel_candidate
from src.simulator.calibration_bridge import build_calibration_report
from src.simulator.wind_tunnel import (
    MAX_DECISIONS,
    MIN_HISTORY_BARS,
    default_payload_builder,
    run_wind_tunnel,
)


def make_bars(n: int = 160, seed: int = 7) -> list[dict]:
    """Deterministic synthetic bars with alternating trend regimes."""
    rng = random.Random(seed)
    bars, price = [], 100.0
    for i in range(n):
        regime = 0.006 if (i // 40) % 2 == 0 else -0.004
        price *= 1.0 + regime + rng.gauss(0, 0.012)
        bars.append({"date": f"d{i:04d}", "close": round(price, 4)})
    return bars


BARS = make_bars()
REPORT = run_wind_tunnel(
    ticker="TUNNEL", bars=BARS, price_provenance="SYNTHETIC",
    horizon_days=10, every_n_bars=5,
)


# --- Happy path --------------------------------------------------------------
def test_wind_tunnel_produces_resolved_decisions_with_spread() -> None:
    assert REPORT.decision_count >= 15
    assert len(REPORT.state_performance) >= 2  # verdicts vary with regime
    for decision in REPORT.decisions:
        assert decision.outcome_class in (
            "good_process_good_result", "good_process_bad_result",
        )
    assert REPORT.calibration["sample_size"] == REPORT.decision_count


# --- The cornerstone: no lookahead -------------------------------------------
def test_no_lookahead_corrupting_future_bars_changes_nothing() -> None:
    cutoff = MIN_HISTORY_BARS + 25  # second decision point (step 5)
    corrupted = copy.deepcopy(BARS)
    for bar in corrupted[cutoff:]:
        bar["close"] = 1.0  # destroy the future
    original = run_wind_tunnel(
        ticker="TUNNEL", bars=BARS, price_provenance="SYNTHETIC",
        horizon_days=10, every_n_bars=5,
    )
    tampered = run_wind_tunnel(
        ticker="TUNNEL", bars=corrupted, price_provenance="SYNTHETIC",
        horizon_days=10, every_n_bars=5,
    )
    # Decisions strictly BEFORE the corruption window must be identical in
    # state and score (their visible bars are untouched).
    for a, b in zip(original.decisions, tampered.decisions):
        if a.bar_index >= cutoff - 10:  # horizon reaches into corruption
            break
        assert (a.final_state, round(a.score, 6)) == (
            b.final_state, round(b.score, 6),
        ), f"lookahead detected at bar {a.bar_index}"


# --- Determinism --------------------------------------------------------------
def test_wind_tunnel_is_deterministic() -> None:
    second = run_wind_tunnel(
        ticker="TUNNEL", bars=make_bars(), price_provenance="SYNTHETIC",
        horizon_days=10, every_n_bars=5,
    )
    assert json.dumps(REPORT.to_dict(), sort_keys=True) == json.dumps(
        second.to_dict(), sort_keys=True
    )


# --- Provenance honesty --------------------------------------------------------
def test_synthetic_provenance_is_fixture_tier_autotune_locked() -> None:
    assert REPORT.data_source == "fixture_replay"
    assert REPORT.calibration["calibration_mode"] == "fixture_replay"
    assert REPORT.calibration["unsafe_to_autotune"] is True


def test_imported_provenance_is_backtest_tier_autotune_still_locked() -> None:
    # Plumbing check: bars here are synthetic, but we verify the IMPORTED
    # path labels rows backtest_replay and that autotune stays locked even
    # on the stronger tier (backtests are counterfactual, not empirical).
    report = run_wind_tunnel(
        ticker="TUNNEL", bars=BARS, price_provenance="IMPORTED",
        horizon_days=10, every_n_bars=5,
    )
    assert report.data_source == "backtest_replay"
    assert report.calibration["calibration_mode"] == "backtest_replay"
    assert report.calibration["backtest_rows"] == report.decision_count
    assert report.calibration["unsafe_to_autotune"] is True
    assert any(
        "not empirical" in blocker
        for blocker in report.calibration["autotune_blockers"]
    )


def test_unknown_provenance_treated_as_synthetic() -> None:
    report = run_wind_tunnel(
        ticker="T", bars=make_bars(60), price_provenance="trust me",
        horizon_days=5, every_n_bars=10,
    )
    assert report.data_source == "fixture_replay"


# --- Outcome resolution math ----------------------------------------------------
def test_forward_return_sign_drives_outcome() -> None:
    for decision in REPORT.decisions:
        entry = float(BARS[decision.bar_index]["close"])
        exit_price = float(BARS[decision.bar_index + 10]["close"])
        expected = (exit_price - entry) / entry
        assert decision.forward_return == pytest.approx(expected)
        assert decision.result_good == (expected > 0)


# --- Contradiction-hold cohort split ---------------------------------------------
def test_contradiction_hold_cohort_is_measured() -> None:
    def contradicting_builder(ticker: str, visible: list[dict]) -> dict:
        payload = default_payload_builder(ticker, visible)
        # Inject a mechanism-free strategy section on alternating windows:
        # the stewards hold those verdicts.
        if len(visible) % 10 < 5:
            payload["strategy"] = {
                "narrative": "vibes",
                "mechanism": {"probability_shock": 0.9},
            }
        return payload

    report = run_wind_tunnel(
        ticker="HOLD", bars=BARS, price_provenance="SYNTHETIC",
        horizon_days=10, every_n_bars=5,
        payload_builder=contradicting_builder,
    )
    assert report.contradiction_hold_cohort.count > 0
    assert report.clean_cohort.count > 0
    assert report.hold_underperformance is not None
    assert any("CONTRADICTION_HOLD cohort" in r for r in report.rationale)


# --- Persistence loop into the calibration report --------------------------------
def test_persisted_run_feeds_calibration_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.simulator_api import simulator_calibration_report

    monkeypatch.setattr(
        persistence, "DB_PATH", tmp_path / "wind.db", raising=True
    )
    report = run_wind_tunnel(
        ticker="LOOP", bars=make_bars(160), price_provenance="IMPORTED",
        horizon_days=10, every_n_bars=5, persist=True,
    )
    assert report.decision_count >= 10  # clears the bridge's signal floor
    assert report.persisted_evaluations == report.decision_count
    served = simulator_calibration_report()
    assert served["calibration_mode"] == "backtest_replay"
    assert served["sample_size"] == report.decision_count
    assert served["unsafe_to_autotune"] is True
    assert served["advisory_status"] == "ADVISORY_ONLY"


# --- Bounds and degenerate inputs --------------------------------------------------
def test_bounds_and_empty_inputs() -> None:
    empty = run_wind_tunnel(
        ticker="X", bars=[], price_provenance="SYNTHETIC",
    )
    assert empty.decision_count == 0
    assert empty.calibration["calibration_mode"] == "insufficient_data"

    short = run_wind_tunnel(
        ticker="X", bars=make_bars(20), price_provenance="SYNTHETIC",
    )
    assert short.decision_count == 0

    dense = run_wind_tunnel(
        ticker="X", bars=make_bars(1200, seed=3),
        price_provenance="SYNTHETIC", horizon_days=2, every_n_bars=1,
    )
    assert dense.decision_count <= MAX_DECISIONS


# --- API contract ---------------------------------------------------------------
def test_api_wrapper_is_stamped_and_bounded() -> None:
    result = run_wind_tunnel_candidate(
        {"ticker": "API", "bars": make_bars(80),
         "price_provenance": "SYNTHETIC", "horizon_days": 5,
         "every_n_bars": 10}
    )
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_gate"] == "LOCKED"
    assert "not a return promise" in result["advisory_note"].lower()
    json.dumps(result)

    for garbage in (None, "x", 9, {"bars": "nope"}):
        out = run_wind_tunnel_candidate(garbage)  # type: ignore[arg-type]
        assert out["decision_count"] == 0


@pytest.fixture(scope="module")
def client():
    try:
        from fastapi.testclient import TestClient
    except ModuleNotFoundError:  # pragma: no cover
        pytest.skip("fastapi not installed")
    from scripts import api_server

    if not getattr(api_server, "_FASTAPI_AVAILABLE", False):
        pytest.skip("fastapi not available")
    return TestClient(api_server.app)


def test_http_wind_tunnel_route(client) -> None:
    response = client.post(
        "/simulator/wind-tunnel",
        json={"ticker": "HTTP", "bars": make_bars(80),
              "price_provenance": "SYNTHETIC", "horizon_days": 5,
              "every_n_bars": 10},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["data_source"] == "fixture_replay"
    assert body["decision_count"] > 0
