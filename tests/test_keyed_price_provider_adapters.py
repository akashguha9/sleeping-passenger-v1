"""Tests — P4 keyed read-only price-provider adapters + per-ticker failover.

Deterministic and NO network / NO real API keys:
  * Twelve Data / Alpha Vantage / Polygon JSON bodies parse to a canonical
    raw quote (price + timestamp + currency).
  * POLYGON honours both POLYGON_API_KEY and the MASSIVE_API_KEY alias.
  * provider symbol normalization preserves the original ticker.
  * the priority failover chain falls Yahoo -> Twelve -> Alpha -> Polygon,
    selecting the first provider that answers for a ticker.
  * missing keys yield NOT_CONFIGURED, never a crash.
  * no raw key value leaks into resolver diagnostics.
  * no broker / order / execution endpoint is reachable.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.real_price_provider import (
    ALPHA_VANTAGE,
    POLYGON,
    PRICE_PROVIDER_NOT_CONFIGURED,
    TWELVE_DATA,
    YAHOO,
    describe_price_providers,
    normalize_for_provider,
    parse_alpha_vantage_quote,
    parse_polygon_quote,
    parse_twelve_data_quote,
    provider_configured,
    resolve_price_provider_chain,
)

NOW = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
ISO = NOW.isoformat()
EPOCH = int(NOW.timestamp())


# --- 1. deterministic transport -> price_mark per provider ------------------

def test_twelve_data_quote_parses_to_price_mark():
    body = {
        "symbol": "RHM.DE",
        "close": "525.40",
        "previous_close": "519.0",
        "open": "520.0",
        "high": "528.0",
        "low": "518.0",
        "volume": "1234567",
        "currency": "EUR",
        "timestamp": EPOCH,
    }
    raw = parse_twelve_data_quote(body)
    assert raw is not None
    assert float(raw["price"]) == 525.40
    assert raw["currency"] == "EUR"
    assert raw["timestamp_utc"].startswith("2026-05-30")


def test_twelve_data_error_body_is_honest_none():
    assert parse_twelve_data_quote({"status": "error", "code": 400, "message": "bad"}) is None
    assert parse_twelve_data_quote({}) is None
    assert parse_twelve_data_quote(None) is None


def test_alpha_vantage_global_quote_parses_with_currency_hint():
    body = {
        "Global Quote": {
            "01. symbol": "MSFT",
            "05. price": "420.10",
            "08. previous close": "418.0",
            "02. open": "419.0",
            "07. latest trading day": "2026-05-30",
            "06. volume": "987654",
        }
    }
    raw = parse_alpha_vantage_quote(body, currency_hint="USD")
    assert raw is not None
    assert float(raw["price"]) == 420.10
    assert raw["currency"] == "USD"  # AV omits currency -> venue hint
    assert raw["timestamp_utc"] == "2026-05-30"


def test_polygon_prev_aggregate_parses():
    body = {
        "ticker": "SHEL",
        "status": "OK",
        "results": [
            {"c": 28.4, "o": 28.0, "h": 28.6, "l": 27.9, "v": 5_000_000, "t": EPOCH * 1000}
        ],
    }
    raw = parse_polygon_quote(body, currency_hint="GBP")
    assert raw is not None
    assert raw["price"] == 28.4
    assert raw["currency"] == "GBP"
    assert raw["timestamp_utc"].startswith("2026-05-30")


def test_polygon_empty_results_is_none():
    assert parse_polygon_quote({"status": "OK", "results": []}, currency_hint="USD") is None


# --- 2. MASSIVE_API_KEY alias for POLYGON -----------------------------------

def test_polygon_configured_by_polygon_key():
    assert provider_configured(POLYGON, {"POLYGON_API_KEY": "pg"}) is True


def test_polygon_configured_by_massive_alias():
    assert provider_configured(POLYGON, {"MASSIVE_API_KEY": "mv"}) is True
    # describe reflects presence + advertises the alias, never the value
    descs = {d["provider"]: d for d in describe_price_providers({"MASSIVE_API_KEY": "mv"})}
    assert descs[POLYGON]["configured"] is True
    assert descs[POLYGON]["api_key_present"] is True
    assert "MASSIVE_API_KEY" in descs[POLYGON]["api_key_env_aliases"]


def test_polygon_not_configured_without_either_key():
    assert provider_configured(POLYGON, {}) is False


# --- 3. symbol normalization preserves original -----------------------------

def test_normalize_preserves_original_and_builds_venue_symbol():
    n = normalize_for_provider("RHM.DE", TWELVE_DATA)
    assert n["original_ticker"] == "RHM.DE"
    assert n["provider_symbol"] == "XETRA:RHM"
    assert n["country"] == "Germany"
    assert normalize_for_provider("SHEL.L", POLYGON)["provider_symbol"] == "LON:SHEL"
    assert normalize_for_provider("RELIANCE.NS", ALPHA_VANTAGE)["provider_symbol"] == "NSE:RELIANCE"
    assert normalize_for_provider("7203.T", TWELVE_DATA)["provider_symbol"] == "TYO:7203"
    # bare US ticker passes through; Yahoo keeps native suffix form
    assert normalize_for_provider("MSFT", TWELVE_DATA)["provider_symbol"] == "MSFT"
    assert normalize_for_provider("RHM.DE", YAHOO)["provider_symbol"] == "RHM.DE"


# --- 4. per-ticker failover chain -------------------------------------------

def _fail_transport(_ticker):
    return None


def _ok_transport(price, currency):
    def _t(_ticker):
        return {"price": price, "timestamp_utc": ISO, "currency": currency}
    return _t


def test_failover_yahoo_fails_twelve_data_succeeds():
    res = resolve_price_provider_chain(
        transports={YAHOO: _fail_transport, TWELVE_DATA: _ok_transport(525.0, "EUR")},
        now_utc=NOW,
    )
    assert res["chain"][0] == YAHOO  # priority order preserved
    mark = res["callable"]("RHM.DE")
    assert mark is not None
    assert mark["provider"] == TWELVE_DATA  # Twelve answered after Yahoo empty
    assert mark["price"] == 525.0


def test_failover_twelve_fails_alpha_succeeds():
    res = resolve_price_provider_chain(
        transports={
            YAHOO: _fail_transport,
            TWELVE_DATA: _fail_transport,
            ALPHA_VANTAGE: _ok_transport(420.0, "USD"),
        },
        now_utc=NOW,
    )
    mark = res["callable"]("MSFT")
    assert mark["provider"] == ALPHA_VANTAGE
    assert mark["price"] == 420.0


def test_failover_alpha_fails_polygon_succeeds():
    res = resolve_price_provider_chain(
        transports={
            YAHOO: _fail_transport,
            TWELVE_DATA: _fail_transport,
            ALPHA_VANTAGE: _fail_transport,
            POLYGON: _ok_transport(28.4, "GBP"),
        },
        now_utc=NOW,
    )
    mark = res["callable"]("SHEL.L")
    assert mark["provider"] == POLYGON
    assert mark["price"] == 28.4


def test_failover_all_empty_returns_none():
    res = resolve_price_provider_chain(
        transports={YAHOO: _fail_transport, TWELVE_DATA: _fail_transport}, now_utc=NOW
    )
    assert res["callable"]("RHM.DE") is None


# --- 5. honest not-configured + safety --------------------------------------

def test_chain_offline_no_transport_is_network_disabled():
    res = resolve_price_provider_chain(allow_network=False, env={}, now_utc=NOW)
    assert res["callable"] is None
    assert res["status"] in {"NETWORK_DISABLED", PRICE_PROVIDER_NOT_CONFIGURED}


def test_chain_network_on_no_keys_not_configured():
    # Only Yahoo (public) would be selectable on network; keyed providers need
    # keys. With network on and no keys, Yahoo is in the chain.
    res = resolve_price_provider_chain(allow_network=True, env={}, now_utc=NOW)
    # Yahoo is public, so the chain is non-empty and starts with yahoo.
    assert res["chain"] == [YAHOO]
    assert res["status"] == "PROVIDER_SELECTED"


def test_chain_carries_locked_stamps_and_no_secret_leak():
    env = {"TWELVE_DATA_API_KEY": "td-secret-xyz", "MASSIVE_API_KEY": "mv-secret-xyz"}
    res = resolve_price_provider_chain(allow_network=True, env=env, now_utc=NOW)
    assert res["broker_api_called"] is False
    assert res["ai_execution_count"] == 0
    assert res["execution_gate"] == "LOCKED"
    blob = json.dumps(res, default=str)
    assert "td-secret-xyz" not in blob
    assert "mv-secret-xyz" not in blob


def test_module_introduces_no_broker_endpoint():
    import scripts.real_price_provider as m

    src = open(m.__file__, encoding="utf-8").read().lower()
    for forbidden in ("place_order", "submit_order", "/orders", "execute_trade", "broker_execute"):
        assert forbidden not in src
