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

# Resolution-style families.  A title that includes a "touch" verb
# (``hit``, ``touch``, ``reach``, ``trade at``, ``anytime``, ``intramonth``)
# resolves on intra-window contact and is NOT the same resolution as a
# "close" verb (``close above``, ``settle``, ``end of`` <period>).
_TOUCH_STYLE_VERBS: frozenset[str] = frozenset(
    {
        "hit", "touch", "touches", "reach", "reaches",
        "trades", "trade", "intramonth", "anytime", "anywhere",
        "any point",
    }
)
_CLOSE_STYLE_VERBS: frozenset[str] = frozenset(
    {
        "close", "closes", "closing", "settle", "settles", "settled",
        "end of", "year-end", "yearend", "endofmonth", "endofyear",
        "month-end", "weekly close",
    }
)

# Date-precision phrases.  ``before/by <date>`` resolves on any tick
# before the date; ``on <date>`` resolves only on the named day.  Both
# must agree for a clean alert.
_BEFORE_DATE_PHRASES: frozenset[str] = frozenset(
    {"before", "by", "prior to", "by end of", "before end of", "by year end"}
)
_ON_DATE_PHRASES: frozenset[str] = frozenset(
    {"on ", "at exactly ", "exact date "}
)

# Direction families — above/below is NOT the same condition as reach/touch
# even though both might fire on the same price level.
_DIRECTION_ABOVE: frozenset[str] = frozenset(
    {"above", "over", "exceed", "exceeds", "greater than", "higher than"}
)
_DIRECTION_BELOW: frozenset[str] = frozenset(
    {"below", "under", "less than", "lower than"}
)

