"""Daily synthesis orchestrator — the corrected pipeline flow.

Wires the four layers into the corrected structure:

    verified_current_holdings + closed/sold + do_not_treat_as_open
    + fresh market scan + old ledger context
    -> Portfolio Truth Gate (Layer 1)
    -> Fresh Market Discovery Gate (Layer 2)
    -> Candidate / Executable split (Layer 3)
    -> Anti-staleness (Layer 4)
    -> rendered Portfolio Truth context block injected into the five prompts

Old ledger context may inform memory but NEVER overrides verified portfolio
truth. This module is advisory/visibility-only — no execution, no broker, no
file mutation beyond writing its own runtime context artifacts.

CLI:
    python scripts/daily_synthesis_pipeline.py            # print context block
    python scripts/daily_synthesis_pipeline.py --json     # print JSON summary
    python scripts/daily_synthesis_pipeline.py --write     # write runtime artifacts
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps, human_only_stamp
    from scripts.anti_staleness import build_anti_staleness
    from scripts.candidate_executable_split import build_candidate_executable_split
    from scripts.daily_payload import load_daily_payload, normalize_ticker
    from scripts.fresh_discovery_contract import assert_no_provenance_violation
    from scripts.fresh_market_discovery import build_fresh_market_discovery
    from scripts.isolated_model_lanes import (
        LANES_COMPLETED,
        build_clean_fresh_discovery_payload,
        clean_payload_tickers,
        run_isolated_model_lanes,
        write_model_lane_artifacts,
    )
    from scripts.interpretation_defense_engine import (
        attach_defense_to_payload,
        attach_expanded_defense_to_payload,
        run_expanded_interpretation_defense,
        run_interpretation_defense,
    )
    from scripts.model_vote_aggregator import aggregate_model_lane_outputs
    from scripts.portfolio_truth_gate import build_portfolio_truth_gate
    from scripts.runtime_common import REPO_ROOT
    from scripts.why_today import why_today_score
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps, human_only_stamp
    from anti_staleness import build_anti_staleness
    from candidate_executable_split import build_candidate_executable_split
    from daily_payload import load_daily_payload, normalize_ticker
    from fresh_discovery_contract import assert_no_provenance_violation
    from fresh_market_discovery import build_fresh_market_discovery
    from isolated_model_lanes import (
        LANES_COMPLETED,
        build_clean_fresh_discovery_payload,
        clean_payload_tickers,
        run_isolated_model_lanes,
        write_model_lane_artifacts,
    )
    from interpretation_defense_engine import (
        attach_defense_to_payload,
        attach_expanded_defense_to_payload,
        run_expanded_interpretation_defense,
        run_interpretation_defense,
    )
    from model_vote_aggregator import aggregate_model_lane_outputs
    from portfolio_truth_gate import build_portfolio_truth_gate
    from runtime_common import REPO_ROOT
    from why_today import why_today_score


# Final-synthesis invention guard ------------------------------------------

class FinalSynthesisCandidateInventionViolation(RuntimeError):
    """Raised if the final auditor's Fresh Discovery section names a ticker that
    is not in the clean fresh discovery payload."""


CONTEXT_MD_PATH = REPO_ROOT / "runtime" / "daily_portfolio_truth_context.md"
CONTEXT_JSON_PATH = REPO_ROOT / "runtime" / "daily_synthesis_context.json"


def _compute_why_today_scores(
    payload: dict[str, Any], discovery: dict[str, Any]
) -> dict[str, float]:
    """Derive WHY_TODAY_SCORE per discovered ticker from the daily payload.

    A live news/filing event today is a fresh trigger (1.0). A mover row carries
    its own ``why_today``/``freshness``/``provider``. Yesterday's repeats with no
    fresh change decay toward the stale-repeat floor.
    """
    movers_by_ticker: dict[str, dict[str, Any]] = {}
    for mover in payload["price_movers"]["movers"]:
        ticker = normalize_ticker(mover.get("ticker") or mover.get("symbol"))
        if ticker:
            movers_by_ticker[ticker] = mover

    def _live_event_tickers(rows: list[dict[str, Any]]) -> set[str]:
        out: set[str] = set()
        for row in rows:
            if row.get("is_live") or str(row.get("freshness") or "").upper() in {
                "FRESH_TODAY",
                "UPDATED_TODAY",
            }:
                ticker = normalize_ticker(row.get("ticker") or row.get("symbol"))
                if ticker:
                    out.add(ticker)
        return out

    live_event_tickers = _live_event_tickers(payload["news_events"]["events"]) | _live_event_tickers(
        payload["filings_events"]["events"]
    )
    yesterday = set(payload["yesterday_candidates"]["final_candidates"]) | set(
        payload["yesterday_candidates"]["watchlist"]
    )

    scores: dict[str, float] = {}
    for score in discovery["scored_candidates"]:
        ticker = score["ticker"]
        mover = movers_by_ticker.get(ticker, {})
        provider = str(mover.get("provider") or "").upper()
        is_static = provider == "STATIC_UNIVERSE_FALLBACK" or not mover
        scores[ticker] = round(
            why_today_score(
                mover.get("why_today"),
                freshness=mover.get("freshness"),
                has_live_event_today=ticker in live_event_tickers,
                in_yesterday=ticker in yesterday,
                is_static_universe_only=is_static and ticker not in live_event_tickers,
            ),
            4,
        )
    return scores


def build_existing_holding_review(
    payload: dict[str, Any], truth_gate: dict[str, Any]
) -> dict[str, Any]:
    """Channel B — Existing Holding Review (verified holdings only).

    Existing holdings appear HERE and nowhere else. They never enter fresh
    discovery, model lanes, or the consensus board unless they are independently
    revalidated by today's live discovery (Channel A).
    """
    holdings = list(truth_gate["verified_open_holdings"])
    positions = {
        normalize_ticker(p.get("normalized_ticker") or p.get("ticker") or p.get("symbol")): p
        for p in payload["verified_holdings"]["positions"]
        if isinstance(p, dict)
    }
    reviews: list[dict[str, Any]] = []
    for ticker in holdings:
        pos = positions.get(ticker, {})
        reviews.append(
            {
                "ticker": ticker,
                "channel": "EXISTING_HOLDING_REVIEW",
                "status": "VERIFIED_OPEN_HOLDING",
                "entry_price": pos.get("entry_price"),
                "current_price": pos.get("current_price"),
                "thesis": pos.get("thesis") or pos.get("thesis_cluster"),
                "review_note": "Stop / thesis / outcome-maturity review only — never fresh discovery.",
            }
        )
    return {
        "channel": "B",
        "label": "EXISTING_HOLDING_REVIEW",
        "verified_open_holdings": holdings,
        "can_manage_positions": truth_gate["can_manage_positions"],
        "reviews": reviews,
        "note": (
            "Existing holdings appear in this section ONLY. They are not fresh "
            "discovery unless independently revalidated by today's live discovery."
        ),
        "safety": advisory_safety_stamps(),
    }


def _interpretation_defense_lessons(interpretation_defense: dict[str, Any] | None) -> dict[str, Any]:
    """Distil interpretation-defense findings into Moltbook learning fields.

    These are advisory learning prompts — what to watch for next time — never
    trade instructions and never fresh-discovery candidates.
    """
    board = (interpretation_defense or {}).get("board", [])
    iqs_lessons: list[str] = []
    transfer_lessons: list[str] = []
    stress_lessons: list[str] = []
    false_positive_risk: list[str] = []
    false_negative_risk: list[str] = []
    for entry in board:
        ticker = entry.get("ticker")
        iqs = entry.get("interpretation_quality", {})
        mtr = entry.get("metric_transfer_risk", {})
        stress = entry.get("adverse_regime_stress", {})
        if iqs.get("grade") in ("LOW", "TRASHY_INTERPRETATION_RISK"):
            iqs_lessons.append(f"{ticker}: {iqs.get('grade')} — {iqs.get('interpretation_warnings')}")
            false_positive_risk.append(f"{ticker}: dirty interpretation could create a false BUY-candidate.")
        if mtr.get("grade") in ("HIGH", "UNRELIABLE_TRANSFER"):
            transfer_lessons.append(f"{ticker}: {mtr.get('grade')} — {mtr.get('metric_transfer_warnings')}")
        if stress.get("grade") in ("FRAGILE", "INSUFFICIENT_DATA"):
            stress_lessons.append(f"{ticker}: {stress.get('grade')} — {stress.get('stress_flags')}")
        if entry.get("interpretation_defense_grade") == "BLOCKED":
            false_negative_risk.append(
                f"{ticker}: blocked by interpretation defense — confirm this was not a missed real signal."
            )
    return {
        "interpretation_quality_lesson": iqs_lessons,
        "metric_transfer_lesson": transfer_lessons,
        "stress_test_lesson": stress_lessons,
        "false_positive_interpretation_risk": false_positive_risk,
        "false_negative_interpretation_risk": false_negative_risk,
    }


def _p2_lessons(interpretation_expansion: dict[str, Any] | None) -> dict[str, Any]:
    """Distil P2 findings into advisory Moltbook learning fields."""
    board = (interpretation_expansion or {}).get("board", [])
    amplification: list[str] = []
    narrative: list[str] = []
    who_benefits: list[str] = []
    audience: list[str] = []
    operator_warn: list[str] = []
    for entry in board:
        t = entry.get("ticker")
        p2 = entry.get("p2_interpretation_expansion", {})
        da = p2.get("distribution_amplification", {})
        nsg = p2.get("narrative_substance_gap", {})
        inc = p2.get("incentive_who_benefits", {})
        amr = p2.get("audience_misinterpretation", {})
        if da.get("grade") in ("HIGH", "HYPE_LED"):
            amplification.append(f"{t}: {da.get('grade')} — attention vs substance {da.get('attention_growth')}/{da.get('fundamental_improvement')}")
        if nsg.get("grade") in ("NARRATIVE_RICH", "NARRATIVE_OVERHANG"):
            narrative.append(f"{t}: {nsg.get('grade')} (gap {nsg.get('narrative_substance_gap')})")
        if inc.get("grade") in ("HIGH", "EXIT_LIQUIDITY_RISK"):
            who_benefits.append(f"{t}: {inc.get('grade')} — {inc.get('exit_liquidity_flags') or inc.get('asymmetry_flags')}")
        if amr.get("grade") in ("HIGH", "MISREAD_LIKELY"):
            audience.append(f"{t}: {amr.get('grade')} — {amr.get('ambiguous_terms')}")
        if "operator_misread_risk_live_but_incomplete" in (amr.get("misread_flags") or []):
            operator_warn.append(f"{t}: live but incomplete — confirm before acting.")
    return {
        "amplification_lesson": amplification,
        "narrative_substance_lesson": narrative,
        "who_benefits_lesson": who_benefits,
        "audience_misread_lesson": audience,
        "operator_misread_warning": operator_warn,
    }


def build_moltbook_learning_review(
    truth_gate: dict[str, Any],
    interpretation_defense: dict[str, Any] | None = None,
    interpretation_expansion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Channel C — Moltbook / Learning-Outcome Review.

    Closed/sold, do-not-treat, phantom and stale-ledger names live here as
    learning/outcome-review names. They may NEVER appear as fresh discovery
    unless revalidated today through Channel A. Interpretation-defense findings
    are distilled into learning lessons (advisory, never candidates).
    """
    closed_or_sold = list(truth_gate["closed_or_sold"])
    do_not_treat = list(truth_gate["do_not_treat_as_open"])
    phantom = list(truth_gate["phantom_position_candidates"])
    stale_ledger = list(truth_gate["stale_ledger_tickers"])
    learning_names = sorted(
        set(closed_or_sold) | set(do_not_treat) | set(phantom) | set(stale_ledger)
    )
    return {
        "channel": "C",
        "label": "LEARNING_OUTCOME_REVIEW",
        "closed_or_sold": closed_or_sold,
        "do_not_treat_as_open": do_not_treat,
        "phantom_position_candidates": phantom,
        "stale_ledger_tickers": stale_ledger,
        "learning_review_names": learning_names,
        "interpretation_defense_lessons": _interpretation_defense_lessons(interpretation_defense),
        "p2_interpretation_lessons": _p2_lessons(interpretation_expansion),
        "note": (
            "Moltbook / outcome-review names ONLY. They may never enter fresh "
            "discovery unless revalidated today through Channel A (live discovery)."
        ),
        "safety": advisory_safety_stamps(),
    }


