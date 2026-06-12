"""Self-Feed: the model feeds itself.

The adaptive opponent model asked callers to judge crowding, repricing,
saturation, signal strength, weaknesses — numbers the pipeline's own
engines were ALREADY computing two steps earlier. This layer wires those
engines into the ``opponent`` section automatically:

    theme_mapper.crowding            -> opponent crowding
    theme_mapper.valuation_heat      -> repricing observed
    narrative_tracker state + dirty
      air                            -> narrative saturation
    signal_tyres blended grip        -> live signal strength
    signal_tyres age / half-life     -> recognition age / edge half-life
    crash risk_factors (incl. the
      consent bridge's injections)   -> weak-side severities
    exposure_resolver components     -> named strengths + capabilities

Every derived value carries provenance (engine.field) — no hidden magic.

Anti-gaming asymmetry (scrutineering style): a caller may always
override a derived value toward CONSERVATISM unchallenged. A caller's
more OPTIMISTIC override loses to the derived value, and the rejected
override is recorded as a challenge — the opponent section is
cross-examined against the caller's own physics payload. Gaming inputs
can only make the verdict more conservative.

Honesty rules: a value is derived only when the engine's own inputs
were actually present in the payload (an absent theme section proves
nothing about crowding). Auto-derived data may gate the ladder only
when coverage of the four adaptation drivers is high; thin derivations
are report-only. ADVISORY_ONLY throughout; no orders exist anywhere.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.simulator.exposure_resolver import ExposureAssessment
from src.simulator.narrative_tracker import NarrativeStatus
from src.simulator.signal_tyres import TyreState, blended_grip_pct
from src.simulator.theme_mapper import ThemeAssessment
from src.utils.math_utils import clamp01
from src.utils.validation_utils import coerce_float, normalized_score

# Fraction of the four adaptation drivers (signal, repricing, crowding,
# saturation) that must be engine-backed before self-fed data may gate.
GATE_COVERAGE_FLOOR = 0.75

# A caller override this much more optimistic than the derived value is
# recorded as a challenge (smaller gaps still resolve conservatively).
CHALLENGE_GAP = 0.20

# Narrative state -> saturation base (blended with dirty air below).
_STATE_SATURATION: dict[str, float] = {
    "ignored": 0.05,
    "early_stir": 0.15,
    "emerging": 0.30,
    "accelerating": 0.50,
    "crowded": 0.75,
    "overheated": 0.90,
    "decaying": 0.60,
    "broken": 0.50,
}

# Scalar opponent fields where the LARGER value is the conservative one.
_HIGHER_IS_CONSERVATIVE = frozenset({
    "crowding", "attack_probability", "repricing_observed",
    "narrative_saturation", "recognition_age_days",
})
# Scalar opponent fields where the SMALLER value is the conservative one.
_LOWER_IS_CONSERVATIVE = frozenset({
    "evidence_reliability", "durability", "signal_strength",
    "cost_to_exploit", "edge_half_life_days",
})

_ADAPTATION_FIELDS = frozenset({
    "signal_strength", "repricing_observed", "crowding",
    "narrative_saturation", "recognition_age_days", "edge_half_life_days",
})


@dataclass(slots=True)
class OverrideChallenge:
    """One optimistic caller override rejected in favor of engine data."""

    field_name: str
    caller_value: float
    derived_value: float
    derived_from: str
    resolution: str = "conservative_engine_value_used"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class SelfFeedReport:
    """How the opponent section was wired: derived, merged, challenged."""

    enabled: bool
    auto_derived: bool  # True when the caller supplied NO opponent section
    coverage: float  # engine-backed fraction of the 4 adaptation drivers
    gate_eligible: bool  # may purely self-fed data cap the ladder?
    derived: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)
    challenges: list[OverrideChallenge] = field(default_factory=list)
    merged_section: dict[str, Any] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["challenges"] = [c.to_dict() for c in self.challenges]
        return payload


def self_feed_enabled(payload: dict[str, Any]) -> bool:
    """The layer is on by default; ``{"self_feed": {"enabled": false}}``
    restores the caller-judgement-only path."""
    section = payload.get("self_feed")
    if isinstance(section, dict) and "enabled" in section:
        return bool(section["enabled"])
    return True


def derive_opponent_inputs(
    *,
    narrative: NarrativeStatus | None,
    theme: ThemeAssessment | None,
    tyres: list[TyreState],
    exposure: ExposureAssessment | None,
    risk_factors: dict[str, float],
    narrative_present: bool,
    theme_present: bool,
    exposure_present: bool,
    risk_factors_present: bool,
    adjusted_signal_strength: float | None = None,
) -> tuple[dict[str, Any], dict[str, str], float]:
    """Derive opponent-section inputs from engines that already ran.

    Returns ``(derived_section, provenance, coverage)``. A field is
    derived only when the engine's inputs were genuinely present —
    defaults proving optimism would be fabrication, not derivation.
    """
    derived: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    adaptation: dict[str, Any] = {}
    drivers_covered = 0

    if theme_present and theme is not None:
        adaptation["crowding"] = clamp01(theme.crowding)
        provenance["adaptation.crowding"] = "theme_mapper.crowding"
        derived["crowding"] = clamp01(theme.crowding)
        provenance["crowding"] = "theme_mapper.crowding"
        drivers_covered += 1

        repricing = clamp01(theme.valuation_heat)
        repricing_source = "theme_mapper.valuation_heat"
        if risk_factors_present:
            already_ran = clamp01(
                coerce_float(risk_factors.get("price_already_ran"))
            )
            if already_ran > repricing:
                repricing = already_ran
                repricing_source = "risk_factors.price_already_ran"
        adaptation["repricing_observed"] = repricing
        provenance["adaptation.repricing_observed"] = repricing_source
        drivers_covered += 1

    if narrative_present and narrative is not None:
        state_base = _STATE_SATURATION.get(narrative.narrative_state, 0.5)
        saturation = clamp01(
            0.6 * state_base + 0.4 * narrative.dirty_air_score
        )
        adaptation["narrative_saturation"] = saturation
        provenance["adaptation.narrative_saturation"] = (
            "narrative_tracker.state+dirty_air"
        )
        drivers_covered += 1

        derived["evidence_reliability"] = clamp01(narrative.source_quality)
        provenance["evidence_reliability"] = (
            "narrative_tracker.source_quality"
        )

    if tyres:
        strongest = max(t.effective_signal_strength for t in tyres)
        signal_strength = clamp01(strongest / 100.0)
        signal_source = "signal_tyres.effective_signal_strength"
        # The signal refiner's independence haircut wins when LOWER:
        # echoes are not evidence, and the merge is conservative-only.
        if adjusted_signal_strength is not None:
            refined = clamp01(adjusted_signal_strength)
            if refined < signal_strength:
                signal_strength = refined
                signal_source = "signal_refiner.adjusted_strength"
        adaptation["signal_strength"] = signal_strength
        provenance["adaptation.signal_strength"] = signal_source
        drivers_covered += 1

        oldest_age_hours = max(t.signal_age_hours for t in tyres)
        adaptation["recognition_age_days"] = oldest_age_hours / 24.0
        provenance["adaptation.recognition_age_days"] = (
            "signal_tyres.signal_age_hours"
        )
        mean_half_life = sum(
            t.adjusted_half_life_hours for t in tyres
        ) / len(tyres)
        adaptation["edge_half_life_days"] = max(mean_half_life / 24.0, 0.5)
        provenance["adaptation.edge_half_life_days"] = (
            "signal_tyres.adjusted_half_life_hours"
        )
        grip = blended_grip_pct(tyres) / 100.0
        provenance["signal_grip_context"] = (
            f"signal_tyres.blended_grip_pct={grip:.2f}"
        )

    if risk_factors_present and risk_factors:
        derived["weaknesses"] = {
            str(name): normalized_score(value)
            for name, value in risk_factors.items()
            if coerce_float(value) > 0
        }
        provenance["weaknesses"] = (
            "crash_simulator.risk_factors (consent bridge included)"
        )

    crowd = adaptation.get("crowding")
    saturation = adaptation.get("narrative_saturation")
    if crowd is not None and saturation is not None:
        derived["attack_probability"] = clamp01(
            0.5 * crowd + 0.5 * saturation
        )
        provenance["attack_probability"] = (
            "0.5*theme.crowding + 0.5*narrative_saturation"
        )

    if exposure_present and exposure is not None:
        strengths = {
            "supply_chain_position": exposure.supply_chain_position,
            "customer_lock_in": exposure.customer_linkage,
            "margin_strength": exposure.margin_sensitivity,
        }
        if narrative_present and narrative is not None:
            strengths["narrative_momentum"] = clamp01(
                narrative.narrative_velocity
            )
        derived["strengths"] = {
            k: clamp01(v) for k, v in strengths.items() if v > 0
        }
        provenance["strengths"] = (
            "exposure_resolver components (+narrative velocity)"
        )
        derived["capabilities"] = {
            "revenue": exposure.revenue_exposure,
            "margin": exposure.margin_sensitivity,
            "backlog": exposure.backlog_linkage,
            "customer": exposure.customer_linkage,
            "geo": exposure.geographic_fit,
            "supply_chain": exposure.supply_chain_position,
        }
        provenance["capabilities"] = "exposure_resolver components"
        derived["durability"] = clamp01(
            0.3
            + 0.4 * exposure.supply_chain_position
            + 0.3 * exposure.backlog_linkage
        )
        provenance["durability"] = (
            "0.3 + 0.4*supply_chain_position + 0.3*backlog_linkage"
        )

    if adaptation:
        derived["adaptation"] = adaptation
    coverage = drivers_covered / 4.0
    return derived, provenance, coverage


def _merge_scalar(
    field_name: str,
    caller_value: Any,
    derived_value: float,
    provenance: dict[str, str],
    challenges: list[OverrideChallenge],
    *,
    prefix: str = "",
) -> float:
    """Conservative-wins merge for one scalar; optimistic overrides are
    recorded as challenges and lose to the engine-derived value."""
    caller = coerce_float(caller_value)
    key = f"{prefix}{field_name}"
    if field_name in _HIGHER_IS_CONSERVATIVE:
        conservative = max(caller, derived_value)
        optimistic_gap = derived_value - caller
    else:  # lower is conservative
        conservative = min(caller, derived_value)
        optimistic_gap = caller - derived_value
    if optimistic_gap >= CHALLENGE_GAP:
        challenges.append(
            OverrideChallenge(
                field_name=key,
                caller_value=caller,
                derived_value=derived_value,
                derived_from=provenance.get(key, "engine_derived"),
            )
        )
    return conservative


def merge_with_caller(
    derived: dict[str, Any],
    caller_section: dict[str, Any],
    provenance: dict[str, str],
) -> tuple[dict[str, Any], list[OverrideChallenge]]:
    """Merge a caller's opponent section with the engine-derived one.

    Conservative wins field by field. Caller-only judgements (niche,
    catalyst_plus_one, fields no engine computed) pass through untouched
    — the layer cross-examines what it can verify, nothing more.
    """
    merged = {
        k: v for k, v in caller_section.items()
        if k not in ("adaptation",)
    }
    challenges: list[OverrideChallenge] = []

    for field_name in _HIGHER_IS_CONSERVATIVE | _LOWER_IS_CONSERVATIVE:
        if field_name in _ADAPTATION_FIELDS:
            continue
        if field_name not in derived:
            continue
        if field_name in caller_section:
            merged[field_name] = _merge_scalar(
                field_name, caller_section[field_name],
                float(derived[field_name]), provenance, challenges,
            )
        else:
            merged[field_name] = derived[field_name]

    # Weaknesses: per-key max severity; an omitted engine-evidenced
    # weakness (severity >= 0.5) is itself an optimistic override.
    derived_weak = dict(derived.get("weaknesses") or {})
    caller_weak = dict(caller_section.get("weaknesses") or {})
    if derived_weak or caller_weak:
        merged_weak: dict[str, float] = {}
        for name in set(derived_weak) | set(caller_weak):
            d_val = coerce_float(derived_weak.get(name))
            c_val = coerce_float(caller_weak.get(name))
            merged_weak[name] = max(d_val, c_val)
            if name in derived_weak and (
                (name in caller_weak and d_val - c_val >= CHALLENGE_GAP)
                or (name not in caller_weak and d_val >= 0.5)
            ):
                challenges.append(
                    OverrideChallenge(
                        field_name=f"weaknesses.{name}",
                        caller_value=c_val,
                        derived_value=d_val,
                        derived_from=provenance.get(
                            "weaknesses", "crash_simulator.risk_factors"
                        ),
                    )
                )
        merged["weaknesses"] = merged_weak

    # Strengths: per-key min when both exist (claiming a stronger weapon
    # than the physics shows is optimistic); caller-only strengths pass
    # through as research judgement.
    derived_strong = dict(derived.get("strengths") or {})
    caller_strong = dict(caller_section.get("strengths") or {})
    if derived_strong or caller_strong:
        merged_strong = dict(caller_strong)
        for name, d_val in derived_strong.items():
            if name in caller_strong:
                c_val = coerce_float(caller_strong[name])
                merged_strong[name] = min(float(d_val), c_val)
                if c_val - float(d_val) >= CHALLENGE_GAP:
                    challenges.append(
                        OverrideChallenge(
                            field_name=f"strengths.{name}",
                            caller_value=c_val,
                            derived_value=float(d_val),
                            derived_from=provenance.get(
                                "strengths", "exposure_resolver"
                            ),
                        )
                    )
            else:
                merged_strong[name] = float(d_val)
        merged["strengths"] = merged_strong

    if "capabilities" in derived and "capabilities" not in caller_section:
        merged["capabilities"] = derived["capabilities"]

    # Adaptation drivers: scalar conservative-wins inside the subsection.
    derived_adaptation = dict(derived.get("adaptation") or {})
    caller_adaptation = dict(caller_section.get("adaptation") or {})
    if derived_adaptation or caller_adaptation:
        merged_adaptation = dict(caller_adaptation)
        for field_name, d_val in derived_adaptation.items():
            if field_name in caller_adaptation:
                merged_adaptation[field_name] = _merge_scalar(
                    field_name, caller_adaptation[field_name],
                    float(d_val), provenance, challenges,
                    prefix="adaptation.",
                )
            else:
                merged_adaptation[field_name] = d_val
        merged["adaptation"] = merged_adaptation

    return merged, challenges


def build_self_fed_opponent(
    payload: dict[str, Any],
    *,
    narrative: NarrativeStatus | None,
    theme: ThemeAssessment | None,
    tyres: list[TyreState],
    exposure: ExposureAssessment | None,
    adjusted_signal_strength: float | None = None,
) -> SelfFeedReport:
    """Wire the opponent section from engine outputs + caller overrides."""
    caller_section = payload.get("opponent")
    caller_section = (
        dict(caller_section) if isinstance(caller_section, dict) else {}
    )
    if not self_feed_enabled(payload):
        return SelfFeedReport(
            enabled=False,
            auto_derived=False,
            coverage=0.0,
            gate_eligible=bool(caller_section),
            merged_section=caller_section,
            rationale=[
                "self-feed disabled by payload flag — caller-judgement path"
            ],
        )

    risk_section = payload.get("risk_factors")
    risk_factors = (
        {str(k): coerce_float(v) for k, v in risk_section.items()}
        if isinstance(risk_section, dict)
        else {}
    )

    derived, provenance, coverage = derive_opponent_inputs(
        narrative=narrative,
        theme=theme,
        tyres=tyres,
        exposure=exposure,
        risk_factors=risk_factors,
        narrative_present=isinstance(payload.get("narrative"), dict)
        and bool(payload.get("narrative")),
        theme_present=isinstance(payload.get("theme_assessment"), dict)
        and bool(payload.get("theme_assessment")),
        exposure_present=exposure is not None
        and exposure.exposure_score > 0,
        risk_factors_present=bool(risk_factors),
        adjusted_signal_strength=adjusted_signal_strength,
    )

    auto_derived = not caller_section
    if auto_derived:
        merged, challenges = dict(derived), []
    else:
        merged, challenges = merge_with_caller(
            derived, caller_section, provenance
        )

    # Caller-supplied sections always carry gate authority (the caller
    # asked the question); purely self-fed data needs coverage.
    gate_eligible = bool(caller_section) or coverage >= GATE_COVERAGE_FLOOR

    rationale = [
        f"self-feed coverage {coverage:.2f} of 4 adaptation drivers; "
        + (
            "auto-derived (no caller opponent section)"
            if auto_derived
            else f"merged with caller section ({len(challenges)} "
            "optimistic override(s) challenged)"
        ),
        (
            "gate authority: " + (
                "caller section present" if caller_section else (
                    "engine coverage above floor"
                    if gate_eligible
                    else "report-only — coverage below floor, "
                    "self-fed data cannot cap the ladder"
                )
            )
        ),
    ]
    return SelfFeedReport(
        enabled=True,
        auto_derived=auto_derived,
        coverage=coverage,
        gate_eligible=gate_eligible,
        derived=derived,
        provenance=provenance,
        challenges=challenges,
        merged_section=merged,
        rationale=rationale,
    )
