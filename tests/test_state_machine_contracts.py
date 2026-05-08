"""Tests for the state machine contracts."""
from __future__ import annotations

import pytest

from scripts.state_machine_contracts import (
    Archetype,
    StateMachine,
    StateMachineError,
    TransitionReason,
    explain_forbidden_transitions,
)


class TestForbiddenTransitions:
    def test_miura_cannot_jump_to_gallardo(self):
        sm = StateMachine(Archetype.MIURA)
        with pytest.raises(StateMachineError):
            sm.transition(
                Archetype.GALLARDO,
                reason=TransitionReason.PROMOTION,
                confidence=0.9,
            )

    def test_miura_cannot_jump_to_aventador(self):
        sm = StateMachine(Archetype.MIURA)
        with pytest.raises(StateMachineError):
            sm.transition(Archetype.AVENTADOR, confidence=1.0)

    def test_miura_cannot_jump_to_deploy(self):
        sm = StateMachine(Archetype.MIURA)
        with pytest.raises(StateMachineError):
            sm.transition(Archetype.DEPLOY, confidence=1.0)

    def test_diablo_cannot_deploy(self):
        sm = StateMachine(Archetype.DIABLO)
        with pytest.raises(StateMachineError):
            sm.transition(Archetype.DEPLOY, confidence=1.0)

    def test_jail_cannot_deploy(self):
        sm = StateMachine(Archetype.JAIL)
        with pytest.raises(StateMachineError):
            sm.transition(Archetype.DEPLOY, confidence=1.0)

    def test_huracan_cannot_deploy_directly(self):
        sm = StateMachine(Archetype.HURACAN)
        with pytest.raises(StateMachineError):
            sm.transition(Archetype.DEPLOY, confidence=1.0)


class TestSpecialRules:
    def test_diablo_creates_veto_consequence(self):
        sm = StateMachine(Archetype.MIURA)
        record = sm.transition(
            Archetype.DIABLO,
            reason=TransitionReason.CHAOS_DETECTED,
            confidence=0.5,
        )
        assert "veto" in record.consequence

    def test_islero_forces_reclassification(self):
        sm = StateMachine(Archetype.MIURA)
        record = sm.transition(
            Archetype.ISLERO,
            reason=TransitionReason.RECLASSIFICATION,
            confidence=0.5,
        )
        assert "reclassif" in record.consequence

    def test_huracan_fast_track_requires_validation_floor(self):
        sm = StateMachine(Archetype.HURACAN, huracan_validation_floor=0.6)
        with pytest.raises(StateMachineError):
            sm.transition(
                Archetype.GALLARDO,
                reason=TransitionReason.FAST_TRACK_QUALIFIED,
                confidence=0.3,
            )

    def test_huracan_fast_track_passes_above_floor(self):
        sm = StateMachine(Archetype.HURACAN, huracan_validation_floor=0.6)
        record = sm.transition(
            Archetype.GALLARDO,
            reason=TransitionReason.FAST_TRACK_QUALIFIED,
            confidence=0.7,
        )
        assert record.to_state == Archetype.GALLARDO

    def test_jail_blocks_new_risk_deployment(self):
        sm = StateMachine(Archetype.MIURA)
        record = sm.transition(
            Archetype.JAIL, reason=TransitionReason.QUARANTINE, confidence=0.0
        )
        assert "block" in record.consequence
        with pytest.raises(StateMachineError):
            sm.transition(Archetype.DEPLOY, confidence=1.0)


class TestTransitionLog:
    def test_log_records_transitions(self):
        sm = StateMachine(Archetype.MIURA)
        sm.transition(
            Archetype.HURACAN,
            reason=TransitionReason.PROMOTION,
            confidence=0.7,
        )
        sm.transition(
            Archetype.GALLARDO,
            reason=TransitionReason.FAST_TRACK_QUALIFIED,
            confidence=0.8,
        )
        log = sm.transition_log
        assert len(log) == 2
        assert log[0].from_state == Archetype.MIURA
        assert log[1].to_state == Archetype.GALLARDO

    def test_log_serialises(self):
        sm = StateMachine(Archetype.MIURA)
        sm.transition(
            Archetype.ISLERO,
            reason=TransitionReason.RECLASSIFICATION,
            confidence=0.5,
        )
        out = sm.serialize_log()
        assert isinstance(out, list)
        assert out[0]["to_state"] == "ISLERO"


def test_explain_forbidden_transitions_lists_all():
    out = explain_forbidden_transitions()
    assert any("MIURA -> GALLARDO" in row for row in out)
    assert any("DIABLO -> DEPLOY" in row for row in out)
    assert any("JAIL -> DEPLOY" in row for row in out)
