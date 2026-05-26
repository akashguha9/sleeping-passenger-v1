"""Calibration corpus curation tests.

Calibration Corpus + Hosted Canary sprint, Phase 1.

What this verifies
------------------
* Dedupe by stable SHA-256 key.
* ``source == "fixture_test_only"`` records do NOT count toward
  ``N_real``.
* ``provenance.mock_fallback`` and ``provenance.fallback_used`` records
  are excluded from ``N_real``.
* Records missing ``model_probability`` or ``outcome_label`` are
  rejected by the validity check (``corpus_validity == 0``).
* ``model_probability`` outside ``[0, 1]`` is rejected.
* ``outcome_label`` outside ``{0, 1}`` is rejected.
* ``EvidenceStatus`` is INSUFFICIENT_EVIDENCE when ``N_real < 200``,
  MEASURABLE otherwise.
* SQLite curation skips the 813 quarantined fake manual trades.
* The build envelope carries advisory stamps and no broker / order
  language.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from scripts.curate_calibration_corpus import (
    CorpusRecord,
    SAFETY_STAMPS,
    build_corpus,
    dedupe_records,
    gather_from_sqlite,
    load_fixture_records,
    stable_dedupe_key,
    validate_corpus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(
    *,
    record_id: str = "r1",
    source: str = "manual_trade",
    source_record_id: str = "sr1",
    asset: str = "SPY",
    signal_ts: str = "2026-05-10T06:10:36+00:00",
    outcome_ts: str = "2026-05-12T06:10:36+00:00",
    horizon: float = 2.0,
    p: float | None = 0.6,
    label: int = 1,
    definition: str = "spy_d2_up",
    mock_fallback: bool = False,
    fallback_used: bool = False,
    truth_source: str = "sqlite",
) -> dict[str, Any]:
    snap: dict[str, Any] = {
        "EMS": None, "EQS": None, "DS": None,
        "LS": None, "EFS": None, "APS": None,
    }
    if p is not None:
        snap["model_probability"] = p
    rec = CorpusRecord(
        record_id=record_id,
        source=source,
        source_record_id=source_record_id,
        asset_or_market=asset,
        signal_timestamp_utc=signal_ts,
        outcome_timestamp_utc=outcome_ts,
        horizon_days=horizon,
        score_snapshot=snap,
        outcome_label=label,
        outcome_definition=definition,
        provenance={
            "truth_source": truth_source,
            "canonical": True,
            "mock_fallback": mock_fallback,
            "fallback_used": fallback_used,
            "url_or_source_hint_redacted": "test",
            "collected_at_utc": "2026-05-26T00:00:00+00:00",
        },
    ).to_dict()
    return rec


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------


def test_stable_dedupe_key_is_deterministic_and_lowercase_normalised():
    a = _record(record_id="A", source="Manual_Trade", asset="spy")
    b = _record(record_id="B", source="MANUAL_TRADE", asset="SPY")
    assert stable_dedupe_key(a) == stable_dedupe_key(b)


def test_dedupe_keeps_first_occurrence():
    a = _record(record_id="A")
    b = _record(record_id="B")  # same dedupe key — only first kept
    c = _record(record_id="C", source_record_id="sr2")
    deduped = dedupe_records([a, b, c])
    assert [r["record_id"] for r in deduped] == ["A", "C"]


# ---------------------------------------------------------------------------
# Validity math
# ---------------------------------------------------------------------------


def test_fixture_records_do_not_count_as_real_evidence():
    real = _record(record_id="r1", source="manual_trade")
    fixture = _record(record_id="f1", source="fixture_test_only", source_record_id="fx")
    metrics = validate_corpus([real, fixture])
    assert metrics["n_total"] == 2
    assert metrics["n_real"] == 1
    assert metrics["n_fixture"] == 1


def test_mock_fallback_records_do_not_count_as_real_evidence():
    real = _record(record_id="r1", source="manual_trade")
    mocked = _record(record_id="r2", source="manual_trade",
                     source_record_id="sr2", mock_fallback=True)
    fb_used = _record(record_id="r3", source="manual_trade",
                      source_record_id="sr3", fallback_used=True)
    metrics = validate_corpus([real, mocked, fb_used])
    assert metrics["n_total"] == 3
    assert metrics["n_real"] == 1
    assert metrics["n_mock"] == 2


def test_missing_outcome_invalidates_corpus():
    rec = _record(record_id="r1", label=99)  # invalid outcome
    metrics = validate_corpus([rec])
    assert metrics["n_valid_y"] == 0
    assert metrics["corpus_validity"] is False


def test_probability_outside_unit_interval_invalidates_corpus():
    rec = _record(record_id="r1", p=1.5)
    metrics = validate_corpus([rec])
    assert metrics["n_valid_p"] == 0
    assert metrics["corpus_validity"] is False


def test_corpus_below_n_min_yields_insufficient_evidence():
    recs = [_record(record_id=f"r{i}", source_record_id=f"sr{i}") for i in range(50)]
    metrics = validate_corpus(recs)
    assert metrics["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert metrics["corpus_coverage_score"] == 2.5  # 10 * 50/200
    assert metrics["corpus_validity"] is False  # also fails n_min


def test_corpus_at_n_min_with_valid_inputs_is_measurable_and_valid():
    recs = [_record(record_id=f"r{i}", source_record_id=f"sr{i}") for i in range(200)]
    metrics = validate_corpus(recs)
    assert metrics["evidence_status"] == "MEASURABLE"
    assert metrics["corpus_validity"] is True
    assert metrics["n_real"] == 200
    assert metrics["n_deduped"] == 200


# ---------------------------------------------------------------------------
# Build envelope safety
# ---------------------------------------------------------------------------


def test_build_corpus_default_emits_advisory_stamps_and_metrics():
    envelope = build_corpus(
        from_sqlite=None,
        include_polymarket_closed=False,
        from_fixture=None,
        max_records=10,
    )
    for k, v in SAFETY_STAMPS.items():
        assert envelope[k] == v, f"safety stamp {k} missing or wrong on envelope"
    assert envelope["metrics"]["n_total"] == 0
    assert envelope["metrics"]["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert envelope["records"] == []


def test_build_corpus_forbidden_words_absent_from_envelope():
    envelope = build_corpus(
        from_sqlite=None,
        include_polymarket_closed=False,
        from_fixture=None,
        max_records=10,
    )
    blob = json.dumps(envelope).lower()
    for word in ("/orders", "/order", "broker_order", "place_order", "execute_trade"):
        assert word not in blob, f"forbidden token in envelope: {word}"


def test_build_corpus_with_fixture(tmp_path: Path):
    fx = tmp_path / "fx.json"
    fx.write_text(json.dumps([
        {
            "record_id": "fixture-1",
            "source": "fixture_test_only",
            "source_record_id": "FX1",
            "asset_or_market": "TEST",
            "signal_timestamp_utc": "2026-01-01T00:00:00+00:00",
            "outcome_timestamp_utc": "2026-01-02T00:00:00+00:00",
            "horizon_days": 1.0,
            "score_snapshot": {"model_probability": 0.55},
            "outcome_label": 1,
            "outcome_definition": "test_fixture",
            "provenance": {"truth_source": "test_fixture"},
        }
    ]), encoding="utf-8")
    envelope = build_corpus(
        from_sqlite=None,
        include_polymarket_closed=False,
        from_fixture=fx,
        max_records=10,
    )
    assert envelope["metrics"]["n_total"] == 1
    assert envelope["metrics"]["n_fixture"] == 1
    assert envelope["metrics"]["n_real"] == 0
    assert envelope["metrics"]["evidence_status"] == "INSUFFICIENT_EVIDENCE"


# ---------------------------------------------------------------------------
# SQLite ingestion
# ---------------------------------------------------------------------------


def _make_sqlite_with_trades(db_path: Path) -> None:
    """Build a minimal SQLite DB shaped like ``runtime/mvp_local.db``
    for tests — manual_trades + reconciliation_results only.  We do not
    use the real DB so the test is hermetic.
    """
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE manual_trades (
              trade_id TEXT PRIMARY KEY,
              event_id TEXT,
              ticker TEXT,
              executed_at TEXT,
              created_via TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE reconciliation_results (
              reconciliation_id INTEGER PRIMARY KEY AUTOINCREMENT,
              trade_id TEXT,
              outcome_status TEXT,
              reconciled_at TEXT
            )
            """
        )
        cur.executemany(
            "INSERT INTO manual_trades (trade_id, event_id, ticker, executed_at, created_via) "
            "VALUES (?,?,?,?,?)",
            [
                ("MT_REAL_WIN", "EV1", "SPY", "2026-05-01T00:00:00+00:00", "manual_trade_log"),
                ("MT_REAL_LOSS", "EV2", "QQQ", "2026-05-02T00:00:00+00:00", "manual_trade_log"),
                ("MT_QUARANTINED", "EV3", "FAKE", "2026-05-03T00:00:00+00:00",
                 "quarantined_fake_manual_trade"),
            ],
        )
        cur.executemany(
            "INSERT INTO reconciliation_results (trade_id, outcome_status, reconciled_at) "
            "VALUES (?,?,?)",
            [
                ("MT_REAL_WIN", "WIN", "2026-05-04T00:00:00+00:00"),
                ("MT_REAL_LOSS", "LOSS", "2026-05-05T00:00:00+00:00"),
                ("MT_QUARANTINED", "WIN", "2026-05-06T00:00:00+00:00"),  # should be excluded
            ],
        )
        con.commit()
    finally:
        con.close()


