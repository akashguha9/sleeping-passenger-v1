from __future__ import annotations

from datetime import datetime, timezone

import scripts.run_diagnostics_pipeline as run_diagnostics_pipeline_module
from scripts.signal_vocoder import build_runtime_vocoder_artifact


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
                "signal_id": "SIG_UNG",
                "ticker": "UNG",
                "signal_state": "ACTIVE",
                "status": "EXECUTED_CHAOS",
                "entry_type": "CHAOS",
                "blocker_attribution": "REALM_BIS",
                "priority_score": 0.91,
                "ce_score": 0.35,
                "watchlist_tier": "NONE",
                "candidate_conversion_state": "CHAOS_ENTRY",
                "pre_entry_state": "NONE",
            },
        ],
        "execution_policy": {"policy_state": "RESTRICTED"},
        "active_blockers": ["GSCE_PHASE_LOCK", "REALM_BIS"],
        "scm_review": {"scm_state": "LOW_CONVERSION"},
        "simulation_context": {"scenario": "LIVE"},
    }


def _sample_health_report() -> dict:
    return {
        "simulation_mode": "LIVE",
        "policy": {"policy_state": "RESTRICTED"},
        "active_blockers": ["GSCE_PHASE_LOCK", "REALM_BIS"],
        "scm": {"scm_state": "LOW_CONVERSION"},
        "scorecard": {"execution_readiness": {"score": 4}},
        "system_readiness_state": "DO_NOT_DEPLOY",
        "decision_review_state": "NONE",
        "what_should_i_do_next": "EXIT_NOW: UNG | DO NOT ADD NEW RISK",
    }


def _sample_open_positions() -> list[dict]:
    return [
        {
            "ticker": "UNG",
            "entry_price": 70.0,
            "current_price": 64.0,
            "pnl_pct": -0.086,
            "position_size": "QUARTER_UNIT",
            "state": "OPEN",
            "chaos_flag": True,
            "entry_type": "CHAOS",
            "thesis_cluster": "ENERGY_VOLATILITY",
            "stop_loss": 66.0,
            "take_profit": 76.0,
            "time_in_trade": "5d",
            "priority_score": 0.91,
        }
    ]


def test_build_runtime_vocoder_artifact_uses_synthetic_runtime_fallback() -> None:
    artifact = build_runtime_vocoder_artifact(
        runtime_state=_sample_runtime_state(),
        health_report=_sample_health_report(),
        open_positions=_sample_open_positions(),
        now=NOW,
    )

    assert artifact["artifact_kind"] == "signal_vocoder_runtime_artifact"
    assert artifact["schema_version"] == "v1"
    assert artifact["scenario"] == "LIVE"
    assert artifact["source_mode"] == "SYNTHETIC_RUNTIME_FALLBACK"
    assert artifact["entity_count"] == 2
    assert [item["entity_id"] for item in artifact["entities"]] == ["RTX", "UNG"]
    assert artifact["entities"][0]["runtime_context"]["pre_entry_state"] == "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE"
    assert artifact["entities"][1]["runtime_context"]["has_open_position"] is True
    assert artifact["summary"]["blocked_entities"] == ["RTX", "UNG"]


def test_run_diagnostics_pipeline_persists_vocoder_artifact_after_health_report(monkeypatch) -> None:
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

    payload = run_diagnostics_pipeline_module.run_diagnostics_pipeline(write_runtime=True)

    assert payload["system_readiness_state"] == "DO_NOT_DEPLOY"
    assert len(persisted) == 1
    assert persisted[0]["source_mode"] == "SYNTHETIC_RUNTIME_FALLBACK"
    assert persisted[0]["entity_count"] == 2