def run_daily_synthesis(
    payload_dir: Path | None = None,
    model_candidates: list[str] | None = None,
    features: dict[str, dict[str, Any]] | None = None,
    eqs_features: dict[str, dict[str, Any]] | None = None,
    change_explanations: dict[str, str] | None = None,
    model_clients: dict[str, Any] | None = None,
    fundamentals_by_ticker: dict[str, dict[str, Any]] | None = None,
    reference_regime_by_ticker: dict[str, dict[str, Any]] | None = None,
    attention_by_ticker: dict[str, dict[str, Any]] | None = None,
    ownership_by_ticker: dict[str, dict[str, Any]] | None = None,
    liquidity_by_ticker: dict[str, dict[str, Any]] | None = None,
    crowding_by_ticker: dict[str, dict[str, Any]] | None = None,
    structure_by_ticker: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the corrected flow: fresh discovery -> interpretation defense ->
    isolated model lanes -> mechanical aggregator -> final auditor, with three
    separate channels."""
    payload = load_daily_payload(payload_dir)
    truth_gate = build_portfolio_truth_gate(payload=payload)
    discovery = build_fresh_market_discovery(
        payload=payload, truth_gate=truth_gate,
        model_candidates=model_candidates, features=features,
    )
    why_today_scores = _compute_why_today_scores(payload, discovery)
    split = build_candidate_executable_split(
        discovery, truth_gate, eqs_features=eqs_features,
        why_today_scores=why_today_scores,
    )

    today_candidates = [
        s["ticker"] for s in discovery["buy_candidate_board"]
    ] + [s["ticker"] for s in discovery["watchlist_upgrade_board"]]
    cqs_by_ticker = {s["ticker"]: s["cqs"] for s in discovery["scored_candidates"]}
    anti_staleness = build_anti_staleness(
        payload, today_candidates, truth_gate,
        change_explanations=change_explanations, cqs_by_ticker=cqs_by_ticker,
    )

    contract = discovery.get("fresh_discovery", {})

    # ----- Stage 2a: clean payload + interpretation defense (IQS/MTR/ARST) -----
    clean_payload = build_clean_fresh_discovery_payload(
        contract, run_date=payload["verified_holdings"].get("run_date"), payload=payload
    )
    interpretation_defense = run_interpretation_defense(
        clean_payload,
        fundamentals_by_ticker=fundamentals_by_ticker,
        reference_regime_by_ticker=reference_regime_by_ticker,
    )
    clean_payload = attach_defense_to_payload(clean_payload, interpretation_defense)

    # ----- Stage 2a2: P2 expansion (amplification / narrative / incentive / audience) -----
    interpretation_expansion = run_expanded_interpretation_defense(
        clean_payload,
        p1_result=interpretation_defense,
        fundamentals_by_ticker=fundamentals_by_ticker,
        attention_by_ticker=attention_by_ticker,
        ownership_by_ticker=ownership_by_ticker,
        liquidity_by_ticker=liquidity_by_ticker,
        crowding_by_ticker=crowding_by_ticker,
        structure_by_ticker=structure_by_ticker,
        reference_regime_by_ticker=reference_regime_by_ticker,
    )
    clean_payload = attach_expanded_defense_to_payload(clean_payload, interpretation_expansion)

    # ----- Stage 2b: isolated model lanes (clean payload only) -----
    # Names that exist ONLY in research/holding/Moltbook context — a lane that
    # drags one in is flagged MODEL_CONTEXT_CONTAMINATION_VIOLATION.
    contamination_names = set(discovery["discovery_universe"]) - clean_payload_tickers(clean_payload)
    lane_result = run_isolated_model_lanes(
        clean_payload, model_clients=model_clients, contamination_names=contamination_names
    )

    # ----- Stage 3: mechanical aggregator -----
    aggregator = aggregate_model_lane_outputs(lane_result["model_lane_outputs"], clean_payload)

    # ----- Channels B & C -----
    existing_holding_review = build_existing_holding_review(payload, truth_gate)
    moltbook_learning_review = build_moltbook_learning_review(
        truth_gate,
        interpretation_defense=interpretation_defense,
        interpretation_expansion=interpretation_expansion,
    )

    # ----- Stage 4: final synthesis / auditor -----
    final_synthesis = build_final_synthesis(
        fresh_discovery_contract=contract,
        clean_fresh_discovery_payload=clean_payload,
        model_lane_result=lane_result,
        mechanical_aggregator=aggregator,
        existing_holding_review=existing_holding_review,
        moltbook_learning_review=moltbook_learning_review,
        interpretation_defense=interpretation_defense,
        interpretation_expansion=interpretation_expansion,
    )

    return {
        "run_date": payload["verified_holdings"].get("run_date"),
        "payload": payload,
        "portfolio_truth_gate": truth_gate,
        "fresh_market_discovery": discovery,
        # Top-level alias so callers/artifacts/tests reach the strict gate
        # without digging through the research discovery object.
        "fresh_discovery_contract": contract,
        "clean_fresh_discovery_payload": clean_payload,
        "interpretation_defense": interpretation_defense,
        "interpretation_expansion": interpretation_expansion,
        "model_lanes": lane_result,
        "mechanical_aggregator": aggregator,
        "existing_holding_review": existing_holding_review,
        "moltbook_learning_review": moltbook_learning_review,
        "final_synthesis": final_synthesis,
        "candidate_executable_split": split,
        "anti_staleness": anti_staleness,
        "why_today_scores": why_today_scores,
        "safety": advisory_safety_stamps(),
        "execution": human_only_stamp(),
    }


# ---------------------------------------------------------------------------
# Stage 4 — Final synthesis / Final Auditor (generates NO candidates)
# ---------------------------------------------------------------------------

def assert_no_candidate_invention(
    final_synthesis: dict[str, Any], clean_payload: dict[str, Any]
) -> None:
    """Fail closed if the final auditor's Fresh Discovery section names a ticker
    that is not in the clean fresh discovery payload."""
    allowed = clean_payload_tickers(clean_payload)
    section = final_synthesis.get("fresh_discovery", {})
    offenders: set[str] = set()
    for ticker in section.get("tickers", []):
        if normalize_ticker(ticker) not in allowed:
            offenders.add(normalize_ticker(ticker))
    for row in section.get("consensus_board", []):
        ticker = normalize_ticker(row.get("ticker"))
        if ticker not in allowed:
            offenders.add(ticker)
    if offenders:
        raise FinalSynthesisCandidateInventionViolation(
            f"FINAL_SYNTHESIS_CANDIDATE_INVENTION_VIOLATION: {sorted(offenders)}"
        )


def _interpretation_defense_board(interpretation_defense: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Per-candidate auditor view: what may be misread / missing / fragile."""
    board: list[dict[str, Any]] = []
    for entry in (interpretation_defense or {}).get("board", []):
        iqs = entry.get("interpretation_quality", {})
        mtr = entry.get("metric_transfer_risk", {})
        stress = entry.get("adverse_regime_stress", {})
        board.append(
            {
                "ticker": entry.get("ticker"),
                "iqs": iqs.get("interpretation_quality_score"),
                "mtr": mtr.get("metric_regime_transfer_risk"),
                "stress_failure_risk": stress.get("stress_failure_risk"),
                "interpretation_defense_score": entry.get("interpretation_defense_score"),
                "grade": entry.get("interpretation_defense_grade"),
                "hard_blocks": entry.get("hard_blocks", []),
                "warnings": entry.get("warnings", []),
                "what_interpretation_may_be_wrong": iqs.get("interpretation_warnings", []),
                "what_context_is_missing": iqs.get("missing_context_fields", []),
                "what_stress_could_break_thesis": stress.get("stress_flags", []),
                "advisory_only": True,
            }
        )
    return board


def _p2_expansion_board(interpretation_expansion: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Per-candidate auditor view of the P2 expansion."""
    board: list[dict[str, Any]] = []
    for entry in (interpretation_expansion or {}).get("board", []):
        p2 = entry.get("p2_interpretation_expansion", {})
        da = p2.get("distribution_amplification", {})
        nsg = p2.get("narrative_substance_gap", {})
        inc = p2.get("incentive_who_benefits", {})
        amr = p2.get("audience_misinterpretation", {})
        hl = entry.get("p3_signal_half_life", {})
        pc = entry.get("p3_payoff_capture", {})
        board.append(
            {
                "ticker": entry.get("ticker"),
                "p1_ids": entry.get("p1_interpretation_defense", {}).get("interpretation_defense_score"),
                "expanded_ids": entry.get("expanded_interpretation_defense_score"),
                "expanded_grade": entry.get("expanded_grade"),
                "distribution_amplification_grade": da.get("grade"),
                "narrative_substance_grade": nsg.get("grade"),
                "incentive_who_benefits_grade": inc.get("grade"),
                "audience_misinterpretation_grade": amr.get("grade"),
                "half_life_class": hl.get("half_life_class"),
                "short_half_life_risk": hl.get("short_half_life_risk"),
                "estimated_half_life_days": hl.get("estimated_half_life_days"),
                "capture_grade": pc.get("capture_grade"),
                "payoff_capture_risk": pc.get("payoff_capture_risk"),
                "payoff_capture_diagnostic": pc.get("diagnostic", {}),
                "primary_value_leak": pc.get("diagnostic", {}).get("primary_value_leak"),
                "owner_capture_confidence": pc.get("diagnostic", {}).get("owner_capture_confidence"),
                "false_house_risk": pc.get("diagnostic", {}).get("false_house_risk"),
                "attention_ahead_of_substance": da.get("grade") in ("HIGH", "HYPE_LED"),
                "narrative_ahead_of_substance": nsg.get("grade") in ("NARRATIVE_RICH", "NARRATIVE_OVERHANG"),
                "edge_is_a_snack_not_an_asset": hl.get("half_life_class") == "SNACK",
                "gross_not_net_weak_capture": pc.get("capture_grade") == "WEAK_CAPTURE",
                "who_benefits_if_believed": inc.get("beneficiary_map"),
                "what_could_be_misread": amr.get("misread_flags", []),
                "top_warnings": entry.get("warnings", [])[:6],
                "advisory_only": True,
            }
        )
    return board


def build_final_synthesis(
    *,
    fresh_discovery_contract: dict[str, Any],
    clean_fresh_discovery_payload: dict[str, Any],
    model_lane_result: dict[str, Any],
    mechanical_aggregator: dict[str, Any],
    existing_holding_review: dict[str, Any],
    moltbook_learning_review: dict[str, Any],
    interpretation_defense: dict[str, Any] | None = None,
    interpretation_expansion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize the upstream stages. Generates NO new names; promotes nothing
    that failed provenance; never mixes stale names into fresh discovery."""
    status = clean_fresh_discovery_payload.get("fresh_discovery_status")
    fresh_tickers = sorted(clean_payload_tickers(clean_fresh_discovery_payload))
    lanes_skipped = model_lane_result.get("status") != LANES_COMPLETED
    interpretation_defense = interpretation_defense or {}
    interpretation_expansion = interpretation_expansion or {}

    fresh_section = {
        "label": "FRESH_DISCOVERY",
        "status": status,
        "tickers": fresh_tickers,
        "consensus_board": mechanical_aggregator.get("candidate_consensus", []),
        "no_fresh_discovery": fresh_discovery_contract.get("no_fresh_discovery"),
    }
    interpretation_defense_section = {
        "label": "INTERPRETATION_DEFENSE_BOARD",
        "status": interpretation_defense.get("status", "SKIPPED_NO_FRESH_DISCOVERY"),
        "board": _interpretation_defense_board(interpretation_defense),
        "blocked_count": interpretation_defense.get("blocked_count", 0),
        "blocked_tickers": interpretation_defense.get("blocked_tickers", []),
        "skipped": interpretation_defense.get("status") != "INTERPRETATION_DEFENSE_COMPLETED",
    }
    p2_section = {
        "label": "P2_INTERPRETATION_EXPANSION_BOARD",
        "status": interpretation_expansion.get("status", "SKIPPED_NO_FRESH_DISCOVERY"),
        "board": _p2_expansion_board(interpretation_expansion),
        "blocked_count": interpretation_expansion.get("blocked_count", 0),
        "defensive_count": interpretation_expansion.get("defensive_count", 0),
        "skipped": interpretation_expansion.get("status") != "P2_INTERPRETATION_EXPANSION_COMPLETED",
    }
    provenance_section = {
        "current_session_date": fresh_discovery_contract.get("current_session_date"),
        "fresh_discovery_status": status,
        "live_candidate_count": fresh_discovery_contract.get("live_candidate_count"),
        "blocked_fallback_names": fresh_discovery_contract.get("blocked_fallback_names"),
        "stale_revalidation_needed": fresh_discovery_contract.get("stale_revalidation_needed"),
        "discovery_provenance_violation": fresh_discovery_contract.get("discovery_provenance_violation"),
        "model_lanes_status": model_lane_result.get("status"),
        "model_lanes_skipped": lanes_skipped,
        "total_model_output_violations": model_lane_result.get("total_provenance_violations", 0),
        "interpretation_defense_status": interpretation_defense_section["status"],
        "blocked_by_interpretation_defense": interpretation_defense_section["blocked_count"],
        "p2_expansion_status": p2_section["status"],
        "p2_blocked": p2_section["blocked_count"],
        "p2_defensive": p2_section["defensive_count"],
    }
    synthesis = {
        "role": "FINAL_AUDITOR",
        "generates_candidates": False,
        "run_date": clean_fresh_discovery_payload.get("run_date"),
        "fresh_discovery": fresh_section,
        "interpretation_defense_board": interpretation_defense_section,
        "p2_interpretation_expansion_board": p2_section,
        "existing_holding_review": existing_holding_review,
        "moltbook_learning_review": moltbook_learning_review,
        "provenance": provenance_section,
        "notes": [
            "Final synthesis is the FINAL AUDITOR. It does not generate candidates.",
            "Existing holdings are labelled Existing Holding Review only.",
            "Moltbook names are labelled Learning / Outcome Review only.",
            "Interpretation defense (P1+P2) can only demote; it never promotes a name.",
        ],
        "safety": advisory_safety_stamps(),
        "execution": human_only_stamp(),
    }
    if lanes_skipped:
        synthesis["notes"].append(
            f"Model lanes were {model_lane_result.get('status')} (no fresh discovery)."
        )
    if status != "FRESH_DISCOVERY_OK":
        synthesis["notes"].append("NO_FRESH_DISCOVERY_GENERATED — no fresh candidates today.")

    # Fail closed: the auditor may never invent a fresh-discovery name.
    assert_no_candidate_invention(synthesis, clean_fresh_discovery_payload)
    return synthesis


def render_final_synthesis_markdown(synthesis: dict[str, Any]) -> str:
    """Render the final auditor report (advisory-only, human review required)."""
    fresh = synthesis["fresh_discovery"]
    prov = synthesis["provenance"]
    holdings = synthesis["existing_holding_review"]
    moltbook = synthesis["moltbook_learning_review"]
    lines: list[str] = []
    lines.append("# Final Synthesis — FINAL AUDITOR (advisory only)")
    lines.append("")
    lines.append("Role: FINAL AUDITOR. This stage summarizes upstream isolated lanes and")
    lines.append("the mechanical aggregator. It generates NO new candidates.")
    lines.append("")
    lines.append("## Fresh Discovery (Channel A — live, current-session ONLY)")
    lines.append(f"fresh_discovery_status: {fresh['status']}")
    if fresh["status"] != "FRESH_DISCOVERY_OK":
        lines.append(">>> NO_FRESH_DISCOVERY_GENERATED <<<")
        nfd = fresh.get("no_fresh_discovery") or {}
        lines.append(f"reason: {nfd.get('reason')}")
        lines.append(f"next_required_fix: {nfd.get('next_required_fix')}")
    lines.append(f"fresh_candidates: {fresh['tickers'] or 'NONE'}")
    if fresh.get("consensus_board"):
        lines.append("")
        lines.append("Consensus board (mechanical — no model invention):")
        for row in fresh["consensus_board"]:
            lines.append(
                f"  - {row['ticker']}: {row['classification']} "
                f"(score {row['manual_review_score']}, agreement {row['agreement']}, "
                f"freshness {row['freshness']})"
            )
    lines.append("")
    lines.append("## Interpretation Defense Board (advisory quality/risk — can only demote)")
    idb = synthesis.get("interpretation_defense_board", {})
    lines.append(f"status: {idb.get('status')}")
    if idb.get("skipped"):
        lines.append("Interpretation defense SKIPPED — no verified live candidates to interpret.")
    else:
        lines.append(f"blocked_by_interpretation_defense: {idb.get('blocked_count')} {idb.get('blocked_tickers') or ''}")
        for row in idb.get("board", []):
            lines.append(
                f"  - {row['ticker']}: {row['grade']} "
                f"(IDS {row['interpretation_defense_score']}, IQS {row['iqs']}, "
                f"MTR {row['mtr']}, stress_failure_risk {row['stress_failure_risk']})"
            )
            if row.get("hard_blocks"):
                lines.append(f"      hard_blocks: {row['hard_blocks']}")
            if row.get("what_interpretation_may_be_wrong"):
                lines.append(f"      may_be_misread: {row['what_interpretation_may_be_wrong']}")
            if row.get("what_context_is_missing"):
                lines.append(f"      missing_context: {row['what_context_is_missing']}")
            if row.get("what_stress_could_break_thesis"):
                lines.append(f"      stress_breakers: {row['what_stress_could_break_thesis']}")
    lines.append("")
    lines.append("## P2/P3 Interpretation Expansion Board (amplification / narrative / incentive / audience / half-life / payoff-capture)")
    p2b = synthesis.get("p2_interpretation_expansion_board", {})
    lines.append(f"status: {p2b.get('status')}")
    if p2b.get("skipped"):
        lines.append("P2 expansion SKIPPED — no verified live candidates.")
    else:
        lines.append(f"p2_blocked: {p2b.get('blocked_count')}  p2_defensive: {p2b.get('defensive_count')}")
        for row in p2b.get("board", []):
            lines.append(
                f"  - {row['ticker']}: expanded={row['expanded_grade']} "
                f"(p1 {row['p1_ids']} -> expanded {row['expanded_ids']}) "
                f"amp={row['distribution_amplification_grade']} "
                f"narr={row['narrative_substance_grade']} "
                f"incentive={row['incentive_who_benefits_grade']} "
                f"audience={row['audience_misinterpretation_grade']} "
                f"half_life={row.get('half_life_class')} "
                f"capture={row.get('capture_grade')}"
            )
            if row.get("edge_is_a_snack_not_an_asset"):
                lines.append(
                    f"      short half-life: edge decays fast "
                    f"(~{row.get('estimated_half_life_days')}d, risk {row.get('short_half_life_risk')})"
                )
            if row.get("gross_not_net_weak_capture"):
                lines.append(
                    f"      weak payoff capture: value diluted before owner "
                    f"(capture risk {row.get('payoff_capture_risk')})"
                )
            if row.get("primary_value_leak") not in (None, "none_detected"):
                lines.append(
                    f"      value leak: {row.get('primary_value_leak')} "
                    f"(confidence {row.get('owner_capture_confidence')}"
                    + (f", false_house={row.get('false_house_risk')}" if row.get('false_house_risk') == 'high' else "")
                    + ")"
                )
            if row.get("attention_ahead_of_substance"):
                lines.append("      ! attention ahead of substance")
            if row.get("narrative_ahead_of_substance"):
                lines.append("      ! narrative ahead of substance")
            if row.get("what_could_be_misread"):
                lines.append(f"      misread_risks: {row['what_could_be_misread']}")
    lines.append("")
    lines.append("## Provenance")
    for key in (
        "current_session_date", "fresh_discovery_status", "live_candidate_count",
        "blocked_fallback_names", "stale_revalidation_needed",
        "discovery_provenance_violation", "model_lanes_status",
        "model_lanes_skipped", "total_model_output_violations",
        "interpretation_defense_status", "blocked_by_interpretation_defense",
        "p2_expansion_status", "p2_blocked", "p2_defensive",
    ):
        lines.append(f"  {key}: {prov.get(key)}")
    lines.append("")
    lines.append("## Existing Holding Review (Channel B — NOT fresh discovery)")
    lines.append(f"verified_open_holdings: {holdings['verified_open_holdings'] or 'NONE'}")
    lines.append(f"can_manage_positions: {holdings['can_manage_positions']}")
    lines.append("")
    lines.append("## Learning / Outcome Review (Channel C — NOT fresh discovery)")
    lines.append(f"learning_review_names: {moltbook['learning_review_names'] or 'NONE'}")
    lines.append(f"closed_or_sold: {moltbook['closed_or_sold'] or 'NONE'}")
    lines.append(f"do_not_treat_as_open: {moltbook['do_not_treat_as_open'] or 'NONE'}")
    lines.append("")
    lines.append("Advisory only. No broker action. No execution. Human review required.")
    return "\n".join(lines)


def render_portfolio_truth_context(result: dict[str, Any]) -> str:
    """Render the Portfolio Truth context block injected into the five prompts.

    This is the text that REPLACES naive pasting of the stale
    moltbook/open_positions.json. It states the verified truth first.
    """
    gate = result["portfolio_truth_gate"]
    discovery = result["fresh_market_discovery"]
    split = result["candidate_executable_split"]
    stale = result["anti_staleness"]

    lines: list[str] = []
    lines.append("============================================================")
    lines.append("PORTFOLIO TRUTH GATE (authoritative — overrides stale rows)")
    lines.append("============================================================")
    lines.append("")
    lines.append("H = V MINUS (C UNION S UNION D) is the ONLY valid current-holdings set.")
    lines.append(f"verified_open_holdings (H): {gate['verified_open_holdings'] or 'NONE'}")
    lines.append(f"closed_or_sold (C UNION S): {gate['closed_or_sold'] or 'NONE'}")
    lines.append(f"do_not_treat_as_open (D): {gate['do_not_treat_as_open'] or 'NONE'}")
    lines.append(
        f"phantom_position_candidates (in stale ledger, NOT holdings): "
        f"{gate['phantom_position_candidates'] or 'NONE'}"
    )
    lines.append(f"can_manage_positions: {gate['can_manage_positions']}")
    lines.append(f"global_discovery_permission: {gate['global_discovery_permission']}")
    lines.append("")
    lines.append("HARD RULES:")
    lines.append("- Only tickers in H may receive exit / TP / stop / hold / runner treatment.")
    lines.append("- UNG, TIP, TLT, FCG, GLD are NOT open unless they appear in H above.")
    lines.append("- Phantom positions must NOT block fresh discovery.")
    lines.append("- Dirty hygiene may block EXECUTABLE buys, never candidate discovery.")
    for note in gate.get("notes", []):
        lines.append(f"  * {note}")
    if gate.get("portfolio_truth_errors"):
        lines.append("PORTFOLIO TRUTH ERRORS:")
        for err in gate["portfolio_truth_errors"]:
            lines.append(f"  ! {err}")
    lines.append("")
    lines.append("------------------------------------------------------------")
    lines.append("FRESH DISCOVERY BOARD (live-verified, current-session ONLY)")
    lines.append("------------------------------------------------------------")
    contract = discovery.get("fresh_discovery", {})
    status = contract.get("status", "NO_FRESH_DISCOVERY_GENERATED")
    lines.append(f"fresh_discovery_status: {status}")
    lines.append(f"current_session_date: {contract.get('current_session_date')}")
    lines.append(f"live_candidate_count: {contract.get('live_candidate_count', 0)}")
    lines.append(f"fresh_discovery_board: {contract.get('fresh_discovery_board') or 'NONE'}")
    if status == "NO_FRESH_DISCOVERY_GENERATED":
        nfd = contract.get("no_fresh_discovery") or {}
        lines.append("  >>> NO_FRESH_DISCOVERY_GENERATED <<<")
        lines.append(f"  reason: {nfd.get('reason')}")
        lines.append(f"  failed_payloads: {nfd.get('failed_payloads')}")
        lines.append(f"  source_health_by_payload: {nfd.get('source_health_by_payload')}")
        lines.append(f"  blocked_fallback_names: {nfd.get('blocked_fallback_names') or 'NONE'}")
        lines.append(f"  next_required_fix: {nfd.get('next_required_fix')}")
    lines.append("")
    lines.append("HARD DISCOVERY RULES (the five models MUST obey):")
    lines.append(
        "- ONLY tickers in fresh_discovery_board above may be presented as fresh "
        "candidates / buy-candidates today."
    )
    lines.append(
        "- If status is NO_FRESH_DISCOVERY_GENERATED, output NO_FRESH_DISCOVERY_GENERATED "
        "and DO NOT invent candidates."
    )
    lines.append(
        "- The names in blocked_fallback_names / the research universe below are "
        "static/fallback/prior/Moltbook/fixture context. They are NOT fresh discovery "
        "and MUST NOT be ranked, promoted, or treated as today's candidates."
    )
    lines.append(
        f"  blocked_fallback_names (NOT fresh): {contract.get('blocked_fallback_names') or 'NONE'}"
    )
    lines.append(
        f"  stale_revalidation_needed (diagnostics only): "
        f"{contract.get('stale_revalidation_needed') or 'NONE'}"
    )
    if contract.get("discovery_provenance_violation"):
        lines.append(
            f"  ! DISCOVERY_PROVENANCE_VIOLATION: {contract.get('provenance_violations')}"
        )
    lines.append("")
    lines.append("RESEARCH/DIAGNOSTIC UNIVERSE (NOT fresh discovery — do not promote):")
    lines.append(f"  research_universe: {discovery['discovery_universe'] or 'NONE'}")
    lines.append(f"  new_tickers_not_seen_yesterday: {discovery['new_tickers_not_seen_yesterday'] or 'NONE'}")
    lines.append(f"  discovery_underpowered: {discovery['discovery_underpowered']}")
    for note in discovery.get("discovery_notes", []):
        lines.append(f"  * {note}")
    lines.append("")
    lines.append("CANDIDATE vs EXECUTABLE SPLIT:")
    lines.append(f"  executable_paper_buys: {[r['ticker'] for r in split['executable_paper_buys']] or 'NONE'}")
    lines.append(
        "  buy_candidate_not_executable: "
        f"{[r['ticker'] for r in split['buy_candidate_not_executable']] or 'NONE'}"
    )
    lines.append(f"  watchlist: {[r['ticker'] for r in split['watchlist'] + split['watchlist_upgrades']] or 'NONE'}")
    lines.append(f"  avoid: {[r['ticker'] for r in split['avoid']] or 'NONE'}")
    lines.append("")
    lines.append("ANTI-STALENESS:")
    lines.append(f"  novelty_ratio: {stale['novelty_ratio']} (min {stale['novelty_ratio_min']})")
    lines.append(f"  stale_discovery_warning: {stale['stale_discovery_warning']}")
    for warning in stale.get("warnings", []):
        lines.append(f"  * {warning}")
    lines.append("")
    lines.append("WHY-TODAY GATE (executable requires why_today_score >= 0.70):")
    why_scores = result.get("why_today_scores", {})
    weak = sorted(t for t, s in why_scores.items() if s < 0.70)
    strong = sorted(t for t, s in why_scores.items() if s >= 0.70)
    lines.append(f"  strong_why_today (>=0.70): {strong or 'NONE'}")
    lines.append(f"  weak_why_today (<0.70, not executable): {weak or 'NONE'}")
    lines.append(
        "  Note: a weak why-today blocks EXECUTABLE but NOT discovery — such names "
        "stay BUY-CANDIDATE / NOT-EXECUTABLE."
    )
    lines.append("")
    lines.append("Reminder: advisory only. No broker action. No execution. Human review required.")
    lines.append("============================================================")
    return "\n".join(lines)


def _write_artifacts(result: dict[str, Any], context_md: str) -> None:
    CONTEXT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTEXT_MD_PATH.write_text(context_md, encoding="utf-8")
    contract = result.get("fresh_discovery_contract", {})
    summary = {
        "run_date": result["run_date"],
        "portfolio_truth_gate": result["portfolio_truth_gate"],
        "discovery_universe": result["fresh_market_discovery"]["discovery_universe"],
        "fresh_discovery": {
            "status": contract.get("status"),
            "current_session_date": contract.get("current_session_date"),
            "fresh_discovery_board": contract.get("fresh_discovery_board"),
            "live_candidate_count": contract.get("live_candidate_count"),
            "fallback_candidate_count": contract.get("fallback_candidate_count"),
            "blocked_fallback_names": contract.get("blocked_fallback_names"),
            "stale_revalidation_needed": contract.get("stale_revalidation_needed"),
            "discovery_provenance_violation": contract.get("discovery_provenance_violation"),
            "provenance_violations": contract.get("provenance_violations"),
            "no_fresh_discovery": contract.get("no_fresh_discovery"),
            "provenance_report": contract.get("provenance_report"),
        },
        "executable_paper_buys": [r["ticker"] for r in result["candidate_executable_split"]["executable_paper_buys"]],
        "buy_candidate_not_executable": [
            r["ticker"] for r in result["candidate_executable_split"]["buy_candidate_not_executable"]
        ],
        "anti_staleness": {
            "novelty_ratio": result["anti_staleness"]["novelty_ratio"],
            "stale_discovery_warning": result["anti_staleness"]["stale_discovery_warning"],
        },
        "safety": result["safety"],
    }
    CONTEXT_JSON_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def write_isolated_run_artifacts(result: dict[str, Any]) -> Path:
    """Write the per-run isolated-lane artifact tree under ``runtime/<run_date>/``.

    Layout::

        runtime/YYYY-MM-DD/
          fresh_discovery_contract.json
          clean_fresh_discovery_payload.json
          model_lanes/{<model>_output.json | SKIPPED_NO_FRESH_DISCOVERY.json}
          aggregation/{model_vote_matrix,candidate_consensus,contradiction_report}.json
          final_synthesis.md
          provenance_report.json
    """
    run_date = result.get("run_date") or result["clean_fresh_discovery_payload"].get("run_date") or "unknown_date"
    run_dir = REPO_ROOT / "runtime" / str(run_date)
    run_dir.mkdir(parents=True, exist_ok=True)

    contract = result["fresh_discovery_contract"]
    aggregator = result["mechanical_aggregator"]

    (run_dir / "fresh_discovery_contract.json").write_text(
        json.dumps(contract, indent=2), encoding="utf-8"
    )
    (run_dir / "clean_fresh_discovery_payload.json").write_text(
        json.dumps(result["clean_fresh_discovery_payload"], indent=2), encoding="utf-8"
    )

    write_model_lane_artifacts(result["model_lanes"], run_dir / "model_lanes")

    # Interpretation defense artifacts.
    defense = result.get("interpretation_defense", {})
    idef_dir = run_dir / "interpretation_defense"
    idef_dir.mkdir(parents=True, exist_ok=True)
    if defense.get("status") != "INTERPRETATION_DEFENSE_COMPLETED":
        (idef_dir / "SKIPPED_NO_FRESH_DISCOVERY.json").write_text(
            json.dumps(
                {"status": defense.get("status"), "reason": defense.get("reason"),
                 "run_date": defense.get("run_date"), "board": []},
                indent=2,
            ),
            encoding="utf-8",
        )
    else:
        board = defense.get("board", [])
        (idef_dir / "interpretation_quality_scores.json").write_text(
            json.dumps([b["interpretation_quality"] for b in board], indent=2), encoding="utf-8"
        )
        (idef_dir / "metric_regime_transfer_risk.json").write_text(
            json.dumps([b["metric_transfer_risk"] for b in board], indent=2), encoding="utf-8"
        )
        (idef_dir / "adverse_regime_stress_tests.json").write_text(
            json.dumps([b["adverse_regime_stress"] for b in board], indent=2), encoding="utf-8"
        )
        (idef_dir / "interpretation_defense_board.json").write_text(
            json.dumps(result["final_synthesis"]["interpretation_defense_board"], indent=2),
            encoding="utf-8",
        )

    # P2 expansion artifacts.
    expansion = result.get("interpretation_expansion", {})
    p2_dir = idef_dir / "p2"
    p2_dir.mkdir(parents=True, exist_ok=True)
    if expansion.get("status") != "P2_INTERPRETATION_EXPANSION_COMPLETED":
        (p2_dir / "SKIPPED_NO_FRESH_DISCOVERY.json").write_text(
            json.dumps({"status": expansion.get("status"), "reason": expansion.get("reason"),
                        "run_date": expansion.get("run_date"), "board": []}, indent=2),
            encoding="utf-8",
        )
    else:
        eb = expansion.get("board", [])
        p2_of = lambda e, k: e.get("p2_interpretation_expansion", {}).get(k)  # noqa: E731
        (p2_dir / "distribution_amplification.json").write_text(
            json.dumps([p2_of(e, "distribution_amplification") for e in eb], indent=2), encoding="utf-8")
        (p2_dir / "narrative_substance_gap.json").write_text(
            json.dumps([p2_of(e, "narrative_substance_gap") for e in eb], indent=2), encoding="utf-8")
        (p2_dir / "incentive_who_benefits.json").write_text(
            json.dumps([p2_of(e, "incentive_who_benefits") for e in eb], indent=2), encoding="utf-8")
        (p2_dir / "audience_misinterpretation_risk.json").write_text(
            json.dumps([p2_of(e, "audience_misinterpretation") for e in eb], indent=2), encoding="utf-8")
        (p2_dir / "signal_half_life.json").write_text(
            json.dumps([e.get("p3_signal_half_life") for e in eb], indent=2), encoding="utf-8")
        (p2_dir / "signal_payoff_capture.json").write_text(
            json.dumps([e.get("p3_payoff_capture") for e in eb], indent=2), encoding="utf-8")
        (p2_dir / "expanded_interpretation_defense_board.json").write_text(
            json.dumps(result["final_synthesis"]["p2_interpretation_expansion_board"], indent=2),
            encoding="utf-8")

    agg_dir = run_dir / "aggregation"
    agg_dir.mkdir(parents=True, exist_ok=True)
    (agg_dir / "model_vote_matrix.json").write_text(
        json.dumps(aggregator.get("model_vote_matrix", []), indent=2), encoding="utf-8"
    )
    (agg_dir / "candidate_consensus.json").write_text(
        json.dumps(aggregator.get("candidate_consensus", []), indent=2), encoding="utf-8"
    )
    (agg_dir / "contradiction_report.json").write_text(
        json.dumps(aggregator.get("contradiction_report", []), indent=2), encoding="utf-8"
    )

    (run_dir / "final_synthesis.md").write_text(
        render_final_synthesis_markdown(result["final_synthesis"]), encoding="utf-8"
    )
    (run_dir / "provenance_report.json").write_text(
        json.dumps(
            {
                "provenance": result["final_synthesis"]["provenance"],
                "provenance_report": contract.get("provenance_report"),
                "existing_holding_review": result["existing_holding_review"],
                "moltbook_learning_review": result["moltbook_learning_review"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "capability_upgrade_report.json").write_text(
        json.dumps(build_capability_upgrade_report(result), indent=2), encoding="utf-8"
    )
    return run_dir


def build_capability_upgrade_report(result: dict[str, Any]) -> dict[str, Any]:
    """Honest, run-grounded capability snapshot for the interpretation-defense
    upgrade. Counts are derived from this run; it asserts no score it cannot back
    with shipped code + a runtime artifact."""
    defense = result.get("interpretation_defense", {})
    board = defense.get("board", [])
    grades: dict[str, int] = {}
    for entry in board:
        g = entry.get("interpretation_defense_grade")
        grades[g] = grades.get(g, 0) + 1
    expansion = result.get("interpretation_expansion", {})
    exp_board = expansion.get("board", [])
    exp_grades: dict[str, int] = {}
    for entry in exp_board:
        g = entry.get("expanded_grade")
        exp_grades[g] = exp_grades.get(g, 0) + 1
    return {
        "report": "capability_upgrade_report",
        "run_date": result.get("run_date"),
        "modules_added": [
            "interpretation_quality_score",
            "metric_regime_transfer_risk",
            "adverse_regime_stress_test",
            "interpretation_defense_engine",
        ],
        "p2_modules_added": [
            "distribution_amplification_detector",
            "narrative_substance_gap",
            "incentive_who_benefits_analyzer",
            "audience_misinterpretation_risk",
        ],
        "p3_modules_added": [
            "signal_half_life_estimator",
            "signal_payoff_capture_estimator",
        ],
        "interpretation_defense_status": defense.get("status"),
        "p2_expansion_status": expansion.get("status"),
        "expanded_ids_enabled": expansion.get("status") == "P2_INTERPRETATION_EXPANSION_COMPLETED",
        "fresh_candidate_count": len(result["clean_fresh_discovery_payload"].get("candidates", [])),
        "interpretation_defense_evaluated": len(board),
        "interpretation_defense_blocked": defense.get("blocked_count", 0),
        "interpretation_defense_grade_counts": grades,
        "p2_evaluated": len(exp_board),
        "p2_blocked": expansion.get("blocked_count", 0),
        "p2_defensive": expansion.get("defensive_count", 0),
        "p2_expanded_grade_counts": exp_grades,
        "integrated_into": [
            "clean_fresh_discovery_payload",
            "isolated_model_lanes",
            "model_vote_aggregator",
            "final_synthesis_auditor",
            "moltbook_learning_review",
            "runtime_artifacts",
        ],
        "no_live_feed_limits": [
            "fundamentals usually absent -> ARST INSUFFICIENT_DATA",
            "attention/ownership/liquidity feeds optional -> DA/incentive use heuristics",
            "regime comparison needs a real target-regime feed",
        ],
        "advisory_only": True,
        "execution_gate": "LOCKED",
        "safety": advisory_safety_stamps(),
    }


def compact_status_lines(result: dict[str, Any]) -> list[str]:
    """Build the compact daily status block (requirement 11)."""
    contract = result["fresh_discovery_contract"]
    lanes = result["model_lanes"]
    aggregator = result["mechanical_aggregator"]
    final = result["final_synthesis"]
    defense = result.get("interpretation_defense", {})
    expansion = result.get("interpretation_expansion", {})
    status = contract.get("status")

    if status != "FRESH_DISCOVERY_OK":
        return [
            "NO_FRESH_DISCOVERY_GENERATED",
            "p1_interpretation_defense: SKIPPED",
            "p2_interpretation_expansion: SKIPPED",
            "model_lanes: SKIPPED",
            "fresh_candidates: 0",
            "reason: no verified live candidates",
        ]

    fresh_count = contract.get("live_candidate_count", 0)
    blocked = defense.get("blocked_count", 0)
    p1_done = defense.get("status") == "INTERPRETATION_DEFENSE_COMPLETED"
    p2_done = expansion.get("status") == "P2_INTERPRETATION_EXPANSION_COMPLETED"
    if blocked and blocked >= fresh_count:
        return [
            "INTERPRETATION_DEFENSE_BLOCKED",
            f"fresh_candidates: {fresh_count}",
            f"blocked_by_interpretation_defense: {blocked}",
            "reason: low IQS / high MTR / stress insufficient / provenance violation",
        ]
    return [
        "FRESH_DISCOVERY_OK",
        f"fresh_candidates: {fresh_count}",
        f"p1_interpretation_defense: {'COMPLETED' if p1_done else 'SKIPPED'}",
        f"p2_interpretation_expansion: {'COMPLETED' if p2_done else 'SKIPPED'}",
        f"blocked_by_interpretation_defense: {blocked}",
        f"p2_blocked: {expansion.get('blocked_count', 0)}  p2_defensive: {expansion.get('defensive_count', 0)}",
        f"model_lanes: {'COMPLETED' if lanes.get('status') == LANES_COMPLETED else lanes.get('status')}",
        f"aggregation: {'COMPLETED' if aggregator.get('status') == 'FRESH_DISCOVERY_OK' else 'SKIPPED'}",
        f"final_synthesis: {'COMPLETED' if final.get('role') == 'FINAL_AUDITOR' else 'SKIPPED'}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily five-model synthesis truth/discovery pipeline.")
    parser.add_argument("--json", action="store_true", help="print the JSON summary instead of the context block")
    parser.add_argument("--write", action="store_true", help="write runtime context + isolated-lane artifacts")
    parser.add_argument("--status", action="store_true", help="print the compact daily status block")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    result = run_daily_synthesis()
    context_md = render_portfolio_truth_context(result)
    if args.write:
        _write_artifacts(result, context_md)
        write_isolated_run_artifacts(result)
    if args.status:
        sys.stdout.write("\n".join(compact_status_lines(result)) + "\n")
    elif args.json:
        sys.stdout.write(json.dumps({
            "run_date": result["run_date"],
            "portfolio_truth_gate": result["portfolio_truth_gate"],
            "anti_staleness_warnings": result["anti_staleness"]["warnings"],
            "fresh_discovery_status": result["fresh_discovery_contract"].get("status"),
            "fresh_discovery_board": result["fresh_discovery_contract"].get("fresh_discovery_board"),
            "model_lanes_status": result["model_lanes"].get("status"),
            "final_synthesis_role": result["final_synthesis"].get("role"),
        }, indent=2) + "\n")
    else:
        sys.stdout.write(context_md + "\n")

    # Regression guard: a contaminated Fresh Discovery Board fails the run with a
    # non-zero exit and the violating ticker(s)/source surfaced on stderr.
    contract = result["fresh_discovery_contract"]
    try:
        assert_no_provenance_violation(contract)
    except Exception as exc:  # DiscoveryProvenanceViolation
        sys.stderr.write("PROVENANCE VIOLATION\n")
        for violation in contract.get("provenance_violations", []):
            sys.stderr.write(
                f"  ticker={violation.get('ticker')} source={violation.get('violations')}\n"
            )
        sys.stderr.write(f"{exc}\n")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
