"""Tests for ``scripts.compliance_readiness``."""
from __future__ import annotations

import json

import pytest

from scripts import compliance_readiness as cr
from scripts import compliance_registers as registers
from scripts import typed_config


def test_summary_writes(tmp_path):
    target = tmp_path / "comp.json"
    out = cr.write_summary(target)
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["compliance_readiness_score"] >= 9.5
    assert out["summary_path"] == str(target)


def test_every_enabled_provider_appears_in_register():
    summary = cr.build_summary()
    assert summary["missing_enabled_providers"] == []


def test_every_required_data_category_in_privacy_inventory():
    summary = cr.build_summary()
    documented = {c["category_name"] for c in registers.PRIVACY_INVENTORY}
    for required in cr.REQUIRED_DATA_CATEGORIES:
        assert required in documented


def test_no_real_secrets_detected():
    hygiene = cr.secret_hygiene_score()
    # In the repo we ship .env.example with placeholders only.
    assert hygiene["score"] == 1.0
    assert hygiene["suspicious_lines"] == []


def test_compliance_score_includes_lawyer_checklist():
    summary = cr.build_summary()
    assert summary["prelaunch_lawyer_review_checklist_exists"] is True
    # File was created by build_summary if missing.
    assert cr.LAWYER_REVIEW_CHECKLIST_PATH.exists()


def test_matrix_rows_have_required_fields():
    summary = cr.build_summary()
    for row in summary["compliance_matrix"]:
        for k in ("item", "category", "personal_data", "license_status",
                  "retention_policy", "risk_level", "needs_legal_review"):
            assert k in row


def test_safety_invariants():
    summary = cr.build_summary()
    assert summary["advisory_only"] is True
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0


def test_missing_provider_register_entry_lowers_score(monkeypatch):
    """If the register loses an enabled provider, coverage drops."""
    orig = registers.build_source_license_register

    def trimmed():
        out = orig()
        # Remove SEC EDGAR — an enabled provider per CONFIG_ENABLED_PROVIDER_KEYS.
        out["entries"] = [
            e for e in out["entries"]
            if str(e.get("provider")) != "SEC EDGAR"
        ]
        return out

    monkeypatch.setattr(registers, "build_source_license_register", trimmed)
    summary = cr.build_summary()
    assert "SEC EDGAR" in summary["missing_enabled_providers"]
    assert summary["provider_license_coverage"] < 1.0
    assert summary["compliance_readiness_score"] < 10.0
