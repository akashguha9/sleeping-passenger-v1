"""Advisory-only safety invariants for the discovery/execution mode model.

The three-lane model must never become an execution surface. BUY / PROBE_BUY
are advisory paper-signal classifications only; the report always carries the
canonical advisory-only stamps and an execution permission of false.
"""
from __future__ import annotations

from scripts.discovery_execution_mode import (
    build_discovery_execution_report,
    classify_candidate,
    compute_mode_state,
)


def _mode(**over):
    base = dict(
        holdings_price_coverage=1.0,
        candidate_price_coverage=1.0,
        portfolio_truth_clean=True,
        phantom_clean=True,
        leverage_clean=True,
        exit_debt_clean=True,
        source_health_ok=True,
    )
    base.update(over)
    return compute_mode_state(**base)


def test_report_carries_advisory_only_stamps():
    report = build_discovery_execution_report(
        mode_state=_mode(),
        holdings_price_coverage=1.0,
        candidate_price_coverage=1.0,
    )
    # Canonical advisory-only contract spliced in.
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
    assert report["can_execute"] is False
    assert report["human_execution_required"] is True
    assert report["real_money_sizing_impact"] == "PROHIBITED"


def test_execution_board_empty_when_execution_blocked():
    report = build_discovery_execution_report(
        mode_state=_mode(holdings_price_coverage=0.0),
        holdings_price_coverage=0.0,
        candidate_price_coverage=0.0,
        execution_board=[{"ticker": "X", "classification": "EXECUTABLE-PAPER-BUY"}],
        discovery_board=[{"ticker": "Y", "classification": "DISCOVERED"}],
    )
    # Even if an execution row is passed, a blocked mode never surfaces it.
    assert report["execution_board"] == []
    assert report["message"] == "Discovery is active, but execution is blocked."
    assert report["discovery_board"]  # discovery still present


def test_buy_label_is_advisory_only_never_executes():
    # A BUY classification carries no execution authority — it is a label.
    verdict = classify_candidate(
        0.95,
        execution_allowed=True,
        proof={
            "price_confirmation": 1.0,
            "volume_confirmation": 1.0,
            "source_quality": 1.0,
            "portfolio_fit": 1.0,
        },
    )
    assert verdict["classification"] == "BUY"
    # The verdict dict has no broker / order / execution field of any kind.
    assert "broker" not in str(verdict).lower()
    assert "order" not in str(verdict).lower()


def test_new_risk_requires_execution_allowed():
    # new_risk_allowed can never be true while execution is blocked.
    m = _mode(phantom_clean=False)
    assert m["execution_allowed"] is False
    assert m["new_risk_allowed"] is False
