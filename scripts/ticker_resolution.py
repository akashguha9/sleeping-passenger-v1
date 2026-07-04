"""Increase Forward-Eligible Throughput Sprint — Phase 2: deterministic ticker
resolution for filings / news / scored rows.

A forward-outcome-eligible decision snapshot needs a *valid ticker* (see
:mod:`scripts.forward_snapshot_contract`).  In production many scored rows arrive
carrying only a company name (``"Tesla, Inc."``) or an SEC ``cik``
(``"0001318605"``) — never a clean exchange symbol.  This module resolves a
ticker **deterministically and conservatively**, never by fuzzy guessing.

Hard honesty rules (all enforced):

* No fabricated tickers.  Every accepted resolution carries a ``method``, a
  ``confidence`` and the ``source_field`` it came from — fully auditable.
* A resolution is accepted only when ``confidence >= ACCEPT_CONFIDENCE`` (0.90).
  Below that the ticker is ``None`` with an explicit reason.
* Company-name / CIK maps are *exact* and small (only high-confidence, well-known
  issuers already present in the runtime data).  An ambiguous company (e.g.
  Alphabet → GOOGL/GOOG) returns ``None`` with ``AMBIGUOUS_COMPANY_NAME``.
* This module is advisory-only.  It reads identifiers and returns a symbol; it
  never places an order, calls a broker, or unlocks execution.

Resolution priority (first valid wins)::

    ticker_i = first_valid(
        event.ticker, event.asset_symbol, event.symbol, event.ticker_symbol,
        payload.ticker, payload.symbol, payload.tickers[0], payload.assets[0],
        score_vector.ticker,
        sec_cik_to_ticker(payload.cik),
        company_name_to_ticker(payload.company_name / entity_name),
        title_to_known_ticker(payload.title),
    )

Validation::

    TickerValid(t) = I(t not null) · I(trim(t) != "")
                   · I(upper(t) not in {UNKNOWN, N/A, NULL, NONE, NAN})
                   · I(matches an accepted symbol pattern)
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping

try:  # package layout
    from scripts.forward_snapshot_contract import normalize_ticker as _normalize_contract_ticker
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    from forward_snapshot_contract import normalize_ticker as _normalize_contract_ticker  # type: ignore[no-redef]

RESOLVER_VERSION = "ticker-resolution-v1"

# Confidence floor for accepting a resolved ticker.
ACCEPT_CONFIDENCE = 0.90

# Per-method confidence (data-quality confidence, never a predictive claim).
CONF_DIRECT_SYMBOL = 1.0      # an explicit ticker/symbol field already present
CONF_SCORE_VECTOR = 0.95      # symbol persisted on the score vector side table
CONF_CIK_MAP = 0.99           # SEC CIK -> ticker is an exact regulatory identity
CONF_NAME_MAP = 0.95          # exact, hand-verified company-name map
CONF_TITLE_MAP = 0.92         # title contains an exact known company name

# Reasons.
REASON_OK = "OK"
REASON_NO_IDENTIFIER = "NO_TICKER_IDENTIFIER"
REASON_AMBIGUOUS = "AMBIGUOUS_COMPANY_NAME"
REASON_LOW_CONFIDENCE = "LOW_CONFIDENCE_TICKER_RESOLUTION"

_REJECTED = {"", "UNKNOWN", "N/A", "NA", "NULL", "NONE", "NAN", "TBD"}

# An accepted bare/decorated symbol: a 1-12 char alphanumeric base with an
# optional exchange prefix (``NSE:``) and an optional dotted/hyphen suffix
# (``.NS`` / ``-USD``).  The 12-char base admits long real tickers like
# ``BHARTIARTL``/``RELIANCE`` while a multi-word company name (which contains a
# space/comma) is still rejected so it routes through the name/CIK maps instead.
_SYMBOL_RE = re.compile(r"^(?:[A-Z]{2,8}:)?[A-Z0-9]{1,12}(?:[.\-][A-Z0-9]{1,5})?$")

# --------------------------------------------------------------------------- #
# Deterministic SEC CIK -> ticker map (exact regulatory identity).
# 10-digit zero-padded CIK form is canonical; we also accept the integer form.
# Only high-confidence issuers already present in the runtime data.
# --------------------------------------------------------------------------- #
_CIK_TO_TICKER: dict[str, str] = {
    "0000320193": "AAPL",   # Apple Inc.
    "0000789019": "MSFT",   # Microsoft Corp
    "0001045810": "NVDA",   # NVIDIA Corp
    "0001318605": "TSLA",   # Tesla, Inc.
    "0001018724": "AMZN",   # Amazon.com, Inc.
    "0001326801": "META",   # Meta Platforms, Inc.
}

# Deterministic, exact company-name -> ticker map.  Keys are upper-cased and
# whitespace-collapsed.  Conservative: only unambiguous issuers.
_NAME_TO_TICKER: dict[str, str] = {
    "APPLE INC": "AAPL",
    "APPLE INC.": "AAPL",
    "APPLE": "AAPL",
    "MICROSOFT CORP": "MSFT",
    "MICROSOFT CORPORATION": "MSFT",
    "MICROSOFT": "MSFT",
    "NVIDIA CORP": "NVDA",
    "NVIDIA CORPORATION": "NVDA",
    "NVIDIA": "NVDA",
    "TESLA INC": "TSLA",
    "TESLA, INC.": "TSLA",
    "TESLA INC.": "TSLA",
    "TESLA": "TSLA",
    "AMAZON.COM INC": "AMZN",
    "AMAZON.COM, INC.": "AMZN",
    "AMAZON COM INC": "AMZN",
    "META PLATFORMS INC": "META",
    "META PLATFORMS, INC.": "META",
}

# Company names that are real but *ambiguous* (multiple share classes / tickers).
# We deliberately refuse to pick one — honesty over coverage.
_AMBIGUOUS_NAMES = {
    "ALPHABET INC",
    "ALPHABET INC.",
    "ALPHABET",
    "GOOGLE",
    "GOOGLE INC",
}


def _collapse(text: Any) -> str:
    """Upper-case, trim, and collapse internal whitespace."""
    return re.sub(r"\s+", " ", str(text or "").strip()).upper()


def ticker_valid(ticker: Any) -> bool:
    """``TickerValid`` — non-null, non-empty, not a sentinel, matches a symbol."""
    norm = _normalize_contract_ticker(ticker)
    if norm is None:
        return False
    if norm in _REJECTED:
        return False
    return bool(_SYMBOL_RE.match(norm))


def sec_cik_to_ticker(cik: Any) -> str | None:
    """Map an SEC CIK (zero-padded or integer form) to a ticker, or ``None``."""
    if cik is None:
        return None
    raw = str(cik).strip()
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    padded = digits.zfill(10)
    return _CIK_TO_TICKER.get(padded)


def company_name_to_ticker(name: Any) -> tuple[str | None, str]:
    """Map an exact company name to a ticker.

    Returns ``(ticker_or_none, reason)``.  An ambiguous issuer returns
    ``(None, "AMBIGUOUS_COMPANY_NAME")``; an unknown name returns
    ``(None, "NO_TICKER_IDENTIFIER")``.  Never fuzzy-matches.
    """
    key = _collapse(name)
    if not key:
        return None, REASON_NO_IDENTIFIER
    if key in _AMBIGUOUS_NAMES:
        return None, REASON_AMBIGUOUS
    hit = _NAME_TO_TICKER.get(key)
    if hit is not None:
        return hit, REASON_OK
    return None, REASON_NO_IDENTIFIER


def title_to_known_ticker(title: Any) -> str | None:
    """Resolve a ticker iff the title *contains* an exact known company name.

    Conservative substring match against the exact name map only — no fuzzy
    token scoring.  Longest names first so ``"NVIDIA CORPORATION"`` wins over a
    bare ``"NVIDIA"`` substring.
    """
    text = _collapse(title)
    if not text:
        return None
    for name in sorted(_NAME_TO_TICKER, key=len, reverse=True):
        # Require word boundaries so "META" does not match "METAL".
        if re.search(rf"(?<![A-Z0-9]){re.escape(name)}(?![A-Z0-9])", text):
            return _NAME_TO_TICKER[name]
    return None


def _payload(obj: Any) -> Mapping[str, Any] | None:
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except (json.JSONDecodeError, TypeError):
            return None
    return obj if isinstance(obj, Mapping) else None


def _first_list_item(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and value:
        return value[0]
    return None


def resolve_ticker(
    *,
    event_row: Mapping[str, Any] | None = None,
    payload: Any = None,
    score_vector: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a ticker for one decision candidate, deterministically.

    Returns a ``TickerResolution`` dict::

        {ticker, confidence, method, source_field, reason, resolver_version}

    ``ticker`` is ``None`` (with an honest ``reason``) when no identifier exists,
    the company is ambiguous, or the best resolution is below
    :data:`ACCEPT_CONFIDENCE`.  Nothing is ever fabricated.
    """
    pl = _payload(payload)
    ev = event_row if isinstance(event_row, Mapping) else None
    sv = score_vector if isinstance(score_vector, Mapping) else None

    # 1) Direct symbol fields on the event row / payload (highest confidence).
    direct_sources: list[tuple[str, Any]] = []
    if ev is not None:
        for key in ("ticker", "asset_symbol", "symbol", "ticker_symbol"):
            direct_sources.append((f"event.{key}", ev.get(key)))
    if pl is not None:
        for key in ("ticker", "symbol", "asset_symbol", "ticker_symbol"):
            direct_sources.append((f"payload.{key}", pl.get(key)))
        direct_sources.append(("payload.tickers[0]", _first_list_item(pl.get("tickers"))))
        direct_sources.append(("payload.assets[0]", _first_list_item(pl.get("assets"))))
    for field, raw in direct_sources:
        norm = _normalize_contract_ticker(raw)
        if norm is not None and ticker_valid(norm):
            return _result(norm, CONF_DIRECT_SYMBOL, "direct_symbol_field", field)

    # 2) Score-vector persisted ticker.  This may itself be a company name
    #    ("Tesla, Inc.") — resolve it through the name map before accepting.
    if sv is not None:
        sv_raw = sv.get("ticker")
        norm = _normalize_contract_ticker(sv_raw)
        if norm is not None and ticker_valid(norm):
            return _result(norm, CONF_SCORE_VECTOR, "score_vector_symbol", "score_vector.ticker")
        name_hit, _reason = company_name_to_ticker(sv_raw)
        if name_hit is not None:
            return _result(name_hit, CONF_NAME_MAP, "score_vector_company_name", "score_vector.ticker")

    # 3) SEC CIK -> ticker (exact regulatory identity).
    cik = None
    if pl is not None:
        cik = pl.get("cik")
    if cik is None and ev is not None:
        cik = ev.get("cik")
    cik_hit = sec_cik_to_ticker(cik)
    if cik_hit is not None:
        return _result(cik_hit, CONF_CIK_MAP, "sec_cik_map", "payload.cik")

    # 4) Exact company-name map (entity_name / company_name).
    ambiguous = False
    for field in ("entity_name", "company_name", "companyName", "name"):
        val = (pl or {}).get(field) if pl is not None else None
        if val is None and ev is not None:
            val = ev.get(field)
        if val is None:
            continue
        name_hit, reason = company_name_to_ticker(val)
        if name_hit is not None:
            return _result(name_hit, CONF_NAME_MAP, "company_name_map", f"payload.{field}")
        if reason == REASON_AMBIGUOUS:
            ambiguous = True

    # 5) Title contains an exact known company name.
    title = (pl or {}).get("title") if pl is not None else None
    if title is None and ev is not None:
        title = ev.get("title")
    title_hit = title_to_known_ticker(title)
    if title_hit is not None:
        return _result(title_hit, CONF_TITLE_MAP, "title_company_name", "payload.title")

    if ambiguous:
        return _none_result(REASON_AMBIGUOUS)
    return _none_result(REASON_NO_IDENTIFIER)


