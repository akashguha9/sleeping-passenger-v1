"""Outcome Factory: maturity scanning, ladder, snippets, source inventory."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import edgar_counterparty_miner as edg
from scripts import live_calibration_report as lcr
from scripts import retrocast_source_inventory as inv
from scripts import run_daily_evidence as daily
from scripts import signal_ceiling_score_report as ceiling
from scripts import snapshot_maturity_scanner as sms

AS_OF = 2400


def _live_snap(sid: str, entry_day: int, direction: str = "UP",
               source_mode: str = "LIVE") -> dict:
    return {"snapshot_id": sid, "ticker": "FIXA", "direction": direction,
            "entry_day": entry_day, "entry_price": 100.0,
            "horizon_days": [1, 5, 21], "delta_p_conv": 0.12,
            "source_mode": source_mode, "status": "OPEN",
            "outcome": "PENDING", "adapter_run_id": "r1",
            "source_hash": "ab" * 16, "map_version": 1}


PRICES = {"FIXA": {d: 100.0 + (d - 2370) * 0.5 for d in range(2370, 2401)}}


def test_no_open_snapshots_reports_zero_ok():
    r = sms.scan([], as_of_day=AS_OF, prices={})
    assert r["outcomes"] == [] and r["live_open_snapshots"] == 0


def test_fixture_snapshot_never_becomes_live_outcome():
    snap = _live_snap("fx-1", 2370, source_mode="FIXTURE_DEMONSTRATION")
    snap["source_mode"] = "FIXTURE"
    r = sms.scan([snap], as_of_day=AS_OF, prices=PRICES)
    assert r["outcomes"] == []
    assert r["fixture_snapshots_ignored"] == 1


def test_not_matured_marked_correctly():
    r = sms.scan([_live_snap("s-1", AS_OF)], as_of_day=AS_OF, prices=PRICES)
    assert r["outcomes"] == []
    assert r["statuses"][sms.NOT_MATURED] == 3      # all three horizons


def test_matured_live_snapshot_writes_outcome_with_hit():
    r = sms.scan([_live_snap("s-2", 2370)], as_of_day=AS_OF, prices=PRICES)
    assert len(r["outcomes"]) == 3                   # T+1, T+5, T+21 all due
    o = next(x for x in r["outcomes"] if x["horizon_days"] == 5)
    assert o["source_mode"] == "LIVE" and o["hit"] == 1
    assert o["outcome_return"] > 0


def test_missing_price_fails_closed_not_scored():
    r = sms.scan([_live_snap("s-3", 2370)], as_of_day=AS_OF, prices={})
    assert r["outcomes"] == []
    assert r["statuses"][sms.PRICE_UNAVAILABLE] == 3


def test_duplicate_maturity_runs_deduplicate(tmp_path: Path):
    out = tmp_path / "live_outcomes.jsonl"
    r = sms.scan([_live_snap("s-4", 2370)], as_of_day=AS_OF, prices=PRICES)
    first = sms.append_outcomes(out, r["outcomes"], mode="write")
    assert first["written"] == 3
    again = sms.scan([_live_snap("s-4", 2370)], as_of_day=AS_OF,
                     prices=PRICES,
                     existing_outcome_ids={x["outcome_id"]
                                           for x in r["outcomes"]})
    assert again["outcomes"] == []                   # scan-level dedup
    second = sms.append_outcomes(out, r["outcomes"], mode="write")
    assert second["written"] == 0                    # file-level dedup
    assert second["skipped_duplicates"] == 3


# --- calibration ladder ------------------------------------------------------------

def test_ladder_no_live_evidence_at_zero():
    r = lcr.build_report([], [])
    assert r["calibration_status"] == "NO_LIVE_EVIDENCE"
    assert r["ladder_score"] == 0.0


def test_ladder_moves_with_n():
    assert lcr.ladder(0) == ("NO_LIVE_EVIDENCE", 0.0)
    assert lcr.ladder(5) == ("WARMING_UP", 2.5)
    assert lcr.ladder(15) == ("PROVISIONAL", 5.0)
    assert lcr.ladder(50) == ("FIRST_PASS", 7.5)
    assert lcr.ladder(120, ece=0.05) == ("READY", 10.0)
    assert lcr.ladder(120, ece=0.5) == ("FIRST_PASS", 7.5)


def test_calibration_report_counts_only_live_outcomes():
    outcomes = [{"source_mode": "LIVE", "horizon_days": 5, "hit": 1,
                 "residual_return": 0.01, "edge": 0.12},
                {"source_mode": "FIXTURE", "horizon_days": 5, "hit": 1,
                 "residual_return": 0.5, "edge": 0.5}]
    r = lcr.build_report(outcomes, [])
    assert r["matured_outcome_count"] == 1
    assert r["calibration_status"] == "WARMING_UP"


# --- EDGAR snippet upgrade ---------------------------------------------------------

def test_snippet_upgrades_client_dependency():
    cls = edg.classify_snippet(
        "the Company relies on Wise for cross-border payments and "
        "settlement under a processing agreement")
    assert cls["edge_type"] == edg.CLIENT_DEPENDENCY
    assert cls["context_confidence"] == 1.0


def test_snippet_detects_boilerplate_and_partner():
    assert edg.classify_snippet(
        "competitors include Wise and other industry participants"
    )["edge_type"] == edg.BOILERPLATE
    assert edg.classify_snippet(
        "we announced a partnership and platform integration with Wise"
    )["edge_type"] == edg.PARTNER_DISCLOSURE


def test_self_filing_cannot_be_snippet_upgraded():
    from datetime import date
    edge = {"edge_type": edg.SELF_FILING, "accession_number": "acc",
            "form_type": "20-F", "filing_date": "2026-06-25"}
    out = edg.upgrade_edge_with_snippet(
        edge, "relies on payment processing", date(2026, 7, 2))
    assert out["edge_type"] == edg.SELF_FILING


def test_snippet_upgrade_recomputes_admissibility():
    from datetime import date
    edge = {"edge_type": edg.COUNTERPARTY_FILING, "accession_number": "acc-9",
            "form_type": "10-K", "filing_date": "2026-05-01",
            "frequency_weight": 0.2}
    out = edg.upgrade_edge_with_snippet(
        edge, "depends on Wise for foreign exchange and settlement",
        date(2026, 7, 2))
    assert out["edge_type"] == edg.CLIENT_DEPENDENCY
    assert out["hard_filing_admissible"] is True
    assert out["materiality_score"] > 0.5


# --- retrocast source inventory ------------------------------------------------------

def test_source_inventory_classification():
    r = inv.classify_sources({
        "full": {"reachable": True, "history": True, "resolutions": True},
        "partial": {"reachable": True, "history": True, "resolutions": False},
        "res_only": {"reachable": True, "history": False,
                     "resolutions": True},
        "nothing": {"reachable": True, "history": False,
                    "resolutions": False},
        "blocked": {"reachable": False},
    })
    legs = r["legs"]
    assert legs["full"]["status"] == "FULL_HISTORY_AVAILABLE"
    assert legs["partial"]["status"] == "PARTIAL_HISTORY_AVAILABLE"
    assert legs["res_only"]["status"] == "RESOLUTION_ONLY_AVAILABLE"
    assert legs["nothing"]["status"] == "NO_HISTORY_AVAILABLE"
    assert legs["blocked"]["status"] == "BLOCKED_ADAPTER_LIMITATION"


def test_resolution_only_never_supports_validation():
    r = inv.classify_sources({
        "res_only": {"reachable": True, "history": False,
                     "resolutions": True}})
    assert r["legs"]["res_only"]["evidence_weight"] == 0.1
    assert r["legs"]["res_only"]["supports_validation"] is False
    assert r["validation_capable_legs"] == []


# --- daily runner + reporter ---------------------------------------------------------

def test_daily_blocked_when_maturity_blocked():
    steps = {"env": {"status": "OK"},
             "pm": {"status": "OK", "polymarket_blocked": True,
                    "fixture_fallback_detected": False},
             "maturity": {"status": "BLOCKED"},
             "calibration": {"status": "OK"},
             "edgar": {"status": "SKIPPED"},
             "retrocast": {"status": "SKIPPED"},
             "source_inventory": {"status": "SKIPPED"},
             "cards": {"status": "OK"}, "score": {"status": "OK"},
             "tests": {"status": "OK"}}
    agg = daily.aggregate_statuses(steps)
    assert "next_required_action" in agg     # runner escalates maturity block


def test_reporter_exposes_outcome_factory_scores():
    r = ceiling.build_report()
    assert "outcome_factory_score" in r
    assert r["score_families"]["outcome_factory_score"] >= 0.0
    assert "live_cadence_score" in r and "source_coverage_score" in r


def test_operator_reality_includes_outcome_factory():
    r = ceiling.build_report()
    fam = r["score_families"]
    expected = round(
        0.12 * fam["architecture_score"]
        + 0.18 * fam["research_readiness_score"]
        + 0.18 * r["segments"]["evidence_discipline"]["new"]
        + 0.17 * fam["calibration_readiness_score"]
        + 0.20 * fam["investability_readiness_score"]
        + 0.10 * fam["outcome_factory_score"]
        + 0.05 * fam["live_outcome_score"], 2)
    assert r["operator_reality_score"] == expected


def test_investability_still_low_without_candidates():
    r = ceiling.build_report()
    assert r["current_investability_readiness_score"] < 4.0
