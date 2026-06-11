"""Proofs for the dependency advisory register and its expiry audit."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from scripts import audit_dependency_advisory_register as reg

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REGISTER = _REPO_ROOT / "docs" / "DEPENDENCY_ADVISORY_REGISTER.md"


def test_register_exists_and_names_risk_owner():
    text = _REGISTER.read_text(encoding="utf-8")
    assert "Akash Guha" in text
    assert "review_by" in text or "Review by" in text


def test_real_register_passes_audit_today():
    assert reg.audit() == []


def test_open_entries_parse():
    entries = reg.parse_open_entries(_REGISTER.read_text(encoding="utf-8"))
    assert entries, "register has no open entries table rows"
    ids = [e["id"] for e in entries]
    assert "ADV-2026-001" in ids  # the next/postcss moderate advisory


def _register_with(review_by: str, severity: str = "Moderate", owner: str = "Akash Guha") -> str:
    return (
        "# Register\n\n## Open entries\n\n"
        "| ID | Package | Severity | Transitive source | Affected path | "
        "Why not fixed | Upstream status | CI behavior | Review by | Owner |\n"
        "| -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |\n"
        f"| ADV-T-1 | demo-pkg | {severity} | x | y | z | none | passes | {review_by} | {owner} |\n"
    )


def test_expired_entry_fails(tmp_path):
    p = tmp_path / "reg.md"
    p.write_text(_register_with("2026-01-01"), encoding="utf-8")
    violations = reg.audit(p, today=dt.date(2026, 6, 10))
    assert any("past its review date" in v for v in violations), violations


def test_future_entry_passes(tmp_path):
    p = tmp_path / "reg.md"
    p.write_text(_register_with("2026-12-31"), encoding="utf-8")
    assert reg.audit(p, today=dt.date(2026, 6, 10)) == []


def test_high_severity_cannot_be_accepted(tmp_path):
    p = tmp_path / "reg.md"
    p.write_text(_register_with("2026-12-31", severity="High"), encoding="utf-8")
    violations = reg.audit(p, today=dt.date(2026, 6, 10))
    assert any("may not be accepted" in v for v in violations), violations


def test_missing_owner_fails(tmp_path):
    p = tmp_path / "reg.md"
    p.write_text(_register_with("2026-12-31", owner="nobody"), encoding="utf-8")
    violations = reg.audit(p, today=dt.date(2026, 6, 10))
    assert any("accepted-risk owner" in v for v in violations), violations


def test_unparsable_date_fails(tmp_path):
    p = tmp_path / "reg.md"
    p.write_text(_register_with("soon"), encoding="utf-8")
    violations = reg.audit(p, today=dt.date(2026, 6, 10))
    assert any("unparsable review_by" in v for v in violations), violations


def test_missing_register_fails(tmp_path):
    violations = reg.audit(tmp_path / "missing.md")
    assert any("register missing" in v for v in violations)
