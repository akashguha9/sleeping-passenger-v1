"""Mythos -> Fable 5 pipeline — the closed loop.

    Mythos interprets  ->  routes  ->  (only if it earns it) Fable scores
                       ->  ledger remembers  ->  reality checks update confidence

Mythos runs FIRST and acts as an advisory pre-filter: only signals it routes to
``fable5`` reach Fable 5's expensive casino/food-chain scoring.  Narrative-only,
stale, or low-integrity signals are blocked before scoring.  When Fable does
run, Mythos's ``confidence_cap`` (= layer integrity) is applied as an upper
bound on the strategist's confidence — it can only *restrain*, never inflate,
and Fable's fraud gates are untouched.

Pure orchestration; no new conceptual layer.  Deterministic.  Advisory-only.
"""
from __future__ import annotations

from typing import Any

from .util import r3
from .mythos import (
    MythosObservation, run_mythos, build_fable5_dossier, validation_window_for,
)
from .strategist import strategize_signal
from .opportunity import score_opportunity
from .mythos_ledger import MythosLedgerStore

# Pre-scoring routing decisions.
REJECTED_PRE_SCORING = "REJECTED_PRE_SCORING"
ROUTE_TO_FABLE5 = "ROUTE_TO_FABLE5"
ROUTE_TO_FOOD_CHAIN = "ROUTE_TO_FOOD_CHAIN"
ROUTE_TO_REALITY_CHECK = "ROUTE_TO_REALITY_CHECK"
ROUTE_TO_CASINO_ODDS = "ROUTE_TO_CASINO_ODDS"
COLLECT_MORE_EVIDENCE = "COLLECT_MORE_EVIDENCE"
WATCH_ONLY = "WATCH_ONLY"


def _pre_scoring_decision(mythos: dict[str, Any]) -> str:
    primary = mythos["primary_route"]
    nextmod = mythos["recommended_next_module"]
    elig = mythos["strategy_eligibility"]
    if elig == "REJECT_STRATEGY" or primary in ("REJECT_INTERPRETATION", "EXIT"):
        return REJECTED_PRE_SCORING
    if primary == "ROUTE_TO_FABLE5" or nextmod == "fable5":
        return ROUTE_TO_FABLE5
    if primary == "ROUTE_TO_FOOD_CHAIN_ANALYSIS" or nextmod == "food_chain":
        return ROUTE_TO_FOOD_CHAIN
    if primary == "ROUTE_TO_REALITY_CHECK" or nextmod == "reality_check":
        return ROUTE_TO_REALITY_CHECK
    if primary == "ROUTE_TO_CASINO_ODDS" or nextmod == "casino_odds":
        return ROUTE_TO_CASINO_ODDS
    if primary == "COLLECT_MORE_EVIDENCE":
        return COLLECT_MORE_EVIDENCE
    return WATCH_ONLY


def run_pipeline(obs: MythosObservation, *, ledger: MythosLedgerStore | None = None,
                 current_day: int | None = None, run_fable: bool = True) -> dict[str, Any]:
    """Interpret -> route -> (maybe) score -> remember."""
    day = obs.day if current_day is None else current_day
    mythos = run_mythos(obs)
    payload = mythos["mythos_to_fable5_payload"]
    cap = payload["confidence_cap"]
    decision = _pre_scoring_decision(mythos)

    fable: dict[str, Any] | None = None
    fable_summary: dict[str, Any] | None = None
    capped_confidence: float | None = None
    gated_recommended_action: str | None = None

    if decision == ROUTE_TO_FABLE5 and run_fable:
        dossier = build_fable5_dossier(obs, mythos)     # rich translation
        fable = strategize_signal(dossier)              # fraud gates fully applied
        capped_confidence = r3(min(fable["confidence_score"], cap))
        gated_recommended_action = fable["recommended_action"]
        # The cap can only RESTRAIN. Low Mythos integrity downgrades an ACT.
        if capped_confidence < 0.35 and gated_recommended_action == "ACT_NOW":
            gated_recommended_action = "WAIT_FOR_CONFIRMATION"
        fable_summary = {
            "decision": fable["decision"],
            "investable_score": fable["investable_score"],
            "research_ceiling_score": fable["research_ceiling_score"],
            "raw_merit": fable["raw_merit"],
            "fable_confidence_score": fable["confidence_score"],
            "recommended_action": fable["recommended_action"],
        }

    # Remember: persist the claim (durable, hash-chained).
    ledger_view: dict[str, Any] | None = None
    if ledger is not None:
        rec = ledger.upsert_claim(
            entity=obs.entity, claim=obs.resolved_claim(),
            interpretation=mythos["dominant_interpretation"]["direction"],
            governance=mythos["governance_type"],
            prior_confidence=mythos["reality_check"]["confidence_after"],
            day=day, validation_window=validation_window_for(obs.claim_type))
        ledger_view = {
            "claim_id": rec.claim_id, "status": rec.status,
            "confidence": r3(rec.confidence),
            "survival_count": rec.survival_count,
            "contradiction_count": rec.contradiction_count,
            "next_reality_check": rec.expected_check_day,
            "chain_valid": rec.chain_valid(),
        }

    return {
        "entity": obs.entity,
        "source": obs.source,
        "claim": obs.resolved_claim(),
        "pre_scoring_decision": decision,
        "routed_to_fable": fable is not None,
        "mythos": {
            "governance_type": mythos["governance_type"],
            "divergence_type": mythos["divergence_type"],
            "claim_status": mythos["claim_status"],
            "primary_route": mythos["primary_route"],
            "strategy_eligibility": mythos["strategy_eligibility"],
            "interpretation_gap_score": mythos["interpretation_gap_score"],
            "layer_integrity_score": mythos["layer_integrity_score"],
        },
        "mythos_confidence_cap": cap,
        "fable": fable_summary,
        "capped_confidence": capped_confidence,
        "gated_recommended_action": gated_recommended_action,
        "ledger": ledger_view,
        "advisory_status": "ADVISORY_ONLY",
        "real_money_execution": "PROHIBITED",
        "broker_api_called": False,
    }


__all__ = [
    "run_pipeline", "MythosLedgerStore",
    "REJECTED_PRE_SCORING", "ROUTE_TO_FABLE5", "ROUTE_TO_FOOD_CHAIN",
    "ROUTE_TO_REALITY_CHECK", "ROUTE_TO_CASINO_ODDS", "COLLECT_MORE_EVIDENCE",
    "WATCH_ONLY",
]
