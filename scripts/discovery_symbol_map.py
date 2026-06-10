"""DISC-B1: explicit exchange-prefix → Yahoo-suffix symbol mapping.

The operator's holdings/signals carry exchange-prefixed tickers
(``NSE:RELIANCE``, ``NASDAQ:ANET``) while every Yahoo-based tool in the
repo expects suffix form (``RELIANCE.NS``).  Before this module the
translation was implicit and a mismapped prefix risked silently fetching
the WRONG INSTRUMENT (e.g. ``LON:BARC`` interpreted as US ``BARC``).

Doctrine (fail loud, never guess):
* every symbol must resolve through the explicit table below;
* unknown prefixes raise :class:`SymbolResolutionError` — no silent
  drop, no pass-through guess;
* ambiguous prefixes (``TSE`` collides: Tokyo vs Toronto) are REFUSED
  with guidance instead of being guessed;
* plain symbols (no prefix) and already-suffixed Yahoo symbols pass
  through with their resolution path recorded.

Pure, dependency-free, no network.  Advisory stamps on every result.
RESULTS FIREWALL: this module is discovery tooling only — nothing here
is evidence of edge.
"""
from __future__ import annotations

import re
from typing import Any

# Exchange prefix → Yahoo suffix.  '' means US listing (no suffix).
EXCHANGE_TO_YAHOO_SUFFIX: dict[str, str] = {
    # United States
    "NASDAQ": "",
    "NYSE": "",
    "AMEX": "",
    "BATS": "",
    # India
    "NSE": ".NS",
    "BSE": ".BO",
    # United Kingdom
    "LON": ".L",
    "LSE": ".L",
    # Germany (XETRA)
    "ETR": ".DE",
    "XETRA": ".DE",
    "FRA": ".F",
    # Japan
    "TYO": ".T",
    "JPX": ".T",
    # South Korea
    "KRX": ".KS",
    "KOSPI": ".KS",
    "KOSDAQ": ".KQ",
    # Canada
    "TSX": ".TO",
    "TSXV": ".V",
    # Hong Kong / Taiwan / Australia (common in the securities master)
    "HKG": ".HK",
    "HKEX": ".HK",
    "TPE": ".TW",
    "TWSE": ".TW",
    "ASX": ".AX",
}

# Prefixes that are REAL but ambiguous across markets — refuse with
# guidance rather than guessing the wrong instrument.
AMBIGUOUS_PREFIXES: dict[str, str] = {
    "TSE": (
        "TSE is ambiguous (Tokyo Stock Exchange vs Toronto Stock "
        "Exchange). Use TYO:<sym> for Tokyo or TSX:<sym> for Toronto."
    ),
}

# Yahoo suffixes we recognise as already-resolved (pass-through).
_KNOWN_YAHOO_SUFFIXES = frozenset(
    {s for s in EXCHANGE_TO_YAHOO_SUFFIX.values() if s}
) | {".TW", ".SS", ".SZ", ".PA", ".AS", ".MI", ".SW", ".ST", ".OL", ".CO"}

_PLAIN_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")

_STAMPS = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}


class SymbolResolutionError(ValueError):
    """A symbol could not be resolved to an unambiguous Yahoo symbol."""


def resolve_symbol(raw: str) -> dict[str, Any]:
    """Resolve one operator symbol to its Yahoo form.  Fail loud.

    Returns ``{"input": ..., "yahoo_symbol": ..., "exchange": ...,
    "resolution": "prefix_mapped"|"already_suffixed"|"plain"}``.
    Raises :class:`SymbolResolutionError` for empty input, unknown
    prefixes, and ambiguous prefixes.
    """
    sym = (raw or "").strip().upper()
    if not sym:
        raise SymbolResolutionError("empty symbol")

    if ":" in sym:
        prefix, _, body = sym.partition(":")
        body = body.strip()
        if not body or not _PLAIN_SYMBOL_RE.match(body):
            raise SymbolResolutionError(f"malformed symbol body in {raw!r}")
        if prefix in AMBIGUOUS_PREFIXES:
            raise SymbolResolutionError(
                f"refusing ambiguous exchange prefix {prefix!r}: "
                + AMBIGUOUS_PREFIXES[prefix]
            )
        if prefix not in EXCHANGE_TO_YAHOO_SUFFIX:
            raise SymbolResolutionError(
                f"unknown exchange prefix {prefix!r} in {raw!r} — add it to "
                "EXCHANGE_TO_YAHOO_SUFFIX (scripts/discovery_symbol_map.py) "
                "after verifying the Yahoo suffix; symbols are NEVER guessed."
            )
        suffix = EXCHANGE_TO_YAHOO_SUFFIX[prefix]
        return {
            **_STAMPS,
            "input": raw,
            "exchange": prefix,
            "yahoo_symbol": f"{body}{suffix}",
            "resolution": "prefix_mapped",
        }

    if not _PLAIN_SYMBOL_RE.match(sym):
        raise SymbolResolutionError(f"malformed symbol {raw!r}")

    dot = sym.rfind(".")
    if dot > 0 and sym[dot:] in _KNOWN_YAHOO_SUFFIXES:
        return {
            **_STAMPS,
            "input": raw,
            "exchange": None,
            "yahoo_symbol": sym,
            "resolution": "already_suffixed",
        }
    return {
        **_STAMPS,
        "input": raw,
        "exchange": None,
        "yahoo_symbol": sym,
        "resolution": "plain",
    }


def validate_universe(symbols: list[str]) -> dict[str, Any]:
    """Resolve EVERY symbol before a run.  One failure fails the batch.

    Returns ``{"resolved": [results...], "requested": N, "validated": M}``
    or raises :class:`SymbolResolutionError` naming every unresolved
    symbol — a backtest must never silently drop or mis-fetch part of
    its universe.
    """
    resolved: list[dict[str, Any]] = []
    failures: list[str] = []
    for raw in symbols:
        try:
            resolved.append(resolve_symbol(raw))
        except SymbolResolutionError as exc:
            failures.append(f"{raw!r}: {exc}")
    if failures:
        raise SymbolResolutionError(
            "universe validation FAILED — unresolved symbols (fix or remove "
            "them; nothing was fetched):\n  " + "\n  ".join(failures)
        )
    # Duplicate Yahoo targets mean two inputs map to one instrument —
    # also a correctness failure (double-counted exposure in results).
    seen: dict[str, str] = {}
    dupes: list[str] = []
    for r in resolved:
        y = r["yahoo_symbol"]
        if y in seen:
            dupes.append(f"{r['input']!r} and {seen[y]!r} both map to {y}")
        else:
            seen[y] = r["input"]
    if dupes:
        raise SymbolResolutionError(
            "universe validation FAILED — duplicate mappings:\n  "
            + "\n  ".join(dupes)
        )
    return {
        **_STAMPS,
        "requested": len(symbols),
        "validated": len(resolved),
        "resolved": resolved,
    }
