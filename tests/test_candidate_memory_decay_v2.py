"""Tests for ``scripts.candidate_memory_decay_v2`` — catalyst-typed decay,
stale-repeat penalty, quarantine, reset discipline, and the two summary
artifacts."""
from __future__ import annotations

import json

from scripts import candidate_memory_decay_v2 as cmd2


def test_decay_differs_by_catalyst_type():
    earnings = cmd2.base_decay("earnings", 5.0)
    ai_only = cmd2.base_decay("ai_report_only", 5.0)
    news = cmd2.base_decay("news", 5.0)
    # Higher λ = faster decay; ai_report_only λ=0.60 > news=0.45 > earnings=0.35
    assert ai_only < news < earnings


def test_stale_repeat_penalty_caps_at_50pct():
    assert cmd2.stale_repeat_penalty(0) == 0.0
    assert cmd2.stale_repeat_penalty(3) == 0.30
    assert cmd2.stale_repeat_penalty(20) == 0.50  # capped


def test_repeated_stale_candidate_is_quarantined():
    cand = {"id": "Q", "catalyst_type": "news",
            "days_since_last_fresh": 6.0, "raw_score": 0.7,
            "repeat_count_30d": 5,
            "last_catalyst_verification": "UNVERIFIED"}
    out = cmd2.evaluate_candidate(cand)
    assert out["quarantined"] is True
    assert out["state"] == "STALE_QUARANTINE"
    assert "STALE_REPEAT_QUARANTINE" in out["downgrade_reasons"]
    assert out["may_promote"] is False


def test_new_verified_catalyst_resets_decay():
    cand = {"id": "RESET", "catalyst_type": "filing",
            "days_since_last_fresh": 0.0, "raw_score": 0.8,
            "repeat_count_30d": 0,
            "last_catalyst_verification": "VERIFIED"}
    out = cmd2.evaluate_candidate(cand)
    assert out["may_promote"] is True
    assert out["base_decay"] == 1.0


def test_fallback_or_mock_does_not_reset_decay():
    for vstatus in ("FALLBACK", "MOCK", "UNVERIFIED"):
        cand = {"id": vstatus, "catalyst_type": "news",
                "days_since_last_fresh": 0.0, "raw_score": 0.9,
                "repeat_count_30d": 1,
                "last_catalyst_verification": vstatus}
        out = cmd2.evaluate_candidate(cand)
        assert out["may_promote"] is False


def test_ai_only_repeated_candidate_decays_faster():
    ai = cmd2.evaluate_candidate(
        {"id": "AI", "catalyst_type": "ai_report_only",
         "days_since_last_fresh": 3.0, "raw_score": 0.8,
         "repeat_count_30d": 1, "last_catalyst_verification": "FALLBACK"}
    )
    filing = cmd2.evaluate_candidate(
        {"id": "FIL", "catalyst_type": "filing",
         "days_since_last_fresh": 3.0, "raw_score": 0.8,
         "repeat_count_30d": 1, "last_catalyst_verification": "FALLBACK"}
    )
    assert ai["memory_adjusted_score"] < filing["memory_adjusted_score"]


def test_summaries_meet_targets_and_write(tmp_path):
    anti_path = tmp_path / "anti.json"
    memo_path = tmp_path / "memo.json"
    anti, memo = cmd2.write_summaries(anti_path=anti_path, memo_path=memo_path)
    assert anti_path.exists() and memo_path.exists()
    assert anti["anti_staleness_score"] >= 9.7
    assert memo["candidate_memory_decay_score"] >= 9.6
    on_disk_anti = json.loads(anti_path.read_text(encoding="utf-8"))
    on_disk_memo = json.loads(memo_path.read_text(encoding="utf-8"))
    assert on_disk_anti["quarantined_count"] >= 1
    assert on_disk_memo["quarantined_count"] >= 1


def test_summaries_carry_safety_invariants():
    anti, memo = cmd2.build_summaries()
    for s in (anti, memo):
        assert s["advisory_only"] is True
        assert s["broker_api_called"] is False
        assert s["ai_execution_count"] == 0
