"""
Kalshi source normalizer — advisory-only, read-only.

This module is the canonical surface for turning a raw Kalshi market dict
into the normalized ``signal_events`` payload the rest of the MVP consumes.
It is also responsible for the category allowlist that gates which Kalshi
markets ever enter the canonical signal inbox.

Hard invariants (do not weaken):
- Every accepted record carries:
    advisory_status         = "ADVISORY_ONLY"
    execution_gate          = "LOCKED"
    execution_permission    = "ADVISORY_ONLY"
    human_review_required   = True
    advisory_only           = True
    broker_api_called       = False
    ai_execution_count      = 0
- No broker calls, no order placement, no execution surfaces.
- Disallowed categories are not normalized (return ``None``) and therefore
  never enter ``signal_events`` persistence.

This module intentionally does NO network I/O.  Live fetching is the
responsibility of ``scripts/ingestion/kalshi_loader.py`` (currently a
scaffold; real Kalshi API wiring is deferred).
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"
EXECUTION_PERMISSION_ADVISORY = "ADVISORY_ONLY"
AI_EXECUTION_COUNT = 0
HUMAN_REVIEW_REQUIRED = True
BROKER_API_CALLED = False

CANONICAL_SOURCE = "kalshi"
CANONICAL_SOURCE_LABEL = "Kalshi"

# ---------------------------------------------------------------------------
# Category allowlist
# ---------------------------------------------------------------------------
# Canonical display labels for the approved seven categories.  Anything not
# mapping to one of these is rejected for the main Kalshi inbox.
CANONICAL_CATEGORIES: tuple[str, ...] = (
    "Elections",
    "Politics",
    "Crypto",
    "Commodities",
    "Economics",
    "Finance",
    "Tech & Science",
)

# Lowercase raw -> canonical display label mapping.
KALSHI_CATEGORY_MAP: dict[str, str] = {
    "elections": "Elections",
    "election": "Elections",
    "politics": "Politics",
    "political": "Politics",
    "crypto": "Crypto",
    "cryptocurrency": "Crypto",
    "bitcoin": "Crypto",
    "commodities": "Commodities",
    "commodity": "Commodities",
    "economics": "Economics",
    "economy": "Economics",
    "macro": "Economics",
    "finance": "Finance",
    "financial": "Finance",
    "markets": "Finance",
    "tech & science": "Tech & Science",
    "tech and science": "Tech & Science",
    "technology": "Tech & Science",
    "science": "Tech & Science",
    "tech_science": "Tech & Science",
}

# Categories explicitly recognised as outside the approved scope.  Listed
# only for human-readable rejection reasons; any value not present in
# KALSHI_CATEGORY_MAP is rejected, this list does not have to be exhaustive.
EXPLICIT_REJECTED_CATEGORIES: frozenset[str] = frozenset(
    {
        "sports", "culture", "climate", "social", "entertainment",
        "lifestyle", "world", "weather",
        # Sprint-Kante hardening: esports/gaming and meta tabs (trending,
        # mentions, other) must NEVER enter the seven-tab Kalshi feed.
        "esports", "esport", "e-sports", "e_sports", "gaming", "videogames",
        "video games", "multi-game", "multi game", "multigame", "fantasy",
        "tennis", "golf", "soccer", "football", "basketball", "baseball",
        "hockey", "racing", "f1", "formula 1", "boxing", "mma",
        "trending", "mentions", "other", "unknown", "uncategorized",
    }
)

# Accepted Kalshi source-name variants — every value here maps to the
# canonical "kalshi" lowercase key.
_SOURCE_NAME_VARIANTS: frozenset[str] = frozenset(
    {"kalshi", "kalshi.com", "kalshi_official", "kalshi_api"}
)


# ---------------------------------------------------------------------------
# Source normalisation
# ---------------------------------------------------------------------------


def normalize_kalshi_source_name(raw: Any) -> str | None:
    """Return ``"kalshi"`` for any accepted Kalshi source-name variant.

    Returns ``None`` for unknown or empty input.  Whitespace is trimmed and
    matching is case-insensitive so ``"Kalshi"``, ``"KALSHI"``, and
    ``" kalshi "`` all normalise to ``"kalshi"``.
    """
    if not isinstance(raw, str):
        return None
    candidate = raw.strip().lower()
    if not candidate:
        return None
    if candidate in _SOURCE_NAME_VARIANTS:
        return CANONICAL_SOURCE
    return None


def is_kalshi_source(raw: Any) -> bool:
    """True when ``raw`` is any accepted Kalshi source-name variant."""
    return normalize_kalshi_source_name(raw) is not None


# ---------------------------------------------------------------------------
# Category classification
# ---------------------------------------------------------------------------


def _normalize_category_key(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    text = raw.strip().lower()
    if not text:
        return ""
    # collapse repeated whitespace
    text = re.sub(r"\s+", " ", text)
    # normalize " and " between words to " & " so "tech and science" matches
    # the same allowlist key as "tech & science".  (We keep both spellings
    # in the map for symmetry, but this guards against extra punctuation.)
    return text


def classify_kalshi_category(
    category: Any,
    *,
    tags: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Classify a raw Kalshi category into the canonical allowlist.

    Parameters
    ----------
    category:
        Raw category string from the Kalshi payload.  May be empty / None.
    tags:
        Optional iterable of tags — used as a *fallback* signal only when
        the primary category is unmapped.  We do not invent broad mappings.

    Returns
    -------
    dict with keys::

        {
          "allowed":          bool,
          "display_category": str | None,   # one of CANONICAL_CATEGORIES
          "raw_category":     str,          # echoed lowercase
          "reason":           str,          # human-readable
        }
    """
    raw = _normalize_category_key(category)
    if raw and raw in KALSHI_CATEGORY_MAP:
        return {
            "allowed": True,
            "display_category": KALSHI_CATEGORY_MAP[raw],
            "raw_category": raw,
            "reason": f"matched approved category '{raw}'",
        }

    # Fallback: tags-only match (only when category is empty/missing — we
    # do not let tags override an explicit non-approved category).
    if not raw and tags:
        for tag in tags:
            tag_key = _normalize_category_key(tag)
            if tag_key in KALSHI_CATEGORY_MAP:
                return {
                    "allowed": True,
                    "display_category": KALSHI_CATEGORY_MAP[tag_key],
                    "raw_category": "",
                    "reason": f"matched approved tag '{tag_key}'",
                }

    if not raw:
        return {
            "allowed": False,
            "display_category": None,
            "raw_category": "",
            "reason": "missing_category",
        }

    if raw in EXPLICIT_REJECTED_CATEGORIES:
        return {
            "allowed": False,
            "display_category": None,
            "raw_category": raw,
            "reason": f"category '{raw}' is not in the approved Kalshi allowlist",
        }

    return {
        "allowed": False,
        "display_category": None,
        "raw_category": raw,
        "reason": f"category '{raw}' is not in the approved Kalshi allowlist",
    }


