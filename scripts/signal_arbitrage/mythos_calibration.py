"""Provisional calibration harness for the Mythos -> Fable loop.

A real closed-outcome corpus would carry, per resolved thesis, the Mythos
observation features AND the realized outcome.  This repo's durable corpus
(data/daily_payload/closed_positions.json, data/calibration_corpus/) records
trade *status* only — no economic/narrative interpretation features and no
labelled P&L outcome — so a faithful calibration is not yet possible.  Per
repo convention this is reported honestly as INSUFFICIENT_EVIDENCE rather than
fabricated.

In its place this module ships a small, deterministic, clearly-PROVISIONAL
mini-corpus of labelled observations and measures whether the pipeline
*separates* realized winners from losers (routing + capped confidence).  It is
a wiring/own-goal check, not a validated edge.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .util import clamp, r3, mean
from .mythos import MythosObservation
from .mythos_pipeline import run_pipeline, ROUTE_TO_FABLE5

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLOSED = _REPO_ROOT / "data" / "daily_payload" / "closed_positions.json"

# Required fields for a real Mythos calibration row.
_REQUIRED_FEATURE_KEYS = ("economic_reality_score", "narrative_belief_score",
                          "realized_outcome")


# --------------------------------------------------------------------------
# Deterministic PROVISIONAL mini-corpus: (observation, realized_outcome 0..1)
# realized_outcome = 1.0 a thesis that played out, 0.0 one that did not.
# --------------------------------------------------------------------------
def mini_corpus() -> list[tuple[MythosObservation, float]]:
    return [
        # Real reality-ahead-of-narrative thesis that played out.
        (MythosObservation(
            source="sec_filing", entity="WIN_QUIET", claim_type="retention_up",
            raw_text="retention and margins improving while sentiment negative",
            reliability=0.85, recency=0.8, independence=0.7, coverage=0.8,
            noise_level=0.15, confidence_prior=0.65,
            demand=0.65, revenue_growth=0.6, margin_trend=0.82, retention=0.85,
            pricing_power=0.65, customer_adoption=0.7,
            attention=0.2, mentions_velocity=0.15, sentiment=0.25, consensus=0.3,
            evidence_events=({"day": 5, "supports": True, "weight": 0.7, "independent": 0.8},)),
         1.0),
        # Corroborated organic growth that played out.
        (MythosObservation(
            source="sec_filing", entity="WIN_ORGANIC", claim_type="revenue_growth",
            raw_text="revenue grew, margin expanded, retention up",
            reliability=0.9, recency=0.8, independence=0.7, coverage=0.8,
            noise_level=0.1, confidence_prior=0.7,
            revenue_growth=0.75, margin_trend=0.8, retention=0.8, demand=0.75,
            pricing_power=0.65, customer_adoption=0.65,
            attention=0.3, sentiment=0.55, consensus=0.4),
         1.0),
        # Pure narrative buzz, no reality -> did NOT play out.
        (MythosObservation(
            source="x", entity="LOSE_HYPE", claim_type="narrative_buzz",
            raw_text="going viral, to the moon, next big thing",
            reliability=0.4, recency=0.9, independence=0.2, coverage=0.2,
            noise_level=0.7, confidence_prior=0.5,
            attention=0.95, mentions_velocity=0.9, sentiment=0.85,
            amplification=0.8, saturation=0.5, consensus=0.6),
         0.0),
        # Theme-only, weak value capture -> did NOT play out.
        (MythosObservation(
            source="analyst", entity="LOSE_THEME", claim_type="theme_sector",
            raw_text="hot sector therefore buy",
            reliability=0.6, recency=0.7, independence=0.5, coverage=0.4,
            noise_level=0.3, confidence_prior=0.6,
            demand=0.8, revenue_growth=0.7, flow_growth=0.8, capture_rate=0.2,
            leakage=0.5, pricing_power=0.3,
            attention=0.6, mentions_velocity=0.6, sentiment=0.7, consensus=0.6),
         0.0),
        # Stale catalyst -> did NOT play out.
        (MythosObservation(
            source="analyst", entity="LOSE_STALE", claim_type="generic",
            raw_text="catalyst expected in 30 days",
            reliability=0.6, recency=0.4, independence=0.5, coverage=0.5,
            noise_level=0.3, confidence_prior=0.6,
            catalyst_eta_days=30.0, catalyst_elapsed_days=80.0,
            demand=0.5, revenue_growth=0.4),
         0.0),
    ]


def _signal_strength(result: dict[str, Any]) -> float:
    """A single 0..1 conviction proxy for ranking.

    Passing the Mythos pre-filter (reaching Fable scoring) is the primary
    signal: routed signals occupy [0.5, 1.0] (baseline + capped confidence),
    while signals blocked before scoring stay in [0, 0.25] (scaled by layer
    integrity).  So 'routed and confident' always out-ranks 'blocked'."""
    if result["routed_to_fable"] and result["capped_confidence"] is not None:
        return clamp(0.5 + 0.5 * result["capped_confidence"])
    return clamp(0.25 * result["mythos"]["layer_integrity_score"])


def run_calibration(corpus: list[tuple[MythosObservation, float]] | None = None) -> dict[str, Any]:
    """Provisional separation check over the (mini) corpus."""
    corpus = corpus if corpus is not None else mini_corpus()
    rows = []
    for obs, outcome in corpus:
        res = run_pipeline(obs)
        rows.append({"entity": obs.entity, "outcome": outcome,
                     "routed_to_fable": res["routed_to_fable"],
                     "decision": res["pre_scoring_decision"],
                     "strength": r3(_signal_strength(res))})
    winners = [r["strength"] for r in rows if r["outcome"] >= 0.5]
    losers = [r["strength"] for r in rows if r["outcome"] < 0.5]
    mean_win = r3(mean(winners)) if winners else 0.0
    mean_lose = r3(mean(losers)) if losers else 0.0
    separation = r3(mean_win - mean_lose)
    # Rank check: do all winners out-strength all losers?
    clean_separation = bool(winners and losers and min(winners) > max(losers))
    # Winners routed to Fable; losers blocked before scoring?
    winners_routed = all(r["routed_to_fable"] for r in rows if r["outcome"] >= 0.5)
    losers_blocked = all(not r["routed_to_fable"] for r in rows if r["outcome"] < 0.5)
    return {
        "corpus": "PROVISIONAL_MINI_CORPUS",
        "status": "PROVISIONAL",
        "n": len(rows),
        "mean_winner_strength": mean_win,
        "mean_loser_strength": mean_lose,
        "separation": separation,
        "clean_rank_separation": clean_separation,
        "winners_routed_to_fable": winners_routed,
        "losers_blocked_before_fable": losers_blocked,
        "rows": rows,
        "advisory_status": "ADVISORY_ONLY",
        "note": ("Provisional wiring check on a deterministic mini-corpus; not a "
                 "validated edge. See real_corpus_readiness() for the live corpus."),
    }


def aggregation_mini_corpus() -> list[tuple[list[MythosObservation], float]]:
    """Deterministic PROVISIONAL clusters: (observation cluster, outcome)."""
    from .mythos_fixtures import (
        multi_source_reality_cluster, social_only_cluster,
        single_source_reality_baseline, case_1_theme_only,
    )
    return [
        (multi_source_reality_cluster(), 1.0),          # corroborated reality -> played out
        ([single_source_reality_baseline()], 1.0),       # real but single-source
        (social_only_cluster(), 0.0),                    # narrative-only cluster -> noise
        ([case_1_theme_only()], 0.0),                    # theme-only, weak capture -> noise
    ]


def run_aggregation_calibration(
        corpus: list[tuple[list[MythosObservation], float]] | None = None) -> dict[str, Any]:
    """Provisional check that aggregated conviction separates winners/losers and
    that genuine corroboration (distinct ecologies) outranks same-source spam."""
    from .mythos_aggregator import run_aggregated_pipeline
    corpus = corpus if corpus is not None else aggregation_mini_corpus()
    rows = []
    for cluster, outcome in corpus:
        res = run_aggregated_pipeline(cluster)
        if res["routed_to_fable"] and res["capped_confidence"] is not None:
            strength = clamp(0.5 + 0.5 * res["capped_confidence"])
        else:
            strength = clamp(0.25 * res["mythos_confidence_cap"])
        rows.append({"entity": res["entity"], "outcome": outcome,
                     "n_distinct_ecologies": res["n_distinct_ecologies"],
                     "routed_to_fable": res["routed_to_fable"],
                     "decision": res["pre_scoring_decision"], "strength": r3(strength)})
    winners = [r["strength"] for r in rows if r["outcome"] >= 0.5]
    losers = [r["strength"] for r in rows if r["outcome"] < 0.5]
    return {
        "corpus": "PROVISIONAL_AGGREGATION_CORPUS",
        "status": "PROVISIONAL",
        "n": len(rows),
        "mean_winner_strength": r3(mean(winners)) if winners else 0.0,
        "mean_loser_strength": r3(mean(losers)) if losers else 0.0,
        "separation": r3((mean(winners) if winners else 0.0) - (mean(losers) if losers else 0.0)),
        "clean_rank_separation": bool(winners and losers and min(winners) > max(losers)),
        "rows": rows,
        "advisory_status": "ADVISORY_ONLY",
    }


def real_corpus_readiness() -> dict[str, Any]:
    """Honestly assess whether the durable corpus can calibrate Mythos."""
    has_closed = _CLOSED.exists()
    # The closed-positions corpus carries trade status only — none of the
    # Mythos interpretation features or labelled outcomes calibration needs.
    return {
        "closed_positions_present": has_closed,
        "required_feature_keys": list(_REQUIRED_FEATURE_KEYS),
        "features_available_in_corpus": False,
        "calibratable_records": 0,
        "status": "INSUFFICIENT_EVIDENCE",
        "reason": ("Durable corpus records trade status only; it lacks Mythos "
                   "economic/narrative interpretation features and labelled "
                   "outcomes. Backfill required before real calibration."),
        "advisory_status": "ADVISORY_ONLY",
    }


__all__ = ["mini_corpus", "run_calibration", "real_corpus_readiness",
           "aggregation_mini_corpus", "run_aggregation_calibration"]
