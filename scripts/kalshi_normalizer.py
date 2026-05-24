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
        "world", "weather",
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


def normalize_kalshi_market(
    raw: dict[str, Any],
    *,
    fetched_at_utc: str | None = None,
    source_hint: str | None = None,
) -> dict[str, Any] | None:
    """Normalize a raw Kalshi market dict into the canonical signal shape.

    Returns ``None`` when the market is rejected by the category allowlist
    or when required fields are missing.  Rejected markets MUST NOT enter
    ``signal_events`` persistence.

    The returned dict is suitable to pass to ``persistence.insert_signal_event``
    as ``raw_payload``.  It carries every safety stamp.
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

    classification = classify_kalshi_category(
        raw.get("category"),
        tags=raw.get("tags") or raw.get("asset_tags") or raw.get("event_tags"),
    )
    if not classification["allowed"]:
        return None

    source_market_id = str(
        raw.get("source_market_id")
        or raw.get("ticker")
        or raw.get("market_ticker")
        or raw.get("id")
        or ""
    ).strip()
    if not source_market_id:
        return None

    title = str(raw.get("title") or raw.get("question") or raw.get("name") or "").strip()
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

    payload: dict[str, Any] = {
        "event_id": stable_kalshi_event_id(source_market_id),
        "source": CANONICAL_SOURCE,
        "source_name": CANONICAL_SOURCE,
        "source_label": CANONICAL_SOURCE_LABEL,
        "source_market_id": source_market_id,
        "title": title,
        "description": description,
        "rules": rules,
        "category": classification["display_category"],
        "category_raw": classification["raw_category"],
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
    "normalize_kalshi_source_name",
    "is_kalshi_source",
    "classify_kalshi_category",
    "build_kalshi_semantic_text",
    "stable_kalshi_event_id",
    "kalshi_safety_stamps",
    "normalize_kalshi_market",
]
