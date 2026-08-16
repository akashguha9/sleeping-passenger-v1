"""Tests — PM state capture, series builder, PEG dataset, readiness gates.

Sprint Phase 16 coverage: append-only immutability, duplicate handling,
provider failure isolation + classification (auth/rate-limit/timeout/
malformed/no-data), frozen exposure-map versioning, no-lookahead series
features, real-vs-fixture separation, missing price bars, sample-size
gates, derived-phase registration in the refresh runner.
"""
from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from scripts.prediction_market_state_capture import (
    AUTH_FAILED,
    MALFORMED_RESPONSE,
    NO_CURATED_MAP,
    NO_DATA,
    OK,
    RATE_LIMITED,
    TIMEOUT,
    append_observations,
    capture_provider,
    classify_http_failure,
    freeze_exposure_map,
    normalize_kalshi_markets,
    normalize_polymarket_markets,
)
from scripts.prediction_market_series_builder import (
    UNDERPOWERED,
    build_daily_series,
    ledger_coverage,
    series_features,
)
from scripts.quant_data_readiness_report import (
    BLOCKED_BY_DATA,
    EXPLORATORY_ONLY,
    INSUFFICIENT,
    TESTABLE,
    build_readiness,
    gate,
)
from scripts.quant_peg_dataset_builder import (
    build_new_observations,
    mature_observations,
    real_peg_census,
)


def _kalshi_payload():
    return {"markets": [
        {"ticker": "KXTEST-26DEC-T1", "event_ticker": "KXTEST-26DEC",
         "title": "Test event resolves YES", "last_price": 42,
         "yes_bid": 41, "yes_ask": 43, "volume": 1000,
         "open_interest": 500, "liquidity": 9000,
         "rules_primary": "resolves yes if X", "close_time": "2026-12-31"},
        {"ticker": "KXJUNK", "last_price": None},  # dropped
    ]}


def _poly_payload():
    return [{"conditionId": "0xabc", "slug": "test-event",
             "question": "Will X happen?", "outcomePrices": "[\"0.44\", \"0.56\"]",
             "volumeNum": 5000, "liquidityNum": 800,
             "description": "resolves yes if X", "endDate": "2026-12-31"}]


class TestNormalization:
    def test_kalshi_contract_fields(self):
        rows = normalize_kalshi_markets(_kalshi_payload(),
                                        observed_at="2026-08-16T10:00:00Z",
                                        run_id="r1")
        assert len(rows) == 1
        r = rows[0]
        assert r["p"] == 0.42 and r["bid"] == 0.41 and r["ask"] == 0.43
        assert r["spread"] == pytest.approx(0.02)
        assert r["rules_hash"] and r["epistemic_label"] == "OBSERVED"

    def test_polymarket_contract_fields(self):
        rows = normalize_polymarket_markets(_poly_payload(),
                                            observed_at="2026-08-16T10:00:00Z",
                                            run_id="r1")
        assert len(rows) == 1
        assert rows[0]["p"] == 0.44
        assert rows[0]["venue"] == "polymarket"


class TestProviderIsolation:
    def test_failure_classification(self):
        assert classify_http_failure(
            urllib.error.HTTPError("u", 401, "no", {}, None)) == AUTH_FAILED
        assert classify_http_failure(
            urllib.error.HTTPError("u", 429, "rl", {}, None)) == RATE_LIMITED
        assert classify_http_failure(TimeoutError()) == TIMEOUT
        assert classify_http_failure(ValueError("bad json")) == \
            MALFORMED_RESPONSE

    def test_one_provider_failure_does_not_kill_capture(self):
        def broken():
            raise urllib.error.HTTPError("u", 401, "no", {}, None)
        bad = capture_provider("kalshi", broken, normalize_kalshi_markets,
                               observed_at="t", run_id="r")
        good = capture_provider("polymarket", _poly_payload,
                                normalize_polymarket_markets,
                                observed_at="t", run_id="r")
        assert bad["status"] == AUTH_FAILED and bad["rows"] == []
        assert good["status"] == OK and len(good["rows"]) == 1

    def test_malformed_payload_classified_not_raised(self):
        out = capture_provider("kalshi", lambda: {"markets": "garbage"},
                               normalize_kalshi_markets,
                               observed_at="t", run_id="r")
        assert out["status"] in (MALFORMED_RESPONSE, NO_DATA)

    def test_empty_payload_is_no_data(self):
        out = capture_provider("kalshi", lambda: {"markets": []},
                               normalize_kalshi_markets,
                               observed_at="t", run_id="r")
        assert out["status"] == NO_DATA


