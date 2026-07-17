"""Process quality vs outcome quality — separate discipline from luck.

A strong process can produce a bad outcome; a weak process can get lucky. Scoring
either alone teaches the wrong lesson. This produces two independent scores and a
four-quadrant classification that feeds the RACR contribution ledger (rewarding
good process even on a bad probabilistic outcome, never rewarding recklessness for
a lucky result).

Process quality is knowable at prediction time (no outcome needed); outcome
quality is only knowable after leakage-safe resolution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.simulation_intelligence.contracts import MarketObservation
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from simulation_intelligence.contracts import MarketObservation  # type: ignore[no-redef]


def _clip(v: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, f)) if f == f else lo


@dataclass(slots=True)
class ProcessQuality:
    score: float                 # 0..10, knowable WITHOUT the outcome
    components: dict[str, float]
    band: str                    # WEAK / ADEQUATE / STRONG
    no_execution_compliant: bool

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def score_process(obs: MarketObservation, council: dict[str, Any],
                  twin: dict[str, Any] | None = None) -> ProcessQuality:
    """Score decision-process quality from evidence completeness, freshness,
    provenance, uncertainty honesty, scenario coverage, tail preservation,
    consistency, and no-execution compliance. Outcome-independent."""
    c: dict[str, float] = {}
    c["evidence_completeness"] = _clip(1.0 - len(obs.missing_fields or []) / 6.0)
    fresh = (obs.freshness_status or "UNKNOWN").upper()
    c["evidence_freshness"] = {"FRESH": 1.0, "AGING": 0.6, "STALE": 0.2}.get(fresh, 0.3)
    c["provenance_quality"] = _clip(min(int(obs.source_count or 0), 4) / 4.0)
    # Uncertainty honesty: did it decline to over-claim? simulation_only + honest label.
    label = council.get("evidence_label", "SIMULATED_ONLY")
    c["uncertainty_honesty"] = 1.0 if label in ("MODEL_INFERRED", "PROXY_DERIVED",
                                                "SIMULATED_ONLY", "INSUFFICIENT_DATA") else 0.4
    c["scenario_coverage"] = _clip(len(council.get("stress_results", []) or []) / 8.0)
    # Tail preservation: were tail warnings surfaced when fragility was high?
    frag = _clip(council.get("fragility", 0.0))
    tail_present = bool(council.get("tail_warnings"))
    c["tail_preservation"] = 1.0 if (frag < 0.6 or tail_present) else 0.3
    c["decision_consistency"] = _clip(council.get("robustness", 0.5))
    # No-execution compliance — a hard gate.
    no_exec = (council.get("execution_gate") == "LOCKED"
               and council.get("broker_api_called") in (False, 0)
               and council.get("ai_execution_count", 0) == 0)
    c["no_execution_compliance"] = 1.0 if no_exec else 0.0

    weights = {"evidence_completeness": 1.2, "evidence_freshness": 1.2,
               "provenance_quality": 1.0, "uncertainty_honesty": 1.4,
               "scenario_coverage": 0.8, "tail_preservation": 1.3,
               "decision_consistency": 1.0, "no_execution_compliance": 2.0}
    tw = sum(weights.values())
    raw = sum(c[k] * weights[k] for k in c) / tw
    # A no-execution violation caps process quality hard.
    if not no_exec:
        raw = min(raw, 0.3)
    score = round(10.0 * raw, 2)
    band = "STRONG" if score >= 7.0 else ("ADEQUATE" if score >= 4.5 else "WEAK")
    return ProcessQuality(score=score, components={k: round(v, 3) for k, v in c.items()},
                          band=band, no_execution_compliant=no_exec)


@dataclass(slots=True)
class ProcessOutcomeVerdict:
    quadrant: str                # GOOD/BAD process x GOOD/BAD outcome
    process_score: float
    outcome_score: float
    lesson: str
    ledger_signal: str           # what the RACR ledger should record

    def to_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__slots__}
        d.update(advisory_safety_stamps())
        return d


def classify(process_score: float, outcome_score: float,
             *, process_min: float = 6.0, outcome_min: float = 5.0) -> ProcessOutcomeVerdict:
    """Four-quadrant process×outcome classification. Rewards good process even on a
    bad outcome; never rewards a reckless process for a lucky one."""
    good_p = process_score >= process_min
    good_o = outcome_score >= outcome_min
    if good_p and good_o:
        q, lesson, sig = ("GOOD_PROCESS_GOOD_OUTCOME",
                          "disciplined process, favourable outcome — reinforce",
                          "credit_process_and_outcome")
    elif good_p and not good_o:
        q, lesson, sig = ("GOOD_PROCESS_BAD_OUTCOME",
                          "disciplined, well-calibrated process; the probabilistic outcome was unfavourable — do NOT punish",
                          "protect_process_credit")
    elif not good_p and good_o:
        q, lesson, sig = ("BAD_PROCESS_GOOD_OUTCOME",
                          "weak process, lucky outcome — do NOT reward; flag the process",
                          "flag_lucky_process")
    else:
        q, lesson, sig = ("BAD_PROCESS_BAD_OUTCOME",
                          "weak process and bad outcome — correct the process",
                          "penalise_process")
    return ProcessOutcomeVerdict(
        quadrant=q, process_score=round(process_score, 2),
        outcome_score=round(outcome_score, 2), lesson=lesson, ledger_signal=sig)


__all__ = ["ProcessQuality", "score_process", "ProcessOutcomeVerdict", "classify"]
