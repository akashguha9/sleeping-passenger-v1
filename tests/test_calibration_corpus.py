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
