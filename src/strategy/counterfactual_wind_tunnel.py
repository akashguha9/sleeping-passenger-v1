"""Counterfactual Wind Tunnel: the model doubts itself.

Self-feed made the model consistent with its own physics. This layer
asks the mentor's harder question: would the same verdict survive if
the rally had gone differently?

    Remove the crowding signal — does the exhausted-edge cap still fire?
    Delay the signal a week — does the model become more reckless?
    Strip the obvious narrative — was it bait or the actual driver?
    Make the regime benign — does the cap falsely suppress a good trade?
    Game the inputs — does conservatism survive?

Three instruments:

* **Perturbation suite** — deterministic payload variants (ablations,
  delays, regime flips, gaming probes), each with a falsifiable
  directional expectation, graded against the original verdict.
* **Gate attribution** — when the adaptation gate fired, ablate each
  driver to classify it NECESSARY_DRIVER / SUFFICIENT_DRIVER /
  REDUNDANT_SUPPORT / PASSENGER_SIGNAL, and flag a gate that hangs on
  exactly one input as FRAGILE_SINGLE_POINT.
* **Gate utility classifier** — turns a wind-tunnel A/B gate experiment
  into helpful / harmful / over_conservative / regime_dependent /
  neutral / insufficient_evidence, honestly.

The audit cannot prevent a caller from feeding a falsified payload —
no internal layer can. What it does instead is EXPOSE the gaming
surface: any caller-controlled field whose suppression improves the
verdict is published in ``gameable_inputs``. Risk numbers here are
deterministic heuristic indicators, not fitted probabilities, and every
report carries its validation-tier warnings. ADVISORY_ONLY throughout;
no orders exist anywhere in this system.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from src.simulator.threshold_ladder import LADDER_STATES
from src.utils.math_utils import clamp01

# --- Expectation grammar (falsifiable, graded against the original run) -----
NOT_BETTER = "NOT_BETTER"
NOT_WORSE = "NOT_WORSE"
CAP_FIRES = "CAP_FIRES"
CAP_SILENT = "CAP_SILENT"
WARN_NOT_CAP = "WARN_NOT_CAP"
CHALLENGED_NOT_BETTER = "CHALLENGED_NOT_BETTER"
NO_UNMEASURED_CAP = "NO_UNMEASURED_CAP"
OBSERVED_ONLY = "OBSERVED_ONLY"  # recorded, never graded

# --- Attribution labels -------------------------------------------------------
NECESSARY_DRIVER = "NECESSARY_DRIVER"
SUFFICIENT_DRIVER = "SUFFICIENT_DRIVER"
REDUNDANT_SUPPORT = "REDUNDANT_SUPPORT"
PASSENGER_SIGNAL = "PASSENGER_SIGNAL"
FRAGILE_SINGLE_POINT = "FRAGILE_SINGLE_POINT"
MISSING_BUT_REQUIRED = "MISSING_BUT_REQUIRED"

GATE_CODES = ("EDGE_EXHAUSTED", "FATAL_WEAK_SIDE")
OAI_THRESHOLD = 1.1  # exhausted_edge boundary in adaptive_opponent
THIN_MARGIN = 0.2
PASSENGER_OAI_EPSILON = 0.05


def _ladder_index(state: str) -> int:
    return LADDER_STATES.index(state) if state in LADDER_STATES else -1


def _strip_meta(payload: dict[str, Any]) -> dict[str, Any]:
    """Variants never re-enter the audit (no recursion) and regime
    probes re-enable self-feed — the audit exists to test the gate."""
    payload.pop("counterfactual_audit", None)
    return payload


def _fresh_narrative(payload: dict[str, Any]) -> None:
    payload["narrative"] = {
        "narrative": str(
            (payload.get("narrative") or {}).get("narrative", "thesis")
        ),
        "mention_count": 10, "origin_count": 9,
        "independent_origin_count": 9, "source_quality": 0.8,
        "narrative_velocity": 0.2, "narrative_acceleration": 0.0,
    }


def _strong_signals(payload: dict[str, Any]) -> None:
    payload["signals"] = [
        {**s, "raw_strength": 90.0, "signal_age_hours": 2.0}
        for s in payload.get("signals", []) or [] if isinstance(s, dict)
    ] or [{"signal_type": "backlog", "raw_strength": 90.0,
           "signal_age_hours": 2.0, "source_quality": 0.9}]


# ---------------------------------------------------------------------------
# Perturbation suite
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PerturbationResult:
    """One counterfactual variant, its expectation, and what happened."""

    name: str
    changed_fields: list[str]
    expected_effect: str
    observed_state: str
    observed_gate: str  # "fired" | "silent" | "absent"
    observed_codes: list[str]
    matched: bool | None  # None = OBSERVED_ONLY / not graded
    improved_verdict: bool
    anti_gaming_probe: bool
    provenance: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _perturbation_specs() -> list[dict[str, Any]]:
    """Deterministic variant builders. ``relevant`` guards honesty: a
    perturbation of an absent section proves nothing and is skipped."""

    def has(key: str) -> Callable[[dict], bool]:
        return lambda p: isinstance(p.get(key), dict) and bool(p[key])

    def has_signals(p: dict) -> bool:
        return bool(p.get("signals"))

    def set_theme(field_name: str, value: float) -> Callable[[dict], None]:
        def mutate(p: dict) -> None:
            p["theme_assessment"] = {**p["theme_assessment"],
                                     field_name: value}
        return mutate

    def drop(key: str) -> Callable[[dict], None]:
        def mutate(p: dict) -> None:
            p.pop(key, None)
        return mutate

    def delay_signals(p: dict) -> None:
        p["signals"] = [
            {**s, "signal_age_hours":
             float(s.get("signal_age_hours", 0.0)) + 168.0}
            for s in p.get("signals", []) if isinstance(s, dict)
        ]

    def shift_quality(delta: float) -> Callable[[dict], None]:
        def mutate(p: dict) -> None:
            section = dict(p.get("narrative") or {})
            quality = float(section.get("source_quality", 0.5))
            section["source_quality"] = clamp01(
                max(0.1, min(1.0, quality + delta))
            )
            p["narrative"] = section
        return mutate

    def optimistic_override(p: dict) -> None:
        # Merge, never replace: deleting the caller's declared
        # weaknesses would test evidence omission, not optimism.
        p["opponent"] = {**(p.get("opponent") or {}), "adaptation": {
            "signal_strength": 0.95, "crowding": 0.02,
            "narrative_saturation": 0.02, "repricing_observed": 0.0,
        }}

    def conservative_override(p: dict) -> None:
        p["opponent"] = {**(p.get("opponent") or {}), "adaptation": {
            "signal_strength": 0.1, "crowding": 0.95,
            "narrative_saturation": 0.9, "repricing_observed": 0.9,
        }}

    def missing_engines(p: dict) -> None:
        for key in ("narrative", "theme_assessment", "signals"):
            p.pop(key, None)

    def benign_regime(p: dict) -> None:
        p.pop("self_feed", None)
        p.pop("opponent", None)
        p["theme_assessment"] = {
            **(p.get("theme_assessment") or {}),
            "crowding": 0.1, "valuation_heat": 0.15,
        }
        _fresh_narrative(p)
        p["signals"] = [{"signal_type": "backlog", "raw_strength": 80.0,
                         "signal_age_hours": 24.0, "source_quality": 0.9}]
        p["risk_factors"] = {"high_valuation": 0.15}

    def hostile_regime(p: dict) -> None:
        p.pop("self_feed", None)
        p.pop("opponent", None)
        p["theme_assessment"] = {
            **(p.get("theme_assessment") or {}),
            "crowding": 0.9, "valuation_heat": 0.8,
        }
        p["narrative"] = {
            "narrative": "everyone is in this trade", "mention_count": 150,
            "origin_count": 20, "independent_origin_count": 10,
            "source_quality": 0.6, "narrative_velocity": 0.4,
            "narrative_acceleration": 0.1,
        }
        p["signals"] = [{"signal_type": "backlog", "raw_strength": 30.0,
                         "signal_age_hours": 400.0, "source_quality": 0.6}]

    def noisy_regime(p: dict) -> None:
        hostile_regime(p)
        p["signals"] = []  # exhaustion visible but unmeasured -> warn only

    def opponent_derived(p: dict) -> bool:
        from src.strategy.self_feed import self_feed_enabled

        return (
            self_feed_enabled(p)
            and (has("theme_assessment")(p) or has("narrative")(p))
        )

    return [
        dict(name="ablate_theme_crowding", relevant=has("theme_assessment"),
             mutate=set_theme("crowding", 0.0), expected=NOT_WORSE,
             gaming=True, fields=["theme_assessment.crowding"],
             provenance="suppressing adverse evidence must never worsen "
             "the verdict; if it improves it, the field is gameable"),
        dict(name="ablate_valuation_heat", relevant=has("theme_assessment"),
             mutate=set_theme("valuation_heat", 0.0), expected=NOT_WORSE,
             gaming=True, fields=["theme_assessment.valuation_heat"],
             provenance="repricing evidence removed"),
        dict(name="omit_weaknesses", relevant=has("risk_factors"),
             mutate=drop("risk_factors"), expected=NOT_WORSE, gaming=True,
             fields=["risk_factors"],
             provenance="weak-side severities omitted by the caller"),
        dict(name="inflate_signals", relevant=has_signals,
             mutate=_strong_signals, expected=NOT_WORSE, gaming=True,
             fields=["signals[].raw_strength", "signals[].signal_age_hours"],
             provenance="fresh maximal signals claimed"),
        dict(name="delay_signals", relevant=has_signals,
             mutate=delay_signals, expected=NOT_BETTER, gaming=False,
             fields=["signals[].signal_age_hours"],
             provenance="the same signal arriving a week later (decayed "
             "grip, longer recognition age) must not read better"),
        dict(name="degrade_source_quality", relevant=has("narrative"),
             mutate=shift_quality(-0.4), expected=NOT_BETTER, gaming=False,
             fields=["narrative.source_quality"],
             provenance="less reliable evidence must not read better"),
        dict(name="boost_source_quality", relevant=has("narrative"),
             mutate=shift_quality(+0.3), expected=NOT_WORSE, gaming=False,
             fields=["narrative.source_quality"],
             provenance="more reliable evidence must not read worse"),
        dict(name="remove_prediction_market",
             relevant=has("prediction_market"),
             mutate=drop("prediction_market"), expected=OBSERVED_ONLY,
             gaming=False, fields=["prediction_market"],
             provenance="odds shock removed — direction depends on the "
             "shock's sign, so this is recorded, not graded"),
        dict(name="remove_exposure", relevant=has("exposure"),
             mutate=drop("exposure"), expected=NOT_BETTER, gaming=False,
             fields=["exposure"],
             provenance="losing exposure evidence must not read better"),
        dict(name="suppress_narrative", relevant=has("narrative"),
             mutate=_fresh_narrative, expected=OBSERVED_ONLY, gaming=True,
             fields=["narrative.*"],
             provenance="the obvious narrative goes missing — does the "
             "cap still fire, or was the narrative the whole story?"),
        dict(name="optimistic_opponent_override", relevant=opponent_derived,
             mutate=optimistic_override, expected=CHALLENGED_NOT_BETTER,
             gaming=True, fields=["opponent.adaptation.*"],
             provenance="rosy self-assessment must be cross-examined and "
             "must not rescue the verdict"),
        dict(name="conservative_opponent_override",
             relevant=opponent_derived, mutate=conservative_override,
             expected=NOT_BETTER, gaming=False,
             fields=["opponent.adaptation.*"],
             provenance="caller caution is honored, never rewarded with "
             "a better verdict"),
        dict(name="missing_engine_fallback",
             relevant=lambda p: has("narrative")(p)
             or has("theme_assessment")(p),
             mutate=missing_engines, expected=NO_UNMEASURED_CAP,
             gaming=False,
             fields=["narrative", "theme_assessment", "signals"],
             provenance="engines gone dark must produce warnings, never "
             "a cap built on defaults"),
        dict(name="benign_regime", relevant=lambda p: True,
             mutate=benign_regime, expected=CAP_SILENT, gaming=False,
             fields=["theme_assessment", "narrative", "signals",
                     "risk_factors"],
             provenance="fresh edge, low crowding, strong young signal — "
             "a cap here would be a false positive"),
        dict(name="hostile_regime", relevant=lambda p: True,
             mutate=hostile_regime, expected=CAP_FIRES, gaming=False,
             fields=["theme_assessment", "narrative", "signals"],
             provenance="crowded, saturated, stale weak signal — failing "
             "to cap here would be a false negative"),
        dict(name="noisy_regime", relevant=lambda p: True,
             mutate=noisy_regime, expected=WARN_NOT_CAP, gaming=False,
             fields=["theme_assessment", "narrative", "signals"],
             provenance="hostile numerator but unmeasured signal — must "
             "warn, never cap on a defaulted denominator"),
    ]


def _gate_observation(result: dict[str, Any]) -> tuple[str, list[str]]:
    gate = result["decision"]["gate_results"].get("adaptation_gate")
    codes = list(result["decision"]["reason_codes"])
    if gate is False:
        return "fired", codes
    if gate is True:
        return "silent", codes
    return "absent", codes


def _grade(
    expected: str,
    *,
    variant: dict[str, Any],
    original_index: int,
) -> bool | None:
    state = variant["decision"]["final_state"]
    gate, codes = _gate_observation(variant)
    improved = _ladder_index(state) > original_index
    worsened = _ladder_index(state) < original_index
    if expected == OBSERVED_ONLY:
        return None
    if expected == NOT_BETTER:
        return not improved
    if expected == NOT_WORSE:
        return not worsened
    if expected == CAP_FIRES:
        return gate == "fired" and any(c in codes for c in GATE_CODES)
    if expected == CAP_SILENT:
        return gate != "fired" and not any(c in codes for c in GATE_CODES)
    if expected == WARN_NOT_CAP:
        return gate != "fired" and "SELF_FEED_LOW_COVERAGE" in codes
    if expected == CHALLENGED_NOT_BETTER:
        return "OPPONENT_OVERRIDE_CHALLENGED" in codes and not improved
    if expected == NO_UNMEASURED_CAP:
        # Exhaustion is a measured ratio — with engines dark it cannot
        # legitimately cap. A FATAL_WEAK_SIDE cap from the caller's own
        # judged weaknesses needs no engine and is allowed to stand.
        return "EDGE_EXHAUSTED" not in codes
    raise ValueError(f"unknown expectation {expected!r}")


# ---------------------------------------------------------------------------
# Gate attribution
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class GateAttributionEntry:
    """One driver's causal role in a fired adaptation gate."""

    input_name: str
    classification: str
    sufficient_alone: bool
    fragile: bool
    gate_after_ablation: str
    state_after_ablation: str
    oai_delta: float
    provenance: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_DRIVER_NEUTRALIZERS: list[tuple[str, str]] = [
    ("theme_crowding", "theme_mapper.crowding -> 0"),
    ("valuation_heat", "theme_mapper.valuation_heat -> 0"),
    ("narrative_saturation", "narrative -> fresh low-dirty-air variant"),
    ("signal_weakness", "signals -> strong and 2h fresh"),
    ("weak_side_severity", "risk_factors + opponent weaknesses cleared"),
]