# ---------------------------------------------------------------------------
# Evidence-based category inference (live Kalshi enrichment)
# ---------------------------------------------------------------------------
#
# Conservative heuristics layered on top of ``classify_kalshi_category``.
# Used when the raw payload's ``category`` field is missing or unmapped — a
# common reality on the public Kalshi API where many markets only carry an
# ``event_ticker`` reference and tags.  Each heuristic is unambiguous and
# documented; if no rule fires the market is REJECTED (not guessed at), so
# the strict allowlist stays intact.
#
# Order of precedence (first hit wins):
#   1. explicit ``category`` field
#   2. event payload ``category`` (joined via /events)
#   3. tag exact-match
#   4. series/event/ticker prefix exact-match (PRES, FED, BTC, ...)
#   5. ticker/title/description/rules keyword anchor (whole-word match)
#   6. reject with reason
#
# We intentionally do not chain partial matches: "stock-price" alone is not
# enough to claim "Finance" without a Finance-anchor keyword.  The point of
# this layer is to *recover real metadata*, not to expand the allowlist.

# Ticker-prefix → canonical category.  Each prefix is an unambiguous Kalshi
# series identifier; anything else falls through to keyword inference.
_TICKER_PREFIX_MAP: tuple[tuple[str, str], ...] = (
    # Elections / Politics
    ("PRES", "Elections"),
    ("ELECT", "Elections"),
    ("ELXN", "Elections"),
    ("SENATE", "Politics"),
    ("HOUSE", "Politics"),
    ("GOV", "Politics"),
    ("CONGRESS", "Politics"),
    ("POTUS", "Politics"),
    # Crypto
    ("BTC", "Crypto"),
    ("ETH", "Crypto"),
    ("SOL", "Crypto"),
    ("DOGE", "Crypto"),
    ("XRP", "Crypto"),
    ("CRYPTO", "Crypto"),
    # Commodities
    ("WTI", "Commodities"),
    ("BRENT", "Commodities"),
    ("OIL", "Commodities"),
    ("GAS", "Commodities"),
    ("NGAS", "Commodities"),
    ("NATGAS", "Commodities"),
    ("GOLD", "Commodities"),
    ("XAU", "Commodities"),
    ("SILVER", "Commodities"),
    ("CORN", "Commodities"),
    ("WHEAT", "Commodities"),
    ("SOYB", "Commodities"),
    # Economics — macro prints
    ("CPI", "Economics"),
    ("PPI", "Economics"),
    ("GDP", "Economics"),
    ("PCE", "Economics"),
    ("FED", "Economics"),
    ("FOMC", "Economics"),
    ("UNEMP", "Economics"),
    ("JOBS", "Economics"),
    ("NFP", "Economics"),
    ("PAYROLL", "Economics"),
    ("RATEHIKE", "Economics"),
    ("RATECUT", "Economics"),
    # Finance — equity benchmarks
    ("SPX", "Finance"),
    ("SP500", "Finance"),
    ("NDX", "Finance"),
    ("NASDAQ", "Finance"),
    ("DJI", "Finance"),
    ("DOW", "Finance"),
    ("RUT", "Finance"),
    ("VIX", "Finance"),
    ("TNX", "Finance"),
    ("YIELD", "Finance"),
    # Tech & Science
    ("AI", "Tech & Science"),
    ("OPENAI", "Tech & Science"),
    ("NVDA", "Tech & Science"),
    ("SEMI", "Tech & Science"),
    ("CHIP", "Tech & Science"),
    ("SPACE", "Tech & Science"),
    ("NASA", "Tech & Science"),
    ("SPX-AI", "Tech & Science"),
)

