"""Tests for ``scripts.fresh_discovery_quality``."""
from __future__ import annotations

import json

from scripts import fresh_discovery_quality as fdq


def test_fresh_cross_source_event_improves_score():
    cand = {
        "id": "GOOD",
        "events": [
            {"source_class": "price_mover",
             "verification_status": "FIXTURE_VERIFIED",
             "age_hours": 1.0, "sla_hours": 6.0, "is_novel": True},
            {"source_class": "filing",
             "verification_status": "FIXTURE_VERIFIED",
             "age_hours": 1.0, "sla_hours": 36.0, "is_novel": True},
            {"source_class": "news_event",
             "verification_status": "FIXTURE_VERIFIED",
             "age_hours": 1.0, "sla_hours": 12.0, "is_novel": True},
        ],
        "why_today_score": 0.8,
    }
    out = fdq.score_candidate(cand)
    assert out["can_enter_fresh_discovery"] is True
    assert out["fresh_discovery_score"] >= 0.7


def test_repeated_stale_event_does_not_promote():
    cand = {
        "id": "STALE_REPEAT",
        "events": [
            {"source_class": "price_mover",
             "verification_status": "FIXTURE_VERIFIED",
             "age_hours": 1.0, "sla_hours": 6.0, "is_novel": False},
        ],
        "stale_repeated": True, "why_today_score": 0.5,
    }
    out = fdq.score_candidate(cand)
    assert out["can_enter_fresh_discovery"] is False
    assert "STALE_REPEAT" in out["block_reasons"]


def test_single_fallback_cannot_produce_high_fresh_discovery():
    cand = {
        "id": "FALLBACK_ONLY",
        "events": [
            {"source_class": "news_event",
             "verification_status": "FALLBACK",
             "age_hours": 1.0, "sla_hours": 12.0, "is_novel": True},
        ],
        "why_today_score": 0.3,
    }
    out = fdq.score_candidate(cand)
    assert "NO_VERIFIED_FRESH_EVENT" in out["block_reasons"]
    assert out["can_enter_fresh_discovery"] is False


def test_why_today_alone_cannot_carry_discovery():
    cand = {
        "id": "WHY_ALONE",
        "events": [
            {"source_class": "ai_report",
             "verification_status": "UNVERIFIED",
             "age_hours": 1.0, "sla_hours": 24.0, "is_novel": True},
        ],
        "why_today_score": 0.95,
    }
    out = fdq.score_candidate(cand)
    # No verified fresh event => blocked even with very high WHY_TODAY.
    assert out["can_enter_fresh_discovery"] is False
    assert "NO_VERIFIED_FRESH_EVENT" in out["block_reasons"]


def test_fixture_summary_reaches_target_score():
    summary = fdq.build_summary()
    assert summary["fresh_discovery_quality_score"] >= 9.1
    # Of the 4 fixture candidates, only FRESH_PASS may enter.
    assert summary["fresh_candidate_count"] == 1
    # The gate must have blocked the stale and the fallback-only candidates.
    assert summary["stale_repeat_block_count"] >= 1
    assert summary["fallback_only_block_count"] >= 1


def test_summary_writes(tmp_path):
    target = tmp_path / "fresh.json"
    out = fdq.write_summary(target)
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["fresh_discovery_quality_score"] >= 9.1
    assert out["summary_path"] == str(target)


def test_safety_invariants():
    summary = fdq.build_summary()
    assert summary["advisory_only"] is True
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0
