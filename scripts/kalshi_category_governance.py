"""
Canonical Kalshi category governance — advisory-only, read-only.

Single source of truth for ``normalize_kalshi_category()``: a strict
allowlist enforcing the seven Kalshi tabs the MVP surfaces.

Allowed categories
------------------
- elections
- politics
- crypto
- commodities
- economics
- finance
- tech_science

Anything else (sports, esports, gaming, culture, climate, mentions,
entertainment, trending, weather, multi-game, ...) is quarantined and
must not enter the canonical Kalshi feed.

This module wraps the existing primitives in ``scripts.kalshi_normalizer``
and adds a stable ``CategoryDecision`` mapping so downstream callers (the
loader, the runner, the quarantine writer, and the frontend payload
contract) share one decision shape.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

try:
    from scripts.kalshi_normalizer import (
        CANONICAL_CATEGORIES,
        EXPLICIT_REJECTED_CATEGORIES,
        KALSHI_CATEGORY_MAP,
        classify_kalshi_category,
        infer_kalshi_category,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from kalshi_normalizer import (  # type: ignore[no-redef]
        CANONICAL_CATEGORIES,
        EXPLICIT_REJECTED_CATEGORIES,
        KALSHI_CATEGORY_MAP,
        classify_kalshi_category,
        infer_kalshi_category,
    )


# Canonical slugs (snake_case keys we use across persistence + the
# frontend payload contract).  Display labels are the human-readable
# strings the UI tab labels match against.
ALLOWED_KALSHI_CATEGORIES: frozenset[str] = frozenset(
    {
        "elections",
        "politics",
        "crypto",
        "commodities",
        "economics",
        "finance",
        "tech_science",
    }
)

DISPLAY_LABELS: dict[str, str] = {
    "elections": "Elections",
    "politics": "Politics",
    "crypto": "Crypto",
    "commodities": "Commodities",
    "economics": "Economics",
    "finance": "Finance",
    "tech_science": "Tech & Science",
}

# Reverse map: display label → slug.  Lets us round-trip from the
# existing normalizer (which already returns display labels) back to the
# canonical slug we persist on the payload.
DISPLAY_TO_SLUG: dict[str, str] = {label: slug for slug, label in DISPLAY_LABELS.items()}


# Source-of-decision enum.  Persisted on every record so the audit story
# is explicit about whether a row landed via official metadata, route
# context, ticker pattern, or keyword inference.
CATEGORY_SOURCE_OFFICIAL = "official_metadata"
CATEGORY_SOURCE_ROUTE = "source_route"
CATEGORY_SOURCE_TICKER = "ticker_fallback"
CATEGORY_SOURCE_KEYWORD = "keyword_fallback"
CATEGORY_SOURCE_UNKNOWN = "unknown"


# Quarantine reasons (machine-readable; surface verbatim in the
# audit jsonl).  Add new ones only with a corresponding test.
QUARANTINE_NOT_IN_ALLOWLIST = "category_not_in_allowlist"
QUARANTINE_EXPLICIT_REJECTED = "category_explicitly_rejected"
QUARANTINE_TICKER_REJECTED = "ticker_pattern_rejected"
QUARANTINE_NO_USABLE_METADATA = "no_usable_category_metadata"


# ---------------------------------------------------------------------------
# Ticker-pattern rejection set
# ---------------------------------------------------------------------------
# Whole-prefix or substring patterns that should hard-reject before any
# inference layer runs.  Each entry maps to a quarantine reason.
#
# KXMVESPORTS is the Kalshi esports multi-game series — it must never
# enter the main feed regardless of inferred title metadata.  The map
# below uses uppercase substring matching against the ticker.
_TICKER_REJECTION_SUBSTRINGS: tuple[str, ...] = (
    "ESPORTS",
    "MVESPORTS",
    "MULTIGAME",
    "MULTI-GAME",
    "MMR",      # esports rating series
    "TENNIS",
    "ATPTOUR",
    "WTATOUR",
    "WIMBLEDON",
    "USOPENTENNIS",
    "PGATOUR",
    "PGAGOLF",
    "F1RACE",
    "NBAFINAL",
    "NFLSB",
    "MLBHR",
    "NHLSC",
    "UFC",
    "OSCAR",
    "GRAMMY",
    "EMMY",
    "OLYMP",
)


def _ticker_rejection_hit(ticker: Any) -> str | None:
    if not ticker:
        return None
    raw = str(ticker).strip().upper()
    if not raw:
        return None
    # Match against the full uppercase ticker so prefix segments like
    # ``KXMVESPORTSMULTIGAMEEXTENDED-...`` reject on ``MVESPORTS`` even
    # when wrapped by the KX series prefix and a hash suffix.
    for needle in _TICKER_REJECTION_SUBSTRINGS:
        if needle in raw:
            return needle
    return None


# ---------------------------------------------------------------------------
# CategoryDecision
# ---------------------------------------------------------------------------


def _safety_stamps() -> dict[str, Any]:
    return {
        "advisory_only": True,
        "human_review_required": True,
        "execution_locked": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


def _empty_decision(reason: str, source: str = CATEGORY_SOURCE_UNKNOWN) -> dict[str, Any]:
    return {
        "kalshi_category_raw": "",
        "kalshi_category_slug": "",
        "kalshi_subcategory_raw": "",
        "mvp_category": None,
        "display_category": None,
        "category_confidence": "none",
        "category_source": source,
        "category_allowed": False,
        "quarantine_reason": reason,
        "safety": _safety_stamps(),
    }


def _allowed_decision(
    *,
    slug: str,
    raw: str,
    subraw: str,
    source: str,
    confidence: str,
) -> dict[str, Any]:
    return {
        "kalshi_category_raw": raw,
        "kalshi_category_slug": slug,
        "kalshi_subcategory_raw": subraw,
        "mvp_category": slug,
        "display_category": DISPLAY_LABELS[slug],
        "category_confidence": confidence,
        "category_source": source,
        "category_allowed": True,
        "quarantine_reason": "",
        "safety": _safety_stamps(),
    }


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).lower()


def normalize_kalshi_category(
    raw_category: Any,
    *,
    raw_subcategory: Any = None,
    ticker: Any = None,
    source_route: Any = None,
    event_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical category decision for a Kalshi market.

    Returns a ``CategoryDecision`` dict with stable keys (see
    ``_allowed_decision`` / ``_empty_decision``).  Never raises.  Never
    weakens the allowlist.  Safety stamps are always present.

    Precedence (first hit wins):
      1. Ticker-pattern rejection (KXMVESPORTS, MULTIGAME, ...) →
         hard-quarantine before any positive layer runs.
      2. Explicit raw_category in the rejected set →
         ``category_explicitly_rejected``.
      3. Explicit raw_category in the allowlist → ``official_metadata``.
      4. source_route (caller's intended Kalshi tab) in the allowlist →
         ``source_route``.
      5. Ticker prefix / keyword inference via
         ``scripts.kalshi_normalizer.infer_kalshi_category`` →
         ``ticker_fallback`` or ``keyword_fallback`` based on the reason.
      6. No usable metadata → ``no_usable_category_metadata``.

    ``event_metadata`` is forwarded to the inference layer for
    /events-joined category recovery (advisory; never opens the gate).
    """
    raw_key = _normalize_text(raw_category)
    sub_key = _normalize_text(raw_subcategory)

    # 1. Ticker-pattern rejection.
    ticker_hit = _ticker_rejection_hit(ticker)
    if ticker_hit is not None:
        decision = _empty_decision(
            QUARANTINE_TICKER_REJECTED, source=CATEGORY_SOURCE_TICKER
        )
        decision["kalshi_category_raw"] = raw_key
        decision["kalshi_subcategory_raw"] = sub_key
        decision["quarantine_reason"] = f"{QUARANTINE_TICKER_REJECTED}:{ticker_hit.lower()}"
        return decision

    # 2. Explicit rejected raw category.
    if raw_key and raw_key in EXPLICIT_REJECTED_CATEGORIES:
        decision = _empty_decision(
            QUARANTINE_EXPLICIT_REJECTED, source=CATEGORY_SOURCE_OFFICIAL
        )
        decision["kalshi_category_raw"] = raw_key
        decision["kalshi_subcategory_raw"] = sub_key
        decision["quarantine_reason"] = f"{QUARANTINE_EXPLICIT_REJECTED}:{raw_key}"
        return decision

    # 3. Allowlisted raw category.
    classification = classify_kalshi_category(raw_category)
    if classification["allowed"]:
        slug = DISPLAY_TO_SLUG[classification["display_category"]]
        return _allowed_decision(
            slug=slug,
            raw=raw_key,
            subraw=sub_key,
            source=CATEGORY_SOURCE_OFFICIAL,
            confidence="high",
        )

    # 4. source_route fallback (caller fetched by category route).
    route_key = _normalize_text(source_route)
    route_class = classify_kalshi_category(route_key)
    if route_class["allowed"]:
        slug = DISPLAY_TO_SLUG[route_class["display_category"]]
        return _allowed_decision(
            slug=slug,
            raw=raw_key,
            subraw=sub_key,
            source=CATEGORY_SOURCE_ROUTE,
            confidence="medium",
        )

    # 5. Ticker/keyword inference.  Build the minimum payload the
    # inference layer expects.
    inference_payload: dict[str, Any] = dict(event_metadata or {})
    if ticker is not None and "ticker" not in inference_payload:
        inference_payload["ticker"] = ticker
    inference_payload.setdefault("category", raw_category)
    cat_display, reason = infer_kalshi_category(inference_payload)
    if cat_display in DISPLAY_TO_SLUG:
        slug = DISPLAY_TO_SLUG[cat_display]
        inferred_source = (
            CATEGORY_SOURCE_TICKER
            if reason.startswith("ticker_prefix:")
            else CATEGORY_SOURCE_KEYWORD
        )
        return _allowed_decision(
            slug=slug,
            raw=raw_key,
            subraw=sub_key,
            source=inferred_source,
            confidence="low",
        )

    # The inference layer hard-rejects (rejection anchor or explicit
    # rejected category).  Surface that reason verbatim so the audit
    # trail explains *why*.
    if reason.startswith("explicit_rejected_category:") or reason.startswith(
        "rejected_keyword:"
    ):
        decision = _empty_decision(
            QUARANTINE_EXPLICIT_REJECTED, source=CATEGORY_SOURCE_KEYWORD
        )
        decision["kalshi_category_raw"] = raw_key
        decision["kalshi_subcategory_raw"] = sub_key
        decision["quarantine_reason"] = f"{QUARANTINE_EXPLICIT_REJECTED}:{reason}"
        return decision

    # 6. No usable metadata.
    if not raw_key and not ticker and not route_key:
        decision = _empty_decision(QUARANTINE_NO_USABLE_METADATA)
        decision["kalshi_subcategory_raw"] = sub_key
        return decision

    decision = _empty_decision(QUARANTINE_NOT_IN_ALLOWLIST)
    decision["kalshi_category_raw"] = raw_key
    decision["kalshi_subcategory_raw"] = sub_key
    return decision


def is_allowed_slug(slug: Any) -> bool:
    return isinstance(slug, str) and slug in ALLOWED_KALSHI_CATEGORIES


def display_label_for(slug: Any) -> str | None:
    if isinstance(slug, str):
        return DISPLAY_LABELS.get(slug)
    return None


def safety_stamps() -> dict[str, Any]:
    return _safety_stamps()


__all__ = [
    "ALLOWED_KALSHI_CATEGORIES",
    "DISPLAY_LABELS",
    "DISPLAY_TO_SLUG",
    "CATEGORY_SOURCE_OFFICIAL",
    "CATEGORY_SOURCE_ROUTE",
    "CATEGORY_SOURCE_TICKER",
    "CATEGORY_SOURCE_KEYWORD",
    "CATEGORY_SOURCE_UNKNOWN",
    "QUARANTINE_NOT_IN_ALLOWLIST",
    "QUARANTINE_EXPLICIT_REJECTED",
    "QUARANTINE_TICKER_REJECTED",
    "QUARANTINE_NO_USABLE_METADATA",
    "CANONICAL_CATEGORIES",
    "KALSHI_CATEGORY_MAP",
    "normalize_kalshi_category",
    "is_allowed_slug",
    "display_label_for",
    "safety_stamps",
]
