from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from scripts.attention_proxy_engine import (
    AttentionProxyInput,
    build_attention_proxy_inputs_from_runtime,
    build_attention_proxy_report,
    build_attention_proxy_result,
)
from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report
from scripts.trend_engine import build_trend_report


REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_SNAPSHOT_LOG = REPO_ROOT / "tests" / "fixtures" / "system_snapshots_seed.jsonl"
FIXED_AS_OF = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)


def test_attention_proxy_complete_input_case() -> None:
    payload = AttentionProxyInput(
        signal_id="SIG_FULL_001",
        ticker="NVDA",
        text_signal="Nvidia raises AI demand guidance after fresh hyperscaler supply surprise",
        source_type="news",
        sentiment_score=0.82,
        novelty_score=0.79,
        engagement_count=12500,
        engagement_velocity=0.84,
        engagement_acceleration=0.46,
        source_credibility=0.86,
        content_modality="mixed",
        network_spread_proxy=0.77,
        trend_persistence_proxy=0.68,
        event_alignment_score=0.88,
        market_theme_alignment=0.9,
        time_since_first_observed_minutes=55,
        metadata={
            "input_mode": "external_augmented",
            "measured_fields": [
                "engagement_count",
                "engagement_velocity",
                "engagement_acceleration",
                "network_spread_proxy",
                "trend_persistence_proxy",
            ],
        },
    )

    result = build_attention_proxy_result(payload)

    assert result.overall_attention_proxy_score > 0.7
    assert result.attention_capture_score > 0.7
    assert result.capital_relevance_score > 0.75
    assert result.proxy_confidence > 0.75
    assert result.confidence_band == "HIGH"
    assert result.proxy_advisory == "possible ignition candidate, monitor for validation"


def test_attention_proxy_missing_input_case_degrades_confidence() -> None:
    payload = AttentionProxyInput(
        signal_id="SIG_SPARSE_001",
        ticker="ABC",
        source_type="internal",
    )

    result = build_attention_proxy_result(payload)

    assert result.proxy_confidence < 0.55
    assert result.confidence_band == "LOW"
    assert "engagement_velocity" in result.missing_inputs
    assert "text_signal" in result.missing_inputs
    assert "trend_persistence_proxy" in result.missing_inputs
    assert result.recommended_interpretation.endswith(
        "Treat this as a monitoring input before validation, tagging, or action."
    )


def test_attention_proxy_high_acceleration_low_persistence_case() -> None:
    payload = AttentionProxyInput(
        signal_id="SIG_ACCEL_001",
        ticker="MEME",
        text_signal="Unexpected product leak triggers fast retail chatter around demand spike",
        source_type="social",
        sentiment_score=0.65,
        novelty_score=0.88,
        engagement_count=2100,
        engagement_velocity=0.79,
        engagement_acceleration=0.83,
        source_credibility=0.46,
        content_modality="video",
        network_spread_proxy=0.82,
        trend_persistence_proxy=0.12,
        event_alignment_score=0.58,
        market_theme_alignment=0.56,
        time_since_first_observed_minutes=30,
        metadata={
            "input_mode": "external_augmented",
            "measured_fields": [
                "engagement_count",
                "engagement_velocity",
                "engagement_acceleration",
                "network_spread_proxy",
                "trend_persistence_proxy",
            ],
        },
    )

    result = build_attention_proxy_result(payload)

    assert result.attention_capture_score > result.persistence_score
    assert result.persistence_score < 0.45
    assert result.novelty_score > 0.7
    assert result.proxy_advisory == "high novelty, low persistence"


def test_attention_proxy_strong_narrative_and_capital_relevance_case() -> None:
    payload = AttentionProxyInput(
        signal_id="SIG_NARR_001",
        ticker="SPY",
        text_signal="ETF approval filing update raises repricing odds across rates and equity flows",
        source_type="market",
        sentiment_score=0.58,
        novelty_score=0.72,
        engagement_count=4700,
        engagement_velocity=0.69,
        engagement_acceleration=0.24,
        source_credibility=0.84,
        content_modality="text",
        network_spread_proxy=0.67,
        trend_persistence_proxy=0.73,
        event_alignment_score=0.91,
        market_theme_alignment=0.89,
        time_since_first_observed_minutes=180,
        metadata={
            "input_mode": "external_augmented",
            "measured_fields": [
                "engagement_count",
                "engagement_velocity",
                "engagement_acceleration",
                "network_spread_proxy",
                "trend_persistence_proxy",
            ],
        },
    )

    result = build_attention_proxy_result(payload)

    assert result.narrative_cohesion_score > 0.7
    assert result.persistence_score > 0.6
    assert result.capital_relevance_score > 0.75
    assert result.overall_attention_proxy_score > 0.68
    assert result.proxy_advisory in {
        "narrative traction forming",
        "possible ignition candidate, monitor for validation",
    }


def test_attention_proxy_high_saturation_high_decay_case() -> None:
    payload = AttentionProxyInput(
        signal_id="SIG_DECAY_001",
        ticker="QQQ",
        text_signal="Same earnings beat narrative recycled again as attention stalls and pricing feels crowded",
        source_type="social",
        sentiment_score=0.12,
        novelty_score=0.22,
        engagement_count=38000,
        engagement_velocity=0.43,
        engagement_acceleration=-0.78,
        source_credibility=0.44,
        content_modality="text",
        network_spread_proxy=0.54,
        trend_persistence_proxy=0.9,
        event_alignment_score=0.48,
        market_theme_alignment=0.44,
        time_since_first_observed_minutes=9800,
        metadata={
            "input_mode": "external_augmented",
            "measured_fields": [
                "engagement_count",
                "engagement_velocity",
                "engagement_acceleration",
                "network_spread_proxy",
                "trend_persistence_proxy",
            ],
        },
    )

    result = build_attention_proxy_result(payload)

    assert result.saturation_risk_score > 0.7
    assert result.decay_risk_score > 0.7
    assert result.narrative_state in {"SATURATED", "EXHAUSTING"}
    assert result.proxy_advisory == "transient spike risk"


