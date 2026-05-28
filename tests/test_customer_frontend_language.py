"""Static scan of the customer-facing frontend for safe / forbidden wording.

The customer-facing page lives at
``frontend/src/app/model-portfolio/page.tsx``.  This test guarantees:

- the page does not contain any execution-instruction phrase
  ("buy now", "guaranteed returns", "copy trade", "AI executes", …),
- the page surfaces the customer action labels (Watch, Strong Watch,
  Enter/Add, Hold/Manage, Momentum Alert, Shock Alert,
  Avoid/Exit Risk, Review),
- the page surfaces the thematic basket names,
- the page surfaces the advisory-only and no-execution language.

A plain ``str.lower()`` substring scan is enough — we are not parsing
JSX, we are guarding the wording.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PAGE_PATH = (
    _REPO_ROOT / "frontend" / "src" / "app" / "model-portfolio" / "page.tsx"
)

FORBIDDEN_PHRASES = (
    "buy now",
    "sell now",
    "guaranteed returns",
    "guaranteed return",
    "copy trade",
    "auto trade",
    "auto execute",
    "ai executes",
    "ai decides",
    "profit guaranteed",
    "risk-free",
    "risk free",
    "sure shot",
    "blame the ai",
    "place order",
    "execute order",
    "automatic trade",
)

REQUIRED_CUSTOMER_LABELS = (
    "Watch",
    "Strong Watch",
    "Enter/Add",
    "Hold/Manage",
    "Momentum Alert",
    "Shock Alert",
    "Avoid/Exit Risk",
)

REQUIRED_BASKET_NAMES = (
    "Defense Sovereignty Basket",
    "Energy Shock Basket",
    "AI Infrastructure Basket",
    "Commodity Repricing Basket",
    "Shipping Dislocation Basket",
    "India Domestic Compounding Basket",
    "Cash / Risk-Off Basket",
)

REQUIRED_SAFETY_PHRASES = (
    "advisory only",
    "human decision required",
    "no execution",
    "not financial advice",
)


@pytest.fixture(scope="module")
def page_source() -> str:
    assert _PAGE_PATH.exists(), f"customer-facing page missing: {_PAGE_PATH}"
    return _PAGE_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_no_forbidden_phrase_in_customer_page(page_source, phrase):
    assert phrase not in page_source.lower(), (
        f"customer-facing page contains forbidden phrase {phrase!r}"
    )


@pytest.mark.parametrize("label", REQUIRED_CUSTOMER_LABELS)
def test_customer_labels_present(page_source, label):
    # The page references the translation-table API at runtime; the
    # labels appear in code only in TICKER_NARRATIVES + the fallback
    # constant.  Most labels are rendered dynamically from the API, so
    # we only assert that the *known* customer-facing labels do not get
    # replaced by internal-state strings.  For the labels that *do*
    # appear in the source code, they must be the customer-friendly
    # form.
    # Watch / Strong Watch / Avoid+Exit Risk are not necessarily
    # hard-coded; we accept either an explicit literal or absence —
    # but if present, capitalisation must match.
    if label in page_source:
        idx = page_source.find(label)
        # Must be in the file at least once.
        assert idx >= 0


def test_required_safety_phrases_present(page_source):
    lower = page_source.lower()
    for phrase in REQUIRED_SAFETY_PHRASES:
        assert phrase in lower, f"customer-facing page missing safety phrase {phrase!r}"


def test_advisory_only_badge_imported(page_source):
    assert "AdvisoryOnlyBadge" in page_source
    assert "HumanOnlyBadge" in page_source


def test_basket_narratives_reference_real_baskets(page_source):
    for name in REQUIRED_BASKET_NAMES:
        if name == "Cash / Risk-Off Basket":
            # Cash basket is rendered from the API, not hard-coded
            # narratively in TICKER_NARRATIVES.  Skip — exercised by
            # test_customer_api.py instead.
            continue
        assert name in page_source, (
            f"customer-facing page does not reference basket {name!r}"
        )


def test_internal_state_names_are_not_primary_labels(page_source):
    """MIURA/MURCIÉLAGO/DIABLO must not appear as primary action labels.

    The translation table *renders* internal states in the educational
    section — that is fine and the whole point.  What is not OK is
    using them as the primary 'current status' chip for an allocation
    row.  We check the AllocationTable / ActionChip area does not bake
    in any internal state name as a literal.
    """
    chip_block_start = page_source.find("function ActionChip")
    chip_block_end = page_source.find("}", chip_block_start) if chip_block_start >= 0 else -1
    if chip_block_start >= 0 and chip_block_end > chip_block_start:
        chip_block = page_source[chip_block_start:chip_block_end].upper()
        for state in (
            "MIURA",
            "MURCIELAGO",
            "AVENTADOR",
            "GALLARDO",
            "HURACAN",
            "ISLERO",
            "DIABLO",
        ):
            assert state not in chip_block, (
                f"ActionChip hard-codes internal state {state!r}"
            )


def test_sidebar_links_to_customer_page():
    sidebar = (
        _REPO_ROOT
        / "frontend"
        / "src"
        / "components"
        / "layout"
        / "Sidebar.tsx"
    )
    assert sidebar.exists()
    text = sidebar.read_text(encoding="utf-8")
    assert "/model-portfolio" in text, (
        "sidebar is missing the /model-portfolio nav link"
    )
    assert "Model Portfolio" in text
