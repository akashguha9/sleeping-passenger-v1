"""Duplicate-source syndication detector (Pass 5 surprise upgrade).

The failure this kills: one wire story gets republished by twenty
outlets, and naive evidence counting sees twenty independent
confirmations. Confirmation count is one of the strongest inputs to the
evidence-quality and grounding layers — syndication silently turns one
data point into twenty, which is exactly how crowded narratives look
like well-confirmed theses.

Method (stdlib only, deterministic):

  * normalize claim text (casefold, strip punctuation/digits-noise,
    collapse whitespace);
  * k-shingle word sets (k=3, falling back to the full token set for
    short claims);
  * Jaccard similarity J(A,B) = |A∩B| / |A∪B|;
  * greedy single-link clustering at threshold τ (default 0.55;
    light editorial rewrites of one wire story measure ≈0.58, genuinely
    distinct stories ≈0.0–0.1) —
    near-duplicates land in one cluster;
  * **effective sources = number of clusters**, not number of items;
    within a cluster, distinct outlet names are reported but contribute
    ZERO extra confirmations (same underlying story).

Integration: ``llm_grounding_guard.ground_claim`` counts support and
contradiction by EFFECTIVE clusters, so a syndicated story can never
outvote a genuinely independent one.

Acceptance (test-pinned): 20 near-identical wire copies collapse to an
effective source count of 1, and the grounding weight with 20 syndicated
copies equals the weight with a single source.

Advisory-only: pure text analysis; executes nothing.
"""
from __future__ import annotations

import re

DEFAULT_SIMILARITY_THRESHOLD = 0.55
_SHINGLE_K = 3
_WORD_RE = re.compile(r"[a-z0-9']+")


def normalize_text(text: str) -> list[str]:
    """Lowercased word tokens with punctuation noise stripped."""
    return _WORD_RE.findall(str(text or "").casefold())


def shingles(text: str, k: int = _SHINGLE_K) -> frozenset[str]:
    """Word k-shingles; short texts fall back to their token set."""
    tokens = normalize_text(text)
    if len(tokens) < k:
        return frozenset(tokens)
    return frozenset(" ".join(tokens[i:i + k]) for i in range(len(tokens) - k + 1))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0  # two empty claims are the same nothing
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity(text_a: str, text_b: str) -> float:
    return jaccard(shingles(text_a), shingles(text_b))


def cluster_claims(
    items: list[dict],
    *,
    text_key: str = "claim",
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[list[int]]:
    """Greedy single-link clustering of items by claim-text similarity.

    Returns clusters as lists of indices into ``items``. Deterministic:
    items are processed in order; an item joins the first cluster whose
    ANY member is ≥ threshold similar, else founds a new cluster.
    """
    if not (0.0 < threshold <= 1.0):
        raise ValueError(f"threshold {threshold} outside (0, 1]")
    sigs = [shingles(str(item.get(text_key, ""))) for item in items]
    clusters: list[list[int]] = []
    for idx, sig in enumerate(sigs):
        placed = False
        # Empty-text items (structured/non-text evidence) carry no
        # similarity signal: they can neither prove duplication nor be
        # syndicated wire copy, so each stays its own independent cluster.
        if sig:
            for cluster in clusters:
                if any(
                    sigs[member] and jaccard(sig, sigs[member]) >= threshold
                    for member in cluster
                ):
                    cluster.append(idx)
                    placed = True
                    break
        if not placed:
            clusters.append([idx])
    return clusters


def effective_sources(
    items: list[dict],
    *,
    text_key: str = "claim",
    source_key: str = "source_name",
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> dict:
    """Collapse syndicated copies into effective independent confirmations.

    Returns::

        {"raw_count": N, "effective_count": K, "syndication_collapsed": N-K,
         "clusters": [{"indices": [...], "outlets": [...],
                       "representative": "<claim>"}, ...]}
    """
    clusters = cluster_claims(items, text_key=text_key, threshold=threshold)
    detail = []
    for cluster in clusters:
        outlets = sorted({
            str(items[i].get(source_key, "?")) for i in cluster
        })
        detail.append({
            "indices": cluster,
            "outlets": outlets,
            "copies": len(cluster),
            "representative": str(items[cluster[0]].get(text_key, ""))[:120],
        })
    return {
        "raw_count": len(items),
        "effective_count": len(clusters),
        "syndication_collapsed": len(items) - len(clusters),
        "clusters": detail,
        "advisory_only": True,
    }


def representatives(
    items: list[dict],
    *,
    text_key: str = "claim",
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[dict]:
    """One representative item per cluster (the first seen — earliest in
    caller order, which callers should keep chronological)."""
    clusters = cluster_claims(items, text_key=text_key, threshold=threshold)
    return [items[cluster[0]] for cluster in clusters]
