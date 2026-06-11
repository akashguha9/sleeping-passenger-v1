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


# ---------------------------------------------------------------------------
# Pass-6 v2: beyond-lexical syndication signals
# ---------------------------------------------------------------------------

_TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "ref", "cmpid", "ito", "ncid")
_WIRE_LINEAGE_MARKERS = {
    "reuters": "reuters", "associated press": "ap", "(ap)": "ap",
    "ap news": "ap", "bloomberg": "bloomberg", "press trust of india": "pti",
    "(pti)": "pti", "afp": "afp", "(ani)": "ani", "ians": "ians",
    "dow jones newswires": "dowjones", "business wire": "businesswire",
    "pr newswire": "prnewswire", "globenewswire": "globenewswire",
}
_CATALYST_CLASSES = {
    "earnings": ("earnings", "revenue", "profit", "quarterly", "q1", "q2",
                 "q3", "q4", "results", "guidance", "eps"),
    "contract": ("contract", "deal", "order win", "tender", "awarded"),
    "merger": ("merger", "acquisition", "acquire", "buyout", "takeover", "stake"),
    "regulatory": ("fda", "sebi", "sec", "approval", "regulator", "license",
                   "antitrust", "probe"),
    "litigation": ("lawsuit", "litigation", "court", "settlement", "verdict"),
    "product": ("launch", "product", "unveil", "release"),
    "capital": ("buyback", "dividend", "split", "rights issue", "ipo",
                "fundraise", "placement"),
    "management": ("ceo", "cfo", "resign", "appoint", "board"),
}
_NUMBER_RE = re.compile(r"\d[\d,.]*")
STALE_REPOST_DAYS = 7.0


def canonical_url(url: str | None) -> str:
    """Normalize a URL so syndicated republications of one link match.

    Lowercased host without www., tracking params stripped, remaining
    query sorted, fragment and trailing slash dropped. Empty for no URL.
    """
    raw = str(url or "").strip()
    if not raw:
        return ""
    raw = raw.split("#", 1)[0]
    raw = re.sub(r"^https?://", "", raw, flags=re.IGNORECASE)
    host, _, rest = raw.partition("/")
    host = host.casefold().removeprefix("www.")
    path, _, query = rest.partition("?")
    path = path.rstrip("/")
    kept = sorted(
        p for p in query.split("&")
        if p and not any(p.casefold().startswith(t) for t in _TRACKING_PARAMS)
    )
    return host + ("/" + path if path else "") + ("?" + "&".join(kept) if kept else "")


def wire_lineage(item: dict) -> str | None:
    """Wire-service lineage label ('reuters', 'ap', 'pti', …) if detectable."""
    blob = (str(item.get("claim", "")) + " " + str(item.get("source_name", ""))
            + " " + str(item.get("provenance", ""))).casefold()
    for marker, label in _WIRE_LINEAGE_MARKERS.items():
        if marker in blob:
            return label
    return None


def catalyst_class(text: str) -> str | None:
    low = str(text or "").casefold()
    for klass, markers in _CATALYST_CLASSES.items():
        if any(m in low for m in markers):
            return klass
    return None


def entity_catalyst_fingerprint(item: dict) -> dict:
    """{symbol, catalyst, numbers} — the story's skeleton, not its wording."""
    claim = str(item.get("claim", ""))
    return {
        "symbol": str(item.get("symbol", "")).upper(),
        "catalyst": catalyst_class(claim),
        "numbers": frozenset(
            n.replace(",", "").rstrip(".") for n in _NUMBER_RE.findall(claim)
        ),
    }


def _fingerprints_match(a: dict, b: dict) -> bool:
    """Same entity + same catalyst class + at least one shared number."""
    return bool(
        a["symbol"] and a["symbol"] == b["symbol"]
        and a["catalyst"] is not None and a["catalyst"] == b["catalyst"]
        and a["numbers"] & b["numbers"]
    )


