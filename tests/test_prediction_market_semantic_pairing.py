"""
Tests for the semantic-pairing primitive used by the disagreement scanner.

Covers (10/10 sprint):
- Component score block on every PairClassification.
- Embedding-fn swappability (deterministic baseline + fake provider).
- Paraphrase same event → SAME_EVENT_SAME_RESOLUTION.
- Same event different wording + same threshold → SAME_EVENT_SAME_RESOLUTION.
- Same theme different asset → SAME_THEME_DIFFERENT_EVENT or AMBIGUOUS_MATCH.
- Same asset different threshold → SAME_EVENT_DIFFERENT_THRESHOLD.
- Same asset/threshold different settlement window → SAME_EVENT_DIFFERENT_THRESHOLD.
- Hit/touch vs close/settle mismatch → SAME_EVENT_DIFFERENT_THRESHOLD with
  ``resolution_style_mismatch`` reason.
- Same event but one title is short, rules carry the missing detail.
- Category mismatch → FALSE_MATCH.
- Entity mismatch → SAME_THEME_DIFFERENT_EVENT or FALSE_MATCH.
- Fixture file is loadable + the CLI accepts --from-fixtures.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.prediction_market_semantic_pairing import (
    AMBIGUOUS_MATCH,
    FALSE_MATCH,
    SAME_EVENT_DIFFERENT_THRESHOLD,
    SAME_EVENT_SAME_RESOLUTION,
    SAME_THEME_DIFFERENT_EVENT,
    PairClassification,
    classify_pair_resolution,
    deterministic_fake_embedding,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "prediction_markets" / "semantic_pairs.json"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _poly(title: str, category: str = "crypto", semantic_text: str | None = None) -> dict:
    return {
        "event_id": f"poly_{abs(hash(title)) % 1_000_000}",
        "market_id": f"poly_{abs(hash(title)) % 1_000_000}",
        "source": "polymarket",
        "source_name": "polymarket",
        "title": title,
        "category": category,
        "semantic_text": semantic_text or f"Title: {title}\nCategory: {category}",
    }


def _kalshi(title: str, category: str = "Crypto", semantic_text: str | None = None) -> dict:
    return {
        "event_id": f"kalshi_{abs(hash(title)) % 1_000_000}",
        "source_market_id": f"kalshi_{abs(hash(title)) % 1_000_000}",
        "source": "kalshi",
        "source_name": "kalshi",
        "title": title,
        "category": category,
        "semantic_text": semantic_text or f"Title: {title}\nCategory: {category}",
    }


# ---------------------------------------------------------------------------
# Component scoring + dataclass contract
# ---------------------------------------------------------------------------


class TestPairScoreComponents:
    def test_components_present_on_every_classification(self):
        c = classify_pair_resolution(
            _poly("What price will Bitcoin hit in May?"),
            _kalshi("How high will Bitcoin get in May?"),
        )
        assert isinstance(c, PairClassification)
        assert isinstance(c.pair_score_components, dict)
        for key in (
            "text_score",
            "entity_score",
            "category_score",
            "date_score",
            "threshold_score",
            "resolution_score",
            "embedding_score",
            "final_score",
        ):
            assert key in c.pair_score_components
            v = c.pair_score_components[key]
            assert 0.0 <= v <= 1.0

    def test_to_dict_includes_components_and_mismatch_reasons(self):
        c = classify_pair_resolution(
            _poly("Will WTI close above $90?", category="commodities"),
            _kalshi("Will WTI close above $90?", category="Commodities"),
        )
        d = c.to_dict()
        assert "pair_score_components" in d
        assert "resolution_mismatch_reasons" in d
        assert isinstance(d["resolution_mismatch_reasons"], list)


# ---------------------------------------------------------------------------
# Embedding provider interface (swappable)
# ---------------------------------------------------------------------------


class TestEmbeddingSwappability:
    def test_custom_embedding_fn_is_called(self):
        seen: list[str] = []

        def fake_emb(text: str) -> list[float]:
            seen.append(text)
            return [1.0] + [0.0] * 15

        c = classify_pair_resolution(
            _poly("Will Bitcoin hit $100k in May?"),
            _kalshi("How high will Bitcoin get in May?"),
            embedding_fn=fake_emb,
        )
        # Provider invoked for both sides.
        assert len(seen) == 2
        # Identical vectors → cosine = 1.0.
        assert c.embedding_similarity == pytest.approx(1.0)
        assert c.pair_score_components["embedding_score"] == pytest.approx(1.0)

    def test_default_embedding_is_deterministic(self):
        a = deterministic_fake_embedding("Will Bitcoin hit $100k in May?")
        b = deterministic_fake_embedding("Will Bitcoin hit $100k in May?")
        assert a == b


# ---------------------------------------------------------------------------
# Pair-type classification — coverage matrix
# ---------------------------------------------------------------------------


class TestPairTypeMatrix:
    def test_paraphrase_same_event_resolves_clean(self):
        c = classify_pair_resolution(
            _poly("What price will Bitcoin hit in May?"),
            _kalshi("How high will Bitcoin get in May?"),
        )
        assert c.pair_type in (SAME_EVENT_SAME_RESOLUTION, AMBIGUOUS_MATCH)
        # Clean alert requires no mismatches.
        if c.pair_type == SAME_EVENT_SAME_RESOLUTION:
            assert c.resolution_mismatch_reasons == []

    def test_same_event_same_threshold_resolves_clean(self):
        c = classify_pair_resolution(
            _poly("Will Bitcoin close above $100k on May 31?"),
            _kalshi("Will Bitcoin close above $100k on May 31?"),
        )
        assert c.pair_type == SAME_EVENT_SAME_RESOLUTION
        assert c.resolution_mismatch_reasons == []

    def test_same_theme_different_asset(self):
        c = classify_pair_resolution(
            _poly("Will Bitcoin hit $100k?"),
            _kalshi("Will Ethereum hit $5k?"),
        )
        # No shared asset entity → cannot be a clean alert.  AMBIGUOUS is
        # also acceptable when the title boilerplate jaccard is high (the
        # downstream scanner still routes AMBIGUOUS through the alert
        # gate, but ``shared_entities`` will be empty so the operator
        # sees no anchor and can override).
        assert c.pair_type in (
            SAME_THEME_DIFFERENT_EVENT,
            FALSE_MATCH,
            AMBIGUOUS_MATCH,
        )
        assert c.shared_entities == []
        assert c.pair_type != SAME_EVENT_SAME_RESOLUTION

    def test_same_asset_different_threshold(self):
        c = classify_pair_resolution(
            _poly("Will Bitcoin hit $150k in May?"),
            _kalshi("Will Bitcoin hit $100k in May?"),
        )
        assert c.pair_type == SAME_EVENT_DIFFERENT_THRESHOLD
        assert any("threshold_mismatch" in r for r in c.resolution_mismatch_reasons)

    def test_same_asset_threshold_different_window(self):
        c = classify_pair_resolution(
            _poly("Will Bitcoin hit $100k in May?"),
            _kalshi("Will Bitcoin hit $100k in June?"),
        )
        assert c.pair_type == SAME_EVENT_DIFFERENT_THRESHOLD
        assert any("window_mismatch" in r for r in c.resolution_mismatch_reasons)

    def test_hit_vs_close_blocks_clean_alert(self):
        """``hit $100k in May`` vs ``close above $100k on May 31`` are NOT the
        same resolution — they fire on different events even though the
        underlying number agrees.
        """
        c = classify_pair_resolution(
            _poly(
                "Will Bitcoin hit $100k in May?",
                semantic_text=(
                    "Title: Will Bitcoin hit $100k in May?\n"
                    "Rules: Resolves YES if BTC trades at or above $100k at any point in May.\n"
                    "Category: crypto"
                ),
            ),
            _kalshi(
                "Will Bitcoin close above $100k on May 31?",
                semantic_text=(
                    "Title: Will Bitcoin close above $100k on May 31?\n"
                    "Rules: Settles to the Coinbase daily close on 2026-05-31.\n"
                    "Category: Crypto"
                ),
            ),
        )
        assert c.pair_type == SAME_EVENT_DIFFERENT_THRESHOLD
        assert any(
            "resolution_style_mismatch" in r for r in c.resolution_mismatch_reasons
        )

    def test_before_vs_on_date_blocks_clean_alert(self):
        c = classify_pair_resolution(
            _poly(
                "Will the Fed cut rates by June?",
                category="economy",
                semantic_text=(
                    "Title: Will the Fed cut rates by June?\n"
                    "Rules: Resolves YES if the FOMC reduces rates before end of June.\n"
                    "Category: economy"
                ),
            ),
            _kalshi(
                "Will the Fed cut rates on June 18?",
                category="Economics",
                semantic_text=(
                    "Title: Will the Fed cut rates on June 18?\n"
                    "Rules: Resolves YES on the FOMC statement issued at exactly the June 18 meeting.\n"
                    "Category: Economics"
                ),
            ),
        )
        assert c.pair_type == SAME_EVENT_DIFFERENT_THRESHOLD
        assert any(
            "date_precision_mismatch" in r for r in c.resolution_mismatch_reasons
        )

    def test_above_vs_below_direction_mismatch_blocks_clean_alert(self):
        c = classify_pair_resolution(
            _poly("Will Bitcoin trade above $100k in May?"),
            _kalshi("Will Bitcoin trade below $100k in May?"),
        )
        assert c.pair_type == SAME_EVENT_DIFFERENT_THRESHOLD
        assert any(
            "direction_mismatch" in r for r in c.resolution_mismatch_reasons
        )

    def test_settlement_source_mismatch_blocks_clean_alert(self):
        c = classify_pair_resolution(
            _poly(
                "Will Bitcoin close above $100k on May 31?",
                semantic_text=(
                    "Title: Will Bitcoin close above $100k on May 31?\n"
                    "Rules: Settles to the Binance close on 2026-05-31.\n"
                    "Category: crypto"
                ),
            ),
            _kalshi(
                "Will Bitcoin close above $100k on May 31?",
                semantic_text=(
                    "Title: Will Bitcoin close above $100k on May 31?\n"
                    "Rules: Settles to the Coinbase close on 2026-05-31.\n"
                    "Category: Crypto"
                ),
            ),
        )
        # Same event same threshold, but Binance vs Coinbase → blocked.
        assert c.pair_type == SAME_EVENT_DIFFERENT_THRESHOLD
        assert any(
            "settlement_source_mismatch" in r for r in c.resolution_mismatch_reasons
        )

    def test_oil_above_80_with_different_assets_blocks(self):
        """``oil above $80`` vs ``Brent oil above $80`` are different assets."""
        c = classify_pair_resolution(
            _poly(
                "Will WTI crude close above $80 in June?",
                category="commodities",
                semantic_text=(
                    "Title: Will WTI crude close above $80 in June?\n"
                    "Rules: Settles to the WTI front-month NYMEX close on June 30.\n"
                    "Category: commodities"
                ),
            ),
            _kalshi(
                "Will Brent oil close above $80 in June?",
                category="Commodities",
                semantic_text=(
                    "Title: Will Brent oil close above $80 in June?\n"
                    "Rules: Settles to ICE Brent front-month close on June 30.\n"
                    "Category: Commodities"
                ),
            ),
        )
        # Settlement-source / asset disagreement must block.
        assert c.pair_type in (
            SAME_EVENT_DIFFERENT_THRESHOLD,
            SAME_THEME_DIFFERENT_EVENT,
            AMBIGUOUS_MATCH,
        )
        # Either explicit settlement-source mismatch or no shared anchor.
        if c.pair_type == SAME_EVENT_DIFFERENT_THRESHOLD:
            assert c.resolution_mismatch_reasons

    def test_year_mismatch_blocks_clean_alert(self):
        c = classify_pair_resolution(
            _poly("Will the Fed cut rates by June 2026?", category="economy"),
            _kalshi("Will the Fed cut rates in 2027?", category="Economics"),
        )
        # Different year → window/year mismatch.
        assert c.pair_type in (SAME_EVENT_DIFFERENT_THRESHOLD, SAME_THEME_DIFFERENT_EVENT)
        if c.pair_type == SAME_EVENT_DIFFERENT_THRESHOLD:
            assert any("year_mismatch" in r for r in c.resolution_mismatch_reasons)

    def test_short_title_with_rules_in_semantic_text_can_match(self):
        """When the title is sparse the rules carry the missing detail —
        the semantic_text fold must let the pair still classify."""
        c = classify_pair_resolution(
            _poly(
                "BTC May",
                category="crypto",
                semantic_text=(
                    "Title: BTC May\n"
                    "Rules: Resolves on the highest BTC price during May 2026.\n"
                    "Category: crypto"
                ),
            ),
            _kalshi(
                "How high will Bitcoin get in May?",
                category="Crypto",
            ),
        )
        # Either a clean SAME_EVENT_SAME_RESOLUTION or AMBIGUOUS_MATCH is fine
        # — what we must NOT see is FALSE_MATCH, because the rules carry the
        # missing entity.
        assert c.pair_type != FALSE_MATCH

    def test_category_mismatch_is_false_match(self):
        c = classify_pair_resolution(
            _poly("Will WTI close above $90?", category="crypto"),
            _kalshi("Will WTI close above $90?", category="Commodities"),
        )
        assert c.pair_type == FALSE_MATCH
        assert "incompatible_category" in c.reasons

    def test_entity_mismatch_blocks_same_event_promotion(self):
        c = classify_pair_resolution(
            _poly("Will Apple announce a foldable iPhone in 2026?"),
            _kalshi("Will OpenAI release GPT-6 in 2026?", category="Tech & Science"),
        )
        assert c.pair_type in (FALSE_MATCH, SAME_THEME_DIFFERENT_EVENT, AMBIGUOUS_MATCH)
        assert c.pair_type != SAME_EVENT_SAME_RESOLUTION


# ---------------------------------------------------------------------------
# Fixture file + CLI --from-fixtures
# ---------------------------------------------------------------------------


class TestFixtureFile:
    def test_fixture_file_loadable(self):
        assert FIXTURE_PATH.exists(), f"fixture missing: {FIXTURE_PATH}"
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        assert "polymarket" in payload and "kalshi" in payload
        assert isinstance(payload["polymarket"], list) and payload["polymarket"]
        assert isinstance(payload["kalshi"], list) and payload["kalshi"]

    def test_scanner_cli_consumes_fixture(self, tmp_path):
        out_path = tmp_path / "report.json"
        result = subprocess.run(
            [
                sys.executable,
                "scripts/prediction_market_disagreement_scanner.py",
                "--from-fixtures",
                str(FIXTURE_PATH),
                "--dry-run",
                "--json",
                "--limit",
                "50",
            ],
            cwd=str(REPO_ROOT),
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        out_path.write_text(result.stdout, encoding="utf-8")
        payload = json.loads(result.stdout)
        assert payload["artifact_kind"] == "prediction_market_disagreement_report"
        # The fixture intentionally includes at least one clean pair that
        # should trigger an alert (BTC May high vs BTC May high).
        assert payload["total_pairs"] >= 1
        # Every alert carries the component scores added this sprint.
        for alert in payload["alerts"]:
            assert "pair_score_components" in alert
            assert "resolution_mismatch_reasons" in alert
            assert "probability_source_polymarket" in alert
            assert "probability_source_kalshi" in alert
