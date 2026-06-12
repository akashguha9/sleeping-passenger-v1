"""Lifecycle attribution + calibration ledger: the verdict must explain
itself now and answer for itself later.

Two instruments, one goal — falsifiability:

* **Attribution** perturbs each lifecycle component (half-life,
  threshold, crowding, carrying capacity, belief gap, convergence,
  break risk, hedge cost, catalyst timing) and reruns the PURE
  ``assess_edge_lifecycle`` function. ``Δ_verdict = rank(baseline) −
  rank(perturbed)`` classifies every assumption as VERDICT_CRITICAL
  (a binding penalty), KILL_SWITCH (an adverse twist that demotes the
  thesis), SCORE_MOVER, or COSMETIC (in the explanation, not in the
  cause). Fragility = flips / perturbations; concentration risk =
  max |Δrank| / rank span.

* **Calibration ledger** records what the lifecycle PREDICTED at entry
  (edge, expiry date, K, convergence probability, hedge structure) and
  computes errors when the thesis RESOLVES: calibration error
  |E_pred − E_real|, expiry error |t_pred − t_actual_death| with an
  expired-before-resolution flag, K error |K_est − K_real| / K_real,
  signed convergence overconfidence P_pred − 1[converged], and hedge
  effectiveness = drawdown avoided / (upside sacrificed + cost).

Deliberately NOT duplicated: ``counterfactual_wind_tunnel`` perturbs
the raw physics payload and attributes the ADAPTATION gate through full
pipeline re-runs; this module perturbs the lifecycle section and
attributes the LIFECYCLE verdict through the pure assessor — different
gate, different inputs, ~100× cheaper. Probability calibration stays in
``calibration_bridge``/``dice_audit``; this ledger owns only the
lifecycle-specific quantities those layers cannot see (expiry, K,
convergence, hedge). Every record carries a data tier — synthetic
fixtures are labeled synthetic, and thin ledgers say
``require_more_data`` instead of pretending. ADVISORY_ONLY throughout.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from src.strategy.edge_lifecycle import assess_edge_lifecycle
from src.utils.math_utils import clamp01, safe_div
from src.utils.validation_utils import coerce_float, normalized_score

# Verdict ordering: higher rank = more actionable. Used only to sign
# attribution deltas, never to promote anything.
VERDICT_RANKS: dict[str, int] = {
    "decayed_below_threshold": 0,
    "saturating_compounder": 1,
    "priced_in": 1,
    "potential_without_catalyst": 2,
    "watch_and_revalidate": 3,
    "live_underpriced_acceleration": 4,
}
_RANK_SPAN = 4.0

VERDICT_CRITICAL = "VERDICT_CRITICAL"  # removing this penalty promotes
KILL_SWITCH = "KILL_SWITCH"            # this twist going wrong demotes
SCORE_MOVER = "SCORE_MOVER"            # verdict holds, score moves
COSMETIC = "COSMETIC"                  # in the explanation, not the cause

SCORE_MOVER_EPSILON = 0.5  # opportunity-score points (0..10 scale)
# >= 4 of 16 single-assumption twists flipping the verdict marks a
# fragile thesis: a golden state with four kill switches is a different
# animal from a robust one, and the operator should know which they own.
FRAGILITY_WARN = 0.25


@dataclass(slots=True)
class LifecyclePerturbation:
    """One assumption changed; what happened to the verdict."""

    name: str
    direction: str  # favorable (penalty removed) | adverse (twist worsened)
    changed_fields: list[str]
    baseline_verdict: str
    perturbed_verdict: str
    rank_delta: int  # rank(perturbed) − rank(baseline); + = promoted
    opportunity_delta: float
    classification: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class LifecycleAttribution:
    """Causal sensitivity map for one lifecycle verdict."""

    baseline_verdict: str
    baseline_opportunity: float
    fragility: float  # verdict flips / perturbations
    concentration_risk: float  # max |Δrank| / rank span
    verdict_critical: list[str] = field(default_factory=list)
    kill_switches: list[str] = field(default_factory=list)
    score_movers: list[str] = field(default_factory=list)
    cosmetic: list[str] = field(default_factory=list)
    perturbations: list[LifecyclePerturbation] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["perturbations"] = [p.to_dict() for p in self.perturbations]
        return payload


def _set(path: str, value: Any) -> Callable[[dict], None]:
    """Mutator for ``sub.key`` or top-level ``key`` lifecycle fields."""
    def mutate(section: dict) -> None:
        if "." in path:
            sub_name, key = path.split(".", 1)
            sub = dict(section.get(sub_name) or {})
            sub[key] = value
            section[sub_name] = sub
        else:
            section[path] = value
    return mutate


def _scale(path: str, factor: float, default: float) -> Callable[[dict], None]:
    def mutate(section: dict) -> None:
        if "." in path:
            sub_name, key = path.split(".", 1)
            sub = dict(section.get(sub_name) or {})
            sub[key] = coerce_float(sub.get(key, default), default) * factor
            section[sub_name] = sub
        else:
            section[path] = coerce_float(
                section.get(path, default), default
            ) * factor
    return mutate


def _perturbation_specs() -> list[dict[str, Any]]:
    """The mission's questions as deterministic single-assumption twists.

    ``favorable`` removes a penalty (a promotion proves the penalty was
    binding — VERDICT_CRITICAL); ``adverse`` worsens one assumption (a
    demotion exposes a thesis KILL_SWITCH)."""

    def remove_capacity_penalty(section: dict) -> None:
        section["capacity"] = {
            **(section.get("capacity") or {}),
            "current_scale": 0.15, "market_penetration": 0.0,
            "tam_evidence": 0.8, "claimed_growth_rate": 0.1,
            "growth_rate_trend": [],
        }

    def close_belief_gap(section: dict) -> None:
        arb = dict(section.get("arbitrage") or {})
        arb["priced_belief"] = coerce_float(arb.get("reality_score"))
        section["arbitrage"] = arb

    def widen_belief_gap(section: dict) -> None:
        arb = dict(section.get("arbitrage") or {})
        arb["priced_belief"] = max(
            coerce_float(arb.get("reality_score")) - 0.35, 0.0
        )
        section["arbitrage"] = arb

    def raise_hedge_cost(section: dict) -> None:
        hedge = dict(section.get("hedge") or {})
        hedge["hedge_cost"] = min(
            coerce_float(hedge.get("thesis_edge"), 0.5) + 0.2, 1.0
        )
        section["hedge"] = hedge

    def delay_catalyst(section: dict) -> None:
        path = dict(section.get("path") or {})
        path["catalyst_proximity_days"] = coerce_float(
            path.get("catalyst_proximity_days"), 30.0
        ) + 60.0
        section["path"] = path

    return [
        # -- favorable: which penalties are actually binding? -----------
        dict(name="extend_half_life", direction="favorable",
             mutate=_scale("half_life_days", 2.0, 30.0),
             fields=["half_life_days"]),
        dict(name="lower_threshold", direction="favorable",
             mutate=_scale("threshold", 0.5, 0.25), fields=["threshold"]),
        dict(name="restore_live_edge", direction="favorable",
             mutate=_set("live_edge", 0.85), fields=["live_edge"]),
        dict(name="remove_crowding", direction="favorable",
             mutate=_set("crowding", 0.0), fields=["crowding"]),
        dict(name="remove_break_risk", direction="favorable",
             mutate=_set("arbitrage.break_risk", 0.0),
             fields=["arbitrage.break_risk"]),
        dict(name="remove_hedge_cost", direction="favorable",
             mutate=_set("hedge.hedge_cost", 0.0),
             fields=["hedge.hedge_cost"]),
        dict(name="remove_capacity_penalty", direction="favorable",
             mutate=remove_capacity_penalty, fields=["capacity.*"]),
        dict(name="widen_belief_gap", direction="favorable",
             mutate=widen_belief_gap, fields=["arbitrage.priced_belief"]),
        dict(name="strengthen_catalyst", direction="favorable",
             mutate=_set("path.catalyst_strength", 0.85),
             fields=["path.catalyst_strength"]),
        # -- adverse: which assumptions, if wrong, kill the thesis? -----
        dict(name="halve_half_life", direction="adverse",
             mutate=_scale("half_life_days", 0.5, 30.0),
             fields=["half_life_days"]),
        dict(name="close_belief_gap", direction="adverse",
             mutate=close_belief_gap, fields=["arbitrage.priced_belief"]),
        dict(name="flip_narrative_to_consensus", direction="adverse",
             mutate=_set("crowding", 0.85), fields=["crowding"]),
        dict(name="shrink_carrying_capacity", direction="adverse",
             mutate=_set("capacity.market_penetration", 0.9),
             fields=["capacity.market_penetration"]),
        dict(name="weaken_convergence", direction="adverse",
             mutate=_set("arbitrage.convergence_probability", 0.15),
             fields=["arbitrage.convergence_probability"]),
        dict(name="raise_hedge_cost", direction="adverse",
             mutate=raise_hedge_cost, fields=["hedge.hedge_cost"]),
        dict(name="delay_catalyst", direction="adverse",
             mutate=delay_catalyst,
             fields=["path.catalyst_proximity_days"]),
    ]


def attribute_lifecycle_verdict(
    section: dict,
    *,
    derived: dict | None = None,
) -> LifecycleAttribution:
    """Rerun the pure lifecycle assessor under single-assumption twists.

    Cheap by design (no pipeline re-runs): ~16 calls to
    ``assess_edge_lifecycle`` on a deep-copied section with the same
    self-fed ``derived`` context the baseline saw.
    """
    baseline = assess_edge_lifecycle(dict(section or {}), derived=derived)
    base_rank = VERDICT_RANKS.get(baseline.verdict, 2)

    perturbations: list[LifecyclePerturbation] = []
    critical: list[str] = []
    kills: list[str] = []
    movers: list[str] = []
    cosmetic: list[str] = []
    flips = 0
    max_shift = 0

    for spec in _perturbation_specs():
        variant_section = copy.deepcopy(dict(section or {}))
        spec["mutate"](variant_section)
        variant = assess_edge_lifecycle(variant_section, derived=derived)
        rank_delta = VERDICT_RANKS.get(variant.verdict, 2) - base_rank
        opportunity_delta = round(
            variant.opportunity_score - baseline.opportunity_score, 2
        )
        flipped = variant.verdict != baseline.verdict
        if flipped:
            flips += 1
            max_shift = max(max_shift, abs(rank_delta))
        if flipped and spec["direction"] == "favorable" and rank_delta > 0:
            classification = VERDICT_CRITICAL
            critical.append(spec["name"])
        elif flipped and spec["direction"] == "adverse" and rank_delta < 0:
            classification = KILL_SWITCH
            kills.append(spec["name"])
        elif flipped:
            # A favorable twist that demotes (or adverse that promotes)
            # still flips the verdict; count it as critical sensitivity.
            classification = VERDICT_CRITICAL
            critical.append(spec["name"])
        elif abs(opportunity_delta) >= SCORE_MOVER_EPSILON:
            classification = SCORE_MOVER
            movers.append(spec["name"])
        else:
            classification = COSMETIC
            cosmetic.append(spec["name"])
        perturbations.append(LifecyclePerturbation(
            name=spec["name"],
            direction=spec["direction"],
            changed_fields=list(spec["fields"]),
            baseline_verdict=baseline.verdict,
            perturbed_verdict=variant.verdict,
            rank_delta=rank_delta,
            opportunity_delta=opportunity_delta,
            classification=classification,
        ))

    fragility = round(flips / len(perturbations), 4)
    concentration = round(max_shift / _RANK_SPAN, 4)
    rationale = [
        f"baseline '{baseline.verdict}' survived "
        f"{len(perturbations) - flips}/{len(perturbations)} "
        f"single-assumption twists; fragility {fragility:.2f}, "
        f"concentration risk {concentration:.2f}",
        (
            "kill switches (assumptions that must hold): "
            + ", ".join(kills)
            if kills else
            "no adverse twist demoted the verdict — the thesis does not "
            "hang on one assumption"
        ),
        (
            "cosmetic inputs (in the explanation, not the cause): "
            + ", ".join(cosmetic)
            if cosmetic else "every input moved the verdict or the score"
        ),
        "weights behind COSMETIC inputs are unsupported by verdict "
        "evidence at this operating point — candidates for the "
        "calibration ledger to confirm or retire",
    ]
    return LifecycleAttribution(
        baseline_verdict=baseline.verdict,
        baseline_opportunity=baseline.opportunity_score,
        fragility=fragility,
        concentration_risk=concentration,
        verdict_critical=critical,
        kill_switches=kills,
        score_movers=movers,
        cosmetic=cosmetic,
        perturbations=perturbations,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Calibration ledger
# ---------------------------------------------------------------------------

DATA_TIERS: tuple[str, ...] = (
    "synthetic_fixture", "backtest_replay", "empirical",
)
LEDGER_MIN_RECORDS = 10  # below this, summaries say so instead of scoring


@dataclass(slots=True)
class LifecycleLedgerEntry:
    """What the lifecycle PREDICTED at entry — the falsifiable half."""

    entry_id: str
    ticker: str
    data_tier: str  # synthetic_fixture | backtest_replay | empirical
    verdict_at_entry: str
    predicted_edge: float
    threshold: float
    predicted_days_to_expiry: float
    k_estimated: float
    ceiling_utilization: float
    convergence_probability: float
    expected_convergence_days: float
    hedge_cost: float
    unwanted_exposure: float
    narrative_phase_at_entry: str = ""
    crowding_at_entry: float = 0.0
    fragility_at_entry: float | None = None
    kill_switches: list[str] = field(default_factory=list)
    entered_at: str = ""
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ResolvedLifecycleRecord:
    """Entry + outcome + the errors that make the model falsifiable."""

    entry: LifecycleLedgerEntry
    resolved_after_days: float
    realized_edge: float
    calibration_error: float  # |predicted edge − realized edge|
    actual_edge_death_day: float | None
    expiry_error: float | None  # |t_pred − t_actual_death|
    expired_before_resolution: bool
    converged: bool
    actual_convergence_day: float | None
    convergence_score: float  # P_pred − 1[converged]; + = overconfident
    k_realized: float | None
    k_error: float | None  # |K_est − K_real| / K_real
    hedge_effectiveness: float | None
    verdict_at_exit: str
    narrative_phase_at_resolution: str
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["entry"] = self.entry.to_dict()
        return payload


def entry_from_lifecycle(
    lifecycle: dict[str, Any],
    *,
    entry_id: str,
    ticker: str,
    data_tier: str = "synthetic_fixture",
    expected_convergence_days: float = 0.0,
    narrative_phase: str = "",
    crowding: float = 0.0,
    attribution: dict[str, Any] | None = None,
    entered_at: str = "",
) -> LifecycleLedgerEntry:
    """Build a ledger entry straight from a pipeline ``lifecycle`` dict —
    the same call real OHLCV/outcome ingestion will use later."""
    tier = data_tier if data_tier in DATA_TIERS else "synthetic_fixture"
    expiry = dict(lifecycle.get("expiry") or {})
    capacity = dict(lifecycle.get("capacity") or {})
    arbitrage = dict(lifecycle.get("arbitrage") or {})
    hedge = dict(lifecycle.get("hedge") or {})
    attribution = dict(attribution or lifecycle.get("attribution") or {})
    return LifecycleLedgerEntry(
        entry_id=str(entry_id),
        ticker=str(ticker).upper(),
        data_tier=tier,
        verdict_at_entry=str(lifecycle.get("verdict", "")),
        predicted_edge=coerce_float(expiry.get("live_edge")),
        threshold=coerce_float(expiry.get("threshold")),
        predicted_days_to_expiry=coerce_float(
            expiry.get("days_to_expiry")
        ),
        k_estimated=coerce_float(capacity.get("k_proxy")),
        ceiling_utilization=coerce_float(
            capacity.get("ceiling_utilization")
        ),
        convergence_probability=coerce_float(
            arbitrage.get("convergence_probability")
        ),
        expected_convergence_days=coerce_float(expected_convergence_days),
        hedge_cost=coerce_float(hedge.get("hedge_cost")),
        unwanted_exposure=coerce_float(hedge.get("unwanted_exposure")),
        narrative_phase_at_entry=str(narrative_phase),
        crowding_at_entry=normalized_score(crowding),
        fragility_at_entry=(
            coerce_float(attribution["fragility"])
            if "fragility" in attribution else None
        ),
        kill_switches=list(attribution.get("kill_switches") or []),
        entered_at=str(entered_at),
    )


def resolve_entry(
    entry: LifecycleLedgerEntry,
    *,
    resolved_after_days: float,
    realized_edge: float,
    actual_edge_death_day: float | None = None,
    converged: bool = False,
    actual_convergence_day: float | None = None,
    k_realized: float | None = None,
    drawdown_avoided: float = 0.0,
    upside_sacrificed: float = 0.0,
    verdict_at_exit: str = "",
    narrative_phase_at_resolution: str = "",
) -> ResolvedLifecycleRecord:
    """Score one prediction against its resolution. Every formula is the
    mission's, verbatim; None means 'not observable', never 'fine'."""
    resolved_after = max(coerce_float(resolved_after_days), 0.0)
    realized = normalized_score(realized_edge)
    calibration_error = round(abs(entry.predicted_edge - realized), 4)

    death = (
        max(coerce_float(actual_edge_death_day), 0.0)
        if actual_edge_death_day is not None else None
    )
    expiry_error = (
        round(abs(entry.predicted_days_to_expiry - death), 2)
        if death is not None else None
    )
    expired_before_resolution = (
        death is not None and death < resolved_after
    )
    convergence_score = round(
        entry.convergence_probability - (1.0 if converged else 0.0), 4
    )
    k_real = (
        clamp01(coerce_float(k_realized)) if k_realized is not None
        else None
    )
    k_error = (
        round(safe_div(abs(entry.k_estimated - k_real), max(k_real, 1e-6)),
              4)
        if k_real is not None else None
    )
    hedge_denominator = (
        normalized_score(upside_sacrificed) + entry.hedge_cost
    )
    hedge_effectiveness = (
        round(safe_div(normalized_score(drawdown_avoided),
                       hedge_denominator), 4)
        if hedge_denominator > 0 else None
    )

    rationale = [
        f"edge: predicted {entry.predicted_edge:.2f} vs realized "
        f"{realized:.2f} (calibration error {calibration_error:.2f})",
        (
            f"expiry: predicted {entry.predicted_days_to_expiry:.1f}d vs "
            f"actual death {death:.1f}d (error {expiry_error:.1f}d)"
            + ("; edge DIED before resolution — the clock was the "
               "binding constraint" if expired_before_resolution else "")
            if death is not None
            else "expiry: actual edge death not observed"
        ),
        f"convergence: P={entry.convergence_probability:.2f} vs "
        f"{'converged' if converged else 'did not converge'} "
        f"(signed overconfidence {convergence_score:+.2f})",
        f"data tier: {entry.data_tier}"
        + (" — synthetic; proves the plumbing, not the model"
           if entry.data_tier == "synthetic_fixture" else ""),
    ]
    if hedge_effectiveness is not None:
        rationale.append(
            f"hedge effectiveness {hedge_effectiveness:.2f} = drawdown "
            "avoided / (upside sacrificed + cost)"
            + (" — the hedge cost more than it protected"
               if hedge_effectiveness < 1.0 else "")
        )
    return ResolvedLifecycleRecord(
        entry=entry,
        resolved_after_days=resolved_after,
        realized_edge=realized,
        calibration_error=calibration_error,
        actual_edge_death_day=death,
        expiry_error=expiry_error,
        expired_before_resolution=expired_before_resolution,
        converged=bool(converged),
        actual_convergence_day=(
            coerce_float(actual_convergence_day)
            if actual_convergence_day is not None else None
        ),
        convergence_score=convergence_score,
        k_realized=k_real,
        k_error=k_error,
        hedge_effectiveness=hedge_effectiveness,
        verdict_at_exit=str(verdict_at_exit),
        narrative_phase_at_resolution=str(narrative_phase_at_resolution),
        rationale=rationale,
    )


