"""Tests for ``scripts.daily_signal_readiness``."""
from __future__ import annotations

import json

from scripts import daily_signal_readiness as dsr


def _all_pass_components():
    # Sprint 3 adds candidate_vs_executable to the readiness formula; the
    # default 9.9 keeps this fixture above the 9.8 cap so the test focuses
    # on the safety / portfolio / live-payload caps the rest of the file
    # exercises individually.
    return {
        "portfolio_truth_integrity": 9.7,
        "fresh_discovery_quality": 9.1,
        "anti_staleness": 9.7,
        "five_model_independence": 9.5,
        "live_fresh_payload_quality": 8.5,
        "why_today_enforcement": 9.6,
        "candidate_memory_decay": 9.6,
        "model_disagreement": 9.5,
        "signal_input_quality": 8.8,
        "candidate_vs_executable": 9.9,
        "safety_advisory_integrity": 10.0,
    }


def test_summary_writes(tmp_path):
    target = tmp_path / "dsr.json"
    out = dsr.write_summary(target, components=_all_pass_components())
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["overall_daily_signal_readiness"] >= 9.25
    assert out["summary_path"] == str(target)


def test_safety_failure_caps_readiness():
    components = _all_pass_components()
    components["safety_advisory_integrity"] = 8.0
    summary = dsr.build_summary(components)
    assert summary["overall_daily_signal_readiness"] <= 7.0
    assert any("safety_floor" in c for c in summary["caps_applied"])


def test_weak_live_payload_caps_readiness():
    components = _all_pass_components()
    components["live_fresh_payload_quality"] = 7.0
    summary = dsr.build_summary(components)
    assert summary["overall_daily_signal_readiness"] <= 9.15
    assert any("live_payload_low" in c for c in summary["caps_applied"])


def test_weak_portfolio_truth_caps_readiness():
    components = _all_pass_components()
    components["portfolio_truth_integrity"] = 8.0
    summary = dsr.build_summary(components)
    assert summary["overall_daily_signal_readiness"] <= 9.0
    assert any("portfolio_truth_low" in c for c in summary["caps_applied"])


def test_strong_fixture_evidence_improves_readiness():
    components = _all_pass_components()
    summary = dsr.build_summary(components)
    assert summary["overall_daily_signal_readiness"] >= 9.25


def test_formula_components_visible():
    summary = dsr.build_summary(_all_pass_components())
    expected = {
        "portfolio_truth_integrity", "fresh_discovery_quality",
        "anti_staleness", "five_model_independence",
        "live_fresh_payload_quality", "why_today_enforcement",
        "candidate_memory_decay", "model_disagreement",
        "signal_input_quality", "candidate_vs_executable",
        "safety_advisory_integrity",
    }
    assert set(summary["component_scores"].keys()) == expected


def test_safety_invariants():
    summary = dsr.build_summary(_all_pass_components())
    assert summary["advisory_only"] is True
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0


def test_lpq_at_or_above_8_6_allows_9_35_plus():
    components = _all_pass_components()
    # Strong scores everywhere + LPQ 8.6 + candidate_vs_executable 9.9.
    components.update({
        "portfolio_truth_integrity": 9.7, "fresh_discovery_quality": 9.3,
        "anti_staleness": 9.8, "five_model_independence": 9.65,
        "live_fresh_payload_quality": 8.6, "why_today_enforcement": 9.75,
        "candidate_memory_decay": 9.75, "model_disagreement": 9.65,
        "signal_input_quality": 9.0, "candidate_vs_executable": 9.9,
        "safety_advisory_integrity": 10.0,
    })
    summary = dsr.build_summary(components)
    # No 9.30 / 9.15 LPQ cap should fire when LPQ ≥ 8.6.
    assert "live_payload_below_target:cap_9.30" not in summary["caps_applied"]
    assert "live_payload_low:cap_9.15" not in summary["caps_applied"]
    assert summary["overall_daily_signal_readiness"] >= 9.35


def test_lpq_below_8_6_caps_readiness_at_9_30():
    components = _all_pass_components()
    components["live_fresh_payload_quality"] = 8.3
    summary = dsr.build_summary(components)
    assert summary["overall_daily_signal_readiness"] <= 9.30
    assert any("9.30" in c for c in summary["caps_applied"])


