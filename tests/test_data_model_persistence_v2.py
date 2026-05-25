"""Tests for the v2 persistence helpers (Sprint 3 — Part 4)."""
from __future__ import annotations

import json

import pytest

from scripts import persistence_integrity as pi


def test_live_provider_evidence_writes_idempotently():
    conn = pi.open_db()
    try:
        first = pi.upsert_live_provider_evidence(
            conn, provider="yfinance", source_type="price_mover",
            run_mode="live", verification_status="LIVE_VERIFIED",
            latest_provider_timestamp_utc="2026-05-24T10:00:00Z",
            freshness_age_hours=1.0,
            payload_hash_value="hash-A",
            source_run_id="run-1",
            sample_source_url="https://finance.yahoo.com/quote/AAPL",
        )
        second = pi.upsert_live_provider_evidence(
            conn, provider="yfinance", source_type="price_mover",
            run_mode="live", verification_status="LIVE_VERIFIED",
            latest_provider_timestamp_utc="2026-05-24T10:00:00Z",
            freshness_age_hours=1.0,
            payload_hash_value="hash-A",
            source_run_id="run-1",
            sample_source_url="https://finance.yahoo.com/quote/AAPL",
        )
        assert first["operation"] == "inserted"
        assert second["operation"] == "deduplicated"
        assert first["evidence_id"] == second["evidence_id"]
        n = conn.execute(
            "SELECT COUNT(*) FROM live_provider_evidence"
        ).fetchone()[0]
        assert n == 1
    finally:
        conn.close()


def test_live_provider_evidence_distinct_payload_inserts_new_row():
    conn = pi.open_db()
    try:
        pi.upsert_live_provider_evidence(
            conn, provider="yfinance", source_type="price_mover",
            run_mode="live", verification_status="LIVE_VERIFIED",
            latest_provider_timestamp_utc="2026-05-24T10:00:00Z",
            freshness_age_hours=1.0, payload_hash_value="hash-A",
        )
        pi.upsert_live_provider_evidence(
            conn, provider="yfinance", source_type="price_mover",
            run_mode="live", verification_status="LIVE_VERIFIED",
            latest_provider_timestamp_utc="2026-05-24T10:00:00Z",
            freshness_age_hours=1.0, payload_hash_value="hash-B",
        )
        n = conn.execute(
            "SELECT COUNT(*) FROM live_provider_evidence"
        ).fetchone()[0]
        assert n == 2
    finally:
        conn.close()


def test_candidate_gate_audit_records_formula_components():
    conn = pi.open_db()
    try:
        audit = pi.insert_candidate_gate_audit(
            conn, candidate_id="AAPL-2026-05-24",
            cqs_final=0.78, eqs=0.72, fcs=0.81, ers=0.30,
            why_today_score=0.82, lpq=0.86,
            portfolio_truth_ok=True, memory_decay_ok=True,
            model_disagreement_ok=True,
            final_state="ADVISORY_CANDIDATE_HUMAN_REVIEW",
            may_promote=True,
            downgrade_reasons=[],
        )
        row = conn.execute(
            "SELECT * FROM candidate_gate_audit WHERE audit_id=?",
            (audit["audit_id"],),
        ).fetchone()
        assert row["cqs_final"] == 0.78
        assert row["lpq"] == 0.86
        assert row["may_promote"] == 1
        assert row["advisory_only"] == 1
        assert row["final_state"] == "ADVISORY_CANDIDATE_HUMAN_REVIEW"
        assert json.loads(row["downgrade_reasons_json"]) == []
    finally:
        conn.close()


def test_candidate_gate_audit_normalizes_downgrade_reasons():
    conn = pi.open_db()
    try:
        audit = pi.insert_candidate_gate_audit(
            conn, candidate_id="X",
            cqs_final=0.5, eqs=0.5, fcs=0.5, ers=0.5,
            why_today_score=0.5, lpq=0.5,
            portfolio_truth_ok=False, memory_decay_ok=False,
            model_disagreement_ok=False,
            final_state="DISCOVERY",
            may_promote=False,
            downgrade_reasons=["CQS_FINAL_LOW", "CQS_FINAL_LOW", "FCS_LOW"],
        )
        # Sorted + deduplicated.
        assert audit["downgrade_reasons"] == ["CQS_FINAL_LOW", "FCS_LOW"]
    finally:
        conn.close()


def test_audit_rejects_non_list_downgrade_reasons():
    conn = pi.open_db()
    try:
        with pytest.raises(ValueError):
            pi.insert_candidate_gate_audit(
                conn, candidate_id="X",
                cqs_final=None, eqs=None, fcs=None, ers=None,
                why_today_score=None, lpq=None,
                portfolio_truth_ok=False, memory_decay_ok=False,
                model_disagreement_ok=False,
                final_state="DISCOVERY", may_promote=False,
                downgrade_reasons="not-a-list",  # type: ignore
            )
    finally:
        conn.close()


def test_v2_summary_writes_and_carries_safety_stamps(tmp_path):
    target = tmp_path / "v2.json"
    summary = pi.write_v2_summary(target)
    assert target.exists()
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert "data_model_persistence_v2_score" in on_disk
    assert on_disk["live_provider_evidence_table_present"] is True
    assert on_disk["candidate_gate_audit_present"] is True
    assert on_disk["idempotent_live_evidence_writes"] is True
    assert on_disk["formula_component_audit_present"] is True
    assert on_disk["advisory_only"] is True
    assert on_disk["broker_api_called"] is False
    assert on_disk["ai_execution_count"] == 0


def test_v2_score_high_when_everything_passes():
    score = pi.data_model_persistence_v2_score(
        existing_persistence_integrity_score_ge_9_8=True,
        live_provider_evidence_table_present=True,
        candidate_gate_audit_present=True,
        idempotent_live_evidence_writes=True,
        formula_component_audit_present=True,
        advisory_flags_present=True,
    )
    assert score == 10.0
