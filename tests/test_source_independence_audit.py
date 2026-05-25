"""Source independence + ant-mill audit.

Proves duplicate catalysts lower independence, unique catalysts raise it, high
agreement + low independence raises ant-mill risk, ant-mill causes an advisory
downgrade (never an execution block), and all output is advisory-only.
"""
from __future__ import annotations

from scripts import source_independence_audit as sia


def _mention(model, ticker, catalyst, **over):
    row = {"model_name": model, "ticker": ticker, "catalyst_text": catalyst}
    row.update(over)
    return row


def test_duplicate_catalysts_lower_independence():
    # Five models, ONE catalyst — five masks, one face.
    rows = [_mention(f"m{i}", "NVDA", "Earnings beat headline") for i in range(5)]
    a = sia.analyze_catalysts(rows)
    assert a["total_catalysts"] == 5
    assert a["unique_catalyst_count"] == 1
    assert a["duplicate_catalyst_count"] == 4
    # 1 - 4/5 = 0.2
    assert a["source_independence_score"] == 0.2


def test_unique_catalysts_raise_independence():
    rows = [_mention(f"m{i}", "NVDA", f"distinct catalyst {i}") for i in range(5)]
    a = sia.analyze_catalysts(rows)
    assert a["unique_catalyst_count"] == 5
    assert a["duplicate_catalyst_count"] == 0
    assert a["source_independence_score"] == 1.0
    assert a["promotion_downgrade_recommendation"] == "no_change"


def test_high_agreement_low_independence_raises_ant_mill():
    rows = [_mention(f"m{i}", "NVDA", "one catalyst") for i in range(5)]
    a = sia.analyze_catalysts(rows)
    # agreement = 5/5 = 1.0; independence = 0.2 -> ant_mill = 1.0 * 0.8 = 0.8
    assert a["model_agreement_score"] == 1.0
    assert a["ant_mill_risk"] == 0.8
    assert a["high_agreement_low_independence"] is True
    assert a["ai_echo_risk"] is True


def test_ant_mill_causes_downgrade_not_execution_block():
    rows = [_mention(f"m{i}", "NVDA", "one catalyst") for i in range(5)]
    a = sia.analyze_catalysts(rows)
    assert a["promotion_downgrade_recommendation"] == "downgrade"
    # Advisory only — there is no execution-permission field that flips true.
    assert a["can_execute"] is False
    assert a["execution_permission"] is False
    assert a["human_review_required"] is True


def test_single_source_consensus_flagged():
    rows = [_mention("m1", "AMD", "same"), _mention("m2", "AMD", "same")]
    a = sia.analyze_catalysts(rows)
    assert a["single_source_consensus"] is True


def test_empty_is_insufficient_data():
    a = sia.analyze_catalysts([])
    assert a["total_catalysts"] == 0
    assert "insufficient_data" in a["source_overlap_note"]
    assert a["advisory_status"] == "ADVISORY_ONLY"


def test_build_report_groups_by_ticker_and_is_advisory_only():
    rows = (
        [_mention(f"m{i}", "NVDA", "one catalyst") for i in range(4)]
        + [_mention(f"m{i}", "AMD", f"distinct {i}") for i in range(3)]
    )
    rep = sia.build_report(rows)
    assert rep["cohort_count"] == 2
    assert "NVDA" in rep["flagged_cohorts"]
    assert "AMD" not in rep["flagged_cohorts"]
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["broker_api_called"] is False


def test_explicit_model_agreement_used():
    rows = [
        _mention("m1", "X", "c1", model_agreement=0.9),
        _mention("m2", "X", "c1", model_agreement=0.9),
    ]
    a = sia.analyze_catalysts(rows)
    assert a["model_agreement_score"] == 0.9
