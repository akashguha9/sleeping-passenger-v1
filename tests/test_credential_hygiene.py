"""Credential hygiene tests.

Calibration Corpus + Hosted Canary sprint, Phase 5.

What this verifies
------------------
* The script reports FAIL when a service-account JSON sits at the repo
  root, even if ``secrets/`` is gitignored.
* The script reports PASS when ``secrets/google-service-account.json``
  is present AND ``secrets/`` is gitignored AND no root-level file is
  present.
* The script reports PASS when no service-account file exists at all
  AND ``secrets/`` is gitignored.
* The script NEVER opens / reads the credential file (monkeypatch
  ``open`` to raise to verify).
* The JSON report carries advisory safety stamps.
* The live repo root passes hygiene (no service-account JSON at root,
  ``secrets/`` is gitignored).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.check_credential_hygiene import (
    SAFETY_STAMPS,
    build_report,
    main,
)


# ---------------------------------------------------------------------------
# Fixture root layouts
# ---------------------------------------------------------------------------


def _make_root(
    tmp_path: Path,
    *,
    root_credential: bool = False,
    secrets_credential: bool = False,
    secrets_gitignored: bool = True,
) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    if root_credential:
        # IMPORTANT — only the FILENAME shape matters for the check.  We
        # never read these contents; the file body is a single byte to
        # keep the test hermetic.
        (root / "google-service-account.json").write_bytes(b"x")
    if secrets_credential:
        sec = root / "secrets"
        sec.mkdir()
        (sec / "google-service-account.json").write_bytes(b"x")
    if secrets_gitignored:
        (root / ".gitignore").write_text("secrets/\n", encoding="utf-8")
    else:
        (root / ".gitignore").write_text("# nothing about secrets\n", encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# Status table
# ---------------------------------------------------------------------------


def test_root_service_account_causes_fail(tmp_path: Path):
    root = _make_root(tmp_path, root_credential=True)
    report = build_report(root=root)
    assert report["root_service_account_present"] is True
    assert report["status"] == "FAIL"
    assert report["credential_hygiene_pass"] == 0
    assert report["credential_risk_score"] == 10.0
    assert "google-service-account.json" in report["root_offenders"]


def test_secrets_service_account_passes_when_gitignored(tmp_path: Path):
    root = _make_root(tmp_path, secrets_credential=True, secrets_gitignored=True)
    report = build_report(root=root)
    assert report["root_service_account_present"] is False
    assert report["secrets_service_account_present"] is True
    assert report["secrets_gitignored"] is True
    assert report["status"] == "PASS"
    assert report["credential_hygiene_pass"] == 1
    assert report["credential_risk_score"] == 0.0


def test_no_credential_file_passes_when_secrets_gitignored(tmp_path: Path):
    root = _make_root(tmp_path)
    report = build_report(root=root)
    assert report["root_service_account_present"] is False
    assert report["secrets_service_account_present"] is False
    assert report["secrets_gitignored"] is True
    assert report["status"] == "PASS"


def test_secrets_not_gitignored_fails(tmp_path: Path):
    root = _make_root(tmp_path, secrets_credential=True, secrets_gitignored=False)
    report = build_report(root=root)
    assert report["secrets_gitignored"] is False
    assert report["status"] == "FAIL"


def test_other_credential_filename_shapes_are_also_refused(tmp_path: Path):
    root = _make_root(tmp_path)
    (root / "my-credentials.json").write_bytes(b"x")
    report = build_report(root=root)
    assert report["status"] == "FAIL"
    assert any("credentials" in n for n in report["root_offenders"])


# ---------------------------------------------------------------------------
# Privacy — script never opens credential contents
# ---------------------------------------------------------------------------


def test_script_never_opens_credential_file_contents(tmp_path: Path, monkeypatch):
    """Monkeypatch ``open`` so any attempt to read a credential file
    fails loudly.  ``build_report`` must still complete successfully
    because it only inspects path metadata and .gitignore lines.
    """
    root = _make_root(tmp_path, secrets_credential=True, secrets_gitignored=True)
    cred_path = root / "secrets" / "google-service-account.json"
    real_open = open

    def _guarded_open(file, *args, **kwargs):  # type: ignore[no-untyped-def]
        # The .gitignore line-read is legitimate; the credential file is not.
        if str(file) == str(cred_path):
            raise AssertionError(
                f"hygiene script attempted to OPEN credential file: {file}"
            )
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _guarded_open)
    report = build_report(root=root)
    assert report["status"] == "PASS"


# ---------------------------------------------------------------------------
# Report shape
# ---------------------------------------------------------------------------


def test_report_carries_advisory_stamps(tmp_path: Path):
    root = _make_root(tmp_path)
    report = build_report(root=root)
    for key, value in SAFETY_STAMPS.items():
        assert report[key] == value, f"safety stamp {key} missing or wrong"


def test_report_writes_json_with_safety_stamps(tmp_path: Path):
    root = _make_root(tmp_path)
    out = tmp_path / "report.json"
    rc = main(["--root", str(root), "--json", str(out)])
    assert rc == 0
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False
    assert body["ai_execution_count"] == 0
    assert body["status"] == "PASS"


def test_main_exits_nonzero_on_failure(tmp_path: Path):
    root = _make_root(tmp_path, root_credential=True)
    rc = main(["--root", str(root)])
    assert rc == 1


# ---------------------------------------------------------------------------
# Live repo root — sanity gate
# ---------------------------------------------------------------------------


def test_live_repo_root_passes_hygiene():
    """The real repo root must pass — root-level google-service-account
    moved into secrets/ during this sprint and secrets/ is gitignored."""
    report = build_report()
    assert report["root_service_account_present"] is False, (
        f"root-level credential leaked back: {report['root_offenders']}"
    )
    assert report["secrets_gitignored"] is True
    assert report["status"] == "PASS"
