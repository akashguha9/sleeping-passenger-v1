"""Tests — core live path manifest + maintainability guardrails (Phase 7).

Proves the core-live-path manifest exists and names the spine (live decision
path, evidence routes, real-evidence refresh), that the dead-code inventory is
strictly read-only (never deletes), and that the private scope guard knows the
new advisory-only evidence modules.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST = _REPO_ROOT / "docs" / "CORE_LIVE_PATH_MANIFEST.md"


def _manifest_text() -> str:
    return _MANIFEST.read_text(encoding="utf-8")


# --- 1. manifest exists --------------------------------------------------- #

def test_core_live_path_manifest_exists():
    assert _MANIFEST.exists(), "docs/CORE_LIVE_PATH_MANIFEST.md is missing"
    assert _manifest_text().strip(), "manifest is empty"


# --- 2. mentions the live decision path ----------------------------------- #

def test_manifest_mentions_live_decision_path():
    assert "live_decision_path.py" in _manifest_text()


# --- 3. mentions the evidence routes -------------------------------------- #

def test_manifest_mentions_evidence_routes():
    text = _manifest_text()
    assert "evidence_router.py" in text
    assert "/evidence/" in text


# --- 4. mentions the real-evidence refresh -------------------------------- #

def test_manifest_mentions_real_evidence_refresh():
    assert "refresh_real_evidence.py" in _manifest_text()


# --- 5. dead-code inventory never deletes --------------------------------- #

def test_dead_code_inventory_does_not_delete_files():
    from scripts.dead_code_inventory import build_inventory

    inv = build_inventory()
    assert inv["deletes_files"] is False
    # The map is advisory and read-only.
    assert inv["advisory_status"] == "ADVISORY_ONLY"
    assert inv["execution_gate"] == "LOCKED"


# --- 6. scope guard knows the new evidence modules ------------------------ #

def test_private_scope_guard_knows_new_evidence_modules():
    from scripts.private_scope_guard import EXPLICIT_IN_SCOPE

    for module in (
        "run_daily_live_advisory_decisions.py",
        "attach_due_outcomes.py",
        "refresh_real_evidence.py",
    ):
        assert module in EXPLICIT_IN_SCOPE, f"{module} not registered in scope guard"


def test_manifest_advisory_safety_language():
    text = _manifest_text().lower()
    assert "advisory-only" in text
    assert "execution_gate" in text
    assert "broker" in text


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
