"""Layer 5 — Binary Truth Ledger.

Before advanced interpretation, force each major claim into a yes/no state.
This is the anti-bullshit audit layer: the model should not say "promising",
it should say which truth bits are active.

    Truth State = Sum(active truth bits) / Total truth bits

The ledger is an *ordered* list of named claims, each evaluated against an
explicit threshold over the dossier evidence.  The output is a compact binary
genome (e.g. ``10110110``) plus a human-readable per-bit explanation, so a
downstream decision can be justified bit by bit.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .util import r3, safe_ratio


@dataclass(frozen=True)
class TruthBit:
    name: str
    bit: int            # 0 or 1
    basis: str          # human-readable why

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BinaryTruthResult:
    bits: list[TruthBit]
    genome: str
    truth_state: float          # active / total
    reason_codes: list[str] = field(default_factory=list)

    def active(self) -> list[str]:
        return [b.name for b in self.bits if b.bit == 1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "bits": [b.to_dict() for b in self.bits],
            "genome": self.genome,
            "truth_state": r3(self.truth_state),
            "active_bits": self.active(),
            "reason_codes": self.reason_codes,
        }


# Each claim: (name, predicate over evidence dict, human basis template).
# Predicates are pure and total — they must tolerate missing keys.
_CLAIMS: list[tuple[str, Callable[[dict[str, Any]], bool], str]] = [
    ("real_human_signal",
     lambda e: e.get("authenticity", 0.0) >= 0.6,
     "authenticity >= 0.60"),
    ("semantic_density_ok",
     lambda e: e.get("semantic_density", 0.0) >= 0.35,
     "semantic_density >= 0.35"),
    ("cross_platform_migration",
     lambda e: e.get("distinct_roles", 0) >= 3,
     "signal present across >= 3 distinct platform ecologies"),
    ("conversion_evidence",
     lambda e: e.get("conversion_strength", 0.0) >= 0.4,
     "conversion_strength >= 0.40"),
    ("retention_evidence",
     lambda e: e.get("retention_strength", 0.0) >= 0.4,
     "retention_strength >= 0.40"),
    ("low_synthetic_contamination",
     lambda e: e.get("contamination", 1.0) <= 0.3,
     "contamination <= 0.30"),
    ("survives_blind",
     lambda e: e.get("reality_purity", 0.0) >= 0.6,
     "reality_purity >= 0.60"),
    ("ownership_improving",
     lambda e: e.get("sovereignty", 0.0) >= 0.5,
     "sovereignty (owned demand) >= 0.50"),
    ("fundamental_confirmation",
     lambda e: e.get("reality_confirmation", 0.0) >= 0.4,
     "reality_confirmation >= 0.40"),
    ("market_recognition_still_early",
     lambda e: e.get("price_recognition", 1.0) <= 0.5,
     "price_recognition <= 0.50 (not yet priced in)"),
    ("interpretation_gap_present",
     lambda e: e.get("interpretation_gap", 0.0) >= 0.3,
     "interpretation_gap >= 0.30"),
    ("within_transfer_window",
     lambda e: bool(e.get("within_transfer_window", False)),
     "signal still inside its alpha transfer window"),
]


def build_truth_ledger(evidence: dict[str, Any]) -> BinaryTruthResult:
    """Evaluate the ordered claim set against a flat evidence dict."""
    bits: list[TruthBit] = []
    for name, pred, basis in _CLAIMS:
        try:
            val = 1 if pred(evidence) else 0
        except Exception:  # pragma: no cover - predicates are total
            val = 0
        bits.append(TruthBit(name=name, bit=val, basis=basis))

    genome = "".join(str(b.bit) for b in bits)
    active = sum(b.bit for b in bits)
    truth_state = safe_ratio(active, len(bits))

    reasons = [f"GENOME:{genome}", f"ACTIVE:{active}/{len(bits)}"]
    # A few load-bearing combinations worth surfacing explicitly.
    by = {b.name: b.bit for b in bits}
    if by["interpretation_gap_present"] and not by["fundamental_confirmation"]:
        reasons.append("GAP_WITHOUT_CONFIRMATION_TRAP_RISK")
    if by["real_human_signal"] and by["low_synthetic_contamination"] and by["survives_blind"]:
        reasons.append("SUBSTANCE_CONFIRMED")
    if not by["market_recognition_still_early"]:
        reasons.append("LIKELY_PRICED_IN")

    return BinaryTruthResult(
        bits=bits, genome=genome, truth_state=truth_state, reason_codes=reasons
    )


__all__ = ["TruthBit", "BinaryTruthResult", "build_truth_ledger"]
