"""Sprint 2 tests for the zip simulation subsystem.

Covers the Phase 14 checklist: cache index + keys, classifier v2, market fuzzy
mapping + leakage + NO_DATA thresholds, abstention grid + DQS, bootstrap CI
determinism, evidence quality, duplicate normalization, source diversity,
rubric/scorecard weight sums, chess advanced metrics, score caps, report
generation, and the advisory-only forbidden-token scan.  Tiny synthetic zips
only — never the real corpus.
"""
from __future__ import annotations

import json
import pathlib
import zipfile

import pytest

from src.simulation_zip import (
    evidence_quality as eq,
    index_store,
    metrics,
    scorecard_v2,
)
from src.simulation_zip.classifier import (
    DatasetClassifier,
    W2_EXTENSION,
    W2_HEADER,
    W2_KEYWORD,
    W2_METADATA,
    W2_PATH,
    W2_SCHEMA,
)
from src.simulation_zip.parsers import (
    MarketParser,
    PgnParser,
    RUBRIC_V2_WEIGHTS,
    chess_aggregate_stats,
    hackathon_rubric_v2,
    normalize_scraped_text,
    time_control_class,
)
from src.simulation_zip.run import run as cli_run
from src.simulation_zip.sprint2 import build_calibration_bundle, run_sprint2


def _market_csv(rows: int, cols: str = "ticker,date,close,volume,signal") -> str:
    out = [cols]
    price = 100.0
    for d in range(rows):
        price *= 1.001 if d % 2 else 0.999
        out.append(f"AAPL,2021-{(d % 12) + 1:02d}-{(d % 28) + 1:02d},{price:.4f},1000,{d % 2}")
    return "\n".join(out)


def _pgn(n: int = 30) -> str:
    out = []
    for i in range(n):
        res = "0-1" if i % 5 == 0 else "1-0"
        term = "Time forfeit" if i % 7 == 0 else "Normal"
        moves = " ".join(f"{j}. e4 e5" for j in range(1, 35))
        out.append(
            f'[Event "x"]\n[Site "chess.com"]\n[Date "2021.01.01"]\n[White "a"]\n'
            f'[Black "b"]\n[Result "{res}"]\n[WhiteElo "1500"]\n[BlackElo "1200"]\n'
            f'[Termination "{term}"]\n[TimeControl "300+0"]\n\n{moves} {res}\n'
        )
    return "\n".join(out)


def _build_zip(path) -> str:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("chess/games.pgn", _pgn(30))
        z.writestr(
            "hackathon/README.md",
            "# P\nproblem pain challenge user need why solution build prototype "
            "feature architecture workflow demo video live deploy run risk "
            "limitation caveat reproduce install requirements readme command "
            "judging criteria rubric business revenue market customer pricing\n",
        )
        z.writestr("scrape/reddit_1.txt", "https://reddit.com/r/a\nhello world")
        z.writestr("scrape/reddit_2.txt", "https://reddit.com/r/a\nhello world")
        z.writestr("scrape/tw.txt", "https://twitter.com/x\ndistinct content")
        z.writestr("market/prices.csv", _market_csv(150))
        z.writestr("misc/blob.bin", b"\x00\x01" * 40)
    return str(path)


# 1. Local zip missing fail-closed
def test_sprint2_missing_zip_blocked_cap40(tmp_path):
    r = run_sprint2(str(tmp_path / "nope.zip"))
    assert r["status"] == "BLOCKED" and r["run_type"] == "BLOCKED_NO_ZIP"
    o = r["scorecard"]["overall"]
    assert o["overall_after"] <= 40.0
    assert "zip_not_found_cap_40" in o["overall_caps"]


