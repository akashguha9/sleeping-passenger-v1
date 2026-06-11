"""Evidence-ledger production wiring proofs (Pass 5, Phase 3)."""
from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest

from scripts import data_quality as dq
from scripts import evidence_bridge as eb
from tests.helpers import scanner_probes as probes

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC).isoformat()


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "evidence.jsonl"
    monkeypatch.setenv("MVP_EVIDENCE_LEDGER_PATH", str(path))
    monkeypatch.setenv("MVP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    return path


def _read(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]


def test_bridge_is_inert_under_pytest_without_explicit_path(monkeypatch):
    monkeypatch.delenv("MVP_EVIDENCE_LEDGER_PATH", raising=False)
    assert eb._bridge_inert() is True
    assert eb.record_evidence(
        source_type="api", source_name="x", claim="c", raw_evidence=b"r",
        observed_at=NOW,
    ) is None


def test_signal_event_chokepoint_emits_evidence(ledger, monkeypatch, tmp_path):
    import scripts.persistence as persistence

    db = tmp_path / "db.sqlite"
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=False)
    persistence.init_schema(db)
    inserted = persistence.insert_signal_event(
        f"EV_{uuid.uuid4().hex[:8]}", "gdelt",
        {"title": "ACME announces results", "symbol": "ACME",
         "url": "https://example.com/a"},
        NOW, db_path=db,
    )
    assert inserted is True
    rows = _read(ledger)
    assert len(rows) == 1
    assert rows[0]["source_name"] == "gdelt"
    assert rows[0]["symbol"] == "ACME"
    assert rows[0]["advisory_only"] is True
    assert dq.verify_ledger(ledger) == []


def test_duplicate_signal_event_emits_no_duplicate_evidence(ledger, monkeypatch, tmp_path):
    import scripts.persistence as persistence

    db = tmp_path / "db.sqlite"
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=False)
    persistence.init_schema(db)
    payload = {"title": "one story", "symbol": "ACME"}
    persistence.insert_signal_event("EV_DUP", "gdelt", payload, NOW, db_path=db)
    persistence.insert_signal_event("EV_DUP", "gdelt", payload, NOW, db_path=db)
    assert len(_read(ledger)) == 1  # INSERT OR IGNORE → no second evidence row


def test_manual_trade_reconciliation_moltbook_emit_evidence(ledger, monkeypatch, tmp_path):
    import scripts.persistence as persistence

    db = tmp_path / "db.sqlite"
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=False)
    persistence.init_schema(db)
    persistence.insert_manual_trade(
        "T1", "EV1", "ACME", "BUY", 1.0, 100.0, NOW,
        "thesis: filings momentum", "", "human", db_path=db,
    )
    persistence.insert_reconciliation(
        "R1", "T1", "EV1", NOW, 101.0, 1.0, "ok", 1.0, "WIN", db_path=db,
    )
    persistence.insert_moltbook_entry(
        "M1", "EV1", "ACME", "t", "ai", "r", "kept", "T1", "WIN",
        "none", "lesson learned", "none", "", "", NOW, db_path=db,
    )
    rows = _read(ledger)
    sources = sorted(r["source_name"] for r in rows)
    assert sources == ["manual_trade_log", "moltbook", "reconciliation"]
    assert all(r["source_type"] == "manual" for r in rows)
    assert dq.verify_ledger(ledger) == []


def test_imported_outcomes_emit_evidence(ledger, monkeypatch, tmp_path):
    import scripts.persistence as persistence

    db = tmp_path / "db.sqlite"
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=False)
    persistence.init_schema(db)
    n = persistence.insert_imported_outcomes([{
        "outcome_id": "O1", "source_type": "IMPORTED_BACKTEST",
        "ticker": "ACME", "direction": "LONG", "signal_id": "S1",
        "trade_id": "", "opened_at": NOW, "closed_at": NOW,
        "entry_price": 100.0, "exit_price": 105.0, "realized_pnl": 5.0,
        "capital_at_risk": 100.0, "leverage": 1.0, "score_at_entry": 0.7,
        "archetype": "", "signal_class": "", "jurisdiction_group": "ROW",
        "notes": "",
    }], db_path=db)
    assert n == 1
    rows = _read(ledger)
    assert len(rows) == 1 and rows[0]["source_type"] == "file"


def test_ai_report_ingestion_emits_evidence(ledger):
    from scripts import ai_report_ingestion as ai

    ai.build_ingestion_summary(
        [{"model_name": "grok", "stance": "BULLISH", "confidence": 0.7,
          "asset_tags": ["ACME"], "raw_text": "report text",
          "generated_at_utc": NOW}],
        write_summary=False,
    )
    rows = _read(ledger)
    assert len(rows) == 1
    assert rows[0]["source_type"] == "llm"
    assert rows[0]["source_name"] == "grok"


def test_audit_event_emitted_per_evidence(ledger, tmp_path):
    eb.record_evidence(source_type="api", source_name="sec_edgar",
                       claim="10-K filed", raw_evidence=b"raw",
                       observed_at=NOW, symbol="ACME")
    audit = _read(tmp_path / "audit.jsonl")
    assert any(e["event_type"] == "evidence_recorded" for e in audit)
    from scripts import verify_audit_log as val

    assert val.verify_chain(tmp_path / "audit.jsonl")["valid"] is True


def test_naive_timestamps_recorded_as_assumed_utc_with_capped_confidence(ledger):
    record = eb.record_evidence(
        source_type="api", source_name="legacy_runner", claim="naive stamp",
        raw_evidence=b"r", observed_at="2026-06-01T12:00:00",  # naive
        confidence=0.9,
    )
    assert record is not None
    assert record["confidence"] <= 0.4
    assert "assumed_utc" in record["extraction_method"]


def test_secret_looking_payloads_refused_without_breaking_caller(ledger):
    # Probe assembled at runtime so the source never contains scanner bait.
    record = eb.record_evidence(
        source_type="api", source_name="x",
        claim=probes.api_key_assignment() + " leaked into claim",
        raw_evidence=b"r", observed_at=NOW,
    )
    assert record is None  # refused by data_quality, swallowed by bridge
    assert _read(ledger) == []


def test_raw_hash_and_id_semantics_via_bridge(ledger):
    a = eb.record_evidence(source_type="api", source_name="s", claim="same claim",
                           raw_evidence=b"AAA", observed_at=NOW, symbol="ACME")
    b = eb.record_evidence(source_type="api", source_name="s", claim="same claim",
                           raw_evidence=b"BBB", observed_at=NOW, symbol="ACME")
    assert a["raw_hash"] != b["raw_hash"]
    assert a["evidence_id"] != b["evidence_id"]


def test_ledger_is_append_only_in_practice(ledger):
    eb.record_evidence(source_type="api", source_name="s", claim="one",
                       raw_evidence=b"1", observed_at=NOW)
    first = ledger.read_text(encoding="utf-8")
    eb.record_evidence(source_type="api", source_name="s", claim="two",
                       raw_evidence=b"2", observed_at=NOW)
    second = ledger.read_text(encoding="utf-8")
    assert second.startswith(first)  # strictly appended, never rewritten