def test_attention_proxy_output_is_deterministic() -> None:
    payload = AttentionProxyInput(
        signal_id="SIG_DET_001",
        ticker="TLT",
        text_signal="Treasury narrative heats up after rate repricing surprise",
        source_type="news",
        novelty_score=0.63,
        engagement_velocity=0.52,
        engagement_acceleration=0.11,
        source_credibility=0.77,
        content_modality="text",
        network_spread_proxy=0.59,
        trend_persistence_proxy=0.51,
        event_alignment_score=0.8,
        market_theme_alignment=0.78,
        time_since_first_observed_minutes=240,
        metadata={"input_mode": "direct_input"},
    )

    first = build_attention_proxy_result(payload).to_dict()
    second = build_attention_proxy_result(payload).to_dict()

    assert first == second


def test_attention_proxy_schema_integrity() -> None:
    payload = AttentionProxyInput(
        signal_id="SIG_SCHEMA_001",
        ticker="ZIM",
        source_type="market",
        novelty_score=0.5,
        engagement_velocity=0.45,
        engagement_acceleration=0.0,
        content_modality="text",
        event_alignment_score=0.52,
        market_theme_alignment=0.56,
        metadata={"input_mode": "direct_input"},
    )

    result = build_attention_proxy_result(payload).to_dict()

    assert {
        "attention_capture_score",
        "narrative_cohesion_score",
        "spreadability_score",
        "persistence_score",
        "novelty_score",
        "saturation_risk_score",
        "decay_risk_score",
        "capital_relevance_score",
        "overall_attention_proxy_score",
        "attention_state",
        "narrative_state",
        "proxy_confidence",
        "confidence_band",
        "proxy_advisory",
        "reasons",
        "risks",
        "missing_inputs",
        "governance_notes",
    }.issubset(result)


def test_attention_proxy_offline_inferred_caps_confidence_and_language() -> None:
    payload = AttentionProxyInput(
        signal_id="SIG_OFFLINE_001",
        ticker="META",
        text_signal="Fresh platform policy filing revives ad pricing narrative and cross-asset repricing chatter",
        source_type="news",
        sentiment_score=0.71,
        novelty_score=0.78,
        engagement_count=8200,
        engagement_velocity=0.76,
        engagement_acceleration=0.41,
        source_credibility=0.82,
        content_modality="text",
        network_spread_proxy=0.69,
        trend_persistence_proxy=0.64,
        event_alignment_score=0.88,
        market_theme_alignment=0.9,
        time_since_first_observed_minutes=90,
        metadata={
            "input_mode": "offline_inferred",
            "inferred_fields": [
                "engagement_velocity",
                "engagement_acceleration",
                "network_spread_proxy",
                "event_alignment_score",
                "market_theme_alignment",
                "novelty_score",
            ],
        },
    )

    result = build_attention_proxy_result(payload)

    assert result.proxy_confidence < 0.55
    assert result.confidence_band == "LOW"
    assert result.attention_state == "EMERGING"
    assert result.proxy_advisory == "attention-bearing but unvalidated"


def test_attention_proxy_runtime_inputs_do_not_backfill_state_derived_fields() -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report()
    )
    trend_report = build_trend_report(log_path=SEED_SNAPSHOT_LOG, write_runtime=False)

    inputs = build_attention_proxy_inputs_from_runtime(
        runtime_state=runtime_state,
        trend_report=trend_report,
        as_of=FIXED_AS_OF,
    )

    assert inputs
    for item in inputs:
        assert item.engagement_velocity is None
        assert item.engagement_acceleration is None
        assert item.network_spread_proxy is None
        assert item.event_alignment_score is None
        assert item.market_theme_alignment is None
        assert item.novelty_score is None
        assert item.metadata["state_overlap_fields"] == []


def test_attention_proxy_runtime_report_uses_seeded_demo_honestly() -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report()
    )
    trend_report = build_trend_report(log_path=SEED_SNAPSHOT_LOG, write_runtime=False)

    report = build_attention_proxy_report(
        runtime_state=runtime_state,
        trend_report=trend_report,
        write_runtime=False,
        as_of=FIXED_AS_OF,
    )

    assert report["scored_signal_count"] == len(runtime_state["per_signal_attribution"])
    assert report["attention_proxy_state"] in {"LOW_VISIBILITY", "EMERGING"}
    assert report["attention_proxy_confidence"] == "LOW"
    assert report["input_mode_counts"].get("seeded_demo", 0) >= 1
    assert report["observability"]["telemetry_backed_signal_count"] == 0
    assert report["observability"]["state_overlap_signal_count"] == 0
    assert report["top_attention_candidates"]
    assert "not a virality predictor" in report["governance_notes"][0].lower()


def test_run_diagnostics_pipeline_surfaces_attention_proxy_summary() -> None:
    payload = run_diagnostics_pipeline(write_runtime=False)

    assert "attention_proxy" in payload
    assert payload["attention_proxy_state"] == payload["attention_proxy"]["attention_proxy_state"]
    assert payload["attention_proxy_score"] == payload["attention_proxy"]["attention_proxy_score"]
    assert (
        payload["attention_proxy_confidence"]
        == payload["attention_proxy"]["attention_proxy_confidence"]
    )
    assert payload["narrative_proxy_advisory"] == payload["attention_proxy"]["narrative_proxy_advisory"]
