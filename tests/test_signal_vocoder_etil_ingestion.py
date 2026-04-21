from __future__ import annotations

import json
from datetime import datetime, timezone

import scripts.run_diagnostics_pipeline as run_diagnostics_pipeline_module
from scripts.signal_vocoder import (
    build_runtime_vocoder_artifact,
    load_runtime_vocoder_etil_signals,
)


NOW = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)


def _sample_runtime_state() -> dict:
    return {
        "per_signal_attribution": [
            {
                "signal_id": "SIG_RTX",
                "ticker": "RTX",
                "signal_state": "WATCHLIST",
                "status": "WATCHLIST",
                "entry_type": "UNKNOWN",
                "blocker_attribution": "GSCE_PHASE_LOCK",
                "priority_score": 0.71,
                "ce_score": 0.71,
                "watchlist_tier": "PROMOTABLE",
                "candidate_conversion_state": "PROMOTABLE_WATCHLIST",
                "pre_entry_state": "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
            },
            {
                "signal_id": "SIG_ZIM",
                "ticker": "ZIM",
                "signal_state": "WATCHLIST",
                "status": "WATCHLIST",
                "entry_type": "UNKNOWN",
                "blocker_attribution": "GSCE_PHASE_LOCK",
                "priority_score": 0.64,
                "ce_score": 0.64,
                "watchlist_tier": "PROMOTABLE",
                "candidate_conversion_state": "PROMOTABLE_WATCHLIST",
                "pre_entry_state": "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
            },
        ],
        "execution_policy": {"policy_state": "RESTRICTED"},
        "active_blockers": ["GSCE_PHASE_LOCK"],
        "scm_review": {"scm_state": "LOW_CONVERSION"},
        "simulation_context": {"scenario": "LIVE"},
    }


def _sample_health_report() -> dict:
    return {
        "simulation_mode": "LIVE",
        "policy": {"policy_state": "RESTRICTED"},
        "active_blockers": ["GSCE_PHASE_LOCK"],
        "scm": {"scm_state": "LOW_CONVERSION"},
        "scorecard": {"execution_readiness": {"score": 4}},
        "system_readiness_state": "DO_NOT_DEPLOY",
        "decision_review_state": "NONE",
        "what_should_i_do_next": "CLEAR_GSCE_PHASE_LOCK_FOR: RTX, ZIM | DO NOT ADD NEW RISK",
    }


def _sample_etil_payloads() -> list[dict]:
    return [
        {
            "source": "polymarket",
            "signal_type": "ANCHOR",
            "content": {
                "condition_id": "RTX-Q2",
                "question": "RTX rebound looks inevitable into earnings",
                "outcome_prices": {"yes": 0.74, "no": 0.26},
                "volume": 84000,
                "end_date": "2026-04-22T14:00:00+00:00",
            },
            "reliability_prior": 0.88,
            "timestamp": "2026-04-21T10:15:00+00:00",
            "freshness_remaining": 0.92,
            "raw_output": {
                "condition_id": "RTX-Q2",
                "question": "RTX rebound looks inevitable into earnings",
                "outcome_prices": {"yes": 0.74, "no": 0.26},
                "volume": 84000,
                "end_date": "2026-04-22T14:00:00+00:00",
            },
        },
        {
            "source": "rss",
            "signal_type": "SYSTEM",
            "content": {
                "title": "Analysts upgrade RTX ahead of earnings",
                "summary": "Bullish defense rebound narrative persists after backlog strength",
                "published": "2026-04-21T09:00:00+00:00",
                "source": "Reuters",
                "link": "https://example.com/rtx-upgrade",
            },
            "reliability_prior": 0.6,
            "timestamp": "2026-04-21T09:30:00+00:00",
            "freshness_remaining": 0.8,
            "raw_output": {
                "title": "Analysts upgrade RTX ahead of earnings",
                "summary": "Bullish defense rebound narrative persists after backlog strength",
                "published": "2026-04-21T09:00:00+00:00",
                "source": "Reuters",
                "link": "https://example.com/rtx-upgrade",
            },
        },
        {
            "source": "reddit",
            "signal_type": "SYSTEM",
            "content": {
                "subreddit": "stocks",
                "title": "$RTX rebound looks real, squeeze setup building",
                "score": 420,
                "num_comments": 88,
                "created_utc": "2026-04-21T11:15:00+00:00",
            },
            "reliability_prior": 0.45,
            "timestamp": "2026-04-21T11:15:00+00:00",
            "freshness_remaining": 0.95,
            "raw_output": {
                "subreddit": "stocks",
                "title": "$RTX rebound looks real, squeeze setup building",
                "score": 420,
                "num_comments": 88,
                "created_utc": "2026-04-21T11:15:00+00:00",
            },
        },
    ]


