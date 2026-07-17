"""Six-lens simulation council — orchestration + explainable aggregation.

Runs the six domain lenses independently, then aggregates their votes WITHOUT
naive averaging.  The aggregator:

* deduplicates evidence by fingerprint (no double-counting a shared source)
* detects correlated lenses (shared fingerprints + shared raw inputs)
* weights empirically-grounded evidence above metaphor/proxy/simulation
* penalises stale data, missing data, source concentration, and agreement that
  is merely an artefact of shared inputs
* preserves minority warnings and tail-risk warnings
* lets RISK_BLOCK override a superficially attractive aggregate score
* explains every weight and penalty
* classifies the disagreement structure

Deterministic: identical (request, seed, observation) → identical result.
"""
from __future__ import annotations

import hashlib
from typing import Any

try:
    from scripts.simulation_intelligence.contracts import (
        SimulationRequest, MarketObservation, LensResult, LensWeight,
        SimulationCouncilResult, AdvisoryVote, VOTE_DEFENSIVENESS,
        DisagreementClass, EvidenceLabel, EVIDENCE_STRENGTH, CONTRACT_VERSION,
        FreshnessStatus,
    )
    from scripts.simulation_intelligence import provenance as prov
    from scripts.simulation_intelligence import feature_flags as flags
    from scripts.simulation_intelligence import scenario_library as scenarios
    from scripts.simulation_intelligence import stress_testing as stress
    from scripts.simulation_intelligence.lenses import all_lenses
    from scripts.simulation_intelligence.adapters.registry import engine_availability_map
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        SimulationRequest, MarketObservation, LensResult, LensWeight,
        SimulationCouncilResult, AdvisoryVote, VOTE_DEFENSIVENESS,
        DisagreementClass, EvidenceLabel, EVIDENCE_STRENGTH, CONTRACT_VERSION,
        FreshnessStatus,
    )
    from simulation_intelligence import provenance as prov  # type: ignore[no-redef]
    from simulation_intelligence import feature_flags as flags  # type: ignore[no-redef]
    from simulation_intelligence import scenario_library as scenarios  # type: ignore[no-redef]
    from simulation_intelligence import stress_testing as stress  # type: ignore[no-redef]
    from simulation_intelligence.lenses import all_lenses  # type: ignore[no-redef]
    from simulation_intelligence.adapters.registry import engine_availability_map  # type: ignore[no-redef]


# Base weights: search/game-theory lenses carry slightly more decision weight
# than the metaphor-heavier physics/chemistry lenses.  All are modest; evidence
# strength does the real work.
_BASE_WEIGHTS = {
    "PHYSICS": 0.9, "CHEMISTRY": 0.9, "BIOLOGY": 1.0,
    "RACING": 1.0, "CHESS": 1.1, "POKER": 1.1,
}


def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, f)) if f == f else lo


def _run_id(request: SimulationRequest, seed: int) -> str:
    basis = f"{request.ticker}|{request.market}|{seed}|" + \
            (request.observation.data_cutoff if request.observation else "")
    return "SIM_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]


def _correlation_penalties(
    results: list[LensResult],
    dedup_report: dict,
) -> dict[str, float]:
    """Per-lens correlation penalty from shared evidence + vote clustering.

    A lens entangled with others via a shared source fingerprint is penalised so
    that agreement caused by *the same input* does not masquerade as independent
    corroboration.
    """
    entangled = set(dedup_report.get("entangled_lenses", []))
    # Vote clustering: if many lenses share a vote AND share evidence, damp them.
    vote_counts: dict[str, int] = {}
    for r in results:
        vote_counts[r.advisory_vote] = vote_counts.get(r.advisory_vote, 0) + 1
    penalties: dict[str, float] = {}
    for r in results:
        pen = 0.0
        if r.lens in entangled:
            pen += 0.25  # shares a source with another lens
        # If this lens's vote is the crowded one and it is entangled, extra damp.
        if vote_counts.get(r.advisory_vote, 0) >= 4 and r.lens in entangled:
            pen += 0.15
        penalties[r.lens] = round(min(0.5, pen), 4)
    return penalties


