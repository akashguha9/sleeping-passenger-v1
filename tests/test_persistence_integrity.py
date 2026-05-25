"""Tests for ``scripts.persistence_integrity`` — idempotent upsert, source-run
ledger, schema metadata, JSONL non-canonical guard, summary artifact."""
from __future__ import annotations

import json

import pytest

from scripts import persistence_integrity as pi


@pytest.fixture()
def conn():
    c = pi.open_db()
    try:
        yield c
    finally:
        c.close()


def test_canonical_json_strips_volatile_keys_and_is_deterministic():
    a = {"x": 1, "ingested_at_utc": "2026-05-24T10:00:00Z"}
    b = {"ingested_at_utc": "2026-05-24T11:00:00Z", "x": 1}
    assert pi.canonical_json(a) == pi.canonical_json(b)
    # Two calls on the same input must be byte-identical.
    assert pi.canonical_json(a) == pi.canonical_json(a)


def test_payload_hash_is_deterministic_and_changes_on_real_change():
    p1 = {"price": 100.0, "ingested_at_utc": "x"}
    p2 = {"price": 100.0, "ingested_at_utc": "y"}
    p3 = {"price": 100.5, "ingested_at_utc": "x"}
    assert pi.payload_hash(p1) == pi.payload_hash(p2)
    assert pi.payload_hash(p1) != pi.payload_hash(p3)


def test_event_id_is_deterministic():
    id1 = pi.compute_event_id(
        provider="yfinance", source_type="price_mover", event_type="quote",
        provider_event_timestamp_utc="2026-05-24T10:00:00Z",
        asset_tags=["ABC"], normalized_key="ABC quote",
    )
    id2 = pi.compute_event_id(
        provider="YFinance", source_type="PRICE_MOVER", event_type="QUOTE",
        provider_event_timestamp_utc="2026-05-24T10:00:30Z",  # same minute
        asset_tags=["abc"], normalized_key="ABC  quote",  # double-space
    )
    assert id1 == id2


def test_same_event_inserted_twice_creates_one_canonical_row(conn):
    run = pi.start_source_run(conn, provider="p", source_type="s")
    payload = {"x": 1, "ingested_at_utc": "ts1"}
    a = pi.upsert_signal_event(
        conn, provider="p", source_type="s", event_type="e",
        asset_tags=["X"], provider_event_timestamp_utc="2026-05-24T10:00:00Z",
        normalized_key="X event", payload=payload, source_run_id=run,
    )
    b = pi.upsert_signal_event(
        conn, provider="p", source_type="s", event_type="e",
        asset_tags=["X"], provider_event_timestamp_utc="2026-05-24T10:00:00Z",
        normalized_key="X event",
        payload={"x": 1, "ingested_at_utc": "ts2"},
        source_run_id=run,
    )
    assert a["operation"] == "inserted"
    assert b["operation"] == "deduplicated"
    count = conn.execute(
        "SELECT COUNT(*) FROM canonical_signal_events"
    ).fetchone()[0]
    assert count == 1


def test_changed_payload_creates_revision_not_duplicate(conn):
    run = pi.start_source_run(conn, provider="p", source_type="s")
    base = dict(provider="p", source_type="s", event_type="e",
                asset_tags=["Y"],
                provider_event_timestamp_utc="2026-05-24T10:00:00Z",
                normalized_key="Y event", source_run_id=run)
    pi.upsert_signal_event(conn, payload={"v": 1}, **base)
    revised = pi.upsert_signal_event(conn, payload={"v": 2}, **base)
    assert revised["operation"] == "revised"
    assert revised["revision_number"] == 1
    count = conn.execute(
        "SELECT COUNT(*) FROM canonical_signal_events"
    ).fetchone()[0]
    assert count == 1
    row = conn.execute(
        "SELECT supersedes_event_id, revision_number, advisory_only, "
        "execution_permission FROM canonical_signal_events"
    ).fetchone()
    assert row["supersedes_event_id"] == revised["event_id"]
    assert row["revision_number"] == 1
    assert row["advisory_only"] == 1
    assert row["execution_permission"] == "ADVISORY_ONLY"


def test_source_run_ledger_records_success_and_failure(conn):
    ok_id = pi.start_source_run(conn, provider="ok_provider", source_type="news")
    pi.finish_source_run(conn, ok_id, status="SUCCESS", events_seen=3,
                         events_inserted=2)
    bad_id = pi.start_source_run(conn, provider="bad_provider", source_type="news")
    pi.finish_source_run(conn, bad_id, status="FAILED", error="network refused")
    rows = {r["source_run_id"]: r
            for r in conn.execute("SELECT * FROM source_runs").fetchall()}
    assert rows[ok_id]["status"] == "SUCCESS"
    assert rows[ok_id]["events_seen"] == 3
    assert rows[bad_id]["status"] == "FAILED"
    assert rows[bad_id]["error"] == "network refused"


def test_finish_source_run_rejects_invalid_status(conn):
    rid = pi.start_source_run(conn, provider="p", source_type="s")
    with pytest.raises(ValueError):
        pi.finish_source_run(conn, rid, status="MAYBE")


def test_schema_metadata_present(conn):
    meta = pi.get_schema_metadata(conn)
    for required in pi.SCHEMA_VERSIONS:
        assert required in meta
        assert meta[required] == pi.SCHEMA_VERSIONS[required]


def test_jsonl_canonicality_guard_holds():
    proof = pi.jsonl_canonicality_proof()
    assert proof["sqlite_is_canonical"] is True
    assert proof["jsonl_is_canonical"] is False
    assert proof["guard_pass"] is True
    assert "audit" in proof["jsonl_allowed_roles"]


def test_evaluate_summary_meets_target_in_fixture_mode():
    summary = pi.evaluate(fixture_mode=True)
    assert summary["ok"] is True
    assert summary["persistence_integrity_score"] >= 9.8
    assert summary["idempotent_upsert_pass"] is True
    assert summary["source_run_ledger_present"] is True
    assert summary["jsonl_noncanonical_guard_pass"] is True
    # Safety stamps are present.
    assert summary["advisory_only"] is True
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0


def test_write_summary_persists_file(tmp_path):
    target = tmp_path / "persistence_integrity_summary.json"
    out = pi.write_summary(target)
    assert target.exists()
    assert out["summary_path"] == str(target)
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["persistence_integrity_score"] >= 9.8
    assert on_disk["jsonl_guard"]["guard_pass"] is True


def test_invalid_verification_status_is_rejected(conn):
    run = pi.start_source_run(conn, provider="p", source_type="s")
    with pytest.raises(ValueError):
        pi.upsert_signal_event(
            conn, provider="p", source_type="s", event_type="e",
            asset_tags=["X"],
            provider_event_timestamp_utc="2026-05-24T10:00:00Z",
            normalized_key="X event", payload={"v": 1}, source_run_id=run,
            verification_status="BOGUS",
        )