def _result(ticker: str, confidence: float, method: str, source_field: str) -> dict[str, Any]:
    if confidence < ACCEPT_CONFIDENCE:
        return _none_result(REASON_LOW_CONFIDENCE)
    return {
        "ticker": ticker,
        "confidence": round(float(confidence), 4),
        "method": method,
        "source_field": source_field,
        "reason": REASON_OK,
        "resolver_version": RESOLVER_VERSION,
    }


def _none_result(reason: str) -> dict[str, Any]:
    return {
        "ticker": None,
        "confidence": 0.0,
        "method": None,
        "source_field": None,
        "reason": reason,
        "resolver_version": RESOLVER_VERSION,
    }


def resolve_ticker_symbol(
    *,
    event_row: Mapping[str, Any] | None = None,
    payload: Any = None,
    score_vector: Mapping[str, Any] | None = None,
) -> str | None:
    """Convenience wrapper returning just the accepted ticker (or ``None``)."""
    return resolve_ticker(
        event_row=event_row, payload=payload, score_vector=score_vector
    )["ticker"]


__all__ = [
    "RESOLVER_VERSION",
    "ACCEPT_CONFIDENCE",
    "REASON_OK",
    "REASON_NO_IDENTIFIER",
    "REASON_AMBIGUOUS",
    "REASON_LOW_CONFIDENCE",
    "ticker_valid",
    "sec_cik_to_ticker",
    "company_name_to_ticker",
    "title_to_known_ticker",
    "resolve_ticker",
    "resolve_ticker_symbol",
]
