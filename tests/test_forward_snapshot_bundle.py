"""Phase 9 — the evidence bundle reports the forward snapshot contract block."""
from __future__ import annotations

import pytest

from _forward_snapshot_helpers import (  # type: ignore[import-not-found]
    event_row,
    init_db,
    seed_market_bar,
    seed_score_vector,
)
from scripts.real_evidence_bundle import build_evidence_bundle, render_markdown
from scripts.run_daily_live_advisory_decisions import run_daily_decision_batch


def _canary():
    return {"per_source": [], "C_global": 0.0, "live_canonical_count": 0,
            "real_source_activation_count": 0, "fixture_source_activation_count": 0}


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "mvp.db"
    init_db(p)
    seed_score_vector(p, event_id="ev1", ticker="AAPL")
    seed_market_bar(p, symbol="AAPL", timestamp="2026-05-09T00:00:00Z", close=190.0)
    run_daily_decision_batch(
        db_path=p, events=[event_row("ev1", payload={})],
        now_iso="2026-05-10T00:00:00Z", write=True,
    )
    return p


def test_bundle_has_forward_snapshot_contract_block(db):
    b = build_evidence_bundle(db, canary_report=_canary())
    fc = b["forward_snapshot_contract"]
    assert fc["n_forward_outcome_eligible"] == 1
    assert fc["target_event_definition"] == "forward_return_ge_threshold"
    assert fc["default_prediction_horizon_days"] == 5
    assert fc["target_return_threshold"] == 0.0
    assert fc["n_needed_to_200"] == 200  # no real-forward pairs yet
    # Eligibility is structural; it never unlocks a claim.
    assert fc["predictive_claim_allowed"] is False
    assert b["predictive_claim_allowed"] is False
    assert b["real_money_ready"] is False


def test_bundle_s_evidence_has_forward_component(db):
    b = build_evidence_bundle(db, canary_report=_canary())
    comps = b["s_evidence"]["components"]
    weights = b["s_evidence"]["weights"]
    assert "forward_eligibility_coverage" in comps
    assert comps["forward_eligibility_coverage"] == 1.0  # 1 eligible / 1 valid-p
    # Real-Forward Outcome Maturation sprint re-weights: forward_eligibility 0.15.
    assert weights["forward_eligibility"] == 0.15
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)


def test_bundle_markdown_renders_forward_section(db):
    b = build_evidence_bundle(db, canary_report=_canary())
    md = render_markdown(b)
    assert "Forward snapshot contract" in md
    assert "forward_return_ge_threshold" in md
    assert "structural only" in md.lower()
