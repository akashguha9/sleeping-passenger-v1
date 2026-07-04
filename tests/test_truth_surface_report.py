"""Tests for the operational truth surface (Close-the-Loop sprint).

Pins the audit's anti-fake-certainty rules:
* install health can never render HEALTHY on its own (N=0 caps the state);
* missing stops on active holdings -> BLOCKED, never HEALTHY;
* stale/missing holdings -> DEGRADED/BROKEN;
* BROKEN scheduler record -> BROKEN;
* zero-persisted key sources -> DEGRADED;
* calibration_status can never say CALIBRATED below the repo gate.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from scripts.truth_surface_report import (
    CAL_CALIBRATED,
    CAL_INSUFFICIENT,
    CAL_MEASURED_NOT_CALIBRATED,
    CAL_NO_EVIDENCE,
    STATE_BLOCKED,
    STATE_BROKEN,
    STATE_DEGRADED,
    STATE_HEALTHY,
    _calibration_status,
    compute_truth_surface,
)

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)

SNAP_DDL = (
    "CREATE TABLE decision_probability_snapshots ("
    "snapshot_id TEXT PRIMARY KEY, ticker TEXT, model_probability REAL,"
    "outcome_label INTEGER, is_real_outcome INTEGER, outcome_kind TEXT,"
    "excluded_from_calibration INTEGER, entry_price REAL,"
    "entry_price_timestamp_utc TEXT, horizon_close_utc TEXT)"
)
EVENTS_DDL = (
    "CREATE TABLE signal_events (id INTEGER PRIMARY KEY, event_id TEXT,"
    " source_name TEXT, raw_payload TEXT, fetched_at TEXT)"
)


def _db(tmp_path: Path, *, n_outcomes: int = 0, fresh_sources: bool = True) -> Path:
    db = tmp_path / "truth.db"
    conn = sqlite3.connect(db)
    conn.execute(SNAP_DDL)
    conn.execute(EVENTS_DDL)
    for i in range(n_outcomes):
        conn.execute(
            "INSERT INTO decision_probability_snapshots VALUES "
            "(?,?,?,?,?,?,?,?,?,?)",
            (f"S{i}", "SPY", 0.55, i % 2, 1, "real_forward", 0, 100.0,
             "2026-05-29T16:00:00Z", "2026-06-05T16:00:00Z"),
        )
    ts = "2026-07-04T10:00:00Z" if fresh_sources else "2026-06-01T10:00:00Z"
    for i, src in enumerate(("market_data", "kalshi", "polymarket")):
        conn.execute(
            "INSERT INTO signal_events VALUES (?,?,?,?,?)",
            (i + 1, f"e{i}", src, json.dumps({"symbol": "SPY"}), ts),
        )
    conn.commit()
    conn.close()
    return db


def _holdings(tmp_path: Path, *, run_date: str = "2026-07-04",
              with_stop: bool = True, leverage: int = 1) -> Path:
    f = tmp_path / "holdings.json"
    pos = {
        "ticker": "NASDAQ:ANET", "normalized_ticker": "ANET", "status": "OPEN",
        "quantity": 1.0, "entry_price": 100.0, "currency": "USD",
        "leverage": leverage, "opened_at": "2026-07-01T00:00:00Z",
        "created_via": "manual_trade_log", "broker_confirmed": False,
        "human_confirmed": True,
    }
    if with_stop:
        pos["stop_loss"] = 90.0
    f.write_text(json.dumps({"run_date": run_date, "positions": [pos]}),
                 encoding="utf-8")
    return f


def _artifact(tmp_path: Path, name: str, ts: str, status: str | None = None) -> Path:
    f = tmp_path / name
    payload = {"generated_at": ts, "timestamp": ts}
    if status:
        payload["status"] = status
    f.write_text(json.dumps(payload), encoding="utf-8")
    return f


def test_n_zero_can_never_be_healthy(tmp_path: Path) -> None:
    """Install success alone must not render HEALTHY (fake-certainty rule)."""
    surface = compute_truth_surface(
        db_path=_db(tmp_path, n_outcomes=0),
        holdings_path=_holdings(tmp_path),
        cards_json_path=_artifact(tmp_path, "cards.json", "2026-07-04T11:00:00Z"),
        scheduler_last_run_path=_artifact(
            tmp_path, "sched.json", "2026-07-04T11:00:00Z", "HEALTHY"
        ),
        now_utc=NOW,
    )
    assert surface["matured_real_outcome_count"] == 0
    assert surface["overall_operational_state"] != STATE_HEALTHY
    assert surface["calibration_status"] == CAL_NO_EVIDENCE
    assert any("N=0" in r for r in surface["state_reasons"])


def test_all_axes_clean_with_outcomes_is_healthy(tmp_path: Path) -> None:
    surface = compute_truth_surface(
        db_path=_db(tmp_path, n_outcomes=56),
        holdings_path=_holdings(tmp_path),
        cards_json_path=_artifact(tmp_path, "cards.json", "2026-07-04T11:00:00Z"),
        scheduler_last_run_path=_artifact(
            tmp_path, "sched.json", "2026-07-04T11:00:00Z", "HEALTHY"
        ),
        now_utc=NOW,
    )
    # one holding with stop but no price -> missing stop count is 0, but the
    # position is not monitorable; that alone must not block HEALTHY? No:
    # stops present, holdings fresh, sources fresh, artifacts fresh, N>0.
    assert surface["missing_stop_count"] == 0
    assert surface["overall_operational_state"] == STATE_HEALTHY
    assert surface["matured_real_outcome_count"] == 56
    # 56 >= 50 but the repo gate (N>=200, Brier<=0.25) fails -> measured, not calibrated
    assert surface["calibration_status"] == CAL_MEASURED_NOT_CALIBRATED
    assert "uncalibrated" in surface["calibration_display_note"]


def test_missing_stop_blocks(tmp_path: Path) -> None:
    surface = compute_truth_surface(
        db_path=_db(tmp_path, n_outcomes=56),
        holdings_path=_holdings(tmp_path, with_stop=False),
        cards_json_path=_artifact(tmp_path, "cards.json", "2026-07-04T11:00:00Z"),
        scheduler_last_run_path=_artifact(
            tmp_path, "sched.json", "2026-07-04T11:00:00Z", "HEALTHY"
        ),
        now_utc=NOW,
    )
    assert surface["overall_operational_state"] == STATE_BLOCKED
    assert surface["missing_stop_count"] == 1


def test_leveraged_without_stop_blocks_with_critical_reason(tmp_path: Path) -> None:
    surface = compute_truth_surface(
        db_path=_db(tmp_path, n_outcomes=56),
        holdings_path=_holdings(tmp_path, with_stop=False, leverage=4),
        cards_json_path=_artifact(tmp_path, "cards.json", "2026-07-04T11:00:00Z"),
        scheduler_last_run_path=_artifact(
            tmp_path, "sched.json", "2026-07-04T11:00:00Z", "HEALTHY"
        ),
        now_utc=NOW,
    )
    assert surface["overall_operational_state"] == STATE_BLOCKED
    assert surface["leveraged_without_stop_count"] == 1
    assert any("CRITICAL" in r for r in surface["state_reasons"])


def test_stale_holdings_degrade(tmp_path: Path) -> None:
    surface = compute_truth_surface(
        db_path=_db(tmp_path, n_outcomes=56),
        holdings_path=_holdings(tmp_path, run_date="2026-05-22"),
        cards_json_path=_artifact(tmp_path, "cards.json", "2026-07-04T11:00:00Z"),
        scheduler_last_run_path=_artifact(
            tmp_path, "sched.json", "2026-07-04T11:00:00Z", "HEALTHY"
        ),
        now_utc=NOW,
    )
    assert surface["holdings_truth_status"] == "HOLDINGS_TRUTH_STALE"
    assert surface["overall_operational_state"] in (STATE_DEGRADED, STATE_BLOCKED)


def test_missing_holdings_broken(tmp_path: Path) -> None:
    surface = compute_truth_surface(
        db_path=_db(tmp_path, n_outcomes=56),
        holdings_path=tmp_path / "absent.json",
        cards_json_path=_artifact(tmp_path, "cards.json", "2026-07-04T11:00:00Z"),
        scheduler_last_run_path=_artifact(
            tmp_path, "sched.json", "2026-07-04T11:00:00Z", "HEALTHY"
        ),
        now_utc=NOW,
    )
    assert surface["overall_operational_state"] == STATE_BROKEN


def test_broken_scheduler_record_is_broken(tmp_path: Path) -> None:
    surface = compute_truth_surface(
        db_path=_db(tmp_path, n_outcomes=56),
        holdings_path=_holdings(tmp_path),
        cards_json_path=_artifact(tmp_path, "cards.json", "2026-07-04T11:00:00Z"),
        scheduler_last_run_path=_artifact(
            tmp_path, "sched.json", "2026-07-04T11:00:00Z", "BROKEN"
        ),
        now_utc=NOW,
    )
    assert surface["overall_operational_state"] == STATE_BROKEN
    assert surface["scheduler_status"] == "BROKEN"


def test_zero_persisted_sources_degrade(tmp_path: Path) -> None:
    surface = compute_truth_surface(
        db_path=_db(tmp_path, n_outcomes=56, fresh_sources=False),
        holdings_path=_holdings(tmp_path),
        cards_json_path=_artifact(tmp_path, "cards.json", "2026-07-04T11:00:00Z"),
        scheduler_last_run_path=_artifact(
            tmp_path, "sched.json", "2026-07-04T11:00:00Z", "HEALTHY"
        ),
        now_utc=NOW,
    )
    assert surface["rows_persisted_status"]["status"] == "DEGRADED"
    assert surface["overall_operational_state"] == STATE_DEGRADED
    assert all(
        v["status"] == "DEGRADED_ZERO_PERSISTED"
        for v in surface["rows_persisted_status"]["sources"].values()
    )


def test_stale_artifacts_degrade(tmp_path: Path) -> None:
    surface = compute_truth_surface(
        db_path=_db(tmp_path, n_outcomes=56),
        holdings_path=_holdings(tmp_path),
        cards_json_path=_artifact(tmp_path, "cards.json", "2026-07-01T11:00:00Z"),
        scheduler_last_run_path=_artifact(
            tmp_path, "sched.json", "2026-07-04T11:00:00Z", "HEALTHY"
        ),
        now_utc=NOW,
    )
    assert surface["overall_operational_state"] == STATE_DEGRADED
    assert any("artifact" in r for r in surface["state_reasons"])


def test_calibration_thresholds() -> None:
    assert _calibration_status(0, None, None) == CAL_NO_EVIDENCE
    assert _calibration_status(49, 0.1, 0.05) == CAL_INSUFFICIENT
    assert _calibration_status(56, 0.279, 0.33) == CAL_MEASURED_NOT_CALIBRATED
    assert _calibration_status(200, 0.30, 0.05) == CAL_MEASURED_NOT_CALIBRATED
    assert _calibration_status(200, 0.20, 0.05) == CAL_CALIBRATED
    # the gate can never be talked into CALIBRATED below N=200
    assert _calibration_status(199, 0.10, 0.01) == CAL_MEASURED_NOT_CALIBRATED


def test_advisory_stamps_and_source_naming(tmp_path: Path) -> None:
    surface = compute_truth_surface(
        db_path=_db(tmp_path), holdings_path=tmp_path / "absent.json",
        cards_json_path=tmp_path / "no_cards.json",
        scheduler_last_run_path=tmp_path / "no_sched.json", now_utc=NOW,
    )
    assert surface["advisory_status"] == "ADVISORY_ONLY"
    assert surface["execution_gate"] == "LOCKED"
    assert "holdings_truth_gate" in surface["risk_engine_source"]
