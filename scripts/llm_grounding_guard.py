"""LLM hallucination / source-grounding guard (Pass 4).

Every LLM-derived claim that could touch a score must first pass through
this guard, which classifies it and computes the only weight it is
allowed to carry:

    classifications: sourced | unsourced | inference | speculation | rejected

    weight(claim) = 0                                   if source_count = 0
    weight(claim) = base_weight × source_confidence
                    × freshness_factor × contradiction_penalty   otherwise

    with each factor ∈ [0, 1].

Rules (test-pinned):
  * an UNSOURCED claim contributes exactly zero scoring weight — it can
    be stored as a note, never as a feature;
  * SPECULATION is stored as a note only, weight 0, regardless of source;
  * a ticker that appears in no evidence item is REJECTED outright —
    LLMs invent tickers, evidence does not;
  * contradictory sources reduce confidence multiplicatively;
  * stale sources decay via the freshness factor;
  * every grounded claim records WHICH evidence ids support it, so the
    final recommendation can say what it stands on.

Advisory-only: this guards inputs to a human-facing score. Nothing here
(or anywhere) executes trades.
"""
from __future__ import annotations

import dataclasses
import math

SOURCED = "sourced"
UNSOURCED = "unsourced"
INFERENCE = "inference"
SPECULATION = "speculation"
REJECTED = "rejected"

_FRESHNESS_HALF_LIFE_DAYS = 14.0
_SPECULATION_MARKERS = (
    "might", "could", "rumor", "rumour", "speculat", "unconfirmed",
    "allegedly", "reportedly possible", "if true",
)


@dataclasses.dataclass(frozen=True)
class GroundedClaim:
    claim: str
    symbol: str
    classification: str
    supporting_evidence_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    source_confidence: float
    freshness_factor: float
    contradiction_penalty: float
    weight: float
    note: str
    advisory_only: bool = True

    @property
    def scoring_eligible(self) -> bool:
        return self.weight > 0.0


def freshness_factor(age_days: float | None) -> float:
    """Exponential decay with a 14-day half-life; unknown age = stale-ish 0.5."""
    if age_days is None:
        return 0.5
    if age_days < 0:
        return 0.0  # "published in the future" is not fresh, it is wrong
    return float(0.5 ** (age_days / _FRESHNESS_HALF_LIFE_DAYS))


def contradiction_penalty(n_support: int, n_contradict: int) -> float:
    """1 with no contradictions; melts toward 0 as contradictions pile up."""
    if n_support <= 0:
        return 0.0
    return n_support / (n_support + 2.0 * n_contradict)


def _looks_speculative(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in _SPECULATION_MARKERS)


def ground_claim(
    *,
    claim: str,
    symbol: str,
    base_weight: float,
    evidence_items: list[dict],
    known_symbols: set[str] | None = None,
    is_inference: bool = False,
) -> GroundedClaim:
    """Classify one LLM-derived claim against the evidence ledger.

    ``evidence_items`` are ledger records (scripts/data_quality.py dicts)
    pre-filtered by the caller to the relevant universe; matching here is
    by symbol. ``known_symbols`` is the symbol master — a claim about a
    symbol outside it is REJECTED (hallucinated ticker).
    """
    if not (0.0 <= base_weight <= 1.0):
        raise ValueError(f"base_weight {base_weight} outside [0,1]")
    symbol = str(symbol).strip().upper()
    claim = str(claim).strip()
    if not claim:
        raise ValueError("empty claim")

    if known_symbols is not None and symbol not in {s.upper() for s in known_symbols}:
        return GroundedClaim(
            claim=claim, symbol=symbol, classification=REJECTED,
            supporting_evidence_ids=(), contradicting_evidence_ids=(),
            source_confidence=0.0, freshness_factor=0.0,
            contradiction_penalty=0.0, weight=0.0,
            note=f"symbol {symbol!r} not in the evidence-backed universe — "
                 "rejected as a probable hallucination",
        )

    support = [e for e in evidence_items
               if e.get("symbol", "").upper() == symbol
               and not e.get("contradicts", False)]
    contra = [e for e in evidence_items
              if e.get("symbol", "").upper() == symbol
              and e.get("contradicts", False)]

    if _looks_speculative(claim):
        return GroundedClaim(
            claim=claim, symbol=symbol, classification=SPECULATION,
            supporting_evidence_ids=tuple(e.get("evidence_id", "?") for e in support),
            contradicting_evidence_ids=tuple(e.get("evidence_id", "?") for e in contra),
            source_confidence=0.0, freshness_factor=0.0,
            contradiction_penalty=0.0, weight=0.0,
            note="speculative language — stored as a note only, never a feature",
        )

    if not support:
        return GroundedClaim(
            claim=claim, symbol=symbol,
            classification=INFERENCE if is_inference else UNSOURCED,
            supporting_evidence_ids=(), contradicting_evidence_ids=tuple(
                e.get("evidence_id", "?") for e in contra),
            source_confidence=0.0, freshness_factor=0.0,
            contradiction_penalty=0.0, weight=0.0,
            note="zero supporting evidence — weight is structurally 0",
        )

    source_confidence = max(0.0, min(1.0, min(
        float(e.get("confidence", 0.0)) for e in support
    )))
    ages = [e.get("freshness_days") for e in support]
    known_ages = [a for a in ages if isinstance(a, (int, float))]
    fresh = freshness_factor(min(known_ages) if known_ages else None)
    penalty = contradiction_penalty(len(support), len(contra))
    weight = base_weight * source_confidence * fresh * penalty
    if math.isnan(weight):
        weight = 0.0
    return GroundedClaim(
        claim=claim, symbol=symbol,
        classification=SOURCED,
        supporting_evidence_ids=tuple(e.get("evidence_id", "?") for e in support),
        contradicting_evidence_ids=tuple(e.get("evidence_id", "?") for e in contra),
        source_confidence=source_confidence,
        freshness_factor=fresh,
        contradiction_penalty=penalty,
        weight=weight,
        note=f"grounded by {len(support)} evidence item(s)"
             + (f", contradicted by {len(contra)}" if contra else ""),
    )


def grounded_score_contribution(claims: list[GroundedClaim]) -> dict:
    """Aggregate scoring contribution + the evidence trail behind it."""
    eligible = [c for c in claims if c.scoring_eligible]
    return {
        "total_weight": sum(c.weight for c in eligible),
        "eligible_claims": len(eligible),
        "excluded_claims": len(claims) - len(eligible),
        "evidence_trail": sorted({
            eid for c in eligible for eid in c.supporting_evidence_ids
        }),
        "exclusions": [
            {"claim": c.claim[:120], "classification": c.classification, "note": c.note}
            for c in claims if not c.scoring_eligible
        ],
        "advisory_only": True,
    }
