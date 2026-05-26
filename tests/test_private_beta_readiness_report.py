"""Tests for :mod:`scripts.private_beta_readiness_report`.

Full Role-Uplift Sprint, Phase 8.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import private_beta_readiness_report as pbr  # noqa: E402


def _scaffold_repo(tmp_path: Path) -> Path:
    """Build a minimal repo skeleton with the design docs in place."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "runtime" / "release").mkdir(parents=True)
    docs = tmp_path / "docs" / "private_beta"
    docs.mkdir(parents=True)
    (docs / "AUTH_AND_USER_ISOLATION_PLAN.md").write_text(
        "design", encoding="utf-8"
    )
    (docs / "STAGING_SMOKE_CHECK.md").write_text(
        "smoke", encoding="utf-8"
    )
    return tmp_path


def test_report_carries_advisory_stamps():
    report = pbr.build_report()
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0


def test_weights_sum_to_one():
    total = sum(pbr.PRIVATE_BETA_WEIGHTS.values())
    assert total == pytest.approx(1.0, abs=1e-9)


def test_score_capped_when_auth_and_hosted_db_absent():
    """Without real auth or hosted DB, the score must stay ≤ 6.2."""
    report = pbr.build_report()
    assert report["capped_to_design_only"] is True
    assert report["private_beta_score"] <= pbr.PRIVATE_BETA_CEILING_DESIGN_ONLY


def test_report_warns_public_saas_not_targeted():
    report = pbr.build_report()
    assert "NOT_TARGETED_THIS_YEAR" in report["warning"]


def test_report_serialisable_to_json():
    report = pbr.build_report()
    blob = json.dumps(report)
    parsed = json.loads(blob)
    assert parsed["script"] == "private_beta_readiness_report.py"


def test_no_forbidden_execution_language():
    report = pbr.build_report()
    blob = json.dumps(report).lower()
    for forbidden in (
        "place_order",
        "submit_order",
        "execute_trade",
        "broker_execute",
        "auto_execute",
        "permission to trade",
    ):
        assert forbidden not in blob


def test_cli_json_write(tmp_path):
    out = tmp_path / "report.json"
    rc = pbr.main(["--json", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["advisory_status"] == "ADVISORY_ONLY"


def test_design_doc_yields_half_credit_for_user_isolation(tmp_path):
    """The user-isolation axis returns 0.5 when design doc exists but
    no contract test does."""
    repo = _scaffold_repo(tmp_path)
    score, reason = pbr._score_user_isolation(repo)
    assert score == 0.5
    assert "Design" in reason or "design" in reason


def test_no_design_doc_yields_zero_user_isolation(tmp_path):
    (tmp_path / "docs" / "private_beta").mkdir(parents=True)
    score, _ = pbr._score_user_isolation(tmp_path)
    assert score == 0.0


def test_legal_doc_pair_yields_full_legal_credit(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "LEGAL_PRIVACY_NOTES.md").write_text(".", encoding="utf-8")
    (tmp_path / "docs" / "LEGAL_PRIVACY_COMPLIANCE_MODEL.md").write_text(".", encoding="utf-8")
    # We have to monkeypatch the module-level path constants because they
    # are computed at import time.
    import importlib
    from scripts import private_beta_readiness_report as pbr_mod
    saved_notes = pbr_mod.LEGAL_NOTES
    saved_comp = pbr_mod.LEGAL_COMPLIANCE
    pbr_mod.LEGAL_NOTES = tmp_path / "docs" / "LEGAL_PRIVACY_NOTES.md"
    pbr_mod.LEGAL_COMPLIANCE = tmp_path / "docs" / "LEGAL_PRIVACY_COMPLIANCE_MODEL.md"
    try:
        score, _ = pbr_mod._score_legal(tmp_path)
        assert score == 1.0
    finally:
        pbr_mod.LEGAL_NOTES = saved_notes
        pbr_mod.LEGAL_COMPLIANCE = saved_comp


def test_public_saas_cap_invariant():
    """Even at theoretical maximum input scores, the report must NOT
    promote Public SaaS — Public SaaS readiness is a separate scorecard
    entry, not a side-effect of private-beta math.
    """
    report = pbr.build_report()
    blob = json.dumps(report).lower()
    assert "public_saas_score" not in blob
    assert "public saas readiness" not in blob  # not bumped here
