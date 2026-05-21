"""Bruce Lee signal-discipline report — synthesis + safety banners.

Proves the report assembles every required field from a clean DB, prints the
three mandated banners, keeps advisory invariants, and that the consolidated
B7/B8/B9 helpers behave (stale news decays, narrative fragility, contradiction
classes, costly signals beat cheap talk, agency/adverse-selection downgrade,
negative reflexivity raises chaos contribution, polymarket distortion).
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import scripts.persistence as persistence
from scripts import bruce_lee_signal_discipline_report as rpt

REQUIRED_FIELDS = [
    "truth_purity_status", "economy_of_motion", "jkd_decision_score",
    "interception", "directness", "adaptability", "anti_dogma",
    "reality_confirmation", "operator_heat", "polymarket_distortion",
    "news_quality", "narrative_quality", "triangulated_signal",
    "contradiction_class", "strategic_actor_summary", "firm_incentive_summary",
    "reflexivity", "diablo_veto", "bldqi_score", "final_advisory_constraint",
]


def _clean_db(tmp_path: Path) -> Path:
    db = tmp_path / "report.db"
    persistence.init_schema(db)
    persistence.insert_manual_trade(
        "MT_real_ok", "EV_USER_REAL", "ICICIBANK.NS", "BUY", 3.0, 40.0,
        "2026-05-16T08:00:00+00:00",
        "break of pivot on bank-nifty breadth confirmation", "", "human", db,
        created_via="manual_trade_log",
    )
    return db


def test_report_has_all_required_fields(tmp_path):
    rep = rpt.build_report(_clean_db(tmp_path))
    for field in REQUIRED_FIELDS:
        assert field in rep, f"missing required field: {field}"


def test_report_prints_safety_banners(tmp_path, capsys):
    rc = rpt.main(["--db-path", str(_clean_db(tmp_path))])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ADVISORY_ONLY" in out
    assert "HUMAN_EXECUTION_REQUIRED" in out
    assert "NO_BROKER_ACTION_PERFORMED" in out


def test_report_advisory_invariants(tmp_path):
    rep = rpt.build_report(_clean_db(tmp_path))
    assert rep["ADVISORY_ONLY"] is True
    assert rep["HUMAN_EXECUTION_REQUIRED"] is True
    assert rep["NO_BROKER_ACTION_PERFORMED"] is True
    assert rep["broker_api_called"] is False
    assert rep["ai_execution_count"] == 0
    assert rep["execution_gate"] == "LOCKED"


def test_no_execution_language_in_report(tmp_path):
    rep = rpt.build_report(_clean_db(tmp_path))
    blob = str(rep).lower()
    for forbidden in ("buy now", "sell now", "execute now", "place order", "submit order"):
        assert forbidden not in blob


# --- consolidated B7/B8/B9 helper behaviour --------------------------------


def test_stale_news_decays_via_freshness():
    fresh = rpt.compute_news_quality(freshness=1.0, source_credibility=0.8, materiality=0.8)
    stale = rpt.compute_news_quality(freshness=0.0, source_credibility=0.8, materiality=0.8)
    assert fresh > stale


def test_high_narrative_weak_fundamentals_raises_fragility():
    fragile = rpt.compute_narrative_quality(
        velocity=0.9, breadth=0.9, emotional_intensity=0.9,
        crowding=0.9, weak_fundamental_support=0.9, single_source_dependence=0.9,
        price_overextension=0.9, meme_contamination=0.9,
    )
    sturdy = rpt.compute_narrative_quality(
        velocity=0.9, breadth=0.9, emotional_intensity=0.9,
        weak_fundamental_support=0.0, single_source_dependence=0.0,
    )
    assert fragile["narrative_fragility"] > sturdy["narrative_fragility"]
    # High strength + high fragility => quality is dragged down vs sturdy.
    assert fragile["narrative_quality"] < sturdy["narrative_quality"]


def test_costly_signals_outrank_cheap_talk():
    costly = rpt.compute_strategic_actor_summary(
        costliness=0.9, verifiability=0.8, incentive_alignment=0.8, historical_accuracy=0.8)
    cheap = rpt.compute_strategic_actor_summary(
        costliness=0.0, verifiability=0.1, incentive_alignment=0.1, historical_accuracy=0.1)
    assert costly["signal_credibility"] > cheap["signal_credibility"]
    assert cheap["cheap_talk"] is True


def test_agency_and_adverse_selection_downgrade():
    rep = rpt.compute_firm_incentive_summary(
        agency_risk_inputs={"compensation_misalignment": 0.9, "dilution_risk": 0.9,
                            "debt_abuse": 0.9},
        adverse_selection_inputs={"insider_selling": 0.9, "opaque_accounting": 0.9},
    )
    assert rep["downgrade_flag"] is True


def test_negative_reflexivity_raises_chaos_contribution():
    calm = rpt.compute_reflexivity(momentum=0.6, narrative_velocity=0.6, flow_confirmation=0.6)
    stressed = rpt.compute_reflexivity(
        drawdown=0.9, leverage=0.9, liquidity_stress=0.9, narrative_decay=0.9)
    assert stressed["chaos_contribution"] > calm["chaos_contribution"]
    assert stressed["reflexivity_score"] < calm["reflexivity_score"]


def test_polymarket_distortion_penalises_low_liquidity_and_whales():
    clean = rpt.compute_polymarket_distortion(
        odds_move=0.8, volume_change=0.8, liquidity_depth=0.9, market_relevance=0.9)
    distorted = rpt.compute_polymarket_distortion(
        odds_move=0.8, volume_change=0.8, liquidity_depth=0.1, market_relevance=0.9,
        low_liquidity=0.9, whale_concentration=0.9, low_trader_count=0.9)
    assert distorted["distortion_risk"] > clean["distortion_risk"]
    assert distorted["pm_clean_signal"] < clean["pm_clean_signal"]


def test_contradiction_classifier_classes():
    # Fake narrative: loud narrative, dead price/news.
    fake = rpt.compute_triangulation(
        price_signal=0.1, news_signal=0.1, polymarket_signal=0.1,
        narrative_signal=0.9, fake_narrative_risk=0.6, source_credibility=0.6,
        reality_confirmation_01=0.5)
    assert fake["contradiction_class"] == rpt.CONTRADICTION_FAKE_NARRATIVE
    # Data reliability: high spread, low source credibility.
    unreliable = rpt.compute_triangulation(
        price_signal=0.9, news_signal=0.1, polymarket_signal=0.9, narrative_signal=0.1,
        source_credibility=0.1, reality_confirmation_01=0.5)
    assert unreliable["contradiction_class"] == rpt.CONTRADICTION_DATA_RELIABILITY
    # Aligned signals: no material contradiction.
    aligned = rpt.compute_triangulation(
        price_signal=0.6, news_signal=0.6, polymarket_signal=0.6, narrative_signal=0.6,
        filing_signal=0.6, source_credibility=0.7, reality_confirmation_01=0.7)
    assert aligned["contradiction_class"] == rpt.CONTRADICTION_NONE
