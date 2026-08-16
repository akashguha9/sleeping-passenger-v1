"""Tests — regime-transition inertia stack + titration/buffer/threshold +
flip engine.

Sprint matrix coverage: strong/weak policy inertia, capital commitment,
supply lead times, IIR bands; reinforcing/contradictory/duplicate/stale
evidence + decay; buffer strong vs depleted; noisy volatility without
supporting evidence; instability vs flip-probability separation.
"""
from __future__ import annotations

import pytest

from scripts.regime_transition_flip_engine import (
    NARRATIVE_NEW,
    NARRATIVE_OLD,
    NARRATIVE_TRANSITION,
    classify_narrative_state,
    narrative_instability_score,
    regime_flip_probability,
)
from scripts.regime_transition_inertia_engine import (
    IIR_NOISE,
    IIR_REGIME_THREAT,
    IIR_WOBBLE,
    InertiaEvidence,
    OK,
    PolicyGenealogyStep,
    UNKNOWN,
    impulse_to_inertia_ratio,
    inertia_stack,
)
from scripts.regime_transition_titration_engine import (
    BufferItem,
    EvidenceDrop,
    SENSITIVITY_RISING,
    TP_CRITICAL_ZONE,
    TP_LOW,
    UNCONFIRMED_NOISE,
    accumulate_evidence,
    buffer_state,
    threshold_pressure,
    threshold_sensitivity_diagnostic,
)


def _pol(mag=0.8, ref="PL-117-169"):
    return InertiaEvidence(kind="LEGISLATION", magnitude=mag,
                           confidence=0.9, evidence_ref=ref)


class TestInertia:
    def test_strong_policy_inertia(self):
        items = [
            _pol(), InertiaEvidence("BUDGET", 0.7, 0.9, "approps-2025"),
            InertiaEvidence("CONTRACT", 0.6, 0.8, "doe-loan-123"),
            InertiaEvidence("INSTITUTION", 0.5, 0.7, "agency-charter"),
        ]
        out = inertia_stack(policy_items=items)
        assert out["policy_inertia"]["status"] == OK
        assert out["policy_inertia"]["score"] > 70

    def test_weak_reversible_policy_scores_low(self):
        items = [InertiaEvidence("EXECUTIVE_ACTION", 0.3, 0.5, "eo-14000",
                                 direction=1),
                 InertiaEvidence("LEGISLATION", 0.4, 0.8, "sunset-clause",
                                 direction=-1)]
        out = inertia_stack(policy_items=items)
        assert out["policy_inertia"]["score"] < 30

    def test_uncited_items_dropped_never_scored(self):
        out = inertia_stack(policy_items=[
            InertiaEvidence("LEGISLATION", 0.9, 0.9, evidence_ref=None)])
        assert out["policy_inertia"]["status"] == UNKNOWN
        assert out["policy_inertia"]["score"] is None
        assert out["policy_inertia"]["dropped_uncited"] == 1

    def test_capital_and_supply_lanes(self):
        out = inertia_stack(
            capital_items=[
                InertiaEvidence("CAPEX_COMMITTED", 0.9, 0.9, "10-K-capex"),
                InertiaEvidence("ORDER_BACKLOG", 0.8, 0.9, "10-Q-backlog")],
            supply_chain_items=[
                InertiaEvidence("CAPACITY_LEAD_TIME", 0.9, 0.8, "ieee-lead"),
                InertiaEvidence("QUALIFICATION_CYCLE", 0.7, 0.8, "cert-doc")])
        assert out["capital_inertia"]["score"] > 70
        assert out["supply_chain_inertia"]["score"] > 60
        assert out["policy_inertia"]["status"] == UNKNOWN
        assert out["lane_coverage"] == pytest.approx(2 / 3, abs=1e-3)

    def test_genealogy_bump_and_chain(self):
        gen = [PolicyGenealogyStep(2020, "grid act", "ref-a"),
               PolicyGenealogyStep(2022, "ira", "ref-b"),
               PolicyGenealogyStep(2024, "permitting reform", "ref-c")]
        out = inertia_stack(policy_items=[_pol()], genealogy=gen)
        assert out["policy_genealogy"]["chain_length"] == 3
        assert out["policy_genealogy"]["span_years"] == 4
        assert out["policy_inertia"].get("genealogy_bump", 0) > 0

    def test_iir_bands(self):
        assert impulse_to_inertia_ratio(10, 80)["band"] == IIR_NOISE
        assert impulse_to_inertia_ratio(60, 80)["band"] == IIR_WOBBLE
        assert impulse_to_inertia_ratio(90, 20)["band"] == IIR_REGIME_THREAT
        assert impulse_to_inertia_ratio(None, 50)["status"] == UNKNOWN


