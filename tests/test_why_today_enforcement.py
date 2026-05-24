"""Tests for ``scripts.why_today_enforcement``."""
from __future__ import annotations

import json

from scripts import why_today_enforcement as wte


def test_no_fresh_catalyst_fails_why_today():
    cand = {"id": "X",
            "verification_status": "FALLBACK",
            "age_hours": 1.0, "sla_hours": 12.0,
            "price_mover_intensity": 0.0, "narrative_velocity": 0.0,
            "filing_materiality_score": 0.0, "source_diversity": 0.0,
            "asset_specific": False, "event_specific": False,
            "timestamp_specific": False, "invalidation_specific": False,
            "cross_source_confirmation": 0.0,
            "evidence_anchors": [],
            "advisory_only": True}
    out = wte.evaluate_candidate(cand)
    assert out["fresh_catalyst_score"] == 0.0
    assert out["can_promote_to_human_review"] is False
    assert "WHY_TODAY_WEAK" in out["downgrade_reasons"]


def test_fresh_verified_filing_improves_why_today():
    cand = {"id": "F",
            "verification_status": "VERIFIED",
            "age_hours": 1.0, "sla_hours": 36.0,
            "price_mover_intensity": 0.6, "narrative_velocity": 0.5,
            "filing_materiality_score": 0.8, "source_diversity": 0.5,
            "asset_specific": True, "event_specific": True,
            "timestamp_specific": True, "invalidation_specific": True,
            "cross_source_confirmation": 0.6,
            "evidence_anchors": [
                {"provider": "sec_edgar",
                 "timestamp_utc": "2026-05-24T09:00:00Z",
                 "claim": "10-Q strong revenue",
                 "verification_status": "VERIFIED"}
            ],
            "advisory_only": True}
    out = wte.evaluate_candidate(cand)
    assert out["why_today_score"] >= wte.WHY_TODAY_HARD_GATE
    assert out["can_promote_to_human_review"] is True


def test_price_only_without_evidence_is_capped():
    cand = {"id": "P",
            "verification_status": "UNVERIFIED",
            "age_hours": 1.0, "sla_hours": 6.0,
            "price_mover_intensity": 1.0, "narrative_velocity": 0.0,
            "filing_materiality_score": 0.0, "source_diversity": 0.0,
            "asset_specific": True, "event_specific": False,
            "timestamp_specific": True, "invalidation_specific": False,
            "cross_source_confirmation": 0.0,
            "evidence_anchors": [],
            "advisory_only": True}
    out = wte.evaluate_candidate(cand)
    # UNVERIFIED + price-only cannot reach the high threshold even if
    # the formula were generous; score must stay capped.
    assert out["why_today_score"] < wte.WHY_TODAY_HIGH_THRESHOLD


def test_high_score_requires_evidence_anchor():
    cand = {"id": "H",
            "verification_status": "FIXTURE_VERIFIED",
            "age_hours": 1.0, "sla_hours": 12.0,
            "price_mover_intensity": 0.9, "narrative_velocity": 0.9,
            "filing_materiality_score": 0.9, "source_diversity": 0.9,
            "asset_specific": True, "event_specific": True,
            "timestamp_specific": True, "invalidation_specific": True,
            "cross_source_confirmation": 0.9,
            "evidence_anchors": [],
            "advisory_only": True}
    out = wte.evaluate_candidate(cand)
    assert out["high_score_evidence_anchor_required"] is True
    assert out["why_today_score"] < wte.WHY_TODAY_HIGH_THRESHOLD
    assert "WHY_TODAY_HIGH_REQUIRES_EVIDENCE" in out["downgrade_reasons"]


def test_fallback_mock_cannot_score_high():
    for vstatus in ("FALLBACK", "MOCK"):
        cand = {"id": vstatus,
                "verification_status": vstatus,
                "age_hours": 1.0, "sla_hours": 12.0,
                "price_mover_intensity": 1.0, "narrative_velocity": 1.0,
                "filing_materiality_score": 1.0, "source_diversity": 1.0,
                "asset_specific": True, "event_specific": True,
                "timestamp_specific": True, "invalidation_specific": True,
                "cross_source_confirmation": 1.0,
                "evidence_anchors": [],
                "advisory_only": True}
        out = wte.evaluate_candidate(cand)
        assert out["fresh_catalyst_score"] == 0.0
        assert out["why_today_score"] < wte.WHY_TODAY_HIGH_THRESHOLD


def test_evidence_anchor_validity():
    valid = {"provider": "x", "timestamp_utc": "y",
             "claim": "z", "verification_status": "VERIFIED"}
    assert wte.evidence_anchor_valid(valid) is True
    invalid = {"provider": "x", "timestamp_utc": "",
               "claim": "z", "verification_status": "VERIFIED"}
    assert wte.evidence_anchor_valid(invalid) is False


def test_weak_why_today_blocks_promotion():
    cand = {"id": "W",
            "verification_status": "STALE",
            "age_hours": 24.0, "sla_hours": 6.0,
            "price_mover_intensity": 0.2, "narrative_velocity": 0.0,
            "filing_materiality_score": 0.0, "source_diversity": 0.0,
            "asset_specific": False, "event_specific": False,
            "timestamp_specific": False, "invalidation_specific": False,
            "cross_source_confirmation": 0.0,
            "evidence_anchors": [],
            "advisory_only": True}
    out = wte.evaluate_candidate(cand)
    assert out["can_promote_to_human_review"] is False


def test_summary_reaches_target_in_fixture_mode():
    summary = wte.build_summary()
    assert summary["why_today_enforcement_score"] >= 9.6
    assert summary["promotable_count"] >= 1
    assert summary["weak_blocked_count"] >= 1


def test_summary_writes_and_safety_invariants(tmp_path):
    target = tmp_path / "wty.json"
    out = wte.write_summary(target)
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["why_today_enforcement_score"] >= 9.6
    assert on_disk["advisory_only"] is True
    assert on_disk["broker_api_called"] is False
    assert on_disk["ai_execution_count"] == 0
