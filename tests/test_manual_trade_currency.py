"""Sprint I addendum — Manual Trade Log native currency dropdown.

Backend tests for:
  - Central supported-currencies catalogue (top 30 economies covered).
  - Persistence accepts/normalises currency on insert.
  - Legacy rows without currency read back as UNKNOWN safely.
  - log_manual_trade wires currency through end-to-end.
  - Currency does NOT mutate safety stamps
    (broker_api_called=False, ai_execution_count=0, execution_gate=LOCKED).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


def test_catalogue_includes_top_30_economy_currencies():
    """Every currency the user named must be in the dropdown set."""
    from scripts.supported_currencies import SUPPORTED_CURRENCY_CODES

    required = {
        "USD", "CNY", "EUR", "JPY", "GBP", "INR", "RUB", "BRL", "CAD",
        "AUD", "MXN", "KRW", "TRY", "IDR", "SAR", "CHF", "PLN", "TWD",
        "SEK", "ILS", "ARS", "SGD", "AED",
    }
    missing = required - SUPPORTED_CURRENCY_CODES
    assert not missing, f"Catalogue missing: {missing}"


def test_eur_groups_eurozone_countries():
    """Shared currencies must list every country sharing them."""
    from scripts.supported_currencies import supported_currencies

    eur = next(c for c in supported_currencies() if c["code"] == "EUR")
    countries = set(eur["countries"])
    # The user named eight eurozone countries explicitly.
    for nation in (
        "Germany", "France", "Italy", "Spain",
        "Netherlands", "Ireland", "Belgium", "Austria",
    ):
        assert nation in countries, nation


def test_normalise_currency_accepts_supported_and_rejects_others():
    from scripts.supported_currencies import normalise_currency

    assert normalise_currency("inr") == "INR"
    assert normalise_currency("  EUR ") == "EUR"
    assert normalise_currency("USD") == "USD"
    # Unsupported / hostile / typo → UNKNOWN, never USD.
    assert normalise_currency("USDX") == "UNKNOWN"
    assert normalise_currency("") == "UNKNOWN"
    assert normalise_currency(None) == "UNKNOWN"
    assert normalise_currency("$$$") == "UNKNOWN"


def test_suggest_currency_for_symbol():
    """Suffix-based suggestion is a convenience, never silently submitted."""
    from scripts.supported_currencies import suggest_currency_for_symbol

    assert suggest_currency_for_symbol("BHARTIARTL.NS") == "INR"
    assert suggest_currency_for_symbol("RELIANCE.BO") == "INR"
    assert suggest_currency_for_symbol("SAP.DE") == "EUR"
    assert suggest_currency_for_symbol("AAPL") == "USD"
    assert suggest_currency_for_symbol("BTC-USD") == "USD"
    assert suggest_currency_for_symbol("WEIRD.XYZ") is None
    assert suggest_currency_for_symbol("") is None


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_db(tmp_path):
    db_path = tmp_path / "mvp.db"
    from scripts.persistence import init_schema

    init_schema(db_path)
    return db_path


def _insert(db_path, trade_id: str, ticker: str, currency: str = ""):
    from scripts.persistence import insert_manual_trade

    insert_manual_trade(
        trade_id=trade_id,
        event_id=f"EVT_{trade_id}",
        ticker=ticker,
        side="BUY",
        quantity=10.0,
        price=100.0,
        executed_at="2026-05-15T16:00:00Z",
        thesis="thesis",
        notes="",
        logged_by="human",
        db_path=db_path,
        currency=currency,
    )


@pytest.mark.parametrize("ticker,currency", [
    ("BHARTIARTL.NS", "INR"),
    ("AAPL", "USD"),
    ("SAP.DE", "EUR"),
    ("TLT", "USD"),
    ("RELIANCE.NS", "INR"),
    ("BTC-USD", "USD"),
])
def test_persist_and_read_back_currency(fresh_db, ticker, currency):
    from scripts.persistence import get_manual_trade

    _insert(fresh_db, f"MT_{ticker}_x", ticker, currency=currency)
    row = get_manual_trade(f"MT_{ticker}_x", db_path=fresh_db)
    assert row is not None
    assert row["currency"] == currency
    # Safety invariants are untouched by currency selection.
    assert row["broker_api_called"] is False
    assert row["ai_execution_count"] == 0
    assert row["advisory_status"] == "ADVISORY_ONLY"


def test_legacy_row_without_currency_reads_back_as_unknown(fresh_db):
    """Insert a manual trade with currency='' (legacy default) and
    confirm it reads back as UNKNOWN — never silently as USD."""
    from scripts.persistence import get_manual_trade

    _insert(fresh_db, "MT_LEGACY_001", "OLD_TICKER", currency="")
    row = get_manual_trade("MT_LEGACY_001", db_path=fresh_db)
    assert row is not None
    assert row["currency"] == "UNKNOWN"


def test_unsupported_currency_falls_back_to_unknown(fresh_db):
    """Hostile / typo input normalises to UNKNOWN at persistence boundary."""
    from scripts.persistence import get_manual_trade

    _insert(fresh_db, "MT_BAD_001", "AAPL", currency="USDX")
    row = get_manual_trade("MT_BAD_001", db_path=fresh_db)
    assert row is not None
    assert row["currency"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# log_manual_trade end-to-end (uses JSONL + DB)
# ---------------------------------------------------------------------------


def test_log_manual_trade_threads_currency(monkeypatch, tmp_path):
    """log_manual_trade must thread the operator-selected currency
    through to insert_manual_trade.  We capture the insert kwargs so
    the assertion does not depend on DB_PATH monkeypatching of an
    already-imported persistence module."""
    from scripts import signal_inbox_api as api

    jsonl_path = tmp_path / "manual_trade_log.jsonl"
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", jsonl_path)

    captured: dict[str, object] = {}

    def fake_insert(*args, **kwargs):
        captured.update(kwargs)
        captured["_args"] = args

    monkeypatch.setattr(api._persistence, "insert_manual_trade", fake_insert)

    out = api.log_manual_trade(
        event_id="EVT_INR_COVERAGE",
        ticker="BHARTIARTL.NS",
        side="BUY",
        quantity=10,
        price=1789.20,
        thesis="regression coverage for INR threading",
        currency="INR",
    )
    assert out.get("operation") == "log_manual_trade"
    # Currency normalises to INR and is passed via the dedicated kwarg.
    assert captured.get("currency") == "INR"
    # Safety stamps still in the return value.
    assert out.get("broker_api_called") in (False, None)


def test_log_manual_trade_currency_optional(monkeypatch, tmp_path):
    """Callers omitting currency stay backwards-compatible — the
    persistence layer receives '' rather than crashing."""
    from scripts import signal_inbox_api as api

    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "ml.jsonl")
    captured: dict[str, object] = {}

    def fake_insert(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(api._persistence, "insert_manual_trade", fake_insert)
    # Use a non-AAPL/180 ticker — the AAPL/$180 fingerprint is now a
    # fake-marker veto (see scripts/manual_trade_origin).  ``thesis``
    # also cannot contain the substring "no currency given" because
    # the leaked-row fingerprint matches that exact phrase.
    api.log_manual_trade(
        event_id="EVT_NO_CUR_COVERAGE",
        ticker="MSFT",
        side="BUY",
        quantity=5,
        price=421.0,
        thesis="currency omitted by caller, backwards-compat coverage",
    )
    # Omitted currency normalises to '' at the API boundary; the
    # persistence layer then reads it back as UNKNOWN on the next get.
    assert captured.get("currency", "") == ""


# ---------------------------------------------------------------------------
# API config endpoint
# ---------------------------------------------------------------------------


def test_config_supported_currencies_endpoint():
    """The /config/supported-currencies endpoint must list the codes the
    frontend dropdown is expected to render and carry safety stamps."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover
        pytest.skip("fastapi[testclient] not installed")

    import scripts.api_server as srv

    client = TestClient(srv.app, raise_server_exceptions=True)
    resp = client.get("/config/supported-currencies")
    assert resp.status_code == 200
    payload = resp.json()
    codes = {c["code"] for c in payload["currencies"]}
    for required in (
        "USD", "INR", "EUR", "JPY", "GBP", "CNY", "BRL", "CAD", "AUD",
        "MXN", "KRW", "TRY", "IDR", "SAR", "CHF", "PLN", "TWD", "SEK",
        "ILS", "ARS", "SGD", "AED", "RUB",
    ):
        assert required in codes, required
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["execution_gate"] == "LOCKED"


def test_post_manual_trade_accepts_currency(monkeypatch):
    """POST /manual-trades should forward `currency` to log_manual_trade."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover
        pytest.skip("fastapi[testclient] not installed")
    import scripts.api_server as srv

    captured: dict[str, object] = {}

    def fake_log(**kwargs):
        captured.update(kwargs)
        return {
            "operation": "log_manual_trade",
            "trade_id": "MT_FAKE_001",
            "broker_api_called": False,
            "ai_execution_count": 0,
        }

    monkeypatch.setattr(srv, "log_manual_trade", fake_log)
    client = TestClient(srv.app, raise_server_exceptions=True)
    body = {
        "event_id": "EVT_INR",
        "ticker": "BHARTIARTL.NS",
        "side": "BUY",
        "quantity": 10,
        "price": 1789.20,
        "thesis": "test",
        "currency": "INR",
    }
    resp = client.post("/manual-trades", json=body)
    assert resp.status_code == 200, resp.text
    assert captured.get("currency") == "INR"
