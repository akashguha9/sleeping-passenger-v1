"""Tests for :mod:`scripts.bootstrap_local_operator`.

Full Role-Uplift Sprint, Phase 3.

These tests pin:

* Dry-run never writes (no canonical mutation, no external API).
* A repo without ``scripts/`` or ``frontend/`` fails the repo-root check.
* A repo missing the frontend package warns rather than fails.
* The aggregate score formula matches the spec.
* Advisory safety stamps are present.
* No execution / broker / order language leaks into the report.
* The script does not read any ``.env``, ``secrets/`` content.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import bootstrap_local_operator as bootstrap  # noqa: E402


def _drain(report: dict) -> str:
    return json.dumps(report).lower()


def test_build_report_carries_advisory_stamps(tmp_path):
    report = bootstrap.build_report(repo_root=tmp_path, skip_frontend=True)
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
    assert report["dry_run"] is True


def test_build_report_does_not_write_anything(tmp_path):
    # An empty tmp_path will look like a non-repo root; the report is
    # generated entirely in memory and must not create files there.
    bootstrap.build_report(repo_root=tmp_path, skip_frontend=True)
    assert list(tmp_path.iterdir()) == []


def test_missing_repo_root_fails(tmp_path):
    """The repo-root check must fail when ``scripts/`` or ``frontend/``
    is absent — those are the hard signals that we are *in* the repo.
    """
    report = bootstrap.build_report(repo_root=tmp_path, skip_frontend=True)
    root_check = next(c for c in report["checks"] if c["name"] == "repo_root")
    assert root_check["status"] == "FAIL"


def test_missing_frontend_warns_not_fails(tmp_path):
    """A repo without frontend/package.json should warn, never fail —
    the frontend is optional for backend-only operators.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "frontend").mkdir()
    report = bootstrap.build_report(repo_root=tmp_path, skip_frontend=False)
    fp = next(c for c in report["checks"] if c["name"] == "frontend_package")
    assert fp["status"] == "WARN"


def test_skip_frontend_skips_both_frontend_checks(tmp_path):
    report = bootstrap.build_report(repo_root=tmp_path, skip_frontend=True)
    fp = next(c for c in report["checks"] if c["name"] == "frontend_package")
    ts = next(c for c in report["checks"] if c["name"] == "tsc_available")
    assert fp["status"] == "SKIP"
    assert ts["status"] == "SKIP"


def test_score_formula_exact():
    """Direct formula test against the spec.

    BootstrapScore = min(10, 10×rate − 2×fail − 0.5×warn − 0.25×skip)
    """
    checks = [
        bootstrap.CheckResult(name="a", status="PASS"),
        bootstrap.CheckResult(name="b", status="PASS"),
        bootstrap.CheckResult(name="c", status="WARN"),
        bootstrap.CheckResult(name="d", status="FAIL"),
        bootstrap.CheckResult(name="e", status="SKIP"),
    ]
    agg = bootstrap._aggregate_score(checks)
    # rate = 2/5 = 0.4 → 10×0.4 = 4, then −2×1 − 0.5×1 − 0.25×1 = −2.75
    # score = max(0, min(10, 1.25)) = 1.25
    assert agg["checks_total"] == 5
    assert agg["checks_passed"] == 2
    assert agg["checks_warned"] == 1
    assert agg["checks_failed"] == 1
    assert agg["checks_skipped"] == 1
    assert agg["bootstrap_success_rate"] == pytest.approx(0.4)
    assert agg["bootstrap_score"] == pytest.approx(1.25)


def test_score_floored_at_zero():
    checks = [
        bootstrap.CheckResult(name=f"f{i}", status="FAIL") for i in range(5)
    ]
    agg = bootstrap._aggregate_score(checks)
    # rate = 0/5; raw = 0 − 10 = −10 → clamped to 0
    assert agg["bootstrap_score"] == 0.0


def test_score_capped_at_ten():
    checks = [
        bootstrap.CheckResult(name=f"p{i}", status="PASS") for i in range(20)
    ]
    agg = bootstrap._aggregate_score(checks)
    assert agg["bootstrap_score"] == 10.0


def test_next_commands_and_urls_present(tmp_path):
    report = bootstrap.build_report(repo_root=tmp_path, skip_frontend=True)
    cmds = report["next_commands"]
    assert "python scripts/api_server.py" in cmds
    assert any("npm run dev" in c for c in cmds)
    urls = report["local_urls"]
    assert any("127.0.0.1" in u for u in urls)


def test_report_does_not_leak_secret_or_execution_language(tmp_path):
    """The report must never embed an execution/broker word; the script
    is preflight-only.
    """
    report = bootstrap.build_report(repo_root=tmp_path, skip_frontend=True)
    blob = _drain(report)
    for forbidden in (
        "place_order",
        "submit_order",
        "execute_trade",
        "broker_execute",
        "auto_execute",
        "buy now",
        "sell now",
    ):
        assert forbidden not in blob, f"forbidden token leaked: {forbidden}"


def test_cli_json_write(tmp_path):
    out = tmp_path / "bootstrap.json"
    rc = bootstrap.main(["--dry-run", "--skip-frontend", "--json", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["advisory_status"] == "ADVISORY_ONLY"
    assert data["execution_gate"] == "LOCKED"


def test_report_does_not_open_any_env_file(monkeypatch, tmp_path):
    """A surrogate ``.env`` is not read.  We monkeypatch ``open`` to
    raise if the script tries to read .env content — credentials must
    never be parsed.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / ".env").write_text("FORBIDDEN_SECRET=abc\n", encoding="utf-8")
    original_open = open

    def guarded_open(file, *args, **kwargs):
        path_str = str(file)
        if path_str.endswith(".env") or "secrets" + str(Path("/")) + "" in path_str:
            raise AssertionError(f"bootstrap must never open {path_str}")
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded_open)
    bootstrap.build_report(repo_root=tmp_path, skip_frontend=True)
