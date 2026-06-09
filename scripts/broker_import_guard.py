"""H2: runtime broker-import guard.

The repo's no-broker invariant was previously proven only by static AST
tests (no forbidden routes/functions defined in this codebase).  Static
proof cannot see a transitively imported broker SDK at runtime.  This
guard makes broker ABSENCE a runtime invariant: at API-server import and
again at startup, it scans ``sys.modules`` and raises ``RuntimeError`` if
any known broker/execution SDK has been loaded into the process.

This module performs no imports of the forbidden SDKs itself, makes no
network calls, and grants no execution permission — it can only refuse
to run.
"""
from __future__ import annotations

import sys
from typing import Iterable

# Known broker / order-execution SDK top-level module names.  Matching is
# on the top-level package: ``ccxt`` and ``ccxt.binance`` both trip.
FORBIDDEN_BROKER_MODULES: tuple[str, ...] = (
    "alpaca",
    "alpaca_trade_api",
    "ib_insync",
    "ibapi",
    "ccxt",
    "tradier",
    "robin_stocks",
)


def detect_broker_modules(modules: Iterable[str] | None = None) -> list[str]:
    """Return the sorted list of loaded forbidden broker modules."""
    names = modules if modules is not None else sys.modules.keys()
    hits: set[str] = set()
    for name in names:
        top = name.split(".", 1)[0]
        if top in FORBIDDEN_BROKER_MODULES:
            hits.add(name)
    return sorted(hits)


def assert_no_broker_modules(modules: Iterable[str] | None = None) -> None:
    """Raise RuntimeError if any broker SDK is loaded.  Fail closed."""
    hits = detect_broker_modules(modules)
    if hits:
        raise RuntimeError(
            "ADVISORY-ONLY VIOLATION: broker/execution SDK(s) loaded in this "
            f"process: {hits}. This system never talks to a broker — refusing "
            "to run. (execution_gate=LOCKED, broker_api_called=False)"
        )
