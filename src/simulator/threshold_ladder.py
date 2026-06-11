"""Threshold ladder + inflection detector with hysteresis.

States (most restrictive to most permissive review state):

    reject -> archive -> watchlist -> active_watch
        -> buy_candidate -> high_conviction_candidate

plus two interrupt states: ``pit_stop`` (thesis damaged, re-score required)
and ``black_flag`` (driver banned from action language).

Hysteresis: promotion requires clearing the threshold by a margin;
demotion only happens after falling below by the same margin, so tiny
score wobbles cannot flip states (anti-porpoising).

    Inflection Score =
        Δnarrative_velocity + Δsource_diversity + Δvolume_quality
        + Δestimate_revision + Δfiling_evidence - Δcontradiction_pressure
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clip

STATE_REJECT = "reject"
STATE_ARCHIVE = "archive"
STATE_WATCHLIST = "watchlist"
STATE_ACTIVE_WATCH = "active_watch"
STATE_BUY_CANDIDATE = "buy_candidate"
STATE_HIGH_CONVICTION = "high_conviction_candidate"
STATE_PIT_STOP = "pit_stop"
STATE_BLACK_FLAG = "black_flag"

LADDER_STATES: tuple[str, ...] = (
    STATE_REJECT,
    STATE_ARCHIVE,
    STATE_WATCHLIST,
    STATE_ACTIVE_WATCH,
    STATE_BUY_CANDIDATE,
    STATE_HIGH_CONVICTION,
)

INTERRUPT_STATES: tuple[str, ...] = (STATE_PIT_STOP, STATE_BLACK_FLAG)

# Base entry thresholds on the 0–100 final-candidate-score scale.
# Multiplied by the circuit threshold multiplier before use.
BASE_STATE_THRESHOLDS: dict[str, float] = {
    STATE_ARCHIVE: 15.0,
    STATE_WATCHLIST: 35.0,
    STATE_ACTIVE_WATCH: 50.0,
    STATE_BUY_CANDIDATE: 65.0,
    STATE_HIGH_CONVICTION: 80.0,
}

HYSTERESIS_MARGIN = 3.0


@dataclass(slots=True)
class InflectionScore:
    """Rate-of-change turning-point score (deltas in [-1, 1])."""

    score: float
    components: dict[str, float] = field(default_factory=dict)
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class LadderDecision:
    """Resolved ladder state with the gates that constrained it."""

    state: str
    eligible_state: str
    score: float
    previous_state: str | None
    thresholds_used: dict[str, float] = field(default_factory=dict)
    gate_caps: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def score_inflection(
    *,
    delta_narrative_velocity: float = 0.0,
    delta_source_diversity: float = 0.0,
    delta_volume_quality: float = 0.0,
    delta_estimate_revision: float = 0.0,
    delta_filing_evidence: float = 0.0,
    delta_contradiction_pressure: float = 0.0,
) -> InflectionScore:
    """Inflection score in [-6, +5]: rising change matters more than level."""
    components = {
        "delta_narrative_velocity": clip(delta_narrative_velocity, -1.0, 1.0),
        "delta_source_diversity": clip(delta_source_diversity, -1.0, 1.0),
        "delta_volume_quality": clip(delta_volume_quality, -1.0, 1.0),
        "delta_estimate_revision": clip(delta_estimate_revision, -1.0, 1.0),
        "delta_filing_evidence": clip(delta_filing_evidence, -1.0, 1.0),
        "delta_contradiction_pressure": clip(delta_contradiction_pressure, -1.0, 1.0),
    }
    score = (
        components["delta_narrative_velocity"]
        + components["delta_source_diversity"]
        + components["delta_volume_quality"]
        + components["delta_estimate_revision"]
        + components["delta_filing_evidence"]
        - components["delta_contradiction_pressure"]
    )
    reasons: list[str] = []
    if score >= 1.5:
        reasons.append("POSITIVE_INFLECTION")
    elif score <= -1.5:
        reasons.append("NEGATIVE_INFLECTION")
    else:
        reasons.append("NO_CLEAR_INFLECTION")
    if (
        components["delta_narrative_velocity"] >= 0.5
        and components["delta_filing_evidence"] <= 0.0
    ):
        reasons.append("POSSIBLE_FALSE_INFLECTION")
    return InflectionScore(score=score, components=components, reason_codes=reasons)


def _eligible_state(score: float, thresholds: dict[str, float]) -> str:
    state = STATE_REJECT
    for candidate in LADDER_STATES[1:]:
        if score >= thresholds[candidate]:
            state = candidate
    return state


def resolve_ladder_state(
    *,
    score: float,
    previous_state: str | None = None,
    circuit_threshold_multiplier: float = 1.0,
    meal_box_complete: bool = False,
    crash_gate_passed: bool = True,
    grip_gate_passed: bool = True,
    data_quality_gate_passed: bool = True,
    hard_conviction_allowed: bool = True,
    scrutineering_passed: bool = True,
    thesis_damaged: bool = False,
    driver_black_flag: bool = False,
    hysteresis_margin: float = HYSTERESIS_MARGIN,
) -> LadderDecision:
    """Resolve the candidate's ladder state from score + gates + hysteresis.

    Gates cap the maximum state regardless of score:
      * missing fire extinguisher (meal box)  -> at most active_watch
      * crash gate failed                     -> at most watchlist
      * grip gate failed (stale signals)      -> at most watchlist
      * data quality failed                   -> at most watchlist
      * scrutineering failed (input physics)  -> at most watchlist
      * hard conviction blocked               -> at most buy_candidate
      * thesis damaged                        -> pit_stop (interrupt)
      * driver black flag                     -> black_flag (interrupt)
    """
    multiplier = clip(circuit_threshold_multiplier, 0.5, 2.0)
    thresholds = {
        state: base * multiplier for state, base in BASE_STATE_THRESHOLDS.items()
    }

    if driver_black_flag:
        return LadderDecision(
            state=STATE_BLACK_FLAG,
            eligible_state=STATE_BLACK_FLAG,
            score=float(score),
            previous_state=previous_state,
            thresholds_used=thresholds,
            gate_caps=["driver_black_flag"],
            reason_codes=["BLACK_FLAG_INTERRUPT"],
        )
    if thesis_damaged:
        return LadderDecision(
            state=STATE_PIT_STOP,
            eligible_state=STATE_PIT_STOP,
            score=float(score),
            previous_state=previous_state,
            thresholds_used=thresholds,
            gate_caps=["thesis_damaged"],
            reason_codes=["PIT_STOP_RESCORE_REQUIRED"],
        )

    raw_eligible = _eligible_state(float(score), thresholds)

    # Hysteresis relative to a valid previous ladder state.
    state = raw_eligible
    reasons: list[str] = []
    if previous_state in LADDER_STATES:
        prev_idx = LADDER_STATES.index(previous_state)
        raw_idx = LADDER_STATES.index(raw_eligible)
        if raw_idx > prev_idx:
            # Promote only when the next rung is cleared by the margin.
            promoted = previous_state
            for candidate in LADDER_STATES[prev_idx + 1 : raw_idx + 1]:
                if float(score) >= thresholds[candidate] + hysteresis_margin:
                    promoted = candidate
                else:
                    break
            if promoted != raw_eligible:
                reasons.append("HYSTERESIS_HELD_PROMOTION")
            state = promoted
        elif raw_idx < prev_idx:
            # Demote only when below the previous rung's threshold by margin.
            prev_threshold = thresholds.get(previous_state, 0.0)
            if float(score) > prev_threshold - hysteresis_margin:
                state = previous_state
                reasons.append("HYSTERESIS_HELD_DEMOTION")

    caps: list[str] = []

    def _cap(max_state: str, label: str) -> None:
        nonlocal state
        if LADDER_STATES.index(state) > LADDER_STATES.index(max_state):
            state = max_state
            caps.append(label)

    if not data_quality_gate_passed:
        _cap(STATE_WATCHLIST, "data_quality_gate")
    if not grip_gate_passed:
        _cap(STATE_WATCHLIST, "grip_gate")
    if not crash_gate_passed:
        _cap(STATE_WATCHLIST, "crash_gate")
    if not scrutineering_passed:
        # A car that fails technical inspection holds a provisional result
        # at best — no promotion past watchlist until evidence is real.
        _cap(STATE_WATCHLIST, "scrutineering_gate")
    if not meal_box_complete:
        _cap(STATE_ACTIVE_WATCH, "meal_box_gate")
    if not hard_conviction_allowed:
        _cap(STATE_BUY_CANDIDATE, "hard_conviction_gate")

    if caps:
        reasons.append("GATE_CAPPED")
    reasons.append(f"STATE_{state.upper()}")

    return LadderDecision(
        state=state,
        eligible_state=raw_eligible,
        score=float(score),
        previous_state=previous_state,
        thresholds_used=thresholds,
        gate_caps=caps,
        reason_codes=reasons,
    )