def _neutralize(payload: dict[str, Any], driver: str) -> None:
    if driver == "theme_crowding" and isinstance(
        payload.get("theme_assessment"), dict
    ):
        payload["theme_assessment"] = {
            **payload["theme_assessment"], "crowding": 0.0,
        }
    elif driver == "valuation_heat" and isinstance(
        payload.get("theme_assessment"), dict
    ):
        payload["theme_assessment"] = {
            **payload["theme_assessment"], "valuation_heat": 0.0,
        }
        risks = payload.get("risk_factors")
        if isinstance(risks, dict):
            payload["risk_factors"] = {
                k: v for k, v in risks.items() if k != "price_already_ran"
            }
    elif driver == "narrative_saturation" and isinstance(
        payload.get("narrative"), dict
    ):
        _fresh_narrative(payload)
    elif driver == "signal_weakness" and payload.get("signals"):
        _strong_signals(payload)
    elif driver == "weak_side_severity":
        payload.pop("risk_factors", None)
        opponent = payload.get("opponent")
        if isinstance(opponent, dict):
            opponent = dict(opponent)
            opponent.pop("weaknesses", None)
            opponent["attack_probability"] = 0.1
            payload["opponent"] = opponent


def _driver_relevant(payload: dict[str, Any], driver: str) -> bool:
    if driver in ("theme_crowding", "valuation_heat"):
        return isinstance(payload.get("theme_assessment"), dict) and bool(
            payload["theme_assessment"]
        )
    if driver == "narrative_saturation":
        return isinstance(payload.get("narrative"), dict) and bool(
            payload["narrative"]
        )
    if driver == "signal_weakness":
        return bool(payload.get("signals"))
    if driver == "weak_side_severity":
        return bool(payload.get("risk_factors")) or bool(
            isinstance(payload.get("opponent"), dict)
            and (payload["opponent"] or {}).get("weaknesses")
        )
    return False