# Settlement-source markers (e.g. ``Coinbase``, ``CoinDesk``, ``CME``).
# Pairs that name *different* sources should NOT be promoted to
# SAME_EVENT_SAME_RESOLUTION even if everything else matches.
_SETTLEMENT_SOURCE_TOKENS: tuple[str, ...] = (
    "coinbase", "coindesk", "binance", "kraken", "bitstamp",
    "cme", "ice", "nymex", "fomc statement", "bloomberg index",
    "bls report", "treasury close", "yahoo finance",
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

    Recognises dollar amounts (``$100k``, ``$1,000,000``), percentages
    (``5%``), and bare numbers that carry an unambiguous magnitude
    suffix (``k``, ``m``, ``b``, ``bn``).  Date components (``01``,
    ``05``, ``2026``, ``31``) and other bare integers are deliberately
    NOT matched — they were a major false-mismatch source in the
    pre-10/10 scanner.
    """
    if text is None:
        return set()
    raw = str(text).lower()
    matches: list[str] = []
    # $-prefixed amounts.
    matches += re.findall(r"\$\s?\d[\d,\.]*\s?(?:k|m|b|bn|million|billion)?", raw)
    # Percentages.
    matches += re.findall(r"\b\d[\d,\.]*\s?%", raw)
    # Bare numbers with an unambiguous magnitude suffix (e.g. ``100k``,
    # ``1.5m``).  The trailing suffix is required so a date component
    # like ``2026`` or ``05`` can't be promoted to a threshold.
    matches += re.findall(r"\b\d[\d,\.]*\s?(?:k|m|b|bn|million|billion)\b", raw)
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


def _extract_years(text: Any) -> set[str]:
    if text is None:
        return set()
    raw = str(text).lower()
    return set(re.findall(r"\b(20\d{2})\b", raw))


def _detect_resolution_style(text: Any) -> str | None:
    """Return ``"touch"`` / ``"close"`` / ``None`` for a market text.

    Mixed signals (text mentions both ``hit`` and ``close``) return ``None``
    so the pairing layer treats the resolution as ambiguous rather than
    forcing a wrong family.
    """
    if text is None:
        return None
    raw = str(text).lower()
    touch_hit = any(re.search(rf"\b{re.escape(v)}\b", raw) for v in _TOUCH_STYLE_VERBS)
    close_hit = any(re.search(rf"\b{re.escape(v)}\b", raw) for v in _CLOSE_STYLE_VERBS)
    if touch_hit and close_hit:
        return None
    if touch_hit:
        return "touch"
    if close_hit:
        return "close"
    return None


def _detect_date_precision(text: Any) -> str | None:
    """Return ``"by"`` (range) / ``"on"`` (exact) / ``None``."""
    if text is None:
        return None
    raw = str(text).lower()
    by_hit = any(p in raw for p in _BEFORE_DATE_PHRASES)
    on_hit = any(p in raw for p in _ON_DATE_PHRASES)
    if by_hit and on_hit:
        return None  # ambiguous
    if by_hit:
        return "by"
    if on_hit:
        return "on"
    return None


def _detect_direction(text: Any) -> str | None:
    """Return ``"above"`` / ``"below"`` / ``None``."""
    if text is None:
        return None
    raw = str(text).lower()
    above_hit = any(w in raw for w in _DIRECTION_ABOVE)
    below_hit = any(w in raw for w in _DIRECTION_BELOW)
    if above_hit and below_hit:
        return None
    if above_hit:
        return "above"
    if below_hit:
        return "below"
    return None


def _extract_settlement_sources(text: Any) -> set[str]:
    """Whole-word match for settlement-source tokens.

    Substring match would let ``"price"`` trigger ``"ice"`` and ``"yahoo"``
    trigger ``"hoo"`` — both real false-positives seen during the 10/10
    sprint.  We compile a word-boundary regex per token so the match
    matches the spirit of the token list.
    """
    if text is None:
        return set()
    raw = str(text).lower()
    out: set[str] = set()
    for token in _SETTLEMENT_SOURCE_TOKENS:
        # Single tokens like ``coinbase`` need \b boundaries.  Multi-word
        # tokens like ``fomc statement`` need plain substring match
        # (``\bfomc statement\b`` is fine since both ends are word chars).
        pattern = r"\b" + re.escape(token) + r"\b"
        if re.search(pattern, raw):
            out.add(token)
    return out


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
    """Output of :func:`classify_pair_resolution`.

    ``pair_score_components`` exposes the per-axis scores that produced
    the final classification.  Each component lives in ``[0, 1]`` and
    has a fixed semantic meaning:

      - ``text_score``        — jaccard token overlap between titles
      - ``entity_score``      — recognised asset/entity overlap
      - ``category_score``    — 1.0 when categories are compatible, 0.0 otherwise
      - ``date_score``        — month/year overlap consistency
      - ``threshold_score``   — numeric threshold agreement
      - ``resolution_score``  — touch/close + above/below + before/on agreement
      - ``embedding_score``   — cosine on the swappable embedding fn
      - ``final_score``       — weighted blend used for sorting/ranking

    ``resolution_mismatch_reasons`` lists the exact axes (threshold,
    timing, touch-vs-close, settlement-source, entity, event-window,
    direction) that downgraded the pair.  Empty when the resolution is
    clean.
    """

    pair_type: str
    semantic_similarity: float
    embedding_similarity: float
    shared_entities: list[str]
    shared_thresholds: list[str]
    shared_months: list[str]
    reasons: list[str]
    pair_score_components: dict[str, float] | None = None
    resolution_mismatch_reasons: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_type": self.pair_type,
            "semantic_similarity": round(self.semantic_similarity, 4),
            "embedding_similarity": round(self.embedding_similarity, 4),
            "shared_entities": list(self.shared_entities),
            "shared_thresholds": list(self.shared_thresholds),
            "shared_months": list(self.shared_months),
            "reasons": list(self.reasons),
            "pair_score_components": dict(self.pair_score_components or {}),
            "resolution_mismatch_reasons": list(self.resolution_mismatch_reasons or []),
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


def _component_scores(
    *,
    semantic: float,
    emb_sim: float,
    shared_entities: set[str],
    poly_thresholds: set[str],
    kalshi_thresholds: set[str],
    shared_thresholds: set[str],
    poly_months: set[str],
    kalshi_months: set[str],
    shared_months: set[str],
    poly_years: set[str],
    kalshi_years: set[str],
    category_compatible: bool,
    resolution_consistent: bool,
) -> dict[str, float]:
    """Compute the 0..1 component scores used by ``PairClassification``."""
    text_score = float(max(0.0, min(1.0, semantic)))
    entity_score = 1.0 if shared_entities else 0.0
    category_score = 1.0 if category_compatible else 0.0
    if poly_thresholds or kalshi_thresholds:
        threshold_score = 1.0 if shared_thresholds else 0.0
    else:
        threshold_score = 0.5  # neither side named a number
    months_agree = (not poly_months and not kalshi_months) or bool(shared_months)
    years_agree = (not poly_years and not kalshi_years) or bool(poly_years & kalshi_years)
    date_score = 1.0 if (months_agree and years_agree) else 0.0
    resolution_score = 1.0 if resolution_consistent else 0.0
    embedding_score = float(max(0.0, min(1.0, emb_sim)))
    final_score = round(
        0.32 * text_score
        + 0.18 * entity_score
        + 0.10 * category_score
        + 0.08 * date_score
        + 0.12 * threshold_score
        + 0.12 * resolution_score
        + 0.08 * embedding_score,
        4,
    )
    return {
        "text_score": round(text_score, 4),
        "entity_score": round(entity_score, 4),
        "category_score": round(category_score, 4),
        "date_score": round(date_score, 4),
        "threshold_score": round(threshold_score, 4),
        "resolution_score": round(resolution_score, 4),
        "embedding_score": round(embedding_score, 4),
        "final_score": final_score,
    }


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
    poly_years = _extract_years(poly_text)
    kalshi_years = _extract_years(kalshi_text)

    poly_style = _detect_resolution_style(poly_text)
    kalshi_style = _detect_resolution_style(kalshi_text)
    poly_date_precision = _detect_date_precision(poly_text)
    kalshi_date_precision = _detect_date_precision(kalshi_text)
    poly_direction = _detect_direction(poly_text)
    kalshi_direction = _detect_direction(kalshi_text)
    poly_settlement = _extract_settlement_sources(poly_text)
    kalshi_settlement = _extract_settlement_sources(kalshi_text)

    emb_a = embedding_fn(poly_text)
    emb_b = embedding_fn(kalshi_text)
    emb_sim = cosine_similarity(emb_a, emb_b)

    category_compatible = _categories_compatible(polymarket, kalshi)
    reasons: list[str] = []
    mismatch_reasons: list[str] = []

    # Resolution-style mismatch detection — used both for the
    # consistency flag (drives ``resolution_score``) and for the explicit
    # ``resolution_mismatch_reasons`` block on every PairClassification.
    if poly_style and kalshi_style and poly_style != kalshi_style:
        mismatch_reasons.append(
            f"resolution_style_mismatch:poly={poly_style}/kalshi={kalshi_style}"
        )
    if (
        poly_date_precision
        and kalshi_date_precision
        and poly_date_precision != kalshi_date_precision
    ):
        mismatch_reasons.append(
            f"date_precision_mismatch:poly={poly_date_precision}/kalshi={kalshi_date_precision}"
        )
    if (
        poly_direction
        and kalshi_direction
        and poly_direction != kalshi_direction
    ):
        mismatch_reasons.append(
            f"direction_mismatch:poly={poly_direction}/kalshi={kalshi_direction}"
        )
    if (
        poly_settlement
        and kalshi_settlement
        and not (poly_settlement & kalshi_settlement)
    ):
        mismatch_reasons.append(
            f"settlement_source_mismatch:poly={sorted(poly_settlement)}/"
            f"kalshi={sorted(kalshi_settlement)}"
        )
    if poly_thresholds and kalshi_thresholds and not shared_thresholds:
        mismatch_reasons.append(
            f"threshold_mismatch:poly={sorted(poly_thresholds)}/"
            f"kalshi={sorted(kalshi_thresholds)}"
        )
    if poly_months and kalshi_months and not shared_months:
        mismatch_reasons.append(
            f"window_mismatch:poly={sorted(poly_months)}/kalshi={sorted(kalshi_months)}"
        )
    if poly_years and kalshi_years and not (poly_years & kalshi_years):
        mismatch_reasons.append(
            f"year_mismatch:poly={sorted(poly_years)}/kalshi={sorted(kalshi_years)}"
        )

    resolution_consistent = not mismatch_reasons

    components = _component_scores(
        semantic=semantic,
        emb_sim=emb_sim,
        shared_entities=shared,
        poly_thresholds=poly_thresholds,
        kalshi_thresholds=kalshi_thresholds,
        shared_thresholds=shared_thresholds,
        poly_months=poly_months,
        kalshi_months=kalshi_months,
        shared_months=shared_months,
        poly_years=poly_years,
        kalshi_years=kalshi_years,
        category_compatible=category_compatible,
        resolution_consistent=resolution_consistent,
    )

    def _build(pair_type: str, extra_reason: str | None = None) -> PairClassification:
        if extra_reason:
            reasons.append(extra_reason)
        return PairClassification(
            pair_type=pair_type,
            semantic_similarity=semantic,
            embedding_similarity=emb_sim,
            shared_entities=sorted(shared),
            shared_thresholds=sorted(shared_thresholds),
            shared_months=sorted(shared_months),
            reasons=list(reasons),
            pair_score_components=components,
            resolution_mismatch_reasons=list(mismatch_reasons),
        )

    if not category_compatible:
        return _build(FALSE_MATCH, "incompatible_category")

    if semantic < ambiguous_floor and emb_sim < ambiguous_floor and not shared:
        return _build(FALSE_MATCH, "low_semantic_overlap_no_shared_entity")

    if not shared:
        # No shared anchor — degrade.  Still note any resolution-axis
        # mismatch the operator might want to see.
        pair_type = AMBIGUOUS_MATCH if semantic >= semantic_threshold else SAME_THEME_DIFFERENT_EVENT
        return _build(pair_type, "no_shared_asset_entity")

    # We have a shared entity.  Any resolution-axis mismatch downgrades
    # us to SAME_EVENT_DIFFERENT_THRESHOLD (the diagnostic-only bucket)
    # so the scanner never raises a clean alert when threshold, timing,
    # touch-vs-close, settlement source, direction, or event window
    # disagree.  A large probability gap cannot bypass this guard.
    if mismatch_reasons:
        return _build(
            SAME_EVENT_DIFFERENT_THRESHOLD,
            "resolution_mismatch_blocks_clean_alert:" + ",".join(mismatch_reasons),
        )

    if semantic >= semantic_threshold:
        return _build(SAME_EVENT_SAME_RESOLUTION, "strong_semantic_match")

    return _build(AMBIGUOUS_MATCH, "shared_entity_but_below_semantic_threshold")


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
    "EmbeddingFn",
    "PairClassification",
    "jaccard_similarity",
    "entity_overlap",
    "deterministic_fake_embedding",
    "cosine_similarity",
    "classify_pair_resolution",
    "iter_pair_candidates",
]
