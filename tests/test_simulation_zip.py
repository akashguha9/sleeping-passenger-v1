"""Tests for the zip simulation corpus ingestion subsystem.

These build tiny synthetic zips in ``tmp_path`` — the real 700 MB operator zip
is never used in automated tests.  Coverage maps to the Phase 6 checklist:
missing/corrupt zip, zip-slip + absolute-path rejection, compression-ratio
warning, manifest + classification, all four parsers, provenance + score
determinism, the test-failure score cap, advisory-only preservation, and a CLI
smoke test.
"""
from __future__ import annotations

import json
import zipfile

import pytest

from src.simulation_zip import metrics, scoring
from src.simulation_zip.classifier import (
    ConfidenceClass,
    DatasetClassifier,
    DatasetFamily,
)
from src.simulation_zip.harness import run_zip_simulation
from src.simulation_zip.labels import SIMULATION_LABELS
from src.simulation_zip.parsers import (
    HackathonParser,
    MarketParser,
    PgnParser,
    ScrapedTextParser,
)
from src.simulation_zip.provenance import ProvenanceHasher
from src.simulation_zip.run import run as cli_run
from src.simulation_zip.safety import (
    SafetyConfig,
    SafetyStatus,
    ZipSafetyValidator,
    is_unsafe_member_path,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #
def _pgn_text(n: int = 30) -> str:
    out = []
    for i in range(n):
        we, be = 1500, 1200  # white strongly favored
        res = "0-1" if i % 5 == 0 else "1-0"  # every 5th is an upset
        term = "Time forfeit" if i % 7 == 0 else "Normal"
        moves = " ".join(f"{j}. e4 e5" for j in range(1, 35))
        out.append(
            f'[Event "Live Chess"]\n[Site "chess.com"]\n[Date "2021.01.01"]\n'
            f'[White "a"]\n[Black "b"]\n[Result "{res}"]\n'
            f'[WhiteElo "{we}"]\n[BlackElo "{be}"]\n[Termination "{term}"]\n'
            f'[ECO "C20"]\n\n{moves} {res}\n'
        )
    return "\n".join(out)


def _market_csv(rows: int = 150) -> str:
    out = ["ticker,date,close,volume,signal"]
    price = 100.0
    for d in range(rows):
        price *= 1.001 if d % 2 else 0.999
        out.append(f"AAPL,2021-01-{(d % 28) + 1:02d},{price:.4f},1000,{d % 2}")
    return "\n".join(out)


def _build_good_zip(path) -> str:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("chess/games.pgn", _pgn_text(30))
        z.writestr(
            "hackathon/README.md",
            "# Proj\nProblem pain challenge user need why.\n"
            "Solution build prototype feature architecture workflow.\n"
            "Demo video live deploy run. Risk limitation caveat assumption.\n"
            "Reproduce install setup requirements readme command.\n"
            "Judging criteria rubric score impact evaluation.\n",
        )
        z.writestr("scrape/reddit_1.txt", "https://reddit.com/r/a\nhello world article")
        z.writestr("scrape/reddit_2.txt", "https://reddit.com/r/a\nhello world article")
        z.writestr("scrape/tw.txt", "https://twitter.com/x\ndistinct tweet content")
        z.writestr("market/prices.csv", _market_csv(150))
        z.writestr("code/util.py", "import os\ndef f():\n    return 1\n")
        z.writestr("misc/blob.bin", b"\x00\x01\x02" * 50)
    return str(path)


# --------------------------------------------------------------------------- #
# 1-2. Missing / corrupted zip handling                                       #
# --------------------------------------------------------------------------- #
def test_missing_zip_is_blocked_fail_closed(tmp_path):
    report = run_zip_simulation(str(tmp_path / "nope.zip"))
    assert report["status"] == "BLOCKED"
    assert report["safety"]["reason"] == "file_not_found"
    assert report["diagnostics"]["usable_records"] == 0
    # Only guardrail preservation may be non-zero; it must be preserved (Δ0).
    g = report["scores"]["segments"]["advisory_guardrail_preservation"]
    assert g["before"] == 100.0 and g["after"] == 100.0


def test_corrupted_zip_is_blocked(tmp_path):
    bad = tmp_path / "broken.zip"
    bad.write_bytes(b"PK\x03\x04 not really a zip at all")
    res = ZipSafetyValidator().validate_archive(str(bad))
    assert res.status is SafetyStatus.BLOCKED
    assert "corrupted" in res.reason or "unreadable" in res.reason
    report = run_zip_simulation(str(bad))
    assert report["status"] == "BLOCKED"


def test_non_zip_extension_blocked(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("hello")
    res = ZipSafetyValidator().validate_archive(str(f))
    assert res.status is SafetyStatus.BLOCKED
    assert res.reason == "extension_not_zip"


# --------------------------------------------------------------------------- #
# 3-4. Zip-slip + absolute path rejection                                     #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "path,expected",
    [
        ("../../evil.py", True),
        ("a/../../b", True),
        ("/etc/passwd", True),
        ("C:\\Windows\\system32", True),
        ("\\\\host\\share\\x", True),
        ("normal/file.txt", False),
        ("a/b/c.csv", False),
    ],
)
def test_unsafe_member_path_detection(path, expected):
    blocked, _ = is_unsafe_member_path(path)
    assert blocked is expected


def test_zip_with_slip_member_is_blocked(tmp_path):
    p = tmp_path / "slip.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("good.txt", "ok")
        # Force a traversal name into the central directory.
        info = zipfile.ZipInfo("../../evil.py")
        z.writestr(info, "print('pwned')")
    res = ZipSafetyValidator().validate_archive(str(p))
    assert res.status is SafetyStatus.BLOCKED
    assert "unsafe_member_paths" in res.reason
    report = run_zip_simulation(str(p))
    assert report["status"] == "BLOCKED"
    assert report["diagnostics"]["usable_records"] == 0


# --------------------------------------------------------------------------- #
# 5. Compression ratio warning                                                #
# --------------------------------------------------------------------------- #
def test_extreme_compression_ratio_warns_not_crashes(tmp_path):
    p = tmp_path / "ratio.zip"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("big.txt", "A" * (2 * 1024 * 1024))  # very compressible
    cfg = SafetyConfig(cr_total_max=50.0)
    res = ZipSafetyValidator(cfg).validate_archive(str(p))
    assert res.cr_total > 50.0
    assert res.status is SafetyStatus.WARNING  # flagged, not blocked
    report = run_zip_simulation(str(p), config=cfg)
    assert report["status"] in ("WARNING", "SAFE")


# --------------------------------------------------------------------------- #
# 6-7. Manifest generation + classification                                   #
# --------------------------------------------------------------------------- #
def test_manifest_and_family_classification(tmp_path):
    zp = _build_good_zip(tmp_path / "good.zip")
    report = run_zip_simulation(zp, corpus_label="SYNTHETIC_FIXTURE")
    fams = report["manifest"]["family_counts"]
    assert fams.get("chess_pgn", 0) == 1
    assert fams.get("market_or_finance_data", 0) == 1
    assert fams.get("hackathon_project", 0) >= 1
    assert report["manifest"]["member_count"] >= 7
    # every manifest entry carries a provenance id
    for f in report["manifest"]["files"]:
        assert len(f["provenance_id"]) == 64


def test_classifier_confidence_bands():
    c = DatasetClassifier()
    res = c.classify("chess/g.pgn", b'[Event "x"]\n[White "a"]\n[Result "1-0"]')
    assert res.family is DatasetFamily.CHESS_PGN
    assert res.confidence_class in (
        ConfidenceClass.HIGH_CONFIDENCE, ConfidenceClass.MEDIUM_CONFIDENCE
    )
    unknown = c.classify("misc/blob.bin", b"\x00\x01\x02")
    assert unknown.family is DatasetFamily.UNKNOWN


# --------------------------------------------------------------------------- #
# 8-11. Parsers on tiny fixtures                                              #
# --------------------------------------------------------------------------- #
def test_pgn_parser_features():
    games = PgnParser().parse(_pgn_text(10), "prov" * 16)
    assert len(games) == 10
    g = games[0]
    assert g.white_elo == 1500 and g.black_elo == 1200
    # White favored (ΔElo +300) => expected > 0.5
    assert g.expected_white > 0.5
    upsets = [x for x in games if x.upset == 1]
    assert len(upsets) >= 1  # the engineered 0-1 results are upsets
    assert any(x.timeout_flag for x in games)


def test_hackathon_parser_metrics_bounded():
    proj = HackathonParser().parse(
        "# T\nproblem pain challenge user need why\nsolution build prototype", "p" * 64
    )
    for v in (
        proj.problem_clarity, proj.solution_specificity, proj.demo_readiness
    ):
        assert 0.0 <= v <= 1.0
    assert proj.problem_clarity == 1.0  # all 6 problem keywords present


def test_scraped_parser_source_inference():
    doc = ScrapedTextParser().parse(
        "https://reddit.com/r/x\nhello", "p" * 64, "scrape/reddit_1.txt"
    )
    assert doc.source == "reddit"
    assert len(doc.normalized_hash) == 64


def test_market_parser_no_data_below_threshold():
    res = MarketParser().parse("ticker,date,close\nAAPL,2021-01-01,100", "p" * 64, "m.csv")
    assert res["status"] == "NO_DATA"  # only 1 row < 100


def test_market_parser_ok_with_enough_rows():
    res = MarketParser().parse(_market_csv(150), "p" * 64, "market/prices.csv")
    assert res["status"] == "OK"
    assert res["valid_price_rows"] >= 100
    assert "cumulative_return" in res["metrics"]
    # No probability column => calibration stays NO_DATA (never faked)
    assert res["metrics"]["calibration"]["status"] == "NO_DATA"


def test_market_parser_rejects_non_market_csv():
    res = MarketParser().parse("a,b,c\n1,2,3\n4,5,6", "p" * 64, "x.csv")
    assert res["status"] == "NO_DATA"
    assert "schema" in res["reason"]


# --------------------------------------------------------------------------- #
# 12. Provenance hash determinism                                             #
# --------------------------------------------------------------------------- #
def test_provenance_id_deterministic():
    h = ProvenanceHasher()
    a = h.provenance_id("C:/x/z.zip", "chess/g.pgn", "deadbeef")
    b = h.provenance_id("C:\\x\\z.zip", "chess/g.pgn", "deadbeef")
    assert a == b and len(a) == 64
    diff = h.provenance_id("C:/x/z.zip", "chess/h.pgn", "deadbeef")
    assert diff != a


def test_streaming_sha_matches_full_hash(tmp_path):
    import hashlib
    p = tmp_path / "h.zip"
    payload = b"hello sleeping passenger" * 1000
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("a.txt", payload)
    with zipfile.ZipFile(p, "r") as z:
        info = z.getinfo("a.txt")
        digest, read, trunc = ProvenanceHasher(chunk_size=64).sha256_member(z, info)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert read == len(payload) and trunc is False


# --------------------------------------------------------------------------- #
# 13-14. Score determinism + test-failure cap                                 #
# --------------------------------------------------------------------------- #
def test_scores_deterministic(tmp_path):
    zp = _build_good_zip(tmp_path / "good.zip")
    a = run_zip_simulation(zp)["scores"]
    b = run_zip_simulation(zp)["scores"]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_tests_failing_caps_overall_at_60(tmp_path):
    zp = _build_good_zip(tmp_path / "good.zip")
    report = run_zip_simulation(zp, tests_pass=False)
    o = report["scores"]["overall"]
    assert o["overall_after"] <= 60.0
    assert "tests_failed_cap_60" in o["caps_applied"]


def test_guardrails_broken_caps_overall_at_30(tmp_path):
    zp = _build_good_zip(tmp_path / "good.zip")
    report = run_zip_simulation(zp, guardrails_ok=False)
    o = report["scores"]["overall"]
    assert o["overall_after"] <= 30.0
    assert "guardrails_broken_cap_30" in o["caps_applied"]


def test_weights_sum_to_one():
    scoring.assert_weights_sum_to_one(scoring.DEFAULT_WEIGHTS)
    assert abs(sum(scoring.DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9


# --------------------------------------------------------------------------- #
# 15. Advisory-only guardrail preservation                                    #
# --------------------------------------------------------------------------- #
def test_outputs_are_labeled_simulation_only(tmp_path):
    zp = _build_good_zip(tmp_path / "good.zip")
    report = run_zip_simulation(zp)
    assert set(SIMULATION_LABELS) == {
        "SIMULATION_ONLY", "ZIP_CORPUS_DERIVED", "NOT_LIVE_TRADING_EVIDENCE",
        "NOT_BROKER_DATA", "NOT_FINANCIAL_ADVICE",
    }
    assert report["labels"]["labels"] == list(SIMULATION_LABELS)
    assert report["scores"]["overall"]["label"] == "SIMULATION_ONLY"


def test_subsystem_has_no_execution_or_broker_logic():
    import pathlib
    pkg = pathlib.Path("src/simulation_zip")
    forbidden = (
        "place_order", "submit_order", "execute_trade", "broker_execute",
        "import alpaca", "import ib_insync", "import ccxt",
    )
    for f in pkg.glob("*.py"):
        src = f.read_text(encoding="utf-8").lower()
        for tok in forbidden:
            assert tok not in src, (f.name, tok)


def test_guardrail_preserved_means_zero_delta(tmp_path):
    zp = _build_good_zip(tmp_path / "good.zip")
    seg = run_zip_simulation(zp)["scores"]["segments"][
        "advisory_guardrail_preservation"
    ]
    assert seg["before"] == 100.0 and seg["after"] == 100.0
    assert seg["delta"] == 0.0  # preserved, not "improved"


# --------------------------------------------------------------------------- #
# 16. CLI smoke test                                                          #
# --------------------------------------------------------------------------- #
def test_cli_smoke_writes_reports(tmp_path, capsys):
    zp = _build_good_zip(tmp_path / "good.zip")
    out = tmp_path / "reports"
    rc = cli_run(["--zip", zp, "--out-dir", str(out), "--corpus-label", "SYNTHETIC_FIXTURE"])
    assert rc == 0
    written = list(out.glob("zip_simulation_*"))
    names = " ".join(p.name for p in written)
    for stem in ("inventory", "run", "scores", "summary", "integration"):
        assert stem in names
    # run report is valid deterministic JSON with labels
    run_json = next(out.glob("zip_simulation_run_*.json"))
    data = json.loads(run_json.read_text())
    assert data["labels"]["labels"][0] == "SIMULATION_ONLY"


def test_cli_missing_path_fails_closed(capsys):
    rc = cli_run(["--zip", ""])
    assert rc == 2


# --------------------------------------------------------------------------- #
# Math sanity                                                                  #
# --------------------------------------------------------------------------- #
def test_elo_and_brier_math():
    assert abs(metrics.elo_expected_white(0) - 0.5) < 1e-9
    assert metrics.elo_expected_white(400) > 0.9
    assert metrics.brier_score([(1.0, 1.0), (0.0, 0.0)]) == 0.0
    assert metrics.brier_score([(1.0, 0.0)]) == 1.0


def test_shannon_diversity_bounds():
    assert metrics.shannon_diversity({"a": 1})["normalized_diversity"] == 0.0
    two = metrics.shannon_diversity({"a": 5, "b": 5})
    assert abs(two["normalized_diversity"] - 1.0) < 1e-9