def attribute_adaptation_gate(
    payload: dict[str, Any],
    original: dict[str, Any],
    evaluate: Callable[[dict[str, Any]], dict[str, Any]],
) -> list[GateAttributionEntry]:
    """Ablate each driver of a FIRED adaptation gate to learn its causal
    role. ``GateAttribution(input) = gate(original) - gate(ablated)``:
    necessary if ablation disables the gate, redundant if the gate holds
    while the OAI moves, passenger if nothing moves, sufficient if the
    driver alone (all others neutralized) still fires it."""
    gate, codes = _gate_observation(original)
    if gate != "fired" or not any(c in codes for c in GATE_CODES):
        return []
    original_oai = float(
        ((original.get("opponent") or {}).get("adaptation") or {})
        .get("oai", 0.0)
    )

    entries: list[GateAttributionEntry] = []
    necessary: list[str] = []
    for driver, provenance in _DRIVER_NEUTRALIZERS:
        if not _driver_relevant(payload, driver):
            entries.append(GateAttributionEntry(
                input_name=driver,
                classification=MISSING_BUT_REQUIRED,
                sufficient_alone=False, fragile=False,
                gate_after_ablation="not_tested",
                state_after_ablation="not_tested", oai_delta=0.0,
                provenance=f"{provenance}; input absent — untestable",
            ))
            continue
        ablated_payload = _strip_meta(copy.deepcopy(payload))
        _neutralize(ablated_payload, driver)
        ablated = evaluate(ablated_payload)
        ablated_gate, _ = _gate_observation(ablated)
        ablated_oai = float(
            ((ablated.get("opponent") or {}).get("adaptation") or {})
            .get("oai", 0.0)
        )
        oai_delta = original_oai - ablated_oai

        # Sufficiency: keep this driver, neutralize every other one.
        alone_payload = _strip_meta(copy.deepcopy(payload))
        for other, _p in _DRIVER_NEUTRALIZERS:
            if other != driver and _driver_relevant(alone_payload, other):
                _neutralize(alone_payload, other)
        alone = evaluate(alone_payload)
        alone_gate, _ = _gate_observation(alone)
        sufficient = alone_gate == "fired"

        if ablated_gate != "fired":
            classification = NECESSARY_DRIVER
            necessary.append(driver)
        elif abs(oai_delta) >= PASSENGER_OAI_EPSILON:
            classification = REDUNDANT_SUPPORT
        else:
            classification = PASSENGER_SIGNAL
        if sufficient and classification != NECESSARY_DRIVER:
            classification = SUFFICIENT_DRIVER

        entries.append(GateAttributionEntry(
            input_name=driver,
            classification=classification,
            sufficient_alone=sufficient,
            fragile=False,
            gate_after_ablation=ablated_gate,
            state_after_ablation=str(ablated["decision"]["final_state"]),
            oai_delta=round(oai_delta, 4),
            provenance=provenance,
        ))

    if len(necessary) == 1:
        for entry in entries:
            if entry.input_name == necessary[0]:
                entry.fragile = True  # the gate hangs on one input
    return entries