class TestAppendOnlyLedger:
    def test_append_dedup_and_immutability(self, tmp_path: Path):
        ledger = tmp_path / "ledger.jsonl"
        rows = normalize_kalshi_markets(_kalshi_payload(),
                                        observed_at="2026-08-16T10:00:00Z",
                                        run_id="r1")
        first = append_observations(rows, ledger_path=ledger)
        assert first["appended"] == 1
        before = ledger.read_text(encoding="utf-8")
        # Same observation again -> duplicate skipped, file unchanged.
        second = append_observations(rows, ledger_path=ledger)
        assert second["appended"] == 0
        assert second["duplicates_skipped"] == 1
        assert ledger.read_text(encoding="utf-8") == before
        # New timestamp -> appended, prior line byte-identical.
        later = normalize_kalshi_markets(_kalshi_payload(),
                                         observed_at="2026-08-17T10:00:00Z",
                                         run_id="r2")
        third = append_observations(later, ledger_path=ledger)
        assert third["appended"] == 1
        assert ledger.read_text(encoding="utf-8").startswith(before)


class TestSeriesBuilder:
    def _rows(self, days, venue="kalshi", ticker="KXTEST-26DEC-T1"):
        return [{"venue": venue, "market_ticker": ticker, "p": p,
                 "date": d, "observed_at": f"{d}T10:00:00Z"}
                for d, p in days]

    def test_intraday_collapse_last_of_day(self):
        rows = self._rows([("2026-08-16", 0.40)])
        rows.append({"venue": "kalshi", "market_ticker": "KXTEST-26DEC-T1",
                     "p": 0.45, "date": "2026-08-16",
                     "observed_at": "2026-08-16T18:00:00Z"})
        series = build_daily_series(rows)
        assert series[("kalshi", "KXTEST-26DEC-T1")] == [("2026-08-16", 0.45)]

    def test_features_no_lookahead_truncation(self):
        days = [("2026-08-10", 0.30), ("2026-08-11", 0.35),
                ("2026-08-12", 0.40), ("2026-08-13", 0.60)]
        series = build_daily_series(self._rows(days))
        s = series[("kalshi", "KXTEST-26DEC-T1")]
        full = series_features(s)
        truncated = series_features(s, as_of_date="2026-08-12")
        assert full["p_latest"] == 0.60
        assert truncated["p_latest"] == 0.40  # future obs invisible
        assert truncated["lookahead_free"] is True

    def test_underpowered_gate(self):
        series = build_daily_series(self._rows([("2026-08-16", 0.4)]))
        s = series[("kalshi", "KXTEST-26DEC-T1")]
        assert series_features(s)["status"] == UNDERPOWERED

    def test_coverage_census(self):
        rows = self._rows([(f"2026-08-{d:02d}", 0.4) for d in range(1, 9)])
        rows += self._rows([("2026-08-01", 0.5)], ticker="OTHER")
        cov = ledger_coverage(rows)
        assert cov["distinct_markets"] == 2
        assert cov["markets_ge_7_days"] == 1
        assert cov["markets_ge_21_days"] == 0