# Keyword anchors used for title/rules inference.  Each keyword is a
# whole-word match (word boundaries) — substring matches would be too
# loose.  Keywords are deliberately narrow: a generic word like "market"
# is NOT here (it would over-classify Finance).
#
# Anchor-discipline rule
# ----------------------
# Every keyword here must satisfy two conditions:
#
#   1. It NAMES a category-specific entity / event / instrument
#      (e.g. "bitcoin", "wti crude", "nonfarm payroll", "nvidia").
#   2. It is unambiguous on the seven approved Kalshi categories —
#      a sports / culture / weather / entertainment market with this
#      keyword in its title is essentially impossible.
#
# Generic words ("price", "market", "high", "low", "will", "event")
# are forbidden.  Stock tickers that overlap with non-finance words
# (e.g. ``KEY`` for KeyCorp) are forbidden.
_KEYWORD_ANCHORS: tuple[tuple[str, str], ...] = (
    # ---- Elections -----------------------------------------------------
    ("presidential election", "Elections"),
    ("presidential primary", "Elections"),
    ("election", "Elections"),
    ("electoral college", "Elections"),
    ("primary election", "Elections"),
    ("ballot measure", "Elections"),
    ("senate race", "Elections"),
    ("house race", "Elections"),
    ("governor election", "Elections"),
    ("gubernatorial", "Elections"),
    # ---- Politics ------------------------------------------------------
    ("senator", "Politics"),
    ("congressional", "Politics"),
    ("congress", "Politics"),
    ("senate bill", "Politics"),
    ("house vote", "Politics"),
    ("impeach", "Politics"),
    ("supreme court", "Politics"),
    ("scotus", "Politics"),
    ("white house", "Politics"),
    ("vice president", "Politics"),
    ("governor", "Politics"),
    ("president approval", "Politics"),
    ("government shutdown", "Politics"),
    ("cabinet", "Politics"),
    ("tariff", "Politics"),
    ("sanctions", "Politics"),
    ("nato", "Politics"),
    ("budget bill", "Politics"),
    # ---- Crypto --------------------------------------------------------
    ("bitcoin", "Crypto"),
    ("ethereum", "Crypto"),
    ("solana", "Crypto"),
    ("ether", "Crypto"),
    ("dogecoin", "Crypto"),
    ("cryptocurrency", "Crypto"),
    ("stablecoin", "Crypto"),
    ("tether", "Crypto"),
    ("usdc", "Crypto"),
    ("xrp", "Crypto"),
    # ---- Commodities ---------------------------------------------------
    ("crude oil", "Commodities"),
    ("wti crude", "Commodities"),
    ("brent crude", "Commodities"),
    ("natural gas", "Commodities"),
    ("gas price", "Commodities"),
    ("gold price", "Commodities"),
    ("silver price", "Commodities"),
    ("wheat futures", "Commodities"),
    ("corn futures", "Commodities"),
    ("soybean", "Commodities"),
    ("soybeans", "Commodities"),
    ("copper price", "Commodities"),
    ("opec", "Commodities"),
    # ---- Economics -----------------------------------------------------
    ("inflation rate", "Economics"),
    ("cpi report", "Economics"),
    ("core cpi", "Economics"),
    ("ppi report", "Economics"),
    ("unemployment rate", "Economics"),
    ("nonfarm payroll", "Economics"),
    ("nonfarm payrolls", "Economics"),
    ("jobs report", "Economics"),
    ("recession", "Economics"),
    ("federal reserve", "Economics"),
    ("fed cut", "Economics"),
    ("fed hike", "Economics"),
    ("fomc meeting", "Economics"),
    ("interest rate", "Economics"),
    ("rate cut", "Economics"),
    ("rate hike", "Economics"),
    ("gdp growth", "Economics"),
    ("gdp print", "Economics"),
    ("mortgage rate", "Economics"),
    # ---- Finance -------------------------------------------------------
    ("s&p 500", "Finance"),
    ("nasdaq composite", "Finance"),
    ("dow jones", "Finance"),
    ("stock market", "Finance"),
    ("equity index", "Finance"),
    ("treasury yield", "Finance"),
    ("ipo", "Finance"),
    ("etf", "Finance"),
    ("treasury bond", "Finance"),
    ("market cap", "Finance"),
    # ---- Tech & Science ------------------------------------------------
    ("artificial intelligence", "Tech & Science"),
    ("openai", "Tech & Science"),
    ("gpt model", "Tech & Science"),
    ("semiconductor", "Tech & Science"),
    ("nvidia chip", "Tech & Science"),
    ("nvidia", "Tech & Science"),
    ("starlink", "Tech & Science"),
    ("spacex", "Tech & Science"),
    ("space launch", "Tech & Science"),
    ("rocket launch", "Tech & Science"),
    ("nasa", "Tech & Science"),
    ("satellite launch", "Tech & Science"),
    ("quantum computer", "Tech & Science"),
    ("quantum computing", "Tech & Science"),
)

# Rejection anchors — title keywords that are SO strongly off-allowlist
# (sports, weather, entertainment, etc.) that they should hard-reject the
# market even if a weaker positive anchor might otherwise fire.  This is
# an extra safety belt; the allowlist gate already excludes unknown
# categories, so this list need not be exhaustive.
_REJECTION_KEYWORDS: tuple[str, ...] = (
    # Sports
    "nba", "nfl", "mlb", "nhl", "fifa", "world cup", "premier league",
    "super bowl", "world series", "olympics", "ncaa", "ncaaf", "ncaab",
    "stanley cup", "ufc", "f1 race", "formula 1 race", "indycar",
    "wimbledon", "us open tennis", "french open", "pga tour", "masters golf",
    # Sprint-Kante hardening: esports + multi-game tennis tickers leaked
    # into the CRYPTO tab in the screenshot bug.  Hard-reject any title
    # bearing these tokens regardless of an otherwise-positive anchor.
    "esports", "esport", "e-sports", "multi-game", "multigame",
    "atp tour", "wta tour", "atp finals", "wta finals", "grand slam",
    "tennis match", "tennis player", "tennis open",
    "fortnite", "valorant", "league of legends", "counter-strike",
    "dota", "overwatch", "rocket league", "starcraft",
    "taylor fritz", "hamad medjedovic", "joao fonseca", "peyton stearns",
    "carlos alcaraz", "jannik sinner", "novak djokovic", "iga swiatek",
    # Entertainment / awards / culture
    "oscars", "grammy", "grammys", "emmy", "emmys", "tony award",
    "billboard", "academy award", "box office", "movie release",
    "album release", "tour dates", "concert tour",
    # Celebrity / social-media drama
    "celebrity", "kardashian", "taylor swift", "kanye", "drake feud",
    "tiktok dance", "instagram drama",
    # Weather (non-economic)
    "hurricane", "tornado", "wildfire", "snowstorm", "snowfall", "weather",
    "rainfall total", "blizzard",
    # Lifestyle / gambling-ish entertainment
    "reality tv", "bachelor finale", "survivor finale",
)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _ticker_prefix_category(ticker: Any) -> tuple[str | None, str | None]:
    """Return (canonical_category, matched_prefix) or (None, None)."""
    if not ticker:
        return None, None
    raw = str(ticker).strip().upper()
    if not raw:
        return None, None
    # Tickers are typically prefix-delimited by ``-`` or ``_`` (e.g.
    # ``BTCMAY-2026``, ``FED-CUT-JUN-2026``, ``KXPRES-2028``).  Examine
    # the first 2-3 alphanumeric segments and try the longest prefix
    # first so ``PRES-2028`` is preferred over a bare ``P`` lookup.
    segments = re.split(r"[-_]+", raw)
    if not segments or not segments[0]:
        return None, None
    head = segments[0]
    # Probe progressively-shorter prefixes of the first segment so
    # "BTCMAY" still matches the BTC prefix and "KXPRES" still matches
    # the PRES prefix (Kalshi uses KX-prefixed series for many events).
    candidates: list[str] = []
    for length in range(len(head), 1, -1):
        candidates.append(head[:length])
    # Also try with leading ``KX`` / ``X`` removed (common Kalshi prefix).
    if head.startswith("KX") and len(head) > 2:
        for length in range(len(head) - 2, 1, -1):
            candidates.append(head[2 : 2 + length])
    for cand in candidates:
        for prefix, category in _TICKER_PREFIX_MAP:
            if cand == prefix:
                return category, prefix
    # If no first-segment match, try the leading ``head`` token literally.
    for prefix, category in _TICKER_PREFIX_MAP:
        if head == prefix:
            return category, prefix
    return None, None