def summarize_ledger(
    records: list[ResolvedLifecycleRecord],
) -> dict[str, Any]:
    """Aggregate resolved records honestly: thin ledgers report
    ``require_more_data``; the tier is the WORST tier present (one
    synthetic row keeps the whole summary synthetic)."""
    count = len(records)
    tier = "empirical"
    for record in records:
        tier_index = DATA_TIERS.index(record.entry.data_tier)
        if tier_index < DATA_TIERS.index(tier):
            tier = record.entry.data_tier

    def _mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    summary: dict[str, Any] = {
        "count": count,
        "data_tier": tier if count else "no_data",
        "status": (
            "require_more_data" if count < LEDGER_MIN_RECORDS else "scored"
        ),
        "mean_calibration_error": _mean(
            [r.calibration_error for r in records]
        ),
        "mean_expiry_error": _mean(
            [r.expiry_error for r in records if r.expiry_error is not None]
        ),
        "mean_k_error": _mean(
            [r.k_error for r in records if r.k_error is not None]
        ),
        "mean_convergence_overconfidence": _mean(
            [r.convergence_score for r in records]
        ),
        "mean_hedge_effectiveness": _mean(
            [r.hedge_effectiveness for r in records
             if r.hedge_effectiveness is not None]
        ),
        "expired_before_resolution_rate": (
            round(sum(1 for r in records if r.expired_before_resolution)
                  / count, 4) if count else None
        ),
        "advisory_status": "ADVISORY_ONLY",
    }
    summary["rationale"] = [
        f"{count} resolved record(s) at tier '{summary['data_tier']}'"
        + ("; below the floor of "
           f"{LEDGER_MIN_RECORDS} — errors reported, conclusions withheld"
           if count < LEDGER_MIN_RECORDS else ""),
        "lifecycle weights stay doctrine-derived until this ledger is "
        "scored on backtest_replay or empirical tiers — synthetic rows "
        "prove the plumbing, never the model",
    ]
    return summary