class TestTitration:
    def test_reinforcing_evidence_accumulates(self):
        drops = [EvidenceDrop(d, 0.5, 1, f"src{d}", f"event {d}")
                 for d in range(5)]
        out = accumulate_evidence(drops, as_of_day=5)
        assert out["accumulated_pressure"] > 1.5
        assert out["independent_sources"] == 5

    def test_contradictory_evidence_subtracts(self):
        drops = [EvidenceDrop(1, 0.5, 1, "a", "pro"),
                 EvidenceDrop(2, 0.5, -1, "b", "contra")]
        out = accumulate_evidence(drops, as_of_day=2)
        assert abs(out["accumulated_pressure"]) < 0.05

    def test_duplicate_evidence_suppressed(self):
        drops = [EvidenceDrop(1, 0.5, 1, "a", "Same headline text"),
                 EvidenceDrop(2, 0.5, 1, "b", "  same HEADLINE   text ")]
        out = accumulate_evidence(drops, as_of_day=3)
        assert out["duplicates_suppressed"] == 1
        single = accumulate_evidence(drops[:1], as_of_day=3)
        assert out["accumulated_pressure"] == pytest.approx(
            single["accumulated_pressure"])

    def test_same_source_diminishing_independence(self):
        drops = [EvidenceDrop(1, 0.5, 1, "one_src", "story a"),
                 EvidenceDrop(1, 0.5, 1, "one_src", "story b")]
        out = accumulate_evidence(drops, as_of_day=1)
        two_src = accumulate_evidence(
            [EvidenceDrop(1, 0.5, 1, "a", "story a"),
             EvidenceDrop(1, 0.5, 1, "b", "story b")], as_of_day=1)
        assert out["accumulated_pressure"] < two_src["accumulated_pressure"]

    def test_stale_evidence_decays(self):
        old = accumulate_evidence(
            [EvidenceDrop(0, 0.9, 1, "a", "ancient story")], as_of_day=120)
        assert old["accumulated_pressure"] < 0.05
        assert old["stale_drops"] == 1

    def test_future_evidence_ignored_no_leakage(self):
        out = accumulate_evidence(
            [EvidenceDrop(10, 0.9, 1, "a", "from the future")], as_of_day=5)
        assert out["drops_considered"] == 0


