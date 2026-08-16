"""Regime-transition sprint — inertia stack (PIS / CIS / SIS / IIR).

Answers ONE question (reflection §31–41):

    How much historical resistance does the system already carry, and is
    today's shock big enough relative to that inertia to matter?

Distinct from ``narrative_inertia_score.py`` (which measures narrative
momentum vs fresh signal) — this module measures PHYSICAL/INSTITUTIONAL
resistance: enacted policy, committed capital, supply-chain response time.

Evidence discipline (cite-or-drop, same contract as nbi_value_chain_mapper):
an inertia evidence item without an ``evidence_ref`` contributes nothing
and is counted in ``dropped_uncited``.  A lane with no admissible items is
UNKNOWN (score None) — never a silent zero.

All band thresholds are documented UNCALIBRATED defaults.  Advisory-only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"
CALIBRATION_STATUS = "UNCALIBRATED_DEFAULTS"
UNKNOWN = "UNKNOWN"
OK = "OK"

# Lanes and their admissible evidence kinds.
POLICY = "POLICY"
CAPITAL = "CAPITAL"
SUPPLY_CHAIN = "SUPPLY_CHAIN"

LANE_KINDS: dict[str, tuple[str, ...]] = {
    POLICY: ("LEGISLATION", "BUDGET", "REGULATION", "CONTRACT",
             "INSTITUTION", "VESTED_INTEREST", "COURT_DECISION",
             "EXECUTIVE_ACTION", "PROCUREMENT"),
    CAPITAL: ("CAPEX_COMMITTED", "FACTORY_CONSTRUCTION", "ORDER_BACKLOG",
              "LONG_TERM_CONTRACT", "PPA", "FINANCING_ARRANGED",
              "INSTALLED_INFRASTRUCTURE"),
    SUPPLY_CHAIN: ("CAPACITY_LEAD_TIME", "PERMITTING_TIME",
                   "QUALIFICATION_CYCLE", "SUPPLIER_CONCENTRATION",
                   "RAMP_TIME", "CERTIFICATION", "SUBSTITUTE_SCARCITY"),
}

# IIR bands (reflection §40; uncalibrated defaults).
IIR_NOISE = "NOISE"
IIR_WOBBLE = "WOBBLE"
IIR_DESTABILIZING = "DESTABILIZING"
IIR_REGIME_THREAT = "REGIME_THREAT"
_IIR_BANDS = ((0.5, IIR_NOISE), (1.5, IIR_WOBBLE), (3.0, IIR_DESTABILIZING))

_SATURATION_K = 1.2  # score = 100 * (1 - exp(-k * Σ contribution))


@dataclass
class InertiaEvidence:
    """One cited piece of inertia evidence.

    ``magnitude`` in [0, 1] is the analyst/extractor estimate of how much
    resistance this item contributes; ``confidence`` in [0, 1] scales it.
    ``direction`` is +1 when the item reinforces the established
    trajectory, -1 when it actively erodes it (e.g. sunset clause).
    """

    kind: str
    magnitude: float
    confidence: float
    evidence_ref: str | None
    direction: int = 1
    note: str = ""


@dataclass
class PolicyGenealogyStep:
    """One node in the historical policy chain (reflection §32)."""

    year: int
    label: str
    evidence_ref: str | None
    reinforcing: bool = True


def _lane_score(items: list[InertiaEvidence], lane: str) -> dict[str, Any]:
    admissible: list[InertiaEvidence] = []
    dropped_uncited = 0
    dropped_wrong_kind = 0
    for it in items:
        if it.kind not in LANE_KINDS[lane]:
            dropped_wrong_kind += 1
            continue
        if not it.evidence_ref:
            dropped_uncited += 1
            continue
        admissible.append(it)
    if not admissible:
        return {"status": UNKNOWN, "score": None, "items_used": 0,
                "dropped_uncited": dropped_uncited,
                "dropped_wrong_kind": dropped_wrong_kind}
    total = sum(
        max(-1.0, min(1.0, it.magnitude)) * max(0.0, min(1.0, it.confidence))
        * (1 if it.direction >= 0 else -1)
        for it in admissible)
    score = 100.0 * (1.0 - math.exp(-_SATURATION_K * max(0.0, total)))
    return {"status": OK, "score": round(score, 2),
            "items_used": len(admissible),
            "net_contribution": round(total, 4),
            "dropped_uncited": dropped_uncited,
            "dropped_wrong_kind": dropped_wrong_kind}


def policy_genealogy(steps: list[PolicyGenealogyStep]) -> dict[str, Any]:
    """Summarize the historical chain feeding today's trajectory."""
    cited = [s for s in steps if s.evidence_ref]
    if not cited:
        return {"status": UNKNOWN, "chain_length": 0,
                "dropped_uncited": len(steps)}
    years = sorted(s.year for s in cited)
    reinforcing = sum(1 for s in cited if s.reinforcing)
    return {
        "status": OK,
        "chain_length": len(cited),
        "span_years": years[-1] - years[0],
        "directional_consistency": round(reinforcing / len(cited), 4),
        "dropped_uncited": len(steps) - len(cited),
        "chain": [{"year": s.year, "label": s.label,
                   "evidence_ref": s.evidence_ref,
                   "reinforcing": s.reinforcing}
                  for s in sorted(cited, key=lambda s: s.year)],
    }


def inertia_stack(
    *,
    policy_items: list[InertiaEvidence] = (),
    capital_items: list[InertiaEvidence] = (),
    supply_chain_items: list[InertiaEvidence] = (),
    genealogy: list[PolicyGenealogyStep] = (),
) -> dict[str, Any]:
    """Compute PIS / CIS / SIS plus a coverage-aware composite."""
    pis = _lane_score(list(policy_items), POLICY)
    cis = _lane_score(list(capital_items), CAPITAL)
    sis = _lane_score(list(supply_chain_items), SUPPLY_CHAIN)
    gen = policy_genealogy(list(genealogy))
    # A long, consistent genealogy modestly lifts PIS (documented: max +10).
    if pis["status"] == OK and gen["status"] == OK:
        bump = min(10.0, 2.0 * gen["chain_length"]) * gen["directional_consistency"]
        pis = {**pis, "score": round(min(100.0, pis["score"] + bump), 2),
               "genealogy_bump": round(bump, 2)}
    known = [x["score"] for x in (pis, cis, sis) if x["status"] == OK]
    composite = round(sum(known) / len(known), 2) if known else None
    return {
        "policy_inertia": pis, "capital_inertia": cis,
        "supply_chain_inertia": sis, "policy_genealogy": gen,
        "composite_inertia": composite,
        "lane_coverage": round(len(known) / 3.0, 4),
        "calibration_status": CALIBRATION_STATUS,
        "safety": {"advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY},
    }


def impulse_to_inertia_ratio(shock_magnitude_0_100: float | None,
                             composite_inertia_0_100: float | None,
                             ) -> dict[str, Any]:
    """IIR = shock / inertia with documented interpretation bands."""
    if shock_magnitude_0_100 is None or composite_inertia_0_100 is None:
        return {"status": UNKNOWN, "iir": None, "band": None,
                "reason": "shock or inertia unavailable"}
    denom = max(1.0, composite_inertia_0_100)
    iir = max(0.0, shock_magnitude_0_100) / denom
    band = IIR_REGIME_THREAT
    for ceiling, label in _IIR_BANDS:
        if iir < ceiling:
            band = label
            break
    return {"status": OK, "iir": round(iir, 4), "band": band,
            "calibration_status": CALIBRATION_STATUS}
