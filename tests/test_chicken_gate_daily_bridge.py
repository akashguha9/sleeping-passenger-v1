"""Chicken Gate v1.2 daily-synthesis integration — regression tests.

Proves the daily path calls the gate, the integrated gate is demote-only
(min rank), integrated scores never exceed either input, audit blocks and
advisory stamps survive the pipeline, missing fields degrade instead of
crashing, freshness decays monotonically, and the debug bypass discloses
itself while defaulting OFF.
"""
from __future__ import annotations

import copy
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from scripts import chicken_gate as cg
from scripts import chicken_gate_daily_bridge as bridge
from scripts import daily_synthesis_pipeline as pipeline
from scripts.advisory_contract import FORBIDDEN_EXECUTION_TOKENS

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_NOW = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)

GATES = (
    cg.GATE_BUY_BLOCKED, cg.GATE_WATCHLIST, cg.GATE_BUY_LIMITED, cg.GATE_BUY_ALLOWED,
)


def synthetic_parts(
    classification: str = "EXECUTABLE-PAPER-BUY", cqs: float = 0.9
) -> dict:
    """Minimal synthetic split/discovery/payload for one candidate."""
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
                "source_health": 0.9, "move_pct": 2.0,
                "why_today": "framework contract award with backlog growth",
            }]},
            "yesterday_candidates": {"final_candidates": [], "watchlist": []},
            "verified_holdings": {"positions": []},
        },
        "why_today_scores": {"TEST": 0.9},
    }


def golden_override() -> dict:
    """Operator-authored full evidence that lets chicken reach BUY_ALLOWED."""
    override = copy.deepcopy(cg.DEMO_THESIS)
    override.pop("ticker", None)
    return override