def _keyword_anchor_category(text: str) -> tuple[str | None, str | None]:
    """Return (canonical_category, matched_keyword) or (None, None).

    Matches are whole-token: the keyword must appear as a contiguous
    substring framed by either start-of-string, end-of-string, whitespace,
    or punctuation.  This avoids ``"ai"`` matching ``"chair"``.
    """
    if not text:
        return None, None
    haystack = f" {text} "
    for keyword, category in _KEYWORD_ANCHORS:
        needle = f" {keyword} "
        if needle in haystack:
            return category, keyword
        # Allow punctuation-bounded matches as well (e.g. "BTC,").
        for pattern in (f" {keyword},", f" {keyword}.", f" {keyword}?", f" {keyword}!"):
            if pattern in haystack:
                return category, keyword
    return None, None


def _matches_rejection_anchor(text: str) -> str | None:
    if not text:
        return None
    haystack = f" {text} "
    for keyword in _REJECTION_KEYWORDS:
        if f" {keyword} " in haystack:
            return keyword
    return None


def infer_kalshi_category(
    raw_market: dict[str, Any],
    event_lookup: dict[str, Any] | None = None,
) -> tuple[str | None, str]:
    """Evidence-based Kalshi category inference.

    Layered enrichment for live Kalshi markets that arrive without a
    populated ``category`` field.  Each layer is conservative: heuristics
    only ever map to the canonical allowlist, and a missing layer falls
    through to the next rather than guessing.

    Parameters
    ----------
    raw_market:
        Raw Kalshi market dict (as returned by ``GET /markets``).
    event_lookup:
        Optional ``{event_ticker: event_payload}`` map of pre-fetched
        ``/events`` rows — used to recover the category when a market
        only carries an ``event_ticker`` back-reference.

    Returns
    -------
    ``(canonical_category | None, reason)``.

    ``canonical_category`` is one of :data:`CANONICAL_CATEGORIES` or
    ``None`` when no layer matches.  ``reason`` is a short
    machine-readable tag (e.g. ``"explicit_category"``,
    ``"event_payload_category"``, ``"ticker_prefix:BTC"``,
    ``"keyword_anchor:federal reserve"``, ``"missing_category"``).

    Safety
    ------
    This function NEVER weakens the allowlist.  It only emits a value
    when a positive rule fires; otherwise it returns ``(None, reason)``.
    Rejection anchors (sports/weather/entertainment keywords in the
    title) hard-reject the market even if a weaker positive anchor would
    otherwise fire.
    """
    if not isinstance(raw_market, dict):
        return None, "invalid_input"

    # An explicit category in the rejected list (Sports/Climate/etc.) is a
    # *stronger* signal than any title heuristic: respect it and never let
    # downstream inference override the upstream label.
    raw_explicit_key = _normalize_category_key(raw_market.get("category"))
    if raw_explicit_key and raw_explicit_key in EXPLICIT_REJECTED_CATEGORIES:
        return None, f"explicit_rejected_category:{raw_explicit_key}"

    title = _normalize_text(raw_market.get("title") or raw_market.get("question"))
    subtitle = _normalize_text(raw_market.get("subtitle") or raw_market.get("event_title"))
    description = _normalize_text(raw_market.get("description") or raw_market.get("event_description"))
    rules = _normalize_text(
        raw_market.get("rules")
        or raw_market.get("rules_primary")
        or raw_market.get("resolution_criteria")
    )
    combined_text = " ".join(t for t in (title, subtitle, description, rules) if t)

    # Hard-reject before any positive inference if a rejection anchor fires.
    rejection_hit = _matches_rejection_anchor(combined_text)
    if rejection_hit:
        return None, f"rejected_keyword:{rejection_hit}"

    # 1. Explicit category field.
    cls = classify_kalshi_category(raw_market.get("category"))
    if cls["allowed"]:
        return cls["display_category"], "explicit_category"

    # 2. Event payload category (joined via /events).
    if event_lookup:
        ev_ticker = str(raw_market.get("event_ticker") or "").strip()
        if ev_ticker and ev_ticker in event_lookup:
            event = event_lookup[ev_ticker]
            if isinstance(event, dict):
                ev_cls = classify_kalshi_category(event.get("category"))
                if ev_cls["allowed"]:
                    return ev_cls["display_category"], "event_payload_category"
                # Sub-title / title text on the event row counts as
                # description-grade signal for the keyword pass below.
                if not combined_text:
                    combined_text = _normalize_text(
                        event.get("title") or event.get("sub_title")
                    )

    # 3. Tag exact-match.
    raw_tags = raw_market.get("tags") or []
    if isinstance(raw_tags, list):
        tags = [
            (t.get("label") if isinstance(t, dict) else str(t))
            for t in raw_tags
            if t
        ]
    else:
        tags = []
    for tag in tags:
        tag_key = _normalize_category_key(tag)
        if tag_key in KALSHI_CATEGORY_MAP:
            return KALSHI_CATEGORY_MAP[tag_key], f"tag_match:{tag_key}"

    # 4. Series/event/ticker prefix exact-match.
    for source_field in ("ticker", "market_ticker", "series_ticker", "event_ticker"):
        cat, prefix = _ticker_prefix_category(raw_market.get(source_field))
        if cat is not None:
            return cat, f"ticker_prefix:{prefix}"

    # 5. Title/rules/description keyword anchor.
    cat, keyword = _keyword_anchor_category(combined_text)
    if cat is not None:
        return cat, f"keyword_anchor:{keyword}"

    # 6. Give up — explicit reason so the diagnostics report can show it.
    if not combined_text and not tags:
        return None, "missing_category"
    return None, "no_confident_match"


# ---------------------------------------------------------------------------
# Title normalization
# ---------------------------------------------------------------------------
#
# Live Kalshi multi-outcome events sometimes return ``title`` as a raw
# comma-joined list of ``yes <outcome>`` strings (the screenshot bug:
# ``"yes Taylor Fritz, yes Hamad Medjedovic, ..."``).  We never let such
# a raw outcome dump become the primary display title.  Instead we
# detect the leak, preserve the outcomes separately, and fall through to
# a higher-quality source — official event_title, market_title, title,
# question, subtitle, short_name, ticker-derived label.

TITLE_OFFICIAL_TITLE = "official_title"
TITLE_OFFICIAL_QUESTION = "official_question"
TITLE_OFFICIAL_SUBTITLE = "official_subtitle"
TITLE_CLEANED_OUTCOMES = "cleaned_outcomes_fallback"
TITLE_TICKER_FALLBACK = "ticker_fallback"
TITLE_UNUSABLE = "unusable"

