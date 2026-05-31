"""Real-Forward Outcome Maturation Sprint — Phase 7 runbook tests.

The daily operator runbook must exist, list the maturity scanner and daily
runner commands, warn against backdating and premature calibration claims, and
contain no execution language.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_RUNBOOK = Path(__file__).resolve().parents[1] / "docs" / "REAL_FORWARD_DAILY_RUNBOOK.md"


@pytest.fixture(scope="module")
def text() -> str:
    return _RUNBOOK.read_text(encoding="utf-8")


def test_runbook_exists():
    assert _RUNBOOK.exists()
    assert _RUNBOOK.stat().st_size > 0


def test_runbook_lists_maturity_scanner(text):
    assert "scripts/forward_outcome_maturity_scanner.py" in text


def test_runbook_lists_daily_outcome_runner(text):
    assert "scripts/run_daily_outcome_maturation.py" in text
    assert "--write" in text


def test_runbook_warns_no_backdating(text):
    low = text.lower()
    assert "do not backdate" in low
    assert "do not run with fake dates" in low


def test_runbook_warns_no_claim_below_200(text):
    low = text.lower()
    assert "n=200" in low
    assert "do not claim calibration below n=200" in low


def test_runbook_warns_stop_when_nothing_due(text):
    assert "n_due_forward = 0" in text.lower()


def test_runbook_says_push_code_only(text):
    low = text.lower()
    assert "push code only" in low


def test_runbook_contains_no_execution_language(text):
    low = text.lower()
    for forbidden in (
        "place order", "execute trade", "auto-trade", "buy now", "sell now",
        "real-money ready: true",
    ):
        assert forbidden not in low
    # The invariants must affirm the locked, advisory-only posture.
    assert "execution_gate = locked" in low
    assert "broker_api_called = false" in low


def test_runbook_lists_calibration_and_bundle_commands(text):
    assert "scripts/real_calibration_evidence.py --write" in text
    assert "scripts/real_evidence_bundle.py --write" in text
