"""Tests for the Kronos price-path evidence layer (advisory-only).

Covers Section 12 backend tests 1-11:
  1.  disabled-safe
  2.  insufficient-data
  3.  supportive math
  4.  unstable downside
  5.  noisy path
  6.  contradictory
  7.  cannot upgrade DIABLO / NO_NEW_RISK
  8.  kronos-only positive stays WATCHLIST
  9.  failure has no decision impact (ERROR_SAFE)
  10. safety stamps on every output
  11. no forbidden execution language in outputs
"""
from __future__ import annotations

import pytest

from scripts import kronos_price_path_evidence as k
from scripts.advisory_contract import FORBIDDEN_EXECUTION_TOKENS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bars(closes):
    return [
        k.KronosOHLCVBar(
            timestamp_utc="2026-01-01T00:00:00Z",
            open=c,
            high=c * 1.01,
            low=c * 0.99,
            close=c,
            volume=1000.0,
        )
        for c in closes
    ]


def _flat_bars(n=120, level=100.0):
    return _bars([level] * n)


def _request(bars, *, score=5.0, signal_class="WATCHLIST", asset_class="equity"):
    return k.KronosEvidenceRequest(
        ticker="TST",
        asset_class=asset_class,
        bars=bars,
        existing_signal_score=score,
        existing_signal_class=signal_class,
        prediction_horizon_bars=20,
    )


@pytest.fixture(autouse=True)
def _enable_stub(monkeypatch):
    """Default to enabled stub-safe mode; individual tests override."""
    monkeypatch.setenv("KRONOS_ENABLED", "true")
    monkeypatch.setenv("KRONOS_MODE", "stub_safe")


def _up_path():
    return [100.0 + (5.0 * h / 20.0) for h in range(1, 21)]


def _down_path():
    return [100.0 - (5.0 * h / 20.0) for h in range(1, 21)]


def _crash_path():
    # Steep drawdown then flat at 80 — large downside_path_risk.
    return [100.0 - (20.0 * h / 10.0) if h <= 10 else 80.0 for h in range(1, 21)]


def _noisy_path():
    # Oscillating, net ~0, small drawdown -> high noise_penalty.
    return [102.0 if h % 2 == 1 else 98.0 for h in range(1, 20)] + [100.0]


# ---------------------------------------------------------------------------
# 1. disabled-safe
# ---------------------------------------------------------------------------


