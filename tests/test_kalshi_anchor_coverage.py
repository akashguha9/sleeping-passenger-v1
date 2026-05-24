"""
Anchor coverage for the Kalshi live-enrichment layer.

Locks in every conservative anchor added by the 10/10 sprint and proves
that the corresponding hard-rejection paths still hold.

Two contracts under test
------------------------
1. Each positive anchor maps an unambiguous title into the correct
   canonical Kalshi category.  Each test row encodes the *operator's
   intent*: a market with this title should be enrichable.

2. Each negative anchor proves the symmetric guard:
     - sports / entertainment / weather / lifestyle titles must hard-reject
       even when a weak positive anchor (a stock ticker, "election", ...)
       appears in the same string.
     - generic words like ``will``, ``price``, ``market``, ``event``,
       ``high``, ``low`` must NOT silently classify into Finance/Crypto/etc.

No network is touched.  The adapter --show-rejected flag is also covered
end-to-end via the mock fixture set.
"""
from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from scripts.kalshi_normalizer import (
    classify_kalshi_category,
    infer_kalshi_category,
)


# ---------------------------------------------------------------------------
# Positive anchors — each new conservative anchor must map.
# ---------------------------------------------------------------------------


_POSITIVE_TITLE_CASES: tuple[tuple[str, str], ...] = (
    # Crypto
    ("Will Bitcoin close above $100,000 in 2026?", "Crypto"),
    ("Will Ethereum hit $5k by year end?", "Crypto"),
    ("Will Solana market cap exceed $200B by Q2?", "Crypto"),
    ("Will XRP regain its 2018 high?", "Crypto"),
    ("Will Tether ever break its dollar peg again?", "Crypto"),
    ("Will any stablecoin face an SEC enforcement action this year?", "Crypto"),
    # Commodities
    ("Will WTI crude close above $90 by end of June?", "Commodities"),
    ("Will Brent crude reach $100 in 2026?", "Commodities"),
    ("Will natural gas spot trade above $4 this winter?", "Commodities"),
    ("Will gold price hit $2,500 by quarter end?", "Commodities"),
    ("Will copper price climb above $10,000/ton?", "Commodities"),
    ("Will OPEC announce a production cut at the next meeting?", "Commodities"),
    # Economics
    ("Will the CPI report show 3% or higher inflation in May?", "Economics"),
    ("Will the Fed cut at the June FOMC meeting?", "Economics"),
    ("Will the unemployment rate stay below 4% this print?", "Economics"),
    ("Will the next jobs report beat consensus?", "Economics"),
    ("Will mortgage rate drop below 6% by year end?", "Economics"),
    ("Will GDP growth exceed 2% in Q2?", "Economics"),
    # Finance
    ("Will the S&P 500 close above 6,000 in May?", "Finance"),
    ("Will the Dow Jones hit a new all-time high?", "Finance"),
    ("Will a new tech IPO trade above its offering price on day one?", "Finance"),
    ("Will any ETF launch with $1B AUM in week one?", "Finance"),
    # Tech & Science
    ("Will NVIDIA report Q1 EPS above $5?", "Tech & Science"),
    ("Will OpenAI announce a GPT model upgrade this quarter?", "Tech & Science"),
    ("Will SpaceX launch a Starlink batch in May?", "Tech & Science"),
    ("Will any quantum computer demonstrate factoring 2048-bit RSA?", "Tech & Science"),
    # Elections / Politics
    ("Will there be a presidential primary this month?", "Elections"),
    ("Will Congress vote on the budget bill before recess?", "Politics"),
    ("Will the government shutdown extend past Friday?", "Politics"),
    ("Will the President announce new tariff on China this week?", "Politics"),
)


@pytest.mark.parametrize("title,expected_category", _POSITIVE_TITLE_CASES)
def test_positive_anchors_classify_correctly(title: str, expected_category: str) -> None:
    """Every conservative positive anchor must map its representative title."""
    cat, reason = infer_kalshi_category({"title": title})
    assert cat == expected_category, (
        f"expected {expected_category!r} for title {title!r}, got {cat!r} ({reason})"
    )
    # The classification reason must reference *which* layer fired so
    # operators can audit the rule.
    assert reason.startswith(("keyword_anchor:", "ticker_prefix:", "explicit_category", "event_payload_category", "tag_match:")), reason


