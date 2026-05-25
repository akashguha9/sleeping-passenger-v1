"""Architecture fitness / dependency boundaries (Kanté Sprint 2 — Task 8)."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import architecture_fitness as fit

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def report():
    return fit.evaluate(_REPO_ROOT)


def _check(report, name):
    return next(x for x in report["checks"] if x["name"] == name)


def test_current_architecture_passes(report):
    assert report["overall"] == "PASS", [c for c in report["checks"]
                                         if c["status"] == "FAIL"]
    assert report["arch_score"] > 0.99


def test_contract_layer_is_pure(report):
    assert _check(report, "contract_layer_purity")["status"] == "PASS"


def test_pure_diagnostics_do_not_import_sqlite3(report):
    assert _check(report, "diagnostic_layer_purity")["status"] == "PASS"


def test_no_broker_imports(report):
    assert _check(report, "no_broker_execution_imports")["status"] == "PASS"


def test_no_frontend_imports_in_scripts(report):
    assert _check(report, "no_frontend_imports_in_scripts")["status"] == "PASS"


def test_tests_runtime_db_isolated(report):
    assert _check(report, "tests_runtime_db_isolated")["status"] == "PASS"


# --- synthetic violation detection (the check actually catches regressions) ---


def test_detects_synthetic_forbidden_import():
    bad = "from scripts import persistence\nimport sqlite3\n"
    viol = fit.module_import_violations(bad, fit._CONTRACT_FORBIDDEN)
    assert "sqlite3" in viol
    assert any("persistence" in v for v in viol)


def test_detects_synthetic_broker_import():
    bad = "import alpaca_trade_api\n"
    viol = fit.module_import_violations(bad, fit._BROKER_IMPORT_TOKENS)
    assert viol  # alpaca matched


def test_clean_module_has_no_violations():
    good = "from __future__ import annotations\nimport json\nfrom typing import Any\n"
    assert fit.module_import_violations(good, fit._CONTRACT_FORBIDDEN) == []


def test_import_targets_parsing():
    text = "import os\nfrom scripts import advisory_contract\nimport json, re\n"
    targets = fit.import_targets(text)
    assert "os" in targets
    assert "scripts" in targets
