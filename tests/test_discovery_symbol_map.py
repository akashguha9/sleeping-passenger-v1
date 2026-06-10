"""DISC-B1 regression: explicit exchange mapping, fail-loud resolution.

Fixture covers every supported exchange prefix plus a deliberately
broken symbol that MUST raise — silent dropping or wrong-instrument
fetches are the failure mode this kills.
"""
from __future__ import annotations

import pytest

from scripts.discovery_symbol_map import (
    EXCHANGE_TO_YAHOO_SUFFIX,
    SymbolResolutionError,
    resolve_symbol,
    validate_universe,
)

# One representative per exchange prefix in the table.
_FIXTURE = {
    "NASDAQ:ANET": "ANET",
    "NYSE:RTX": "RTX",
    "AMEX:GLD": "GLD",
    "BATS:CBOE": "CBOE",
    "NSE:RELIANCE": "RELIANCE.NS",
    "BSE:500325": "500325.BO",
    "LON:BARC": "BARC.L",
    "LSE:HSBA": "HSBA.L",
    "ETR:SAP": "SAP.DE",
    "XETRA:BMW": "BMW.DE",
    "FRA:DTE": "DTE.F",
    "TYO:7203": "7203.T",
    "JPX:6758": "6758.T",
    "KRX:005930": "005930.KS",
    "KOSPI:000660": "000660.KS",
    "KOSDAQ:035720": "035720.KQ",
    "TSX:SHOP": "SHOP.TO",
    "TSXV:DML": "DML.V",
    "HKG:0700": "0700.HK",
    "HKEX:9988": "9988.HK",
    "TPE:2330": "2330.TW",
    "TWSE:2002": "2002.TW",
    "ASX:BHP": "BHP.AX",
}


def test_every_supported_exchange_maps_correctly():
    for raw, expected in _FIXTURE.items():
        out = resolve_symbol(raw)
        assert out["yahoo_symbol"] == expected, raw
        assert out["resolution"] == "prefix_mapped"
        assert out["execution_gate"] == "LOCKED"


def test_fixture_covers_the_entire_mapping_table():
    covered = {raw.split(":")[0] for raw in _FIXTURE}
    assert covered == set(EXCHANGE_TO_YAHOO_SUFFIX), (
        "fixture must cover every exchange in the table"
    )


def test_plain_and_already_suffixed_pass_through():
    assert resolve_symbol("AAPL")["yahoo_symbol"] == "AAPL"
    assert resolve_symbol("AAPL")["resolution"] == "plain"
    out = resolve_symbol("SBIN.NS")
    assert out["yahoo_symbol"] == "SBIN.NS"
    assert out["resolution"] == "already_suffixed"


def test_unknown_prefix_fails_loud():
    with pytest.raises(SymbolResolutionError) as exc:
        resolve_symbol("MOEX:GAZP")
    assert "unknown exchange prefix" in str(exc.value)
    assert "NEVER guessed" in str(exc.value)


def test_ambiguous_tse_is_refused_with_guidance():
    with pytest.raises(SymbolResolutionError) as exc:
        resolve_symbol("TSE:7203")
    assert "ambiguous" in str(exc.value)
    assert "TYO:" in str(exc.value) and "TSX:" in str(exc.value)


@pytest.mark.parametrize("bad", ["", "  ", "NSE:", "NSE:REL IANCE", "N$E:X"])
def test_malformed_symbols_fail_loud(bad):
    with pytest.raises(SymbolResolutionError):
        resolve_symbol(bad)


def test_validate_universe_fails_the_whole_batch_with_full_list():
    symbols = ["NSE:RELIANCE", "BROKEN:XYZ", "TSE:AMBIG", "AAPL"]
    with pytest.raises(SymbolResolutionError) as exc:
        validate_universe(symbols)
    msg = str(exc.value)
    # Every failure is named; nothing is silently dropped.
    assert "BROKEN" in msg and "TSE" in msg
    assert "nothing was fetched" in msg


def test_validate_universe_rejects_duplicate_mappings():
    with pytest.raises(SymbolResolutionError) as exc:
        validate_universe(["NSE:RELIANCE", "RELIANCE.NS"])
    assert "duplicate mappings" in str(exc.value)


def test_validate_universe_happy_path_reports_counts():
    out = validate_universe(["NSE:RELIANCE", "NASDAQ:ANET", "SPY"])
    assert out["requested"] == 3
    assert out["validated"] == 3
    assert [r["yahoo_symbol"] for r in out["resolved"]] == [
        "RELIANCE.NS", "ANET", "SPY",
    ]
