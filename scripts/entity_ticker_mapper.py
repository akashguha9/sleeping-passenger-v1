"""Entity-to-ticker mapping for the live discovery bridge.

Live news/filing events arrive with an entity name (and sometimes a raw
ticker). The synthesis can only treat an event as a tradable discovery when
that entity resolves to a concrete ``(ticker, exchange, country)`` with a
confidence score. Before this module the resolver existed in ``persistence``
but was never invoked by ingestion, so non-US events stayed tickerless and were
silently dropped.

This module bridges that gap. It is pure/advisory and read-only:
    * no broker, no execution, no network
    * reads the SQLite alias table (``resolve_alias``) read-only when a db is
      supplied, and the committed ``global_securities_master.yaml`` seed
    * NEVER fabricates a mapping — an unmappable event is RETAINED and labelled
      ``UNMAPPED`` with an explicit failure reason (never dropped)

Confidence (verbatim from the sprint spec)::

    mapping_confidence =
        0.40 * exact_alias_match
      + 0.20 * country_match
      + 0.15 * exchange_or_suffix_match
      + 0.10 * source_asset_tag_match
      + 0.10 * headline_context_match
      + 0.05 * provider_entity_confidence

    * passthrough ticker only  -> max(existing_confidence, 0.70)
    * fuzzy name match only     -> <= 0.60 unless country AND exchange match
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import REPO_ROOT
    from scripts.top30_country_coverage import (
        COUNTRY_CONF_MAPPED,
        canonical_country,
        country_from_ticker,
        enrich_country,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from runtime_common import REPO_ROOT
    from top30_country_coverage import (
        COUNTRY_CONF_MAPPED,
        canonical_country,
        country_from_ticker,
        enrich_country,
    )


SECURITIES_MASTER_PATH = REPO_ROOT / "configs" / "global_securities_master.yaml"
DEFAULT_THETA_MAP = 0.70

_US_EXCHANGES = {"NYSE", "NASDAQ", "AMEX", "ARCA", "BATS", "NYSEARCA"}

# Trailing corporate-form tokens stripped during alias normalization so that
# "Reliance Industries Ltd" and "Reliance Industries Limited" collapse to the
# same key. Conservative + deterministic; never reduces a name to empty.
_CORP_SUFFIXES = {
    "ltd", "limited", "ltda", "plc", "ag", "sa", "sab", "nv", "corp",
    "corporation", "inc", "incorporated", "se", "co", "company", "companies",
    "holdings", "holding", "group", "gmbh", "ab", "oyj", "spa", "kk", "bhd",
    "tbk", "pcl", "asa", "pjsc", "sas", "srl", "llc", "lp", "llp", "aps",
}


def _normalize_alias(text: Any) -> str:
    """Case/punctuation-insensitive alias key with corporate suffixes stripped.

    Lowercases, maps every non-alphanumeric character to a space, collapses
    whitespace, then drops trailing corporate-form tokens (Ltd/PLC/AG/SA/...).
    Returns "" when there is nothing to index.
    """
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    tokens = "".join(ch if ch.isalnum() else " " for ch in raw).split()
    while len(tokens) > 1 and tokens[-1] in _CORP_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _load_yaml(path: Path) -> Any:
    try:
        from src.utils.config_loader import load_yaml_config

        return load_yaml_config(path)
    except Exception:
        try:
            import yaml  # type: ignore

            return yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            return None


class _SecuritiesMaster:
    """Indexed view of the securities master used by the mapper.

    * ``name_index``   — lowercased exact security name -> security dict.
    * ``symbol_index`` — uppercased canonical symbol -> security dict.
    * ``alias_index``  — normalized alias key -> set of canonical symbols.
                         Built from the top-level ``aliases:`` block, each
                         security's ``aliases`` list, and each security's
                         (suffix-stripped) name. A key resolving to more than
                         one distinct symbol is AMBIGUOUS, never auto-chosen.
    * ``symbol_set``   — every canonical symbol seen.
    """

    __slots__ = ("name_index", "symbol_index", "alias_index", "symbol_set")

    def __init__(
        self,
        name_index: dict[str, dict[str, Any]],
        symbol_index: dict[str, dict[str, Any]],
        alias_index: dict[str, frozenset[str]],
        symbol_set: frozenset[str],
    ) -> None:
        self.name_index = name_index
        self.symbol_index = symbol_index
        self.alias_index = alias_index
        self.symbol_set = symbol_set


@lru_cache(maxsize=4)
def _load_securities_master(path_str: str) -> _SecuritiesMaster:
    """Parse + index the securities master YAML (cached per path)."""
    path = Path(path_str)
    data = _load_yaml(path) if path.exists() else None
    name_index: dict[str, dict[str, Any]] = {}
    symbol_index: dict[str, dict[str, Any]] = {}
    alias_accum: dict[str, set[str]] = {}
    symbols: set[str] = set()

    def _add_alias(key: str, symbol: str) -> None:
        norm = _normalize_alias(key)
        if not norm or not symbol:
            return
        alias_accum.setdefault(norm, set()).add(symbol.upper())

    if isinstance(data, dict):
        for entry in data.get("securities") or []:
            if not isinstance(entry, dict):
                continue
            symbol = str(entry.get("canonical_symbol") or "").strip().upper()
            if not symbol:
                continue
            name = str(entry.get("name") or "").strip()
            sec = {
                "canonical_symbol": symbol,
                "yahoo_symbol": str(entry.get("yahoo_symbol") or symbol),
                "local_ticker": str(entry.get("local_ticker") or "").strip(),
                "exchange_code": str(entry.get("exchange_code") or "").strip().upper(),
                "country": canonical_country(entry.get("country")),
                "currency": (str(entry.get("currency")).strip() if entry.get("currency") else None),
                "asset_type": str(entry.get("asset_type") or "EQUITY"),
                "sector": (str(entry.get("sector")).strip() if entry.get("sector") else None),
                "name": name,
                "is_adr": bool(entry.get("is_adr", False)),
                "adr_ticker": (str(entry.get("adr_ticker")).strip().upper() if entry.get("adr_ticker") else None),
                "mapping_priority": entry.get("mapping_priority"),
            }
            symbols.add(symbol)
            symbol_index[symbol] = sec
            if name:
                name_index[name.lower()] = sec
                _add_alias(name, symbol)
            company_name = str(entry.get("company_name") or "").strip()
            if company_name:
                _add_alias(company_name, symbol)
            for alias in entry.get("aliases") or []:
                _add_alias(str(alias), symbol)

        # Top-level explicit aliases (alias -> canonical_symbol).
        for entry in data.get("aliases") or []:
            if not isinstance(entry, dict):
                continue
            alias = str(entry.get("alias") or "").strip()
            target = str(entry.get("canonical_symbol") or "").strip().upper()
            if alias and target:
                symbols.add(target)
                _add_alias(alias, target)

    alias_index = {key: frozenset(syms) for key, syms in alias_accum.items()}
    return _SecuritiesMaster(name_index, symbol_index, alias_index, frozenset(symbols))


def _security_master(path: Path | None) -> _SecuritiesMaster:
    return _load_securities_master(str(path or SECURITIES_MASTER_PATH))


def _is_us_listing(exchange: str, country: str | None, ticker: str) -> bool:
    if exchange and exchange.upper() in _US_EXCHANGES:
        return True
    # A bare ticker with no foreign suffix and US country tag is US-listed.
    if country == "United States" and country_from_ticker(ticker) is None:
        return True
    return False


def _entity_name(event: dict[str, Any]) -> str:
    for key in ("entity_name", "issuer_name", "company", "company_name", "name"):
        value = str(event.get(key) or "").strip()
        if value:
            return value
    return ""


def _raw_ticker(event: dict[str, Any]) -> str:
    for key in ("ticker", "ticker_or_identifier", "symbol"):
        value = str(event.get(key) or "").strip().upper()
        if value:
            return value
    return ""


def _event_country(event: dict[str, Any]) -> str | None:
    return (
        canonical_country(event.get("country"))
        or canonical_country(event.get("jurisdiction"))
    )


def _confidence(
    *,
    exact_alias_match: bool,
    country_match: bool,
    exchange_or_suffix_match: bool,
    source_asset_tag_match: bool,
    headline_context_match: bool,
    provider_entity_confidence: float,
) -> float:
    raw = (
        0.40 * (1.0 if exact_alias_match else 0.0)
        + 0.20 * (1.0 if country_match else 0.0)
        + 0.15 * (1.0 if exchange_or_suffix_match else 0.0)
        + 0.10 * (1.0 if source_asset_tag_match else 0.0)
        + 0.10 * (1.0 if headline_context_match else 0.0)
        + 0.05 * max(0.0, min(1.0, provider_entity_confidence))
    )
    return max(0.0, min(1.0, raw))


def _mapped(
    *,
    entity_name: str,
    ticker: str,
    exchange: str,
    country: str | None,
    confidence: float,
    method: str,
    reason: str,
    asset_type: str = "EQUITY",
    currency: str | None = None,
    is_adr: bool | None = None,
) -> dict[str, Any]:
    if is_adr is None:
        is_adr = ticker.upper().endswith(".ADR") or (
            country not in (None, "United States")
            and _is_us_listing(exchange, country, ticker)
        )
    return {
        "entity_name": entity_name,
        "ticker": ticker.upper(),
        "exchange": exchange.upper(),
        "country": country,
        "country_confidence": None,
        "country_method": None,
        "currency": currency,
        "asset_type": asset_type,
        "mapping_confidence": round(confidence, 4),
        "mapping_method": method,
        "mapping_status": "MAPPED" if confidence > 0 else "UNMAPPED",
        "is_adr": bool(is_adr),
        "is_local_listing": country_from_ticker(ticker) is not None,
        "reason": reason,
    }


def _unmapped(entity_name: str, reason_code: str, detail: str = "") -> dict[str, Any]:
    return {
        "entity_name": entity_name,
        "ticker": None,
        "exchange": "",
        "country": None,
        "country_confidence": None,
        "country_method": None,
        "currency": None,
        "asset_type": None,
        "mapping_confidence": 0.0,
        "mapping_method": "none",
        "mapping_status": "UNMAPPED",
        "mapping_failure_reason": reason_code,
        "is_adr": False,
        "is_local_listing": False,
        "reason": detail or reason_code,
    }


def _attach_country_confidence(row: dict[str, Any], event: dict[str, Any]) -> None:
    """Fill ``country_confidence``/``country_method`` (and country if absent).

    For a row that already carries a country (a real mapping), the mapped
    country is authoritative — we only record how strongly the event evidence
    corroborates it. For a country-less row (unmapped or no master country) we
    adopt the deterministically enriched country, which may stay UNKNOWN.
    """
    enriched = enrich_country(
        event,
        mapped_country=row.get("country"),
        mapped_ticker=row.get("ticker"),
        mapped_exchange=row.get("exchange"),
    )
    if row.get("country"):
        if enriched["country"] == row["country"]:
            row["country_confidence"] = enriched["country_confidence"]
            row["country_method"] = enriched["country_method"]
        else:
            row["country_confidence"] = COUNTRY_CONF_MAPPED
            row["country_method"] = "mapped_ticker_country"
    else:
        row["country"] = enriched["country"] if enriched["country"] != "UNKNOWN" else None
        row["country_confidence"] = enriched["country_confidence"]
        row["country_method"] = enriched["country_method"]


def map_event_to_tickers(
    event: dict[str, Any],
    *,
    db_path: Path | None = None,
    securities_master_path: Path | None = None,
    theta_map: float = DEFAULT_THETA_MAP,
    phantom_set: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Map one event to candidate tickers (never silently drops).

    Returns a non-empty list. When nothing maps, the single row has
    ``mapping_status="UNMAPPED"`` and a ``mapping_failure_reason``.
    """
    master_data = _security_master(securities_master_path)
    name_index = master_data.name_index
    symbol_index = master_data.symbol_index
    alias_index = master_data.alias_index
    symbol_set = master_data.symbol_set
    phantom_set = {t.upper() for t in (phantom_set or set())}
    entity_name = _entity_name(event)
    raw_ticker = _raw_ticker(event)
    event_country = _event_country(event)
    asset_tags = event.get("asset_tags") or []
    try:
        provider_conf = float(event.get("mapping_confidence") or event.get("confidence") or 0.0)
    except (TypeError, ValueError):
        provider_conf = 0.0

    results: list[dict[str, Any]] = []

    # --- 1. Passthrough: the event already carries a ticker. ---
    if raw_ticker:
        suffix_country = country_from_ticker(raw_ticker)
        country = suffix_country or event_country
        master = symbol_index.get(raw_ticker)
        exchange = master["exchange_code"] if master else ""
        if master and master.get("country"):
            country = master["country"]
        confidence = max(provider_conf, 0.70)
        results.append(
            _mapped(
                entity_name=entity_name or raw_ticker,
                ticker=raw_ticker,
                exchange=exchange,
                country=country,
                confidence=confidence,
                method="passthrough_ticker",
                reason="event carried an explicit ticker/identifier",
                currency=(master or {}).get("currency"),
            )
        )

    # --- 2. Alias DB resolution (read-only). ---
    if not results and entity_name and db_path is not None:
        try:
            try:
                from scripts.persistence import resolve_alias
            except ModuleNotFoundError:  # pragma: no cover
                from persistence import resolve_alias  # type: ignore[no-redef]
            canonical = resolve_alias(entity_name, db_path=db_path)
        except Exception:
            canonical = None
        if canonical:
            master = symbol_index.get(canonical.upper())
            country = (master or {}).get("country") or event_country or country_from_ticker(canonical)
            exchange = (master or {}).get("exchange_code", "")
            confidence = _confidence(
                exact_alias_match=True,
                country_match=bool(event_country and country == event_country),
                exchange_or_suffix_match=bool(exchange or country_from_ticker(canonical)),
                source_asset_tag_match=bool(asset_tags),
                headline_context_match=False,
                provider_entity_confidence=provider_conf,
            )
            results.append(
                _mapped(
                    entity_name=entity_name,
                    ticker=canonical,
                    exchange=exchange,
                    country=country,
                    confidence=confidence,
                    method="alias_db",
                    reason="resolved via global_security_aliases",
                    currency=(master or {}).get("currency"),
                )
            )

    # --- 3. Securities-master exact name match. ---
    if not results and entity_name:
        sec = name_index.get(entity_name.lower())
        if sec:
            confidence = _confidence(
                exact_alias_match=True,
                country_match=bool(event_country and sec["country"] == event_country),
                exchange_or_suffix_match=bool(sec["exchange_code"]),
                source_asset_tag_match=bool(asset_tags),
                headline_context_match=True,
                provider_entity_confidence=provider_conf,
            )
            results.append(
                _mapped(
                    entity_name=entity_name,
                    ticker=sec["canonical_symbol"],
                    exchange=sec["exchange_code"],
                    country=sec["country"],
                    confidence=confidence,
                    method="securities_master_exact",
                    reason="exact name match in global securities master",
                    asset_type=sec["asset_type"],
                    currency=sec.get("currency"),
                )
            )

    # --- 3b. Deterministic alias-index resolution. ---
    # Normalized aliases from the YAML (top-level + per-security `aliases` +
    # suffix-stripped names). An exact alias hit scores high; an alias that
    # resolves to more than one distinct symbol is AMBIGUOUS and is never
    # silently collapsed to a single ticker.
    if not results and entity_name:
        norm = _normalize_alias(entity_name)
        candidate_symbols = alias_index.get(norm) if norm else None
        if candidate_symbols:
            if len(candidate_symbols) == 1:
                symbol = next(iter(candidate_symbols))
                sec = symbol_index.get(symbol)
                country = (
                    (sec or {}).get("country")
                    or event_country
                    or country_from_ticker(symbol)
                )
                exchange = (sec or {}).get("exchange_code", "")
                confidence = _confidence(
                    exact_alias_match=True,
                    country_match=bool(event_country and country == event_country),
                    exchange_or_suffix_match=bool(exchange or country_from_ticker(symbol)),
                    source_asset_tag_match=bool(asset_tags),
                    headline_context_match=True,
                    provider_entity_confidence=provider_conf,
                )
                results.append(
                    _mapped(
                        entity_name=entity_name,
                        ticker=symbol,
                        exchange=exchange,
                        country=country,
                        confidence=confidence,
                        method="alias_index",
                        reason="exact alias match in securities master alias index",
                        asset_type=(sec or {}).get("asset_type", "EQUITY"),
                        currency=(sec or {}).get("currency"),
                        is_adr=(sec or {}).get("is_adr"),
                    )
                )
            else:
                return [
                    _unmapped(
                        entity_name,
                        "AMBIGUOUS_ENTITY",
                        f"alias '{norm}' resolves to {len(candidate_symbols)} distinct symbols: "
                        + ", ".join(sorted(candidate_symbols)),
                    )
                ]

    # --- 4. Securities-master fuzzy (token-prefix) match. ---
    if not results and entity_name:
        lowered = entity_name.lower()
        fuzzy = [
            sec
            for name, sec in name_index.items()
            if name and (name.startswith(lowered.split()[0]) or lowered.split()[0] in name)
        ] if lowered.split() else []
        if len(fuzzy) == 1:
            sec = fuzzy[0]
            country_match = bool(event_country and sec["country"] == event_country)
            exchange_match = bool(sec["exchange_code"])
            confidence = _confidence(
                exact_alias_match=False,
                country_match=country_match,
                exchange_or_suffix_match=exchange_match,
                source_asset_tag_match=bool(asset_tags),
                headline_context_match=True,
                provider_entity_confidence=provider_conf,
            )
            # Fuzzy is capped at 0.60 unless BOTH country and exchange match.
            if not (country_match and exchange_match):
                confidence = min(confidence, 0.60)
            results.append(
                _mapped(
                    entity_name=entity_name,
                    ticker=sec["canonical_symbol"],
                    exchange=sec["exchange_code"],
                    country=sec["country"],
                    confidence=confidence,
                    method="securities_master_fuzzy",
                    reason="single fuzzy name match in securities master",
                    asset_type=sec["asset_type"],
                    currency=sec.get("currency"),
                )
            )
        elif len(fuzzy) > 1:
            return [
                _unmapped(
                    entity_name,
                    "MULTIPLE_LOW_CONFIDENCE_MATCHES",
                    f"{len(fuzzy)} securities matched the entity name token",
                )
            ]

    # --- Unmapped handling. ---
    if not results:
        if not entity_name and not raw_ticker:
            row = _unmapped("", "NO_ENTITY", "event had no entity name or ticker")
        elif not symbol_set:
            row = _unmapped(entity_name, "SECURITY_MASTER_EMPTY", "securities master had no entries")
        else:
            row = _unmapped(entity_name, "NO_ALIAS_MATCH", "no alias/master match for entity")
        _attach_country_confidence(row, event)
        return [row]

    # --- ADR vs local preference + phantom flagging. ---
    for row in results:
        _attach_country_confidence(row, event)
        if row.get("ticker") and row["ticker"].upper() in phantom_set:
            row["phantom"] = True
            row["reason"] = (row.get("reason", "") + "; ticker is phantom/closed/sold").strip("; ")
        else:
            row["phantom"] = False
    # Prefer a valid local listing when both a local and an ADR row exist.
    local = [r for r in results if r.get("is_local_listing")]
    if local and any(not r.get("is_local_listing") for r in results):
        for r in results:
            if not r.get("is_local_listing"):
                r["local_listing_unresolved"] = False
        results = local + [r for r in results if not r.get("is_local_listing")]
    return results


def valid_mapped_event(
    mapped: dict[str, Any],
    *,
    theta_map: float = DEFAULT_THETA_MAP,
    top30_set: set[str] | None = None,
    price_resolvable: bool = True,
) -> bool:
    """valid_mapped_event(e,t) per spec."""
    if mapped.get("mapping_status") != "MAPPED":
        return False
    try:
        conf = float(mapped.get("mapping_confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    if conf < theta_map:
        return False
    if mapped.get("phantom"):
        return False
    if top30_set is not None and mapped.get("country") not in top30_set:
        return False
    return bool(price_resolvable or True)  # PRICE_PENDING is allowed


__all__ = [
    "DEFAULT_THETA_MAP",
    "SECURITIES_MASTER_PATH",
    "map_event_to_tickers",
    "valid_mapped_event",
]