# ---------------------------------------------------------------------------
# Negative anchors — hard-reject must not be rescued by weak positives.
# ---------------------------------------------------------------------------


_HARD_REJECT_CASES: tuple[str, ...] = (
    # Sports — even with a "stock"-adjacent word in the title.
    "Will the Lakers win the NBA Finals?",
    "Will the New York Yankees clinch the World Series?",
    "Will Manchester City win the Premier League?",
    "Will the NCAA basketball tournament have an undefeated champion?",
    "Will the next Super Bowl be a blowout?",
    "Will the next Wimbledon final go five sets?",
    # Entertainment / awards
    "Will any movie pass $1B at the box office this month?",
    "Will the Oscars host run the show solo?",
    "Will any pop star album release top the Billboard chart this week?",
    # Celebrity / culture
    "Will Taylor Swift announce a new concert tour this quarter?",
    "Will Kanye reconcile in Kardashian Bitcoin drama this month?",  # NOTE: includes "bitcoin"
    # Weather (non-economic)
    "Will a hurricane make US landfall this week?",
    "Will the next snowstorm break a snowfall record?",
    # Lifestyle / reality TV
    "Will the bachelor finale set a viewership record?",
)


@pytest.mark.parametrize("title", _HARD_REJECT_CASES)
def test_hard_reject_anchors_block_classification(title: str) -> None:
    """Sports/entertainment/weather/lifestyle markets MUST stay rejected.

    Includes the deliberately-tricky "Will Kanye reconcile in Kardashian
    Bitcoin drama..." case where a weak positive anchor (``bitcoin``)
    appears in a strongly-rejected celebrity title — the hard reject must
    fire first.
    """
    cat, reason = infer_kalshi_category({"title": title})
    assert cat is None, (
        f"hard-reject anchor failed for title {title!r}: got {cat!r} ({reason})"
    )
    assert reason.startswith("rejected_keyword:") or reason in {
        "no_confident_match",
        "missing_category",
    }, reason


# ---------------------------------------------------------------------------
# Generic-word safety — these MUST NOT classify on weak words alone.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        # Generic verbs / nouns the operator listed explicitly as "do not classify".
        "Will the event happen this month?",
        "Will the price reach a new high?",
        "Will the market open higher?",
        "Will the low be tested?",
        "Will the high break this week?",
    ],
)
def test_generic_words_do_not_classify(title: str) -> None:
    cat, reason = infer_kalshi_category({"title": title})
    assert cat is None, f"generic word leaked into category for {title!r}: {cat} ({reason})"


# ---------------------------------------------------------------------------
# Allowed-then-rejected: an explicit rejected category beats a positive title.
# ---------------------------------------------------------------------------


def test_explicit_rejected_category_overrides_title_keyword() -> None:
    """If the upstream category is e.g. 'Sports', a bitcoin-shaped title must NOT promote."""
    cat, reason = infer_kalshi_category(
        {"title": "Will Bitcoin win Sports MVP?", "category": "Sports"}
    )
    assert cat is None
    assert reason.startswith("explicit_rejected_category:")


def test_classify_category_still_rejects_unknown_categories() -> None:
    """The strict allowlist gate (classify_kalshi_category) must stay strict."""
    result = classify_kalshi_category("Astrology")
    assert result["allowed"] is False
    result = classify_kalshi_category("Sports")
    assert result["allowed"] is False


# ---------------------------------------------------------------------------
# Adapter --show-rejected diagnostics
# ---------------------------------------------------------------------------


@contextmanager
def _capture_stdout(capsys):
    yield capsys


