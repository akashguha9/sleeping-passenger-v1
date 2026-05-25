"""Tests for the dead-diagnostic / maintainability audit (Task 10).

Uses a synthetic repo tree so orphan/untested/unstamped/broker detection is
deterministic and independent of the real ``scripts/`` inventory.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import dead_diagnostic_audit as dda


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src").mkdir()
    return tmp_path


def _write(repo: Path, rel: str, text: str) -> None:
    (repo / rel).write_text(text, encoding="utf-8")


def test_known_good_module_is_useful(repo):
    # helper.py is imported by user.py, has a test, and is advisory-stamped.
    _write(repo, "scripts/helper.py",
           "from scripts import advisory_contract\n"
           "def build_report():\n    return {'advisory_status': 'ADVISORY_ONLY'}\n")
    _write(repo, "scripts/user.py", "from scripts import helper\n")
    _write(repo, "tests/test_helper.py", "from scripts import helper\n")
    rep = dda.evaluate(repo)
    helper = next(m for m in rep["modules"] if m["module"] == "helper.py")
    assert helper["useful"] is True
    assert helper["has_test"] is True
    assert helper["is_imported"] is True
    assert helper["advisory_stamped"] is True
    assert "helper.py" not in rep["orphan_scripts"]
    assert "helper.py" not in rep["unstamped_report_producers"]


def test_orphan_script_detected(repo):
    # No test, not imported, no main() -> orphan / dead code.
    _write(repo, "scripts/lonely.py", "X = 1\n")
    rep = dda.evaluate(repo)
    assert "lonely.py" in rep["orphan_scripts"]
    assert rep["release_gate_impact"] == dda.WARN


def test_runnable_script_is_not_orphan(repo):
    _write(repo, "scripts/cli.py", "def main(argv=None):\n    return 0\n")
    rep = dda.evaluate(repo)
    assert "cli.py" not in rep["orphan_scripts"]


def test_untested_script_flagged(repo):
    _write(repo, "scripts/used_but_untested.py", "VALUE = 2\n")
    _write(repo, "scripts/consumer.py", "from scripts import used_but_untested\n")
    rep = dda.evaluate(repo)
    # Imported -> useful (not orphan) but still flagged as untested.
    assert "used_but_untested.py" in rep["untested_scripts"]
    assert "used_but_untested.py" not in rep["orphan_scripts"]


def test_unstamped_report_producer_flagged(repo):
    # Produces a report but carries no advisory stamp.
    _write(repo, "scripts/naked_report.py",
           "def build_audit():\n    return {'count': 0}\n")
    _write(repo, "tests/test_naked_report.py", "from scripts import naked_report\n")
    rep = dda.evaluate(repo)
    assert "naked_report.py" in rep["unstamped_report_producers"]


def test_broker_call_pattern_is_forbidden(repo):
    _write(repo, "scripts/bad_actor.py",
           "def go(broker):\n    broker.place_order('AAPL', 1)\n")
    rep = dda.evaluate(repo)
    assert "bad_actor.py" in rep["broker_call_offenders"]
    assert "place_order" in rep["broker_call_offenders"]["bad_actor.py"]
    assert rep["release_gate_impact"] == dda.BLOCK


def test_safety_module_listing_tokens_not_flagged(repo):
    # A module that merely *names* the tokens in a list (no call) is clean.
    _write(repo, "scripts/safe_list.py",
           'FORBIDDEN = ("place_order", "submit_order")\n')
    _write(repo, "tests/test_safe_list.py", "from scripts import safe_list\n")
    rep = dda.evaluate(repo)
    assert "safe_list.py" not in rep["broker_call_offenders"]


def test_usefulness_score_and_stamps(repo):
    _write(repo, "scripts/a.py", "def main():\n    return 0\n")   # useful
    _write(repo, "scripts/b.py", "Y = 1\n")                        # orphan
    rep = dda.evaluate(repo)
    assert rep["total_scripts"] == 2
    assert rep["useful_scripts"] == 1
    assert rep["diagnostic_usefulness_score"] == 0.5
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["broker_api_called"] is False
    assert rep["ai_execution_count"] == 0
