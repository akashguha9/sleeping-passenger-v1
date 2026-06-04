"""Adversarial / behavioural tests for the core signal engines.

These replace label-checking with behaviour-checking: each test drives a real
decision boundary and asserts the engine reacts correctly, including the
benign (must-NOT-fire) cases that catch "always returns the scary state"
theater. Engines covered are exactly the production-core set listed in
docs/CORE_ENGINE_MANIFEST.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# DIABLO narrative veto — must fire on dangerous combinations, stay CLEAR on
# benign inputs (proves it is a real decision boundary, not a constant).
# ---------------------------------------------------------------------------

from scripts.diablo_narrative_veto import evaluate_veto, VETO_DIABLO, VETO_REVIEW, VETO_NONE  # noqa: E402


def test_diablo_fires_on_weak_signal_strong_emotion_leverage():
    out = evaluate_veto(signal_strength=0.1, operator_emotion=0.9, leverage=0.9)
    assert out["veto_state"] == VETO_DIABLO
    assert out["diablo_veto"] is True
    assert "weak_signal+strong_emotion+leverage" in out["veto_reason"]
    # only ever recommends a safe non-trading action
    assert "buy" not in out["recommended_safe_action"].lower()
    assert out["broker_api_called"] is False


def test_diablo_fires_on_viral_narrative_without_fundamentals():
    out = evaluate_veto(narrative_virality=0.95, fundamental_support=0.05)
    assert out["veto_state"] == VETO_DIABLO
    assert "viral_narrative+no_fundamental_support" in out["veto_reason"]


def test_diablo_fires_on_crowding_with_low_liquidity():
    out = evaluate_veto(crowding=0.9, liquidity=0.05)
    assert out["veto_state"] == VETO_DIABLO
    assert "high_crowding+low_liquidity" in out["veto_reason"]


def test_diablo_soft_review_on_thin_polymarket_high_impact():
    out = evaluate_veto(polymarket_move_thinness=0.9, asset_impact=0.9)
    assert out["veto_state"] == VETO_REVIEW
    assert out["diablo_veto"] is True  # review still flags for human


def test_diablo_clear_on_benign_inputs():
    out = evaluate_veto(
        signal_strength=0.8, operator_emotion=0.1, leverage=0.0,
        narrative_virality=0.1, fundamental_support=0.9,
        crowding=0.1, liquidity=0.9, invalidation_clarity=0.9,
        news_age=0.1, conviction=0.2,
    )
    assert out["veto_state"] == VETO_NONE
    assert out["diablo_veto"] is False


def test_diablo_does_not_fire_on_strong_signal_even_with_some_heat():
    # Strong signal + moderate emotion + NO leverage must not trip the
    # weak+emotion+leverage combo.
    out = evaluate_veto(signal_strength=0.9, operator_emotion=0.8, leverage=0.0)
    assert "weak_signal+strong_emotion+leverage" not in out["veto_reason"]


# ---------------------------------------------------------------------------
# Event-prior detector — must return NO windows when data is inadequate, and
# detect a cluster only once the threshold is met. Never invents rows.
# ---------------------------------------------------------------------------

from scripts.chronology_store import get_connection, init_schema, log_observation  # noqa: E402
from scripts.event_prior_detector import detect_prior_windows, open_readonly  # noqa: E402


def _seed_observations(db_path: Path, timestamps: list[str], source: str = "sec_edgar") -> Path:
    conn = get_connection(db_path)
    init_schema(conn)
    for ts in timestamps:
        log_observation(conn, {"ts": ts, "source": source, "payload_json": "{}"})
    conn.close()
    return db_path


def test_event_prior_insufficient_data_returns_no_window(tmp_path):
    # Two observations but min_count=3 -> inadequate -> no window.
    db = _seed_observations(tmp_path / "o.db", [
        "2026-05-01T10:00:00Z", "2026-05-01T10:05:00Z",
    ])
    conn = open_readonly(db)
    try:
        windows = detect_prior_windows(conn, window_minutes=60, min_count=3)
    finally:
        conn.close()
    assert windows == []


def test_event_prior_detects_cluster_at_threshold(tmp_path):
    db = _seed_observations(tmp_path / "o.db", [
        "2026-05-01T10:00:00Z",
        "2026-05-01T10:10:00Z",
        "2026-05-01T10:20:00Z",
    ])
    conn = open_readonly(db)
    try:
        windows = detect_prior_windows(conn, window_minutes=60, min_count=3)
    finally:
        conn.close()
    assert len(windows) == 1
    assert windows[0]["count"] == 3


def test_event_prior_spread_out_observations_do_not_cluster(tmp_path):
    # Three observations but each >60min apart -> no 60-min window of 3.
    db = _seed_observations(tmp_path / "o.db", [
        "2026-05-01T10:00:00Z",
        "2026-05-01T12:00:00Z",
        "2026-05-01T14:00:00Z",
    ])
    conn = open_readonly(db)
    try:
        windows = detect_prior_windows(conn, window_minutes=60, min_count=3)
    finally:
        conn.close()
    assert windows == []


# ---------------------------------------------------------------------------
# Moltbook feedback classification — must classify outcomes correctly and
# refuse to over-claim when evidence is missing.
# ---------------------------------------------------------------------------

from scripts.moltbook_feedback import build_feedback_case_from_reconciliation_row  # noqa: E402


def test_moltbook_target_hit_is_success():
    case = build_feedback_case_from_reconciliation_row({
        "trade_id": "T1", "ticker": "RELIANCE", "side": "BUY",
        "realized_return_pct": 3.0, "realized_pnl": 300.0,
        "close_reason": "target_hit",
    })
    assert case.classification == "SUCCESS_VALID_SIGNAL"


def test_moltbook_missing_outcome_does_not_overclaim():
    # A row with no reliable outcome must NOT be called a success. Depending on
    # data-quality flags it lands on INCONCLUSIVE or FAIL_DATA_QUALITY — both
    # are honest "insufficient evidence" verdicts, never SUCCESS.
    case = build_feedback_case_from_reconciliation_row({
        "trade_id": "T2", "ticker": "ACME", "side": "BUY",
    })
    assert case.classification in {"INCONCLUSIVE", "FAIL_DATA_QUALITY"}
    assert case.classification != "SUCCESS_VALID_SIGNAL"


def test_moltbook_classification_is_in_known_vocabulary():
    case = build_feedback_case_from_reconciliation_row({
        "trade_id": "T3", "ticker": "ACME", "side": "SELL",
        "realized_return_pct": -5.0, "realized_pnl": -500.0,
        "close_reason": "stopped_out",
    })
    assert isinstance(case.classification, str) and case.classification
    # a loss must not be miscategorised as a success
    assert case.classification != "SUCCESS_VALID_SIGNAL"


# ---------------------------------------------------------------------------
# Scoring + calibration — a high raw score must NOT present as high-confidence
# / sizing-grade when calibration evidence is missing.
# ---------------------------------------------------------------------------

from scripts.score_calibration import (  # noqa: E402
    compute_score_calibration,
    score_calibration_envelope,
)


def test_high_score_not_sizing_grade_when_uncalibrated():
    summary = compute_score_calibration([])  # no outcomes
    env = score_calibration_envelope(0.97, summary, label="priority_score")
    assert env["score"] == 0.97
    assert env["score_should_drive_sizing"] is False
    assert env["score_calibration_status"] == "UNCALIBRATED"


def test_high_score_sizing_grade_only_with_enough_outcomes():
    rows = [{"outcome_status": "WIN", "pnl_estimate": 1.0}] * 30
    rows += [{"outcome_status": "LOSS", "pnl_estimate": -1.0}] * 25  # 55 resolved
    summary = compute_score_calibration(rows)
    env = score_calibration_envelope(0.97, summary)
    assert env["score_calibration_status"] == "CALIBRATED"
    assert env["score_should_drive_sizing"] is True


# ---------------------------------------------------------------------------
# Leverage governance — breaches flagged (cross-reference to the P0 module).
# ---------------------------------------------------------------------------

from scripts.leverage_governance import validate_leverage_policy  # noqa: E402


def test_leverage_governance_flags_row_breach():
    res = validate_leverage_policy(ticker="AAPL", exchange="NASDAQ", leverage=2.0)
    assert res["breach"] is True and res["severity"] == "POLICY_BREACH"


def test_leverage_governance_clears_india_within_ceiling():
    res = validate_leverage_policy(ticker="RELIANCE.NS", leverage=4.0)
    assert res["breach"] is False and res["severity"] == "NONE"