def integrate(parts: dict, **kwargs) -> dict:
    return bridge.build_chicken_gate_integration(
        split=parts["split"], discovery=parts["discovery"],
        payload=parts["payload"], why_today_scores=parts["why_today_scores"],
        thesis_overrides=kwargs.pop("thesis_overrides", {}),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1. The daily path calls chicken_gate exactly once per buy-side candidate
# ---------------------------------------------------------------------------


def test_daily_synthesis_calls_chicken_gate(monkeypatch):
    calls: list[str] = []
    real = bridge.evaluate_chicken_gate

    def counting(thesis, **kwargs):
        calls.append(thesis.get("ticker"))
        return real(thesis, **kwargs)

    monkeypatch.setattr(bridge, "evaluate_chicken_gate", counting)
    result = pipeline.run_daily_synthesis()
    integration = result["chicken_gate_integration"]
    rows = integration["rows"]
    assert len(rows) >= 1
    # Pass #1 once per candidate, pass #2 once per five-model roundtrip.
    assert len(set(calls)) == len(rows)
    roundtrips = sum(1 for r in rows if r.get("FIVE_MODEL_ROUNDTRIP"))
    assert len(calls) == len(rows) + roundtrips
    assert integration["mode"] == bridge.ENABLED_MODE


# ---------------------------------------------------------------------------
# 2-5. Demote-only integrated gate
# ---------------------------------------------------------------------------


def test_chicken_gate_cannot_upgrade_existing_block():
    parts = synthetic_parts(classification="AVOID")
    result = integrate(parts, thesis_overrides={"TEST": golden_override()})
    row = result["rows"][0]
    assert row["CHICKEN_ACTION_GATE"] == cg.GATE_BUY_ALLOWED  # chicken loves it
    assert row["EXISTING_ACTION_GATE"] == cg.GATE_BUY_BLOCKED
    assert row["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED    # cannot upgrade


def test_chicken_gate_demotes_buy_allowed_to_limited():
    parts = synthetic_parts(classification="EXECUTABLE-PAPER-BUY")
    override = golden_override()
    override["thesis_touches_node"] = False  # node cap -> chicken BUY_LIMITED
    result = integrate(parts, thesis_overrides={"TEST": override})
    row = result["rows"][0]
    assert row["EXISTING_ACTION_GATE"] == cg.GATE_BUY_ALLOWED
    assert row["CHICKEN_ACTION_GATE"] == cg.GATE_BUY_LIMITED
    assert row["FINAL_ACTION_GATE"] == cg.GATE_BUY_LIMITED
    assert row["FINAL_EXECUTABLE"] is False
    assert "TEST" in result["demotions"]


def test_chicken_gate_demotes_to_blocked_on_hard_flag():
    parts = synthetic_parts(classification="EXECUTABLE-PAPER-BUY")
    override = golden_override()
    override["spoilage_risk"] = True
    result = integrate(parts, thesis_overrides={"TEST": override})
    row = result["rows"][0]
    assert row["EXISTING_ACTION_GATE"] == cg.GATE_BUY_ALLOWED
    assert row["CHICKEN_ACTION_GATE"] == cg.GATE_BUY_BLOCKED
    assert "SPOILAGE_RISK" in row["CHICKEN_HARD_FLAG_TRIGGERED"]
    assert row["FINAL_ACTION_GATE"] == cg.GATE_BUY_BLOCKED


@pytest.mark.parametrize("existing", GATES)
@pytest.mark.parametrize("chicken", GATES)
def test_final_gate_rank_is_minimum(existing, chicken):
    final = bridge.integrate_final_gate(existing, chicken)
    assert bridge.GATE_RANK[final] == min(
        bridge.GATE_RANK[existing], bridge.GATE_RANK[chicken]
    )


# ---------------------------------------------------------------------------
# 6. Integrated score never exceeds either input
# ---------------------------------------------------------------------------


def test_integrated_final_score_never_exceeds_existing_or_chicken_raw():
    for classification in ("EXECUTABLE-PAPER-BUY", "WATCHLIST", "AVOID"):
        for override in ({}, golden_override()):
            parts = synthetic_parts(classification=classification)
            result = integrate(
                parts,
                thesis_overrides={"TEST": override} if override else {},
            )
            row = result["rows"][0]
            assert row["INTEGRATED_FINAL_SCORE"] <= row["EXISTING_SCORE"] + 1e-9
            assert (
                row["INTEGRATED_FINAL_SCORE"]
                <= row["CHICKEN_RAW_VALIDATED_SCORE"] + 1e-9
            )
            assert (
                row["INTEGRATED_FINAL_SCORE"] <= row["CHICKEN_FINAL_SCORE"] + 1e-9
            )


# ---------------------------------------------------------------------------
# 7-8. Audit block + advisory stamp survive the pipeline
# ---------------------------------------------------------------------------


def test_daily_output_contains_chicken_audit_block():
    result = pipeline.run_daily_synthesis()
    rows = result["chicken_gate_integration"]["rows"]
    assert rows
    for row in rows:
        block = row["chicken_gate"]
        for key in (
            "scoring_profile_version", "raw_trade_score", "raw_validated_score",
            "raw_inflation_leakage", "freshness_state", "freshness_multiplier",
            "iap_effective", "iap_confidence", "channel_multiplier",
            "operator_fit_score", "operator_fit_confidence", "final_score",
            "final_action_gate", "hard_flag_triggered", "cap_rules_triggered",
            "value_extraction_ledger", "evidence_notes", "one_line_reason",
            "advisory_only_stamp",
        ):
            assert key in block, key
        assert block["scoring_profile_version"] == "chicken-gate-v1.3"
        for key in (
            "EXISTING_ACTION_GATE", "CHICKEN_ACTION_GATE", "FINAL_ACTION_GATE",
            "CHICKEN_FINAL_SCORE", "INTEGRATED_FINAL_SCORE",
            "CHICKEN_HARD_FLAG_TRIGGERED", "CHICKEN_CAP_RULES_TRIGGERED",
            "CHICKEN_ONE_LINE_REASON",
        ):
            assert key in row, key


def test_advisory_stamp_survives_daily_pipeline():
    result = pipeline.run_daily_synthesis()
    integration = result["chicken_gate_integration"]
    assert result["safety"]["advisory_status"] == "ADVISORY_ONLY"
    assert integration["safety"]["advisory_status"] == "ADVISORY_ONLY"
    assert integration["safety"]["can_execute"] is False
    for row in integration["rows"]:
        stamp = row["chicken_gate"]["advisory_only_stamp"]
        assert stamp["advisory_status"] == "ADVISORY_ONLY"
        assert stamp["execution_gate"] == "LOCKED"
        assert stamp["broker_api_called"] is False


# ---------------------------------------------------------------------------
# 9. Missing candidate fields degrade, never crash
# ---------------------------------------------------------------------------


def test_missing_candidate_fields_degrade_not_crash():
    result = bridge.build_chicken_gate_integration(
        split={"classified": [{"ticker": "BARE", "classification": "WATCHLIST"}]},
        discovery={},
        payload={},
        why_today_scores={},
        thesis_overrides={},
    )
    row = result["rows"][0]
    assert row["FINAL_ACTION_GATE"] in GATES
    assert bridge.GATE_RANK[row["FINAL_ACTION_GATE"]] <= bridge.GATE_RANK[
        cg.GATE_WATCHLIST
    ]
    notes = row["chicken_gate"]["evidence_notes"]
    assert notes  # every gap named
    assert any("INSUFFICIENT" in str(n).upper() for n in notes)


# ---------------------------------------------------------------------------
# 10. Freshness daily decay is monotonic
# ---------------------------------------------------------------------------


def test_freshness_daily_decay_monotonic():
    thesis = golden_override()
    thesis["ticker"] = "DECAY"
    del thesis["thesis_age_days"]
    thesis["thesis_first_signal_date"] = _NOW.isoformat()
    earlier = cg.evaluate_chicken_gate(thesis, now=_NOW + timedelta(days=1))
    later = cg.evaluate_chicken_gate(thesis, now=_NOW + timedelta(days=8))
    assert later["FRESHNESS_MULTIPLIER"] <= earlier["FRESHNESS_MULTIPLIER"]
    assert later["FINAL_SCORE"] <= earlier["FINAL_SCORE"]


def test_reevaluate_daily_decay_reports_rows():
    parts = synthetic_parts()
    override = golden_override()
    del override["thesis_age_days"]
    override["thesis_first_signal_date"] = _NOW.isoformat()
    integration = integrate(
        parts, thesis_overrides={"TEST": override}, now=_NOW + timedelta(days=1)
    )
    report = bridge.reevaluate_daily_decay(
        integration, now=_NOW + timedelta(days=30)
    )
    assert report["reevaluated"]
    entry = report["reevaluated"][0]
    assert entry["reevaluated_final_score"] <= entry["previous_final_score"] + 1e-9


# ---------------------------------------------------------------------------
# 11. No broker execution anywhere in the integration
# ---------------------------------------------------------------------------


def test_no_broker_execution_import_or_call():
    for module in (bridge, pipeline, cg):
        src = pathlib.Path(module.__file__).read_text(encoding="utf-8").lower()
        for token in FORBIDDEN_EXECUTION_TOKENS:
            assert token.lower() not in src, f"{module.__name__}: {token}"
        assert "import broker" not in src
        assert "paper_execution" not in src  # gate never touches execution layer


# ---------------------------------------------------------------------------
# 12. Runtime artifact schema is extended, not broken
# ---------------------------------------------------------------------------


def test_runtime_artifact_schema_not_broken(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "CONTEXT_MD_PATH", tmp_path / "ctx.md")
    monkeypatch.setattr(pipeline, "CONTEXT_JSON_PATH", tmp_path / "ctx.json")
    # _write_artifacts also writes the override template since v1.3 — keep
    # test runs from polluting the real runtime/ (governance scans it).
    monkeypatch.setattr(
        bridge, "OVERRIDE_TEMPLATE_PATH", tmp_path / "overrides.template.json"
    )
    result = pipeline.run_daily_synthesis()
    pipeline._write_artifacts(result, pipeline.render_portfolio_truth_context(result))
    summary = json.loads((tmp_path / "ctx.json").read_text(encoding="utf-8"))
    # Pre-v1.2 keys all preserved:
    for key in (
        "run_date", "portfolio_truth_gate", "discovery_universe",
        "fresh_discovery", "executable_paper_buys",
        "buy_candidate_not_executable", "anti_staleness", "safety",
    ):
        assert key in summary, key
    # New nested block added:
    assert summary["chicken_gate"]["mode"] == bridge.ENABLED_MODE
    assert summary["chicken_gate"]["scoring_profile_version"] == "chicken-gate-v1.3"
    assert "final_gate_counts" in summary["chicken_gate"]


# ---------------------------------------------------------------------------
# 13-14. Audit lines rendered + CLI demo
# ---------------------------------------------------------------------------


def test_chicken_gate_audit_line_logged():
    result = pipeline.run_daily_synthesis()
    context = pipeline.render_portfolio_truth_context(result)
    assert "CHICKEN GATE (final advisory freshness/asymmetry/node layer):" in context
    assert "TICKER | existing -> chicken -> final | score | reason" in context
    integration = result["chicken_gate_integration"]
    if integration["rows"]:
        assert integration["audit_lines"]
        assert integration["audit_lines"][0] in context


def test_cli_daily_demo_with_chicken_gate(capsys):
    rc = pipeline.main([])
    out = capsys.readouterr().out
    assert rc in (0, 2)  # 2 = provenance guard, unrelated to chicken gate
    assert "CHICKEN GATE" in out


# ---------------------------------------------------------------------------
# 15. Bypass is debug-only, disclosed, and OFF by default
# ---------------------------------------------------------------------------


def test_chicken_gate_can_be_disabled_only_for_debug():
    assert bridge.CHICKEN_GATE_ENABLED_DEFAULT is True
    assert bridge.CHICKEN_GATE_DEBUG_BYPASS_DEFAULT is False

    parts = synthetic_parts(classification="EXECUTABLE-PAPER-BUY")
    bypassed = integrate(parts, debug_bypass=True)
    assert bypassed["mode"] == "CHICKEN_GATE_DISABLED_DEBUG_ONLY"
    row = bypassed["rows"][0]
    assert row["CHICKEN_ACTION_GATE"] == "CHICKEN_GATE_DISABLED_DEBUG_ONLY"
    assert row["FINAL_ACTION_GATE"] == row["EXISTING_ACTION_GATE"]  # no demotion

    # Default path is enabled and does gate.
    normal = integrate(parts)
    assert normal["mode"] == bridge.ENABLED_MODE
    assert normal["rows"][0]["CHICKEN_ACTION_GATE"] in GATES

    # run_daily_synthesis defaults keep the gate on.
    import inspect
    sig = inspect.signature(pipeline.run_daily_synthesis)
    assert sig.parameters["chicken_gate_enabled"].default is True
    assert sig.parameters["chicken_gate_debug_bypass"].default is False