_TITLE_MAX_LEN = 240
_YES_LEAK_PATTERN = re.compile(r"(?i)(^|[\s,;|])yes\s+[A-Za-z][^,;|]{1,80}(,\s*yes\s+[A-Za-z])")


def _looks_like_yes_outcome_leak(text: str) -> bool:
    if not text:
        return False
    if _YES_LEAK_PATTERN.search(text):
        return True
    # Count comma-separated "yes <something>" segments — three or more
    # is a multi-outcome dump masquerading as a title.
    chunks = [c.strip().lower() for c in text.split(",") if c.strip()]
    yes_chunks = sum(1 for c in chunks if c.startswith("yes "))
    return yes_chunks >= 2


def _strip_yes_prefix(text: str) -> str:
    s = text.strip()
    low = s.lower()
    if low.startswith("yes "):
        return s[4:].strip()
    if low.startswith("no "):
        return s[3:].strip()
    return s


def _outcomes_from(raw: dict[str, Any]) -> list[str]:
    candidates: list[Any] = []
    for key in ("outcomes", "response_options", "yes_no_outcomes", "legs", "options", "contracts"):
        value = raw.get(key)
        if value:
            candidates.append(value)
    out: list[str] = []
    for v in candidates:
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",") if p.strip()]
            out.extend(parts)
        elif isinstance(v, (list, tuple, set)):
            for item in v:
                if isinstance(item, str) and item.strip():
                    out.append(item.strip())
                elif isinstance(item, dict):
                    label = item.get("label") or item.get("name") or item.get("title")
                    if isinstance(label, str) and label.strip():
                        out.append(label.strip())
    # De-dupe order-preserving.
    seen: set[str] = set()
    deduped: list[str] = []
    for o in out:
        key = o.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(o)
    return deduped


def _cleaned_ticker_label(ticker: Any) -> str:
    if not ticker:
        return ""
    raw = str(ticker).strip()
    if not raw:
        return ""
    cleaned = re.sub(r"[-_]+", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:80]


