"""Real read-only price-provider resolver (advisory, P_price priority).

Selects the first *usable* read-only quote provider in priority order::

    P_price = [YAHOO_PUBLIC_READ_ONLY, TWELVE_DATA, ALPHA_VANTAGE, POLYGON]

* Yahoo's public chart/quote endpoint needs no API key (public read-only).
* Twelve Data / Alpha Vantage / Polygon are gated on an env key whose *value*
  is never logged (only ``api_key_present`` is reported).
* Network is NEVER touched unless ``allow_network=True``. Tests inject a
  deterministic ``transports`` mapping so the resolve/parse/normalize path runs
  with NO network and NO key.

The resolver yields a provider *callable* shaped for
:func:`scripts.refresh_live_price_marks.refresh_price_marks` — i.e.
``provider(ticker) -> mark dict | None``.

Hard safety contract (mirrors the rest of the MVP):
    * read-of-market only — returning a price quote NEVER trades.
    * no broker, no order placement, no Alpaca *trading* endpoint. Broker /
      execution providers are explicitly non-selectable here.
    * a misbehaving / empty / timed-out provider degrades to an honest status;
      it never fabricates a price and never claims LIVE without fresh data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping

try:
    from scripts.provider_secret_redaction import key_present, provider_key_fields
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from provider_secret_redaction import key_present, provider_key_fields


# Provider identifiers.
YAHOO = "yahoo"
TWELVE_DATA = "twelve_data"
ALPHA_VANTAGE = "alpha_vantage"
POLYGON = "polygon"

# Priority order — Yahoo public first, then key-gated providers.
PRICE_PROVIDER_PRIORITY: tuple[str, ...] = (YAHOO, TWELVE_DATA, ALPHA_VANTAGE, POLYGON)

# Provider -> required env key (None = public, no key needed).
PROVIDER_ENV: dict[str, str | None] = {
    YAHOO: None,
    TWELVE_DATA: "TWELVE_DATA_API_KEY",
    ALPHA_VANTAGE: "ALPHA_VANTAGE_API_KEY",
    POLYGON: "POLYGON_API_KEY",
}

# A provider may accept more than one env-var spelling for its key. The first
# entry is the *canonical* one reported in ``api_key_env``; any alias also
# satisfies ``provider_configured`` (e.g. POLYGON honours MASSIVE_API_KEY).
PROVIDER_ENV_ALIASES: dict[str, tuple[str, ...]] = {
    TWELVE_DATA: ("TWELVE_DATA_API_KEY",),
    ALPHA_VANTAGE: ("ALPHA_VANTAGE_API_KEY",),
    POLYGON: ("POLYGON_API_KEY", "MASSIVE_API_KEY"),
}

# Broker / trading / execution providers are NEVER selectable as a price source.
# A request to prefer one of these is refused (returns no callable).
FORBIDDEN_PROVIDERS: frozenset[str] = frozenset(
    {
        "alpaca",
        "alpaca_trading",
        "alpaca_orders",
        "broker",
        "ibkr",
        "ib_trade",
        "interactive_brokers",
        "execute",
        "order",
    }
)

# Honest provider/price status vocabulary (mission P3).
PRICE_PROVIDER_NOT_CONFIGURED = "PRICE_PROVIDER_NOT_CONFIGURED"
NETWORK_DISABLED = "NETWORK_DISABLED"
PRICE_PROVIDER_OK_EMPTY = "PRICE_PROVIDER_OK_EMPTY"
PRICE_PROVIDER_TIMEOUT = "PRICE_PROVIDER_TIMEOUT"
PRICE_PROVIDER_ERROR = "PRICE_PROVIDER_ERROR"
PRICE_PROVIDER_RATE_LIMITED = "PRICE_PROVIDER_RATE_LIMITED"
PRICE_PROVIDER_AUTH_FAILED = "PRICE_PROVIDER_AUTH_FAILED"
SYMBOL_UNSUPPORTED = "SYMBOL_UNSUPPORTED"
PROVIDER_SELECTED = "PROVIDER_SELECTED"

# Network read timeout — every real request is bounded.
HTTP_TIMEOUT_SECONDS = 8.0

# A transport fetches a *raw* quote for one ticker. It must be read-only.
PriceTransport = Callable[[str], "dict[str, Any] | None"]


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(microsecond=0).isoformat()


def provider_requires_key(provider: str) -> bool:
    return PROVIDER_ENV.get(provider) is not None


def provider_env_names(provider: str) -> tuple[str, ...]:
    """Every env-var spelling that satisfies this provider's key (canonical first)."""
    env_key = PROVIDER_ENV.get(provider)
    if env_key is None:
        return ()
    return PROVIDER_ENV_ALIASES.get(provider, (env_key,))


