"""Closure sprint: honest score math, EDGAR edge typing, ledger warmup."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import edgar_counterparty_miner as edg
from scripts import prediction_market_shock_engine as pm
from scripts import retrocast_calibration as rc
from scripts import run_daily_evidence as daily
from scripts import signal_ceiling_score_report as ceiling
from scripts import signal_thesis_card_report as card
from scripts import signal_thesis_contract as tc

_REPO = Path(__file__).resolve().parents[1]


# --- score math (Section 2) ------------------------------------------------------

def test_machinery_and_operator_scores_both_reported():
    r = ceiling.build_report()
    assert "system_machinery_score" in r and "operator_reality_score" in r
    assert "current_score" not in r          # the flattering name is gone
    assert r["operator_reality_score"] < r["system_machinery_score"]
    assert "why_operator_reality_is_lower" in r


def test_operator_reality_includes_investability_and_calibration():
    r = ceiling.build_report()
    fam = r["score_families"]
    a, rr = fam["architecture_score"], fam["research_readiness_score"]
    e = r["segments"]["evidence_discipline"]["new"]
    c = fam["calibration_readiness_score"]
    i = fam["investability_readiness_score"]
    of = fam["outcome_factory_score"]
    live = fam["live_outcome_score"]
    expected = round(0.12 * a + 0.18 * rr + 0.18 * e + 0.17 * c
                     + 0.20 * i + 0.10 * of + 0.05 * live, 2)
    assert r["operator_reality_score"] == expected
    # investability and calibration must both appear as inputs
    assert 0.0 <= i <= 10.0 and 0.0 <= c <= 10.0


def test_vacuous_candidate_absence_does_not_inflate_investability(tmp_path):
    r = ceiling.build_report(root=tmp_path)   # empty repo: no candidates
    comps = r["score_families"]["investability_readiness_components"]
    assert comps["promoted_candidate_count_score"] == 0.0
    assert comps["hard_evidence_coverage"] == 0.0
    assert comps["fixture_contamination_absence"] is None   # NA, not 1
    assert r["score_families"]["investability_readiness_score"] == 0.0


def test_live_outcome_score_zero_without_matured_snapshots():
    r = ceiling.build_report()
    assert r["score_families"]["live_matured_snapshot_count"] == 0
    assert r["score_families"]["live_outcome_score"] == 0.0


# --- EDGAR edge typing (Section 3) ------------------------------------------------

def test_wise_own_filing_classified_self_filing():
    assert edg.classify_edge("Wise", "Wise Group plc  (WSE)") == edg.SELF_FILING
    assert edg.classify_edge("Amazon Web Services",
                             "AMAZON.COM, INC.") == edg.SELF_FILING


def test_other_filer_is_counterparty_or_stronger():
    assert edg.classify_edge("Wise", "Western Union CO") in (
        edg.COUNTERPARTY_FILING, edg.PARTNER_DISCLOSURE,
        edg.CLIENT_DEPENDENCY)
    assert edg.classify_edge(
        "Wise", "Grab Holdings", "payment processing agreement with Wise"
    ) == edg.CLIENT_DEPENDENCY
    assert edg.classify_edge(
        "Wise", "SomeCo", "competitors include Wise, among others"
    ) == edg.BOILERPLATE


def test_self_filing_and_boilerplate_never_admissible():
    assert edg.edge_admissible(edg.SELF_FILING, "acc-1", 0.99) is False
    assert edg.edge_admissible(edg.BOILERPLATE, "acc-1", 0.99) is False
    assert edg.edge_admissible(edg.CLIENT_DEPENDENCY, "acc-1", 0.60) is True
    assert edg.edge_admissible(edg.CLIENT_DEPENDENCY, "", 0.99) is False


def test_regenerated_report_counts_by_edge_type():
    report = json.loads((_REPO / "runtime/edgar_counterparty_report.json"
                         ).read_text(encoding="utf-8"))
    for key in ("self_filing_count", "counterparty_count",
                "hard_admissible_count", "total_edges"):
        assert key in report
    assert report["self_filing_count"] > 0
    assert (report["hard_admissible_count"]
            <= report["total_edges"] - report["self_filing_count"])


# --- ledger-aware shock loop (Section 4) -------------------------------------------

def _obs(ticker: str, ts: str, p: float, depth: float = 50_000.0) -> str:
    return json.dumps({
        "observation_id": f"{ticker}-{ts}", "market_ticker": ticker,
        "event_ticker": "FIX-EVT-RATECUT", "p": p, "depth_usd": depth,
        "fetch_timestamp": ts, "adapter_name": "kalshi_public_market_data",
        "adapter_run_id": f"run-{ts}", "source_hash": "aa" * 16,
        "source_mode": "LIVE", "is_live_verified": True})


def test_first_run_is_ledger_warmup(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(_obs("MKT-A", "2026-07-01T00:00:00Z", 0.50) + "\n",
                      encoding="utf-8")
    d = pm.detect_shocks_from_ledger(ledger)
    assert d["markets_with_prior"] == 0
    assert d["markets_warming_up"] == 1
    assert d["shocks"] == []


def test_second_run_can_emit_shock_from_history(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        _obs("MKT-A", "2026-07-01T00:00:00Z", 0.50) + "\n"
        + _obs("MKT-A", "2026-07-02T00:00:00Z", 0.65) + "\n",
        encoding="utf-8")
    d = pm.detect_shocks_from_ledger(ledger, threshold=0.10)
    assert d["markets_with_prior"] == 1
    assert len(d["shocks"]) == 1
    s = d["shocks"][0]
    assert s.source_mode == "LIVE" and s.adapter_run_id
    assert abs(s.delta_p - 0.15) < 1e-9


def test_small_move_or_sign_flip_emits_no_shock(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        _obs("MKT-A", "2026-07-01T00:00:00Z", 0.50) + "\n"
        + _obs("MKT-A", "2026-07-02T00:00:00Z", 0.53) + "\n"   # small
        + _obs("MKT-B", "2026-07-01T00:00:00Z", 0.50) + "\n"
        + _obs("MKT-B", "2026-07-02T00:00:00Z", 0.70) + "\n"
        + _obs("MKT-B", "2026-07-03T00:00:00Z", 0.52) + "\n",  # sign flip
        encoding="utf-8")
    d = pm.detect_shocks_from_ledger(ledger, threshold=0.10)
    assert d["shocks"] == []


# --- retrocast real-lite (Section 5) -----------------------------------------------

def test_real_lite_reports_unavailable_neutral_not_fixture(monkeypatch):
    monkeypatch.setattr(rc, "_kalshi_get",
                        lambda path, retries=3: ({"markets": []}, b"{}"))
    lite = rc.run_real_lite({"categories": {}})
    assert lite["blocker"] is None
    for row in lite["real_category_status"].values():
        assert row["real_status"] == "UNAVAILABLE_NEUTRAL"
    assert "records" not in lite      # no fixture data smuggled in


def test_real_lite_blocked_records_exact_blocker(monkeypatch):
    def boom(path, retries=3):
        raise rc.LiveSourceError("KALSHI_FETCH_FAILED after 3 attempts: X")
    monkeypatch.setattr(rc, "_kalshi_get", boom)
    lite = rc.run_real_lite({"categories": {}})
    assert "KALSHI_FETCH_FAILED" in lite["blocker"]
    for row in lite["real_category_status"].values():
        assert row["real_status"] == "BLOCKED_ADAPTER_LIMITATION"


# --- daily evidence run (Section 7) -----------------------------------------------

def test_daily_degraded_when_polymarket_blocked_but_kalshi_works():
    agg = daily.aggregate_statuses({
        "env": {"status": "OK"},
        "pm": {"status": "OK", "polymarket_blocked": True,
               "fixture_fallback_detected": False},
        "edgar": {"status": "SKIPPED"}, "retrocast": {"status": "SKIPPED"},
        "cards": {"status": "OK"}, "score": {"status": "OK"},
        "tests": {"status": "OK"}})
    assert agg["overall_status"] == "DEGRADED"
    assert any("Polymarket" in r for r in agg["degraded_reasons"])


def test_daily_blocked_on_test_failure_or_fixture_fallback():
    base = {"env": {"status": "OK"},
            "pm": {"status": "OK", "polymarket_blocked": False,
                   "fixture_fallback_detected": False},
            "edgar": {"status": "SKIPPED"}, "retrocast": {"status": "SKIPPED"},
            "cards": {"status": "OK"}, "score": {"status": "OK"},
            "tests": {"status": "FAIL"}}
    assert daily.aggregate_statuses(base)["overall_status"] == "BLOCKED"
    base["tests"] = {"status": "OK"}
    base["pm"] = {"status": "OK", "polymarket_blocked": False,
                  "fixture_fallback_detected": True}
    assert daily.aggregate_statuses(base)["overall_status"] == "BLOCKED"


# --- Wise card (Section 6) ---------------------------------------------------------

def test_wise_card_prints_binding_gate_and_next_actions():
    p = _REPO / "data/evidence/thesis_contracts/fbb46d359ead3369.json"
    c = tc.load_contract(p)
    report = tc.grade(c, 2374)
    md = card.render_thesis_card(c, report, 2374)
    assert "BindingGate = **EQS**" in md
    assert "Separate Wise self-filings" in md
    assert "RESEARCH ONLY — NOT A BUY LIST" in md
    assert c.next_evidence_actions and len(c.next_evidence_actions) == 5


def test_investable_board_still_empty():
    boards = card.build_boards([])
    md = card.render_board_markdown(boards)
    assert "No investable candidates currently promoted" in md[
        "INVESTABLE_CANDIDATE_BOARD"]
