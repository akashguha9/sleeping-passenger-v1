"""Tests for outcome extraction from persistence-shaped rows."""
from __future__ import annotations

from scripts import outcome_evidence as oe
from scripts import outcome_evidence_extractor as ex


def _trade(trade_id, ticker="AAPL", side="BUY", price=100.0, score=0.7, **extra):
    d = {
        "trade_id": trade_id, "event_id": f"EV_{trade_id}", "ticker": ticker,
        "side": side, "price": price, "executed_at": "2026-01-01T00:00:00Z",
        "leverage": 1.0, "jurisdiction_group": "REST_OF_WORLD",
        "decision_grade_energy_at_decision": score,
    }
    d.update(extra)
    return d


def _recon(trade_id, status="WIN", fill=110.0, pnl=100.0):
    return {
        "trade_id": trade_id, "event_id": f"EV_{trade_id}",
        "outcome_status": status, "actual_fill_price": fill,
        "pnl_estimate": pnl, "reconciled_at": "2026-01-05T00:00:00Z",
    }


def test_complete_real_manual_trade_quality_high():
    outs = ex.extract_outcomes([_trade("T1")], [_recon("T1")])
    assert len(outs) == 1
    o = outs[0]
    assert o.source_type == oe.REAL_MANUAL_TRADE
    assert o.quality >= 0.9
    assert o.is_calibration_eligible is True
    assert o.outcome_label == "WIN"


def test_missing_score_reduces_quality():
    t = _trade("T1")
    t.pop("decision_grade_energy_at_decision")
    outs = ex.extract_outcomes([t], [_recon("T1")])
    assert outs[0].score_at_entry is None
    assert outs[0].is_calibration_eligible is False
    assert outs[0].ineligible_reason == "missing_score_at_entry"


def test_open_trade_excluded():
    # No reconciliation -> no exit -> OPEN.
    outs = ex.extract_outcomes([_trade("T1")], [])
    assert outs[0].outcome_label == oe.OPEN
    assert outs[0].is_calibration_eligible is False


def test_moltbook_only_classification_does_not_invent_pnl():
    molt = [{"event_id": "EV_T1", "outcome_status": "LOSS"}]
    outs = ex.extract_outcomes([_trade("T1")], [], molt)
    o = outs[0]
    assert o.outcome_label == "LOSS"      # label honoured
    assert o.realized_pnl is None         # no invented PnL
    assert o.realized_return is None      # no invented return


def test_reconciliation_takes_precedence_over_moltbook():
    molt = [{"event_id": "EV_T1", "outcome_status": "LOSS"}]
    outs = ex.extract_outcomes([_trade("T1")], [_recon("T1", status="WIN")], molt)
    assert outs[0].outcome_label == "WIN"  # reconciliation wins


def test_short_trade_direction_mapped():
    outs = ex.extract_outcomes([_trade("T1", side="SELL")], [_recon("T1", status="WIN", fill=90.0)])
    assert outs[0].direction == "SHORT"
    # short: entry 100 exit 90 -> +0.10 return
    assert abs(outs[0].realized_return - 0.10) < 1e-9


def test_extraction_is_deterministic():
    trades = [_trade("T2"), _trade("T1"), _trade("T3")]
    recons = [_recon("T1"), _recon("T2"), _recon("T3")]
    a = [o.outcome_id for o in ex.extract_outcomes(trades, recons)]
    b = [o.outcome_id for o in ex.extract_outcomes(trades, recons)]
    assert a == b == ["OE_T1", "OE_T2", "OE_T3"]  # sorted by trade_id


def test_extracted_objects_have_advisory_stamps():
    outs = ex.extract_outcomes([_trade("T1")], [_recon("T1")])
    d = outs[0].to_dict()
    assert d["advisory_only"] is True
    assert d["broker_api_called"] is False


def test_synthetic_source_type_never_eligible():
    outs = ex.extract_outcomes(
        [_trade("T1")], [_recon("T1")], source_type=oe.SYNTHETIC_FIXTURE
    )
    assert outs[0].is_calibration_eligible is False
    assert outs[0].ineligible_reason == "synthetic_fixture_never_calibration_eligible"
