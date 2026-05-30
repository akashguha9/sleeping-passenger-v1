"""Tests for the operator-readiness reliability block + frontend truth (WS B/F)."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import external_evidence_operator_readiness as eor

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CARD = _REPO_ROOT / "frontend" / "src" / "components" / "ExternalEvidenceReliabilityCard.tsx"

# Execution-instruction phrases that must never appear in a positive context.
_FORBIDDEN = (
    "place order",
    "place_order",
    "submit order",
    "submit_order",
    "execute trade",
    "execute_trade",
    "trade now",
    "auto-trade",
    "broker order",
    "permission to trade",
)


def _available_bundle(**over):
    bundle = {
        "external_evidence_status": "ACCEPTED_EVIDENCE_ONLY",
        "external_evidence_enabled": True,
        "external_evidence_accepted_count": 2,
        "external_evidence_score_delta_raw_uncalibrated": 0.30,
        "external_evidence_score_delta_paper_calibrated": 0.12,
        "external_evidence_calibration": {
            "enabled": True,
            "applied_to_score_delta": True,
            "calibrated_items_count": 2,
            "cold_start_items_count": 1,
            "mature_items_count": 1,
        },
    }
    bundle.update(over)
    return bundle


def _buckets():
    return [
        {
            "bucket_id": "kronos|FORECAST|WATCH|MID", "source_name": "kronos",
            "sample_count": 60, "advisory_weight": 0.4, "help_rate": 0.7,
            "harm_rate": 0.05, "false_confidence_rate": 0.05,
        },
    ]


def test_reliability_block_contains_paper_only() -> None:
    block = eor.build_external_evidence_operator_readiness(
        _available_bundle(), calibration_buckets=_buckets()
    )
    text = eor.render_external_evidence_operator_readiness_block(block)
    assert "PAPER ONLY" in text
    assert block["mode"] == "PAPER_ONLY"


def test_reliability_block_contains_real_money_prohibited() -> None:
    block = eor.build_external_evidence_operator_readiness(_available_bundle())
    text = eor.render_external_evidence_operator_readiness_block(block)
    assert "Real-money sizing: PROHIBITED" in text
    assert block["real_money_sizing_impact"] == "PROHIBITED"
    assert block["real_money_weight_allowed"] is False


def test_reliability_block_contains_fake_confidence_risk() -> None:
    block = eor.build_external_evidence_operator_readiness(
        _available_bundle(), calibration_buckets=_buckets()
    )
    text = eor.render_external_evidence_operator_readiness_block(block)
    assert "false-confidence risk" in text.lower()
    # The risk label must be one of the known fake-confidence labels.
    assert block["biggest_false_confidence_risk"] in {
        "COLD_START_UNKNOWN",
        "LOW_FAKE_CONFIDENCE_RISK",
        "MODERATE_FAKE_CONFIDENCE_RISK",
        "HIGH_FAKE_CONFIDENCE_RISK",
    }


def test_reliability_block_no_execution_language() -> None:
    block = eor.build_external_evidence_operator_readiness(
        _available_bundle(), calibration_buckets=_buckets()
    )
    text = eor.render_external_evidence_operator_readiness_block(block).lower()
    for phrase in _FORBIDDEN:
        assert phrase not in text, f"forbidden execution phrase in block: {phrase!r}"
    # Safety posture is explicit.
    assert "veto override: impossible" in text
    assert "human review: required" in text


def test_reliability_block_honest_when_disabled() -> None:
    block = eor.build_external_evidence_operator_readiness(
        {"external_evidence_status": "DISABLED", "external_evidence_enabled": False}
    )
    text = eor.render_external_evidence_operator_readiness_block(block)
    assert block["data_available"] is False
    assert "PAPER ONLY" in text
    assert "PROHIBITED" in text
    # No fake live status.
    assert "LIVE_VERIFIED" not in text


def test_reliability_block_carries_safety_stamps() -> None:
    block = eor.build_external_evidence_operator_readiness(_available_bundle())
    assert block["advisory_status"] == "ADVISORY_ONLY"
    assert block["execution_gate"] == "LOCKED"
    assert block["broker_api_called"] is False
    assert block["ai_execution_count"] == 0
    assert block["human_execution_required"] is True


def test_frontend_page_mount_or_truthful_not_mounted() -> None:
    """The reliability card must EITHER be mounted by a page/component OR carry a
    truthful, explicit not-mounted note (Workstream F honesty rule)."""
    assert _CARD.is_file(), "ExternalEvidenceReliabilityCard.tsx must exist"
    card_text = _CARD.read_text(encoding="utf-8")

    app_dir = _REPO_ROOT / "frontend" / "src"
    mounted = False
    for path in app_dir.rglob("*.tsx"):
        if path == _CARD or path.name.endswith(".spec.tsx"):
            continue
        if "ExternalEvidenceReliabilityCard" in path.read_text(encoding="utf-8"):
            mounted = True
            break

    if mounted:
        return  # cleanly mounted — acceptable

    # Not mounted: the component must say so truthfully, and not pretend to be
    # live.  No fake data route.
    upper = card_text.upper()
    assert "NOT MOUNTED" in upper, (
        "card is not mounted and lacks a truthful NOT MOUNTED note"
    )
    assert "disabled by default" in card_text.lower()
    # Must still carry the paper-only / no-execution safety posture.
    assert "Real-money sizing prohibited" in card_text
    assert "Human review required" in card_text
