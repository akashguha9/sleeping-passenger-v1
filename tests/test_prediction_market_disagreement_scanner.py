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
from scripts.prediction_market_embedding_providers import (
    DeterministicEmbeddingProvider,
    HTTPEmbeddingProvider,
    PROVIDER_DETERMINISTIC,
    PROVIDER_FALLBACK_REAL,
    resolve_embedding_provider,
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
# Cross-axis ALERT guardrails — embedding similarity must never override
# entity / threshold / resolution / category mismatch.
# ---------------------------------------------------------------------------


_BAD_ALERT_REASON_TOKENS = (
    "no_shared_asset_entity",
    "category_mismatch",
    "entity_mismatch",
    "threshold_mismatch",
    "settlement_source_mismatch",
    "resolution_mismatch_blocks_clean_alert",
    "incompatible_category",
    "low_semantic_overlap_no_shared_entity",
)
_BLOCKED_CONFIDENCE_BANDS_TEST = {"BLOCKED", "LOW"}
_ELIGIBLE_PAIR_TYPES_TEST = {SAME_EVENT_SAME_RESOLUTION, AMBIGUOUS_MATCH}


def _assert_pair_must_not_alert(alert: dict) -> None:
    """An advisory-only pair that fails any cross-axis guardrail must
    never carry ``status == 'ALERT'`` regardless of probability gap."""
    assert alert is not None
    assert alert["disagreement_triggered"] is False, (
        f"pair triggered ALERT despite guardrails: "
        f"reasons={alert.get('reasons')} "
        f"mismatch={alert.get('resolution_mismatch_reasons')} "
        f"shared={alert.get('shared_entities')}"
    )
    assert alert["status"] != "ALERT", (
        f"pair status is ALERT despite guardrails: "
        f"block_reasons={alert.get('alert_block_reasons')}"
    )
    _assert_safety_stamped(alert)


class TestAlertGuardrails:
    """Regression suite for the false-positive ALERT bugs surfaced by the
    PowerShell fixture smoke.  Each test asserts a specific mismatch
    *cannot* be promoted to a clean ALERT, even when embedding similarity
    is high and the probability gap is large."""

    # ------------------------------------------------------------------
    # A. BTC vs ETH — no shared asset/entity, large probability gap.
    # ------------------------------------------------------------------
    def test_a_btc_vs_eth_with_high_gap_is_not_alert(self):
        poly = _poly(
            title="What price will Bitcoin hit in May?",
            implied=0.62,
            market_id="poly-btc-may",
            semantic_text=(
                "Title: What price will Bitcoin hit in May?\n"
                "Rules: Resolves YES if BTC trades at or above $150k at any "
                "point in May.\nCategory: crypto"
            ),
        )
        kalshi = _kalshi(
            title="Will Ethereum hit $5k in 2026?",
            implied=0.12,
            source_market_id="ETH-5K-2026",
            semantic_text=(
                "Title: Will Ethereum hit $5k in 2026?\n"
                "Rules: Resolves YES if ETH/USD trades at or above $5,000 "
                "at any point in 2026.\nCategory: Crypto"
            ),
        )
        alert = build_disagreement_alert(poly, kalshi)
        # Probability gap of 0.50 is well above threshold, but the pair
        # has no shared asset — ALERT must be withheld.
        if alert is None:
            return  # FALSE_MATCH is also an acceptable outcome.
        _assert_pair_must_not_alert(alert)
        assert not alert.get("shared_entities"), (
            "BTC vs ETH pair should not have shared entities"
        )

    # ------------------------------------------------------------------
    # B. WTI vs Brent — settlement-source mismatch (NYMEX vs ICE).
    # ------------------------------------------------------------------
    def test_b_wti_vs_brent_settlement_source_mismatch_is_not_alert(self):
        poly = _poly(
            title="Will WTI crude close above $80 by end of June?",
            implied=0.22,
            market_id="poly-oil-above-80",
            category="commodities",
            semantic_text=(
                "Title: Will WTI crude close above $80 by end of June?\n"
                "Rules: Settles to the WTI front-month NYMEX close on June 30.\n"
                "Category: commodities"
            ),
        )
        kalshi = _kalshi(
            title="Will Brent oil close above $80 by end of June 2026?",
            implied=0.30,
            source_market_id="BRENT-JUN-2026",
            category="Commodities",
            semantic_text=(
                "Title: Will Brent oil close above $80 by end of June 2026?\n"
                "Rules: Settles to ICE Brent front-month close on June 30.\n"
                "Category: Commodities"
            ),
        )
        alert = build_disagreement_alert(poly, kalshi)
        assert alert is not None
        _assert_pair_must_not_alert(alert)
        # Either the classifier flagged it explicitly, or we lost the
        # shared entity — both must be visible to the operator.
        mismatch = alert.get("resolution_mismatch_reasons") or []
        shared = alert.get("shared_entities") or []
        assert (
            any("settlement_source_mismatch" in r for r in mismatch)
            or not shared
        ), f"pair should expose settlement mismatch or empty shared: {alert}"

    # ------------------------------------------------------------------
    # C. Any pair with resolution_mismatch_reasons non-empty.
    # ------------------------------------------------------------------
    def test_c_resolution_mismatch_reasons_non_empty_never_alerts(self):
        poly = _poly(
            title="Will Bitcoin close above $100k on May 31?",
            implied=0.80,
            market_id="poly-btc-100k",
            semantic_text=(
                "Title: Will Bitcoin close above $100k on May 31?\n"
                "Rules: Settles to BTC/USD close on Coinbase on 2026-05-31.\n"
                "Category: crypto"
            ),
        )
        kalshi = _kalshi(
            title="Will Bitcoin close above $150k on May 31?",
            implied=0.10,
            source_market_id="BTCMAY-150K",
            semantic_text=(
                "Title: Will Bitcoin close above $150k on May 31?\n"
                "Rules: Settles to BTC/USD close on Coinbase on 2026-05-31.\n"
                "Category: Crypto"
            ),
        )
        alert = build_disagreement_alert(poly, kalshi)
        assert alert is not None
        # Massive 70pp gap, but threshold mismatch should kill the alert.
        assert (alert.get("resolution_mismatch_reasons") or []), (
            "test setup expects a populated resolution_mismatch_reasons"
        )
        _assert_pair_must_not_alert(alert)

    # ------------------------------------------------------------------
    # D. Any pair with no_shared_asset_entity.
    # ------------------------------------------------------------------
    def test_d_no_shared_asset_entity_never_alerts(self):
        poly = _poly(
            title="Will the Lakers win the NBA Finals?",
            implied=0.20,
            market_id="poly-lakers",
            category="sports",
            semantic_text=(
                "Title: Will the Lakers win the NBA Finals?\n"
                "Rules: Resolves YES if Lakers win.\n"
                "Category: sports"
            ),
        )
        kalshi = _kalshi(
            title="Will the Celtics win the NBA Finals?",
            implied=0.75,
            source_market_id="CELTICS-2026",
            category="sports",
            semantic_text=(
                "Title: Will the Celtics win the NBA Finals?\n"
                "Rules: Resolves YES if Celtics win.\n"
                "Category: sports"
            ),
        )
        alert = build_disagreement_alert(poly, kalshi)
        if alert is None:
            return  # FALSE_MATCH path is also acceptable.
        # Either no shared entity at all, or the reason is explicitly
        # flagged — both must keep the pair away from ALERT.
        reasons = alert.get("reasons") or []
        shared = alert.get("shared_entities") or []
        assert (
            not shared
            or any("no_shared_asset_entity" in r for r in reasons)
        ), f"expected no shared entity or explicit reason: {alert}"
        _assert_pair_must_not_alert(alert)

    # ------------------------------------------------------------------
    # E. A valid Fed same-resolution pair with >=5pp gap remains ALERT.
    # ------------------------------------------------------------------
    def test_e_valid_fed_same_resolution_pair_still_alerts(self):
        poly = _poly(
            title="Will the Fed reduce rates at the June meeting?",
            implied=0.40,
            market_id="poly-fed-june",
            category="economy",
            semantic_text=(
                "Title: Will the Fed reduce rates at the June meeting?\n"
                "Rules: Resolves YES on FOMC June statement reducing the "
                "target range.\nCategory: economy"
            ),
        )
        kalshi = _kalshi(
            title="Will the Fed cut rates at the June 2026 meeting?",
            implied=0.31,
            source_market_id="FED-CUT-JUN-2026",
            category="Economics",
            semantic_text=(
                "Title: Will the Fed cut rates at the June 2026 meeting?\n"
                "Rules: Resolves YES if the FOMC June 2026 statement "
                "reduces the target range.\nCategory: Economics"
            ),
        )
        alert = build_disagreement_alert(poly, kalshi)
        assert alert is not None
        assert alert["pair_type"] in (SAME_EVENT_SAME_RESOLUTION, AMBIGUOUS_MATCH)
        assert alert["disagreement_triggered"] is True, (
            f"clean Fed pair should ALERT, got block_reasons="
            f"{alert.get('alert_block_reasons')}"
        )
        assert alert["status"] == "ALERT"
        assert alert.get("alert_block_reasons") == []
        assert not (alert.get("resolution_mismatch_reasons") or [])
        assert alert.get("shared_entities"), "Fed pair must have shared entity"
        _assert_safety_stamped(alert)

    # ------------------------------------------------------------------
    # F. Fixture-wide sweep: no ALERT may carry a blocked reason set.
    # ------------------------------------------------------------------
    def test_f_fixture_run_has_no_blocked_or_mismatched_alerts(self):
        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "prediction_markets"
            / "semantic_pairs.json"
        )
        with fixture_path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        poly_rows = list(payload.get("polymarket") or [])
        kalshi_rows = list(payload.get("kalshi") or [])
        alerts = scan_disagreements(poly_rows, kalshi_rows)

        offenders: list[str] = []
        for alert in alerts:
            if alert.get("status") != "ALERT":
                continue
            # F.1 — no_shared_asset_entity must NEVER appear on an ALERT.
            reasons = alert.get("reasons") or []
            for r in reasons:
                for token in _BAD_ALERT_REASON_TOKENS:
                    if r.startswith(token):
                        offenders.append(
                            f"ALERT carries forbidden reason '{token}': "
                            f"{alert.get('pair_id')}"
                        )
            # F.2 — non-empty resolution_mismatch_reasons on an ALERT.
            if alert.get("resolution_mismatch_reasons"):
                offenders.append(
                    f"ALERT has resolution_mismatch_reasons: "
                    f"{alert.get('pair_id')} -> "
                    f"{alert.get('resolution_mismatch_reasons')}"
                )
            # F.3 — pair_type must be in the eligible set.
            if alert.get("pair_type") not in _ELIGIBLE_PAIR_TYPES_TEST:
                offenders.append(
                    f"ALERT has ineligible pair_type "
                    f"{alert.get('pair_type')!r}: {alert.get('pair_id')}"
                )
            # F.4 — confidence_band must not be blocked/low.
            if alert.get("confidence_band") in _BLOCKED_CONFIDENCE_BANDS_TEST:
                offenders.append(
                    f"ALERT has blocked confidence_band "
                    f"{alert.get('confidence_band')!r}: {alert.get('pair_id')}"
                )
            # F.5 — shared_entities must be non-empty for an ALERT.
            if not (alert.get("shared_entities") or []):
                offenders.append(
                    f"ALERT has no shared_entities: {alert.get('pair_id')}"
                )

        assert not offenders, "fixture ALERTs violate guardrails:\n" + "\n".join(
            offenders
        )

        # And there must be at least ONE legitimate ALERT in the fixture
        # so we know the guardrails are not vacuously suppressing
        # everything.  The Fed-June pair satisfies every guardrail.
        triggered = [a for a in alerts if a.get("status") == "ALERT"]
        assert triggered, "fixture must surface at least one clean ALERT"

    # ------------------------------------------------------------------
    # G. alert_block_reasons surfaces the blocking axes on every record.
    # ------------------------------------------------------------------
    def test_g_block_reasons_surface_on_blocked_records(self):
        poly = _poly(
            title="What price will Bitcoin hit in May?",
            implied=0.62,
            market_id="poly-btc-may",
        )
        kalshi = _kalshi(
            title="Will Ethereum hit $5k in 2026?",
            implied=0.12,
            source_market_id="ETH-5K-2026",
        )
        alert = build_disagreement_alert(poly, kalshi)
        if alert is None:
            return
        assert "alert_block_reasons" in alert
        if alert["status"] == "ALERT":
            assert alert["alert_block_reasons"] == []
        else:
            assert alert["alert_block_reasons"], (
                "non-ALERT statuses must explain themselves via "
                "alert_block_reasons"
            )


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