def _weights(
    results: list[LensResult],
    dedup_report: dict,
    source_conc: float,
) -> list[LensWeight]:
    corr = _correlation_penalties(results, dedup_report)
    weights: list[LensWeight] = []
    for r in results:
        base = _BASE_WEIGHTS.get(r.lens, 1.0)
        ev_mult = EVIDENCE_STRENGTH.get(r.evidence_label, 0.2)
        corr_pen = corr.get(r.lens, 0.0)
        stale_pen = 0.4 if r.freshness_status.upper() == "STALE" else 0.0
        missing_pen = min(0.4, 0.15 * len(r.missing_data_warnings))
        # Source concentration is a council-wide fragility: applied uniformly.
        conc_pen = round(0.3 * source_conc, 4)
        final = base * ev_mult * (1.0 - corr_pen) * (1.0 - stale_pen) \
            * (1.0 - missing_pen) * (1.0 - conc_pen)
        # An errored / insufficient lens contributes ~nothing.
        if r.error or r.evidence_label == EvidenceLabel.INSUFFICIENT_DATA.value:
            final *= 0.05
        reasons = [
            f"base={base}",
            f"evidence[{r.evidence_label}]×{ev_mult}",
        ]
        if corr_pen:
            reasons.append(f"correlation−{corr_pen} (shared evidence)")
        if stale_pen:
            reasons.append(f"stale−{stale_pen}")
        if missing_pen:
            reasons.append(f"missing_data−{round(missing_pen,3)}")
        if conc_pen:
            reasons.append(f"source_concentration−{conc_pen}")
        if r.error:
            reasons.append("lens_error→0.05×")
        weights.append(LensWeight(
            lens=r.lens, base_weight=base, evidence_multiplier=round(ev_mult, 3),
            correlation_penalty=corr_pen, staleness_penalty=stale_pen,
            missing_data_penalty=round(missing_pen, 3), final_weight=round(max(0.0, final), 4),
            reasons=reasons,
        ))
    return weights


def _aggregate_vote(
    results: list[LensResult],
    weights: list[LensWeight],
) -> tuple[str, bool, str, list[str]]:
    """Weighted vote with RISK_BLOCK precedence.

    Returns (vote, risk_block_engaged, reason, explanation_lines).
    """
    wmap = {w.lens: w.final_weight for w in weights}
    explanation: list[str] = []

    # Weighted defensiveness score in [0..4]; higher = more defensive.
    total_w = sum(wmap.values()) or 1.0
    weighted_def = sum(
        VOTE_DEFENSIVENESS.get(r.advisory_vote, 0) * wmap.get(r.lens, 0.0)
        for r in results
    ) / total_w
    explanation.append(f"weighted defensiveness = {weighted_def:.2f}/4 (0=WATCH … 4=RISK_BLOCK)")

    # --- RISK_BLOCK precedence -------------------------------------------
    # A RISK_BLOCK from a lens with meaningful weight, OR a supermajority of
    # AVOID/RISK_BLOCK, OR a severe tail warning, overrides an attractive score.
    risk_block_votes = [r for r in results if r.advisory_vote == AdvisoryVote.RISK_BLOCK.value]
    strong_risk_block = any(wmap.get(r.lens, 0.0) >= 0.15 for r in risk_block_votes)
    defensive_votes = sum(1 for r in results
                          if r.advisory_vote in (AdvisoryVote.AVOID.value, AdvisoryVote.RISK_BLOCK.value))
    severe_tail = any(r.tail_warning and ("ruin" in r.tail_warning.lower()
                                          or "breaches" in r.tail_warning.lower())
                      for r in results)
    high_fragility = (sum(r.fragility for r in results) / max(1, len(results))) >= 0.7

    if strong_risk_block:
        explanation.append("RISK_BLOCK precedence: a weighted lens voted RISK_BLOCK → override")
        return AdvisoryVote.RISK_BLOCK.value, True, "weighted lens RISK_BLOCK", explanation
    if defensive_votes >= 4 and severe_tail:
        explanation.append("RISK_BLOCK precedence: defensive supermajority + severe tail warning")
        return AdvisoryVote.RISK_BLOCK.value, True, "defensive supermajority + tail", explanation
    if severe_tail and high_fragility:
        explanation.append("RISK_BLOCK precedence: severe tail warning under high aggregate fragility")
        return AdvisoryVote.RISK_BLOCK.value, True, "tail + fragility", explanation

    # --- otherwise map weighted defensiveness to a vote ------------------
    if weighted_def >= 2.6:
        vote = AdvisoryVote.AVOID.value
    elif weighted_def >= 1.4:
        vote = AdvisoryVote.WAIT.value
    elif weighted_def >= 0.7:
        vote = AdvisoryVote.OUTCOME_REVIEW.value
    else:
        vote = AdvisoryVote.WATCH.value
    explanation.append(f"mapped to {vote}")
    return vote, False, "weighted aggregation", explanation