def _join_reason(items: list[dict], i: int, j: int,
                 sigs: list[frozenset[str]], threshold: float) -> tuple[float, str] | None:
    """(confidence, human-readable reason) if i and j belong together."""
    url_i = canonical_url(items[i].get("provenance"))
    url_j = canonical_url(items[j].get("provenance"))
    if url_i and url_i == url_j:
        return 1.0, f"identical canonical URL ({url_i[:60]})"
    if sigs[i] and sigs[j]:
        sim = jaccard(sigs[i], sigs[j])
        if sim >= threshold:
            return round(sim, 3), f"lexical near-duplicate (Jaccard {sim:.2f})"
    fp_i = entity_catalyst_fingerprint(items[i])
    fp_j = entity_catalyst_fingerprint(items[j])
    if _fingerprints_match(fp_i, fp_j):
        lin_i, lin_j = wire_lineage(items[i]), wire_lineage(items[j])
        if lin_i and lin_i == lin_j:
            return 0.85, (f"same entity+catalyst+figures AND shared wire "
                          f"lineage ({lin_i}) — one story, many mastheads")
        return 0.7, (f"same entity ({fp_i['symbol']}), same catalyst class "
                     f"({fp_i['catalyst']}), shared figures "
                     f"{sorted(fp_i['numbers'] & fp_j['numbers'])[:3]} — "
                     "paraphrased duplicate")
    return None


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
    joins: dict[int, tuple[float, str]] = {}
    for idx in range(len(items)):
        placed = False
        # Empty-text items with no URL/fingerprint signal stay independent:
        # they can neither prove duplication nor be a wire copy.
        for cluster in clusters:
            for member in cluster:
                reason = _join_reason(items, idx, member, sigs, threshold)
                if reason is not None:
                    cluster.append(idx)
                    joins[idx] = reason
                    placed = True
                    break
            if placed:
                break
        if not placed:
            clusters.append([idx])
    cluster_claims.last_joins = joins  # type: ignore[attr-defined]
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
    joins = getattr(cluster_claims, "last_joins", {})
    detail = []
    for cluster in clusters:
        outlets = sorted({
            str(items[i].get(source_key, "?")) for i in cluster
        })
        member_reasons = [joins[i] for i in cluster if i in joins]
        confidence = max((c for c, _ in member_reasons), default=1.0)
        explanations = sorted({r for _, r in member_reasons}) or [
            "single item — no duplication signal"
        ]
        lineages = sorted({l for l in (wire_lineage(items[i]) for i in cluster) if l})
        # Stale repost: a cluster member published much later than the first.
        published = []
        for i in cluster:
            age = items[i].get("freshness_days")
            if isinstance(age, (int, float)):
                published.append(age)
        stale_repost = bool(published) and (max(published) - min(published)
                                            > STALE_REPOST_DAYS)
        if stale_repost:
            explanations.append(
                f"STALE REPOST: same story re-published > "
                f"{STALE_REPOST_DAYS:.0f} days after the original — adds "
                "zero new information"
            )
        detail.append({
            "indices": cluster,
            "outlets": outlets,
            "copies": len(cluster),
            "representative": str(items[cluster[0]].get(text_key, ""))[:120],
            "cluster_confidence": confidence,
            "why_clustered": explanations,
            "wire_lineage": lineages,
            "stale_repost": stale_repost,
        })
    # Lineage-aware independence: clusters that are DIFFERENT stories but
    # share one wire lineage for the same symbol are only partially
    # independent (one newsroom feeding several stories).
    lineage_seen: dict[tuple[str, str], int] = {}
    partially_independent = 0
    for d in detail:
        symbol = str(items[d["indices"][0]].get("symbol", "")).upper()
        for lin in d["wire_lineage"]:
            key = (symbol, lin)
            lineage_seen[key] = lineage_seen.get(key, 0) + 1
            if lineage_seen[key] > 1:
                partially_independent += 1
                d["why_clustered"].append(
                    f"PARTIAL INDEPENDENCE: shares wire lineage "
                    f"({lin}) with another cluster on {symbol} — verify the "
                    "stories are truly separate before counting both"
                )
                break
    return {
        "raw_count": len(items),
        "effective_count": len(clusters),
        "lineage_discounted_count": len(clusters) - partially_independent,
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
