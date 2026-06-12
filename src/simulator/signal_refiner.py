"""Signal Refiner: count origins, not echoes — for the signals list.

The narrative tracker already counts origins for MENTIONS (dirty air),
and the aero engine penalizes caller-judged duplication LEVELS. But the
``signals`` list itself was scored tyre by tyre as if every signal were
independent evidence: three social spikes echoing one viral post added
three tyres of effective strength. This module clusters the signals
into evidence clusters and prices the redundancy:

    Independence       = unique clusters / raw signal count
    Redundancy penalty = 1 − Independence
    Adjusted strength  = strongest effective × (1 − 0.4 · redundancy)

Clustering is conservative by doctrine: signals of the same type
WITHOUT declared distinct origins are assumed correlated (one cluster)
— independence must be evidenced via an ``origin`` or
``evidence_basis`` field, never assumed. The adjustment only ever
LOWERS derived optimism (it feeds the self-feed signal_strength via
conservative merge), and the raw tyres remain untouched everywhere
else. ADVISORY_ONLY.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.simulator.signal_tyres import TyreState
from src.utils.math_utils import clamp01

REDUNDANCY_WARN = 0.5  # more than half the signals are echoes
MAX_REDUNDANCY_HAIRCUT = 0.4


@dataclass(slots=True)
class SignalCluster:
    """One independent evidence cluster and the signals inside it."""

    cluster_key: str
    signal_types: list[str]
    member_count: int
    strongest_effective: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class SignalRefinement:
    """Independence accounting for one payload's signals list."""

    raw_signal_count: int
    effective_signal_count: int  # unique evidence clusters
    independence: float
    redundancy_penalty: float
    strongest_effective_strength: float
    adjusted_strength: float  # independence-haircut strength (0..150)
    clusters: list[SignalCluster] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["clusters"] = [c.to_dict() for c in self.clusters]
        return payload


def _cluster_key(spec: dict[str, Any]) -> str:
    """Independence must be declared, never assumed: a distinct
    ``origin`` (or ``evidence_basis``) separates clusters; the same
    signal type with no declared origin collapses into one cluster."""
    origin = str(spec.get("origin", "") or "").strip().lower()
    if origin:
        return f"origin:{origin}"
    basis = str(spec.get("evidence_basis", "") or "").strip().lower()
    signal_type = str(spec.get("signal_type", "unknown")).strip().lower()
    if basis:
        return f"{signal_type}|basis:{basis}"
    return f"type:{signal_type}"


def refine_signals(
    signal_specs: list[dict[str, Any]],
    tyres: list[TyreState],
) -> SignalRefinement:
    """Cluster the signals list and price the echo discount.

    ``signal_specs`` are the raw payload dicts (carrying the optional
    ``origin`` / ``evidence_basis`` declarations); ``tyres`` are the
    already-scored states in the same order. Extra or missing tyres
    degrade gracefully — pairs are zipped, never guessed.
    """
    specs = [s for s in (signal_specs or []) if isinstance(s, dict)]
    paired = list(zip(specs, tyres))
    raw_count = len(paired)
    if raw_count == 0:
        return SignalRefinement(
            raw_signal_count=0,
            effective_signal_count=0,
            independence=1.0,
            redundancy_penalty=0.0,
            strongest_effective_strength=0.0,
            adjusted_strength=0.0,
            rationale=["no signals supplied — nothing to refine"],
        )

    clusters: dict[str, SignalCluster] = {}
    for spec, tyre in paired:
        key = _cluster_key(spec)
        cluster = clusters.get(key)
        if cluster is None:
            clusters[key] = SignalCluster(
                cluster_key=key,
                signal_types=[str(spec.get("signal_type", "unknown"))],
                member_count=1,
                strongest_effective=tyre.effective_signal_strength,
            )
        else:
            cluster.member_count += 1
            signal_type = str(spec.get("signal_type", "unknown"))
            if signal_type not in cluster.signal_types:
                cluster.signal_types.append(signal_type)
            cluster.strongest_effective = max(
                cluster.strongest_effective,
                tyre.effective_signal_strength,
            )

    effective_count = len(clusters)
    independence = effective_count / raw_count
    redundancy = round(1.0 - independence, 4)
    strongest = max(t.effective_signal_strength for _, t in paired)
    adjusted = round(
        strongest * (1.0 - MAX_REDUNDANCY_HAIRCUT * redundancy), 4
    )

    reason_codes: list[str] = []
    if redundancy >= REDUNDANCY_WARN:
        reason_codes.append("SIGNAL_REDUNDANCY_HIGH")
    duplicated = [c for c in clusters.values() if c.member_count > 1]
    rationale = [
        f"{raw_count} raw signal(s) -> {effective_count} independent "
        f"evidence cluster(s); independence {independence:.2f}, "
        f"redundancy penalty {redundancy:.2f}",
        f"adjusted strength {adjusted:.1f} = strongest {strongest:.1f} × "
        f"(1 − {MAX_REDUNDANCY_HAIRCUT} × redundancy)",
    ]
    if duplicated:
        rationale.append(
            "correlated clusters (echoes, not evidence): "
            + "; ".join(
                f"{c.cluster_key} ×{c.member_count}" for c in duplicated
            )
        )
        rationale.append(
            "independence must be declared via origin/evidence_basis — "
            "same-type signals without distinct origins are assumed "
            "correlated"
        )
    return SignalRefinement(
        raw_signal_count=raw_count,
        effective_signal_count=effective_count,
        independence=round(independence, 4),
        redundancy_penalty=redundancy,
        strongest_effective_strength=round(strongest, 4),
        adjusted_strength=adjusted,
        clusters=sorted(clusters.values(),
                        key=lambda c: -c.strongest_effective),
        reason_codes=reason_codes,
        rationale=rationale,
    )
