"""Inventory test for ``scripts/_legacy_layers/README.md``.

Identity Collapse + First-Day Operator sprint, Phase 2.

Every module listed in the legacy inventory must exist on disk.  Every
module that matches the metaphor / archetype vocabulary glob must either
be in the inventory or be explicitly canonical.  This prevents silent
drift in either direction:

* A legacy module deleted on disk shows up loudly.
* A new metaphor module added in the future without being listed is
  flagged for triage.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = REPO_ROOT / "scripts" / "_legacy_layers" / "README.md"
SCRIPTS_DIR = REPO_ROOT / "scripts"


# Canonical modules — even if their filename hints at metaphor vocabulary,
# they are NOT legacy and are intentionally absent from the inventory.
CANONICAL_ALLOWLIST: set[str] = {
    "advisory_contract.py",
    "live_source_registry.py",
    "refresh_live_signals.py",
    "watchdog_refresh_stale_sources.py",
    "persistence.py",
    "api_server.py",
    "calibration_report.py",
    "first_run_seed_free_sources.py",
    "runtime_truth_purity_audit.py",
    "moltbook_api.py",
    "moltbook_reconciliation_bridge.py",
}


def _parse_inventory() -> set[str]:
    """Pull every ``scripts/<name>.py`` token from the inventory markdown."""
    assert INVENTORY_PATH.exists(), f"missing legacy inventory: {INVENTORY_PATH}"
    text = INVENTORY_PATH.read_text(encoding="utf-8")
    # The inventory table lists each module as ``scripts/<name>.py``.
    return set(re.findall(r"scripts/([A-Za-z0-9_]+\.py)", text))


def _vocabulary_glob() -> list[str]:
    """Filenames in scripts/ matching the legacy vocabulary."""
    pattern = re.compile(
        r"(archetype|baines|chess|tennis|casino|monopoly|football|hedge_trade|"
        r"extreme_state|signal_metabolism|signal_surface|signal_refinery|"
        r"signal_vocoder|signal_zeta|signal_texture|structural_admission|"
        r"structural_design|structural_integrity|latent_signal|"
        r"contextual_interpretation|narrative_archetype|board_control|"
        r"false_negative|field_dynamics)",
        re.IGNORECASE,
    )
    out: list[str] = []
    for p in sorted(SCRIPTS_DIR.iterdir()):
        if p.is_file() and p.suffix == ".py" and pattern.search(p.name):
            out.append(p.name)
    return out


def test_inventory_lists_at_least_one_module():
    assert len(_parse_inventory()) >= 10


def test_every_inventoried_module_exists():
    listed = _parse_inventory()
    missing = [name for name in listed if not (SCRIPTS_DIR / name).exists()]
    assert not missing, f"inventory references modules that no longer exist: {missing}"


def test_no_metaphor_module_outside_inventory_unless_canonical():
    """Every metaphor-vocabulary module must either be inventoried or be
    on the canonical allow-list."""
    listed = _parse_inventory()
    found = _vocabulary_glob()
    leaked = [
        name
        for name in found
        if name not in listed and name not in CANONICAL_ALLOWLIST
    ]
    assert not leaked, (
        f"metaphor-vocabulary modules not classified — add to "
        f"scripts/_legacy_layers/README.md or the canonical allow-list: {leaked}"
    )


def test_inventory_advisory_only_invariants_documented():
    text = INVENTORY_PATH.read_text(encoding="utf-8")
    assert "advisory-only" in text.lower()
    assert "broker" in text.lower()
    assert "predictive" in text.lower()


def test_inventory_math_block_present():
    text = INVENTORY_PATH.read_text(encoding="utf-8")
    assert "LegacyRatio" in text
    assert "S_total" in text
