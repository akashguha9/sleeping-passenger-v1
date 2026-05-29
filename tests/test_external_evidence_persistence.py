"""External-evidence persistence — canonical snapshot store + safety proofs.

Proves that the advisory external-evidence bundle is now persisted as immutable
evidence-at-time-t in the canonical SQLite store, idempotently, with hard
advisory safety stamps, and that persistence failure degrades safe (never
blocks the daily run).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import private_scope_guard as guard
import scripts.external_evidence_persistence as eep
import scripts.persistence as persistence
from scripts.build_daily_payloads import build_all_daily_payloads
from scripts import daily_synthesis_pipeline as dsp

RUN_DATE = "2026-05-22"
GEN_AT = "2026-05-22T10:00:00+00:00"


# --------------------------------------------------------------------- helpers
def _item(
    *,
    source_name="kronos",
    evidence_type="CANDLESTICK_FORECAST",
    status="ACCEPTED_EVIDENCE_ONLY",
    route_decision="WATCH",
    score_delta=0.12,
    alignment=1.0,
    confidence_calibrated=0.6,
    forecast_return_pct=5.0,
    execution_permission="WATCH_ONLY",
    mode="stub_safe",
):
    return {
        "source_name": source_name,
        "evidence_type": evidence_type,
        "status": status,
        "route_decision": route_decision,
        "execution_permission": execution_permission,
        "watch_only": True,
        "advisory_only": True,
        "human_execution_required": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "score_delta": score_delta,
        "alignment_score": alignment,
        "reliability_weight": 0.8,
        "router_safety_multiplier": 0.25,
        "evidence_quality_multiplier": 0.7,
        "reason": "test evidence",
        "proof_status": "ACCEPTED_EVIDENCE_ONLY",
        "payload_summary": {
            "KRONOS_STATUS": "SUPPORTIVE",
            "KRONOS_MODE": mode,
            "KRONOS_FORECAST_RETURN_PCT": forecast_return_pct,
            "KRONOS_CONFIDENCE_CALIBRATED": confidence_calibrated,
            "KRONOS_DOWNSIDE_PATH_RISK": 0.1,
            "KRONOS_NOISE_PENALTY": 0.0,
            "forecast_direction": "UP",
        },
    }


def _bundle(items, *, enabled=True, status="ACCEPTED_EVIDENCE_ONLY"):
    return {
        "stage": "EXTERNAL_ADVISORY_EVIDENCE_ENRICHMENT",
        "external_evidence_enabled": enabled,
        "external_evidence_status": status,
        "external_evidence_count": len(items),
        "external_evidence_accepted_count": len(items),
        "external_evidence_rejected_count": 0,
        "external_evidence_error_count": 0,
        "external_evidence_decision_impact": "ADVISORY_CONTEXT_ONLY",
        "external_evidence_score_delta": 0.1,
        "external_evidence_items": items,
        "generated_at_utc": GEN_AT,
    }


def _ctx(signal_id="SIG1", ticker="AAPL"):
    return {"daily_run_id": RUN_DATE, "signal_id": signal_id, "ticker": ticker}


def _open(db):
    return eep._open(db)


def _count(db, table):
    conn = _open(db)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


# ----------------------------------------------------------------------- test 1
def test_external_evidence_schema_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    conn = _open(db)
    try:
        # Run a second time — must not raise.
        eep.ensure_external_evidence_schema(conn)
        eep.ensure_external_evidence_schema(conn)
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        idx = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
    finally:
        conn.close()
    for t in (
        "external_evidence_snapshots",
        "external_evidence_outcomes",
        "external_evidence_calibration_buckets",
    ):
        assert t in tables, t
    for i in (
        "idx_external_evidence_snapshot_id",
        "idx_external_evidence_signal_id",
        "idx_external_evidence_outcome_known",
        "idx_external_evidence_outcomes_learning_id",
    ):
        assert i in idx, i


# ----------------------------------------------------------------------- test 2
def test_make_external_evidence_snapshot_id_deterministic() -> None:
    base = dict(
        daily_run_id=RUN_DATE,
        signal_id="SIG1",
        ticker="AAPL",
        source_name="kronos",
        evidence_type="CANDLESTICK_FORECAST",
        generated_at_utc=GEN_AT,
        route_decision="WATCH",
    )
    a = eep.make_external_evidence_snapshot_id(**base)
    b = eep.make_external_evidence_snapshot_id(**base)
    assert a == b and len(a) == 64

    # Different source / ticker / time bucket → different hash.
    assert eep.make_external_evidence_snapshot_id(**{**base, "source_name": "x"}) != a
    assert eep.make_external_evidence_snapshot_id(**{**base, "ticker": "MSFT"}) != a
    assert (
        eep.make_external_evidence_snapshot_id(
            **{**base, "generated_at_utc": "2026-05-22T11:00:00+00:00"}
        )
        != a
    )
    # Same minute bucket → same hash (second drift is ignored).
    assert (
        eep.make_external_evidence_snapshot_id(
            **{**base, "generated_at_utc": "2026-05-22T10:00:45+00:00"}
        )
        == a
    )


# ----------------------------------------------------------------------- test 3
def test_persist_external_evidence_bundle_writes_snapshots(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    items = [
        _item(source_name="kronos", status="ACCEPTED_EVIDENCE_ONLY", route_decision="WATCH"),
        _item(source_name="tradingagents", status="ROUTER_REJECTED", route_decision="REJECT"),
        _item(source_name="trendradar", status="ERROR_SAFE", route_decision="REJECT"),
    ]
    summary = eep.persist_external_evidence_bundle(_bundle(items), _ctx(), db_path=db)
    assert summary["status"] == eep.STATUS_PERSISTED
    assert summary["persisted_count"] == 3
    assert summary["canonical_store"] == "SQLITE"
    assert summary["jsonl_is_canonical"] is False

    rows = eep.load_external_evidence_for_signal("SIG1", db_path=db)
    assert len(rows) == 3
    for r in rows:
        assert r["advisory_only"] is True
        assert r["human_execution_required"] is True
        assert r["execution_gate"] == "LOCKED"
        assert r["broker_api_called"] is False
        assert r["ai_execution_count"] == 0
        assert r["real_money_sizing_impact"] == "PROHIBITED"
        assert r["used_in_decision"] == "EVIDENCE_ONLY"
        assert r["execution_permission"] in {"WATCH_ONLY", "REJECT_ONLY"}


# ----------------------------------------------------------------------- test 4
def test_persist_external_evidence_bundle_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    items = [_item(source_name="kronos"), _item(source_name="tradingagents")]
    first = eep.persist_external_evidence_bundle(_bundle(items), _ctx(), db_path=db)
    second = eep.persist_external_evidence_bundle(_bundle(items), _ctx(), db_path=db)
    assert first["persisted_count"] == 2
    assert second["persisted_count"] == 0
    assert second["skipped_count"] == 2
    assert _count(db, "external_evidence_snapshots") == 2


# ----------------------------------------------------------------------- test 5
def test_persistence_failure_is_error_safe(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "ee.db"

    def _boom(*_a, **_k):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(eep, "_open", _boom)
    summary = eep.persist_external_evidence_bundle(_bundle([_item()]), _ctx(), db_path=db)
    assert summary["status"] == eep.STATUS_ERROR_SAFE
    assert summary["decision_impact"] == "NONE"
    assert summary["proof_status"] == "PERSISTENCE_FAILED_SAFE_NO_DECISION_IMPACT"
    assert summary["persisted_count"] == 0


# ----------------------------------------------------------------------- test 6
def _seed_payload(base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "verified_current_holdings.json").write_text(
        json.dumps({"run_date": RUN_DATE, "positions": []}), encoding="utf-8"
    )
    (base / "do_not_treat_as_open.json").write_text(
        json.dumps(
            {
                "run_date": RUN_DATE,
                "not_owned_do_not_manage": ["UNG"],
                "closed_or_sold_positions": ["GLD"],
                "operator_note": "test",
            }
        ),
        encoding="utf-8",
    )
    (base / "closed_positions.json").write_text(
        json.dumps({"run_date": RUN_DATE, "positions": [{"ticker": "GLD", "status": "CLOSED"}]}),
        encoding="utf-8",
    )
    (base / "sold_positions.json").write_text(
        json.dumps({"run_date": RUN_DATE, "tickers": ["GLD"]}), encoding="utf-8"
    )


def test_daily_synthesis_persists_external_evidence_when_enabled(
    tmp_path: Path, monkeypatch
) -> None:
    base = tmp_path / "payload"
    _seed_payload(base)
    build_all_daily_payloads(run_date=RUN_DATE, payload_dir=base)

    def _fake_bundle(*_a, **_k):
        b = _bundle([_item(source_name="kronos")])
        b["external_evidence_decision_impact"] = "ADVISORY_CONTEXT_ONLY"
        return b

    monkeypatch.setattr(dsp, "build_external_evidence_bundle", _fake_bundle)
    result = dsp.run_daily_synthesis(payload_dir=base)

    persist = result["external_evidence_persistence"]
    assert persist["status"] == "PERSISTED"
    assert persist["persisted_count"] == 1
    assert persist["canonical_store"] == "SQLITE"
    # The snapshot landed in the isolated runtime DB.
    assert _count(persistence.DB_PATH, "external_evidence_snapshots") == 1


# ----------------------------------------------------------------------- test 7
def test_daily_synthesis_no_fake_persistence_when_disabled(tmp_path: Path) -> None:
    base = tmp_path / "payload"
    _seed_payload(base)
    build_all_daily_payloads(run_date=RUN_DATE, payload_dir=base)
    # Default config keeps the framework disabled — no adapter calls, no rows.
    result = dsp.run_daily_synthesis(payload_dir=base)
    persist = result["external_evidence_persistence"]
    assert persist["status"] == "DISABLED"
    assert persist["persisted_count"] == 0
    assert persist["decision_impact"] == "NONE"
    assert _count(persistence.DB_PATH, "external_evidence_snapshots") == 0


# ---------------------------------------------------------------------- test 18
def test_external_evidence_persistence_safety_stamps(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    eep.persist_external_evidence_bundle(_bundle([_item()]), _ctx(), db_path=db)
    conn = _open(db)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT advisory_only, human_execution_required, execution_gate,"
            " broker_api_called, ai_execution_count, real_money_sizing_impact,"
            " used_in_decision FROM external_evidence_snapshots"
        )]
    finally:
        conn.close()
    assert rows, "expected at least one snapshot row"
    for r in rows:
        assert r["advisory_only"] == 1
        assert r["human_execution_required"] == 1
        assert r["execution_gate"] == "LOCKED"
        assert r["broker_api_called"] == 0
        assert r["ai_execution_count"] == 0
        assert r["real_money_sizing_impact"] == "PROHIBITED"
        assert r["used_in_decision"] == "EVIDENCE_ONLY"


# ---------------------------------------------------------------------- test 21
def test_external_evidence_sqlite_is_canonical(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    summary = eep.persist_external_evidence_bundle(_bundle([_item()]), _ctx(), db_path=db)
    assert summary["canonical_store"] == "SQLITE"
    assert summary["jsonl_is_canonical"] is False
    # No "JSONL is canonical" claim anywhere in the summary.
    blob = json.dumps(summary).lower()
    assert "jsonl" not in blob or '"jsonl_is_canonical": false' in blob


# ---------------------------------------------------------------------- test 22
def test_external_evidence_mock_not_live(tmp_path: Path) -> None:
    db = tmp_path / "ee.db"
    # Stub-safe Kronos mode must never be persisted as a live-verified read.
    eep.persist_external_evidence_bundle(
        _bundle([_item(mode="stub_safe")]), _ctx(), db_path=db
    )
    conn = _open(db)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT payload_json, proof_status, adapter_status FROM"
            " external_evidence_snapshots"
        )]
    finally:
        conn.close()
    assert rows
    for r in rows:
        payload = json.loads(r["payload_json"])
        assert payload.get("KRONOS_MODE") in {"stub_safe", "disabled"}
        blob = json.dumps(r).upper()
        assert "LIVE_VERIFIED" not in blob
        assert "LIVE_ADVISORY" not in blob


# ---------------------------------------------------------------------- test 23
def test_private_scope_guard_external_evidence_modules() -> None:
    # Sprint-scoped assertion: THIS sprint's modules must be in-scope and must
    # never appear in review_required.  We deliberately do NOT assert the
    # repo-wide ``review_required == []`` here (that global invariant is owned
    # by tests/test_private_scope_guard.py) so this test is not brittle to
    # unrelated parallel work that adds a yet-to-be-classified module.
    report = guard.build_report()
    assert report["quarantine_leaks"] == []
    for name in (
        "external_evidence_persistence.py",
        "external_evidence_moltbook_calibration.py",
        "external_evidence_calibration_backfill.py",
    ):
        assert name in report["in_scope"], name
        assert name not in report["review_required"], name
