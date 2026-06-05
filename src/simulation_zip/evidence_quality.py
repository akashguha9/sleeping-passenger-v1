"""Evidence quality scoring (Sprint 2, Phase 8).

Per-record quality Q_i in [0,100], family quality Q_f, corpus quality
Q_corpus = Σ_f w_f Q_f with w_f = n_f / N_total.  All inputs are explicit,
bounded [0,1] components — fully transparent, no hidden weighting.
"""
from __future__ import annotations

from src.simulation_zip.metrics import duplicate_ratio  # noqa: F401 (doc ref)

Q_WEIGHTS: dict[str, float] = {
    "provenance_complete": 0.20,
    "parser_confidence": 0.15,
    "schema_completeness": 0.15,
    "source_identifiability": 0.15,
    "recency_parseability": 0.10,
    "dedup_uniqueness": 0.10,
    "safety_clean": 0.10,
    "limitation_documented": 0.05,
}


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def record_quality(components: dict[str, float]) -> float:
    """Q_i = 100 * Σ_k w_k * component_k, each component clipped to [0,1]."""
    return round(
        100.0 * sum(w * _clip01(components.get(k, 0.0)) for k, w in Q_WEIGHTS.items()),
        4,
    )


def quality_band(q: float) -> str:
    if q >= 85:
        return "STRONG_SIMULATION_EVIDENCE"
    if q >= 70:
        return "USEFUL_SIMULATION_EVIDENCE"
    if q >= 50:
        return "LIMITED_SIMULATION_EVIDENCE"
    if q >= 30:
        return "WEAK_SIMULATION_EVIDENCE"
    return "POOR_OR_UNUSABLE"


def family_quality(component_rows: list[dict[str, float]]) -> dict[str, object]:
    """Mean Q over a family's records."""
    if not component_rows:
        return {"n": 0, "Q_f": 0.0, "band": quality_band(0.0)}
    qs = [record_quality(c) for c in component_rows]
    q_f = round(sum(qs) / len(qs), 4)
    return {"n": len(qs), "Q_f": q_f, "band": quality_band(q_f)}


def corpus_quality(per_family: dict[str, list[dict[str, float]]]) -> dict[str, object]:
    """Q_corpus = Σ_f w_f Q_f, w_f = n_f / N_total_parsed."""
    fam_results: dict[str, dict] = {}
    total = 0
    for fam, rows in per_family.items():
        fr = family_quality(rows)
        fam_results[fam] = fr
        total += fr["n"]
    if total == 0:
        return {"Q_corpus": 0.0, "band": quality_band(0.0), "families": fam_results,
                "total_parsed": 0}
    q_corpus = round(
        sum((fr["n"] / total) * fr["Q_f"] for fr in fam_results.values()), 4
    )
    return {
        "Q_corpus": q_corpus,
        "band": quality_band(q_corpus),
        "total_parsed": total,
        "families": fam_results,
    }


__all__ = [
    "Q_WEIGHTS",
    "record_quality",
    "quality_band",
    "family_quality",
    "corpus_quality",
]
