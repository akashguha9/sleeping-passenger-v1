"""Contribution-event ledger — the "match events" behind a role rating.

Football ratings move on individual events (interceptions, recoveries, errors).
This is the system-intelligence equivalent: positive, negative, prevention,
recovery and enabling events, each evidence-linked to an actual run so a rating
can be inspected down to what caused it.

Two anti-gaming rules are baked in:
* **Diminishing returns** — repeated events of the same type for the same
  component contribute geometrically less, so event *volume* cannot inflate a score.
* **Severe-integrity penalties** — a single SEVERE negative event (unsafe
  authority, false evidence grade, leakage, suppressed tail warning, non-
  deterministic replay presented as deterministic) can materially cut a score.

Events are *derived from observable run facts*, never asserted — a prevented
failure requires an executable counterfactual (see ``ablation``), not imagination.

Pure scoring here; persistence lives in ``scripts/persistence.py``.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]


class EventDirection(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


class EventSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"      # integrity failures — can materially cut a rating


class EventClass(str, Enum):
    CONTRIBUTION = "CONTRIBUTION"
    PREVENTION = "PREVENTION"
    RECOVERY = "RECOVERY"
    ENABLING = "ENABLING"


# Event taxonomy: type -> (direction, default_severity, base_value, class, target dim)
# base_value is in "rating points" before diminishing returns / context scaling.
_EVENT_TYPES: dict[str, tuple[str, str, float, str, str]] = {
    # --- positive contributions -----------------------------------------
    "tail_risk_detected": (EventDirection.POSITIVE.value, EventSeverity.MAJOR.value, 1.0, EventClass.PREVENTION.value, "risk_interception"),
    "stale_data_blocked": (EventDirection.POSITIVE.value, EventSeverity.MODERATE.value, 0.8, EventClass.PREVENTION.value, "error_prevention"),
    "missing_data_prevented_false_confidence": (EventDirection.POSITIVE.value, EventSeverity.MODERATE.value, 0.8, EventClass.PREVENTION.value, "error_prevention"),
    "duplicate_evidence_removed": (EventDirection.POSITIVE.value, EventSeverity.MODERATE.value, 0.7, EventClass.CONTRIBUTION.value, "evidence_quality"),
    "correlated_agreement_penalised": (EventDirection.POSITIVE.value, EventSeverity.MAJOR.value, 0.9, EventClass.CONTRIBUTION.value, "evidence_quality"),
    "minority_warning_preserved": (EventDirection.POSITIVE.value, EventSeverity.MODERATE.value, 0.8, EventClass.CONTRIBUTION.value, "role_fidelity"),
    "risk_block_overrode_aggregate": (EventDirection.POSITIVE.value, EventSeverity.MAJOR.value, 1.2, EventClass.PREVENTION.value, "risk_interception"),
    "failing_engine_isolated": (EventDirection.POSITIVE.value, EventSeverity.MODERATE.value, 0.7, EventClass.RECOVERY.value, "recovery_ability"),
    "simulation_timed_out_safely": (EventDirection.POSITIVE.value, EventSeverity.MODERATE.value, 0.7, EventClass.RECOVERY.value, "recovery_ability"),
    "deterministic_replay_matched": (EventDirection.POSITIVE.value, EventSeverity.MODERATE.value, 0.9, EventClass.CONTRIBUTION.value, "consistency"),
    "fragile_assumption_identified": (EventDirection.POSITIVE.value, EventSeverity.MODERATE.value, 0.7, EventClass.CONTRIBUTION.value, "uncertainty_handling"),
    "counterfactual_changed_conclusion": (EventDirection.POSITIVE.value, EventSeverity.MAJOR.value, 1.0, EventClass.CONTRIBUTION.value, "decision_influence"),
    "orthogonal_scenario_surfaced": (EventDirection.POSITIVE.value, EventSeverity.MODERATE.value, 0.8, EventClass.CONTRIBUTION.value, "coverage"),
    "provenance_completed": (EventDirection.POSITIVE.value, EventSeverity.MINOR.value, 0.5, EventClass.CONTRIBUTION.value, "evidence_quality"),
    "runtime_recovered_clean_state": (EventDirection.POSITIVE.value, EventSeverity.MAJOR.value, 0.9, EventClass.RECOVERY.value, "recovery_ability"),
    "false_certainty_reduced": (EventDirection.POSITIVE.value, EventSeverity.MODERATE.value, 0.8, EventClass.PREVENTION.value, "uncertainty_handling"),
    "enabling_downstream_trust": (EventDirection.POSITIVE.value, EventSeverity.MINOR.value, 0.5, EventClass.ENABLING.value, "collaboration"),
    # --- negative contributions -----------------------------------------
    "tail_risk_missed": (EventDirection.NEGATIVE.value, EventSeverity.MAJOR.value, -1.2, EventClass.PREVENTION.value, "risk_interception"),
    "stale_evidence_accepted": (EventDirection.NEGATIVE.value, EventSeverity.MAJOR.value, -1.0, EventClass.PREVENTION.value, "error_prevention"),
    "duplicate_evidence_double_counted": (EventDirection.NEGATIVE.value, EventSeverity.MAJOR.value, -1.0, EventClass.CONTRIBUTION.value, "evidence_quality"),
    "correlated_agreement_as_independent": (EventDirection.NEGATIVE.value, EventSeverity.MAJOR.value, -1.1, EventClass.CONTRIBUTION.value, "evidence_quality"),
    "minority_warning_suppressed": (EventDirection.NEGATIVE.value, EventSeverity.MAJOR.value, -1.0, EventClass.CONTRIBUTION.value, "role_fidelity"),
    "false_risk_block": (EventDirection.NEGATIVE.value, EventSeverity.MODERATE.value, -0.8, EventClass.PREVENTION.value, "error_prevention"),
    "unstable_output": (EventDirection.NEGATIVE.value, EventSeverity.MODERATE.value, -0.8, EventClass.CONTRIBUTION.value, "consistency"),
    "operator_confusing_output": (EventDirection.NEGATIVE.value, EventSeverity.MODERATE.value, -0.8, EventClass.CONTRIBUTION.value, "operator_usefulness"),
    "runtime_orphaned_capability": (EventDirection.NEGATIVE.value, EventSeverity.MAJOR.value, -1.2, EventClass.CONTRIBUTION.value, "runtime_reach"),
    # --- SEVERE integrity failures (materially cut a rating) -------------
    "unsafe_authority": (EventDirection.NEGATIVE.value, EventSeverity.SEVERE.value, -5.0, EventClass.PREVENTION.value, "role_fidelity"),
    "hidden_execution_path": (EventDirection.NEGATIVE.value, EventSeverity.SEVERE.value, -5.0, EventClass.PREVENTION.value, "role_fidelity"),
    "false_evidence_grade": (EventDirection.NEGATIVE.value, EventSeverity.SEVERE.value, -4.0, EventClass.CONTRIBUTION.value, "evidence_quality"),
    "corrupted_persistence": (EventDirection.NEGATIVE.value, EventSeverity.SEVERE.value, -4.0, EventClass.RECOVERY.value, "reliability"),
    "nondeterministic_replay_claimed_deterministic": (EventDirection.NEGATIVE.value, EventSeverity.SEVERE.value, -4.0, EventClass.CONTRIBUTION.value, "consistency"),
    "leakage_detected": (EventDirection.NEGATIVE.value, EventSeverity.SEVERE.value, -4.0, EventClass.CONTRIBUTION.value, "calibration_integrity"),
    "silent_failure": (EventDirection.NEGATIVE.value, EventSeverity.SEVERE.value, -3.5, EventClass.RECOVERY.value, "reliability"),
    "unbounded_execution": (EventDirection.NEGATIVE.value, EventSeverity.SEVERE.value, -3.5, EventClass.RECOVERY.value, "resource_efficiency"),
    "simulated_presented_as_measured": (EventDirection.NEGATIVE.value, EventSeverity.SEVERE.value, -4.0, EventClass.CONTRIBUTION.value, "evidence_quality"),
}

SEVERE_EVENT_TYPES: frozenset[str] = frozenset(
    t for t, (_d, sev, *_r) in _EVENT_TYPES.items() if sev == EventSeverity.SEVERE.value
)


def is_known_event(event_type: str) -> bool:
    return event_type in _EVENT_TYPES


def event_meta(event_type: str) -> tuple[str, str, float, str, str]:
    return _EVENT_TYPES.get(
        event_type,
        (EventDirection.NEUTRAL.value, EventSeverity.MINOR.value, 0.0,
         EventClass.CONTRIBUTION.value, "role_fidelity"),
    )


@dataclass(slots=True)
class ContributionEvent:
    event_id: str
    component_id: str
    run_id: str
    event_type: str
    direction: str
    severity: str
    event_class: str
    target_dimension: str
    base_value: float
    context_difficulty: float = 0.5
    confidence: float = 0.7
    counterfactual_impact: str = ""
    evidence: str = ""
    affected_final_result: bool = False
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__slots__}
        d.update(advisory_safety_stamps())
        return d


def _event_id(component_id: str, run_id: str, event_type: str, ordinal: int) -> str:
    basis = f"{component_id}|{run_id}|{event_type}|{ordinal}"
    return "EV_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]


def make_event(
    component_id: str, run_id: str, event_type: str, *,
    context_difficulty: float = 0.5, confidence: float = 0.7,
    counterfactual_impact: str = "", evidence: str = "",
    affected_final_result: bool = False, ordinal: int = 0, created_at: str = "",
) -> ContributionEvent:
    direction, severity, base_value, ev_class, dim = event_meta(event_type)
    return ContributionEvent(
        event_id=_event_id(component_id, run_id, event_type, ordinal),
        component_id=component_id, run_id=run_id, event_type=event_type,
        direction=direction, severity=severity, event_class=ev_class,
        target_dimension=dim, base_value=base_value,
        context_difficulty=max(0.0, min(1.0, context_difficulty)),
        confidence=max(0.0, min(1.0, confidence)),
        counterfactual_impact=counterfactual_impact, evidence=evidence,
        affected_final_result=affected_final_result, created_at=created_at,
    )


def _diminish(base: float, k: int) -> float:
    """The k-th (0-indexed) event of a type contributes base / (1 + 0.6k).
    Volume cannot inflate: the 5th identical event is worth ~1/3.4 of the first."""
    return base / (1.0 + 0.6 * k)


@dataclass(slots=True)
class LedgerScore:
    component_id: str
    positive_points: float
    negative_points: float
    severe_penalty: float
    net_points: float
    per_dimension: dict[str, float]
    event_count: int
    positive_count: int
    negative_count: int
    severe_count: int
    diminished_count: int
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__slots__}
        d.update(advisory_safety_stamps())
        return d


def score_events(events: list[ContributionEvent]) -> LedgerScore:
    """Aggregate a component's events with diminishing returns + severe penalties.

    Context difficulty scales POSITIVE credit up (handling a hard context is worth
    more) but never scales it purely because the input was bad — the event itself
    must have fired. Negative events are NOT softened by difficulty."""
    if not events:
        return LedgerScore("", 0.0, 0.0, 0.0, 0.0, {}, 0, 0, 0, 0, 0,
                           ["no events"])
    component_id = events[0].component_id
    seen: dict[str, int] = {}
    pos = neg = severe = 0.0
    per_dim: dict[str, float] = {}
    pos_n = neg_n = sev_n = dim_events = 0
    for ev in sorted(events, key=lambda e: (e.event_type, e.event_id)):
        k = seen.get(ev.event_type, 0)
        seen[ev.event_type] = k + 1
        val = _diminish(ev.base_value, k) * ev.confidence
        if ev.direction == EventDirection.POSITIVE.value:
            # Reward harder contexts: up to +50% for an EXTREME context.
            val *= (1.0 + 0.5 * ev.context_difficulty)
            pos += val
            pos_n += 1
            if k > 0:
                dim_events += 1
        elif ev.direction == EventDirection.NEGATIVE.value:
            neg += abs(val)
            neg_n += 1
            if ev.severity == EventSeverity.SEVERE.value:
                severe += abs(_diminish(ev.base_value, 0)) * ev.confidence
                sev_n += 1
        per_dim[ev.target_dimension] = per_dim.get(ev.target_dimension, 0.0) + val

    net = pos - neg
    notes = []
    if sev_n:
        notes.append(f"{sev_n} SEVERE integrity event(s): rating will be capped")
    if dim_events:
        notes.append(f"{dim_events} repeated event(s) hit diminishing returns")
    return LedgerScore(
        component_id=component_id,
        positive_points=round(pos, 4), negative_points=round(neg, 4),
        severe_penalty=round(severe, 4), net_points=round(net, 4),
        per_dimension={k: round(v, 4) for k, v in per_dim.items()},
        event_count=len(events), positive_count=pos_n, negative_count=neg_n,
        severe_count=sev_n, diminished_count=dim_events, notes=notes,
    )


# ---------------------------------------------------------------------------
# Derive events from observable run facts (evidence-linked, never imagined).
# ---------------------------------------------------------------------------
def derive_events_from_run(
    council: dict[str, Any],
    ablation: dict[str, Any] | None = None,
    context_difficulty: float = 0.5,
    created_at: str = "",
) -> list[ContributionEvent]:
    """Emit contribution events grounded in a council result (+ optional ablation).
    Every event points at a concrete field of the run as its evidence."""
    run_id = str(council.get("run_id", ""))
    events: list[ContributionEvent] = []

    def add(component: str, etype: str, *, evidence: str, cf: str = "",
            affected: bool = False, conf: float = 0.8, ordinal: int = 0) -> None:
        events.append(make_event(
            component, run_id, etype, context_difficulty=context_difficulty,
            confidence=conf, counterfactual_impact=cf, evidence=evidence,
            affected_final_result=affected, ordinal=ordinal, created_at=created_at))

    # Council-level evidence.
    if council.get("risk_block_engaged"):
        add("council", "risk_block_overrode_aggregate",
            evidence=f"risk_block_reason={council.get('risk_block_reason','')}",
            cf="without the risk-block precedence the aggregate would not be RISK_BLOCK",
            affected=True)
        add("risk_engine", "tail_risk_detected",
            evidence="risk_block_engaged=true", affected=True)
    for i, w in enumerate(council.get("minority_warnings", []) or []):
        add("council", "minority_warning_preserved", evidence=str(w)[:120], ordinal=i)
    for i, w in enumerate(council.get("tail_warnings", []) or []):
        add("risk_engine", "tail_risk_detected", evidence=str(w)[:120], ordinal=i)
    for i, line in enumerate(council.get("aggregation_explanation", []) or []):
        low = str(line).lower()
        if "dedup" in low and "duplication" in low:
            add("evidence_provenance", "duplicate_evidence_removed", evidence=str(line)[:120])
        if "correlation" in low or "shared evidence" in low:
            add("evidence_provenance", "correlated_agreement_penalised", evidence=str(line)[:120])
        if "concentration" in low:
            add("evidence_provenance", "provenance_completed", evidence=str(line)[:120], ordinal=i)

    # Missing-data prevention (fail-closed).
    if council.get("missing_data_warnings"):
        add("signal_bridge", "missing_data_prevented_false_confidence",
            evidence=f"{len(council['missing_data_warnings'])} missing-data warning(s)",
            cf="lenses labelled INSUFFICIENT_DATA instead of inventing values")
    if (council.get("freshness_status") or "").upper() == "STALE":
        add("signal_reactor", "stale_data_blocked", evidence="freshness_status=STALE")

    # Simulation-only honesty (prevents false certainty).
    if council.get("simulation_only") or council.get("evidence_label") == "SIMULATED_ONLY":
        add("council", "false_certainty_reduced",
            evidence=f"evidence_label={council.get('evidence_label')}, simulation_only={council.get('simulation_only')}")

    # Ablation-grounded quiet contributions (the Kanté work).
    if ablation:
        for c in ablation.get("lens_contributions", []) or []:
            lens_id = f"lens.{str(c.get('lens','')).lower()}"
            if c.get("tail_warning_lost", 0) > 0:
                add(lens_id, "tail_risk_detected",
                    evidence=f"ablation: removing {c['lens']} loses {c['tail_warning_lost']} tail warning(s)",
                    cf="lens uniquely preserves a tail warning", affected=True)
            if c.get("vote_changed"):
                add(lens_id, "counterfactual_changed_conclusion",
                    evidence=f"ablation: removing {c['lens']} flips {c.get('baseline_vote')}→{c.get('ablated_vote')}",
                    cf="lens is decisive for the headline vote", affected=True)
            elif c.get("shapley_value", 0.0) > 0.02:
                add(lens_id, "orthogonal_scenario_surfaced",
                    evidence=f"ablation Shapley={c['shapley_value']} despite no vote change (quiet contributor)",
                    cf=f"coverage_loss={c.get('coverage_loss')} if removed")
    return events


def positive_event_types() -> list[str]:
    return [t for t, m in _EVENT_TYPES.items() if m[0] == EventDirection.POSITIVE.value]


def negative_event_types() -> list[str]:
    return [t for t, m in _EVENT_TYPES.items() if m[0] == EventDirection.NEGATIVE.value]


__all__ = [
    "EventDirection", "EventSeverity", "EventClass", "ContributionEvent",
    "LedgerScore", "make_event", "score_events", "derive_events_from_run",
    "event_meta", "is_known_event", "SEVERE_EVENT_TYPES",
    "positive_event_types", "negative_event_types",
]
