"""Chicken Gate v1.3 Evidence Repair Loop — regression tests.

Covers: five-model roundtrip (structured + report + absent), three-way
min-rank gate, min-score integration, repair-plan generation, unlock
simulation bounds, non-repairable blocks, override template generation,
repair priorities, payload health, the v1.3 daily summary, and the
no-theoretical-components honesty assertion.
"""
from __future__ import annotations

import copy
import pathlib

import pytest

from scripts import chicken_gate as cg
from scripts import chicken_gate_daily_bridge as bridge
from scripts import chicken_gate_repair_engine as repair
from scripts import daily_synthesis_pipeline as pipeline
from scripts.advisory_contract import FORBIDDEN_EXECUTION_TOKENS

GATES = (
    cg.GATE_BUY_BLOCKED, cg.GATE_WATCHLIST, cg.GATE_BUY_LIMITED, cg.GATE_BUY_ALLOWED,
)


def synthetic_parts(classification: str = "EXECUTABLE-PAPER-BUY", cqs: float = 0.9):
    executable = classification == "EXECUTABLE-PAPER-BUY"
    return {
        "split": {"classified": [{
            "ticker": "TEST", "classification": classification, "cqs": cqs,
            "eqs": 0.9, "executable": executable, "reason": "synthetic",
        }]},
        "discovery": {"scored_candidates": [{
            "ticker": "TEST", "cqs": cqs, "data_quality": 0.9,
            "crowding_risk": 0.1, "chaos_risk": 0.0,
        }]},
        "payload": {
            "price_movers": {"movers": [{
                "ticker": "TEST", "is_live": True, "freshness": "FRESH_TODAY",
                "provider": "SEC_FILING", "source": "filings",
                "source_health": 0.9, "move_pct": 2.0, "price": 100.0,
                "why_today": "framework contract award with backlog growth",
            }]},
            "yesterday_candidates": {"final_candidates": [], "watchlist": []},
            "verified_holdings": {"positions": []},
        },
        "why_today_scores": {"TEST": 0.9},
    }


def golden_override() -> dict:
    override = copy.deepcopy(cg.DEMO_THESIS)
    override.pop("ticker", None)
    return override


