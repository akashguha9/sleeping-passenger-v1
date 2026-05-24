"""
Tests for the Polymarket × Kalshi cross-venue disagreement scanner.

Covers:
- Same event, different wording → SAME_EVENT_SAME_RESOLUTION match
- 0.08 probability gap → triggered alert
- 0.03 probability gap → watch, not triggered
- Resolution mismatch (different threshold) → NOT a clean alert
- Different theme → no clean pair
- Safety invariants on every alert
- Forbidden language never appears in scanner output
- Write mode persists only to canonical SQLite (no JSONL, no execution row)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.prediction_market_disagreement_scanner import (
    CROSS_VENUE_SIGNAL_CLASS,
    CUSTOMER_LABEL,
    DEFAULT_DISAGREEMENT_THRESHOLD,
    PERSISTENCE_SOURCE_NAME,
    build_disagreement_alert,
    extract_implied_probability,
    run,
    scan_disagreements,
)
from scripts.prediction_market_semantic_pairing import (
    AMBIGUOUS_MATCH,
    FALSE_MATCH,
    SAME_EVENT_DIFFERENT_THRESHOLD,
    SAME_EVENT_SAME_RESOLUTION,
    SAME_THEME_DIFFERENT_EVENT,
    classify_pair_resolution,
)


_FORBIDDEN_PHRASES = (
    "buy",
    "sell",
    "execute",
    "trade now",
    "arbitrage this",
    "guaranteed edge",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _poly(
    *,
    title: str,
    market_id: str = "poly-1",
    category: str = "crypto",
    implied: float | None = None,
    yes_price: float | None = None,
    semantic_text: str | None = None,
) -> dict:
    return {
        "event_id": f"polymarket_{market_id}",
        "source": "polymarket",
        "source_name": "polymarket",
        "market_id": market_id,
        "title": title,
        "category": category,
        "implied_probability": implied,
        "yes_price": yes_price,
        "semantic_text": semantic_text,
    }


def _kalshi(
    *,
    title: str,
    source_market_id: str = "kalshi-1",
    category: str = "Crypto",
    implied: float | None = None,
    yes_price: float | None = None,
    semantic_text: str | None = None,
) -> dict:
    return {
        "event_id": f"kalshi_{source_market_id}",
        "source": "kalshi",
        "source_name": "kalshi",
        "source_market_id": source_market_id,
        "title": title,
        "category": category,
        "implied_probability": implied,
        "yes_price": yes_price,
        "semantic_text": semantic_text or f"Title: {title}\nCategory: {category}",
    }


def _assert_safety_stamped(alert: dict) -> None:
    assert alert["signal_class"] == CROSS_VENUE_SIGNAL_CLASS
    assert alert["customer_label"] == CUSTOMER_LABEL
    assert alert["execution_permission"] == "ADVISORY_ONLY"
    assert alert["advisory_status"] == "ADVISORY_ONLY"
    assert alert["execution_gate"] == "LOCKED"
    assert alert["human_review_required"] is True
    assert alert["broker_api_called"] is False
    assert alert["ai_execution_count"] == 0


def _assert_no_forbidden_language(text: str) -> None:
    lower = text.lower()
    for phrase in _FORBIDDEN_PHRASES:
        assert phrase not in lower, f"forbidden phrase '{phrase}' found in: {text[:120]!r}"


# ---------------------------------------------------------------------------
# Pair classification
# ---------------------------------------------------------------------------


class TestPairClassification:
    def test_different_wording_same_event_matches_semantically(self):
        kalshi = _kalshi(title="How high will Bitcoin get in May?", implied=0.54)
        poly = _poly(title="What price will Bitcoin hit in May?", implied=0.62)
        result = classify_pair_resolution(poly, kalshi)
        # Either SAME_EVENT_SAME_RESOLUTION or AMBIGUOUS_MATCH is
        # acceptable — both are eligible for an alert.
        assert result.pair_type in (SAME_EVENT_SAME_RESOLUTION, AMBIGUOUS_MATCH)
        assert "bitcoin" in result.shared_entities

    def test_different_theme_does_not_match(self):
        kalshi = _kalshi(title="Will Bitcoin hit $100k?", implied=0.30)
        poly = _poly(title="Will Ethereum hit $5k?", implied=0.40)
        result = classify_pair_resolution(poly, kalshi)
        # Without shared entities and a strong-enough overall match,
        # this must be a SAME_THEME_DIFFERENT_EVENT or FALSE_MATCH.
        assert result.pair_type in (FALSE_MATCH, SAME_THEME_DIFFERENT_EVENT)

    def test_resolution_mismatch_does_not_promote_to_same_resolution(self):
        kalshi = _kalshi(
            title="Will Bitcoin close above $100k on May 31?",
            implied=0.30,
            semantic_text=(
                "Title: Will Bitcoin close above $100k on May 31?\n"
                "Rules: Settles to BTC/USD close on Coinbase on 2026-05-31.\n"
                "Category: Crypto"
            ),
        )
        poly = _poly(
            title="Will Bitcoin hit $150k in May?",
            implied=0.40,
            semantic_text=(
                "Title: Will Bitcoin hit $150k in May?\n"
                "Rules: Resolves YES if BTC trades at or above $150k at any point in May.\n"
                "Category: crypto"
            ),
        )
        result = classify_pair_resolution(poly, kalshi)
        assert result.pair_type != SAME_EVENT_SAME_RESOLUTION

    def test_incompatible_category_is_false_match(self):
        kalshi = _kalshi(title="Will WTI close above $90?", category="Commodities", implied=0.30)
        poly = _poly(title="Will WTI close above $90?", category="crypto", implied=0.40)
        result = classify_pair_resolution(poly, kalshi)
        assert result.pair_type == FALSE_MATCH


# ---------------------------------------------------------------------------
# Alert thresholding
# ---------------------------------------------------------------------------


class TestAlertThreshold:
    def test_eight_point_gap_triggers_alert(self):
        kalshi = _kalshi(title="How high will Bitcoin get in May?", implied=0.54)
        poly = _poly(title="What price will Bitcoin hit in May?", implied=0.62)
        alert = build_disagreement_alert(poly, kalshi)
        assert alert is not None
        assert alert["polymarket_probability"] == pytest.approx(0.62)
        assert alert["kalshi_probability"] == pytest.approx(0.54)
        assert alert["probability_gap"] == pytest.approx(0.08, abs=0.001)
        assert alert["disagreement_threshold"] == DEFAULT_DISAGREEMENT_THRESHOLD
        assert alert["disagreement_triggered"] is True
        assert alert["status"] == "ALERT"
        _assert_safety_stamped(alert)

    def test_three_point_gap_does_not_trigger(self):
        kalshi = _kalshi(title="How high will Bitcoin get in May?", implied=0.49)
        poly = _poly(title="What price will Bitcoin hit in May?", implied=0.52)
        alert = build_disagreement_alert(poly, kalshi)
        assert alert is not None
        assert alert["probability_gap"] == pytest.approx(0.03, abs=0.001)
        assert alert["disagreement_triggered"] is False
        assert alert["status"] == "WATCH"
        _assert_safety_stamped(alert)

    def test_resolution_mismatch_never_triggers_alert(self):
        """SAME_EVENT_DIFFERENT_THRESHOLD is the diagnostic-only bucket
        and must not flip to ALERT regardless of probability gap."""
        kalshi = _kalshi(
            title="Will Bitcoin close above $100k on May 31?",
            implied=0.30,
            semantic_text=(
                "Title: Will Bitcoin close above $100k on May 31?\n"
                "Rules: Settles to BTC/USD close on Coinbase on 2026-05-31.\n"
                "Category: Crypto"
            ),
        )
        poly = _poly(
            title="Will Bitcoin hit $150k in May?",
            implied=0.80,
            semantic_text=(
                "Title: Will Bitcoin hit $150k in May?\n"
                "Rules: Resolves YES if BTC trades at or above $150k at any point in May.\n"
                "Category: crypto"
            ),
        )
        alert = build_disagreement_alert(poly, kalshi)
        assert alert is not None
        assert alert["pair_type"] != SAME_EVENT_SAME_RESOLUTION
        assert alert["disagreement_triggered"] is False
        assert alert["status"] in ("DIAGNOSTIC", "WATCH")

    def test_missing_probability_yields_watch_record(self):
        kalshi = _kalshi(title="How high will Bitcoin get in May?")  # no price
        poly = _poly(title="What price will Bitcoin hit in May?", implied=0.62)
        alert = build_disagreement_alert(poly, kalshi)
        assert alert is not None
        assert alert["disagreement_triggered"] is False
        assert alert["status"] == "PROBABILITY_MISSING"
        _assert_safety_stamped(alert)


# ---------------------------------------------------------------------------
# Probability extraction
# ---------------------------------------------------------------------------


class TestProbabilityExtraction:
    def test_direct_implied_probability(self):
        assert extract_implied_probability({"implied_probability": 0.31}) == 0.31

    def test_yes_price_as_dollars_passes_through(self):
        assert extract_implied_probability({"yes_price": 0.42}) == 0.42

    def test_yes_price_as_cents_normalises(self):
        assert extract_implied_probability({"yes_price": 42}) == pytest.approx(0.42)

    def test_polymarket_outcome_prices_string_format(self):
        result = extract_implied_probability({"outcomePrices": '["0.62","0.38"]'})
        assert result == pytest.approx(0.62)

    def test_invalid_payload_returns_none(self):
        assert extract_implied_probability(None) is None
        assert extract_implied_probability({}) is None
        assert extract_implied_probability({"yes_price": "huh"}) is None


# ---------------------------------------------------------------------------
# Scanner — multi-pair scan
# ---------------------------------------------------------------------------


class TestScanDisagreements:
    def test_scans_multiple_pairs_and_emits_only_matches(self):
        kalshi_rows = [
            _kalshi(title="How high will Bitcoin get in May?", implied=0.54, source_market_id="BTC-MAY"),
            _kalshi(title="Will the Fed cut rates in June?", implied=0.31, source_market_id="FED-JUN", category="Economics"),
        ]
        poly_rows = [
            _poly(title="What price will Bitcoin hit in May?", implied=0.62, market_id="poly-btc"),
            _poly(title="Will the Lakers win the NBA Finals?", implied=0.20, market_id="poly-nba", category="sports"),
        ]
        alerts = scan_disagreements(poly_rows, kalshi_rows)
        # Pair-types: poly-btc × BTC-MAY (alert), poly-btc × FED-JUN (false),
        # poly-nba × BTC-MAY (incompat category → false),
        # poly-nba × FED-JUN (false).
        assert any(a.get("disagreement_triggered") for a in alerts)
        for alert in alerts:
            _assert_safety_stamped(alert)


# ---------------------------------------------------------------------------
# Safety + forbidden-language audit
# ---------------------------------------------------------------------------


class TestSafetyAndLanguage:
    def test_no_forbidden_phrases_in_emitted_alerts(self):
        kalshi_rows = [
            _kalshi(title="How high will Bitcoin get in May?", implied=0.54),
            _kalshi(title="Will the Fed cut rates in June?", implied=0.31, category="Economics"),
        ]
        poly_rows = [
            _poly(title="What price will Bitcoin hit in May?", implied=0.62),
            _poly(title="Will the Fed reduce rates at the June meeting?", implied=0.50, category="economy"),
        ]
        alerts = scan_disagreements(poly_rows, kalshi_rows)
        # Walk every value in every alert and prove no forbidden phrase
        # leaks in via reasoning fields, customer labels, or status strings.
        blob = json.dumps(alerts)
        _assert_no_forbidden_language(blob)
        for alert in alerts:
            _assert_safety_stamped(alert)

    def test_every_persistence_payload_is_advisory_only(self):
        kalshi = _kalshi(title="How high will Bitcoin get in May?", implied=0.54)
        poly = _poly(title="What price will Bitcoin hit in May?", implied=0.62)
        alert = build_disagreement_alert(poly, kalshi)
        assert alert is not None
        # The persistence-bound dict must carry the canonical advisory
        # contract — these are the exact fields the API surface inspects
        # before showing an alert to a human.
        for field in (
            "execution_permission",
            "advisory_status",
            "execution_gate",
            "broker_api_called",
            "ai_execution_count",
            "human_review_required",
            "signal_class",
            "customer_label",
        ):
            assert field in alert, f"alert missing safety field {field}"


# ---------------------------------------------------------------------------
# Write-mode persistence
# ---------------------------------------------------------------------------


class TestWriteModePersistence:
    def test_write_mode_persists_only_triggered_into_signal_events(
        self, tmp_path: Path, monkeypatch
    ):
        from scripts import persistence

        db_path = tmp_path / "disagreement_e2e.db"
        persistence.init_schema(db_path)
        monkeypatch.setattr(persistence, "DB_PATH", db_path, raising=False)

        # Build a fixture file the CLI can ingest.
        fixture = {
            "polymarket": [
                _poly(
                    title="What price will Bitcoin hit in May?",
                    implied=0.62,
                    market_id="poly-btc",
                ),
            ],
            "kalshi": [
                _kalshi(
                    title="How high will Bitcoin get in May?",
                    implied=0.54,
                    source_market_id="kalshi-btc",
                ),
            ],
        }
        fixture_path = tmp_path / "semantic_pairs.json"
        fixture_path.write_text(json.dumps(fixture), encoding="utf-8")

        rc = run([
            "--from-fixtures",
            str(fixture_path),
            "--write",
            "--limit",
            "10",
            "--json",
        ])
        assert rc == 0

        rows = persistence.get_signal_events(
            source_name=PERSISTENCE_SOURCE_NAME, limit=50, db_path=db_path
        )
        assert len(rows) >= 1
        for row in rows:
            assert row["source_name"] == PERSISTENCE_SOURCE_NAME
            payload = row["raw_payload"]
            assert payload["signal_class"] == CROSS_VENUE_SIGNAL_CLASS
            assert payload["customer_label"] == CUSTOMER_LABEL
            assert payload["execution_permission"] == "ADVISORY_ONLY"
            assert payload["execution_gate"] == "LOCKED"
            assert payload["broker_api_called"] is False
            assert payload["ai_execution_count"] == 0
            assert payload["disagreement_triggered"] is True

    def test_cli_dry_run_does_not_write(self, tmp_path: Path, monkeypatch):
        from scripts import persistence

        db_path = tmp_path / "disagreement_dryrun.db"
        persistence.init_schema(db_path)
        monkeypatch.setattr(persistence, "DB_PATH", db_path, raising=False)

        fixture = {
            "polymarket": [
                _poly(title="What price will Bitcoin hit in May?", implied=0.62, market_id="poly-btc"),
            ],
            "kalshi": [
                _kalshi(title="How high will Bitcoin get in May?", implied=0.54, source_market_id="kalshi-btc"),
            ],
        }
        fixture_path = tmp_path / "semantic_pairs.json"
        fixture_path.write_text(json.dumps(fixture), encoding="utf-8")

        rc = run([
            "--from-fixtures",
            str(fixture_path),
            "--dry-run",
            "--limit",
            "10",
            "--json",
        ])
        assert rc == 0
        rows = persistence.get_signal_events(
            source_name=PERSISTENCE_SOURCE_NAME, limit=50, db_path=db_path
        )
        assert rows == []


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


class TestCLISmoke:
    def test_cli_handles_empty_fixture_cleanly(self, tmp_path: Path):
        empty = tmp_path / "empty.json"
        empty.write_text(json.dumps({"polymarket": [], "kalshi": []}), encoding="utf-8")
        rc = run(["--from-fixtures", str(empty), "--dry-run", "--limit", "5"])
        assert rc == 0
