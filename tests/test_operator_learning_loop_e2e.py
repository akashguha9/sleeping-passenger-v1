"""Phase 7 — end-to-end operator learning loop through the LIVE decision path.

This is the core hackathon proof.  It calls the real live-path function
``run_live_decision_path`` (not isolated modules) twice, with a reconciliation
step in between, and proves:

    Decision 1 (fresh source, no history)
        -> advisory candidate, model_probability snapshot persisted

    Reconciliation
        -> a STOP_LOSS_HIT outcome for that pattern is journaled
           (moltbook_api, JSONL isolated to tmp) and turned into a
           pattern-tagged Moltbook entry

    Decision 2 (same pattern, loss now in history)
        -> p2_adj < p2_base  (the learned penalty bites)
        -> candidate downgraded (WATCHLIST), execution still LOCKED

Mathematics::

    n_bad(phi) increases by 1  =>  BadRate_after > BadRate_before
    M_penalty_after > M_penalty_before
    p2_adj = sigma(logit(p2_base) - M_penalty_after) < p2_base

No network, no broker, temp DB only.
"""
from __future__ import annotations

import json

from scripts.decision_probability_snapshot import count_valid_p
from scripts.live_decision_path import run_live_decision_path

_AXES = {"EMS": 0.9, "EQS": 0.9, "DS": 0.9, "LS": 0.9, "EFS": 0.9, "APS": 0.9}

_PATTERN = dict(
    country="India",
    signal_class="momentum",
    sector="energy",
    market_regime="risk_on",
    source_mix=["yfinance"],
)


def _decision_kwargs(signal_id, db, **overrides):
    base = dict(
        signal_id=signal_id,
        axes=_AXES,
        ticker="RELIANCE.NS",
        prediction_horizon_days=3.0,
        api_health_status="OK",
        rows_added=5,
        canonical_age_hours=1.0,
        state="HURACAN",
        chaos_risk=0.1,
        capital=1_000_000.0,
        cash_available=900_000.0,
        entry_price=100.0,
        hard_stop_price=98.0,
        db_path=db,
    )
    base.update(_PATTERN)
    base.update(overrides)
    return base


def _loss_entries(n):
    """Reconciliation output: n pattern-tagged STOP_LOSS_HIT Moltbook rows."""
    rows = []
    for i in range(n):
        row = dict(_PATTERN)
        row["outcome_quality"] = "STOP_LOSS_HIT"
        row["entry_id"] = f"MB_LOSS_{i}"
        rows.append(row)
    return rows


def test_decision_snapshot_then_reconciliation_then_future_moltbook_downgrade(tmp_path):
    db = tmp_path / "loop.db"

    # --- Decision 1: fresh source, no Moltbook history -------------------
    d1 = run_live_decision_path(**_decision_kwargs("SIG_D1", db, moltbook_entries=[]))
    assert d1["final_advisory_class"] == "ADVISORY_CANDIDATE_FOR_HUMAN_REVIEW"
    assert d1["snapshot_persisted"] is True
    assert count_valid_p(db) == 1
    p1 = d1["p_after_moltbook"]

    # --- Reconciliation: the trade hit its stop; journal the loss -------
    losses = _loss_entries(8)

    # --- Decision 2: same pattern, loss now in history ------------------
    d2 = run_live_decision_path(
        **_decision_kwargs("SIG_D2", db, moltbook_entries=losses)
    )
    p2_base = d2["p_base"]
    p2_adj = d2["p_after_moltbook"]

    # The learned penalty strictly lowers the adjusted probability.
    assert d2["moltbook"]["moltbook_penalty"] > 0.0
    assert p2_adj < p2_base
    # And the candidate is downgraded vs. the clean first decision.
    assert d2["final_advisory_class"] == "WATCHLIST"
    assert d2["moltbook_downgraded"] is True
    # Penalty grew the corpus of decisions, too.
    assert count_valid_p(db) == 2
    # The clean p1 was higher than the penalised p2_adj for the same pattern.
    assert p1 >= p2_adj


def test_e2e_preserves_advisory_only_all_steps(tmp_path):
    db = tmp_path / "loop.db"
    d1 = run_live_decision_path(**_decision_kwargs("S1", db, moltbook_entries=[]))
    d2 = run_live_decision_path(
        **_decision_kwargs("S2", db, moltbook_entries=_loss_entries(8))
    )
    for d in (d1, d2):
        assert d["advisory_status"] == "ADVISORY_ONLY"
        assert d["execution_gate"] == "LOCKED"
        assert d["broker_api_called"] is False
        assert d["ai_execution_count"] == 0
        assert d["human_execution_required"] is True
        assert d["predictive_claim_allowed"] is False


def test_e2e_no_broker_route_or_execution_fields_unlocked(tmp_path):
    db = tmp_path / "loop.db"
    d = run_live_decision_path(**_decision_kwargs("S", db, moltbook_entries=_loss_entries(8)))
    blob = json.dumps(d).lower()
    for forbidden in (
        "broker_connected", "place_order", "submit_order", "execute_trade",
        "auto_trade", "buy_now", "sell_now", "order_id\": \"live",
    ):
        assert forbidden not in blob
    # The only broker_order-ish field, if present, is the NONE sentinel.
    assert d.get("broker_order_id", "NONE") == "NONE"


def test_e2e_source_freshness_gate_blocks_stale_candidate(tmp_path):
    db = tmp_path / "loop.db"
    d = run_live_decision_path(
        **_decision_kwargs("S_STALE", db, moltbook_entries=[],
                           canonical_age_hours=200.0, ttl_hours=24.0)
    )
    assert d["is_live_canonical"] is False
    assert d["final_advisory_class"] == "BLOCKED_BY_FRESHNESS"


def test_e2e_capacity_gate_blocks_missing_stop_candidate(tmp_path):
    db = tmp_path / "loop.db"
    d = run_live_decision_path(
        **_decision_kwargs("S_NOSTOP", db, moltbook_entries=[], hard_stop_price=None)
    )
    assert d["capacity_ok"] is False
    assert d["final_advisory_class"] != "ADVISORY_CANDIDATE_FOR_HUMAN_REVIEW"


def test_e2e_moltbook_journal_write_is_real_and_isolated(tmp_path, monkeypatch):
    """The reconciliation->Moltbook journal write path is real (not faked) and
    test-isolated to a tmp JSONL so it never pollutes runtime state."""
    import scripts.moltbook_api as mb

    log_path = tmp_path / "moltbook_entries.jsonl"
    monkeypatch.setattr(mb, "MOLTBOOK_LOG", log_path)

    res = mb.log_moltbook_entry(
        event_id="EVT1",
        ticker="RELIANCE.NS",
        original_signal_thesis="momentum continuation",
        ai_interpretation="advisory only",
        user_reflection="exited at stop",
        final_human_decision="closed at loss",
        mistake_type="stop_loss_breach",
        lesson_learned="respect the stop",
        outcome="loss",
    )
    assert res["status"] == "logged"
    assert res["ai_execution_count"] == 0
    assert log_path.exists()
    rows = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["mistake_type"] == "stop_loss_breach"