# ---------------------------------------------------------------------------
# Embedding provider integration
# ---------------------------------------------------------------------------


class TestEmbeddingProviderIntegration:
    def test_alert_stamps_default_deterministic_provider(self):
        kalshi = _kalshi(title="How high will Bitcoin get in May?", implied=0.54)
        poly = _poly(title="What price will Bitcoin hit in May?", implied=0.62)
        alert = build_disagreement_alert(poly, kalshi)
        assert alert is not None
        assert alert["embedding_provider"] == PROVIDER_DETERMINISTIC
        assert alert["embedding_available"] is True
        assert "pair_score_components" in alert
        assert "embedding_score" in alert["pair_score_components"]

    def test_scan_uses_custom_provider(self):
        seen: list[str] = []

        base = DeterministicEmbeddingProvider()

        class _TrackingProvider(DeterministicEmbeddingProvider):
            def embed_text(self, text: str):
                seen.append(text)
                return base.embed_text(text)

        provider = _TrackingProvider(name="tracking_test_provider")
        kalshi_rows = [_kalshi(title="How high will Bitcoin get in May?", implied=0.54)]
        poly_rows = [_poly(title="What price will Bitcoin hit in May?", implied=0.62)]
        alerts = scan_disagreements(
            poly_rows, kalshi_rows, embedding_provider=provider
        )
        assert alerts, "scanner returned no alerts"
        assert all(a["embedding_provider"] == "tracking_test_provider" for a in alerts)
        # Provider was actually consulted.
        assert len(seen) >= 2

    def test_real_provider_fallback_when_no_key(self):
        provider = resolve_embedding_provider("real", env={})
        kalshi = _kalshi(title="How high will Bitcoin get in May?", implied=0.54)
        poly = _poly(title="What price will Bitcoin hit in May?", implied=0.62)
        alert = build_disagreement_alert(poly, kalshi, embedding_provider=provider)
        assert alert is not None
        assert alert["embedding_provider"] == PROVIDER_FALLBACK_REAL
        assert alert["embedding_available"] is False
        # Even with fallback the safety stamps remain intact.
        _assert_safety_stamped(alert)

    def test_real_provider_with_mocked_transport(self):
        captured: list[dict] = []

        def fake_transport(url, headers, payload, timeout_seconds):
            captured.append({"url": url, "payload": dict(payload)})
            return {"data": [{"embedding": [1.0] + [0.0] * 15}]}

        provider = HTTPEmbeddingProvider(
            name="real",
            model="text-embedding-3-small",
            base_url="https://example.invalid/v1/embeddings",
            api_key="sk-test",
            timeout_seconds=5.0,
            available=True,
            status_reason="transport_injected",
            transport=fake_transport,
        )
        kalshi = _kalshi(title="How high will Bitcoin get in May?", implied=0.54)
        poly = _poly(title="What price will Bitcoin hit in May?", implied=0.62)
        alert = build_disagreement_alert(poly, kalshi, embedding_provider=provider)
        assert alert is not None
        assert alert["embedding_provider"] == "real"
        assert alert["embedding_available"] is True
        assert captured, "transport was never called"

    def test_strict_mode_raises_when_real_unavailable(self):
        from scripts.prediction_market_embedding_providers import (
            EmbeddingProviderUnavailable,
        )

        with pytest.raises(EmbeddingProviderUnavailable):
            resolve_embedding_provider("real", env={}, strict=True)

    def test_cli_accepts_embedding_provider_flag(self, tmp_path: Path):
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
            "5",
            "--embedding-provider",
            "deterministic",
        ])
        assert rc == 0

    def test_cli_real_provider_falls_back_without_key(
        self, tmp_path: Path, monkeypatch
    ):
        # Ensure the env has no key configured.
        monkeypatch.delenv("PREDICTION_MARKET_EMBEDDING_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
            "5",
            "--embedding-provider",
            "real",
        ])
        # Non-strict fallback succeeds.
        assert rc == 0

    def test_cli_strict_embedding_real_without_key_exits_non_zero(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        monkeypatch.delenv("PREDICTION_MARKET_EMBEDDING_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        fixture = {"polymarket": [], "kalshi": []}
        fixture_path = tmp_path / "semantic_pairs.json"
        fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
        rc = run([
            "--from-fixtures",
            str(fixture_path),
            "--dry-run",
            "--limit",
            "5",
            "--embedding-provider",
            "real",
            "--strict-embedding",
        ])
        assert rc != 0
        out = capsys.readouterr().out
        assert "embedding_provider_unavailable" in out


# ---------------------------------------------------------------------------
# Source-run logging
# ---------------------------------------------------------------------------


class TestSourceRunLogging:
    def test_write_mode_records_source_run_log_entry(
        self, tmp_path: Path, monkeypatch
    ):
        from scripts import persistence

        db_path = tmp_path / "scanner_srl.db"
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
            "--write",
            "--limit",
            "5",
            "--json",
        ])
        assert rc == 0

        latest = persistence.get_latest_source_run_per_source(db_path=db_path)
        by_source = {r["source_name"]: r for r in latest}
        assert PERSISTENCE_SOURCE_NAME in by_source, (
            "scanner did not emit a source_run_log row in write mode"
        )
        row = by_source[PERSISTENCE_SOURCE_NAME]
        assert row["status"] == "OK"
        # extras blob should mention the embedding provider used.
        assert "embedding_provider" in str(row.get("skipped_reason", ""))

    def test_dry_run_does_not_emit_source_run_log_row(
        self, tmp_path: Path, monkeypatch
    ):
        from scripts import persistence

        db_path = tmp_path / "scanner_srl_dryrun.db"
        persistence.init_schema(db_path)
        monkeypatch.setattr(persistence, "DB_PATH", db_path, raising=False)

        fixture = {
            "polymarket": [_poly(title="What price will Bitcoin hit in May?", implied=0.62)],
            "kalshi": [_kalshi(title="How high will Bitcoin get in May?", implied=0.54)],
        }
        fixture_path = tmp_path / "semantic_pairs.json"
        fixture_path.write_text(json.dumps(fixture), encoding="utf-8")

        rc = run([
            "--from-fixtures",
            str(fixture_path),
            "--dry-run",
            "--limit",
            "5",
            "--json",
        ])
        assert rc == 0
        latest = persistence.get_latest_source_run_per_source(db_path=db_path)
        sources = {r["source_name"] for r in latest}
        assert PERSISTENCE_SOURCE_NAME not in sources, (
            "dry-run must never record a source_run_log row"
        )