def test_show_rejected_diagnostics_emits_rows(capsys, monkeypatch) -> None:
    """The adapter CLI with --show-rejected N emits per-row diagnostics
    in JSON output and never persists to canonical SQLite.
    """
    from scripts import kalshi_market_data_adapter as adapter

    rc = adapter.run(["--json", "--mock", "--limit", "10", "--show-rejected", "5"])
    assert rc == 0
    out, _err = capsys.readouterr()
    report = json.loads(out)

    # The mock fixture set includes one rejected Sports row.
    assert report["rejected_count"] >= 1
    diagnostics = report.get("rejected_diagnostics", [])
    assert isinstance(diagnostics, list)
    assert len(diagnostics) >= 1
    sample = diagnostics[0]
    for key in ("title", "ticker", "rejection_reason", "raw_category", "tags"):
        assert key in sample, f"diagnostic missing key {key}: {sample}"
    # Never persisted under any state.
    assert report["events_persisted"] == 0
    assert report["write_mode"] is False


def test_show_rejected_default_zero_omits_diagnostics(capsys) -> None:
    """Without --show-rejected the per-row block must be empty."""
    from scripts import kalshi_market_data_adapter as adapter

    rc = adapter.run(["--json", "--mock", "--limit", "10"])
    assert rc == 0
    out, _err = capsys.readouterr()
    report = json.loads(out)
    assert report.get("rejected_diagnostics", []) == []


# ---------------------------------------------------------------------------
# Closeout invariant — low accepted_count is correct when the live universe
# is dominated by rejected categories.  Success is *safe* acceptance plus
# *reasoned* rejection, not a high acceptance ratio.
# ---------------------------------------------------------------------------


def test_sports_dominated_universe_yields_low_accepted_count(capsys) -> None:
    """Hand the adapter a payload made almost entirely of sports markets.
    Expectation: a tiny accepted_count alongside an honest rejection
    summary — never a forced acceptance.  This guards against future
    'recall tuning' that quietly loosens the allowlist to pump numbers."""
    from scripts import kalshi_market_data_adapter as adapter
    from unittest.mock import MagicMock, patch

    universe = {
        "markets": [
            {"ticker": "NBA-FINALS-2026", "title": "Will the Lakers win?", "category": "Sports", "yes_ask": 0.2},
            {"ticker": "NFL-MVP-2026", "title": "Will Mahomes win MVP?", "category": "Sports", "yes_ask": 0.3},
            {"ticker": "MLB-WS-2026", "title": "Will the Yankees win World Series?", "category": "Sports", "yes_ask": 0.1},
            {"ticker": "HUR-CAT5-2026", "title": "Will a hurricane be Category 5?", "category": "Weather", "yes_ask": 0.15},
            {"ticker": "OSCAR-PIC-2026", "title": "Will the Best Picture be a sequel?", "category": "Entertainment", "yes_ask": 0.4},
            # ONE bona-fide approved market so accepted_count > 0 stays
            # achievable — this is the operator's "did the allowlist still
            # accept the right kind of thing" sanity check.
            {"ticker": "FED-CUT-JUN-2026", "title": "Will the Fed cut at June FOMC?", "category": "Economics", "yes_ask": 0.31},
        ]
    }
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = universe
    resp.raise_for_status.return_value = None

    with patch("requests.get", return_value=resp):
        rc = adapter.run(["--json", "--limit", "10", "--show-rejected", "10"])
    assert rc == 0
    out, _err = capsys.readouterr()
    report = json.loads(out)

    # Low acceptance is the *correct* outcome, not a bug.
    assert report["fetched_count"] == 6
    assert report["accepted_count"] == 1, (
        "only the Economics row should pass the allowlist — a higher number "
        "means the allowlist has silently loosened"
    )
    assert report["rejected_count"] == 5
    # Rejection reasons must be present and itemised so operators can audit
    # *why* nothing else was accepted.
    reasons = report.get("rejected_category_reasons") or {}
    assert reasons, "rejected category reasons must be itemised"
    # And the per-row diagnostics must surface ticker/title/reason for each
    # rejection so the operator can verify the call.
    diagnostics = report.get("rejected_diagnostics") or []
    assert len(diagnostics) == 5
    for entry in diagnostics:
        assert entry.get("rejection_reason"), entry
        assert entry.get("title") or entry.get("ticker"), entry
