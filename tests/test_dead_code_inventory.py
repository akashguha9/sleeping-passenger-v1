"""Tests — Real Evidence Sprint Phase 7: dead-code inventory (read-only).

Proves the inventory runs and returns the expected shape, that it NEVER
deletes a file, and that the runtime-artifact untracked patterns are documented.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import dead_code_inventory as dci


def _snapshot_scripts() -> set[str]:
    root = Path(dci.REPO_ROOT) / "scripts"
    return {str(p) for p in root.rglob("*.py")}


# --- 1. inventory runs -----------------------------------------------------
def test_dead_code_inventory_runs():
    inv = dci.build_inventory()
    for key in [
        "n_scripts", "unreferenced_candidates", "modules_without_tests",
        "metaphor_labeled_modules", "legacy_quarantine_files",
        "runtime_artifact_patterns", "deletes_files",
    ]:
        assert key in inv
    assert inv["n_scripts"] > 0
    assert isinstance(inv["unreferenced_candidates"], list)
    assert inv["deletes_files"] is False
    # The Phase-1..6 modules we just added must NOT be flagged unreferenced,
    # because their tests import them.
    for mod in [
        "real_evidence_canary", "outcome_labeling_flow",
        "real_calibration_evidence", "portfolio_correlation_guard",
    ]:
        assert mod not in inv["unreferenced_candidates"]


# --- 2. inventory does not delete files ------------------------------------
def test_dead_code_inventory_does_not_delete_files(tmp_path):
    before = _snapshot_scripts()
    inv = dci.build_inventory()
    dci.write_report(inv, tmp_path / "DEAD_CODE_AUDIT.md")
    after = _snapshot_scripts()
    assert before == after, "inventory must not add/remove any script file"
    assert (tmp_path / "DEAD_CODE_AUDIT.md").exists()
    # The module never imports a destructive API.
    src = (Path(dci.REPO_ROOT) / "scripts" / "dead_code_inventory.py").read_text(encoding="utf-8")
    for forbidden in ["os.remove(", "os.unlink(", "shutil.rmtree(", "Path.unlink("]:
        assert forbidden not in src


# --- 3. runtime artifact patterns documented -------------------------------
def test_runtime_artifacts_not_staged_pattern_documented():
    inv = dci.build_inventory()
    patterns = inv["runtime_artifact_patterns"]
    for expected in ["runtime/", "*.db", "logs/", "data/daily_payload_backup_*/"]:
        assert expected in patterns
    md = dci.render_markdown(inv)
    assert "Runtime-artifact patterns" in md
    assert "data/daily_payload_backup_*/" in md


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
