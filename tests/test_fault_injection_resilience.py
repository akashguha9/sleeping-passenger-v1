"""Fault-injection / resilience (Kanté Sprint 2 — Task 9).

Proves P(unsafe output | fault) = 0: every injected fault degrades to a safe
state, no execution token is ever emitted, and no traceback escapes.
"""
from __future__ import annotations

import json

import pytest

from scripts import fault_injection_probe as fip


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fault")
    return fip.run_probe(tmp)


def test_all_faults_handled_safely(report):
    bad = [r for r in report["results"] if not r["handled_safely"]]
    assert bad == [], bad
    assert report["resilience"] == 1.0


def test_no_unsafe_output_under_any_fault(report):
    assert report["any_unsafe_output"] is False
    for r in report["results"]:
        assert r["unsafe_markers"] == [], r


def test_every_fault_in_set_is_probed(report):
    probed = {r["fault"] for r in report["results"]}
    assert probed == set(fip.FAULTS)


def test_missing_db_fails_closed(report):
    r = next(x for x in report["results"] if x["fault"] == "missing_db")
    assert r["observed_state"] == "FAIL_CLOSED"


def test_polluted_moltbook_fails_closed(report):
    r = next(x for x in report["results"] if x["fault"] == "polluted_moltbook")
    assert r["observed_state"] in ("FAIL", "FAIL_CLOSED")


def test_invalid_role_denied(report):
    r = next(x for x in report["results"] if x["fault"] == "invalid_operator_role")
    assert r["observed_state"] == "DENY"
    assert r["handled_safely"] is True


def test_missing_canonical_tables_degrade(report):
    for fault in ("missing_duplicate_fingerprints", "missing_signal_cell_index"):
        r = next(x for x in report["results"] if x["fault"] == fault)
        assert r["observed_state"] == "INSUFFICIENT_DATA"


def test_no_secret_leak_in_report(report, monkeypatch):
    blob = json.dumps(report)
    assert "sk-" not in blob


def test_cli_exit_zero_when_all_safe():
    assert fip.main(["--json"]) == 0
