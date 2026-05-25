"""Compliance preflight — legal/privacy floor, read-only and offline.

Kanté "no leak": proves the repo's visible behaviour matches its advisory-only
posture and that the gate fails loudly when it does not.
"""
from __future__ import annotations

from scripts import compliance_preflight as comp


def test_passes_current_advisory_only_posture():
    report = comp.run_compliance_preflight()
    assert report["overall"] in {"PASS", "WARN"}, report["counts"]
    # The blocking checks must all pass on the real repo.
    failing = [c["name"] for c in report["checks"] if c["status"] == "FAIL"]
    assert failing == [], failing


def test_fails_if_execution_language_appears(tmp_path):
    # Synthetic repo with an autonomous-execution claim in a surface doc.
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ADVISORY_DISCLOSURE.md").write_text(
        "advisory-only. a human makes the final decision.\n"
        "But also: the system places orders automatically.\n",
        encoding="utf-8",
    )
    report = comp.run_compliance_preflight(tmp_path)
    names = {c["name"]: c["status"] for c in report["checks"]}
    assert names["no_autonomous_trading_claims"] == "FAIL"
    assert report["overall"] == "FAIL"


def test_has_execution_claim_helper():
    assert comp.has_execution_claim("the bot places orders automatically") is True
    assert comp.has_execution_claim("we will trade for you") is True
    assert comp.has_execution_claim("This MVP is advisory-only.") is False
    # Negated noun phrases must not trip it.
    assert comp.has_execution_claim("This is NOT an autonomous trading system.") is False


def test_fails_if_advisory_disclosure_missing(tmp_path):
    # Empty synthetic repo → disclosure + register missing.
    report = comp.run_compliance_preflight(tmp_path)
    names = {c["name"]: c["status"] for c in report["checks"]}
    assert names["advisory_disclosure_present"] == "FAIL"
    assert report["overall"] == "FAIL"


def test_fails_if_source_register_missing(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ADVISORY_DISCLOSURE.md").write_text(
        "advisory-only. a human makes the final decision.\n", encoding="utf-8"
    )
    report = comp.run_compliance_preflight(tmp_path)
    names = {c["name"]: c["status"] for c in report["checks"]}
    assert names["data_source_register_exists"] == "FAIL"


def test_find_secret_like():
    assert comp.find_secret_like("api_key = sk-abcdef0123456789abcd")
    assert comp.find_secret_like("nothing here") == []


def test_never_touches_external_network():
    import pathlib
    text = pathlib.Path(comp.__file__).read_text(encoding="utf-8").lower()
    for forbidden in ("import urllib", "import requests", "import socket",
                      "urlopen", "http://", "https://"):
        assert forbidden not in text, forbidden


def test_report_is_advisory_only():
    report = comp.run_compliance_preflight()
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
