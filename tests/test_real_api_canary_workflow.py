"""Validate the nightly real-API canary GitHub Actions workflow.

Calibration Corpus + Hosted Canary sprint, Phase 2.

The workflow must:

* exist under ``.github/workflows/real-api-canary.yml``
* trigger on ``schedule`` AND ``workflow_dispatch``
* set ``RUN_REAL_API_CANARY=1`` so the otherwise-skipped tests run
* invoke ``python -m pytest tests/test_real_api_canary.py``
* upload a canary report artifact via ``actions/upload-artifact``
* NOT hardcode any secret value
* NOT add any execution / broker / order language

Local pytest must continue to skip the canary by default (we verify
that contract by importing the test module and checking the autouse
fixture's behaviour in the absence of ``RUN_REAL_API_CANARY``).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "real-api-canary.yml"


# ---------------------------------------------------------------------------
# Workflow file structure
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert _WORKFLOW_PATH.exists(), (
        f"missing nightly canary workflow at {_WORKFLOW_PATH}"
    )
    return _WORKFLOW_PATH.read_text(encoding="utf-8")


def test_workflow_file_exists():
    assert _WORKFLOW_PATH.exists()


def test_workflow_has_schedule_trigger(workflow_text: str):
    # ``schedule:`` on its own indented line, followed by at least one
    # ``- cron:`` entry.
    assert re.search(r"^\s*schedule\s*:", workflow_text, re.MULTILINE), (
        "workflow missing `schedule:` trigger"
    )
    assert re.search(r"-\s*cron\s*:\s*['\"][^'\"]+['\"]", workflow_text), (
        "schedule trigger missing cron expression"
    )


def test_workflow_has_workflow_dispatch_trigger(workflow_text: str):
    assert re.search(r"^\s*workflow_dispatch\s*:", workflow_text, re.MULTILINE), (
        "workflow missing `workflow_dispatch:` manual trigger"
    )


def test_workflow_sets_run_real_api_canary_env(workflow_text: str):
    # Must export RUN_REAL_API_CANARY=1 at the job-env level (string "1"
    # to match GitHub Actions env semantics).
    assert re.search(
        r"RUN_REAL_API_CANARY\s*:\s*['\"]?1['\"]?", workflow_text
    ), "workflow must set RUN_REAL_API_CANARY=1 so the opt-in tests run"


def test_workflow_invokes_canary_pytest_module(workflow_text: str):
    assert "tests/test_real_api_canary.py" in workflow_text, (
        "workflow must invoke pytest tests/test_real_api_canary.py"
    )
    assert re.search(r"python\s+-m\s+pytest", workflow_text), (
        "workflow must invoke pytest via ``python -m pytest``"
    )


def test_workflow_uploads_canary_artifact(workflow_text: str):
    assert "actions/upload-artifact" in workflow_text, (
        "workflow must upload the canary artifact via actions/upload-artifact"
    )
    assert (
        "real_api_canary_report.json" in workflow_text
        or "real_api_canary_junit.xml" in workflow_text
    ), "workflow must upload a canary report file"


def test_workflow_does_not_hardcode_secrets(workflow_text: str):
    # GitHub Actions ``${{ secrets.X }}`` is the only allowed shape.
    # Any token-looking literal of 20+ alnum chars near the keys we
    # care about should never appear.
    for forbidden in (
        # Common API-key shapes — none should ever appear verbatim.
        re.compile(r"['\"]sk-[A-Za-z0-9]{20,}['\"]"),
        re.compile(r"['\"][A-Za-z0-9]{32,}['\"]\s*#\s*api[_\- ]?key", re.IGNORECASE),
    ):
        assert not forbidden.search(workflow_text), (
            "workflow must not embed literal secrets"
        )
    # Defensive: NEWS_API_KEY in the workflow MUST come from `secrets.*`
    # if present at all.  Plain `NEWS_API_KEY: somevalue` is forbidden.
    for match in re.finditer(r"NEWS_API_KEY\s*:\s*(.+)", workflow_text):
        value = match.group(1).strip()
        assert value.startswith("${{"), (
            f"NEWS_API_KEY must come from secrets context, found: {value!r}"
        )


def test_workflow_uses_no_execution_or_broker_language(workflow_text: str):
    lowered = workflow_text.lower()
    for forbidden in (
        " /orders",
        "/buy",
        "/sell",
        "/execute",
        "place_order",
        "broker_api",
        "broker_order",
    ):
        assert forbidden not in lowered, (
            f"forbidden execution/broker token in workflow: {forbidden!r}"
        )


# ---------------------------------------------------------------------------
# Skip contract — local pytest must still skip by default
# ---------------------------------------------------------------------------


def test_canary_remains_skipped_locally_without_env(monkeypatch):
    """Importing the canary test module must not register any test that
    actually fires a network request when the env var is unset."""
    monkeypatch.delenv("RUN_REAL_API_CANARY", raising=False)
    from scripts import curate_calibration_corpus  # ensure unrelated import works
    assert curate_calibration_corpus is not None  # marker
    # Verify the canary module's gate function returns False when unset.
    from tests import test_real_api_canary as canary_mod
    assert not canary_mod._canary_enabled()


def test_canary_gate_recognises_truthy_values(monkeypatch):
    from tests import test_real_api_canary as canary_mod
    for value in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("RUN_REAL_API_CANARY", value)
        assert canary_mod._canary_enabled(), f"truthy value {value!r} should enable canary"
    monkeypatch.setenv("RUN_REAL_API_CANARY", "")
    assert not canary_mod._canary_enabled()
