"""
Semantic pairing primitives for cross-venue prediction-market matching.

This module provides the *deterministic, dependency-free* baseline that the
Polymarket × Kalshi disagreement scanner uses to decide whether a
Polymarket market and a Kalshi market refer to the SAME real-world event.

Hard non-goals
--------------
- This is NOT trading.  It is NOT execution.  It is NOT a buy/sell signal.
- It does NOT touch a broker, place an order, or compute an arb size.
- It does NOT consult a live embedding API.  A swappable embedding
  interface is reserved for future use, but tests use a deterministic
  local baseline so results are reproducible offline.

Resolution-equivalence classes emitted by ``classify_pair_resolution``::

    SAME_EVENT_SAME_RESOLUTION    same event, same numeric threshold/condition
    SAME_EVENT_DIFFERENT_THRESHOLD same event, different threshold/condition
    SAME_THEME_DIFFERENT_EVENT     overlapping theme, different events
    AMBIGUOUS_MATCH                strong semantic match, weak metadata
    FALSE_MATCH                    insufficient overlap to claim a pair
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable

# Classification labels.
SAME_EVENT_SAME_RESOLUTION = "SAME_EVENT_SAME_RESOLUTION"
SAME_EVENT_DIFFERENT_THRESHOLD = "SAME_EVENT_DIFFERENT_THRESHOLD"
SAME_THEME_DIFFERENT_EVENT = "SAME_THEME_DIFFERENT_EVENT"
AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
FALSE_MATCH = "FALSE_MATCH"

CLASS_LABELS: tuple[str, ...] = (
    SAME_EVENT_SAME_RESOLUTION,
    SAME_EVENT_DIFFERENT_THRESHOLD,
    SAME_THEME_DIFFERENT_EVENT,
    AMBIGUOUS_MATCH,
    FALSE_MATCH,
)

# Anchors that contribute to the resolution check.  If both sides name
# the same asset+threshold+window the resolution is treated as identical;
# differing thresholds bump the classification to SAME_EVENT_DIFFERENT_THRESHOLD.
_ASSET_ANCHORS: tuple[str, ...] = (
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol",
    "dogecoin", "doge", "wti", "brent", "crude", "natural gas",
    "gold", "silver", "wheat", "corn", "soybean",
    "cpi", "ppi", "gdp", "pce", "fed", "fomc", "rate", "rates",
    "unemployment", "jobs", "nfp", "payroll",
    "s&p", "spx", "nasdaq", "ndx", "dow", "dji", "russell", "rut",
    "treasury", "yield", "vix", "yields",
    "president", "presidential", "senator", "senate", "house",
    "governor", "election", "primary", "trump", "biden",
)

# Words that signal a numeric resolution threshold.  When the two market
# titles disagree on the underlying number (e.g. $100k vs $150k, May vs
# June, close-above vs hit) the resolution is NOT identical even if the
# theme matches perfectly.
_THRESHOLD_WORDS: tuple[str, ...] = (
    "above", "below", "over", "under", "at least", "exceed", "exceeds",
    "hit", "reach", "close", "settle", "settles", "rise", "fall", "drop",
    "close above", "close below",
)

# Lightweight English stopword set — keep small and deterministic.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "and", "any", "are", "as", "at", "be", "by", "do",
        "does", "for", "from", "get", "gets", "going", "has", "have",
        "in", "into", "is", "it", "of", "on", "or", "that", "the",
        "this", "to", "was", "were", "what", "when", "where", "which",
        "will", "with", "would", "you", "your",
    }
)


# ---------------------------------------------------------------------------
# Tokenisation + similarity
# ---------------------------------------------------------------------------


def _tokenize(text: Any) -> list[str]:
    if text is None:
        return []
    raw = str(text).strip().lower()
    if not raw:
        return []
    # Keep alphanumerics; preserve common decimal numbers like 100k or 100,000.
    tokens = re.findall(r"[a-z0-9$%][a-z0-9$%,\.k]*", raw)
    cleaned: list[str] = []
    for tok in tokens:
        if tok in _STOPWORDS:
            continue
        cleaned.append(tok)
    return cleaned


def _token_set(text: Any) -> set[str]:
    return set(_tokenize(text))


def jaccard_similarity(a: Any, b: Any) -> float:
    """Tokenised Jaccard over two strings (stopwords stripped).

    Returns 0.0 if either side is empty.  Result lives in ``[0, 1]``.
    """
    ta = _token_set(a)
    tb = _token_set(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def entity_overlap(a: Any, b: Any) -> set[str]:
    """Return the intersection of recognised entity tokens between two strings."""
    ta = _token_set(a) & set(_ASSET_ANCHORS)
    tb = _token_set(b) & set(_ASSET_ANCHORS)
    return ta & tb


def _extract_thresholds(text: Any) -> set[str]:
    """Extract numeric thresholds from a string.

    Recognises dollar amounts ($100k, $1,000,000), bare numbers in price
    contexts (e.g. 100k, 5%, 4.5), and percentage values.  Returns a set
    of canonicalised threshold tokens (e.g. ``{"$100k"}``).
    """
    if text is None:
        return set()
    raw = str(text).lower()
    # $-prefixed amounts.
    matches = re.findall(r"\$\s?\d[\d,\.]*\s?(?:k|m|b|bn|million|billion)?", raw)
    # Bare percentages and numbers.
    matches += re.findall(r"\b\d[\d,\.]*\s?%", raw)
    matches += re.findall(r"\b\d{2,}[\d,\.]*\s?(?:k|m|b|bn)?", raw)
    canonical: set[str] = set()
    for m in matches:
        c = re.sub(r"\s+", "", m)
        canonical.add(c)
    return canonical


def _extract_months(text: Any) -> set[str]:
    if text is None:
        return set()
    raw = str(text).lower()
    months = re.findall(
        r"\b(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|"
        r"jul|july|aug|august|sep|sept|september|oct|october|nov|november|"
        r"dec|december)\b",
        raw,
    )
    canonical_map = {
        "jan": "january", "feb": "february", "mar": "march",
        "apr": "april", "jun": "june", "jul": "july",
        "aug": "august", "sep": "september", "sept": "september",
        "oct": "october", "nov": "november", "dec": "december",
        "may": "may",
    }
    return {canonical_map.get(m, m) for m in months}


# ---------------------------------------------------------------------------
# Embedding interface (swappable, default = deterministic fake)
# ---------------------------------------------------------------------------


EmbeddingFn = Callable[[str], "list[float] | None"]


def deterministic_fake_embedding(text: str) -> list[float] | None:
    """A purely-local, deterministic stand-in for a real embedding model.

    The vector is a 16-dim histogram over hashed token buckets.  This is
    not a "good" embedding — it is *consistent* so disagreement scanner
    tests stay reproducible without a network round trip.
    """
    if not text:
        return None
    vec = [0.0] * 16
    for tok in _tokenize(text):
        vec[hash(tok) % 16] += 1.0
    norm = sum(v * v for v in vec) ** 0.5
    if not norm:
        return None
    return [v / norm for v in vec]


def cosine_similarity(vec_a: list[float] | None, vec_b: list[float] | None) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    return max(0.0, min(1.0, dot))


# ---------------------------------------------------------------------------
# Pair classification
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PairClassification:
    """Output of :func:`classify_pair_resolution`."""

    pair_type: str
    semantic_similarity: float
    embedding_similarity: float
    shared_entities: list[str]
    shared_thresholds: list[str]
    shared_months: list[str]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_type": self.pair_type,
            "semantic_similarity": round(self.semantic_similarity, 4),
            "embedding_similarity": round(self.embedding_similarity, 4),
            "shared_entities": list(self.shared_entities),
            "shared_thresholds": list(self.shared_thresholds),
            "shared_months": list(self.shared_months),
            "reasons": list(self.reasons),
        }


def _market_text(market: dict[str, Any]) -> str:
    """Best-available semantic text for a market — semantic_text if
    populated by the source, otherwise the title plus any description."""
    if not isinstance(market, dict):
        return ""
    text = str(market.get("semantic_text") or "").strip()
    if text:
        return text
    parts = [
        str(market.get("title") or market.get("question") or "").strip(),
        str(market.get("description") or "").strip(),
        str(market.get("rules") or market.get("rules_primary") or "").strip(),
    ]
    return " \n".join(p for p in parts if p)


def _categories_compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Markets must come from compatible categories to count as a pair.

    Polymarket uses domain labels ("politics", "economy", "crypto", ...),
    Kalshi uses the canonical 7-category allowlist.  Compatibility is
    case-insensitive overlap on the first word of each.
    """
    a_cat = str(a.get("category") or a.get("domain") or "").strip().lower()
    b_cat = str(b.get("category") or b.get("domain") or "").strip().lower()
    if not a_cat or not b_cat:
        return True  # be permissive — semantic score still gates
    # Quick canonical mapping so "Crypto" matches "crypto".
    compat_groups = (
        {"crypto", "cryptocurrency"},
        {"elections", "election", "politics", "political"},
        {"economics", "economy", "macro"},
        {"finance", "financial", "markets"},
        {"commodities", "commodity"},
        {"tech & science", "tech", "science", "technology"},
    )
    for group in compat_groups:
        if a_cat in group and b_cat in group:
            return True
    return a_cat == b_cat


