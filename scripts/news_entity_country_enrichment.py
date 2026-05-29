"""Deterministic entity + country enrichment for news rows.

Live news rows arrive with ``entity_name=null`` and ``country=null`` (the
provider gives a headline, not a security). With nothing to resolve, those rows
stay UNMAPPED, ``C_news`` is 0, and L_today never sees a news-derived candidate.

This module adds a pure, deterministic, no-NLP-dependency enrichment pass:

    1. Extract candidate entities by matching the committed securities-master
       alias index against the (normalized) headline / summary / asset-tags.
    2. Score extraction confidence (mission formula).
    3. Resolve the candidate to a ticker via the existing entity-ticker mapper.
    4. Enrich the country deterministically (ticker suffix / exchange / domain).
    5. Gate a *valid* news mapping behind three thresholds so a bare common-word
       headline mention can never become a confident tradable candidate.

It is advisory / read-only: no broker, no execution, no network. Unmapped rows
are NEVER dropped — they are returned with an explicit failure reason for
evidence / data-quality feedback.

Mission formulas
----------------
    entity_extraction_confidence =
        0.45*exact_alias_in_headline + 0.20*exact_alias_in_summary
      + 0.15*asset_tag_match + 0.10*provider_entity_present
      + 0.10*ticker_symbol_present

    valid_news_mapping(e,t) = 1[
        entity_extraction_confidence >= 0.60
        and mapping_confidence(e,t)  >= 0.70
        and country_confidence(e)    >= 0.60 ]
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from scripts.entity_ticker_mapper import (
        DEFAULT_THETA_MAP,
        _normalize_alias,
        _security_master,
        map_event_to_tickers,
    )
    from scripts.top30_country_coverage import enrich_country
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from entity_ticker_mapper import (  # type: ignore[no-redef]
        DEFAULT_THETA_MAP,
        _normalize_alias,
        _security_master,
        map_event_to_tickers,
    )
    from top30_country_coverage import enrich_country  # type: ignore[no-redef]


THETA_ENTITY = 0.60
THETA_COUNTRY = 0.60

# Extraction-confidence weights (mission formula).
W_HEADLINE = 0.45
W_SUMMARY = 0.20
W_ASSET_TAG = 0.15
W_PROVIDER = 0.10
W_TICKER = 0.10

_HEADLINE_KEYS = ("headline", "title")
_SUMMARY_KEYS = ("summary", "description", "body_snippet", "body", "snippet")


def _normalize_text(value: Any) -> str:
    raw = str(value or "").lower()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in raw).split())


def _concat(event: dict[str, Any], keys: tuple[str, ...]) -> str:
    return _normalize_text(" ".join(str(event.get(k) or "") for k in keys))


def _phrase_present(alias_key: str, normalized_text: str, token_set: set[str]) -> bool:
    """Whole-token / whole-phrase containment (no mid-word substring hits)."""
    if not alias_key:
        return False
    parts = alias_key.split()
    if len(parts) == 1:
        return parts[0] in token_set
    return f" {alias_key} " in f" {normalized_text} "


def extract_news_entities(
    event: dict[str, Any],
    *,
    securities_master_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Return scored entity candidates found in the event text.

    Each candidate: ``{symbol, alias, entity_extraction_confidence,
    in_headline, in_summary, in_asset_tags}``. Ambiguous alias keys (one alias
    string mapping to several symbols) are skipped so extraction never picks a
    symbol at random. Sorted by confidence descending, then symbol.
    """
    master = _security_master(securities_master_path)
    headline_text = _concat(event, _HEADLINE_KEYS)
    summary_text = _concat(event, _SUMMARY_KEYS)
    headline_tokens = set(headline_text.split())
    summary_tokens = set(summary_text.split())

    asset_tags = event.get("asset_tags") or []
    asset_tag_norm = {_normalize_alias(t) for t in asset_tags if t}
    asset_tag_symbols = {str(t).strip().upper() for t in asset_tags if t}

    provider_entities = event.get("provider_entities") or []
    provider_norm = {_normalize_alias(p) for p in provider_entities if p}
    ticker_present = bool(str(event.get("ticker") or "").strip())

    best: dict[str, dict[str, Any]] = {}
    for alias_key, symbols in master.alias_index.items():
        if len(symbols) != 1:
            continue  # ambiguous alias -> never auto-extract a single symbol
        symbol = next(iter(symbols))
        in_headline = _phrase_present(alias_key, headline_text, headline_tokens)
        in_summary = _phrase_present(alias_key, summary_text, summary_tokens)
        in_asset = (
            alias_key in asset_tag_norm
            or symbol.upper() in asset_tag_symbols
        )
        in_provider = alias_key in provider_norm
        if not (in_headline or in_summary or in_asset or in_provider):
            continue
        confidence = (
            W_HEADLINE * (1.0 if in_headline else 0.0)
            + W_SUMMARY * (1.0 if in_summary else 0.0)
            + W_ASSET_TAG * (1.0 if in_asset else 0.0)
            + W_PROVIDER * (1.0 if in_provider else 0.0)
            + W_TICKER * (1.0 if ticker_present else 0.0)
        )
        confidence = max(0.0, min(1.0, confidence))
        prior = best.get(symbol)
        if prior is None or confidence > prior["entity_extraction_confidence"]:
            best[symbol] = {
                "symbol": symbol,
                "alias": alias_key,
                "entity_extraction_confidence": round(confidence, 4),
                "in_headline": in_headline,
                "in_summary": in_summary,
                "in_asset_tags": in_asset,
            }
    return sorted(
        best.values(),
        key=lambda c: (-c["entity_extraction_confidence"], c["symbol"]),
    )