def test_sqlite_ingestion_skips_quarantined_rows(tmp_path: Path):
    db = tmp_path / "mvp.db"
    _make_sqlite_with_trades(db)
    rows = gather_from_sqlite(db)
    assert len(rows) == 2
    ids = {r["source_record_id"] for r in rows}
    assert ids == {"MT_REAL_WIN", "MT_REAL_LOSS"}
    for rec in rows:
        assert rec["advisory_status"] == "ADVISORY_ONLY"
        assert rec["execution_gate"] == "LOCKED"
        assert rec["broker_api_called"] is False
        assert rec["ai_execution_count"] == 0


def test_sqlite_missing_db_yields_no_rows(tmp_path: Path):
    rows = gather_from_sqlite(tmp_path / "absent.db")
    assert rows == []


# ---------------------------------------------------------------------------
# Probability-snapshot bridge
# ---------------------------------------------------------------------------


def _make_sqlite_with_snapshots(db_path: Path, *, p_yes: float, p_no: float) -> None:
    """Build a hermetic DB with manual trades + reconciliations + a
    probability_snapshots row for each event.
    """
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE manual_trades (
              trade_id TEXT PRIMARY KEY,
              event_id TEXT,
              ticker TEXT,
              executed_at TEXT,
              created_via TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE reconciliation_results (
              reconciliation_id INTEGER PRIMARY KEY AUTOINCREMENT,
              trade_id TEXT,
              outcome_status TEXT,
              reconciled_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE probability_snapshots (
              signal_id TEXT PRIMARY KEY,
              generated_at_utc TEXT,
              model_probability REAL,
              probability_formula_version TEXT,
              EMS REAL, EQS REAL, DS REAL, LS REAL, EFS REAL, APS REAL,
              raw_score REAL,
              chaos_risk REAL,
              staleness_penalty REAL,
              mock_penalty REAL,
              advisory_status TEXT,
              execution_gate TEXT,
              broker_api_called INTEGER,
              ai_execution_count INTEGER
            )
            """
        )
        cur.executemany(
            "INSERT INTO manual_trades (trade_id, event_id, ticker, executed_at, created_via) "
            "VALUES (?,?,?,?,?)",
            [
                ("MT_WIN", "EV_WIN", "SPY", "2026-05-01T00:00:00+00:00", "manual_trade_log"),
                ("MT_LOSS", "EV_LOSS", "QQQ", "2026-05-02T00:00:00+00:00", "manual_trade_log"),
            ],
        )
        cur.executemany(
            "INSERT INTO reconciliation_results (trade_id, outcome_status, reconciled_at) "
            "VALUES (?,?,?)",
            [
                ("MT_WIN", "WIN", "2026-05-04T00:00:00+00:00"),
                ("MT_LOSS", "LOSS", "2026-05-05T00:00:00+00:00"),
            ],
        )
        cur.executemany(
            "INSERT INTO probability_snapshots (signal_id, generated_at_utc, "
            "model_probability, probability_formula_version, EMS, EQS, DS, LS, EFS, APS, "
            "raw_score, chaos_risk, staleness_penalty, mock_penalty, advisory_status, "
            "execution_gate, broker_api_called, ai_execution_count) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    "EV_WIN", "2026-05-01T00:00:00+00:00", p_yes, "v1",
                    0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.0, 0.0, 0.0,
                    "ADVISORY_ONLY", "LOCKED", 0, 0,
                ),
                (
                    "EV_LOSS", "2026-05-02T00:00:00+00:00", p_no, "v1",
                    0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.0, 0.0, 0.0,
                    "ADVISORY_ONLY", "LOCKED", 0, 0,
                ),
            ],
        )
        con.commit()
    finally:
        con.close()


def test_sqlite_bridge_attaches_probability_snapshot(tmp_path: Path):
    db = tmp_path / "bridge.db"
    _make_sqlite_with_snapshots(db, p_yes=0.7, p_no=0.4)
    rows = gather_from_sqlite(db)
    assert len(rows) == 2
    by_id = {r["source_record_id"]: r for r in rows}
    win = by_id["MT_WIN"]
    loss = by_id["MT_LOSS"]
    assert win["score_snapshot"]["model_probability"] == 0.7
    assert loss["score_snapshot"]["model_probability"] == 0.4
    assert win["provenance"]["bridged_from_probability_snapshot"] is True
    assert win["provenance"]["probability_formula_version"] == "v1"
    assert win["outcome_label"] == 1
    assert loss["outcome_label"] == 0


def test_sqlite_bridge_produces_calibration_pairs_with_class_balance(tmp_path: Path):
    db = tmp_path / "bridge.db"
    _make_sqlite_with_snapshots(db, p_yes=0.7, p_no=0.4)
    rows = gather_from_sqlite(db)
    metrics = validate_corpus(rows)
    assert metrics["n_pairs"] == 2
    assert metrics["base_rate"] == 0.5
    assert metrics["class_imbalance"] == 0.0
    assert metrics["class_balance_warning"] == "OK"


def test_class_balance_warning_when_all_losses(tmp_path: Path):
    """If only loss-only outcomes exist, the class_balance_warning must
    trip — the gate must not treat a one-sided corpus as predictive.
    """
    recs = [
        _record(record_id=f"r{i}", source_record_id=f"sr{i}", label=0, p=0.4)
        for i in range(10)
    ]
    metrics = validate_corpus(recs)
    assert metrics["n_pairs"] == 10
    assert metrics["base_rate"] == 0.0
    assert metrics["class_imbalance"] == 1.0
    assert metrics["class_balance_warning"] == "HIGH_CLASS_IMBALANCE"


def test_no_pairs_when_probability_missing():
    rec = _record(record_id="r1", source_record_id="sr1", p=None)
    metrics = validate_corpus([rec])
    assert metrics["n_pairs"] == 0
    assert metrics["base_rate"] is None
    assert metrics["class_balance_warning"] == "NO_PAIRS"


def test_unmatched_trade_does_not_create_calibration_pair(tmp_path: Path):
    """A trade without a probability_snapshots row stays in the corpus
    for provenance but has no ``model_probability`` and is not counted
    toward calibration pairs.
    """
    db = tmp_path / "no_snap.db"
    _make_sqlite_with_trades(db)  # legacy fixture, no probability_snapshots
    rows = gather_from_sqlite(db)
    assert all("model_probability" not in r["score_snapshot"] for r in rows)
    metrics = validate_corpus(rows)
    assert metrics["n_pairs"] == 0
    assert metrics["class_balance_warning"] == "NO_PAIRS"


def test_fixture_load_marks_records_as_fixture_test_only(tmp_path: Path):
    fx = tmp_path / "fx.json"
    fx.write_text(json.dumps([
        {
            "record_id": "x1",
            "source": "manual_trade",  # should be overridden
            "source_record_id": "X1",
            "asset_or_market": "T",
            "signal_timestamp_utc": "2026-01-01T00:00:00+00:00",
            "outcome_timestamp_utc": "2026-01-02T00:00:00+00:00",
            "horizon_days": 1.0,
            "score_snapshot": {"model_probability": 0.7},
            "outcome_label": 1,
            "outcome_definition": "f",
        }
    ]), encoding="utf-8")
    rows = load_fixture_records(fx)
    assert len(rows) == 1
    assert rows[0]["source"] == "fixture_test_only"
    assert rows[0]["provenance"]["truth_source"] == "test_fixture"