def _disagreement_class(
    results: list[LensResult],
    dedup_report: dict,
    weights: list[LensWeight],
    simulation_only: bool,
) -> str:
    ok = [r for r in results if not r.error]
    votes = [r.advisory_vote for r in ok]
    if not votes:
        return DisagreementClass.INSUFFICIENT_INDEPENDENCE.value
    distinct = set(votes)
    shared = dedup_report.get("shared_evidence_detected", False)
    entangled = len(dedup_report.get("entangled_lenses", []))
    n = len(ok)
    independent = n - entangled  # lenses sharing no external fingerprint
    tail = any(r.tail_warning for r in results)
    mean_fragility = sum(r.fragility for r in results) / max(1, len(results))
    benign = sum(1 for v in votes if v in (AdvisoryVote.WATCH.value, AdvisoryVote.OUTCOME_REVIEW.value))

    # --- lenses DISAGREE -------------------------------------------------
    # Disagreement despite shared inputs is a sign of independent *reasoning*,
    # not a defect — it is never INSUFFICIENT_INDEPENDENCE.
    if len(distinct) > 1:
        # A lone tail/defensive warning against an otherwise benign majority.
        if tail and benign >= 4:
            return DisagreementClass.MINORITY_TAIL_WARNING.value
        return DisagreementClass.SPLIT_DECISION.value

    # --- lenses AGREE (unanimous) ----------------------------------------
    # So few independent voices that the "consensus" is really one input.
    if independent < 2 and shared:
        return DisagreementClass.INSUFFICIENT_INDEPENDENCE.value
    # Agreement that is materially an artefact of shared external evidence.
    if shared and entangled >= 4:
        return DisagreementClass.SHARED_EVIDENCE_ILLUSION.value
    # Agreement resting only on simulated/proxy evidence (no real grounding).
    if simulation_only:
        return DisagreementClass.SIMULATION_ONLY_CONSENSUS.value
    if mean_fragility < 0.4:
        return DisagreementClass.CONSENSUS_ROBUST.value
    return DisagreementClass.CONSENSUS_FRAGILE.value


def _usefulness_score(
    results: list[LensResult],
    dedup_report: dict,
    disagreement: str,
) -> float:
    """Engineering / decision usefulness — explicitly NOT predictive alpha.

    Rewards: lens coverage, independence (low entanglement), honest evidence
    labelling, preserved warnings, and explainability.  Bounded 0..10.
    """
    n_ok = sum(1 for r in results if not r.error
               and r.evidence_label != EvidenceLabel.INSUFFICIENT_DATA.value)
    coverage = n_ok / 6.0
    entangled = len(dedup_report.get("entangled_lenses", []))
    independence = 1.0 - min(1.0, entangled / 6.0)
    warnings_preserved = 1.0 if any(r.tail_warning or r.missing_data_warnings for r in results) else 0.6
    honesty = 1.0 if all(r.evidence_label != EvidenceLabel.MEASURED.value for r in results) else 0.8
    # (all-MEASURED would be dishonest here — there are no real outcomes.)
    score = 10.0 * (0.35 * coverage + 0.30 * independence + 0.20 * warnings_preserved + 0.15 * honesty)
    return round(min(10.0, score), 2)


