"""Action-doctrine status is UNRATIFIED and unlocks nothing (Phase 5).

These tests lock the doctrine reporter to a safe default and prove it never
becomes a control surface.
"""

import ast
from pathlib import Path

from scripts import action_doctrine_status as ads
from scripts.narrative_operator_wisdom_filter import (
    evaluate_narrative_operator_wisdom_filter,
)

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_doctrine_unratified_by_default() -> None:
    status = ads.doctrine_status()
    assert status["overall"] == "UNRATIFIED"
    assert status["ratified"] is False
    assert status["authorizes_action"] is False
    assert all(v == "UNRATIFIED" for v in status["gates"].values())
    assert set(status["gates"]) == {
        "authority", "unit_of_learning", "operator_contract",
        "observation_evidence", "safety_rollback",
    }


def test_is_ratified_is_always_false() -> None:
    assert ads.is_ratified() is False


def test_doctrine_status_does_not_change_action_authority() -> None:
    # Reading doctrine status must not affect the verdict — authority stays REVOKED.
    ads.doctrine_status()
    ads.is_ratified()
    result = evaluate_narrative_operator_wisdom_filter(None)
    assert result["action_authority"] == "REVOKED"
    assert result["allowed_to_execute"] is False


def test_doctrine_module_has_no_execution_or_broker_imports() -> None:
    tree = ast.parse((SCRIPTS / "action_doctrine_status.py").read_text(encoding="utf-8-sig"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    joined = " ".join(imported).lower()
    for bad in ("action_engine", "broker", "execution_governance", "paper_execution"):
        assert bad not in joined