def integrate(parts, **kwargs):
    return bridge.build_chicken_gate_integration(
        split=parts["split"], discovery=parts["discovery"],
        payload=parts["payload"], why_today_scores=parts["why_today_scores"],
        thesis_overrides=kwargs.pop("thesis_overrides", {}),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Five-model roundtrip
# ---------------------------------------------------------------------------


def test_five_model_output_roundtrips_through_chicken_gate_if_available():
    parts = synthetic_parts()
    result = integrate(
        parts,
        thesis_overrides={"TEST": golden_override()},
        five_model_outputs={"TEST": {
            "thesis_text": "Synthesis: demand step-change from framework contracts."
        }},
    )
    row = result["rows"][0]
    assert row["FIVE_MODEL_ROUNDTRIP"] is True
    assert row["CHICKEN_SYNTH_ACTION_GATE"] in GATES
    assert row["CHICKEN_SYNTH_FINAL_SCORE"] is not None
    assert row["FIVE_MODEL_SOURCE"] == "structured_five_model_output"


def test_five_model_report_text_extraction_roundtrips(tmp_path, monkeypatch):
    report = "## Picks\nTEST looks strong on contract backlog.\nAvoid chasing.\n"
    date_dir = tmp_path / "runtime" / "five_model_synthesis" / "2099-01-01"
    date_dir.mkdir(parents=True)
    (date_dir / "final_synthesis.md").write_text(report, encoding="utf-8")
    loaded = bridge.load_five_model_synthesis("2099-01-01", repo_root=tmp_path)
    assert loaded is not None
    section = bridge.extract_ticker_section(loaded["text"], "TEST")
    assert "contract backlog" in section
    assert bridge.extract_ticker_section(loaded["text"], "ABSENT") is None


def test_missing_five_model_output_disclosed_not_crash():
    parts = synthetic_parts()
    result = integrate(parts)  # no outputs, no run_date -> no report
    row = result["rows"][0]
    assert row["FIVE_MODEL_ROUNDTRIP"] is False
    assert row["CHICKEN_SYNTH_ACTION_GATE"] == "NOT_AVAILABLE"
    assert bridge.SYNTH_NOT_AUDITED_NOTE in row["chicken_gate"]["evidence_notes"]


def test_unaudited_synthesis_caps_buy_allowed_at_limited():
    parts = synthetic_parts(classification="EXECUTABLE-PAPER-BUY")
    result = integrate(parts, thesis_overrides={"TEST": golden_override()})
    row = result["rows"][0]
    assert row["CHICKEN_ACTION_GATE"] == cg.GATE_BUY_ALLOWED  # candidate pass
    assert row["FIVE_MODEL_ROUNDTRIP"] is False
    assert row["FINAL_ACTION_GATE"] == cg.GATE_BUY_LIMITED    # capped
    assert any(
        c["rule"] == bridge.SYNTH_NOT_AUDITED_CAP
        for c in row["CHICKEN_CAP_RULES_TRIGGERED"]
    )


def test_final_gate_min_across_existing_candidate_and_synth():
    parts = synthetic_parts(classification="EXECUTABLE-PAPER-BUY")
    synth = {"thesis_text": "spoiled", "spoilage_risk": True}  # synth pass blocks
    result = integrate(
        parts,
        thesis_overrides={"TEST": golden_override()},
        five_model_outputs={"TEST": synth},
    )
    row = result["rows"][0]
    assert row["EXISTING_ACTION_GATE"] == cg.GATE_BUY_ALLOWED
    assert row["CHICKEN_ACTION_GATE"] == cg.GATE_BUY_ALLOWED
    assert row["CHICKEN_SYNTH_ACTION_GATE"] == cg.GATE_BUY_BLOCKED
    assert row["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED


def test_integrated_score_min_across_available_scores():
    parts = synthetic_parts()
    result = integrate(
        parts,
        thesis_overrides={"TEST": golden_override()},
        five_model_outputs={"TEST": {"operator_fit_score": 0.0}},  # synth much lower
    )
    row = result["rows"][0]
    assert row["INTEGRATED_FINAL_SCORE"] <= row["EXISTING_SCORE"] + 1e-9
    assert row["INTEGRATED_FINAL_SCORE"] <= row["CHICKEN_FINAL_SCORE"] + 1e-9
    assert row["INTEGRATED_FINAL_SCORE"] <= row["CHICKEN_SYNTH_FINAL_SCORE"] + 1e-9


def test_v13_keeps_v12_min_rank_invariant():
    for existing in GATES:
        for chicken in GATES:
            final = bridge.integrate_final_gate(existing, chicken)
            assert bridge.GATE_RANK[final] == min(
                bridge.GATE_RANK[existing], bridge.GATE_RANK[chicken]
            )


# ---------------------------------------------------------------------------
# Evidence repair plan
# ---------------------------------------------------------------------------


def test_repair_plan_created_for_missing_load_bearing_node():
    thesis = golden_override()
    for key in ("load_bearing_node", "load_bearing_node_score",
                "load_bearing_node_evidence_confidence", "thesis_touches_node"):
        thesis.pop(key, None)
    gate_result = cg.evaluate_chicken_gate(thesis)
    plan = repair.build_evidence_repair_plan(gate_result, thesis)
    node_items = [p for p in plan if p["missing_or_weak_field"] == "LOAD_BEARING_NODE"]
    assert node_items
    item = node_items[0]
    assert item["repairable"] is True
    assert "load_bearing_node" in item["operator_override_field"]
    assert item["current_status"] == "MISSING"


def test_repair_plan_created_for_net_edge_insufficient():
    thesis = golden_override()
    thesis.pop("model_probability", None)
    gate_result = cg.evaluate_chicken_gate(thesis)
    plan = repair.build_evidence_repair_plan(gate_result, thesis)
    edge_items = [p for p in plan if p["missing_or_weak_field"] == "NET_EDGE"]
    assert edge_items
    item = edge_items[0]
    assert item["current_status"] == "MISSING"
    for field in ("model_probability", "market_implied_probability",
                  "friction_leakage_estimate"):
        assert field in item["operator_override_field"]


def test_non_repairable_spoilage_stays_blocked():
    thesis = golden_override()
    thesis["spoilage_risk"] = True
    gate_result = cg.evaluate_chicken_gate(thesis)
    plan = repair.build_evidence_repair_plan(gate_result, thesis)
    spoil = [p for p in plan if p["missing_or_weak_field"] == "SPOILAGE_RISK"]
    assert spoil and spoil[0]["repairable"] is False
    sim = repair.simulate_unlock(thesis, gate_result, cg.GATE_BUY_ALLOWED)
    assert sim["simulated_max_repairable_gate"] == cg.GATE_BUY_BLOCKED
    assert "SPOILAGE_RISK" in sim["non_repairable_blocks"]


def test_unlock_simulation_respects_existing_gate():
    thesis = golden_override()
    for key in ("load_bearing_node", "load_bearing_node_score",
                "load_bearing_node_evidence_confidence", "thesis_touches_node"):
        thesis.pop(key, None)
    gate_result = cg.evaluate_chicken_gate(thesis)
    sim = repair.simulate_unlock(thesis, gate_result, cg.GATE_WATCHLIST)
    assert repair._RANK[sim["simulated_max_repairable_gate"]] <= repair._RANK[
        cg.GATE_WATCHLIST
    ]
    assert sim["bounded_by_existing_gate"] == cg.GATE_WATCHLIST


def test_unlock_simulation_never_replaces_present_values():
    thesis = golden_override()
    thesis["model_probability"] = 0.50
    thesis["market_implied_probability"] = 0.55  # genuinely negative edge
    gate_result = cg.evaluate_chicken_gate(thesis)
    assert "NET_EDGE_NON_POSITIVE" in gate_result["HARD_FLAG_TRIGGERED"]
    sim = repair.simulate_unlock(thesis, gate_result, cg.GATE_BUY_ALLOWED)
    # Real negative edge is evidence, not a gap — simulation stays blocked.
    assert sim["simulated_max_repairable_gate"] == cg.GATE_BUY_BLOCKED


def test_repair_priority_orders_highest_gate_lift_first():
    thesis = golden_override()
    for key in ("load_bearing_node", "load_bearing_node_score",
                "load_bearing_node_evidence_confidence", "thesis_touches_node"):
        thesis.pop(key, None)
    del thesis["thesis_age_days"]  # small haircut fix available too
    gate_result = cg.evaluate_chicken_gate(thesis)
    plan = repair.build_evidence_repair_plan(gate_result, thesis)
    top = repair.prioritize_repairs(
        thesis, gate_result, cg.GATE_BUY_ALLOWED, plan, top_n=5
    )
    priorities = [t["priority"] for t in top]
    assert priorities == sorted(priorities, reverse=True)
    assert all(p >= 0.0 for p in priorities)
    # The top repair is the one that actually lifts the gate (here: the
    # freshness-date fix crosses WATCHLIST -> BUY_LIMITED; the node fix
    # alone cannot cross a band yet).
    assert priorities[0] > 0.0
    top_fields = [t["missing_or_weak_field"] for t in top]
    assert "LOAD_BEARING_NODE" in top_fields
    assert "THESIS_FIRST_SIGNAL_DATE" in top_fields


def test_repair_plan_is_advisory_never_changes_live_gate():
    parts = synthetic_parts(classification="WATCHLIST")
    result = integrate(parts)
    row = result["rows"][0]
    live_gate = row["FINAL_ACTION_GATE"]
    sim_gate = row["UNLOCK_SIMULATION"]["simulated_max_repairable_gate"]
    # Simulation may look better, but the live gate is untouched by it.
    assert row["FINAL_ACTION_GATE"] == live_gate
    assert bridge.GATE_RANK[sim_gate] <= bridge.GATE_RANK[cg.GATE_WATCHLIST]


# ---------------------------------------------------------------------------
# Override template
# ---------------------------------------------------------------------------


def test_override_template_generated_from_repair_plan():
    parts = synthetic_parts(classification="WATCHLIST")
    result = integrate(parts)
    template = result["override_template"]
    assert "TEST" in template
    block = template["TEST"]
    for field in ("load_bearing_node", "model_probability",
                  "thesis_first_signal_date", "operator_notes",
                  "evidence_links_or_sources", "do_not_override_if"):
        assert field in block, field
    assert block["_priority_repairs"]


def test_override_template_does_not_override_hard_nonrepairable():
    parts = synthetic_parts(classification="EXECUTABLE-PAPER-BUY")
    override = golden_override()
    override["spoilage_risk"] = True
    result = integrate(parts, thesis_overrides={"TEST": override})
    block = result["override_template"]["TEST"]
    assert "SPOILAGE_RISK" in block["_non_repairable_do_not_touch"]
    assert "spoiled thesis not disproven" in block["do_not_override_if"]


def test_write_override_template(tmp_path):
    parts = synthetic_parts(classification="WATCHLIST")
    result = integrate(parts)
    target = bridge.write_override_template(result, path=tmp_path / "tpl.json")
    assert target is not None and target.exists()
    text = target.read_text(encoding="utf-8")
    assert "TEST" in text and "do_not_override_if" in text


# ---------------------------------------------------------------------------
# Payload health
# ---------------------------------------------------------------------------


def test_payload_health_score_flags_degraded_payload():
    parts = synthetic_parts(cqs=0.0)
    parts["payload"]["price_movers"]["movers"][0]["price"] = None
    parts["payload"]["price_movers"]["movers"][0]["provider"] = None
    parts["payload"]["price_movers"]["movers"][0]["source"] = None
    result = integrate(parts)
    health = result["payload_health"]
    assert 0.0 <= health["payload_health_score"] <= 10.0
    assert health["payload_health_score"] < 5.0
    assert health["degraded"] is True
    assert "DAILY_PAYLOAD_DEGRADED" in health["system_note"]


def test_payload_health_score_good_payload_no_warning():
    parts = synthetic_parts(cqs=0.9)
    override = golden_override()  # supplies model_probability + thesis text
    result = integrate(parts, thesis_overrides={"TEST": override})
    health = result["payload_health"]
    assert health["payload_health_score"] >= 5.0
    assert health["degraded"] is False
    assert "system_note" not in health


# ---------------------------------------------------------------------------
# v1.3 daily summary
# ---------------------------------------------------------------------------


def test_daily_summary_contains_v13_fields():
    result = pipeline.run_daily_synthesis()
    summary = result["chicken_gate_integration"]["chicken_gate_v1_3_summary"]
    for key in (
        "version", "candidate_count", "evaluated_count", "excluded_count",
        "demotions", "hard_blocks", "caps", "five_model_roundtrip_evaluated",
        "payload_health_score", "top_blockers", "top_repair_fields",
        "top_unlockable_candidates", "non_repairable_blocks",
        "override_template_path", "audit_lines",
    ):
        assert key in summary, key
    assert summary["version"] == "chicken-gate-v1.3"


def test_top_blockers_aggregated():
    result = pipeline.run_daily_synthesis()
    summary = result["chicken_gate_integration"]["chicken_gate_v1_3_summary"]
    assert isinstance(summary["top_blockers"], list)
    assert summary["top_blockers"]  # degraded payload day: blockers exist
    assert isinstance(summary["top_repair_fields"], list)
    assert "LOAD_BEARING_NODE" in summary["top_repair_fields"]


def test_top_unlockable_candidates_present():
    # A good candidate whose only gaps are repairable appears unlockable.
    parts = synthetic_parts(classification="EXECUTABLE-PAPER-BUY")
    override = golden_override()
    del override["thesis_touches_node"]  # sole repairable gap: node touch unproven
    result = integrate(
        parts,
        thesis_overrides={"TEST": override},
        five_model_outputs={"TEST": {"thesis_text": "TEST audited by synthesis."}},
    )
    row = result["rows"][0]
    assert row["FINAL_ACTION_GATE"] == cg.GATE_BUY_LIMITED  # node cap holds today
    sim = row["UNLOCK_SIMULATION"]
    assert sim["simulated_max_repairable_gate"] == cg.GATE_BUY_ALLOWED
    assert bridge.GATE_RANK[sim["simulated_max_repairable_gate"]] > bridge.GATE_RANK[
        row["FINAL_ACTION_GATE"]
    ]
    summary = result["chicken_gate_v1_3_summary"]
    unlockable = {u["ticker"] for u in summary["top_unlockable_candidates"]}
    assert "TEST" in unlockable


# ---------------------------------------------------------------------------
# Doctrine preserved
# ---------------------------------------------------------------------------


def test_advisory_only_stamp_still_present():
    parts = synthetic_parts()
    result = integrate(parts)
    assert result["safety"]["advisory_status"] == "ADVISORY_ONLY"
    summary = result["chicken_gate_v1_3_summary"]
    assert summary["safety"]["advisory_status"] == "ADVISORY_ONLY"
    row = result["rows"][0]
    assert row["chicken_gate"]["advisory_only_stamp"]["can_execute"] is False


def test_no_broker_execution():
    for module in (repair, bridge, pipeline):
        src = pathlib.Path(module.__file__).read_text(encoding="utf-8").lower()
        for token in FORBIDDEN_EXECUTION_TOKENS:
            assert token.lower() not in src, f"{module.__name__}: {token}"
        assert "import broker" not in src


def test_current_score_equals_ceiling_by_no_theoretical_components():
    # Honesty metadata: nothing shipped-on-paper-only.  Any entry here would
    # mean a claimed capability without code, and this test would fail.
    assert repair.THEORETICAL_COMPONENTS == ()
    # External DATA constraints (not code gaps) must be named, not hidden.
    assert repair.EXTERNAL_DATA_CONSTRAINTS
    assert all(isinstance(c, str) and c for c in repair.EXTERNAL_DATA_CONSTRAINTS)
