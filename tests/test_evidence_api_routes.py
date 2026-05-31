"""Tests — /evidence/* read-only cockpit evidence routes (Phase 2).

Proves, deterministically and with NO network:
  1  source-truth is a pure read-only builder (no DB/file mutation)
  2  calibration route reports predictive_claim_allowed locked below the gate
  3  bundle route never reports real_money_ready
  4  live-decision route preserves advisory stamps
  5  capacity route reports UNKNOWN as risk (never silently safe)
  6  evidence routes never expose secrets
  7  evidence routes carry no execution language
  8  evidence routes import + work without FastAPI (shim path)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.api.routers import evidence_router as er


# Wording that must never appear in a read-only advisory evidence payload.
_FORBIDDEN_EXECUTION_WORDS = (
    "place order",
    "submit order",
    "buy now",
    "sell now",
    "execute trade",
    "broker_execute",
    "route order",
    "auto-trade",
    "autotrade",
)


def _assert_locked(payload: dict) -> None:
    assert payload["advisory_only"] is True
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["human_execution_required"] is True
    assert payload["real_money_ready"] is False


def _no_execution_language(payload: dict) -> None:
    blob = json.dumps(payload).lower()
    for word in _FORBIDDEN_EXECUTION_WORDS:
        assert word not in blob, f"execution language leaked: {word!r}"


# --- 1. source-truth read-only -------------------------------------------- #

def test_evidence_source_truth_route_is_read_only(tmp_path):
    # Point at a non-existent canary artifact: must degrade honestly, no writes.
    canary = tmp_path / "real_evidence_canary.json"
    db = tmp_path / "mvp.db"
    payload = er.build_source_truth_payload(canary_path=canary, db_path=db)
    assert payload["status"] == er.STATUS_DEGRADED
    assert payload["artifact_present"] is False
    assert payload["real_source_activation_count"] == 0
    assert payload["sources"] == []
    # No artifact and no DB file were created by a read.
    assert not canary.exists()
    assert not db.exists()
    _assert_locked(payload)


def test_evidence_source_truth_reads_persisted_canary(tmp_path):
    canary = tmp_path / "real_evidence_canary.json"
    canary.write_text(
        json.dumps({
            "generated_at_utc": "2026-05-31T00:00:00Z",
            "real_source_activation_count": 3,
            "fixture_source_activation_count": 0,
            "live_canonical_count": 3,
            "C_global": 0.75,
            "source_activation_target_met": True,
            "per_source": [
                {
                    "source_name": "sec_edgar",
                    "api_health_status": "OK",
                    "canonical_signal_status": "LIVE_CANONICAL",
                    "rows_added": 25,
                    "is_live_canonical": True,
                    "activated": True,
                    "canary_real": True,
                    "mock_flag": False,
                    "backfill_flag": False,
                    "source_truth_score": 0.9,
                },
                {
                    "source_name": "gdelt",
                    "api_health_status": "UNHEALTHY",
                    "canonical_signal_status": "UNHEALTHY",
                    "rows_added": 0,
                    "is_live_canonical": False,
                    "activated": False,
                    "canary_real": True,
                },
            ],
        }),
        encoding="utf-8",
    )
    payload = er.build_source_truth_payload(canary_path=canary)
    assert payload["status"] == er.STATUS_OK
    assert payload["artifact_present"] is True
    assert payload["real_source_activation_count"] == 3
    assert len(payload["sources"]) == 2
    # rows_added == 0 source is never live.
    gdelt = [s for s in payload["sources"] if s["source_name"] == "gdelt"][0]
    assert gdelt["is_live_canonical"] is False
    _assert_locked(payload)


# --- 2. calibration locked below the gate --------------------------------- #

def test_evidence_calibration_route_reports_predictive_claim_locked(tmp_path):
    db = tmp_path / "mvp.db"
    # Seed a handful of snapshots (far below N=200) so the corpus is real but
    # the gate stays locked.
    from scripts.decision_probability_snapshot import record_decision_probability

    for i in range(3):
        record_decision_probability(
            db_path=db,
            signal_id=f"SIG_{i}",
            axes={"EMS": 0.6, "EQS": 0.5, "DS": 0.4, "LS": 0.5, "EFS": 0.5, "APS": 0.5},
        )
    payload = er.build_calibration_payload(db_path=db)
    assert payload["predictive_claim_allowed"] is False
    assert payload["predictive_claim_label"] == er.PREDICTIVE_CLAIM_LOCKED
    assert payload["n_real_forward"] == 0  # no outcomes attached yet
    assert payload["calibration_status"] == er.INSUFFICIENT_EVIDENCE
    assert payload["n_valid_p"] >= 3
    _assert_locked(payload)


# --- 3. bundle never real-money-ready ------------------------------------- #

def test_evidence_bundle_route_reports_no_real_money_ready(tmp_path):
    # Missing bundle => DEGRADED but still real_money_ready False.
    missing = tmp_path / "real_evidence_bundle.json"
    payload = er.build_bundle_payload(bundle_path=missing)
    assert payload["real_money_ready"] is False
    assert payload["edge_claimed"] is False
    _assert_locked(payload)

    # Present bundle that (hypothetically) tried to claim real money — the
    # builder still surfaces the literal value, and the safety stamp pins False.
    present = tmp_path / "bundle.json"
    present.write_text(
        json.dumps({
            "generated_at_utc": "2026-05-31T00:00:00Z",
            "repo_commit": "abc123",
            "s_evidence": {"score": 0.42},
            "real_money_ready": False,
            "edge_claimed": False,
            "predictive_claim_allowed": False,
            "limitations": ["N_real_forward < 200"],
        }),
        encoding="utf-8",
    )
    payload = er.build_bundle_payload(bundle_path=present)
    assert payload["status"] == er.STATUS_OK
    assert payload["evidence_score"] == 0.42
    assert payload["real_money_ready"] is False
    _assert_locked(payload)


# --- 4. live-decision preserves advisory stamps --------------------------- #

def test_evidence_live_decision_route_preserves_advisory_stamps(tmp_path):
    db = tmp_path / "mvp.db"
    # No snapshots yet => DEGRADED but still locked.
    payload = er.build_live_decision_path_payload(db_path=db)
    assert payload["status"] == er.STATUS_DEGRADED
    assert payload["last_decision_id"] is None
    _assert_locked(payload)

    from scripts.decision_probability_snapshot import record_decision_probability

    record_decision_probability(
        db_path=db,
        signal_id="SIG_LIVE",
        ticker="AAPL",
        country="United States",
        axes={"EMS": 0.6, "EQS": 0.5, "DS": 0.4, "LS": 0.5, "EFS": 0.5, "APS": 0.5},
    )
    payload = er.build_live_decision_path_payload(db_path=db)
    assert payload["status"] == er.STATUS_OK
    assert payload["last_decision_id"] is not None
    assert payload["model_probability"] is not None
    assert payload["gate_result"]["execution_gate"] == "LOCKED"
    _assert_locked(payload)


# --- 5. capacity UNKNOWN == risk ------------------------------------------ #

def test_evidence_capacity_route_reports_unknown_as_risk():
    payload = er.build_capacity_risk_payload()
    assert payload["status"] == er.STATUS_UNKNOWN
    assert payload["capacity_ok"] is False
    assert payload["capacity_status"] == "CAPACITY_UNKNOWN"
    assert payload["block_reason"]
    _assert_locked(payload)


# --- 6. no secrets -------------------------------------------------------- #

def test_evidence_routes_do_not_expose_secrets(tmp_path):
    canary = tmp_path / "real_evidence_canary.json"
    canary.write_text(
        json.dumps({
            "real_source_activation_count": 1,
            "per_source": [
                {
                    "source_name": "sec_edgar",
                    "api_health_status": "OK",
                    "canonical_signal_status": "LIVE_CANONICAL",
                    "rows_added": 5,
                    "is_live_canonical": True,
                    "activated": True,
                    "canary_real": True,
                    # adversarial: a secret-looking key must be stripped.
                    "api_key": "SUPER_SECRET_VALUE",
                    "authorization": "Bearer leak",
                }
            ],
        }),
        encoding="utf-8",
    )
    payload = er.build_source_truth_payload(canary_path=canary)
    blob = json.dumps(payload).lower()
    assert "super_secret_value" not in blob
    assert "bearer leak" not in blob
    assert "api_key" not in blob
    assert "authorization" not in blob


# --- 7. no execution language --------------------------------------------- #

def test_evidence_routes_have_no_execution_language(tmp_path):
    db = tmp_path / "mvp.db"
    from scripts.decision_probability_snapshot import record_decision_probability

    record_decision_probability(
        db_path=db,
        signal_id="SIG_X",
        axes={"EMS": 0.6, "EQS": 0.5, "DS": 0.4, "LS": 0.5, "EFS": 0.5, "APS": 0.5},
    )
    for builder in (
        lambda: er.build_source_truth_payload(canary_path=db.parent / "none.json"),
        lambda: er.build_calibration_payload(db_path=db),
        lambda: er.build_bundle_payload(bundle_path=db.parent / "none.json"),
        lambda: er.build_live_decision_path_payload(db_path=db),
        er.build_capacity_risk_payload,
        lambda: er.build_summary_payload(db_path=db),
    ):
        _no_execution_language(builder())


# --- 8. works without FastAPI (shim) -------------------------------------- #

def test_evidence_routes_work_without_fastapi_if_repo_uses_shim():
    # build_router must succeed whether or not FastAPI is installed; the module
    # provides a shim APIRouter so the import never fails offline.
    router = er.build_router()
    assert router is not None
    # The pure handlers are importable and callable with the real (or empty) DB.
    assert callable(er.get_evidence_source_truth)
    assert callable(er.get_evidence_summary)


def test_evidence_summary_aggregates(tmp_path):
    db = tmp_path / "mvp.db"
    from scripts.decision_probability_snapshot import record_decision_probability

    record_decision_probability(
        db_path=db,
        signal_id="SIG_SUM",
        axes={"EMS": 0.6, "EQS": 0.5, "DS": 0.4, "LS": 0.5, "EFS": 0.5, "APS": 0.5},
    )
    payload = er.build_summary_payload(db_path=db)
    assert payload["predictive_claim_allowed"] is False
    assert payload["real_money_ready"] is False
    assert payload["n_valid_p"] >= 1
    _assert_locked(payload)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