def test_lpq_below_8_0_caps_readiness_at_9_15():
    components = _all_pass_components()
    components["live_fresh_payload_quality"] = 7.5
    summary = dsr.build_summary(components)
    assert summary["overall_daily_signal_readiness"] <= 9.15
    assert any("live_payload_low" in c for c in summary["caps_applied"])


def test_weak_candidate_vs_executable_caps_readiness_at_9_25():
    components = _all_pass_components()
    components["candidate_vs_executable"] = 9.5
    summary = dsr.build_summary(components)
    assert summary["overall_daily_signal_readiness"] <= 9.25
    assert any(
        "candidate_vs_executable_low" in c for c in summary["caps_applied"]
    )


def test_summary_exposes_live_refresh_fields():
    summary = dsr.build_summary(_all_pass_components())
    assert "live_refresh_present" in summary
    assert "live_refresh_fresh" in summary
    assert "live_fresh_payload_quality_score" in summary
    assert "candidate_vs_executable_score" in summary
    # advisory invariants intact
    assert summary["advisory_only"] is True
    assert summary["human_review_required"] is True
    assert summary["execution_permission"] == "ADVISORY_ONLY"


def test_caps_applied_explains_every_cap():
    # Single test that fires all caps at once and confirms each is recorded.
    components = {
        "portfolio_truth_integrity": 8.0,        # cap 9.0
        "fresh_discovery_quality": 8.0,
        "anti_staleness": 8.0,
        "five_model_independence": 8.0,
        "live_fresh_payload_quality": 7.0,       # cap 9.15 (also < 8.6)
        "why_today_enforcement": 8.0,
        "candidate_memory_decay": 8.0,
        "model_disagreement": 8.0,
        "signal_input_quality": 8.0,
        "candidate_vs_executable": 9.0,          # cap 9.25
        "safety_advisory_integrity": 8.0,        # cap 7.0
    }
    summary = dsr.build_summary(components)
    caps = summary["caps_applied"]
    assert any("safety_floor" in c for c in caps)
    assert any("portfolio_truth_low" in c for c in caps)
    assert any("live_payload_low" in c for c in caps)
    assert any("candidate_vs_executable_low" in c for c in caps)
    # safety floor caps at 7.0 (the lowest cap wins).
    assert summary["overall_daily_signal_readiness"] <= 7.0


def test_gather_component_scores_uses_fallback_when_summary_missing(
    monkeypatch, tmp_path,
):
    # Point every component path to a missing file under tmp_path; the
    # gather function should fall back to fixture builders rather than
    # crash or return zeros.
    from scripts import portfolio_truth_integrity as pti
    from scripts import fresh_discovery_quality as fdq
    from scripts import candidate_memory_decay_v2 as cmd2
    from scripts import why_today_enforcement as wte
    from scripts import five_model_independence as fmi
    from scripts import model_disagreement_handling as mdh
    from scripts import source_run_ledger as srl
    from scripts import signal_input_quality as siq

    for module, attr in [
        (pti, "DEFAULT_SUMMARY_PATH"), (fdq, "DEFAULT_SUMMARY_PATH"),
        (wte, "DEFAULT_SUMMARY_PATH"), (fmi, "DEFAULT_SUMMARY_PATH"),
        (mdh, "DEFAULT_SUMMARY_PATH"), (srl, "DEFAULT_SUMMARY_PATH"),
        (siq, "DEFAULT_SUMMARY_PATH"),
    ]:
        monkeypatch.setattr(module, attr, tmp_path / f"{attr}_missing.json",
                            raising=False)
    monkeypatch.setattr(
        cmd2, "ANTI_STALENESS_SUMMARY_PATH",
        tmp_path / "anti_missing.json", raising=False,
    )
    monkeypatch.setattr(
        cmd2, "MEMORY_DECAY_SUMMARY_PATH",
        tmp_path / "memo_missing.json", raising=False,
    )
    comps = dsr.gather_component_scores()
    assert comps["portfolio_truth_integrity"] >= 9.5
    assert comps["fresh_discovery_quality"] >= 9.0
    assert comps["safety_advisory_integrity"] == 10.0