class TestFrozenExposureMap:
    def _curated(self, tmp_path: Path, entries):
        p = tmp_path / "current_event_equity_map.json"
        p.write_text(json.dumps({"entries": entries}), encoding="utf-8")
        return p

    def _entry(self, **kw):
        base = {"event_id": "KXTEST-26DEC", "ticker": "AAPL",
                "direction": 1, "exposure": 0.5,
                "capture_rate": 0.5, "hop": 1,
                "rationale": "test", "evidence_ref": "10-K-x"}
        base.update(kw)
        return base

    def test_missing_map_reports_and_writes_template(self, tmp_path: Path):
        out = freeze_exposure_map(
            curated_path=tmp_path / "absent.json",
            frozen_dir=tmp_path / "frozen", run_date_day=1000)
        assert out["status"] == NO_CURATED_MAP
        assert (tmp_path / "TEMPLATE_event_equity_map.json").exists()

    def test_versions_chain_and_history_never_replaced(self, tmp_path: Path):
        curated = self._curated(tmp_path, [self._entry()])
        frozen_dir = tmp_path / "frozen"
        v1 = freeze_exposure_map(curated_path=curated,
                                 frozen_dir=frozen_dir, run_date_day=1000)
        assert v1["status"] == OK and v1["version"] == 1
        v1_bytes = Path(v1["path"]).read_text(encoding="utf-8")
        # Unchanged content -> no new version.
        again = freeze_exposure_map(curated_path=curated,
                                    frozen_dir=frozen_dir, run_date_day=1001)
        assert again["status"] == "UNCHANGED"
        # Changed content -> v2 chained to v1; v1 file untouched.
        self._curated(tmp_path, [self._entry(exposure=0.8)])
        v2 = freeze_exposure_map(curated_path=curated,
                                 frozen_dir=frozen_dir, run_date_day=1002)
        assert v2["status"] == OK and v2["version"] == 2
        doc2 = json.loads(Path(v2["path"]).read_text(encoding="utf-8"))
        assert doc2["prev_hash"] == v1["content_hash"]
        assert Path(v1["path"]).read_text(encoding="utf-8") == v1_bytes

    def test_uncited_entries_dropped(self, tmp_path: Path):
        curated = self._curated(
            tmp_path, [self._entry(evidence_ref=None)])
        out = freeze_exposure_map(curated_path=curated,
                                  frozen_dir=tmp_path / "frozen",
                                  run_date_day=1000)
        assert out["status"] == NO_DATA
        assert out["dropped_uncited"] == 1