def test_load_runtime_vocoder_etil_signals_canonicalises_supported_sources() -> None:
    payload_path = _write_fixture_payload(_sample_etil_payloads())

    signals = load_runtime_vocoder_etil_signals(path=payload_path, now=NOW)

    assert [signal["source"] for signal in signals] == [
        "polymarket",
        "feedparser",
        "praw_reddit",
    ]
    assert signals[0]["signal_type"] == "ANCHOR"
    assert signals[1]["content"]["title"] == "Analysts upgrade RTX ahead of earnings"
    assert signals[2]["content"]["subreddit"] == "stocks"


def test_build_runtime_vocoder_artifact_uses_etil_signals_when_available() -> None:
    artifact = build_runtime_vocoder_artifact(
        runtime_state=_sample_runtime_state(),
        health_report=_sample_health_report(),
        etil_signals=_sample_etil_payloads(),
        open_positions=[],
        now=NOW,
    )

    assert artifact["source_mode"] == "LIVE_ETIL"
    assert artifact["entity_count"] == 2
    assert artifact["entities"][0]["entity_id"] == "RTX"
    assert artifact["entities"][0]["input_origin"] == "live_etil"
    assert artifact["entities"][0]["input_payload_count"] == 3
    assert artifact["entities"][1]["entity_id"] == "ZIM"
    assert artifact["entities"][1]["input_origin"] == "synthetic_runtime_fallback"


def test_run_diagnostics_pipeline_prefers_loaded_etil_signals(monkeypatch) -> None:
    persisted: list[dict] = []

    monkeypatch.setattr(
        run_diagnostics_pipeline_module,
        "build_signal_conversion_report",
        lambda **kwargs: {"simulation_context": {"scenario": "LIVE"}},
    )
    monkeypatch.setattr(
        run_diagnostics_pipeline_module,
        "build_runtime_state_from_scm_report",
        lambda scm_report: _sample_runtime_state(),
    )
    monkeypatch.setattr(
        run_diagnostics_pipeline_module,
        "persist_current_runtime_state",
        lambda state: None,
    )
    monkeypatch.setattr(
        run_diagnostics_pipeline_module,
        "build_action_report",
        lambda runtime_state, write_runtime: {"actions": [], "summary_by_action": {}},
    )
    monkeypatch.setattr(
        run_diagnostics_pipeline_module,
        "build_blocker_cost_report",
        lambda runtime_state, write_runtime: {"friction_band": "HIGH_FRICTION"},
    )
    monkeypatch.setattr(
        run_diagnostics_pipeline_module,
        "log_snapshot",
        lambda path, runtime_state: {"timestamp": NOW.isoformat()},
    )
    monkeypatch.setattr(
        run_diagnostics_pipeline_module,
        "build_trend_report",
        lambda **kwargs: {"snapshot_count": 1, "scenario_scope": "LIVE"},
    )
    monkeypatch.setattr(
        run_diagnostics_pipeline_module,
        "build_pipeline_health_report",
        lambda **kwargs: _sample_health_report(),
    )
    monkeypatch.setattr(
        run_diagnostics_pipeline_module,
        "persist_runtime_vocoder_artifact",
        lambda artifact: persisted.append(artifact),
    )

    # Replace the loader monkeypatch with a deterministic fixture payload.
    monkeypatch.setattr(
        run_diagnostics_pipeline_module,
        "load_runtime_vocoder_etil_signals",
        lambda: load_runtime_vocoder_etil_signals_from_fixture(),
    )

    payload = run_diagnostics_pipeline_module.run_diagnostics_pipeline(write_runtime=True)

    assert payload["system_readiness_state"] == "DO_NOT_DEPLOY"
    assert len(persisted) == 1
    assert persisted[0]["source_mode"] == "LIVE_ETIL"
    assert persisted[0]["entities"][0]["entity_id"] == "RTX"
    assert persisted[0]["entities"][0]["input_origin"] == "live_etil"


def load_runtime_vocoder_etil_signals_from_fixture() -> list[dict]:
    return load_runtime_vocoder_etil_signals_from_payload(_sample_etil_payloads())


def load_runtime_vocoder_etil_signals_from_payload(payload: list[dict]) -> list[dict]:
    return load_runtime_vocoder_etil_signals(path=_write_fixture_payload(payload), now=NOW)


def _write_fixture_payload(payload: list[dict]):
    from pathlib import Path
    import tempfile

    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    handle.write(json.dumps(payload, indent=2))
    handle.close()
    return Path(handle.name)
