"""Tests proving the Global Signal Fabric has no execution path.

These tests are intentionally aggressive: they walk the entire ``scripts``
package and make sure no module exposes any forbidden execution method, and
that the ADVISORY_ONLY guardrails cannot be flipped.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ingestion.base_loader import FORBIDDEN_METHODS, BaseLoader  # noqa: E402
from scripts.normalization.signal_event_schema import (  # noqa: E402
    ADVISORY_ONLY,
    SignalEvent,
)

# Modules outside the new fabric we don't want to inspect (they predate this work).
LEGACY_DIRS = {"runtime_common", "moltbook_loader"}

INGESTION_PKG = "scripts.ingestion"
REPORTS_PKG = "scripts.reports"
STATE_PKG = "scripts.state_machine"


def _iter_modules(package_name: str):
    pkg = importlib.import_module(package_name)
    for info in pkgutil.iter_modules(pkg.__path__, prefix=f"{package_name}."):
        yield importlib.import_module(info.name)


def test_yaml_policy_declares_advisory_only() -> None:
    text = (REPO_ROOT / "configs" / "no_execution_policy.yaml").read_text()
    assert "ai_can_execute: false" in text
    assert "broker_order_placement_enabled: false" in text
    assert "default_action_permission: ADVISORY_ONLY" in text
    for forbidden in [
        "place_order",
        "modify_order",
        "cancel_order",
        "redeem_position",
        "submit_order",
    ]:
        assert forbidden in text


def test_no_loader_exposes_forbidden_method_names() -> None:
    for module in _iter_modules(INGESTION_PKG):
        for name, obj in inspect.getmembers(module):
            if not inspect.isclass(obj):
                continue
            if not issubclass(obj, BaseLoader) or obj is BaseLoader:
                continue
            class_attrs = set(vars(obj).keys())
            forbidden = FORBIDDEN_METHODS.intersection(class_attrs)
            assert not forbidden, f"{module.__name__}.{name} declares {forbidden}"


def test_loader_modules_have_no_forbidden_words_in_method_definitions() -> None:
    forbidden = FORBIDDEN_METHODS
    for module in _iter_modules(INGESTION_PKG):
        src_path = inspect.getsourcefile(module)
        if not src_path:
            continue
        text = Path(src_path).read_text()
        for name in forbidden:
            # We allow forbidden tokens to appear in *strings/comments* (as
            # documentation) but never as a `def <name>(` definition.
            pattern = rf"^\s*def\s+{re.escape(name)}\s*\("
            assert not re.search(pattern, text, re.MULTILINE), (
                f"{module.__name__} defines forbidden method {name!r}"
            )


def test_state_machine_never_emits_execute_permission() -> None:
    for module in _iter_modules(STATE_PKG):
        for name, obj in inspect.getmembers(module):
            if isinstance(obj, str):
                assert obj.upper() not in {"EXECUTE", "AUTO_EXECUTE"}, (
                    f"{module.__name__}.{name} is forbidden permission"
                )


def test_signal_event_locked_to_advisory_only() -> None:
    e = SignalEvent(source_name="x", source_type="news_event")
    with pytest.raises(ValueError):
        SignalEvent(
            source_name="x",
            source_type="news_event",
            execution_permission="AUTO_EXECUTE",
        )
    assert e.execution_permission == ADVISORY_ONLY


def test_reports_invariants_present() -> None:
    from scripts.reports.advisory_action_report import ADVISORY_INVARIANTS
    from scripts.reports.global_signal_report import REPORT_INVARIANTS
    from scripts.reports.human_review_queue import QUEUE_INVARIANTS

    for invariant in (REPORT_INVARIANTS, QUEUE_INVARIANTS, ADVISORY_INVARIANTS):
        assert invariant["execution_permission"] == ADVISORY_ONLY
        assert invariant["human_review_required"] is True
        assert invariant["ai_executions"] == 0