class TestPEGDataset:
    def _frozen_map(self):
        return {"version": 1, "content_hash": "abc123",
                "entries": [{"event_id": "KXTEST", "ticker": "AAPL",
                             "direction": 1, "exposure": 0.6,
                             "exposure_confidence": 0.8, "hop": 1,
                             "chain_position": "MIDSTREAM",
                             "expected_lag_days": 5,
                             "filing_confirmation": "STRONG",
                             "capture_rate": 0.5,
                             "evidence_ref": "10-K"}]}

    def _ledger_rows(self):
        return [{"venue": "kalshi", "market_ticker": "KXTEST-T1",
                 "p": 0.30 + 0.05 * i, "date": f"2026-08-{10 + i:02d}",
                 "observed_at": f"2026-08-{10 + i:02d}T10:00:00Z"}
                for i in range(5)]

    def test_builds_live_observation_with_frozen_fields(
            self, tmp_path: Path, monkeypatch):
        import scripts.quant_peg_dataset_builder as mod
        monkeypatch.setattr(
            mod, "load_close_series",
            lambda db, min_days=1: {"AAPL": {"2026-08-14": 230.0}})
        obs_path = tmp_path / "peg.jsonl"
        out = build_new_observations(
            run_date="2026-08-14", frozen_map=self._frozen_map(),
            ledger_rows=self._ledger_rows(), obs_path=obs_path)
        assert out["status"] == OK and out["created"] == 1
        row = json.loads(obs_path.read_text(encoding="utf-8"))
        assert row["data_mode"] == "LIVE"
        assert row["hop"] == 1 and row["filing_confirmation"] == "STRONG"
        assert row["prob"]["delta_p"] > 0
        assert row["ar"] == {}  # missing != zero
        # Re-run same day -> dedup, no second row.
        again = build_new_observations(
            run_date="2026-08-14", frozen_map=self._frozen_map(),
            ledger_rows=self._ledger_rows(), obs_path=obs_path)
        assert again["created"] == 0 and again["skipped_dup"] == 1

    def test_missing_price_bar_skipped_never_faked(self, tmp_path: Path,
                                                   monkeypatch):
        import scripts.quant_peg_dataset_builder as mod
        monkeypatch.setattr(mod, "load_close_series",
                            lambda db, min_days=1: {})
        out = build_new_observations(
            run_date="2026-08-14", frozen_map=self._frozen_map(),
            ledger_rows=self._ledger_rows(),
            obs_path=tmp_path / "peg.jsonl")
        assert out["created"] == 0 and out["skipped_no_price"] == 1

    def test_maturation_fills_only_available_horizons(self, tmp_path: Path,
                                                      monkeypatch):
        import scripts.quant_peg_dataset_builder as mod
        closes = {"AAPL": {f"2026-08-{d:02d}": 230.0 + d for d in range(14, 18)},
                  "SPY": {f"2026-08-{d:02d}": 640.0 + d for d in range(14, 18)}}
        monkeypatch.setattr(mod, "load_close_series",
                            lambda db, min_days=1: closes["AAPL"] and closes)
        obs_path = tmp_path / "peg.jsonl"
        build_new_observations(
            run_date="2026-08-14", frozen_map=self._frozen_map(),
            ledger_rows=self._ledger_rows(), obs_path=obs_path)
        out = mature_observations(obs_path=obs_path)
        assert out["status"] == OK
        row = json.loads(obs_path.read_text(encoding="utf-8"))
        assert "1" in row["ar"] and "3" in row["ar"]   # bars exist
        assert "21" not in row["ar"]                   # not yet mature
        entry_before = row["entry_price"]
        # Maturing again must not modify matured values or entry fields.
        mature_observations(obs_path=obs_path)
        row2 = json.loads(obs_path.read_text(encoding="utf-8"))
        assert row2["ar"]["1"] == row["ar"]["1"]
        assert row2["entry_price"] == entry_before

    def test_census_counts_live_only(self, tmp_path: Path):
        obs = tmp_path / "peg.jsonl"
        obs.write_text(
            json.dumps({"data_mode": "LIVE", "hop": 2,
                        "filing_confirmation": "STRONG",
                        "ar": {"5": 0.01}}) + "\n" +
            json.dumps({"data_mode": "FIXTURE_DEMONSTRATION", "hop": 1,
                        "ar": {"5": 0.02}}) + "\n", encoding="utf-8")
        census = real_peg_census(obs_path=obs)
        assert census["n_live_observations"] == 1
        assert census["n_matured_by_horizon"][5] == 1
        assert census["hop_distribution"] == {"2": 1}


class TestReadinessGates:
    def test_gate_bands(self):
        assert gate(0) == BLOCKED_BY_DATA
        assert gate(5) == INSUFFICIENT
        assert gate(20) == EXPLORATORY_ONLY
        assert gate(79) == EXPLORATORY_ONLY
        assert gate(80) == TESTABLE

    def test_build_readiness_empty_world(self, tmp_path: Path):
        readiness = build_readiness(
            ledger_rows=[],
            peg_census={"n_live_observations": 0,
                        "n_matured_by_horizon": {h: 0 for h in
                                                 (1, 3, 5, 10, 21)},
                        "hop_distribution": {},
                        "filing_confirmation_distribution": {}},
            frozen_dir=tmp_path / "none")
        assert readiness["experiments"]["peg_forward_ar"]["status"] == \
            BLOCKED_BY_DATA
        assert readiness["frozen_exposure_map_versions"] == 0
        assert readiness["signal_class"] == "RESEARCH_ONLY"


class TestRefreshDerivedPhase:
    def test_disagreement_source_now_has_phase(self):
        from scripts.refresh_live_signals import _phase_for
        assert _phase_for("prediction_market_disagreement") == "derived"
        assert _phase_for("polymarket") == "phase1"
        assert _phase_for("made_up_source") == "unknown"


