"""Branch-stranding guard (Close-the-Loop sprint, 2026-07-04).

The forensic audit found a repeated process failure: flagship sprint work
(the outcome-maturation loop, the isolated-model-lanes scoring) was
committed to side branches, recorded as "shipped" in project memory, and
never merged — leaving the canonical branch unable to even READ the DB
tables the stranded code wrote.  56 timestamp-locked forward predictions
expired unmatured because of this.

This guard makes the failure mode loud on the CANONICAL branch:

1. Every DB table the evidence loop writes must have a reader in the
   working tree.
2. The maturation loop's public entry points must exist and be importable.
3. The daily scheduler must actually reference the maturation step.
4. Docs that claim a capability is shipped must point at code that exists.

If a future sprint strands its code on a branch again, this file fails the
suite instead of letting the gap hide for a month.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Public entry points the canonical branch must always carry.  Extend this
# list when a sprint ships a new load-bearing loop.
REQUIRED_MODULES: dict[str, tuple[str, ...]] = {
    "scripts.forward_outcome_maturity_scanner": ("scan_forward_outcome_maturity",),
    "scripts.run_daily_outcome_maturation": ("run_daily_outcome_maturation",),
    "scripts.attach_due_outcomes": ("attach_due_outcomes",),
    "scripts.real_calibration_evidence": ("build_calibration_evidence",),
    "scripts.decision_probability_snapshot": ("ensure_schema",),
    "scripts.benchmark_outcome_report": ("build_benchmark_comparison",),
    "scripts.holdings_truth_gate": ("load_holdings_truth_gate",),
    "scripts.truth_surface_report": ("compute_truth_surface",),
    # Feed-the-Loop sprint (2026-07-04): the compounding loop's new organs.
    "scripts.run_daily_live_advisory_decisions": ("run_daily_decision_batch",),
    "scripts.refresh_fresh_discovery_live": ("refresh_fresh_discovery",),
    "scripts.operator_alert_bridge": ("build_alerts_from_surface", "dispatch_alerts"),
    "scripts.kalshi_settlement_reconciliation": ("reconcile_settlements",),
    # Open-the-Gate sprint (2026-07-04): risk monitoring + proof organs.
    "scripts.drawdown_stop_monitor": ("run_drawdown_monitor",),
    "scripts.sheets_roundtrip_probe": ("run_roundtrip_probe",),
    "scripts.evidence_calendar": ("build_evidence_calendar",),
    "scripts.smoke_cockpit_truth": ("run_smoke",),
}

# DB tables written by the evidence loop -> at least one working-tree module
# that reads them.  A table with zero readers is orphaned evidence.
TABLE_READERS: dict[str, tuple[str, ...]] = {
    "decision_probability_snapshots": (
        "scripts/forward_outcome_maturity_scanner.py",
        "scripts/attach_due_outcomes.py",
        "scripts/truth_surface_report.py",
    ),
}


@pytest.mark.parametrize("module_name", sorted(REQUIRED_MODULES))
def test_required_entry_points_importable(module_name: str) -> None:
    mod = importlib.import_module(module_name)
    for attr in REQUIRED_MODULES[module_name]:
        assert hasattr(mod, attr), (
            f"{module_name}.{attr} missing — was this sprint's code stranded "
            "on a branch?"
        )


@pytest.mark.parametrize("table", sorted(TABLE_READERS))
def test_evidence_tables_have_working_tree_readers(table: str) -> None:
    readers = []
    for rel in TABLE_READERS[table]:
        path = REPO_ROOT / rel
        if path.exists() and table in path.read_text(encoding="utf-8"):
            readers.append(rel)
    assert readers, (
        f"DB table {table!r} has no reader in the working tree — orphaned "
        "evidence (this is exactly how 56 locked predictions expired unmatured)"
    )


def test_daily_scheduler_references_maturation() -> None:
    src = (REPO_ROOT / "scripts" / "nbi_scheduler.py").read_text(encoding="utf-8")
    assert "run_daily_outcome_maturation" in src, (
        "the installed daily loop no longer closes outcomes (audit SP-013)"
    )
    assert "run_daily_decision_batch" in src, (
        "the installed daily loop no longer PRODUCES snapshots — N stops "
        "compounding (Feed-the-Loop regression)"
    )
    assert "refresh_fresh_discovery" in src
    assert "reconcile_settlements" in src
    assert "dispatch_alerts" in src
    assert "run_drawdown_monitor" in src, (
        "the daily loop lost the drawdown/stop-breach monitor "
        "(Open-the-Gate regression)"
    )


def test_action_engine_references_canonical_holdings() -> None:
    src = (REPO_ROOT / "scripts" / "action_engine.py").read_text(encoding="utf-8")
    assert "holdings_truth_gate" in src, (
        "the action engine stopped reading the canonical holdings gate "
        "(audit SP-001 regression)"
    )


def test_docs_shipped_claims_point_at_existing_code() -> None:
    """Docs must not claim shipped capabilities whose code is absent.

    Narrow, mechanical contract: every relative ``scripts/*.py`` path named
    in the operational docs below must exist in the working tree.
    """
    docs = [
        REPO_ROOT / "docs" / "REAL_FORWARD_DAILY_RUNBOOK.md",
        REPO_ROOT / "docs" / "OPERATIONAL_TRUTH.md",
    ]
    import re

    missing: list[str] = []
    for doc in docs:
        if not doc.exists():
            continue
        for match in re.findall(r"scripts/[a-z0-9_/]+\.py", doc.read_text(encoding="utf-8")):
            if not (REPO_ROOT / match).exists():
                missing.append(f"{doc.name} -> {match}")
    assert missing == [], f"docs claim code that does not exist: {missing}"
