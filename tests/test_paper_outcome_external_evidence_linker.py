"""Tests — paper-outcome → external-evidence linker (Workstream B).

Proves the link-confidence math + the AUTO / REVIEW / NO_LINK bands, the 72h
pre-entry time window, the read-only DB candidate search, and that a link can
NEVER affect real-money sizing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import scripts.external_evidence_persistence as eep
from scripts.paper_outcome_external_evidence_linker import (
    AUTO_LINK,
    NO_LINK,
    REVIEW_LINK,
    link_outcome_from_db,
    score_link,
)

GEN_AT = "2026-05-22T10:00:00+00:00"


def _snapshot(**overrides):
    snap = {
        "snapshot_id": "snap-1",
        "signal_id": "S-1",
        "ticker": "AAPL",
        "source_name": "kronos",
        "generated_at_utc": GEN_AT,
        "candidate_id": "",
        "outcome_trade_id": "",
    }
    snap.update(overrides)
    return snap


def _outcome(**overrides):
    o = {
        "trade_id": "T-1",
        "signal_id": "S-1",
        "ticker": "AAPL",
        # 24h after the snapshot → snapshot sits inside the 72h pre-entry window.
        "entry_timestamp_utc": "2026-05-23T10:00:00Z",
    }
    o.update(overrides)
    return o


# --- 5: exact signal_id (+ticker +time) auto-links --------------------------
def test_exact_signal_id_auto_links():
    s = score_link(_outcome(), _snapshot())
    assert s["signal_id_match"] == 1
    assert s["ticker_match"] == 1
    assert s["time_window_match"] == 1
    # 0.50 + 0.20 + 0.20 = 0.90
    assert s["link_confidence"] == pytest.approx(0.90)
    assert s["link_classification"] == AUTO_LINK


# --- 6: ticker match without the time window review-links -------------------
def test_ticker_review_link_without_time_window():
    # signal + ticker match but the snapshot is OUTSIDE the 72h window.
    out = _outcome(entry_timestamp_utc="2026-06-30T10:00:00Z")
    s = score_link(out, _snapshot())
    assert s["ticker_match"] == 1
    assert s["time_window_match"] == 0
    # 0.50 + 0.20 = 0.70 → REVIEW band.
    assert s["link_confidence"] == pytest.approx(0.70)
    assert s["link_classification"] == REVIEW_LINK


# --- 7: ticker-only is low-confidence → no link -----------------------------
def test_ticker_only_no_link():
    out = _outcome(signal_id="", entry_timestamp_utc="2026-06-30T10:00:00Z")
    s = score_link(out, _snapshot(signal_id="OTHER"))
    assert s["signal_id_match"] == 0
    assert s["ticker_match"] == 1
    assert s["time_window_match"] == 0
    # 0.20 only → below 0.60.
    assert s["link_confidence"] == pytest.approx(0.20)
    assert s["link_classification"] == NO_LINK


# --- 7b: source_context (trade_id in snapshot) contributes ------------------
def test_trade_id_in_snapshot_context_scores():
    s = score_link(_outcome(), _snapshot(outcome_trade_id="T-1"))
    assert s["source_context_match"] == 1
    # 0.50 + 0.20 + 0.20 + 0.10 = 1.00
    assert s["link_confidence"] == pytest.approx(1.00)
    assert s["link_classification"] == AUTO_LINK


# --- 8: a link never affects real-money sizing ------------------------------
def test_link_never_affects_real_money_sizing():
    s = score_link(_outcome(), _snapshot())
    assert s["real_money_sizing_impact"] == "PROHIBITED"
    assert s["real_money_weight_allowed"] is False


# --- DB integration: read-only candidate search + auto-link -----------------
def test_link_outcome_from_db_auto_links(tmp_path: Path):
    db = tmp_path / "mvp_local.db"
    item = {
        "source_name": "kronos",
        "evidence_type": "CANDLESTICK_FORECAST",
        "status": "ACCEPTED_EVIDENCE_ONLY",
        "route_decision": "WATCH",
        "execution_permission": "WATCH_ONLY",
        "score_delta": 0.12,
        "proof_status": "ACCEPTED_EVIDENCE_ONLY",
        "payload_summary": {"KRONOS_STATUS": "SUPPORTIVE"},
    }
    bundle = {
        "external_evidence_enabled": True,
        "external_evidence_status": "ACCEPTED_EVIDENCE_ONLY",
        "external_evidence_items": [item],
        "generated_at_utc": GEN_AT,
    }
    eep.persist_external_evidence_bundle(
        bundle, {"signal_id": "S-1", "ticker": "AAPL"}, db_path=db
    )

    report = link_outcome_from_db(_outcome(), db_path=db)
    assert report["candidate_count"] == 1
    assert report["best_link_classification"] == AUTO_LINK
    assert report["real_money_sizing_impact"] == "PROHIBITED"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
