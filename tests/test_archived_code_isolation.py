"""Guard: archived/experimental dead code stays out of the runtime.

After Phase 5 the vendored fMRI library (tribev2) and the broken-file
quarantine were moved to archived_experimental/. These tests ensure that:

  1. The production-core backend modules import cleanly and do NOT pull in
     anything under archived_experimental/ (directly or transitively).
  2. The tribev2 research adapter remains sandbox-only (wired_into_pipeline
     is False) and does not import the archived library.
  3. No file under scripts/ or src/ references the archived package paths.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ARCHIVED = REPO_ROOT / "archived_experimental"

PRODUCTION_CORE_MODULES = [
    "scripts.api_server",
    "scripts.signal_inbox_api",
    "scripts.persistence",
    "scripts.leverage_governance",
    "scripts.score_calibration",
    "scripts.diablo_narrative_veto",
    "scripts.event_prior_detector",
    "scripts.moltbook_feedback",
    "scripts.calibration_gate",
]


def test_archived_dir_exists_and_holds_dead_code():
    assert ARCHIVED.is_dir()
    assert (ARCHIVED / "tribev2").is_dir()
    assert (ARCHIVED / "_quarantine").is_dir()


def test_old_runtime_paths_are_gone():
    assert not (REPO_ROOT / "scripts" / "external" / "tribev2").exists()
    assert not (REPO_ROOT / "scripts" / "_quarantine").exists()


@pytest.mark.parametrize("modname", PRODUCTION_CORE_MODULES)
def test_core_module_imports_without_archived_code(modname):
    importlib.import_module(modname)
    leaked = [
        name
        for name in sys.modules
        if "archived_experimental" in name or name.startswith("tribev2")
    ]
    assert not leaked, f"{modname} pulled in archived code: {leaked}"


def test_tribev2_adapter_is_sandbox_only_and_does_not_import_archived():
    from scripts.tribev2_adapter import get_tribev2_adapter_summary

    summary = get_tribev2_adapter_summary()
    assert summary["healthcheck"]["wired_into_pipeline"] is False
    leaked = [n for n in sys.modules if "archived_experimental" in n or n.startswith("tribev2")]
    assert not leaked, f"tribev2 adapter imported archived library: {leaked}"


def test_no_source_file_references_archived_paths():
    needles = ("scripts.external.tribev2", "scripts/external/tribev2", "scripts._quarantine", "scripts/_quarantine")
    offenders: list[str] = []
    for base in ("scripts", "src"):
        root = REPO_ROOT / base
        if not root.exists():
            continue
        for py in root.rglob("*.py"):
            text = py.read_text(encoding="utf-8-sig", errors="ignore")
            for needle in needles:
                if needle in text:
                    offenders.append(f"{py.relative_to(REPO_ROOT)} -> {needle}")
    assert not offenders, "stale references to archived paths:\n" + "\n".join(offenders)
