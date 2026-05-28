"""Static scan of the Kronos frontend card for safe / forbidden wording.

Mirrors ``tests/test_customer_frontend_language.py`` — a plain lowercase
substring scan of the component source guards the wording.  The Kronos
card is advisory-only and must never render execution language; it must
surface the no-broker safety banner and the disabled/no-data line.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CARD_PATH = (
    _REPO_ROOT / "frontend" / "src" / "components" / "KronosEvidenceCard.tsx"
)

# Forbidden execution phrases.  Note: the card legitimately uses the word
# "execution" inside "Human execution required" (a denial), so we only ban
# the affirmative execution-instruction phrases, not the bare word.
FORBIDDEN_PHRASES = (
    "place order",
    "place_order",
    "execute trade",
    "execute_trade",
    "auto trade",
    "auto-trade",
    "auto_trade",
    "broker connected",
    "broker_connected",
    "buy now",
    "sell now",
    "ai executes",
    "ai decides",
    "guaranteed return",
    "place an order",
    "submit order",
)

REQUIRED_SAFE_PHRASES = (
    "kronos price-path evidence",
    "evidence only. human execution required. no broker action.",
    "no decision impact",
)


@pytest.fixture(scope="module")
def card_source() -> str:
    assert _CARD_PATH.exists(), f"Kronos card missing: {_CARD_PATH}"
    return _CARD_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_no_forbidden_phrase_in_kronos_card(card_source, phrase):
    assert phrase not in card_source.lower(), (
        f"Kronos card contains forbidden phrase {phrase!r}"
    )


def test_required_safe_phrases_present(card_source):
    lower = card_source.lower()
    for phrase in REQUIRED_SAFE_PHRASES:
        assert phrase in lower, f"Kronos card missing safe phrase {phrase!r}"


def test_only_allowed_status_labels(card_source):
    # No execution verbs ever appear as a status label in the card.
    upper = card_source.upper()
    for forbidden in ("PLACE_ORDER", "AUTO_TRADE", "EXIT_NOW"):
        assert forbidden not in upper


def test_kronos_card_mounted_or_truthfully_declared(card_source):
    """Required test 8: the card is either mounted in a real page, or the
    component truthfully declares it is NOT mounted yet.

    This prevents claiming a runtime/user-facing effect that does not exist.
    """
    app_dir = _REPO_ROOT / "frontend" / "src"
    importers: list[str] = []
    for tsx in app_dir.rglob("*.tsx"):
        if tsx.resolve() == _CARD_PATH.resolve():
            continue
        if "__tests__" in tsx.parts:
            continue
        text = tsx.read_text(encoding="utf-8")
        if "KronosEvidenceCard" in text:
            importers.append(str(tsx.relative_to(_REPO_ROOT)))

    if importers:
        # Genuinely mounted somewhere — that is acceptable and truthful.
        return
    # Not mounted anywhere → the component must say so explicitly.
    assert "NOT MOUNTED YET" in card_source.upper(), (
        "Kronos card is not imported by any page and does not declare "
        "'NOT MOUNTED YET'; fix the component comment or mount it."
    )