def run_council(
    request: SimulationRequest,
    run_stress: bool = True,
) -> SimulationCouncilResult:
    """Run the six-lens council for a request. Pure + deterministic."""
    obs = request.observation or MarketObservation(ticker=request.ticker, market=request.market)
    seed = int(request.seed)

    # -- 1. run the six lenses independently ------------------------------
    requested = {d.upper() for d in request.requested_lenses} if request.requested_lenses else None
    lenses = [l for l in all_lenses() if (requested is None or l.domain in requested)]
    results: list[LensResult] = [l.evaluate(obs, request, seed) for l in lenses]

    # -- 2. evidence dedup + provenance -----------------------------------
    all_evidence = [e for r in results for e in r.evidence]
    _unique, dedup_report = prov.deduplicate(all_evidence)
    source_conc = prov.source_concentration(all_evidence)

    # -- 3. weights (explainable) -----------------------------------------
    weights = _weights(results, dedup_report, source_conc)

    # -- 4. aggregate vote with RISK_BLOCK precedence ---------------------
    vote, risk_block, rb_reason, agg_expl = _aggregate_vote(results, weights)

    # -- 5. preserve minority + tail warnings -----------------------------
    tail_warnings = [f"[{r.lens}] {r.tail_warning}" for r in results if r.tail_warning]
    # Minority = the least common non-error vote, surfaced so it is not buried.
    vote_counts: dict[str, int] = {}
    for r in results:
        if not r.error:
            vote_counts[r.advisory_vote] = vote_counts.get(r.advisory_vote, 0) + 1
    minority_warnings = []
    if len(vote_counts) > 1:
        minority_vote = min(vote_counts, key=vote_counts.get)
        for r in results:
            if r.advisory_vote == minority_vote and not r.error:
                minority_warnings.append(
                    f"[{r.lens}] minority view ({minority_vote}): {r.main_risk}"
                )

    # -- 6. aggregate scalar summaries ------------------------------------
    total_w = sum(w.final_weight for w in weights) or 1.0
    wmap = {w.lens: w.final_weight for w in weights}
    agg_conf = sum(r.confidence * wmap.get(r.lens, 0.0) for r in results) / total_w
    agg_robust = sum(r.robustness * wmap.get(r.lens, 0.0) for r in results) / total_w
    agg_fragility = sum(r.fragility * wmap.get(r.lens, 0.0) for r in results) / total_w

    # -- 7. honesty floor: weakest binding evidence label -----------------
    contributing = [r for r in results if wmap.get(r.lens, 0.0) > 0.05 and not r.error]
    simulation_only = True
    if contributing:
        weakest = min(contributing, key=lambda r: EVIDENCE_STRENGTH.get(r.evidence_label, 0.0))
        agg_label = weakest.evidence_label
        simulation_only = all(
            EVIDENCE_STRENGTH.get(r.evidence_label, 0.0) <= EVIDENCE_STRENGTH[EvidenceLabel.SIMULATED_ONLY.value] + 0.15
            for r in contributing
        )
    else:
        agg_label = EvidenceLabel.INSUFFICIENT_DATA.value

    disagreement = _disagreement_class(results, dedup_report, weights, simulation_only)

    # -- 8. missing data + freshness --------------------------------------
    missing = sorted({m for r in results for m in r.missing_data_warnings})
    freshness = obs.freshness_status or FreshnessStatus.UNKNOWN.value

    # -- 9. optional stress suite -----------------------------------------
    stress_results = []
    if run_stress:
        scen_ids = request.scenarios or scenarios.default_scenario_ids()
        scen = [s for sid in scen_ids if (s := scenarios.get_scenario(sid))]
        stress_results = stress.run_stress_suite(
            obs, scen, seed, min(flags.max_runs(), request.max_runs),
            max_scenarios=flags.max_scenarios(),
        )

    # -- 10. counterfactuals + dominant assumptions (from physics lens) ---
    counterfactuals = []
    dominant = []
    for r in results:
        if r.lens == "PHYSICS" and r.detail.get("counterfactuals"):
            from dataclasses import fields  # local import; contracts already loaded
            for cf in r.detail["counterfactuals"]:
                counterfactuals.append(_cf_from_dict(cf))
            dominant = r.detail.get("dominant_assumptions", [])

    agg_expl.append(f"evidence dedup: {dedup_report['unique_evidence']}/{dedup_report['total_evidence']} unique "
                    f"(duplication {dedup_report['duplication_ratio']})")
    agg_expl.append(f"source concentration = {source_conc} (Herfindahl)")
    agg_expl.append(f"aggregate evidence label (weakest binding) = {agg_label}")
    if risk_block:
        agg_expl.append(f"RISK_BLOCK engaged: {rb_reason}")

    usefulness = _usefulness_score(results, dedup_report, disagreement)

    return SimulationCouncilResult(
        run_id=_run_id(request, seed),
        contract_version=CONTRACT_VERSION,
        ticker=request.ticker,
        market=request.market,
        as_of=obs.as_of,
        data_cutoff=obs.data_cutoff,
        seed=seed,
        parent_signal_id=request.parent_signal_id,
        aggregate_vote=vote,
        disagreement_class=disagreement,
        aggregate_confidence=round(_clip(agg_conf), 4),
        evidence_label=agg_label,
        robustness=round(_clip(agg_robust), 4),
        fragility=round(_clip(agg_fragility), 4),
        lens_results=results,
        lens_weights=weights,
        minority_warnings=minority_warnings,
        tail_warnings=tail_warnings,
        stress_results=stress_results,
        counterfactuals=counterfactuals,
        dominant_assumptions=dominant,
        missing_data_warnings=missing,
        freshness_status=freshness,
        risk_block_engaged=risk_block,
        risk_block_reason=rb_reason if risk_block else "",
        simulation_only=simulation_only,
        aggregation_explanation=agg_expl,
        engine_availability=engine_availability_map(),
        usefulness_score=usefulness,
    )


def _cf_from_dict(cf: dict) -> Any:
    try:
        from scripts.simulation_intelligence.contracts import CounterfactualBranch
    except ModuleNotFoundError:  # pragma: no cover
        from simulation_intelligence.contracts import CounterfactualBranch  # type: ignore[no-redef]
    return CounterfactualBranch(
        branch_id=cf.get("branch_id", ""),
        changed_assumption=cf.get("changed_assumption", ""),
        from_value=cf.get("from_value", 0.0),
        to_value=cf.get("to_value", 0.0),
        baseline_outcome=cf.get("baseline_outcome", 0.0),
        branch_outcome=cf.get("branch_outcome", 0.0),
        delta=cf.get("delta", 0.0),
        dominant=cf.get("dominant", False),
    )


__all__ = ["run_council"]