# ---------------------------------------------------------------------------
# Gate utility (for wind-tunnel A/B experiments)
# ---------------------------------------------------------------------------

UTILITY_HELPFUL = "helpful"
UTILITY_HARMFUL = "harmful"
UTILITY_NEUTRAL = "neutral"
UTILITY_INSUFFICIENT = "insufficient_evidence"
UTILITY_OVER_CONSERVATIVE = "over_conservative"
UTILITY_REGIME_DEPENDENT = "regime_dependent"

_UTILITY_EPSILON = 0.005


def classify_gate_utility(experiment: Any) -> str:
    """Label a ``GateExperimentReport``. GateUtility is the forward-return
    difference the cap pointed at (``capped_return_disadvantage``); a gate
    that mostly caps winners is over_conservative even if the mean looks
    fine, and a gate that never diverged has proven nothing."""
    disadvantage = experiment.capped_return_disadvantage
    if disadvantage is None:
        return UTILITY_INSUFFICIENT
    capped = experiment.capped_cohort
    share = (
        experiment.divergent_count / experiment.decision_count
        if experiment.decision_count
        else 0.0
    )
    if share >= 0.5 and (capped.win_rate or 0.0) >= 0.6:
        return UTILITY_OVER_CONSERVATIVE
    if disadvantage > _UTILITY_EPSILON:
        return UTILITY_HELPFUL
    if disadvantage < -_UTILITY_EPSILON:
        return UTILITY_HARMFUL
    if capped.count >= 2 and 0.0 < (capped.win_rate or 0.0) < 1.0:
        return UTILITY_REGIME_DEPENDENT
    return UTILITY_NEUTRAL