class TestBufferAndThreshold:
    def _pressure(self, n=8):
        return accumulate_evidence(
            [EvidenceDrop(d, 0.6, 1, f"s{d}", f"drop {d}") for d in range(n)],
            as_of_day=n)

    def test_strong_buffer_suppresses_threshold_pressure(self):
        buf = buffer_state([BufferItem("INVENTORY", 0.9, "10-K-inv"),
                            BufferItem("SPARE_CAPACITY", 0.8, "eia-spare"),
                            BufferItem("CASH", 0.7, "10-Q-cash")])
        tp = threshold_pressure(accumulated=self._pressure(),
                                composite_inertia_0_100=70.0, buffer=buf)
        weak = buffer_state([BufferItem("INVENTORY", 0.9, "x")],
                            absorbed_stress=0.85)
        tp_weak = threshold_pressure(accumulated=self._pressure(),
                                     composite_inertia_0_100=70.0,
                                     buffer=weak)
        assert tp["threshold_pressure"] < tp_weak["threshold_pressure"]

    def test_depleted_buffer_critical_zone(self):
        depleted = buffer_state([BufferItem("RESERVES", 0.5, "spr-doc")],
                                absorbed_stress=0.5)
        assert depleted["remaining_buffer"] == 0.0
        tp = threshold_pressure(accumulated=self._pressure(10),
                                composite_inertia_0_100=10.0, buffer=depleted)
        assert tp["band"] == TP_CRITICAL_ZONE

    def test_low_pressure_low_band(self):
        tp = threshold_pressure(
            accumulated=accumulate_evidence(
                [EvidenceDrop(0, 0.1, 1, "a", "one small drop")], as_of_day=1),
            composite_inertia_0_100=80.0,
            buffer=buffer_state([BufferItem("CASH", 0.9, "ref")]))
        assert tp["band"] == TP_LOW

    def test_unknown_denominator_yields_unknown_not_inflated(self):
        tp = threshold_pressure(accumulated=self._pressure(),
                                composite_inertia_0_100=None,
                                buffer={"status": UNKNOWN})
        assert tp["status"] == UNKNOWN
        assert tp["threshold_pressure"] is None

    def test_volatility_without_evidence_is_noise(self):
        obs = [(1.0, 0.5), (1.0, 0.6), (1.0, 2.0), (1.0, 2.5)]
        diag = threshold_sensitivity_diagnostic(
            obs, accumulated_pressure=0.05)
        assert diag["label"] == UNCONFIRMED_NOISE
        assert diag["diagnostic_only"] is True
        confirmed = threshold_sensitivity_diagnostic(
            obs, accumulated_pressure=2.0)
        assert confirmed["label"] == SENSITIVITY_RISING


class TestFlipEngine:
    def _instability(self, strong=True):
        if strong:
            return narrative_instability_score(
                divergence_latest=0.20, divergence_velocity=0.05,
                probability_acceleration=0.02, nsd_score=0.6,
                threshold_pressure_band=TP_CRITICAL_ZONE,
                model_disagreement_0_1=0.8, catalyst_days_until=5)
        return narrative_instability_score(
            divergence_latest=0.02, divergence_velocity=0.0,
            probability_acceleration=0.0, nsd_score=0.05,
            threshold_pressure_band=TP_LOW,
            model_disagreement_0_1=0.1, catalyst_days_until=90)

    def test_instability_high_vs_low(self):
        assert self._instability(True)["instability_score"] > 70
        assert self._instability(False)["instability_score"] < 20

    def test_flip_distinct_from_instability_and_gated(self):
        inst = self._instability(True)
        flip = regime_flip_probability(
            instability=inst, threshold_pressure_band=TP_CRITICAL_ZONE,
            iir_band="DESTABILIZING")
        assert flip["status"] == OK
        assert flip["experimental"] is True
        assert flip["uncertainty_band"][0] < flip["flip_probability"]
        # Fragile but no corroborating pressure -> honestly NOT computed.
        blocked = regime_flip_probability(
            instability=inst, threshold_pressure_band=TP_LOW)
        assert blocked["status"] == "NOT_COMPUTED"
        assert blocked["flip_probability"] is None

    def test_low_instability_never_produces_flip(self):
        flip = regime_flip_probability(
            instability=self._instability(False),
            threshold_pressure_band=TP_CRITICAL_ZONE)
        assert flip["status"] == "NOT_COMPUTED"

    def test_insufficient_components_honest(self):
        inst = narrative_instability_score(divergence_latest=0.2)
        assert inst["status"] == "INSUFFICIENT_COMPONENTS"
        assert inst["instability_score"] is None

    def test_narrative_state_classification(self):
        strong = self._instability(True)
        weak = self._instability(False)
        flip = {"status": "NOT_COMPUTED"}
        assert classify_narrative_state(
            instability=weak, flip=flip,
            new_regime_evidence_share=0.9)["narrative_state"] == NARRATIVE_NEW
        assert classify_narrative_state(
            instability=weak, flip=flip,
            new_regime_evidence_share=0.1)["narrative_state"] == NARRATIVE_OLD
        assert classify_narrative_state(
            instability=strong, flip=flip,
            new_regime_evidence_share=0.5)["narrative_state"] == \
            NARRATIVE_TRANSITION
        assert classify_narrative_state(
            instability=strong, flip=flip,
            new_regime_evidence_share=None)["status"] == "UNKNOWN"
