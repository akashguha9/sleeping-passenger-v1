"""Tests for the Integrated Sprint hooks in release_gate.evaluate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import release_gate


def test_evaluate_emits_integrated_sprint_block(tmp_path, monkeypatch):
    # Run the real evaluate() against the live repo — it should never crash
    # and must surface the new integrated_sprint block.
    result = release_gate.evaluate()
    assert "integrated_sprint" in result
    block = result["integrated_sprint"]
    assert "typed_config_ok" in block
    assert "live_payload_quality_module_available" in block
    assert "model_reliability_ledger_ok" in block
    assert "compliance_surface_ok" in block
    # The release-gate JSON always exposes a verdict + advisory invariants.
    assert result["verdict"] in {release_gate.PASS, release_gate.WARN, release_gate.FAIL}


def test_evaluate_marks_typed_config_fail_when_safety_floor_violated(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("ADVISORY_ONLY", "false")
    result = release_gate.evaluate()
    assert result["integrated_sprint"]["typed_config_ok"] is False
    assert result["verdict"] == release_gate.FAIL
    assert any("typed_config" in r for r in result["reasons"])


def test_evaluate_warns_when_business_value_summary_missing(monkeypatch, tmp_path):
    # Point the BVR module at a path that does not exist.
    from scripts import business_value_report as bvr
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(bvr, "DEFAULT_SUMMARY_PATH", missing, raising=False)
    result = release_gate.evaluate()
    block = result["integrated_sprint"]
    # The release gate must surface it; the verdict can be WARN or FAIL (FAIL
    # if other checks already failed) but it must not be PASS.
    assert block["business_value_ok"] is False
    assert result["verdict"] in {release_gate.WARN, release_gate.FAIL}


def test_evaluate_safety_stamps_preserved(monkeypatch):
    result = release_gate.evaluate()
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_gate"] == "LOCKED"
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0


def test_evaluate_includes_warnings_and_blocking_lists(monkeypatch):
    result = release_gate.evaluate()
    assert isinstance(result.get("warnings", []), list)
    assert isinstance(result.get("blocking_reasons", []), list)


# ---------------------------------------------------------------------------
# Sprint-2 (Kanté defensive batch 2): the release_gate now writes a full
# release_gate_proof.json with one block per subsystem and aggregates the
# safety invariants centrally.
# ---------------------------------------------------------------------------

def _required_proof_keys():
    return {
        "generated_at_utc", "release_gate_ok", "verdict", "advisory_only_ok",
        "safety", "data_model_persistence", "live_source_refresh",
        "portfolio_truth", "fresh_discovery", "anti_staleness",
        "why_today", "candidate_memory_decay", "five_model_independence",
        "model_disagreement", "ai_integration", "signal_input_quality",
        "business_value", "compliance_readiness", "daily_signal_readiness",
        "blocking_reasons", "warnings",
    }


def test_release_gate_proof_block_has_every_subsystem(monkeypatch):
    result = release_gate.evaluate()
    proof = result.get("release_gate_proof")
    assert isinstance(proof, dict)
    missing = _required_proof_keys() - set(proof.keys())
    assert not missing, f"release_gate_proof missing keys: {missing}"


def test_release_gate_proof_safety_block_holds():
    result = release_gate.evaluate()
    safety = result["release_gate_proof"]["safety"]
    assert safety["ADVISORY_ONLY"] is True
    assert safety["HUMAN_EXECUTION_REQUIRED"] is True
    assert safety["execution_gate"] == "LOCKED"
    assert safety["broker_api_called"] is False
    assert safety["ai_execution_count"] == 0


def test_release_gate_proof_written_to_disk():
    from scripts import release_gate as rg
    release_gate.evaluate()
    proof_path = rg.RELEASE_GATE_PROOF_PATH
    assert proof_path.exists()
    on_disk = json.loads(proof_path.read_text(encoding="utf-8"))
    assert on_disk["safety"]["execution_gate"] == "LOCKED"
    assert on_disk["verdict"] in {"PASS", "WARN", "FAIL"}


def test_release_gate_proof_seeded_with_summaries(tmp_path, monkeypatch):
    """If every subsystem summary is seeded (fixture mode), every block is
    present and has a real score."""
    # Build each summary fresh under tmp_path and point each module at it.
    from scripts import (
        persistence_integrity, source_run_ledger,
        portfolio_truth_integrity, fresh_discovery_quality,
        candidate_memory_decay_v2, why_today_enforcement,
        five_model_independence, model_disagreement_handling,
        ai_integration_readiness, signal_input_quality,
        compliance_readiness, daily_signal_readiness,
    )
    summaries = {
        "persistence_integrity": persistence_integrity,
        "source_run_ledger": source_run_ledger,
        "portfolio_truth_integrity": portfolio_truth_integrity,
        "fresh_discovery_quality": fresh_discovery_quality,
        "why_today_enforcement": why_today_enforcement,
        "five_model_independence": five_model_independence,
        "model_disagreement_handling": model_disagreement_handling,
        "ai_integration_readiness": ai_integration_readiness,
        "signal_input_quality": signal_input_quality,
        "compliance_readiness": compliance_readiness,
        "daily_signal_readiness": daily_signal_readiness,
    }
    for name, mod in summaries.items():
        target = tmp_path / f"{name}.json"
        monkeypatch.setattr(mod, "DEFAULT_SUMMARY_PATH", target, raising=False)
        # Call the module's write_summary if it has one.
        if hasattr(mod, "write_summary"):
            mod.write_summary(target)
    # candidate_memory_decay_v2 has two summaries.
    anti_target = tmp_path / "anti.json"
    memo_target = tmp_path / "memo.json"
    monkeypatch.setattr(candidate_memory_decay_v2,
                        "ANTI_STALENESS_SUMMARY_PATH", anti_target,
                        raising=False)
    monkeypatch.setattr(candidate_memory_decay_v2,
                        "MEMORY_DECAY_SUMMARY_PATH", memo_target,
                        raising=False)
    candidate_memory_decay_v2.write_summaries(
        anti_path=anti_target, memo_path=memo_target,
    )
    result = release_gate.evaluate()
    proof = result["release_gate_proof"]
    for key in (
        "data_model_persistence", "live_source_refresh", "portfolio_truth",
        "fresh_discovery", "anti_staleness", "why_today",
        "candidate_memory_decay", "five_model_independence",
        "model_disagreement", "ai_integration", "signal_input_quality",
        "compliance_readiness", "daily_signal_readiness",
    ):
        assert proof[key]["summary_present"] is True
        assert proof[key].get("score") is not None
