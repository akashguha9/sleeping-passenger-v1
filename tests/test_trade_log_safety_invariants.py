"""Advisory-only safety invariants for the trade-log / discovery intelligence modules.

These modules are analytics + advisory classification ONLY.  They must never
introduce an execution surface: no broker imports, no order-placement language
in user-facing output, and the canonical advisory stamps must hold.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from scripts.google_sheet_schema import load_trade_log_csv
from scripts.outcome_maturity import summarize_maturity
from scripts.trade_log_metrics import build_report, render_text

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
CORE_MODULES = (
    "google_sheet_schema.py",
    "outcome_maturity.py",
    "trade_log_metrics.py",
)
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "trade_log_sample.csv"
REPORT = date(2026, 6, 2)

# Banned execution tokens (must not appear as instructions in output).
BANNED_OUTPUT_TOKENS = (
    "BUY NOW",
    "SELL NOW",
    "EXECUTE TRADE",
    "PLACE ORDER",
    "BROKER ORDER",
    "AUTO TRADE",
    "AUTONOMOUS EXECUTION",
)
# Genuine execution surfaces: broker SDK imports and order-placement calls.
# (The string ``broker_api_called`` is a *safety flag asserting False* and is
# intentionally NOT banned.)
BANNED_PATTERNS = (
    "import alpaca",
    "from alpaca",
    "import ib_insync",
    "import ccxt",
    "place_order(",
    "submit_order(",
    "cancel_order(",
    "broker.execute",
)


def test_no_broker_imports_in_core_modules():
    for name in CORE_MODULES:
        src = (SCRIPTS / name).read_text(encoding="utf-8").lower()
        for token in BANNED_PATTERNS:
            assert token not in src, f"{name} references forbidden execution surface {token!r}"


def test_report_text_has_no_execution_language():
    report = build_report(load_trade_log_csv(FIXTURE).rows, 4000.0, REPORT)
    text = render_text(report).upper()
    for token in BANNED_OUTPUT_TOKENS:
        assert token not in text


def test_report_safety_stamps_locked():
    report = build_report(load_trade_log_csv(FIXTURE).rows, 4000.0, REPORT)
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
    assert report["can_execute"] is False
    assert report["human_execution_required"] is True


def test_maturity_summary_safety_stamps_locked():
    summary = summarize_maturity(load_trade_log_csv(FIXTURE).rows, REPORT)
    assert summary["execution_gate"] == "LOCKED"
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0


def test_no_buy_sell_command_words_in_output():
    report = build_report(load_trade_log_csv(FIXTURE).rows, 4000.0, REPORT)
    text = render_text(report)
    # No imperative buy/sell command (the words may appear only inside neutral
    # labels, never as a command followed by a ticker/now).
    assert not re.search(r"\b(BUY|SELL)\s+(NOW|ORDER|\$?[A-Z]{2,5})\b", text.upper())
