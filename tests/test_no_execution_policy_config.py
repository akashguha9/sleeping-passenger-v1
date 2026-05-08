"""
Tests for the no-execution policy config and its enforcement across all
ingestion loaders.

Validates that:
1. no_execution_policy.yaml is valid and contains required fields.
2. No ingestion loader source file defines forbidden execution methods.
3. No ingestion loader imports execution modules.
4. LoaderResult carries the correct advisory contract.
5. Phase 1 compatibility is preserved after Phase 2 import.
"""
from __future__ import annotations

import ast
import dataclasses
import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INGESTION_DIR = REPO_ROOT / "scripts" / "ingestion"
POLICY_PATH = REPO_ROOT / "configs" / "no_execution_policy.yaml"

FORBIDDEN_METHODS = {
    "place_order",
    "modify_order",
    "cancel_order",
    "submit_order",
    "execute_trade",
    "auto_buy",
    "auto_sell",
}

FORBIDDEN_IMPORTS = {
    "paper_execution",
    "live_execution",
    "build_paper_order",
    "build_live_order",
}


def _ingestion_py_files() -> list[Path]:
    if not INGESTION_DIR.exists():
        return []
    return sorted(INGESTION_DIR.glob("*.py"))


# ---------------------------------------------------------------------------
# Policy file validation
# ---------------------------------------------------------------------------


class TestNoExecutionPolicyFile:
    def test_policy_file_exists(self) -> None:
        assert POLICY_PATH.exists(), f"Missing: {POLICY_PATH}"

    def test_policy_file_parseable(self) -> None:
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_advisory_status_is_advisory_only(self) -> None:
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
        assert data["advisory_status"] == "ADVISORY_ONLY"

    def test_execution_gate_is_locked(self) -> None:
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
        assert data["execution_gate"] == "LOCKED"

    def test_human_review_required_is_true(self) -> None:
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
        assert data["human_review_required"] is True

    def test_policy_lists_all_forbidden_methods(self) -> None:
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
        listed = set(data["prohibitions"]["forbidden_methods"])
        missing = FORBIDDEN_METHODS - listed
        assert not missing, f"Policy is missing forbidden methods: {missing}"

    def test_policy_has_required_sections(self) -> None:
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
        for section in ("prohibitions", "output_contract", "api_credential_policy"):
            assert section in data, f"Policy missing required section: {section!r}"

    def test_missing_key_behavior_is_skip_cleanly(self) -> None:
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
        cred = data["api_credential_policy"]
        assert cred["missing_key_behavior"] == "skip_cleanly"
        assert cred["missing_key_exception"] == "SkipLoader"
        assert cred["tests_must_not_fail_on_missing_key"] is True
        assert cred["do_not_hardcode_secrets"] is True

    def test_schema_version_present(self) -> None:
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
        assert "schema_version" in data


# ---------------------------------------------------------------------------
# AST-level source code enforcement
# ---------------------------------------------------------------------------


class TestSourceCodeEnforcement:
    @pytest.mark.parametrize("py_file", _ingestion_py_files())
    def test_no_forbidden_method_definitions(self, py_file: Path) -> None:
        source = py_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            pytest.fail(f"{py_file.name}: SyntaxError: {exc}")

        defined: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(node.name)

        violations = defined & FORBIDDEN_METHODS
        assert not violations, (
            f"{py_file.name} defines forbidden execution methods: {violations}"
        )

    @pytest.mark.parametrize("py_file", _ingestion_py_files())
    def test_no_forbidden_imports(self, py_file: Path) -> None:
        source = py_file.read_text(encoding="utf-8")
        for mod in FORBIDDEN_IMPORTS:
            assert f"import {mod}" not in source, (
                f"{py_file.name}: forbidden `import {mod}`"
            )
            assert f"from {mod}" not in source, (
                f"{py_file.name}: forbidden `from {mod}`"
            )

    @pytest.mark.parametrize("py_file", _ingestion_py_files())
    def test_no_raw_execution_calls(self, py_file: Path) -> None:
        source = py_file.read_text(encoding="utf-8")
        for call in ("place_order(", "execute_trade(", "submit_order("):
            assert call not in source, (
                f"{py_file.name}: forbidden call pattern {call!r}"
            )


# ---------------------------------------------------------------------------
# Runtime contract
# ---------------------------------------------------------------------------


class TestRuntimeContract:
    def test_loader_result_advisory_contract(self) -> None:
        from scripts.ingestion.base_loader import LoaderResult
        r = LoaderResult(source_name="x")
        assert r.advisory_status == "ADVISORY_ONLY"
        assert r.human_review_required is True
        assert r.execution_gate == "LOCKED"

    def test_skipped_result_carries_advisory_contract(self) -> None:
        from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

        class _L(BaseSourceLoader):
            source_name = "skip_test"
            def fetch(self) -> LoaderResult:
                raise SkipLoader("test skip")

        result = _L().safe_fetch()
        assert isinstance(result, LoaderResult)
        assert result.advisory_status == "ADVISORY_ONLY"
        assert result.human_review_required is True
        assert result.execution_gate == "LOCKED"

    def test_base_loader_has_no_order_methods(self) -> None:
        from scripts.ingestion.base_loader import BaseSourceLoader
        methods = {m for m in dir(BaseSourceLoader) if not m.startswith("__")}
        assert not (methods & FORBIDDEN_METHODS)

    def test_loader_result_has_no_order_fields(self) -> None:
        from scripts.ingestion.base_loader import LoaderResult
        fields = {f.name for f in dataclasses.fields(LoaderResult)}
        order_fields = {"order_id", "fill_price", "quantity", "side", "execution_policy"}
        assert not (fields & order_fields)


# ---------------------------------------------------------------------------
# Phase 1 compatibility
# ---------------------------------------------------------------------------


class TestPhase1Compatibility:
    def test_signal_event_has_no_order_fields(self) -> None:
        from scripts.global_signal_fabric import SignalEvent
        field_names = {f.name for f in dataclasses.fields(SignalEvent)}
        forbidden = {"order_id", "fill_price", "quantity", "side"}
        assert not (field_names & forbidden)

    def test_global_signal_fabric_still_importable(self) -> None:
        from scripts.global_signal_fabric import (
            SignalEvent,
            SnapshotRow,
            build_global_signal_fabric_report,
        )
        assert SignalEvent is not None
        assert SnapshotRow is not None
        assert build_global_signal_fabric_report is not None

    def test_phase2_import_does_not_break_phase1_report(self) -> None:
        import scripts.ingestion  # noqa: F401 — confirm no side effects
        from scripts.global_signal_fabric import build_global_signal_fabric_report
        seed = REPO_ROOT / "tests" / "fixtures" / "system_snapshots_seed.jsonl"
        report = build_global_signal_fabric_report(
            snapshot_path=seed, write_runtime=False
        )
        assert report["advisory_status"] == "ADVISORY_ONLY"
        assert report["execution_gate"] == "LOCKED"
        assert report["human_review_required"] is True

    def test_phase1_report_execution_gate_locked(self) -> None:
        from scripts.global_signal_fabric import build_global_signal_fabric_report
        seed = REPO_ROOT / "tests" / "fixtures" / "system_snapshots_seed.jsonl"
        report = build_global_signal_fabric_report(
            snapshot_path=seed, write_runtime=False
        )
        assert report["execution_gate"] == "LOCKED"
