"""Actionable uncertainty — WHY confidence is low and whether it is reducible.

The council can say "confidence is low"; this decomposes that into typed
uncertainty and, crucially, marks each type **reducible or not** and names the
best reduction action. Epistemic/data-quality uncertainty is reducible (acquire
evidence); aleatoric/regime uncertainty largely is not. This is what the Value-of-
Information engine consumes to decide whether research is worth the cost.

Pure/deterministic: derived from the observation + council result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.simulation_intelligence.contracts import MarketObservation
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.contracts import MarketObservation  # type: ignore[no-redef]


def _clip(v: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, f)) if f == f else lo


@dataclass(slots=True)
class UncertaintyComponent:
    kind: str
    magnitude: float          # 0..1
    reducible: bool
    reduction_action: str     # "" when not reducible
    reduction_cost: str       # LOW / MEDIUM / HIGH / NA
    decision_relevance: float # 0..1 — does it affect the headline advisory state?
    decay: str                # how quickly it expires: SLOW / MEDIUM / FAST / NONE
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


@dataclass(slots=True)
class UncertaintyProfile:
    components: list[UncertaintyComponent]
    dominant_kind: str
    reducible_fraction: float   # share of total uncertainty that is reducible
    total_magnitude: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "components": [c.to_dict() for c in self.components],
            "dominant_kind": self.dominant_kind,
            "reducible_fraction": self.reducible_fraction,
            "total_magnitude": self.total_magnitude,
        }


def decompose(obs: MarketObservation, council: dict[str, Any]) -> UncertaintyProfile:
    comps: list[UncertaintyComponent] = []
    missing = list(obs.missing_fields or [])
    n_ret = len(obs.returns or [])
    fresh = (obs.freshness_status or "UNKNOWN").upper()
    frag = _clip(council.get("fragility", 0.5))
    dis = council.get("disagreement_class", "")

    # Aleatoric — irreducible market noise (proxied by realized volatility).
    vol = _clip((obs.volatility or 0.02) / 0.05)
    comps.append(UncertaintyComponent(
        "aleatoric", round(vol, 3), False, "", "NA",
        decision_relevance=0.4, decay="NONE", source="realized volatility"))

    # Epistemic — reducible model uncertainty (proxied by fragility).
    comps.append(UncertaintyComponent(
        "epistemic", round(frag, 3), True, "acquire disambiguating evidence",
        "MEDIUM", decision_relevance=0.8, decay="SLOW", source="council fragility"))

    # Data-quality — reducible via better/fresher data.
    dq = _clip(len(missing) / 6.0 + (0.3 if n_ret < 5 else 0.0))
    comps.append(UncertaintyComponent(
        "data_quality", round(dq, 3), True, "backfill missing fields / OHLCV",
        "LOW", decision_relevance=0.7 if missing else 0.3, decay="MEDIUM",
        source=f"{len(missing)} missing field(s)"))

    # Model-disagreement — partially reducible.
    dis_mag = {"SPLIT_DECISION": 0.8, "MINORITY_TAIL_WARNING": 0.7,
               "CONSENSUS_FRAGILE": 0.5, "SHARED_EVIDENCE_ILLUSION": 0.6,
               "INSUFFICIENT_INDEPENDENCE": 0.7}.get(dis, 0.3)
    comps.append(UncertaintyComponent(
        "model_disagreement", round(dis_mag, 3), True, "seek an independent source",
        "MEDIUM", decision_relevance=0.6, decay="SLOW", source=f"disagreement={dis}"))

    # Regime — largely irreducible (you can't research your way out of a regime).
    comps.append(UncertaintyComponent(
        "regime", 0.5, False, "", "NA", decision_relevance=0.5, decay="SLOW",
        source="regime instability"))

    # Timing — reducible by waiting for a catalyst / fresher data.
    timing = 0.7 if fresh in ("AGING", "STALE", "UNKNOWN") else 0.3
    comps.append(UncertaintyComponent(
        "timing", round(timing, 3), True, "wait for the next catalyst/fresh data",
        "LOW", decision_relevance=0.6, decay="FAST", source=f"freshness={fresh}"))

    # Outcome-definition — reducible by tightening the prediction target.
    comps.append(UncertaintyComponent(
        "outcome_definition", 0.3, True, "tighten target variable / window",
        "LOW", decision_relevance=0.4, decay="NONE", source="target ambiguity"))

    # Operator-response — irreducible from the system's side.
    comps.append(UncertaintyComponent(
        "operator_response", 0.4, False, "", "NA", decision_relevance=0.3,
        decay="MEDIUM", source="human interpretation variance"))

    total = sum(c.magnitude for c in comps)
    reducible = sum(c.magnitude for c in comps if c.reducible)
    dominant = max(comps, key=lambda c: c.magnitude * (1 + c.decision_relevance)).kind
    return UncertaintyProfile(
        components=comps, dominant_kind=dominant,
        reducible_fraction=round(reducible / total, 4) if total else 0.0,
        total_magnitude=round(total, 4))


__all__ = ["UncertaintyComponent", "UncertaintyProfile", "decompose"]
