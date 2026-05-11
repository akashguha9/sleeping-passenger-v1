"""
Live signal domain classifier and source-name normalizer.

classify_market_domain()  — strictly gates Polymarket (and other prediction
    market) items to finance / politics / geopolitics / economy domains.
    Blocked terms always win over allowed terms.

normalize_source_name()   — maps backend source-name variants to the
    canonical dashboard display names used in the frontend.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Allowed domain terms
# ---------------------------------------------------------------------------
# A market is accepted when at least one of these appears in the lowercase
# concatenation of (title, category, tags).
_ALLOWED_TERMS: list[str] = [
    # Politics / elections
    "politics", "election", "president", "senate", "congress", "parliament",
    "prime minister", "trump", "biden", "vance", "modi",
    # Geopolitics / countries
    "china", "taiwan", "iran", "israel", "russia", "ukraine",
    # Central banks
    "fed", "federal reserve", "fomc", "ecb", "bank of england",
    "rbi", "sebi", "nse", "bse",
    # Macro / economy
    "rate cut", "rate hike", "interest rate", "inflation", "cpi", "ppi",
    "gdp", "recession", "unemployment",
    # Trade / sanctions / war
    "tariff", "sanctions", "export controls", "trade",
    "war", "ceasefire", "diplomatic", "blockade", "invasion", "coup",
    "enriched uranium", "nuclear",
    "strait of hormuz",
    # Energy / commodities
    "oil", "crude", "wti", "brent", "gold", "silver", "copper", "gas", "energy",
    # Equities / indices
    "s&p", "spx", "spy", "nasdaq", "qqq", "dow",
    "nvidia", "tesla", "apple", "microsoft", "alphabet",
    "coinbase", "microstrategy",
    # Crypto (macro-relevant only)
    "bitcoin", "ethereum", "crypto", "stablecoin",
    # Fixed income
    "treasury", "yields", "bond", "debt ceiling",
    # Catch-all financial
    "company", "market cap", "earnings", "ipo",
]

# ---------------------------------------------------------------------------
# Blocked domain terms (hard-blocked — wins over any allowed match)
# ---------------------------------------------------------------------------
_BLOCKED_TERMS: list[str] = [
    # Sports
    "sports", "nhl", "stanley cup", "nba", "nfl", "mlb", "ufc", "wwe",
    "tennis", "formula 1", " f1 ",
    # Sport teams by name (redundant to league names above, belt-and-suspenders)
    "sabres", "hurricanes", "avalanche", "golden knights",
    "flyers", "canadiens",
    # Soccer / football
    "football", "soccer", "cricket",
    # Music / entertainment
    "music", "album", "rihanna", "playboi carti", "taylor swift", "drake",
    "kendrick", "grammy", "oscars", "movie", "film", " tv ", "netflix",
    "celebrity", "influencer",
    # Gaming
    "gaming", "gta vi", "gta", "grand theft auto",
    # Meme / pop-culture
    "jesus christ", "pope joke", "meme", "relationship", "dating",
    "reality show",
]

# ---------------------------------------------------------------------------
# Pre-compiled blocked patterns — word-boundary anchored so that short
# abbreviations like "nba" do NOT fire on words containing them (e.g.
# "coinbase" or "inflammation").  Negative lookbehind/lookahead on
# [a-zA-Z] handles punctuation-adjacent terms like "s&p".
# ---------------------------------------------------------------------------
def _blocked_pattern(term: str) -> re.Pattern:
    return re.compile(
        r"(?<![a-zA-Z])" + re.escape(term) + r"(?![a-zA-Z])",
        re.IGNORECASE,
    )


_BLOCKED_PATTERNS: dict[str, re.Pattern] = {
    t: _blocked_pattern(t) for t in _BLOCKED_TERMS
}


# ---------------------------------------------------------------------------
# Domain assignment: first allowed term that matches decides the domain
# priority order: geopolitics > politics > economy > finance
# ---------------------------------------------------------------------------
_TERM_DOMAIN: dict[str, str] = {
    # Geopolitics
    "china": "geopolitics",
    "taiwan": "geopolitics",
    "iran": "geopolitics",
    "israel": "geopolitics",
    "russia": "geopolitics",
    "ukraine": "geopolitics",
    "strait of hormuz": "geopolitics",
    "war": "geopolitics",
    "ceasefire": "geopolitics",
    "diplomatic": "geopolitics",
    "blockade": "geopolitics",
    "invasion": "geopolitics",
    "coup": "geopolitics",
    "enriched uranium": "geopolitics",
    "nuclear": "geopolitics",
    "trade": "geopolitics",
    "export controls": "geopolitics",
    "sanctions": "geopolitics",
    "tariff": "geopolitics",
    "modi": "geopolitics",
    # Politics
    "politics": "politics",
    "election": "politics",
    "president": "politics",
    "senate": "politics",
    "congress": "politics",
    "parliament": "politics",
    "prime minister": "politics",
    "trump": "politics",
    "biden": "politics",
    "vance": "politics",
    # Economy
    "rate cut": "economy",
    "rate hike": "economy",
    "interest rate": "economy",
    "inflation": "economy",
    "cpi": "economy",
    "ppi": "economy",
    "gdp": "economy",
    "recession": "economy",
    "unemployment": "economy",
}
# Everything not listed above is finance
_DOMAIN_PRIORITY: list[str] = ["geopolitics", "politics", "economy", "finance"]

# ---------------------------------------------------------------------------
# Source-name normalisation
# ---------------------------------------------------------------------------
_SOURCE_NAME_MAP: dict[str, str] = {
    "polymarket": "Polymarket",
    "gdelt": "GDELT",
    "sec": "SEC EDGAR",
    "sec_edgar": "SEC EDGAR",
    "edgar": "SEC EDGAR",
    "newsapi": "NewsAPI",
    "news_api": "NewsAPI",
    "eventregistry": "Event Registry",
    "event_registry": "Event Registry",
    "etherscan": "Etherscan",
    "grok": "Grok/xAI",
    "xai": "Grok/xAI",
    "grok_xai": "Grok/xAI",
    "grok/xai": "Grok/xAI",
    "market_data": "Market Data",
    "india": "India",
    "global_filings": "Global Filings",
    "asia_disclosure": "Asia Disclosure",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_market_domain(
    title: str,
    category: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    """
    Classify a prediction-market question against the allowed set of
    finance / politics / geopolitics / economy domain terms.

    Parameters
    ----------
    title:
        Market question text.
    category:
        Optional market category string from the provider.
    tags:
        Optional list of tag strings from the provider.

    Returns
    -------
    dict with keys:
        allowed (bool)        — True only when allowed terms match AND no
                                blocked terms match.
        domain (str)          — one of "politics", "finance", "geopolitics",
                                "economy", "blocked", "unknown".
        reason (str)          — human-readable explanation.
        matched_terms (list)  — allowed terms found in the corpus.
        blocked_terms (list)  — blocked terms found in the corpus.

    Rules
    -----
    - Blocked terms always win; if any blocked term matches the market is
      rejected regardless of allowed-term matches.
    - If no allowed term matches (and no blocked term) the market is rejected
      as "unknown" domain.
    - Domain is assigned from the highest-priority allowed term matched.
    """
    parts: list[str] = [title or ""]
    if category:
        parts.append(category)
    if tags:
        parts.extend(str(t) for t in tags)
    corpus = " " + " ".join(parts).lower() + " "

    matched: list[str] = [t for t in _ALLOWED_TERMS if t in corpus]
    # Use word-boundary patterns for blocked terms to avoid false positives
    # such as "nfl" matching inside "inflation" or "nba" inside "coinbase".
    blocked: list[str] = [
        t for t, pat in _BLOCKED_PATTERNS.items() if pat.search(corpus)
    ]

    if blocked:
        return {
            "allowed": False,
            "domain": "blocked",
            "reason": f"blocked term(s) matched: {', '.join(blocked)}",
            "matched_terms": matched,
            "blocked_terms": blocked,
        }

    if not matched:
        return {
            "allowed": False,
            "domain": "unknown",
            "reason": "no allowed domain terms matched",
            "matched_terms": [],
            "blocked_terms": [],
        }

    assigned_domains: set[str] = {
        _TERM_DOMAIN.get(t, "finance") for t in matched
    }
    domain = next(
        (d for d in _DOMAIN_PRIORITY if d in assigned_domains),
        "finance",
    )

    return {
        "allowed": True,
        "domain": domain,
        "reason": f"matched domain terms: {', '.join(matched[:5])}",
        "matched_terms": matched,
        "blocked_terms": [],
    }


def normalize_source_name(name: str) -> str:
    """Map any backend source-name variant to the canonical dashboard label."""
    return _SOURCE_NAME_MAP.get(name.lower().strip(), name)


__all__ = [
    "classify_market_domain",
    "normalize_source_name",
    "_ALLOWED_TERMS",
    "_BLOCKED_TERMS",
    "_SOURCE_NAME_MAP",
]