# 2. Index schema creation
def test_index_schema_created(tmp_path):
    db = tmp_path / "idx.sqlite"
    with index_store.ZipCorpusIndex(db) as idx:
        tables = {
            row[0]
            for row in idx.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {"zip_runs", "zip_members", "parsed_records"} <= tables


# 3. Cache key determinism
def test_cache_key_deterministic():
    a = index_store.cache_key("C:/z.zip", 100, "a/b.csv", 10, 50, "2021-01-01")
    b = index_store.cache_key("C:\\z.zip", 100, "a/b.csv", 10, 50, "2021-01-01")
    assert a == b
    c = index_store.cache_key("C:/z.zip", 101, "a/b.csv", 10, 50, "2021-01-01")
    assert c != a
    strong = index_store.cache_key_strong("C:/z.zip", "a/b.csv", "deadbeef")
    assert strong and index_store.cache_key_strong("C:/z.zip", "a/b.csv", None) is None


# 4. Cache hit/miss accounting
def test_cache_hit_accounting():
    members = [
        {"cache_key_strong": "k1"}, {"cache_key_strong": "k2"},
        {"cache_key_strong": None},
    ]
    stats = index_store.compute_cache_hits(members, {"k1"})
    assert stats["cache_hits"] == 1
    assert stats["cache_misses"] == 2
    assert stats["total_members"] == 3


def test_sprint2_cache_hit_on_rerun(tmp_path):
    zp = _build_zip(tmp_path / "c.zip")
    db = str(tmp_path / "idx.sqlite")
    first = run_sprint2(zp, index_path=db, bootstrap_samples=50)
    assert first["cache"]["cache_hit_rate"] == 0.0
    second = run_sprint2(zp, index_path=db, bootstrap_samples=50)
    assert second["cache"]["cache_hit_rate"] == 1.0


# 5. Family classifier v2 weights
def test_classifier_v2_weights_sum_to_one():
    total = W2_EXTENSION + W2_HEADER + W2_KEYWORD + W2_SCHEMA + W2_PATH + W2_METADATA
    assert abs(total - 1.0) < 1e-9


def test_classifier_v2_refined_family():
    c = DatasetClassifier()
    res = c.classify("notebooks/run.ipynb", b'{"cells": [], "nbformat": 4}')
    assert res.refined_family in ("notebook_corpus", "code_corpus", "json_api_dump")
    assert "metadata_match" in res.v2_features


# 6. Market fuzzy column mapping
def test_market_fuzzy_column_mapping():
    mp = MarketParser()
    mapping, ambiguous = mp._fuzzy_map(["Symbol", "Timestamp", "Adj Close", "Vol"])
    assert mapping["ticker"] == "symbol"
    assert mapping["date"] == "timestamp"
    assert mapping["price"] == "adj close"
    assert mapping["volume"] == "vol"


def test_market_fuzzy_short_name_guard_blocks_substring():
    mp = MarketParser()
    # Single-char exact aliases (o/h/l/c/v) ARE valid per spec, but a 2-char
    # non-alias like "cl" must NOT fuzzily claim "close" via substring.
    mapping, _ = mp._fuzzy_map(["xx", "cl", "vv"])
    assert mapping["price"] is None  # 'cl' is not an exact alias, too short to fuzz
    assert mapping["ticker"] is None
    # 'a','b' are not aliases of ticker/date, so a junk header is rejected.
    junk, _ = mp._fuzzy_map(["a", "b"])
    assert junk["ticker"] is None and junk["date"] is None


# 7. Market leakage-risk detection
def test_market_leakage_detection():
    mp = MarketParser()
    rep = mp._leakage_report(["ticker", "date", "close", "future_return", "target"])
    assert rep["leakage_band"] == "HIGH"
    assert rep["predictive_uplift_allowed"] is False
    clean = mp._leakage_report(["ticker", "date", "close", "volume"])
    assert clean["leakage_band"] == "LOW"


# 8. Market threshold NO_DATA
def test_market_no_data_below_threshold():
    res = MarketParser().parse(_market_csv(20), "p" * 64, "m.csv")
    assert res["status"] == "NO_DATA"


def test_market_ok_reports_readiness_and_label():
    res = MarketParser().parse(_market_csv(150), "p" * 64, "market/prices.csv")
    assert res["status"] == "OK"
    assert res["unique_dates"] >= 30
    assert res["fully_ready"] is True
    assert res["market_label"] in (
        "MARKET_DATA_WITH_SIGNALS", "MARKET_DATA_DESCRIPTIVE_ONLY"
    )
    assert "leakage" in res and "walk_forward_split" in res["metrics"]


# 9-10. Abstention grid + DQS / τ*
def test_abstention_grid_and_dqs():
    pairs = [(0.9, 1.0)] * 30 + [(0.9, 0.0)] * 5 + [(0.4, 0.0)] * 20
    grid = metrics.abstention_grid(pairs)
    assert len(grid) == 10
    for row in grid:
        assert 0.0 <= row["coverage"] <= 1.0
        assert 0.0 <= row["dqs"] <= 1.0
    best = metrics.best_decision_threshold(grid)
    assert best is not None and best["threshold"] in [r["threshold"] for r in grid]


def test_dqs_formula_matches_components():
    grid = metrics.abstention_grid([(0.8, 1.0)] * 50 + [(0.2, 0.0)] * 50)
    for r in grid:
        expected = r["accuracy"] * (r["coverage"] ** 0.5) * ((1 - r["hcfr"]) ** 2.0)
        assert abs(r["dqs"] - expected) < 1e-9


# 11. Bootstrap CI deterministic seed
def test_bootstrap_ci_deterministic_and_min_n():
    vals = [float(i % 2) for i in range(100)]
    a = metrics.bootstrap_ci(vals, lambda s: sum(s) / len(s), samples=200, seed=42)
    b = metrics.bootstrap_ci(vals, lambda s: sum(s) / len(s), samples=200, seed=42)
    assert a == b and a["status"] == "OK"
    assert a["ci_low"] <= a["point"] <= a["ci_high"]
    small = metrics.bootstrap_ci([1.0] * 10, lambda s: sum(s), samples=50)
    assert small["status"] == "NO_DATA_INSUFFICIENT_N"


# 12. Evidence quality
def test_evidence_quality_score_and_bands():
    full = {k: 1.0 for k in eq.Q_WEIGHTS}
    assert eq.record_quality(full) == 100.0
    assert eq.quality_band(100.0) == "STRONG_SIMULATION_EVIDENCE"
    assert eq.quality_band(0.0) == "POOR_OR_UNUSABLE"
    corpus = eq.corpus_quality({"chess_pgn": [full, full], "scraped_text": []})
    assert corpus["Q_corpus"] == 100.0
    assert corpus["total_parsed"] == 2


# 13. Duplicate hash normalization
def test_normalize_scraped_text_collapses_and_dedups():
    a = normalize_scraped_text("<p>Hello   World</p> https://x.com/a/b")
    b = normalize_scraped_text("hello world x.com")
    assert a == b  # html stripped, ws collapsed, url->domain


# 14. Source diversity formula
def test_domain_diversity_bounds():
    one = metrics.shannon_diversity({"a.com": 5})
    assert one["normalized_diversity"] == 0.0
    two = metrics.shannon_diversity({"a.com": 5, "b.com": 5})
    assert abs(two["normalized_diversity"] - 1.0) < 1e-9


# 15. Hackathon rubric weights sum to 1
def test_hackathon_rubric_v2_weights_and_bounds():
    assert abs(sum(RUBRIC_V2_WEIGHTS.values()) - 1.0) < 1e-9
    res = hackathon_rubric_v2("problem solution demo risk reproduce", "p" * 64)
    assert 0.0 <= res["P_h"] <= 100.0
    assert set(res["components"]) == set(RUBRIC_V2_WEIGHTS)


# 16. Chess advanced metrics
def test_chess_aggregate_stats():
    games = PgnParser().parse(_pgn(30), "p" * 64)
    stats = chess_aggregate_stats(games)
    assert stats["games"] == 30
    for key in ("upset_rate", "draw_rate", "long_game_rate", "timeout_rate"):
        assert 0.0 <= stats[key] <= 1.0
    assert stats["time_control_classes"].get("blitz", 0) == 30  # 300s => blitz
    assert time_control_class(60) == "bullet"
    assert time_control_class(3600) == "classical"


# 17. Scorecard v2 weights sum to 1
def test_scorecard_v2_weights_sum_to_one():
    scorecard_v2.assert_weights_sum_to_one(scorecard_v2.WEIGHTS_V2)
    assert abs(sum(scorecard_v2.WEIGHTS_V2.values()) - 1.0) < 1e-9
    assert len(scorecard_v2.SEGMENTS) == 18


# 18. Score caps
def test_scorecard_caps_no_market_and_no_outcomes():
    before = {s: 0.0 for s in scorecard_v2.SEGMENTS}
    after = {s: 100.0 for s in scorecard_v2.SEGMENTS}
    card = scorecard_v2.compute_scorecard_v2(
        before, after,
        flags={"zip_found": True, "safety_blocked": False, "tests_pass": True,
               "guardrails_ok": True, "provenance_present": True,
               "has_real_market_data": False, "has_labelled_outcomes": False,
               "has_parsed_records": True},
    )
    assert card["segments"]["market_data_readiness"]["after"] <= 60.0
    assert card["segments"]["calibration_hardening"]["after"] <= 75.0


def test_scorecard_guardrails_broken_cap30():
    before = {s: 0.0 for s in scorecard_v2.SEGMENTS}
    after = {s: 100.0 for s in scorecard_v2.SEGMENTS}
    card = scorecard_v2.compute_scorecard_v2(
        before, after,
        flags={"zip_found": True, "safety_blocked": False, "tests_pass": True,
               "guardrails_ok": False, "provenance_present": True,
               "has_real_market_data": True, "has_labelled_outcomes": True,
               "has_parsed_records": True},
    )
    assert card["overall"]["overall_after"] <= 30.0


def test_scorecard_no_records_zeros_segments():
    before = {s: 0.0 for s in scorecard_v2.SEGMENTS}
    after = {s: 80.0 for s in scorecard_v2.SEGMENTS}
    card = scorecard_v2.compute_scorecard_v2(
        before, after,
        flags={"zip_found": True, "safety_blocked": False, "tests_pass": True,
               "guardrails_ok": True, "provenance_present": True,
               "has_real_market_data": True, "has_labelled_outcomes": True,
               "has_parsed_records": False},
    )
    for seg in ("parsed_simulation_volume", "evidence_quality", "source_diversity"):
        assert card["segments"][seg]["after"] == 0.0


# 19. Report generation (CLI sprint2)
def test_sprint2_cli_writes_reports(tmp_path):
    zp = _build_zip(tmp_path / "c.zip")
    out = tmp_path / "reports"
    rc = cli_run([
        "--sprint2", "--zip", zp, "--out-dir", str(out),
        "--corpus-label", "SYNTHETIC_FIXTURE", "--bootstrap-samples", "50",
        "--index-path", str(tmp_path / "idx.sqlite"),
    ])
    assert rc == 0
    names = " ".join(p.name for p in out.glob("zip_simulation_sprint2_*"))
    for stem in ("inventory", "run", "scores", "scorecard", "integration"):
        assert stem in names
    run_json = next(out.glob("zip_simulation_sprint2_run_*.json"))
    data = json.loads(run_json.read_text())
    assert data["labels"]["labels"][0] == "SIMULATION_ONLY"
    assert data["sprint"] == 2


# 20. Advisory-only forbidden token scan
def test_sprint2_modules_have_no_execution_logic():
    pkg = pathlib.Path("src/simulation_zip")
    forbidden = (
        "place_order", "submit_order", "execute_trade", "broker_execute",
        "import alpaca", "import ib_insync", "import ccxt", "ibkr",
    )
    for f in pkg.glob("*.py"):
        src = f.read_text(encoding="utf-8").lower()
        for tok in forbidden:
            assert tok not in src, (f.name, tok)


def test_calibration_bundle_no_data():
    assert build_calibration_bundle([], bootstrap_samples=10, seed=1)["status"] == "NO_DATA"


def test_sprint2_synthetic_run_is_simulation_only(tmp_path):
    zp = _build_zip(tmp_path / "c.zip")
    r = run_sprint2(zp, corpus_label="SYNTHETIC_FIXTURE",
                    index_path=str(tmp_path / "i.sqlite"), bootstrap_samples=50)
    assert r["labels"]["labels"] == [
        "SIMULATION_ONLY", "ZIP_CORPUS_DERIVED", "NOT_LIVE_TRADING_EVIDENCE",
        "NOT_BROKER_DATA", "NOT_FINANCIAL_ADVICE",
    ]
    assert r["scorecard"]["overall"]["label"] == "SIMULATION_ONLY"
    # guardrails preserved
    g = r["scorecard"]["segments"]["advisory_guardrail_preservation"]
    assert g["before"] == g["after"]
