"""Evidence provenance + de-duplication.

Central to the aggregator's honesty: two lenses that both lean on the *same*
underlying observation must not have that observation counted twice.  This
module builds stable fingerprints for evidence and detects shared sources.
"""
from __future__ import annotations

import hashlib
from typing import Iterable

try:
    from scripts.simulation_intelligence.contracts import (
        EvidencePacket,
        EVIDENCE_STRENGTH,
        EvidenceLabel,
        FreshnessStatus,
    )
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        EvidencePacket,
        EVIDENCE_STRENGTH,
        EvidenceLabel,
        FreshnessStatus,
    )


def fingerprint(source_keys: Iterable[str]) -> str:
    """Stable 16-hex fingerprint of a set of source keys (order-independent)."""
    keys = sorted({str(k).strip().lower() for k in source_keys if str(k).strip()})
    if not keys:
        return "nosource"
    canonical = "|".join(keys)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def make_evidence(
    lens: str,
    claim: str,
    evidence_label: str,
    source_keys: Iterable[str],
    weight: float = 1.0,
    freshness_status: str = FreshnessStatus.UNKNOWN.value,
) -> EvidencePacket:
    keys = [str(k) for k in source_keys]
    return EvidencePacket(
        lens=lens,
        claim=claim,
        evidence_label=evidence_label,
        fingerprint=fingerprint(keys),
        source_keys=keys,
        weight=float(weight),
        freshness_status=freshness_status,
    )


def evidence_strength(label: str) -> float:
    return EVIDENCE_STRENGTH.get(label, EVIDENCE_STRENGTH[EvidenceLabel.SIMULATED_ONLY.value])


def deduplicate(packets: list[EvidencePacket]) -> tuple[list[EvidencePacket], dict]:
    """Collapse packets sharing a fingerprint into a single strongest packet.

    Returns ``(unique_packets, report)`` where ``report`` explains how much
    evidence was shared (used to detect the SHARED_EVIDENCE_ILLUSION).
    """
    by_fp: dict[str, list[EvidencePacket]] = {}
    for p in packets:
        by_fp.setdefault(p.fingerprint, []).append(p)

    unique: list[EvidencePacket] = []
    shared_fingerprints: list[dict] = []
    for fp, group in by_fp.items():
        # Keep the strongest-labelled packet as the representative.
        rep = max(group, key=lambda x: evidence_strength(x.evidence_label))
        unique.append(rep)
        if len(group) > 1:
            shared_fingerprints.append({
                "fingerprint": fp,
                "lenses": sorted({p.lens for p in group}),
                "count": len(group),
            })

    total = len(packets)
    unique_n = len(unique)
    duplication_ratio = 0.0 if total == 0 else round(1.0 - unique_n / total, 4)
    # How many *distinct lenses* are entangled via a shared source.
    entangled_lenses = sorted({
        lens for s in shared_fingerprints for lens in s["lenses"]
    })
    report = {
        "total_evidence": total,
        "unique_evidence": unique_n,
        "duplication_ratio": duplication_ratio,
        "shared_fingerprints": shared_fingerprints,
        "entangled_lenses": entangled_lenses,
        "shared_evidence_detected": bool(shared_fingerprints),
    }
    return unique, report


def source_concentration(packets: list[EvidencePacket]) -> float:
    """Herfindahl-style concentration of evidence across distinct sources.

    1.0 = every packet from one source (maximally concentrated / fragile);
    ~0 = evidence spread across many independent sources.
    """
    counts: dict[str, int] = {}
    total = 0
    for p in packets:
        for k in (p.source_keys or [p.fingerprint]):
            counts[k] = counts.get(k, 0) + 1
            total += 1
    if total == 0:
        return 1.0
    return round(sum((c / total) ** 2 for c in counts.values()), 4)


__all__ = [
    "fingerprint",
    "make_evidence",
    "evidence_strength",
    "deduplicate",
    "source_concentration",
]
