"""Behavioural tests for the guarded calibration recommendation loop."""
from __future__ import annotations

from scripts import calibration_recommendations as cr


def _recs(wins=0, losses=0, breakeven=0, pnl=1.0, bucket=None):
    rows = []
    def row(status):
        r = {"outcome_status": status, "pnl_estimate": pnl if status == "WIN" else -pnl}
        if bucket is not None:
            r["signal_state"] = bucket
        return r
    rows += [row("WIN")] * wins
    rows += [row("LOSS")] * losses
    rows += [row("BREAKEVEN")] * breakeven
    return rows


def test_no_data_observe_more():
    out = cr.build_recommendation([])
    assert out["overall"]["recommendation"] == cr.OBSERVE_MORE_DATA
    assert out["overall"]["recommended_threshold_shift"] == 0.0
    assert out["overall"]["applied"] is False
    assert out["auto_apply"] is False


def test_small_sample_do_not_adjust():
    out = cr.build_recommendation(_recs(wins=3, losses=2))  # 5 < 20
    assert out["overall"]["recommendation"] == cr.LOW_SAMPLE_DO_NOT_ADJUST
    assert out["overall"]["recommended_threshold_shift"] == 0.0
    assert out["overall"]["confidence"] == 0.0
    assert out["overall"]["applied"] is False


def test_enough_poor_outcomes_recommends_tighten_not_applied():
    # 25 outcomes, 70% losses -> high false-positive rate.
    out = cr.build_recommendation(_recs(wins=7, losses=18))
    o = out["overall"]
    assert o["recommendation"] == cr.RECOMMEND_TIGHTEN
    assert o["recommended_threshold_shift"] > 0  # raise the bar
    assert o["applied"] is False
    assert o["confidence"] > 0


def test_enough_good_outcomes_recommends_maintain_or_loosen_not_applied():
    # 30 outcomes, ~83% wins -> strong.
    out = cr.build_recommendation(_recs(wins=25, losses=5))
    o = out["overall"]
    assert o["recommendation"] in {cr.RECOMMEND_LOOSEN_SLIGHTLY, cr.RECOMMEND_MAINTAIN}
    assert o["recommended_threshold_shift"] <= 0.0
    assert o["applied"] is False


def test_mixed_outcomes_recommend_maintain():
    # 24 outcomes, 50/50 -> neither high FPR nor high win -> maintain.
    out = cr.build_recommendation(_recs(wins=12, losses=12))
    assert out["overall"]["recommendation"] == cr.RECOMMEND_MAINTAIN
    assert out["overall"]["recommended_threshold_shift"] == 0.0


def test_never_auto_applies():
    out = cr.build_recommendation(_recs(wins=7, losses=18))
    assert out["auto_apply"] is False
    assert out["overall"]["applied"] is False
    # No execution / sizing surface anywhere in the payload.
    blob = str(out).lower()
    for word in ("place_order", "execute_trade", "submit_order", "auto_buy", "auto_sell"):
        assert word not in blob


def test_bucketing_by_signal_state():
    rows = _recs(wins=7, losses=18, bucket="HURACAN")
    rows += _recs(wins=25, losses=5, bucket="DIABLO")
    out = cr.build_recommendation(rows, bucket_key="signal_state")
    assert "HURACAN" in out["buckets"]
    assert "DIABLO" in out["buckets"]
    assert out["buckets"]["HURACAN"]["recommendation"] == cr.RECOMMEND_TIGHTEN
    assert out["buckets"]["DIABLO"]["recommendation"] in {
        cr.RECOMMEND_LOOSEN_SLIGHTLY, cr.RECOMMEND_MAINTAIN
    }


def test_advisory_invariants_present():
    out = cr.build_recommendation(_recs(wins=1))
    assert out["advisory_status"] == "ADVISORY_ONLY"
    assert out["broker_api_called"] is False
    assert out["human_review_required"] is True
    assert out["ai_execution_count"] == 0


def test_recommendations_api_endpoint(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from scripts import api_server
    import scripts.persistence as persistence
    monkeypatch.setattr(persistence, "DB_PATH", tmp_path / "rec_api.db", raising=False)
    client = TestClient(api_server.app)
    r = client.get("/api/calibration-recommendations")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["overall"]["recommendation"] == "OBSERVE_MORE_DATA"
    assert data["auto_apply"] is False
    assert data["advisory_status"] == "ADVISORY_ONLY"
    assert data["broker_api_called"] is False
