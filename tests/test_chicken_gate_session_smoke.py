"""Session smoke test — one file that proves the delivered system stands.

Runs the real daily synthesis once and asserts, in a single place, every
contract the session shipped: the v1.3 summary, payload health, override
template (with priority repairs, simulated max gate, and degraded-payload
warning), runtime artifacts, the advisory-only stamp, the absence of
broker execution, the empty THEORETICAL_COMPONENTS honesty tuple, and the
full mathematical invariant chain over live rows.

If this file passes, a fresh checkout is operator-ready.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from scripts import chicken_gate as cg
from scripts import chicken_gate_daily_bridge as bridge
from scripts import chicken_gate_repair_engine as repair
from scripts import daily_synthesis_pipeline as pipeline
from scripts.advisory_contract import FORBIDDEN_EXECUTION_TOKENS

_RANK = bridge.GATE_RANK


@pytest.fixture(scope="module")
def daily_result():
    return pipeline.run_daily_synthesis()


def test_daily_synthesis_runs_and_gates(daily_result):
    integration = daily_result["chicken_gate_integration"]
    assert integration["mode"] == bridge.ENABLED_MODE
    assert integration["rows"], "daily path produced no gated rows"
    assert integration["scoring_profile_version"] == "chicken-gate-v1.3"


def test_v13_summary_complete(daily_result):
    summary = daily_result["chicken_gate_integration"]["chicken_gate_v1_3_summary"]
    for key in (
        "version", "candidate_count", "evaluated_count", "excluded_count",
        "demotions", "hard_blocks", "caps", "five_model_roundtrip_evaluated",
        "payload_health_score", "top_blockers", "top_repair_fields",
        "top_unlockable_candidates", "non_repairable_blocks",
        "override_template_path", "audit_lines",
    ):
        assert key in summary, key


def test_payload_health_bounded_and_warns_when_degraded(daily_result):
    health = daily_result["chicken_gate_integration"]["payload_health"]
    score = health["payload_health_score"]
    assert 0.0 <= score <= 10.0
    if score < 5.0:
        assert health["degraded"] is True
        assert "DAILY_PAYLOAD_DEGRADED" in health["system_note"]
    else:
        assert health["degraded"] is False


def test_override_template_operator_ready(daily_result):
    integration = daily_result["chicken_gate_integration"]
    template = integration["override_template"]
    tickers = [k for k in template if not k.startswith("_")]
    assert tickers, "no unlockable candidates in template"
    block = template[tickers[0]]
    assert block["_priority_repairs"], "template must name the priority repairs"
    assert block["do_not_override_if"]
    assert "_max_simulated_repairable_gate" in block
    meta = template["_meta"]
    assert "instructions" in meta
    if integration["payload_health"]["degraded"]:
        assert "DAILY_PAYLOAD_DEGRADED" in meta["payload_health_warning"]


def test_runtime_artifacts_written(daily_result, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "CONTEXT_MD_PATH", tmp_path / "ctx.md")
    monkeypatch.setattr(pipeline, "CONTEXT_JSON_PATH", tmp_path / "ctx.json")
    monkeypatch.setattr(
        bridge, "OVERRIDE_TEMPLATE_PATH", tmp_path / "overrides.template.json"
    )
    context = pipeline.render_portfolio_truth_context(daily_result)
    pipeline._write_artifacts(daily_result, context)
    summary = json.loads((tmp_path / "ctx.json").read_text(encoding="utf-8"))
    assert summary["chicken_gate_v1_3_summary"]["version"] == "chicken-gate-v1.3"
    assert summary["chicken_gate"]["mode"] == bridge.ENABLED_MODE
    template = json.loads(
        (tmp_path / "overrides.template.json").read_text(encoding="utf-8")
    )
    assert "_meta" in template
    assert "EVIDENCE REPAIR LOOP (v1.3):" in context
    assert "ADVISORY" in context.upper() or "advisory" in context


def test_invariant_chain_on_live_rows(daily_result):
    """Every mathematical contract, asserted over the real daily rows."""
    for row in daily_result["chicken_gate_integration"]["rows"]:
        block = row["chicken_gate"]
        # Chicken internal chain: FINAL <= RAW_VALIDATED <= RAW.
        assert block["final_score"] <= block["raw_validated_score"] + 1e-9
        assert block["raw_validated_score"] <= block["raw_trade_score"] + 1e-9
        assert 0.0 <= block["freshness_multiplier"] <= 1.0
        assert 0.0 <= block["channel_multiplier"] <= 1.0
        # Integrated score <= min(available scores).
        pool = [row["EXISTING_SCORE"], row["CHICKEN_FINAL_SCORE"]]
        if row["CHICKEN_SYNTH_FINAL_SCORE"] is not None:
            pool.append(row["CHICKEN_SYNTH_FINAL_SCORE"])
        assert row["INTEGRATED_FINAL_SCORE"] <= min(pool) + 1e-9
        # Gate min-rank (synth-unaudited cap may only lower further).
        min_rank = min(
            _RANK[row["EXISTING_ACTION_GATE"]], _RANK[row["CHICKEN_ACTION_GATE"]]
        )
        if row["FIVE_MODEL_ROUNDTRIP"]:
            min_rank = min(min_rank, _RANK[row["CHICKEN_SYNTH_ACTION_GATE"]])
            assert _RANK[row["FINAL_ACTION_GATE"]] == min_rank
        else:
            assert _RANK[row["FINAL_ACTION_GATE"]] <= min_rank
        # Repair loop is advisory: simulation bounded by existing gate; a
        # non-repairable hard block pins it at BUY_BLOCKED.
        sim = row["UNLOCK_SIMULATION"]
        assert _RANK[sim["simulated_max_repairable_gate"]] <= _RANK[
            row["EXISTING_ACTION_GATE"]
        ]
        if sim["non_repairable_blocks"]:
            assert sim["simulated_max_repairable_gate"] == cg.GATE_BUY_BLOCKED


def test_advisory_stamp_everywhere(daily_result):
    integration = daily_result["chicken_gate_integration"]
    for stamp in (
        daily_result["safety"],
        integration["safety"],
        integration["chicken_gate_v1_3_summary"]["safety"],
    ):
        assert stamp["advisory_status"] == "ADVISORY_ONLY"
        assert stamp["can_execute"] is False
        assert stamp["broker_api_called"] is False
    for row in integration["rows"]:
        assert (
            row["chicken_gate"]["advisory_only_stamp"]["execution_gate"] == "LOCKED"
        )


def test_no_broker_execution_in_gate_path():
    for module in (cg, bridge, repair, pipeline):
        src = pathlib.Path(module.__file__).read_text(encoding="utf-8").lower()
        for token in FORBIDDEN_EXECUTION_TOKENS:
            assert token.lower() not in src, f"{module.__name__}: {token}"
        assert "import broker" not in src


def test_no_theoretical_components():
    assert repair.THEORETICAL_COMPONENTS == ()
    assert repair.EXTERNAL_DATA_CONSTRAINTS  # external constraints named, not hidden


def test_runbook_and_docs_exist():
    root = pathlib.Path(pipeline.__file__).resolve().parents[1]
    for rel in (
        "docs/chicken_gate_runbook.md",
        "docs/chicken_gate_consolidation_map.md",
        "docs/chicken_gate_v1_2_daily_integration.md",
        "docs/chicken_gate_v1_3_evidence_repair_loop.md",
    ):
        assert (root / rel).exists(), rel
    runbook = (root / "docs/chicken_gate_runbook.md").read_text(encoding="utf-8")
    assert "ADVISORY-ONLY" in runbook
    assert "pytest" in runbook
