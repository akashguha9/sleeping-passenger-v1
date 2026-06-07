"""Stage 2 + Stage 4 isolation tests for the refactored five-model workflow.

These prove the five models run as ISOLATED review lanes AFTER fresh discovery:
each lane sees only the clean Fresh Discovery Payload, can never see stale /
static / Moltbook / holding / prior names, and the final synthesis is a final
auditor that cannot invent candidates.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from daily_payload_factory import holding, write_daily_payload, write_stale_ledger

from scripts.daily_payload import load_daily_payload
from scripts.daily_synthesis_pipeline import (
    FinalSynthesisCandidateInventionViolation,
    assert_no_candidate_invention,
    build_moltbook_learning_review,
    run_daily_synthesis,
)
from scripts.fresh_market_discovery import build_fresh_market_discovery
from scripts.isolated_model_lanes import (
    CONTEXT_CONTAMINATION_VIOLATION,
    LANES_COMPLETED,
    LANES_SKIPPED,
    MODEL_LANES,
    UNKNOWN_TICKER_VIOLATION,
    ModelLaneInputProvenanceViolation,
    build_all_lane_prompts,
    build_clean_fresh_discovery_payload,
    clean_payload_tickers,
    run_isolated_model_lanes,
    validate_model_lane_input,
    validate_model_lane_output,
)
from scripts.portfolio_truth_gate import build_portfolio_truth_gate

SESSION = "2026-06-07"
STATIC_NAMES = ("NVDA", "AMZN", "GLD", "RHM.DE", "SAP.DE")


def _live_mover(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "is_live": True,
        "source_health": "VERIFIED_LIVE",
        "provider": "yahoo_live",
        "freshness": "FRESH_TODAY",
        "timestamp_utc": f"{SESSION}T13:00:00Z",
        "why_today": "Live gap + volume confirmed today.",
    }


def _static_mover(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "is_live": False,
        "source_health": "UNVERIFIED",
        "provider": "STATIC_UNIVERSE_FALLBACK",
        "freshness": "UNVERIFIED",
    }


def _candidate_item(ticker: str, classification: str = "WATCH", **grades) -> dict:
    base = {
        "ticker": ticker,
        "classification": classification,
        "evidence_strength": grades.get("evidence_strength", "MEDIUM"),
        "model_confidence": grades.get("model_confidence", "MEDIUM"),
        "catalyst_freshness": grades.get("catalyst_freshness", "MEDIUM"),
        "contradiction_risk": grades.get("contradiction_risk", "LOW"),
        "chaos_risk": grades.get("chaos_risk", "LOW"),
        "reason": "test",
        "invalidation_condition": "missing / not provided",
        "what_must_be_true_before_manual_review": "test",
        "no_action_reason": "test",
    }
    return base


def _fixed_client(raw: dict):
    def client(model_name, prompt, clean_payload):
        return dict(raw)
    return client


# ---------------------------------------------------------------------------
# A. No fresh discovery -> lanes skipped, no prompts, empty board, no statics.
# ---------------------------------------------------------------------------

def test_A_no_fresh_discovery_skips_lanes(tmp_path: Path) -> None:
    base = write_daily_payload(
        tmp_path / "p", run_date=SESSION, movers=[], news=[], filings=[],
        source_health="MISSING_OR_UNVERIFIED",
    )
    result = run_daily_synthesis(payload_dir=base)

    assert result["fresh_discovery_contract"]["status"] == "NO_FRESH_DISCOVERY_GENERATED"
    assert result["model_lanes"]["status"] == LANES_SKIPPED
    assert result["model_lanes"]["prompts_built"] == 0
    assert result["model_lanes"]["models_called"] == 0
    assert result["model_lanes"]["model_lane_outputs"] == []

    clean = result["clean_fresh_discovery_payload"]
    assert clean["candidates"] == []
    assert build_all_lane_prompts(clean) == {}

    assert result["mechanical_aggregator"]["candidate_consensus"] == []

    final = result["final_synthesis"]
    assert final["fresh_discovery"]["status"] == "NO_FRESH_DISCOVERY_GENERATED"
    assert final["fresh_discovery"]["tickers"] == []
    # No static name appears anywhere in fresh discovery.
    for name in STATIC_NAMES:
        assert name not in final["fresh_discovery"]["tickers"]


# ---------------------------------------------------------------------------
# B. One valid live candidate -> only PLTR everywhere; NVDA nowhere in lanes.
# ---------------------------------------------------------------------------

def test_B_single_live_candidate_only(tmp_path: Path) -> None:
    base = write_daily_payload(
        tmp_path / "p", run_date=SESSION,
        movers=[_live_mover("PLTR"), _static_mover("NVDA")], source_health="OK",
    )
    result = run_daily_synthesis(payload_dir=base)

    clean = result["clean_fresh_discovery_payload"]
    assert clean_payload_tickers(clean) == {"PLTR"}

    prompts = build_all_lane_prompts(clean)
    assert set(prompts) == set(MODEL_LANES)
    for prompt in prompts.values():
        assert "PLTR" in prompt
        assert "NVDA" not in prompt

    # NVDA is nowhere in model lane input.
    for output in result["model_lanes"]["model_lane_outputs"]:
        all_tickers = {
            item["ticker"]
            for key in ("manual_consideration", "watch", "wait", "avoid", "risk_blocks")
            for item in output.get(key, [])
        }
        assert "NVDA" not in all_tickers

    board_tickers = {r["ticker"] for r in result["mechanical_aggregator"]["candidate_consensus"]}
    assert board_tickers == {"PLTR"}

    assert result["final_synthesis"]["fresh_discovery"]["tickers"] == ["PLTR"]


# ---------------------------------------------------------------------------
# C. Model invents an unknown ticker -> dropped + violation recorded.
# ---------------------------------------------------------------------------

def test_C_model_invents_unknown_ticker(tmp_path: Path) -> None:
    base = write_daily_payload(
        tmp_path / "p", run_date=SESSION, movers=[_live_mover("PLTR")], source_health="OK",
    )
    raw = {
        "watch": [_candidate_item("PLTR")],
        "manual_consideration": [_candidate_item("NVDA", "MANUAL_CONSIDERATION")],
    }
    clients = {m: _fixed_client(raw) for m in MODEL_LANES}
    result = run_daily_synthesis(payload_dir=base, model_clients=clients)

    for output in result["model_lanes"]["model_lane_outputs"]:
        emitted = {
            item["ticker"]
            for key in ("manual_consideration", "watch", "wait", "avoid", "risk_blocks")
            for item in output.get(key, [])
        }
        assert "NVDA" not in emitted
        assert "PLTR" in emitted
        codes = {v["code"] for v in output["provenance_violations_detected"]}
        assert codes  # at least one violation recorded
        assert any(v["ticker"] == "NVDA" for v in output["provenance_violations_detected"])

    board_tickers = {r["ticker"] for r in result["mechanical_aggregator"]["candidate_consensus"]}
    assert board_tickers == {"PLTR"}
    assert "NVDA" not in result["final_synthesis"]["fresh_discovery"]["tickers"]


def test_C_pure_unknown_ticker_code(tmp_path: Path) -> None:
    # A wholly made-up name (not in any research universe) is UNKNOWN, not
    # contamination.
    base = write_daily_payload(
        tmp_path / "p", run_date=SESSION, movers=[_live_mover("PLTR")], source_health="OK",
    )
    payload = load_daily_payload(base)
    gate = build_portfolio_truth_gate(payload=payload)
    disc = build_fresh_market_discovery(payload=payload, truth_gate=gate)
    clean = build_clean_fresh_discovery_payload(disc["fresh_discovery"], payload=payload)

    raw = {"watch": [_candidate_item("PLTR"), _candidate_item("ZZQXFAKE")]}
    cleaned = validate_model_lane_output("gpt", raw, clean, contamination_names=set())
    codes = {v["code"]: v["ticker"] for v in cleaned["provenance_violations_detected"]}
    assert codes.get(UNKNOWN_TICKER_VIOLATION) == "ZZQXFAKE"
    assert {i["ticker"] for i in cleaned["watch"]} == {"PLTR"}


# ---------------------------------------------------------------------------
# D. Moltbook contamination -> learning-only; never in lanes / fresh discovery.
# ---------------------------------------------------------------------------

def test_D_moltbook_names_isolated_to_channel_c(tmp_path: Path) -> None:
    base = write_daily_payload(
        tmp_path / "p", run_date=SESSION, movers=[_live_mover("PLTR")], source_health="OK",
    )
    payload = load_daily_payload(base)
    op, sl = write_stale_ledger(
        tmp_path / "stale", [],
        [{"ticker": "RHM.DE", "status": "WATCHLIST"}, {"ticker": "SAP.DE", "status": "WATCHLIST"}],
    )
    gate = build_portfolio_truth_gate(payload=payload, open_positions_path=op, signal_ledger_path=sl)
    disc = build_fresh_market_discovery(payload=payload, truth_gate=gate, signal_ledger_path=sl)
    contract = disc["fresh_discovery"]
    clean = build_clean_fresh_discovery_payload(contract, payload=payload)

    # Not in the clean payload / lane input.
    assert clean_payload_tickers(clean) == {"PLTR"}
    for prompt in build_all_lane_prompts(clean).values():
        assert "RHM.DE" not in prompt and "SAP.DE" not in prompt

    # A lane that drags a Moltbook name in is flagged as contamination.
    contamination = set(disc["discovery_universe"]) - clean_payload_tickers(clean)
    assert {"RHM.DE", "SAP.DE"} <= contamination
    raw = {"watch": [_candidate_item("PLTR"), _candidate_item("RHM.DE")]}
    cleaned = validate_model_lane_output("grok", raw, clean, contamination_names=contamination)
    codes = {v["code"]: v["ticker"] for v in cleaned["provenance_violations_detected"]}
    assert codes.get(CONTEXT_CONTAMINATION_VIOLATION) == "RHM.DE"
    assert {i["ticker"] for i in cleaned["watch"]} == {"PLTR"}

    # Moltbook learning review (Channel C) is where they legitimately appear.
    learning = build_moltbook_learning_review(gate)
    assert {"RHM.DE", "SAP.DE"} <= set(learning["learning_review_names"])

    # Aggregator only ranks PLTR.
    lanes = run_isolated_model_lanes(clean, contamination_names=contamination)
    from scripts.model_vote_aggregator import aggregate_model_lane_outputs
    agg = aggregate_model_lane_outputs(lanes["model_lane_outputs"], clean)
    assert {r["ticker"] for r in agg["candidate_consensus"]} == {"PLTR"}


# ---------------------------------------------------------------------------
# E. Existing holdings -> Channel B only; never fresh discovery / lanes.
# ---------------------------------------------------------------------------

def test_E_existing_holdings_isolated_to_channel_b(tmp_path: Path) -> None:
    base = write_daily_payload(
        tmp_path / "p", run_date=SESSION,
        verified=[holding("MSFT"), holding("ASML")],
        movers=[_live_mover("PLTR")], source_health="OK",
    )
    result = run_daily_synthesis(payload_dir=base)

    clean = result["clean_fresh_discovery_payload"]
    assert clean_payload_tickers(clean) == {"PLTR"}

    holdings_review = result["existing_holding_review"]
    assert set(holdings_review["verified_open_holdings"]) == {"MSFT", "ASML"}

    for prompt in build_all_lane_prompts(clean).values():
        assert "MSFT" not in prompt and "ASML" not in prompt

    board_tickers = {r["ticker"] for r in result["mechanical_aggregator"]["candidate_consensus"]}
    assert board_tickers == {"PLTR"}
    assert "MSFT" not in result["final_synthesis"]["fresh_discovery"]["tickers"]
    assert "ASML" not in result["final_synthesis"]["fresh_discovery"]["tickers"]


# ---------------------------------------------------------------------------
# F. Static universe contamination, no live data -> NO_FRESH_DISCOVERY.
# ---------------------------------------------------------------------------

def test_F_static_universe_only_yields_no_fresh_discovery(tmp_path: Path) -> None:
    base = write_daily_payload(
        tmp_path / "p", run_date=SESSION, movers=[], source_health="MISSING_OR_UNVERIFIED",
    )
    result = run_daily_synthesis(payload_dir=base)
    assert result["fresh_discovery_contract"]["status"] == "NO_FRESH_DISCOVERY_GENERATED"
    assert result["model_lanes"]["status"] == LANES_SKIPPED
    assert result["mechanical_aggregator"]["candidate_consensus"] == []
    assert result["final_synthesis"]["fresh_discovery"]["tickers"] == []
    # The static universe IS in the research universe (proving exclusion, not absence).
    assert len(result["fresh_market_discovery"]["discovery_universe"]) >= 1


# ---------------------------------------------------------------------------
# G. Prompt examples cannot leak into output candidates.
# ---------------------------------------------------------------------------

def test_G_prompt_has_no_example_tickers(tmp_path: Path) -> None:
    base = write_daily_payload(
        tmp_path / "p", run_date=SESSION, movers=[_live_mover("PLTR")], source_health="OK",
    )
    payload = load_daily_payload(base)
    gate = build_portfolio_truth_gate(payload=payload)
    disc = build_fresh_market_discovery(payload=payload, truth_gate=gate)
    clean = build_clean_fresh_discovery_payload(disc["fresh_discovery"], payload=payload)

    # The only ticker that appears in the prompt is the live payload candidate.
    for prompt in build_all_lane_prompts(clean).values():
        for example in ("NVDA", "AAPL", "TSLA", "SPY", "QQQ", "EXAMPLEX"):
            assert example not in prompt

    # A model that echoes a prompt-example name not in payload is rejected.
    raw = {"watch": [_candidate_item("PLTR"), _candidate_item("EXAMPLEX")]}
    cleaned = validate_model_lane_output("claude", raw, clean, contamination_names=set())
    assert {i["ticker"] for i in cleaned["watch"]} == {"PLTR"}
    assert any(v["ticker"] == "EXAMPLEX" for v in cleaned["provenance_violations_detected"])


# ---------------------------------------------------------------------------
# Input provenance guard — defence in depth.
# ---------------------------------------------------------------------------

def test_input_validation_raises_on_dirty_candidate() -> None:
    dirty = {
        "run_date": SESSION,
        "fresh_discovery_status": "FRESH_DISCOVERY_OK",
        "execution_gate": "LOCKED",
        "advisory_only": True,
        "candidates": [
            {
                "ticker": "NVDA",
                "source_health": "UNVERIFIED",
                "is_live": False,
                "evidence_type": "STATIC_UNIVERSE_FALLBACK",
                "live_evidence_count": 0,
                "from_cache": False,
                "from_fallback": True,
                "from_moltbook": False,
                "from_trade_log": False,
                "allowed_in_fresh_discovery": True,
            }
        ],
    }
    with pytest.raises(ModelLaneInputProvenanceViolation):
        validate_model_lane_input("gpt", dirty)


def test_input_validation_skips_when_no_fresh_discovery() -> None:
    empty = {"fresh_discovery_status": "NO_FRESH_DISCOVERY_GENERATED", "candidates": []}
    assert validate_model_lane_input("gpt", empty) == LANES_SKIPPED


def test_run_lanes_completes_on_clean_payload(tmp_path: Path) -> None:
    base = write_daily_payload(
        tmp_path / "p", run_date=SESSION, movers=[_live_mover("PLTR")], source_health="OK",
    )
    payload = load_daily_payload(base)
    gate = build_portfolio_truth_gate(payload=payload)
    disc = build_fresh_market_discovery(payload=payload, truth_gate=gate)
    clean = build_clean_fresh_discovery_payload(disc["fresh_discovery"], payload=payload)
    lanes = run_isolated_model_lanes(clean)
    assert lanes["status"] == LANES_COMPLETED
    assert lanes["prompts_built"] == len(MODEL_LANES)
    assert lanes["models_called"] == len(MODEL_LANES)


# ---------------------------------------------------------------------------
# I. Final synthesis invention guard.
# ---------------------------------------------------------------------------

def test_I_final_synthesis_invention_guard() -> None:
    clean = {
        "run_date": SESSION,
        "fresh_discovery_status": "FRESH_DISCOVERY_OK",
        "candidates": [{"ticker": "PLTR"}],
    }
    forged = {"fresh_discovery": {"tickers": ["PLTR", "NVDA"], "consensus_board": []}}
    with pytest.raises(FinalSynthesisCandidateInventionViolation):
        assert_no_candidate_invention(forged, clean)


def test_I_final_synthesis_invention_guard_via_board() -> None:
    clean = {
        "run_date": SESSION,
        "fresh_discovery_status": "FRESH_DISCOVERY_OK",
        "candidates": [{"ticker": "PLTR"}],
    }
    forged = {
        "fresh_discovery": {"tickers": ["PLTR"], "consensus_board": [{"ticker": "NVDA"}]}
    }
    with pytest.raises(FinalSynthesisCandidateInventionViolation):
        assert_no_candidate_invention(forged, clean)