def provider_configured(provider: str, env: Mapping[str, str] | None = None) -> bool:
    """A provider is configured when it needs no key, or ANY of its key env
    names (canonical or alias) is present. POLYGON honours MASSIVE_API_KEY."""
    env_key = PROVIDER_ENV.get(provider)
    if env_key is None:
        return provider in PROVIDER_ENV  # public provider (Yahoo) is always configured
    return any(key_present(name, env) for name in provider_env_names(provider))


def describe_price_providers(env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Secret-safe descriptor for every known price provider (priority order)."""
    out: list[dict[str, Any]] = []
    for name in PRICE_PROVIDER_PRIORITY:
        fields = provider_key_fields(name, PROVIDER_ENV.get(name), env)
        # Honour every accepted env-var spelling (e.g. POLYGON/MASSIVE) so the
        # *_present boolean agrees with ``configured``. Secret VALUES are never
        # added here — only booleans and the env-var NAMES.
        aliases = provider_env_names(name)
        if len(aliases) > 1:
            fields["api_key_env_aliases"] = list(aliases)
            fields["api_key_present"] = any(key_present(a, env) for a in aliases)
        fields["configured"] = provider_configured(name, env)
        fields["category"] = "READ_ONLY_MARKET_DATA"
        out.append(fields)
    return out


def _normalize_raw_quote(
    ticker: str, raw: Any, provider: str, now_utc: datetime
) -> dict[str, Any] | None:
    """Map a transport's raw quote into the canonical mark shape, or None.

    Accepts several key spellings so a real or injected transport can hand back
    its native shape. Returns None when there is no usable price (honest empty).
    """
    if not isinstance(raw, dict):
        return None
    price = raw.get("price")
    if price is None:
        price = raw.get("close")
    if price is None:
        price = raw.get("last_price")
    if price is None:
        price = raw.get("regularMarketPrice")
    timestamp = (
        raw.get("timestamp_utc")
        or raw.get("timestamp")
        or raw.get("as_of")
        or raw.get("regular_market_time")
    )
    if price is None or not timestamp:
        return None
    try:
        price_f = float(price)
    except (TypeError, ValueError):
        return None
    return {
        "ticker": ticker,
        "price": price_f,
        "close": price_f,
        "timestamp_utc": str(timestamp),
        "currency": raw.get("currency"),
        "previous_close": raw.get("previous_close"),
        "open": raw.get("open"),
        "high": raw.get("high") or raw.get("day_high"),
        "low": raw.get("low") or raw.get("day_low"),
        "volume": raw.get("volume"),
        "provider": provider,
    }


def _yahoo_http_quote(ticker: str) -> dict[str, Any] | None:  # pragma: no cover - network
    """Best-effort public Yahoo chart quote. Read-only; never raises.

    Only invoked on the real network path (``allow_network=True`` and no
    injected transport). Bounded by ``HTTP_TIMEOUT_SECONDS``. Returns None on
    any failure so the caller degrades honestly.
    """
    import json as _json
    import urllib.parse
    import urllib.request

    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{urllib.parse.quote(ticker)}?range=1d&interval=1d"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "sleeping-passenger-advisory/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            data = _json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - network failure is non-fatal
        return None
    try:
        result = data["chart"]["result"][0]
        meta = result["meta"]
        price = meta.get("regularMarketPrice")
        ts = meta.get("regularMarketTime")
        ts_iso = (
            datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat() if ts else None
        )
        return {
            "price": price,
            "timestamp_utc": ts_iso,
            "currency": meta.get("currency"),
            "previous_close": meta.get("chartPreviousClose") or meta.get("previousClose"),
        }
    except (KeyError, IndexError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Keyed-provider symbol normalization + quote parsers (P4).
# ---------------------------------------------------------------------------
# Each provider speaks a slightly different symbol dialect. We NEVER replace the
# operator's original ticker — we derive a best-effort ``provider_symbol`` and
# preserve ``original_ticker`` alongside it. Exchange-suffix -> (venue prefix,
# country) used to build prefixed provider symbols (e.g. XETRA:RHM, LON:SHEL).
_SUFFIX_VENUE: dict[str, tuple[str, str]] = {
    ".DE": ("XETRA", "Germany"),
    ".F": ("XETRA", "Germany"),
    ".L": ("LON", "United Kingdom"),
    ".NS": ("NSE", "India"),
    ".BO": ("BSE", "India"),
    ".T": ("TYO", "Japan"),
    ".TW": ("TPE", "Taiwan"),
    ".KS": ("KRX", "South Korea"),
    ".PA": ("EPA", "France"),
    ".AS": ("AMS", "Netherlands"),
    ".MI": ("BIT", "Italy"),
    ".MC": ("BME", "Spain"),
    ".SA": ("BVMF", "Brazil"),
    ".TO": ("TSX", "Canada"),
    ".AX": ("ASX", "Australia"),
    ".SI": ("SGX", "Singapore"),
    ".HK": ("HKG", "Hong Kong"),
    ".SS": ("SHA", "China"),
    ".SZ": ("SHE", "China"),
}

# Providers that accept a ``VENUE:BASE`` prefixed symbol for non-US listings.
_PREFIXED_SYMBOL_PROVIDERS = frozenset({TWELVE_DATA, POLYGON, ALPHA_VANTAGE})


def normalize_for_provider(ticker: str, provider: str) -> dict[str, Any]:
    """Best-effort provider symbol for ``ticker`` — original is NEVER replaced.

    Returns ``{original_ticker, provider_symbol, provider, resolved_exchange,
    country}``. Yahoo keeps the native suffixed symbol; the keyed providers get
    a ``VENUE:BASE`` form for non-US listings (e.g. RHM.DE -> XETRA:RHM, SHEL.L
    -> LON:SHEL, RELIANCE.NS -> NSE:RELIANCE, 7203.T -> TYO:7203). Bare US
    tickers are passed through unchanged (MSFT -> MSFT).
    """
    original = str(ticker).strip()
    upper = original.upper()
    suffix = ""
    base = upper
    if "." in upper:
        base, suf = upper.rsplit(".", 1)
        suffix = "." + suf
    venue, country = _SUFFIX_VENUE.get(suffix, ("", "United States" if not suffix else ""))
    if provider == YAHOO or not suffix:
        provider_symbol = original
    elif provider in _PREFIXED_SYMBOL_PROVIDERS and venue:
        provider_symbol = f"{venue}:{base}"
    else:
        provider_symbol = original
    return {
        "original_ticker": original,
        "provider_symbol": provider_symbol,
        "provider": provider,
        "resolved_exchange": venue or ("US" if not suffix else ""),
        "country": country or None,
    }


def _epoch_to_iso(value: Any) -> str | None:
    """Convert an epoch (seconds or milliseconds) to a UTC ISO string, or None."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num <= 0:
        return None
    if num > 1e12:  # milliseconds
        num /= 1000.0
    try:
        return datetime.fromtimestamp(num, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def parse_twelve_data_quote(
    payload: Any, *, currency_hint: str | None = None
) -> dict[str, Any] | None:
    """Map a Twelve Data ``/quote`` JSON body into the canonical raw-quote dict.

    Returns None on an error/empty body (honest empty). Pure — no network.
    """
    if not isinstance(payload, dict):
        return None
    if str(payload.get("status") or "").lower() == "error":
        return None
    price = payload.get("close") or payload.get("price")
    if price is None:
        return None
    ts = payload.get("timestamp")
    ts_iso = _epoch_to_iso(ts) if ts is not None else None
    if ts_iso is None:
        ts_iso = str(payload.get("datetime") or "").strip() or None
    if ts_iso is None:
        return None
    return {
        "price": price,
        "timestamp_utc": ts_iso,
        "currency": payload.get("currency") or currency_hint,
        "previous_close": payload.get("previous_close"),
        "open": payload.get("open"),
        "high": payload.get("high"),
        "low": payload.get("low"),
        "volume": payload.get("volume"),
    }


def parse_alpha_vantage_quote(
    payload: Any, *, currency_hint: str | None = None
) -> dict[str, Any] | None:
    """Map an Alpha Vantage ``GLOBAL_QUOTE`` body into the canonical raw quote.

    Alpha Vantage's GLOBAL_QUOTE does not return a currency, so a venue-derived
    ``currency_hint`` is used (US listings default to USD by the caller). Pure.
    """
    if not isinstance(payload, dict):
        return None
    quote = payload.get("Global Quote") or payload.get("globalQuote") or payload
    if not isinstance(quote, dict):
        return None
    price = quote.get("05. price") or quote.get("price")
    day = quote.get("07. latest trading day") or quote.get("latest_trading_day")
    if price is None or not day:
        return None
    return {
        "price": price,
        "timestamp_utc": str(day).strip(),
        "currency": currency_hint,
        "previous_close": quote.get("08. previous close"),
        "open": quote.get("02. open"),
        "high": quote.get("03. high"),
        "low": quote.get("04. low"),
        "volume": quote.get("06. volume"),
    }


def parse_polygon_quote(
    payload: Any, *, currency_hint: str | None = None
) -> dict[str, Any] | None:
    """Map a Polygon ``/v2/aggs/ticker/{t}/prev`` body into the canonical raw quote.

    Polygon (and the MASSIVE alias) return aggregate bars; we read the most
    recent result's close. Pure — no network.
    """
    if not isinstance(payload, dict):
        return None
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return None
    bar = results[0]
    if not isinstance(bar, dict):
        return None
    price = bar.get("c")
    ts_iso = _epoch_to_iso(bar.get("t"))
    if price is None or ts_iso is None:
        return None
    return {
        "price": price,
        "timestamp_utc": ts_iso,
        "currency": currency_hint,
        "open": bar.get("o"),
        "high": bar.get("h"),
        "low": bar.get("l"),
        "volume": bar.get("v"),
    }


def _keyed_http_quote(provider: str, ticker: str) -> dict[str, Any] | None:  # pragma: no cover - network
    """Best-effort read-only fetch for a key-gated provider. Never raises.

    Read-only quote/aggregate endpoints only — NO broker, NO order, NO trading
    endpoint is ever reached. Bounded by ``HTTP_TIMEOUT_SECONDS``. The API key
    is read from the environment at call time and is NEVER logged.
    """
    import json as _json
    import os
    import urllib.parse
    import urllib.request

    norm = normalize_for_provider(ticker, provider)
    sym = norm["provider_symbol"]
    currency_hint = "USD" if not norm["resolved_exchange"] or norm["resolved_exchange"] == "US" else None

    def _key() -> str | None:
        for name in provider_env_names(provider):
            val = os.environ.get(name, "").strip()
            if val:
                return val
        return None

    key = _key()
    if not key:
        return None
    if provider == TWELVE_DATA:
        url = (
            "https://api.twelvedata.com/quote?symbol="
            f"{urllib.parse.quote(sym)}&apikey={urllib.parse.quote(key)}"
        )
        parser = parse_twelve_data_quote
    elif provider == ALPHA_VANTAGE:
        url = (
            "https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol="
            f"{urllib.parse.quote(sym)}&apikey={urllib.parse.quote(key)}"
        )
        parser = parse_alpha_vantage_quote
    elif provider == POLYGON:
        url = (
            f"https://api.polygon.io/v2/aggs/ticker/{urllib.parse.quote(sym)}/prev"
            f"?adjusted=true&apiKey={urllib.parse.quote(key)}"
        )
        parser = parse_polygon_quote
    else:
        return None

    req = urllib.request.Request(
        url, headers={"User-Agent": "sleeping-passenger-advisory/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            data = _json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - network failure is non-fatal
        return None
    return parser(data, currency_hint=currency_hint)


def _default_real_transport(provider: str) -> PriceTransport | None:
    """The real read-only fetcher for a provider, or None when unimplemented.

    Yahoo uses its public endpoint; the key-gated providers (Twelve Data, Alpha
    Vantage, Polygon/MASSIVE) use their read-only quote/aggregate endpoints. All
    are read-only — no broker/order/trading endpoint is ever reached.
    """
    if provider == YAHOO:
        return _yahoo_http_quote
    if provider in (TWELVE_DATA, ALPHA_VANTAGE, POLYGON):
        return lambda ticker, _p=provider: _keyed_http_quote(_p, ticker)
    return None


def _candidate_order(prefer: str | None) -> list[str]:
    if prefer:
        p = str(prefer).strip().lower()
        if p in PRICE_PROVIDER_PRIORITY:
            return [p] + [x for x in PRICE_PROVIDER_PRIORITY if x != p]
    return list(PRICE_PROVIDER_PRIORITY)


def resolve_price_provider(
    *,
    allow_network: bool = False,
    prefer: str | None = None,
    env: Mapping[str, str] | None = None,
    transports: Mapping[str, PriceTransport] | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Resolve the active read-only price provider + build its callable.

    Returns a dict with:
        provider           : selected provider name or None
        status             : PROVIDER_SELECTED / NETWORK_DISABLED /
                             PRICE_PROVIDER_NOT_CONFIGURED
        callable           : provider(ticker)->mark|None, or None
        configured_providers / selectable_providers : secret-safe diagnostics
        allow_network, prefer_rejected_reason

    Selection logic (first match wins, priority order):
        * an injected transport for a provider makes it selectable OFFLINE
          (deterministic, no network) regardless of ``allow_network``.
        * otherwise a provider is selectable only when configured AND
          ``allow_network`` is True (a real network fetch).
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    transports = dict(transports or {})

    prefer_rejected = None
    if prefer and str(prefer).strip().lower() in FORBIDDEN_PROVIDERS:
        prefer_rejected = f"refused forbidden/broker provider '{prefer}'"
        prefer = None

    descriptors = describe_price_providers(env)
    any_configured = any(d["configured"] for d in descriptors)

    selected: str | None = None
    transport: PriceTransport | None = None
    for name in _candidate_order(prefer):
        if name in FORBIDDEN_PROVIDERS:
            continue
        injected = transports.get(name)
        if injected is not None:
            selected, transport = name, injected
            break
        if provider_configured(name, env) and allow_network:
            real = _default_real_transport(name)
            if real is not None:
                selected, transport = name, real
                break

    if selected is None or transport is None:
        if transports:
            status = PRICE_PROVIDER_NOT_CONFIGURED
        elif not allow_network:
            status = NETWORK_DISABLED
        elif not any_configured:
            status = PRICE_PROVIDER_NOT_CONFIGURED
        else:
            # configured + network on, but no real adapter wired for it yet.
            status = PRICE_PROVIDER_NOT_CONFIGURED
        return {
            "provider": None,
            "status": status,
            "callable": None,
            "allow_network": bool(allow_network),
            "configured_providers": descriptors,
            "selectable_providers": [],
            "prefer_rejected_reason": prefer_rejected,
            "broker_api_called": False,
            "ai_execution_count": 0,
            "execution_gate": "LOCKED",
        }

    fetch = transport

    def _provider(ticker: str) -> dict[str, Any] | None:
        try:
            raw = fetch(ticker)
        except Exception:  # noqa: BLE001 - per-symbol network failure is safe
            return None
        return _normalize_raw_quote(str(ticker), raw, selected, now_utc)

    return {
        "provider": selected,
        "status": PROVIDER_SELECTED,
        "callable": _provider,
        "allow_network": bool(allow_network),
        "configured_providers": descriptors,
        "selectable_providers": [selected],
        "prefer_rejected_reason": prefer_rejected,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_gate": "LOCKED",
    }


def resolve_price_provider_chain(
    *,
    allow_network: bool = False,
    env: Mapping[str, str] | None = None,
    transports: Mapping[str, PriceTransport] | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Resolve a PER-TICKER FAILOVER callable across the P_price priority chain.

    Unlike :func:`resolve_price_provider` (which selects a single provider), this
    returns a callable that, for each ticker, tries every selectable provider in
    priority order until one yields a normalized mark — implementing::

        selected_provider(t) = first p in P_price with valid normalized quote(t)

    A provider is in the chain when it has an injected transport (offline,
    deterministic) OR is configured AND ``allow_network`` is True AND a real
    read-only adapter exists. Broker/execution providers are never in the chain.

    Returns a dict with ``chain`` (provider names, in order), ``callable``
    (``ticker -> mark|None``; the mark's ``provider`` field names the provider
    that actually answered), secret-safe ``configured_providers``, and the
    advisory LOCKED stamps.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    transports = dict(transports or {})
    descriptors = describe_price_providers(env)

    chain: list[tuple[str, PriceTransport]] = []
    for name in PRICE_PROVIDER_PRIORITY:
        if name in FORBIDDEN_PROVIDERS:
            continue
        injected = transports.get(name)
        if injected is not None:
            chain.append((name, injected))
            continue
        if provider_configured(name, env) and allow_network:
            real = _default_real_transport(name)
            if real is not None:
                chain.append((name, real))

    def _failover(ticker: str) -> dict[str, Any] | None:
        for provider, fetch in chain:
            try:
                raw = fetch(ticker)
            except Exception:  # noqa: BLE001 - per-provider failure is safe
                continue
            mark = _normalize_raw_quote(str(ticker), raw, provider, now_utc)
            if mark is not None:
                return mark
        return None

    status = PROVIDER_SELECTED if chain else (
        NETWORK_DISABLED if (not allow_network and not transports)
        else PRICE_PROVIDER_NOT_CONFIGURED
    )
    return {
        "chain": [name for name, _ in chain],
        "status": status,
        "callable": _failover if chain else None,
        "allow_network": bool(allow_network),
        "configured_providers": descriptors,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_gate": "LOCKED",
    }


def build_mock_price_transport(
    now_utc: datetime | None = None,
    universe: Mapping[str, tuple[str, float]] | None = None,
) -> PriceTransport:
    """Deterministic offline transport for tests / ``--use-mock-providers``.

    Returns a fresh quote for a fixed multi-country fixture universe and None
    for anything else (honest 'symbol unsupported'). No network, no API key.
    The fixture spans Germany / UK / India / Japan / US so the price layer can
    be exercised across countries.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    iso = _iso(now_utc)
    fixture: dict[str, tuple[str, float]] = dict(
        universe
        or {
            "RHM.DE": ("EUR", 525.0),
            "SAP.DE": ("EUR", 175.0),
            "SHEL.L": ("GBP", 28.0),
            "BP.L": ("GBP", 4.6),
            "RELIANCE.NS": ("INR", 2900.0),
            "HDFCBANK.NS": ("INR", 1650.0),
            "7203.T": ("JPY", 3100.0),
            "AAPL": ("USD", 190.0),
            "MSFT": ("USD", 420.0),
        }
    )

    def _transport(ticker: str) -> dict[str, Any] | None:
        key = str(ticker).strip().upper()
        if key not in fixture:
            return None
        currency, price = fixture[key]
        return {
            "price": price,
            "timestamp_utc": iso,
            "currency": currency,
            "volume": 1_000_000.0,
            "previous_close": round(price * 0.99, 4),
        }

    return _transport


__all__ = [
    "PRICE_PROVIDER_PRIORITY",
    "PROVIDER_ENV",
    "FORBIDDEN_PROVIDERS",
    "YAHOO",
    "TWELVE_DATA",
    "ALPHA_VANTAGE",
    "POLYGON",
    "PRICE_PROVIDER_NOT_CONFIGURED",
    "NETWORK_DISABLED",
    "PRICE_PROVIDER_OK_EMPTY",
    "PRICE_PROVIDER_TIMEOUT",
    "PRICE_PROVIDER_ERROR",
    "PRICE_PROVIDER_RATE_LIMITED",
    "PRICE_PROVIDER_AUTH_FAILED",
    "SYMBOL_UNSUPPORTED",
    "PROVIDER_SELECTED",
    "PROVIDER_ENV_ALIASES",
    "provider_requires_key",
    "provider_configured",
    "provider_env_names",
    "describe_price_providers",
    "resolve_price_provider",
    "resolve_price_provider_chain",
    "normalize_for_provider",
    "parse_twelve_data_quote",
    "parse_alpha_vantage_quote",
    "parse_polygon_quote",
    "build_mock_price_transport",
]
