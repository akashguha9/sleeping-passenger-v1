"""CI-safe import contract for the daily synthesis pipeline.

Regression guard for the GitHub Actions collection failure where
``scripts.daily_synthesis_pipeline`` raised ``ModuleNotFoundError: No module
named 'scripts.external_advisory_evidence'`` during ``python -m pytest tests``.

Root cause: ``scripts`` had no ``__init__.py``, so it behaved as a *namespace*
package whose ``__path__`` resolution was order-dependent across a large mixed
collection.  Combined with a brittle ``try/except ModuleNotFoundError`` import
fallback, a missing submodule was masked into a misleading ``advisory_contract``
error.  These tests pin the package shape and the canonical imports so the
failure cannot silently return.

No network, no DB, no API keys, no local payload artifacts are touched.
"""
from __future__ import annotations

import importlib
from pathlib import Path


def test_scripts_is_a_regular_package_not_namespace() -> None:
    """``scripts`` must be a regular package (deterministic resolution).

    A namespace package has ``__file__ is None``; a regular package's
    ``__file__`` points at its ``__init__.py``.  Pinning this prevents the
    order-dependent collection flake from returning.
    """
    import scripts

    assert scripts.__file__ is not None, "scripts must not be a namespace package"
    assert Path(scripts.__file__).name == "__init__.py"


def test_daily_synthesis_pipeline_imports_cleanly() -> None:
    dsp = importlib.import_module("scripts.daily_synthesis_pipeline")
    assert hasattr(dsp, "run_daily_synthesis")


def test_evidence_and_contract_modules_import() -> None:
    importlib.import_module("scripts.external_advisory_evidence")
    importlib.import_module("scripts.advisory_contract")


def test_advisory_only_posture_preserved() -> None:
    """The pipeline's safety contract must stay advisory-only."""
    from scripts.advisory_contract import advisory_safety_stamps, human_only_stamp

    stamps = advisory_safety_stamps()
    assert stamps["advisory_status"] == "ADVISORY_ONLY"
    assert stamps["broker_api_called"] is False
    assert stamps["ai_execution_count"] == 0
    assert stamps["execution_permission"] is False
    assert stamps["can_execute"] is False

    human = human_only_stamp()
    assert human["human_review_required"] is True
    assert human["human_final_decision_required"] is True
