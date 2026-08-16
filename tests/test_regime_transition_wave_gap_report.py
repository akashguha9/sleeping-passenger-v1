"""Tests — regime-transition wave graph, propagation gap (PEG) and report.

Sprint matrix coverage: upstream/downstream propagation, bidirectional
feedback, differing edge lags, disconnected nodes, cite-or-drop edges;
PEG four cases (gap open / both moved / price led / weak exposure) plus
stale price; report gates, provenance labels and advisory stamps.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.regime_transition_propagation_gap_engine import (
    ABSORBED,
    CONTRARY_MOVE,
    GAP_OPEN,
    NO_EXPOSURE,
    OK,
    PARTIALLY_ABSORBED,
    PRICE_LED,
    UNKNOWN,
    propagation_gap,
    rank_gap_candidates,
)
from scripts.regime_transition_report import (
    assemble_candidate_card,
    write_report,
)
from scripts.regime_transition_wave_engine import (
    ARRIVING,
    DEMAND_SHOCK,
    NOT_YET_REACHED,
    SUPPLY_SHOCK,
    WaveEdge,
    WaveGraph,
    backwash_diagnostic,
    wavefront,
)


def _graph():
    # mines -> copper -> transformers -> datacenters -> ai (supply flows down)
    return WaveGraph(edges=[
        WaveEdge("mines", "copper", 0.9, 30, 0.9, 0.9, "usgs-ref"),
        WaveEdge("copper", "transformers", 0.8, 20, 0.9, 0.9, "10-K-tx"),
        WaveEdge("transformers", "datacenters", 0.8, 15, 0.9, 0.9, "eia-ref"),
        WaveEdge("datacenters", "ai", 0.9, 10, 0.9, 0.9, "capex-ref"),
    ])


class TestWavePropagation:
    def test_demand_shock_travels_upstream_with_cumulative_lags(self):
        prop = _graph().propagate(origin="ai", shock_kind=DEMAND_SHOCK,
                                  magnitude=1.0, shock_day=0)
        assert "mines" in prop["nodes"]
        assert prop["nodes"]["datacenters"]["arrival_day"] == 10
        assert prop["nodes"]["transformers"]["arrival_day"] == 25
        assert prop["nodes"]["mines"]["arrival_day"] == 75
        assert prop["nodes"]["mines"]["impact"] < \
            prop["nodes"]["datacenters"]["impact"]

    def test_supply_shock_travels_downstream(self):
        prop = _graph().propagate(origin="copper", shock_kind=SUPPLY_SHOCK,
                                  magnitude=1.0, shock_day=0)
        assert "ai" in prop["nodes"]
        assert "mines" not in prop["nodes"]  # supply shock does not go up

    def test_uncited_edge_transmits_nothing(self):
        g = WaveGraph(edges=[WaveEdge("a", "b", 0.9, 5, 0.9, 0.9, None)])
        prop = g.propagate(origin="a", shock_kind=SUPPLY_SHOCK,
                           magnitude=1.0, shock_day=0)
        assert "b" not in prop["nodes"]
        assert prop["dropped_uncited_edges"] == 1

    def test_disconnected_node_unreached(self):
        prop = _graph().propagate(origin="ai", shock_kind=DEMAND_SHOCK,
                                  magnitude=1.0, shock_day=0)
        assert "unrelated_co" not in prop["nodes"]

    def test_feedback_loop_detected_and_backwash_flagged(self):
        g = _graph()
        g.edges.append(WaveEdge("ai", "copper", 0.5, 60, 0.9, 0.9,
                                "induced-capex-ref"))
        prop = g.propagate(origin="copper", shock_kind=SUPPLY_SHOCK,
                           magnitude=1.0, shock_day=0)
        diag = backwash_diagnostic(prop)
        assert diag["backwash_risk"] == "FEEDBACK_LOOP_PRESENT"
        assert diag["diagnostic_only"] is True

    def test_no_loop_no_backwash(self):
        prop = _graph().propagate(origin="copper", shock_kind=SUPPLY_SHOCK,
                                  magnitude=1.0, shock_day=0)
        assert backwash_diagnostic(prop)["backwash_risk"] == "NONE_DETECTED"

    def test_wavefront_states_and_ahead_list(self):
        prop = _graph().propagate(origin="ai", shock_kind=DEMAND_SHOCK,
                                  magnitude=1.0, shock_day=0)
        wf = wavefront(prop, today=30,
                       absorption={"datacenters": 0.9, "transformers": 0.2})
        assert wf["nodes"]["datacenters"]["wavefront_state"] == "ABSORBED"
        assert wf["nodes"]["transformers"]["wavefront_state"] == ARRIVING
        assert wf["nodes"]["mines"]["wavefront_state"] == NOT_YET_REACHED
        assert "mines" in wf["ahead_of_wavefront"]
        assert "datacenters" not in wf["ahead_of_wavefront"]


class TestPropagationGap:
    def _gap(self, **kw):
        defaults = dict(ticker="XYZ", delta_p_event=0.35,
                        prob_move_start_day=10, exposure=0.6,
                        exposure_evidence_ref="10-K-seg",
                        observed_price_move=0.0, price_move_start_day=12,
                        price_age_days=0)
        defaults.update(kw)
        return propagation_gap(**defaults)

    def test_probability_moved_stock_did_not_gap_open(self):
        g = self._gap(observed_price_move=0.002)
        assert g["gap_state"] == GAP_OPEN
        assert g["unabsorbed_fraction"] > 0.9

    def test_both_moved_absorbed(self):
        g = self._gap(observed_price_move=0.070)
        assert g["gap_state"] == ABSORBED

    def test_partial_absorption(self):
        g = self._gap(observed_price_move=0.030)
        assert g["gap_state"] == PARTIALLY_ABSORBED

    def test_stock_moved_before_probability_price_led(self):
        g = self._gap(observed_price_move=0.06, price_move_start_day=3)
        assert g["gap_state"] == PRICE_LED

    def test_weak_exposure_is_not_a_lagging_beneficiary(self):
        g = self._gap(exposure=0.05)
        assert g["gap_state"] == NO_EXPOSURE

    def test_uncited_exposure_unknown(self):
        g = self._gap(exposure_evidence_ref=None)
        assert g["status"] == UNKNOWN
        assert g["gap_state"] is None

    def test_stale_price_unknown_never_fake_gap(self):
        g = self._gap(price_age_days=9)
        assert g["status"] == UNKNOWN

    def test_contrary_move_flagged(self):
        g = self._gap(observed_price_move=-0.05)
        assert g["gap_state"] == CONTRARY_MOVE

    def test_direction_negative_event_harms(self):
        g = self._gap(direction=-1, observed_price_move=-0.07)
        assert g["gap_state"] == ABSORBED

    def test_ranking_prefers_large_open_gaps(self):
        big = self._gap(observed_price_move=0.001, exposure=0.9)
        small = self._gap(observed_price_move=0.03, exposure=0.3)
        excluded = self._gap(exposure=0.05)
        ranked = rank_gap_candidates([small, excluded, big])
        assert ranked[0] is big
        assert excluded not in ranked

    def test_provenance_labels_present(self):
        g = self._gap()
        assert g["provenance"]["delta_p_event"] == "OBSERVED"
        assert g["provenance"]["sensitivity"] == "ASSUMED"


class TestReport:
    def _card(self, **kw):
        peg = propagation_gap(
            ticker="XYZ", delta_p_event=0.35, prob_move_start_day=10,
            exposure=0.6, exposure_evidence_ref="10-K-seg",
            observed_price_move=0.002, price_move_start_day=12,
            price_age_days=0)
        defaults = dict(
            ticker="XYZ", event_id="EV-1", peg=peg,
            divergence={"status": "OK", "divergence_latest": 0.15},
            instability={"status": "OK", "instability_score": 65.0},
            titration={"status": "OK", "accumulated_pressure": 1.4},
        )
        defaults.update(kw)
        return assemble_candidate_card(**defaults)

    def test_peg_only_card_below_coverage_floor_is_unranked(self):
        peg = propagation_gap(
            ticker="XYZ", delta_p_event=0.35, prob_move_start_day=10,
            exposure=0.6, exposure_evidence_ref="10-K-seg",
            observed_price_move=0.002, price_move_start_day=12,
            price_age_days=0)
        c = assemble_candidate_card(ticker="XYZ", event_id="EV-1", peg=peg)
        assert c["hard_gate_failed"] is False
        assert c["research_priority"] is None  # honest: too few components
        assert c["priority_coverage"] < 0.45

    def test_card_has_provenance_and_safety(self):
        c = self._card()
        assert c["safety"]["advisory_status"] == "ADVISORY_ONLY"
        assert c["safety"]["execution_gate"] == "LOCKED"
        assert c["fields"]["pmds"]["provenance"] == "EXPERIMENTAL"
        assert c["fields"]["regime_flip_probability"]["provenance"] == \
            "EXPERIMENTAL"
        assert c["signal_class"] == "RESEARCH_TRIAGE_ONLY"
        assert c["reason_it_may_be_wrong"]

    def test_priority_computed_when_gates_pass(self):
        c = self._card()
        assert c["hard_gate_failed"] is False
        assert c["research_priority"] is not None
        assert c["research_priority"] > 0

    def test_uncited_exposure_hard_gate_blocks_priority(self):
        peg = propagation_gap(
            ticker="ABC", delta_p_event=0.35, prob_move_start_day=10,
            exposure=0.6, exposure_evidence_ref=None,
            observed_price_move=0.002)
        c = assemble_candidate_card(ticker="ABC", event_id="EV-1", peg=peg)
        assert c["hard_gate_failed"] is True
        assert c["research_priority"] is None

    def test_stale_price_hard_gate(self):
        peg = propagation_gap(
            ticker="ABC", delta_p_event=0.35, prob_move_start_day=10,
            exposure=0.6, exposure_evidence_ref="ref",
            observed_price_move=0.002, price_age_days=30)
        c = assemble_candidate_card(ticker="ABC", event_id="EV-1", peg=peg)
        assert c["hard_gate_failed"] is True

    def test_halflife_scales_priority_down(self):
        fresh = self._card(halflife_remaining_0_1=1.0)
        stale = self._card(halflife_remaining_0_1=0.2)
        assert stale["research_priority"] < fresh["research_priority"]

    def test_write_report_files(self, tmp_path: Path):
        cards = [self._card()]
        peg_gated = propagation_gap(
            ticker="ABC", delta_p_event=0.35, prob_move_start_day=10,
            exposure=0.6, exposure_evidence_ref=None,
            observed_price_move=0.002)
        cards.append(assemble_candidate_card(
            ticker="ABC", event_id="EV-1", peg=peg_gated))
        paths = write_report(cards, report_date="2026-08-16",
                             reports_dir=tmp_path)
        assert paths["json"].exists() and paths["md"].exists()
        md = paths["md"].read_text(encoding="utf-8")
        assert "RESEARCH TRIAGE ONLY" in md
        assert "XYZ" in md and "ABC" in md
        for word in ("BUY", "SELL", "execute this"):
            assert word not in md

    def test_empty_report_fails_closed_gracefully(self, tmp_path: Path):
        paths = write_report([], report_date="2026-08-16",
                             reports_dir=tmp_path)
        md = paths["md"].read_text(encoding="utf-8")
        assert "No candidates passed" in md