def test_kronos_disabled_safe(monkeypatch):
    monkeypatch.setenv("KRONOS_ENABLED", "false")
    ev = k.generate_evidence(_request(_flat_bars()), forecast_closes=_up_path())
    assert ev.status == k.STATUS_DISABLED
    assert ev.final_score_delta == 0.0
    d = ev.to_dict()
    assert d["advisory_only"] is True
    assert d["human_execution_required"] is True
    assert d["execution_gate"] == "LOCKED"
    assert d["broker_api_called"] is False
    assert d["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# 2. insufficient-data
# ---------------------------------------------------------------------------


def test_kronos_insufficient_data():
    ev = k.generate_evidence(_request(_flat_bars(n=10)), forecast_closes=_up_path())
    assert ev.status == k.STATUS_INSUFFICIENT_DATA
    assert ev.final_score_delta == 0.0
    assert ev.forecast_return_pct is None


# ---------------------------------------------------------------------------
# 3. supportive math
# ---------------------------------------------------------------------------


def test_kronos_supportive_math():
    ev = k.generate_evidence(_request(_flat_bars()), forecast_closes=_up_path())
    assert ev.status == k.STATUS_SUPPORTIVE
    assert ev.final_score_delta > 0
    assert ev.final_score_delta <= 0.50
    assert ev.directional_agreement is True
    assert ev.forecast_return_pct == pytest.approx(5.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 4. unstable downside
# ---------------------------------------------------------------------------


def test_kronos_unstable_downside():
    ev = k.generate_evidence(_request(_flat_bars()), forecast_closes=_crash_path())
    assert ev.status == k.STATUS_UNSTABLE
    assert ev.downside_penalty > ev.alignment_bonus
    assert ev.final_score_delta <= 0
    assert ev.downside_path_risk >= 0.70


# ---------------------------------------------------------------------------
# 5. noisy path
# ---------------------------------------------------------------------------


def test_kronos_noisy_path():
    ev = k.generate_evidence(_request(_flat_bars()), forecast_closes=_noisy_path())
    assert ev.status == k.STATUS_NOISY
    assert ev.noise_penalty > 0
    assert ev.downside_path_risk < 0.70


# ---------------------------------------------------------------------------
# 6. contradictory
# ---------------------------------------------------------------------------


def test_kronos_contradictory():
    ev = k.generate_evidence(_request(_flat_bars()), forecast_closes=_down_path())
    assert ev.status == k.STATUS_CONTRADICTORY
    assert ev.sign_forecast == -1
    assert ev.directional_agreement is False
    # The gating helper must require human review on a contradiction.
    result = k.apply_kronos_to_signal(
        {"score": 5.0, "signal_class": "WATCHLIST"}, ev
    )
    assert result["human_review_required"] is True


# ---------------------------------------------------------------------------
# 7. cannot upgrade DIABLO / NO_NEW_RISK
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("veto_class", ["DIABLO", "NO_NEW_RISK", "CHAOS_VETO"])
def test_kronos_cannot_upgrade_diablo(veto_class):
    ev = k.generate_evidence(_request(_flat_bars()), forecast_closes=_up_path())
    assert ev.status == k.STATUS_SUPPORTIVE  # positive evidence
    base = {"score": 4.0, "signal_class": veto_class}
    result = k.apply_kronos_to_signal(base, ev)
    assert result["final_signal_class"] == veto_class
    assert result["safety_veto_preserved"] is True
    # Score may not be raised above base by Kronos.
    assert result["final_score"] <= result["base_score"]


# ---------------------------------------------------------------------------
# 8. kronos-only positive stays WATCHLIST
# ---------------------------------------------------------------------------


def test_kronos_only_positive_evidence_stays_watchlist():
    ev = k.generate_evidence(_request(_flat_bars()), forecast_closes=_up_path())
    assert ev.final_score_delta > 0
    base = {"score": 5.0, "signal_class": "CANDIDATE"}
    result = k.apply_kronos_to_signal(
        base, ev, kronos_is_only_positive_evidence=True
    )
    assert result["final_signal_class"] == "WATCHLIST"
    assert result["final_signal_class"] != "BUY-CANDIDATE"


# ---------------------------------------------------------------------------
# 9. failure has no decision impact (ERROR_SAFE)
# ---------------------------------------------------------------------------


def test_kronos_failure_has_no_decision_impact():
    def _boom(_request, _horizon):
        raise RuntimeError("forced model failure")

    base_score = 6.0
    ev = k.generate_evidence(_request(_flat_bars()), forecast_fn=_boom)
    assert ev.status == k.STATUS_ERROR_SAFE
    assert ev.final_score_delta == 0.0
    assert ev.proof_status == "FAILED_SAFE_NO_DECISION_IMPACT"
    result = k.apply_kronos_to_signal(
        {"score": base_score, "signal_class": "WATCHLIST"}, ev
    )
    assert result["final_score"] == pytest.approx(base_score)
    assert "ERROR_SAFE_NO_DECISION_IMPACT" in result["proof_status"]


# ---------------------------------------------------------------------------
# 10. safety stamps on every output
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "forecast,enabled",
    [
        (_up_path(), True),
        (_down_path(), True),
        (_crash_path(), True),
        (_noisy_path(), True),
    ],
)
def test_kronos_safety_stamps(forecast, enabled, monkeypatch):
    monkeypatch.setenv("KRONOS_ENABLED", "true" if enabled else "false")
    ev = k.generate_evidence(_request(_flat_bars()), forecast_closes=forecast)
    d = ev.to_dict()
    assert d["advisory_only"] is True
    assert d["human_execution_required"] is True
    assert d["execution_gate"] == "LOCKED"
    assert d["broker_api_called"] is False
    assert d["ai_execution_count"] == 0
    assert d["used_in_decision"] == "EVIDENCE_ONLY"
    # Status is always one of the allowed labels, never an execution verb.
    assert d["status"] in k.ALLOWED_STATUSES
    for forbidden in k.FORBIDDEN_STATUS_LABELS:
        assert d["status"] != forbidden


def test_kronos_status_never_execution_label():
    paths = {
        "up": _up_path(),
        "down": _down_path(),
        "crash": _crash_path(),
        "noisy": _noisy_path(),
    }
    for forecast in paths.values():
        ev = k.generate_evidence(_request(_flat_bars()), forecast_closes=forecast)
        assert ev.status in k.ALLOWED_STATUSES


# ---------------------------------------------------------------------------
# 11. no forbidden execution language in outputs
# ---------------------------------------------------------------------------


def test_kronos_no_forbidden_language_backend(monkeypatch):
    """Scan produced evidence + gating outputs for execution tokens."""
    forecasts = [_up_path(), _down_path(), _crash_path(), _noisy_path()]
    blobs: list[str] = []
    for forecast in forecasts:
        ev = k.generate_evidence(_request(_flat_bars()), forecast_closes=forecast)
        d = ev.to_dict()
        blobs.append(" ".join(str(v) for v in d.values()))
        result = k.apply_kronos_to_signal(
            {"score": 5.0, "signal_class": "WATCHLIST"}, ev
        )
        blobs.append(" ".join(str(v) for v in result.values()))
    # Disabled + error-safe outputs too.
    monkeypatch.setenv("KRONOS_ENABLED", "false")
    blobs.append(
        " ".join(
            str(v)
            for v in k.generate_evidence(
                _request(_flat_bars()), forecast_closes=_up_path()
            )
            .to_dict()
            .values()
        )
    )

    combined = " ".join(blobs).lower()
    for token in FORBIDDEN_EXECUTION_TOKENS:
        assert token.lower() not in combined, (
            f"forbidden execution token {token!r} found in Kronos output"
        )


# ---------------------------------------------------------------------------
# Extra: mode resolution + caps
# ---------------------------------------------------------------------------


def test_resolve_mode_disabled_when_flag_off(monkeypatch):
    monkeypatch.setenv("KRONOS_ENABLED", "false")
    assert k.resolve_mode() == k.MODE_DISABLED


def test_resolve_mode_stub_when_enabled(monkeypatch):
    monkeypatch.setenv("KRONOS_ENABLED", "true")
    monkeypatch.setenv("KRONOS_MODE", "stub_safe")
    assert k.resolve_mode() == k.MODE_STUB_SAFE


def test_final_score_delta_hard_caps():
    # Help is capped at +0.50; a strongly upward, high-confidence path
    # must never exceed the cap.
    huge_up = [100.0 * (1.10 ** h) for h in range(1, 21)]
    ev = k.generate_evidence(
        _request(_flat_bars()),
        forecast_closes=huge_up,
        calibration_multiplier=1.25,
    )
    assert ev.final_score_delta <= 0.50
    # Hurt is capped at -1.00.
    ev2 = k.generate_evidence(
        _request(_flat_bars()),
        forecast_closes=_crash_path(),
        calibration_multiplier=1.25,
    )
    assert ev2.final_score_delta >= -1.00


def test_supportive_clip_at_ten():
    ev = k.generate_evidence(_request(_flat_bars(), score=9.9), forecast_closes=_up_path())
    result = k.apply_kronos_to_signal({"score": 9.9, "signal_class": "CANDIDATE"}, ev)
    assert result["final_score"] <= 10.0