def normalize_kalshi_title(raw: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic title decision for a raw Kalshi market dict.

    Returns a ``TitleDecision`` mapping::

        {
          "primary_title":   str,        # what the UI card shows
          "display_title":   str,        # alias of primary_title
          "raw_title":       str,        # original payload title (unchanged)
          "title_source":    str,        # which field won the priority race
          "title_quality":   str,        # official_title / cleaned_outcomes_fallback / ...
          "title_warnings":  list[str],  # e.g. ["yes_outcome_leak_detected"]
          "outcomes":        list[str],  # preserved separately, NEVER joined into the title
        }

    Pure function.  Never raises.  Never weakens the seven-category gate.
    """
    if not isinstance(raw, dict):
        return {
            "primary_title": "",
            "display_title": "",
            "raw_title": "",
            "title_source": "",
            "title_quality": TITLE_UNUSABLE,
            "title_warnings": ["invalid_input"],
            "outcomes": [],
        }

    raw_title = str(raw.get("title") or "").strip()
    warnings: list[str] = []
    outcomes = _outcomes_from(raw)

    # Priority chain, skipping anything that looks like a "yes X, yes Y" leak.
    priority: list[tuple[str, Any, str]] = [
        (TITLE_OFFICIAL_TITLE, raw.get("event_title"), "event_title"),
        (TITLE_OFFICIAL_TITLE, raw.get("market_title"), "market_title"),
        (TITLE_OFFICIAL_TITLE, raw.get("title"), "title"),
        (TITLE_OFFICIAL_QUESTION, raw.get("question"), "question"),
        (TITLE_OFFICIAL_SUBTITLE, raw.get("subtitle"), "subtitle"),
        (TITLE_OFFICIAL_TITLE, raw.get("short_name"), "short_name"),
        (TITLE_OFFICIAL_TITLE, raw.get("name"), "name"),
    ]
    for quality, value, source_field in priority:
        if not value:
            continue
        candidate = str(value).strip()
        if not candidate:
            continue
        if _looks_like_yes_outcome_leak(candidate):
            warnings.append(f"yes_outcome_leak_detected:{source_field}")
            # Treat as outcome leak: pull individual yes-options into the
            # outcomes list and skip to the next priority entry.
            for chunk in candidate.split(","):
                option = _strip_yes_prefix(chunk)
                if option and option.lower() not in {o.lower() for o in outcomes}:
                    outcomes.append(option)
            continue
        if len(candidate) > _TITLE_MAX_LEN:
            candidate = candidate[: _TITLE_MAX_LEN - 1].rstrip() + "…"
        return {
            "primary_title": candidate,
            "display_title": candidate,
            "raw_title": raw_title,
            "title_source": source_field,
            "title_quality": quality,
            "title_warnings": warnings,
            "outcomes": outcomes,
        }

    # No usable field — try a cleaned outcomes fallback (only if there
    # are concrete outcomes to summarise).
    if outcomes:
        joined = ", ".join(outcomes[:6])
        candidate = f"Kalshi multi-outcome market: {joined}"
        if len(candidate) > _TITLE_MAX_LEN:
            candidate = candidate[: _TITLE_MAX_LEN - 1].rstrip() + "…"
        return {
            "primary_title": candidate,
            "display_title": candidate,
            "raw_title": raw_title,
            "title_source": "outcomes",
            "title_quality": TITLE_CLEANED_OUTCOMES,
            "title_warnings": warnings,
            "outcomes": outcomes,
        }

    # Final fallback: derive from ticker so the card never renders blank.
    ticker_label = _cleaned_ticker_label(
        raw.get("ticker") or raw.get("market_ticker") or raw.get("id")
    )
    if ticker_label:
        return {
            "primary_title": ticker_label,
            "display_title": ticker_label,
            "raw_title": raw_title,
            "title_source": "ticker",
            "title_quality": TITLE_TICKER_FALLBACK,
            "title_warnings": warnings + ["no_official_title"],
            "outcomes": outcomes,
        }

    return {
        "primary_title": "",
        "display_title": "",
        "raw_title": raw_title,
        "title_source": "",
        "title_quality": TITLE_UNUSABLE,
        "title_warnings": warnings + ["no_official_title", "no_ticker_fallback"],
        "outcomes": outcomes,
    }


# ---------------------------------------------------------------------------
# Source-freshness vs market-activity semantics
# ---------------------------------------------------------------------------
#
# The screenshot bug collapsed "source last-fetch age" and "market still
# open/closed" into one vague STALE_ACTIVE chip.  These are independent
# axes and must be computed independently.

SOURCE_LIVE_VERIFIED = "LIVE_VERIFIED"
SOURCE_STALE = "SOURCE_STALE"
SOURCE_UNVERIFIED = "UNVERIFIED"
SOURCE_ERROR = "SOURCE_ERROR"

MARKET_OPEN = "MARKET_OPEN"
MARKET_CLOSED = "MARKET_CLOSED"
MARKET_EXPIRED = "MARKET_EXPIRED"
MARKET_UNKNOWN = "MARKET_UNKNOWN"

UI_BADGE_LIVE_OPEN = "LIVE_MARKET_OPEN"
UI_BADGE_STALE_OPEN = "SOURCE_STALE_MARKET_OPEN"
UI_BADGE_UNVERIFIED_OPEN = "UNVERIFIED_MARKET_OPEN"
UI_BADGE_ERROR_OPEN = "SOURCE_ERROR_MARKET_OPEN"
UI_BADGE_LIVE_CLOSED = "LIVE_MARKET_CLOSED"
UI_BADGE_STALE_CLOSED = "SOURCE_STALE_MARKET_CLOSED"
UI_BADGE_MARKET_EXPIRED = "MARKET_EXPIRED"
UI_BADGE_UNKNOWN = "UNKNOWN"

DEFAULT_SOURCE_FRESHNESS_TTL_SECONDS = 6 * 60 * 60  # 6h, matches scheduler cadence
MARKET_EXPIRED_GRACE_SECONDS = 7 * 24 * 60 * 60     # 7 days past close → EXPIRED


def _parse_utc(ts: Any):
    """Parse an ISO-8601 UTC timestamp.  Returns ``None`` on failure."""
    from datetime import datetime, timezone

    if ts is None:
        return None
    if hasattr(ts, "tzinfo"):
        # Already a datetime.
        dt = ts
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    text = str(ts).strip()
    if not text:
        return None
    # Tolerate trailing Z.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_source_freshness(
    last_successful_fetch_at_utc: Any,
    now_utc: Any,
    ttl_seconds: int = DEFAULT_SOURCE_FRESHNESS_TTL_SECONDS,
    *,
    error_state: bool = False,
) -> str:
    """Classify how fresh the source's last successful fetch is.

    Returns one of LIVE_VERIFIED / SOURCE_STALE / UNVERIFIED / SOURCE_ERROR.
    ``error_state`` should be True only when the last refresh attempt
    raised or returned a non-OK upstream status — UNVERIFIED is the
    fallback for "no fetch on record yet".
    """
    if error_state:
        return SOURCE_ERROR
    last = _parse_utc(last_successful_fetch_at_utc)
    now = _parse_utc(now_utc)
    if last is None or now is None:
        return SOURCE_UNVERIFIED
    age = (now - last).total_seconds()
    if age < 0:
        # Clock skew — treat as fresh to avoid spurious staleness.
        return SOURCE_LIVE_VERIFIED
    if age > int(ttl_seconds):
        return SOURCE_STALE
    return SOURCE_LIVE_VERIFIED


def compute_market_activity(close_time_utc: Any, now_utc: Any) -> str:
    """Classify whether the underlying market is open / closed / expired."""
    close = _parse_utc(close_time_utc)
    now = _parse_utc(now_utc)
    if close is None or now is None:
        return MARKET_UNKNOWN
    if close > now:
        return MARKET_OPEN
    age = (now - close).total_seconds()
    if age > MARKET_EXPIRED_GRACE_SECONDS:
        return MARKET_EXPIRED
    return MARKET_CLOSED


def compute_kalshi_ui_badge(
    source_freshness_status: str,
    market_activity_status: str,
) -> str:
    """Combine the two axes into a single explicit UI badge."""
    if market_activity_status == MARKET_EXPIRED:
        return UI_BADGE_MARKET_EXPIRED
    if market_activity_status == MARKET_OPEN:
        if source_freshness_status == SOURCE_LIVE_VERIFIED:
            return UI_BADGE_LIVE_OPEN
        if source_freshness_status == SOURCE_STALE:
            return UI_BADGE_STALE_OPEN
        if source_freshness_status == SOURCE_UNVERIFIED:
            return UI_BADGE_UNVERIFIED_OPEN
        if source_freshness_status == SOURCE_ERROR:
            return UI_BADGE_ERROR_OPEN
    if market_activity_status == MARKET_CLOSED:
        if source_freshness_status == SOURCE_LIVE_VERIFIED:
            return UI_BADGE_LIVE_CLOSED
        if source_freshness_status == SOURCE_STALE:
            return UI_BADGE_STALE_CLOSED
    return UI_BADGE_UNKNOWN


# ---------------------------------------------------------------------------
# Composite semantic-text builder
# ---------------------------------------------------------------------------


def _clean_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        return []
    cleaned: list[str] = []
    for item in items:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def build_kalshi_semantic_text(market: dict[str, Any]) -> str:
    """Build composite semantic text suitable for future cross-venue
    semantic-disagreement matching against Polymarket markets.

    The composite intentionally includes title, description, rules /
    resolution criteria, outcomes, category, tags, and an event-window
    (close date) when available.  Pure-title embeddings miss obvious
    semantic equivalents like::

        Kalshi:     "How high will Bitcoin get in May?"
        Polymarket: "What price will Bitcoin hit in May?"

    Each section is emitted only when its source field is present.  Empty
    sections are omitted rather than rendered as ``Title: <empty>``.
    """
    if not isinstance(market, dict):
        return ""

    title = str(market.get("title") or market.get("question") or "").strip()
    description = str(market.get("description") or market.get("subtitle") or "").strip()
    rules = str(
        market.get("rules")
        or market.get("resolution_criteria")
        or market.get("rules_primary")
        or ""
    ).strip()
    outcomes = _clean_list(
        market.get("outcomes")
        or market.get("response_options")
        or market.get("yes_no_outcomes")
    )
    category = str(market.get("category") or "").strip()
    tags = _clean_list(market.get("tags") or market.get("asset_tags") or market.get("event_tags"))
    close = str(
        market.get("close_time_utc")
        or market.get("close_date")
        or market.get("event_window")
        or market.get("close_time")
        or ""
    ).strip()

    sections: list[str] = []
    if title:
        sections.append(f"Title: {title}")
    if description:
        sections.append(f"Description: {description}")
    if rules:
        sections.append(f"Rules: {rules}")
    if outcomes:
        sections.append(f"Outcomes: {', '.join(outcomes)}")
    if category:
        sections.append(f"Category: {category}")
    if tags:
        sections.append(f"Tags: {', '.join(tags)}")
    if close:
        sections.append(f"Close: {close}")
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Stable event id
# ---------------------------------------------------------------------------


def stable_kalshi_event_id(source_market_id: str) -> str:
    """Deterministic ``signal_events.event_id`` for a Kalshi market."""
    raw = f"{CANONICAL_SOURCE}:{source_market_id}".encode()
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return f"{CANONICAL_SOURCE}_{digest}"


# ---------------------------------------------------------------------------
# Safety stamps
# ---------------------------------------------------------------------------


def kalshi_safety_stamps() -> dict[str, Any]:
    """Return the canonical safety field set.  Stored on every Kalshi row.

    Returning a fresh dict each call avoids accidental cross-call mutation.
    """
    return {
        "advisory_status": ADVISORY_STATUS,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "execution_permission": EXECUTION_PERMISSION_ADVISORY,
        "human_review_required": HUMAN_REVIEW_REQUIRED,
        "advisory_only": True,
        "broker_api_called": BROKER_API_CALLED,
        "ai_execution_count": AI_EXECUTION_COUNT,
    }


# ---------------------------------------------------------------------------
# Main normalizer
# ---------------------------------------------------------------------------


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def build_kalshi_quarantine_record(
    raw: dict[str, Any],
    *,
    decision: dict[str, Any] | None = None,
    fetched_at_utc: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an operator-facing quarantine record for an out-of-scope market.

    Used by the loader/runner to write to ``runtime/release/kalshi_quarantine.jsonl``.
    Never persisted into ``signal_events``.  Carries every safety stamp.
    """
    raw_dict = raw if isinstance(raw, dict) else {}
    title = str(raw_dict.get("title") or raw_dict.get("question") or "").strip()
    ticker = str(
        raw_dict.get("ticker")
        or raw_dict.get("market_ticker")
        or raw_dict.get("id")
        or ""
    ).strip()
    record: dict[str, Any] = {
        "source_name": CANONICAL_SOURCE,
        "ticker": ticker,
        "event_ticker": str(raw_dict.get("event_ticker") or "").strip(),
        "title": title,
        "subtitle": str(raw_dict.get("subtitle") or "").strip(),
        "raw_category": str(raw_dict.get("category") or "").strip(),
        "raw_subcategory": str(raw_dict.get("subcategory") or "").strip(),
        "tags": list(raw_dict.get("tags") or []),
        "category_decision": decision or {},
        "mvp_category": None,
        "category_allowed": False,
        "visible_in_kalshi_feed": False,
        "quarantine_reason": (decision or {}).get("quarantine_reason", ""),
        "fetched_at_utc": fetched_at_utc,
    }
    if extra:
        for k, v in extra.items():
            if k not in record:
                record[k] = v
    record.update(kalshi_safety_stamps())
    return record


def normalize_kalshi_market(
    raw: dict[str, Any],
    *,
    fetched_at_utc: str | None = None,
    source_hint: str | None = None,
    event_lookup: dict[str, Any] | None = None,
    now_utc: str | None = None,
    source_freshness_status: str | None = None,
    last_successful_fetch_at_utc: str | None = None,
    source_freshness_ttl_seconds: int = DEFAULT_SOURCE_FRESHNESS_TTL_SECONDS,
) -> dict[str, Any] | None:
    """Normalize a raw Kalshi market dict into the canonical signal shape.

    Returns ``None`` when the market is rejected by the category allowlist
    or when required fields are missing.  Rejected markets MUST NOT enter
    ``signal_events`` persistence.

    The returned dict is suitable to pass to ``persistence.insert_signal_event``
    as ``raw_payload``.  It carries every safety stamp.

    ``event_lookup`` is an optional ``{event_ticker: event_dict}`` map used
    by :func:`infer_kalshi_category` to recover the category for live
    markets that ship without one — purely additive, never weakens the
    allowlist.
    """
    if not isinstance(raw, dict):
        return None

    # Source-name guard.  Accepts ``raw["source"]`` / ``raw["source_name"]``
    # / ``raw["sourceLabel"]`` / explicit ``source_hint`` so adapters with
    # different schemas all normalise to "kalshi".
    source_candidate = (
        source_hint
        or raw.get("source")
        or raw.get("source_name")
        or raw.get("sourceLabel")
        or CANONICAL_SOURCE  # caller-supplied Kalshi context
    )
    if not is_kalshi_source(source_candidate):
        return None

    # First try the explicit-category path so test fixtures and adapters
    # that ship a canonical category keep behaving as before.
    classification = classify_kalshi_category(
        raw.get("category"),
        tags=raw.get("tags") or raw.get("asset_tags") or raw.get("event_tags"),
    )
    inferred_category: str | None = None
    inference_reason = ""
    if classification["allowed"]:
        display_category = classification["display_category"]
        raw_category = classification["raw_category"]
        category_source = "explicit_category"
        category_reason = classification["reason"]
    else:
        # Evidence-based inference for live markets without a populated
        # category field (or with one outside the allowlist *that the
        # inference layer can rescue via stronger metadata*).
        inferred_category, inference_reason = infer_kalshi_category(
            raw, event_lookup=event_lookup
        )
        if inferred_category is None:
            return None
        display_category = inferred_category
        raw_category = _normalize_category_key(raw.get("category"))
        category_source = "inferred"
        category_reason = inference_reason
        classification = {
            "allowed": True,
            "display_category": display_category,
            "raw_category": raw_category,
            "reason": inference_reason,
        }

    source_market_id = str(
        raw.get("source_market_id")
        or raw.get("ticker")
        or raw.get("market_ticker")
        or raw.get("id")
        or ""
    ).strip()
    if not source_market_id:
        return None

    title_decision = normalize_kalshi_title(raw)
    title = title_decision["primary_title"]
    if not title:
        return None

    description = str(raw.get("description") or raw.get("subtitle") or "").strip() or None
    rules = str(
        raw.get("rules")
        or raw.get("resolution_criteria")
        or raw.get("rules_primary")
        or ""
    ).strip() or None
    market_url = str(raw.get("market_url") or raw.get("url") or "").strip() or None
    close_time_utc = str(
        raw.get("close_time_utc")
        or raw.get("close_date")
        or raw.get("close_time")
        or ""
    ).strip() or None

    yes_price = _coerce_float(raw.get("yes_price") or raw.get("yes_ask") or raw.get("last_price"))
    no_price = _coerce_float(raw.get("no_price") or raw.get("no_ask"))
    implied = _coerce_float(raw.get("implied_probability"))
    if implied is None and yes_price is not None:
        # Kalshi YES prices are 0-100 cents; convert to 0-1 probability.
        if 0.0 <= yes_price <= 1.0:
            implied = yes_price
        elif 0.0 <= yes_price <= 100.0:
            implied = yes_price / 100.0

    volume = _coerce_float(raw.get("volume"))
    liquidity = _coerce_float(raw.get("liquidity"))
    open_interest = _coerce_int(raw.get("open_interest"))

    asset_tags = _clean_list(raw.get("asset_tags") or raw.get("tags"))
    event_tags = _clean_list(raw.get("event_tags"))

    semantic_text = build_kalshi_semantic_text(
        {
            **raw,
            "title": title,
            "description": description,
            "rules": rules,
            "category": classification["display_category"],
            "tags": asset_tags or raw.get("tags"),
            "close_time_utc": close_time_utc,
        }
    )

    # Round-trip display label back to canonical slug for mvp_category.
    try:
        from scripts.kalshi_category_governance import DISPLAY_TO_SLUG  # local
    except ModuleNotFoundError:  # pragma: no cover
        from kalshi_category_governance import DISPLAY_TO_SLUG  # type: ignore[no-redef]
    mvp_category = DISPLAY_TO_SLUG.get(classification["display_category"])

    # Source freshness + market activity decomposition.
    now_ref = now_utc or fetched_at_utc
    fresh = source_freshness_status or compute_source_freshness(
        last_successful_fetch_at_utc or fetched_at_utc,
        now_ref,
        source_freshness_ttl_seconds,
    )
    activity = compute_market_activity(close_time_utc, now_ref)
    ui_badge = compute_kalshi_ui_badge(fresh, activity)

    payload: dict[str, Any] = {
        "event_id": stable_kalshi_event_id(source_market_id),
        "source": CANONICAL_SOURCE,
        "source_name": CANONICAL_SOURCE,
        "source_label": CANONICAL_SOURCE_LABEL,
        "source_market_id": source_market_id,
        "title": title,
        "primary_title": title_decision["primary_title"],
        "display_title": title_decision["display_title"],
        "raw_title": title_decision["raw_title"],
        "title_source": title_decision["title_source"],
        "title_quality": title_decision["title_quality"],
        "title_warnings": title_decision["title_warnings"],
        "outcomes": title_decision["outcomes"],
        "description": description,
        "rules": rules,
        "category": classification["display_category"],
        "display_category": classification["display_category"],
        "mvp_category": mvp_category,
        "category_raw": classification["raw_category"],
        "category_source": category_source,
        "category_reason": category_reason,
        "category_allowed": True,
        "quarantine_reason": "",
        "visible_in_kalshi_feed": True,
        "market_url": market_url,
        "implied_probability": implied,
        "yes_price": yes_price,
        "no_price": no_price,
        "volume": volume,
        "liquidity": liquidity,
        "open_interest": open_interest,
        "close_time_utc": close_time_utc,
        "fetched_at_utc": fetched_at_utc,
        "asset_tags": asset_tags,
        "event_tags": event_tags,
        "semantic_text": semantic_text,
        # Source freshness vs market activity — split intentionally so the
        # UI can render two badges instead of one misleading STALE_ACTIVE.
        "source_freshness_status": fresh,
        "market_activity_status": activity,
        "ui_badge_status": ui_badge,
        "source_freshness_ttl_seconds": int(source_freshness_ttl_seconds),
        "last_successful_fetch_at_utc": last_successful_fetch_at_utc,
        # Future cross-venue matching label slot.  Left empty until the
        # disagreement layer lands; declared here so the schema is stable.
        "cross_venue_match_label": None,
    }
    payload.update(kalshi_safety_stamps())
    return payload


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "EXECUTION_PERMISSION_ADVISORY",
    "AI_EXECUTION_COUNT",
    "HUMAN_REVIEW_REQUIRED",
    "BROKER_API_CALLED",
    "CANONICAL_SOURCE",
    "CANONICAL_SOURCE_LABEL",
    "CANONICAL_CATEGORIES",
    "KALSHI_CATEGORY_MAP",
    "EXPLICIT_REJECTED_CATEGORIES",
    "TITLE_OFFICIAL_TITLE",
    "TITLE_OFFICIAL_QUESTION",
    "TITLE_OFFICIAL_SUBTITLE",
    "TITLE_CLEANED_OUTCOMES",
    "TITLE_TICKER_FALLBACK",
    "TITLE_UNUSABLE",
    "SOURCE_LIVE_VERIFIED",
    "SOURCE_STALE",
    "SOURCE_UNVERIFIED",
    "SOURCE_ERROR",
    "MARKET_OPEN",
    "MARKET_CLOSED",
    "MARKET_EXPIRED",
    "MARKET_UNKNOWN",
    "UI_BADGE_LIVE_OPEN",
    "UI_BADGE_STALE_OPEN",
    "UI_BADGE_UNVERIFIED_OPEN",
    "UI_BADGE_ERROR_OPEN",
    "UI_BADGE_LIVE_CLOSED",
    "UI_BADGE_STALE_CLOSED",
    "UI_BADGE_MARKET_EXPIRED",
    "UI_BADGE_UNKNOWN",
    "DEFAULT_SOURCE_FRESHNESS_TTL_SECONDS",
    "MARKET_EXPIRED_GRACE_SECONDS",
    "normalize_kalshi_title",
    "compute_source_freshness",
    "compute_market_activity",
    "compute_kalshi_ui_badge",
    "build_kalshi_quarantine_record",
    "normalize_kalshi_source_name",
    "is_kalshi_source",
    "classify_kalshi_category",
    "infer_kalshi_category",
    "build_kalshi_semantic_text",
    "stable_kalshi_event_id",
    "kalshi_safety_stamps",
    "normalize_kalshi_market",
]