def enrich_news_event(
    event: dict[str, Any],
    *,
    db_path: Path | None = None,
    securities_master_path: Path | None = None,
    theta_map: float = DEFAULT_THETA_MAP,
) -> dict[str, Any]:
    """Resolve a news event's entity, country, ticker + validity (never drops).

    Returns an enrichment dict (merge-able onto the event) that always carries
    ``mapping_status`` and, when unmapped, a ``mapping_failure_reason``.
    """
    base = {
        "entity_name": None,
        "entity_extraction_confidence": 0.0,
        "country": "UNKNOWN",
        "country_confidence": 0.0,
        "country_method": "INSUFFICIENT_EVIDENCE",
        "ticker": None,
        "exchange": "",
        "mapping_status": "UNMAPPED",
        "mapping_confidence": 0.0,
        "mapping_failure_reason": "NO_ENTITY",
        "valid_news_mapping": False,
    }

    # Country can be enriched even with no entity (explicit / domain / locale).
    plain_country = enrich_country(event)
    if plain_country["country"] != "UNKNOWN":
        base.update(
            country=plain_country["country"],
            country_confidence=plain_country["country_confidence"],
            country_method=plain_country["country_method"],
        )

    candidates = extract_news_entities(
        event, securities_master_path=securities_master_path
    )
    if not candidates:
        return base

    strong = [c for c in candidates if c["entity_extraction_confidence"] >= THETA_ENTITY]
    distinct_strong = {c["symbol"] for c in strong}
    if len(distinct_strong) > 1:
        base["entity_name"] = candidates[0]["alias"]
        base["entity_extraction_confidence"] = candidates[0]["entity_extraction_confidence"]
        base["mapping_failure_reason"] = "AMBIGUOUS_ENTITY"
        return base

    best = candidates[0]
    base["entity_name"] = best["alias"]
    base["entity_extraction_confidence"] = best["entity_extraction_confidence"]

    master = _security_master(securities_master_path)
    sec = master.symbol_index.get(best["symbol"], {})
    country_eval = enrich_country(
        event,
        mapped_country=sec.get("country"),
        mapped_ticker=sec.get("canonical_symbol") or best["symbol"],
        mapped_exchange=sec.get("exchange_code"),
    )
    base.update(
        country=country_eval["country"],
        country_confidence=country_eval["country_confidence"],
        country_method=country_eval["country_method"],
    )

    # Resolve the ticker, feeding the enriched country back so an exact alias
    # hit corroborated by a deterministic country can clear theta_map.
    map_event = dict(event)
    map_event["entity_name"] = best["alias"]
    if country_eval["country"] != "UNKNOWN":
        map_event.setdefault("country", country_eval["country"])
    rows = map_event_to_tickers(
        map_event,
        db_path=db_path,
        securities_master_path=securities_master_path,
        theta_map=theta_map,
    )
    mrow = max(rows, key=lambda m: float(m.get("mapping_confidence") or 0.0))
    base["ticker"] = mrow.get("ticker")
    base["exchange"] = mrow.get("exchange", "")
    base["mapping_status"] = mrow.get("mapping_status", "UNMAPPED")
    base["mapping_confidence"] = float(mrow.get("mapping_confidence") or 0.0)
    if mrow.get("mapping_status") == "MAPPED":
        base["mapping_failure_reason"] = None
    else:
        base["mapping_failure_reason"] = mrow.get("mapping_failure_reason") or "NO_ALIAS_MATCH"

    extraction_ok = base["entity_extraction_confidence"] >= THETA_ENTITY
    mapping_ok = base["mapping_confidence"] >= theta_map and base["mapping_status"] == "MAPPED"
    country_ok = base["country_confidence"] >= THETA_COUNTRY
    base["valid_news_mapping"] = bool(extraction_ok and mapping_ok and country_ok)

    if not base["valid_news_mapping"] and base["mapping_status"] == "MAPPED":
        if not extraction_ok:
            base["mapping_failure_reason"] = "INSUFFICIENT_ENTITY_CONFIDENCE"
        elif not country_ok:
            base["mapping_failure_reason"] = "COUNTRY_MISMATCH"
        elif not mapping_ok:
            base["mapping_failure_reason"] = "MULTIPLE_LOW_CONFIDENCE_MATCHES"
    return base


def apply_news_enrichment(
    event: dict[str, Any],
    *,
    db_path: Path | None = None,
    securities_master_path: Path | None = None,
    theta_map: float = DEFAULT_THETA_MAP,
) -> dict[str, Any]:
    """Return a copy of ``event`` with enriched ``entity_name`` / ``country``.

    Only populates ``entity_name`` when a *valid* news mapping is found, so an
    ambiguous / low-confidence headline mention never injects a fake entity.
    A confidently-enriched country is always written back (it helps coverage
    even without a tradable mapping). Original keys are otherwise preserved.
    """
    enr = enrich_news_event(
        event,
        db_path=db_path,
        securities_master_path=securities_master_path,
        theta_map=theta_map,
    )
    out = dict(event)
    if enr["valid_news_mapping"]:
        out["entity_name"] = enr["entity_name"]
        out["ticker"] = enr["ticker"]
    if enr["country"] and enr["country"] != "UNKNOWN":
        out.setdefault("country", enr["country"])
    out["country_confidence"] = enr["country_confidence"]
    out["country_method"] = enr["country_method"]
    out["entity_extraction_confidence"] = enr["entity_extraction_confidence"]
    out["valid_news_mapping"] = enr["valid_news_mapping"]
    if not enr["valid_news_mapping"]:
        out.setdefault("news_mapping_failure_reason", enr["mapping_failure_reason"])
    return out


__all__ = [
    "THETA_ENTITY",
    "THETA_COUNTRY",
    "extract_news_entities",
    "enrich_news_event",
    "apply_news_enrichment",
]