def classify_pair_resolution(
    polymarket: dict[str, Any],
    kalshi: dict[str, Any],
    *,
    embedding_fn: EmbeddingFn = deterministic_fake_embedding,
    semantic_threshold: float = 0.42,
    ambiguous_floor: float = 0.30,
) -> PairClassification:
    """Classify the resolution-equivalence relationship between two markets.

    The classification routes the pair to one of the labels described in
    the module docstring.  Only ``SAME_EVENT_SAME_RESOLUTION`` and
    high-confidence ``AMBIGUOUS_MATCH`` pairs are eligible for clean
    disagreement alerts in the downstream scanner — the rest produce
    "watch" / "reject" diagnostics only.

    The scoring is deliberately layered:

    1. category compatibility (gate)
    2. tokenised Jaccard similarity (broad semantic anchor)
    3. asset-anchor entity overlap (must share at least one)
    4. threshold compatibility (same number → same resolution)
    5. event-window compatibility (same month or close window)
    6. embedding cosine (optional extra signal; uses the deterministic
       fake unless ``embedding_fn`` is overridden)
    """
    poly_text = _market_text(polymarket)
    kalshi_text = _market_text(kalshi)

    semantic = jaccard_similarity(poly_text, kalshi_text)
    shared = entity_overlap(poly_text, kalshi_text)
    poly_thresholds = _extract_thresholds(poly_text)
    kalshi_thresholds = _extract_thresholds(kalshi_text)
    shared_thresholds = poly_thresholds & kalshi_thresholds
    poly_months = _extract_months(poly_text)
    kalshi_months = _extract_months(kalshi_text)
    shared_months = poly_months & kalshi_months

    emb_a = embedding_fn(poly_text)
    emb_b = embedding_fn(kalshi_text)
    emb_sim = cosine_similarity(emb_a, emb_b)

    reasons: list[str] = []

    if not _categories_compatible(polymarket, kalshi):
        reasons.append("incompatible_category")
        return PairClassification(
            pair_type=FALSE_MATCH,
            semantic_similarity=semantic,
            embedding_similarity=emb_sim,
            shared_entities=sorted(shared),
            shared_thresholds=sorted(shared_thresholds),
            shared_months=sorted(shared_months),
            reasons=reasons,
        )

    if semantic < ambiguous_floor and emb_sim < ambiguous_floor and not shared:
        reasons.append("low_semantic_overlap_no_shared_entity")
        return PairClassification(
            pair_type=FALSE_MATCH,
            semantic_similarity=semantic,
            embedding_similarity=emb_sim,
            shared_entities=sorted(shared),
            shared_thresholds=sorted(shared_thresholds),
            shared_months=sorted(shared_months),
            reasons=reasons,
        )

    if not shared:
        reasons.append("no_shared_asset_entity")
        return PairClassification(
            pair_type=AMBIGUOUS_MATCH if semantic >= semantic_threshold else SAME_THEME_DIFFERENT_EVENT,
            semantic_similarity=semantic,
            embedding_similarity=emb_sim,
            shared_entities=sorted(shared),
            shared_thresholds=sorted(shared_thresholds),
            shared_months=sorted(shared_months),
            reasons=reasons,
        )

    # Threshold disagreement → SAME_EVENT_DIFFERENT_THRESHOLD only if
    # both sides explicitly named a number AND they do not overlap.
    thresholds_disagree = (
        poly_thresholds and kalshi_thresholds and not shared_thresholds
    )
    # Different month names in both titles disagree on window.
    months_disagree = (
        poly_months and kalshi_months and not shared_months
    )

    if thresholds_disagree or months_disagree:
        reasons.append(
            "threshold_or_window_mismatch"
            f" (poly_thresholds={sorted(poly_thresholds)} "
            f"kalshi_thresholds={sorted(kalshi_thresholds)} "
            f"poly_months={sorted(poly_months)} "
            f"kalshi_months={sorted(kalshi_months)})"
        )
        return PairClassification(
            pair_type=SAME_EVENT_DIFFERENT_THRESHOLD,
            semantic_similarity=semantic,
            embedding_similarity=emb_sim,
            shared_entities=sorted(shared),
            shared_thresholds=sorted(shared_thresholds),
            shared_months=sorted(shared_months),
            reasons=reasons,
        )

    if semantic >= semantic_threshold:
        reasons.append("strong_semantic_match")
        return PairClassification(
            pair_type=SAME_EVENT_SAME_RESOLUTION,
            semantic_similarity=semantic,
            embedding_similarity=emb_sim,
            shared_entities=sorted(shared),
            shared_thresholds=sorted(shared_thresholds),
            shared_months=sorted(shared_months),
            reasons=reasons,
        )

    reasons.append("shared_entity_but_below_semantic_threshold")
    return PairClassification(
        pair_type=AMBIGUOUS_MATCH,
        semantic_similarity=semantic,
        embedding_similarity=emb_sim,
        shared_entities=sorted(shared),
        shared_thresholds=sorted(shared_thresholds),
        shared_months=sorted(shared_months),
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def iter_pair_candidates(
    polymarket_rows: Iterable[dict[str, Any]],
    kalshi_rows: Iterable[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Produce the full cross-product of (polymarket, kalshi) candidate pairs."""
    poly = list(polymarket_rows)
    kalshi = list(kalshi_rows)
    return [(p, k) for p in poly for k in kalshi]


__all__ = [
    "SAME_EVENT_SAME_RESOLUTION",
    "SAME_EVENT_DIFFERENT_THRESHOLD",
    "SAME_THEME_DIFFERENT_EVENT",
    "AMBIGUOUS_MATCH",
    "FALSE_MATCH",
    "CLASS_LABELS",
    "PairClassification",
    "jaccard_similarity",
    "entity_overlap",
    "deterministic_fake_embedding",
    "cosine_similarity",
    "classify_pair_resolution",
    "iter_pair_candidates",
]
