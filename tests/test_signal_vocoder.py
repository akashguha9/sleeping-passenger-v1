from __future__ import annotations

from datetime import datetime, timezone

from scripts.signal_vocoder import (
    build_signal_vocoder_output,
    extract_band,
    extract_signal_bands,
    normalise_vocoder_inputs,
    score_artist_modes,
)


NOW = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)


def _sample_tool_payloads() -> list[dict]:
    return [
        {
            "tool": "polymarket",
            "timestamp": "2026-04-21T10:15:00+00:00",
            "raw_output": {
                "condition_id": "RTX-Q2",
                "question": "RTX rebound looks inevitable into earnings",
                "outcome_prices": {"yes": 0.74, "no": 0.26},
                "volume": 84000,
                "end_date": "2026-04-22T14:00:00+00:00",
            },
        },
        {
            "tool": "market_data",
            "timestamp": "2026-04-21T11:40:00+00:00",
            "raw_output": {
                "symbol": "RTX",
                "price": 131.5,
                "price_change_pct": 0.08,
                "velocity_z": 1.6,
                "volume_ratio": 1.8,
                "volatility": 0.14,
                "event_time": "2026-04-22T14:00:00+00:00",
                "implied_probability": 0.69,
            },
        },
        {
            "tool": "reddit",
            "timestamp": "2026-04-21T11:15:00+00:00",
            "raw_output": {
                "subreddit": "stocks",
                "title": "$RTX rebound looks real, squeeze setup building",
                "score": 420,
                "num_comments": 88,
            },
        },
        {
            "tool": "rss",
            "timestamp": "2026-04-21T09:30:00+00:00",
            "raw_output": {
                "title": "Analysts upgrade RTX ahead of earnings",
                "summary": "Bullish defense rebound narrative persists after backlog strength",
                "published": "2026-04-21T09:00:00+00:00",
                "source": "Reuters",
                "link": "https://example.com/rtx-upgrade",
            },
        },
    ]


def _sample_runtime_state() -> dict:
    return {
        "execution_policy": {"policy_state": "RESTRICTED"},
        "active_blockers": ["GSCE_PHASE_LOCK"],
        "scm_review": {"scm_state": "LOW_CONVERSION"},
    }


def _sample_health_report() -> dict:
    return {
        "policy": {"policy_state": "RESTRICTED"},
        "active_blockers": ["GSCE_PHASE_LOCK"],
        "scm": {"scm_state": "LOW_CONVERSION"},
        "scorecard": {"execution_readiness": {"score": 4}},
    }


def test_normalise_vocoder_inputs_canonicalises_tool_aliases() -> None:
    signals = normalise_vocoder_inputs(_sample_tool_payloads(), now=NOW)

    assert [signal["source"] for signal in signals] == [
        "polymarket",
        "market_data",
        "praw_reddit",
        "feedparser",
    ]
    assert signals[1]["content"]["symbol"] == "RTX"
    assert signals[2]["content"]["subreddit"] == "stocks"


def test_extract_band_interface_and_carrier_alignment() -> None:
    signals = normalise_vocoder_inputs(_sample_tool_payloads(), now=NOW)
    bands, carrier = extract_signal_bands(
        signals,
        runtime_state=_sample_runtime_state(),
        health_report=_sample_health_report(),
        entity_id="RTX",
        now=NOW,
    )

    assert set(bands) == {
        "sentiment",
        "velocity",
        "divergence",
        "entity",
        "confidence",
        "timing",
        "narrative_structure",
        "market_translation",
    }
    assert extract_band("sentiment", signals, now=NOW).band == "sentiment"
    assert extract_band("market_translation", signals, now=NOW, carrier=carrier).band == "market_translation"
    assert carrier.symbol == "RTX"
    assert carrier.policy_state == "RESTRICTED"
    assert carrier.active_blockers == ["GSCE_PHASE_LOCK"]
    assert carrier.execution_readiness == 0.4
    assert carrier.anchor_probability is not None
    assert carrier.anchor_probability >= 0.69
    assert carrier.carrier_score > 0.0


def test_build_signal_vocoder_output_emits_schema_versioned_compressed_signal() -> None:
    signals = normalise_vocoder_inputs(_sample_tool_payloads(), now=NOW)
    bands, carrier = extract_signal_bands(
        signals,
        runtime_state=_sample_runtime_state(),
        health_report=_sample_health_report(),
        entity_id="RTX",
        now=NOW,
    )
    output = build_signal_vocoder_output(
        signals,
        runtime_state=_sample_runtime_state(),
        health_report=_sample_health_report(),
        entity_id="RTX",
        now=NOW,
    )

    assert output["schema_version"] == "v1"
    assert output["generated_at"] == NOW.isoformat()
    assert output["entity_id"] == "RTX"
    assert output["dominant_mode"] == "HBFS"
    assert output["deployment_posture"] == "BLOCKED"
    assert output["decision_signal"].startswith("BLOCKED_")
    assert len(output["mode_scores"]) == 5
    assert [item["mode"] for item in output["mode_scores"]] == [
        item.mode for item in score_artist_modes(bands, carrier)
    ]
