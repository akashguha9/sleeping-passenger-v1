"""Tests for the machine-readable compliance registers (Integrated Sprint Part 7)."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import compliance_registers as cr


def test_privacy_inventory_contains_required_categories():
    payload = cr.build_privacy_inventory()
    names = {entry["category_name"] for entry in payload["categories"]}
    assert "Operator manual trades" in names
    assert "Provider payloads" in names
    assert "AI reports" in names
    assert "Operator audit log" in names
    assert "Local secrets (.env)" in names


def test_source_license_register_required_providers():
    payload = cr.build_source_license_register()
    providers = {entry["provider"] for entry in payload["entries"]}
    assert "yfinance" in providers
    assert "SEC EDGAR" in providers
    assert "GDELT" in providers
    assert "xAI (Grok)" in providers
    assert "Local fixtures" in providers


def test_write_registers_produces_both_files(tmp_path):
    p = tmp_path / "p.json"
    r = tmp_path / "r.json"
    written_p, written_r = cr.write_registers(privacy_path=p, register_path=r)
    assert written_p == p and written_r == r
    assert p.exists() and r.exists()
    data_p = json.loads(p.read_text(encoding="utf-8"))
    data_r = json.loads(r.read_text(encoding="utf-8"))
    assert data_p["advisory_only"] is True
    assert data_r["advisory_only"] is True
    assert data_r["entries"]


def test_missing_config_enabled_providers_when_register_complete(monkeypatch, tmp_path):
    # Default register contains the providers the typed config might enable.
    monkeypatch.delenv("NEWSAPI_ENABLED", raising=False)
    register = cr.build_source_license_register()
    missing = cr.missing_config_enabled_providers(register=register)
    assert "yfinance" not in missing
    assert "SEC EDGAR" not in missing


def test_no_real_secrets_in_register_text():
    import re
    text_p = json.dumps(cr.build_privacy_inventory())
    text_r = json.dumps(cr.build_source_license_register())
    for blob in (text_p, text_r):
        assert not re.search(r"xai-[A-Za-z0-9]{16,}", blob)
        assert not re.search(r"sk-[A-Za-z0-9]{16,}", blob)
        assert "BEGIN PRIVATE KEY" not in blob


def test_docs_files_exist():
    root = Path(__file__).resolve().parents[1]
    assert (root / "docs" / "COMPLIANCE_SURFACE_AUDIT.md").exists()
    assert (root / "docs" / "PRIVACY_INVENTORY.md").exists()
    assert (root / "docs" / "SOURCE_LICENSE_REGISTER.md").exists()


def test_privacy_inventory_records_no_third_party_pii():
    payload = cr.build_privacy_inventory()
    # No third-party PII anywhere in the inventory.
    for entry in payload["categories"]:
        assert entry["contains_personal_data"] is False