class TestTemporalDepth:
    def _rows(self, specs):
        return [{"venue": v, "market_ticker": m, "p": p, "date": ts[:10],
                 "observed_at": ts} for v, m, p, ts in specs]

    def test_same_day_observations_are_one_distinct_day(self):
        from scripts.prediction_market_series_builder import ledger_coverage
        rows = self._rows([
            ("kalshi", "M1", 0.4, "2026-08-16T10:00:00+00:00"),
            ("kalshi", "M1", 0.5, "2026-08-16T16:00:00+00:00")])
        cov = ledger_coverage(rows)
        assert cov["distinct_days"] == 1
        assert cov["markets_ge_2_days"] == 0
        assert cov["max_depth_days"] == 1

    def test_two_different_days_counts_ge2(self):
        from scripts.prediction_market_series_builder import ledger_coverage
        rows = self._rows([
            ("kalshi", "M1", 0.4, "2026-07-02T10:00:00+00:00"),
            ("kalshi", "M1", 0.5, "2026-08-16T10:00:00+00:00"),
            ("kalshi", "M2", 0.3, "2026-08-16T10:00:00+00:00")])
        cov = ledger_coverage(rows)
        assert cov["markets_ge_2_days"] == 1
        assert cov["distinct_markets"] == 2
        assert cov["elapsed_calendar_days"] == 45
        assert cov["per_venue"]["kalshi"]["ge_2_days"] == 1

    def test_duplicate_records_do_not_inflate_depth(self):
        from scripts.prediction_market_series_builder import ledger_coverage
        rows = self._rows([
            ("kalshi", "M1", 0.4, "2026-08-16T10:00:00+00:00")] * 5)
        cov = ledger_coverage(rows)
        assert cov["max_depth_days"] == 1
        assert cov["markets_ge_2_days"] == 0

    def test_history_quality_bands(self):
        from scripts.prediction_market_series_builder import (
            EXPLORATORY_SERIES, LEVEL_ONLY, RESEARCH_READY, SHORT_SERIES,
            TWO_POINT_HISTORY, contract_history_quality)
        assert contract_history_quality(1) == LEVEL_ONLY
        assert contract_history_quality(2) == TWO_POINT_HISTORY
        assert contract_history_quality(3) == SHORT_SERIES
        assert contract_history_quality(7) == EXPLORATORY_SERIES
        assert contract_history_quality(21) == RESEARCH_READY

    def test_feature_capability_matches_estimator_minimums(self):
        from scripts.prediction_market_series_builder import feature_capability
        assert feature_capability(1) == "LEVEL_ONLY"
        assert feature_capability(2) == "DELTA_AND_VELOCITY_POSSIBLE"
        assert feature_capability(3) == "ACCELERATION_POSSIBLE"
        assert feature_capability(9) == "ACCELERATION_POSSIBLE"
        assert feature_capability(10) == "STANDARDIZED_SHOCK_POSSIBLE"

    def test_two_point_series_gives_velocity_not_acceleration(self):
        from scripts.prediction_market_series_builder import series_features
        two = [("2026-07-02", 0.11), ("2026-08-16", 0.09)]
        # series_features requires MIN_DAILY_OBS=3 for full features —
        # two points stay UNDERPOWERED rather than pretending acceleration.
        out = series_features(two)
        assert out["status"] == "UNDERPOWERED"

    def test_depth_note_early_longitudinal_in_readiness(self):
        from scripts.quant_data_readiness_report import build_readiness
        rows = self._rows([
            ("kalshi", "M1", 0.4, "2026-07-02T10:00:00+00:00"),
            ("kalshi", "M1", 0.5, "2026-08-16T10:00:00+00:00")])
        readiness = build_readiness(
            ledger_rows=rows,
            peg_census={"n_live_observations": 0,
                        "n_matured_by_horizon": {h: 0 for h in
                                                 (1, 3, 5, 10, 21)},
                        "hop_distribution": {},
                        "filing_confirmation_distribution": {}})
        dyn = readiness["experiments"]["probability_dynamics"]
        assert dyn["status"] == "BLOCKED_BY_DATA"
        assert "EARLY_LONGITUDINAL" in (dyn.get("depth_note") or "")
