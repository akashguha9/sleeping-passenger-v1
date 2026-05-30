"""Tests — operator readiness checklist (deterministic, pure).

Kanté Ceiling Push II, Workstream C.  Proves the readiness bands, that a
missing invalidation cannot reach READY, that the checklist never grants
execution permission, and that real-money sizing stays PROHIBITED.
"""
from __future__ import annotations

import pytest

from scripts.operator_readiness_checklist import (
    CHECKLIST_KEYS,
    LABEL_READY,
    LABEL_REVIEW_REQUIRED,
    build_operator_checklist,
)


def _all_checks(**overrides):
    checks = {k: True for k in CHECKLIST_KEYS}
    checks.update(overrides)
    return checks


# --- 1 ----------------------------------------------------------------------
def test_operator_checklist_missing_invalidation_review():
    r = build_operator_checklist(_all_checks(invalidation_recorded=False))
    assert r["readiness_label"] == LABEL_REVIEW_REQUIRED
    assert "invalidation_recorded" in r["missing_critical_checks"]


# --- 2 ----------------------------------------------------------------------
def test_operator_checklist_full_ready():
    r = build_operator_checklist(_all_checks())
    assert r["readiness_label"] == LABEL_READY
    assert r["checklist_completion_rate"] == pytest.approx(1.0)
    assert r["passed_checks"] == r["total_checks"]
    assert r["missing_critical_checks"] == []


# --- 3 ----------------------------------------------------------------------
def test_operator_checklist_no_execution_permission():
    for checks in ({}, _all_checks(), _all_checks(invalidation_recorded=False)):
        r = build_operator_checklist(checks)
        assert r["execution_permission_granted"] is False
        assert r["operator_execution_required"] is True
        assert r["execution_gate"] == "LOCKED"
        assert r["broker_api_called"] is False
        assert r["ai_execution_count"] == 0


# --- 4 ----------------------------------------------------------------------
def test_operator_checklist_real_money_prohibited():
    # Even passing real_money_sizing_prohibited=True, the output stamp is fixed.
    r = build_operator_checklist(_all_checks())
    assert r["real_money_sizing_impact"] == "PROHIBITED"
    assert r["real_money_weight_allowed"] is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
