"""Lens ablation + marginal-contribution analysis — the Kanté mechanism.

Measures the *invisible work* of each lens: how much worse, more fragile, or
less informed does the council become when a lens is absent? A lens that rarely
changes the headline vote can still be elite if it consistently reduces
uncertainty, preserves tail warnings, or adds orthogonal coverage.

Method (all deterministic, bounded):
1. Run the full council.
2. Leave-one-out: remove each lens, re-run aggregation, measure concrete deltas.
3. Characteristic value v(S) over lens coalitions.
4. Shapley value: EXACT for <=6 lenses (2^n subsets, bounded, labelled exact),
   Monte-Carlo permutation APPROX above that (labelled approximate with bounds).
5. Pairwise interaction contributions when the workload budget allows.

Stress is disabled during ablation runs so the 2^n coalition sweep stays cheap.
Prevented-failure claims elsewhere are grounded on these executable ablations —
never on imagined prevention.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

try:
    from scripts.simulation_intelligence.contracts import (
        SimulationRequest, MarketObservation, AdvisoryVote, VOTE_DEFENSIVENESS,
    )
    from scripts.simulation_intelligence.council import run_council
    from scripts.simulation_intelligence.lenses import LENS_DOMAINS
    from scripts.simulation_intelligence import provenance as prov
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        SimulationRequest, MarketObservation, AdvisoryVote, VOTE_DEFENSIVENESS,
    )
    from simulation_intelligence.council import run_council  # type: ignore[no-redef]
    from simulation_intelligence.lenses import LENS_DOMAINS  # type: ignore[no-redef]
    from simulation_intelligence import provenance as prov  # type: ignore[no-redef]


# Hard bound: exact Shapley is only computed up to this many lenses (2^n runs).
_EXACT_SHAPLEY_MAX_LENSES = 6
# Monte-Carlo permutation samples when we fall back to approximate Shapley.
_APPROX_SHAPLEY_SAMPLES = 64


@dataclass(slots=True)
class LensMarginalContribution:
    lens: str
    vote_changed: bool
    baseline_vote: str
    ablated_vote: str
    confidence_delta: float
    robustness_delta: float
    fragility_delta: float
    uncertainty_delta: float
    tail_warning_lost: int          # tail warnings present in full, gone when ablated
    risk_block_lost: bool           # risk block engaged in full, gone when ablated
    coverage_loss: float            # unique-evidence fraction lost
    evidence_diversity_loss: float  # distinct source_keys lost
    decision_stability_delta: float
    shapley_value: float
    shapley_exact: bool
    marginal_summary: str

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


@dataclass(slots=True)
class InteractionContribution:
    lens_a: str
    lens_b: str
    interaction: float  # v(AB) - v(A) - v(B) + v(empty); >0 synergy, <0 redundancy
    kind: str           # SYNERGY / REDUNDANCY / INDEPENDENT

    def to_dict(self) -> dict[str, Any]:
        return {"lens_a": self.lens_a, "lens_b": self.lens_b,
                "interaction": self.interaction, "kind": self.kind}


@dataclass(slots=True)
class CouncilAblationResult:
    run_id: str
    baseline_vote: str
    baseline_confidence: float
    baseline_robustness: float
    baseline_fragility: float
    lens_contributions: list[LensMarginalContribution] = field(default_factory=list)
    interactions: list[InteractionContribution] = field(default_factory=list)
    shapley_exact: bool = True
    coalition_evaluations: int = 0
    most_valuable_lens: str = ""
    quietest_valuable_lens: str = ""  # low vote-change but high Shapley (the Kanté)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "baseline_vote": self.baseline_vote,
            "baseline_confidence": self.baseline_confidence,
            "baseline_robustness": self.baseline_robustness,
            "baseline_fragility": self.baseline_fragility,
            "lens_contributions": [c.to_dict() for c in self.lens_contributions],
            "interactions": [i.to_dict() for i in self.interactions],
            "shapley_exact": self.shapley_exact,
            "coalition_evaluations": self.coalition_evaluations,
            "most_valuable_lens": self.most_valuable_lens,
            "quietest_valuable_lens": self.quietest_valuable_lens,
            "notes": self.notes,
        }


def _council_for(request: SimulationRequest, lenses: tuple[str, ...]) -> Any:
    req = SimulationRequest(
        ticker=request.ticker, market=request.market,
        observation=request.observation, scenarios=[], seed=request.seed,
        max_runs=request.max_runs, parent_signal_id=request.parent_signal_id,
        requested_lenses=list(lenses),
    )
    return run_council(req, run_stress=False)


def _unique_evidence(council: Any) -> tuple[int, int]:
    """Return (unique evidence fingerprints, distinct source_keys)."""
    packets = [e for r in council.lens_results for e in r.evidence]
    _uniq, rep = prov.deduplicate(packets)
    keys = set()
    for e in packets:
        for k in getattr(e, "source_keys", []) or []:
            keys.add(k)
    return rep.get("unique_evidence", 0), len(keys)


def _value(council: Any) -> float:
    """Characteristic value v(S) in [0,1]: how well-informed and protected the
    decision is with this lens coalition. Deterministic."""
    n_unique, _keys = _unique_evidence(council)
    coverage = min(1.0, n_unique / 8.0)
    robustness = max(0.0, min(1.0, council.robustness))
    tail = 1.0 if council.tail_warnings else (0.6 if council.risk_block_engaged else 0.4)
    certainty = 1.0 - max(0.0, min(1.0, council.fragility))
    return round(0.30 * coverage + 0.25 * robustness + 0.25 * tail + 0.20 * certainty, 6)


def _shapley_exact(request: SimulationRequest, lenses: tuple[str, ...],
                   value_cache: dict[frozenset, float]) -> dict[str, float]:
    n = len(lenses)
    idx = list(lenses)

    def v(S: frozenset) -> float:
        if S not in value_cache:
            value_cache[S] = _value(_council_for(request, tuple(sorted(S))))
        return value_cache[S]

    fact = [math.factorial(k) for k in range(n + 1)]
    phi: dict[str, float] = {l: 0.0 for l in idx}
    others = [l for l in idx]
    for l in idx:
        rest = [x for x in others if x != l]
        for k in range(len(rest) + 1):
            weight = fact[k] * fact[n - k - 1] / fact[n]
            for S in combinations(rest, k):
                Sf = frozenset(S)
                phi[l] += weight * (v(Sf | {l}) - v(Sf))
    return {l: round(phi[l], 6) for l in idx}


def _shapley_approx(request: SimulationRequest, lenses: tuple[str, ...],
                    value_cache: dict[frozenset, float], samples: int,
                    seed: int) -> dict[str, float]:
    # Deterministic permutation sampling: derive permutations from a seeded LCG
    # (no Math.random / os randomness — reproducible).
    idx = list(lenses)
    n = len(idx)

    def v(S: frozenset) -> float:
        if S not in value_cache:
            value_cache[S] = _value(_council_for(request, tuple(sorted(S))))
        return value_cache[S]

    state = (seed * 2654435761 + 1) & 0xFFFFFFFF
    def _rand() -> int:
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        return state

    phi: dict[str, float] = {l: 0.0 for l in idx}
    for _ in range(samples):
        perm = idx[:]
        for i in range(n - 1, 0, -1):
            j = _rand() % (i + 1)
            perm[i], perm[j] = perm[j], perm[i]
        prefix: frozenset = frozenset()
        vp = v(prefix)
        for l in perm:
            nxt = prefix | {l}
            vn = v(nxt)
            phi[l] += (vn - vp)
            prefix, vp = nxt, vn
    return {l: round(phi[l] / samples, 6) for l in idx}


def run_ablation(request: SimulationRequest, include_interactions: bool = True
                 ) -> CouncilAblationResult:
    """Run leave-one-out + Shapley marginal-contribution analysis."""
    obs = request.observation or MarketObservation(ticker=request.ticker,
                                                   market=request.market)
    all_lenses = tuple(request.requested_lenses) if request.requested_lenses \
        else tuple(LENS_DOMAINS)
    all_lenses = tuple(l.upper() for l in all_lenses)

    full = _council_for(request, all_lenses)
    base_vote = full.aggregate_vote
    base_conf = full.aggregate_confidence
    base_rob = full.robustness
    base_frag = full.fragility
    base_uncert = sum(r.uncertainty for r in full.lens_results) / max(1, len(full.lens_results))
    base_tail = len(full.tail_warnings)
    base_rb = full.risk_block_engaged
    base_uniq, base_keys = _unique_evidence(full)

    value_cache: dict[frozenset, float] = {}
    exact = len(all_lenses) <= _EXACT_SHAPLEY_MAX_LENSES
    if exact:
        shapley = _shapley_exact(request, all_lenses, value_cache)
    else:
        shapley = _shapley_approx(request, all_lenses, value_cache,
                                  _APPROX_SHAPLEY_SAMPLES, request.seed)

    contribs: list[LensMarginalContribution] = []
    for lens in all_lenses:
        others = tuple(l for l in all_lenses if l != lens)
        ab = _council_for(request, others)
        ab_uncert = sum(r.uncertainty for r in ab.lens_results) / max(1, len(ab.lens_results))
        ab_uniq, ab_keys = _unique_evidence(ab)
        vote_changed = ab.aggregate_vote != base_vote
        stability = 1.0 - abs(
            VOTE_DEFENSIVENESS.get(ab.aggregate_vote, 0)
            - VOTE_DEFENSIVENESS.get(base_vote, 0)
        ) / 4.0
        summary_bits = []
        if vote_changed:
            summary_bits.append(f"removing {lens} flips vote {base_vote}→{ab.aggregate_vote}")
        if base_tail and len(ab.tail_warnings) < base_tail:
            summary_bits.append("tail warning lost")
        if base_rb and not ab.risk_block_engaged:
            summary_bits.append("risk block lost")
        if base_uniq - ab_uniq > 0:
            summary_bits.append(f"{base_uniq - ab_uniq} unique evidence lost")
        if not summary_bits:
            summary_bits.append("quiet contributor: no headline change, "
                                f"Shapley={shapley.get(lens, 0.0)}")
        contribs.append(LensMarginalContribution(
            lens=lens, vote_changed=vote_changed, baseline_vote=base_vote,
            ablated_vote=ab.aggregate_vote,
            confidence_delta=round(base_conf - ab.aggregate_confidence, 4),
            robustness_delta=round(base_rob - ab.robustness, 4),
            fragility_delta=round(base_frag - ab.fragility, 4),
            uncertainty_delta=round(ab_uncert - base_uncert, 4),
            tail_warning_lost=max(0, base_tail - len(ab.tail_warnings)),
            risk_block_lost=bool(base_rb and not ab.risk_block_engaged),
            coverage_loss=round(max(0, base_uniq - ab_uniq) / max(1, base_uniq), 4),
            evidence_diversity_loss=round(max(0, base_keys - ab_keys) / max(1, base_keys), 4),
            decision_stability_delta=round(stability, 4),
            shapley_value=shapley.get(lens, 0.0),
            shapley_exact=exact,
            marginal_summary="; ".join(summary_bits),
        ))

    interactions: list[InteractionContribution] = []
    if include_interactions and len(all_lenses) <= _EXACT_SHAPLEY_MAX_LENSES:
        def v(S: tuple[str, ...]) -> float:
            key = frozenset(S)
            if key not in value_cache:
                value_cache[key] = _value(_council_for(request, tuple(sorted(S))))
            return value_cache[key]
        empty = v(())
        for a, b in combinations(all_lenses, 2):
            inter = v((a, b)) - v((a,)) - v((b,)) + empty
            kind = "SYNERGY" if inter > 0.01 else ("REDUNDANCY" if inter < -0.01
                                                   else "INDEPENDENT")
            interactions.append(InteractionContribution(
                lens_a=a, lens_b=b, interaction=round(inter, 6), kind=kind))

    # Most valuable = highest Shapley. Quietest-valuable (the Kanté): high Shapley
    # but did NOT change the headline vote.
    ranked = sorted(contribs, key=lambda c: -c.shapley_value)
    most_valuable = ranked[0].lens if ranked else ""
    quiet = [c for c in ranked if not c.vote_changed]
    quietest_valuable = quiet[0].lens if quiet else ""

    notes = [
        f"coalition evaluations: {len(value_cache)}",
        "Shapley " + ("EXACT (2^n subsets, n<=6)" if exact
                      else f"APPROXIMATE (permutation MC, {_APPROX_SHAPLEY_SAMPLES} samples)"),
        "stress disabled during ablation to bound the coalition sweep",
    ]
    return CouncilAblationResult(
        run_id=full.run_id, baseline_vote=base_vote, baseline_confidence=base_conf,
        baseline_robustness=base_rob, baseline_fragility=base_frag,
        lens_contributions=contribs, interactions=interactions,
        shapley_exact=exact, coalition_evaluations=len(value_cache),
        most_valuable_lens=most_valuable, quietest_valuable_lens=quietest_valuable,
        notes=notes,
    )


__all__ = [
    "LensMarginalContribution", "InteractionContribution", "CouncilAblationResult",
    "run_ablation",
]