# ---------------------------------------------------------------------------
# The audit
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CounterfactualReport:
    """Counterfactual robustness + causal attribution for one payload."""

    robustness_score: float
    graded_count: int
    matched_count: int
    gate_fired: bool
    gate_margin: float | None
    gate_utility: str
    false_positive_risk: float
    false_negative_risk: float
    fragility_count: int
    overconfidence_penalty: float
    fragile_inputs: list[str] = field(default_factory=list)
    necessary_drivers: list[str] = field(default_factory=list)
    sufficient_drivers: list[str] = field(default_factory=list)
    redundant_supports: list[str] = field(default_factory=list)
    passenger_signals: list[str] = field(default_factory=list)
    gameable_inputs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    perturbations: list[PerturbationResult] = field(default_factory=list)
    attribution: list[GateAttributionEntry] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["perturbations"] = [p.to_dict() for p in self.perturbations]
        payload["attribution"] = [a.to_dict() for a in self.attribution]
        return payload


def run_counterfactual_audit(
    payload: dict[str, Any],
    original: dict[str, Any] | None = None,
) -> CounterfactualReport:
    """Perturb, ablate, and stress one payload's evidence.

    RobustnessScore = matched / graded − FragilityPenalty −
    OverconfidencePenalty. Gaming probes that IMPROVE the verdict land
    in ``gameable_inputs`` (the audit exposes the gaming surface; it
    cannot police the world outside the payload). Risk numbers are
    deterministic heuristics, not probabilities.
    """
    from src.simulator.pipeline import evaluate_candidate_payload

    base_payload = _strip_meta(copy.deepcopy(payload))
    if original is None:
        original = evaluate_candidate_payload(copy.deepcopy(base_payload))
    original_index = _ladder_index(original["decision"]["final_state"])
    original_gate, original_codes = _gate_observation(original)
    gate_fired = original_gate == "fired" and any(
        c in original_codes for c in GATE_CODES
    )
    oai = (
        float(((original.get("opponent") or {}).get("adaptation") or {})
              .get("oai", 0.0))
        if original.get("opponent")
        else None
    )
    gate_margin = (
        round(oai - OAI_THRESHOLD, 4) if oai is not None else None
    )

    perturbations: list[PerturbationResult] = []
    gameable: list[str] = []
    breaches: list[str] = []
    for spec in _perturbation_specs():
        if not spec["relevant"](base_payload):
            continue
        variant_payload = _strip_meta(copy.deepcopy(base_payload))
        spec["mutate"](variant_payload)
        variant = evaluate_candidate_payload(variant_payload)
        matched = _grade(
            spec["expected"], variant=variant, original_index=original_index
        )
        gate, codes = _gate_observation(variant)
        improved = (
            _ladder_index(variant["decision"]["final_state"])
            > original_index
        )
        if spec["gaming"] and improved:
            gameable.append(spec["name"])
        if spec["name"] == "optimistic_opponent_override" and improved:
            breaches.append("optimistic override improved the verdict")
        perturbations.append(PerturbationResult(
            name=spec["name"],
            changed_fields=list(spec["fields"]),
            expected_effect=spec["expected"],
            observed_state=str(variant["decision"]["final_state"]),
            observed_gate=gate,
            observed_codes=[
                c for c in codes
                if c in GATE_CODES + (
                    "SELF_FEED_LOW_COVERAGE", "OPPONENT_OVERRIDE_CHALLENGED",
                    "OPPONENT_SELF_FED",
                )
            ],
            matched=matched,
            improved_verdict=improved,
            anti_gaming_probe=bool(spec["gaming"]),
            provenance=str(spec["provenance"]),
        ))

    attribution = attribute_adaptation_gate(
        base_payload, original, evaluate_candidate_payload
    )
    necessary = [
        a.input_name for a in attribution
        if a.classification == NECESSARY_DRIVER
    ]
    sufficient = [a.input_name for a in attribution if a.sufficient_alone]
    redundant = [
        a.input_name for a in attribution
        if a.classification == REDUNDANT_SUPPORT
    ]
    passengers = [
        a.input_name for a in attribution
        if a.classification == PASSENGER_SIGNAL
    ]
    fragile = [a.input_name for a in attribution if a.fragile]

    graded = [p for p in perturbations if p.matched is not None]
    matched_count = sum(1 for p in graded if p.matched)
    base_score = matched_count / len(graded) if graded else 0.0
    fragility_penalty = 0.1 if fragile else 0.0
    overconfidence_penalty = 0.15 * len(breaches)
    robustness = clamp01(
        base_score - fragility_penalty - overconfidence_penalty
    )

    by_name = {p.name: p for p in perturbations}
    benign_capped = (
        by_name.get("benign_regime") is not None
        and by_name["benign_regime"].matched is False
    )
    hostile_missed = (
        by_name.get("hostile_regime") is not None
        and by_name["hostile_regime"].matched is False
    )
    thin = gate_fired and gate_margin is not None and (
        gate_margin < THIN_MARGIN
    )
    false_positive_risk = round(
        0.85 if benign_capped else (0.25 if thin else 0.1), 4
    )
    false_negative_risk = round(
        0.85 if hostile_missed
        else min(0.4, 0.1 + 0.05 * len(gameable)), 4
    )

    warnings: list[str] = []
    data_source = str(payload.get("data_source", "caller_payload"))
    if data_source in ("caller_payload", "fixture_replay"):
        warnings += ["SYNTHETIC_REPLAY_TIER", "LOW_REAL_WORLD_CALIBRATION"]
    elif data_source == "backtest_replay":
        warnings.append("BACKTEST_TIER_NOT_EMPIRICAL")
    if thin:
        warnings.append("GATE_MARGIN_THIN")
    if fragile:
        warnings.append("FRAGILE_SINGLE_POINT")
    for name in gameable:
        warnings.append(f"VERDICT_SENSITIVE_TO_CALLER_INPUT:{name}")
    if breaches:
        warnings.append("ANTI_GAMING_BREACH")
    coverage = (
        float((original.get("opponent") or {})
              .get("self_feed", {}).get("coverage", 0.0))
        if original.get("opponent")
        else 0.0
    )
    if coverage < 1.0:
        warnings.append("LOW_COVERAGE_WARNING")

    rationale = [
        f"{matched_count}/{len(graded)} graded counterfactuals matched "
        f"expectation; robustness {robustness:.2f} after fragility "
        f"penalty {fragility_penalty:.2f} and overconfidence penalty "
        f"{overconfidence_penalty:.2f}",
        (
            f"adaptation gate fired with OAI margin {gate_margin:+.2f}; "
            f"necessary drivers: {', '.join(necessary) or 'none'}"
            if gate_fired
            else "adaptation gate silent — attribution not applicable; "
            "regime probes cover latent sensitivity"
        ),
        "gate utility requires an A/B bar replay — see "
        "wind_tunnel.run_gate_experiment + classify_gate_utility",
        "the audit exposes the gaming surface; it cannot verify the "
        "world outside the payload",
    ]
    if gameable:
        rationale.append(
            "caller-controlled fields that would improve the verdict if "
            "suppressed/inflated: " + ", ".join(gameable)
        )

    return CounterfactualReport(
        robustness_score=round(robustness, 4),
        graded_count=len(graded),
        matched_count=matched_count,
        gate_fired=gate_fired,
        gate_margin=gate_margin,
        gate_utility=UTILITY_INSUFFICIENT,
        false_positive_risk=false_positive_risk,
        false_negative_risk=false_negative_risk,
        fragility_count=len(fragile),
        overconfidence_penalty=round(overconfidence_penalty, 4),
        fragile_inputs=fragile,
        necessary_drivers=necessary,
        sufficient_drivers=sufficient,
        redundant_supports=redundant,
        passenger_signals=passengers,
        gameable_inputs=gameable,
        warnings=warnings,
        perturbations=perturbations,
        attribution=attribution,
        rationale=rationale,
    )
