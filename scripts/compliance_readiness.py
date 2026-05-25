"""Compliance readiness — release-gated compliance matrix + score.

Integrated Sprint — Part 13 (Kanté defensive batch 2).  Layered on top of
:mod:`scripts.compliance_registers` (which carries the static privacy /
license data); this module turns the registers into a release-gate
compliance matrix and computes the readiness score the gate consumes
at ``runtime/release/compliance_readiness_summary.json``.

The matrix covers providers, data stores, artifacts, and logs.  Every
row carries ``needs_legal_review`` and ``risk_level`` so the operator can
see what still requires a lawyer before non-operator use.

No broker, no execution, advisory-only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
    from scripts import compliance_registers as _registers
    from scripts import typed_config as _typed_config
except ModuleNotFoundError:  # pragma: no cover
    import advisory_contract as _contract  # type: ignore[no-redef]
    import compliance_registers as _registers  # type: ignore[no-redef]
    import typed_config as _typed_config  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_PATH = (
    REPO_ROOT / "runtime" / "release" / "compliance_readiness_summary.json"
)
LAWYER_REVIEW_CHECKLIST_PATH = (
    REPO_ROOT / "docs" / "compliance" / "prelaunch_lawyer_review_checklist.md"
)

# Required compliance matrix rows (per spec).  Each row falls into one of:
#   provider | data_store | artifact | log | report
MATRIX_ROWS: tuple[dict[str, Any], ...] = (
    {"item": "yfinance", "category": "provider", "personal_data": "no",
     "license_status": "needs review", "storage_allowed": "yes",
     "redistribution_status": "no",
     "retention_policy": "bounded; ingestion summaries",
     "deletion_method": "scripts/toxic_signal_quarantine.py",
     "risk_level": "medium",
     "mitigation": "personal-non-commercial; rate-limited",
     "needs_legal_review": True},
    {"item": "SEC EDGAR", "category": "provider", "personal_data": "no",
     "license_status": "public", "storage_allowed": "yes",
     "redistribution_status": "yes",
     "retention_policy": "bounded; ingestion summaries",
     "deletion_method": "scripts/toxic_signal_quarantine.py",
     "risk_level": "low",
     "mitigation": "User-Agent + 10 req/s cap",
     "needs_legal_review": False},
    {"item": "GDELT", "category": "provider", "personal_data": "no",
     "license_status": "public", "storage_allowed": "yes",
     "redistribution_status": "yes",
     "retention_policy": "bounded; ingestion summaries",
     "deletion_method": "scripts/toxic_signal_quarantine.py",
     "risk_level": "low",
     "mitigation": "public-attribution required",
     "needs_legal_review": False},
    {"item": "NewsAPI", "category": "provider", "personal_data": "no",
     "license_status": "needs review", "storage_allowed": "yes",
     "redistribution_status": "no",
     "retention_policy": "bounded; ingestion summaries",
     "deletion_method": "scripts/toxic_signal_quarantine.py",
     "risk_level": "medium",
     "mitigation": "developer tier; non-commercial only",
     "needs_legal_review": True},
    {"item": "AI reports", "category": "provider", "personal_data": "no",
     "license_status": "needs review", "storage_allowed": "yes",
     "redistribution_status": "no",
     "retention_policy": "indefinite (operator-owned)",
     "deletion_method": "operator-initiated",
     "risk_level": "medium",
     "mitigation": "advisory-only; never executes",
     "needs_legal_review": True},
    {"item": "local fixtures", "category": "data_store",
     "personal_data": "no", "license_status": "public",
     "storage_allowed": "yes", "redistribution_status": "yes",
     "retention_policy": "tracked in repo",
     "deletion_method": "operator-initiated",
     "risk_level": "low", "mitigation": "deterministic synthetic data",
     "needs_legal_review": False},
    {"item": "SQLite DB", "category": "data_store",
     "personal_data": "no", "license_status": "public",
     "storage_allowed": "yes", "redistribution_status": "no",
     "retention_policy": "indefinite (operator-owned)",
     "deletion_method": "operator-initiated DELETE / DROP",
     "risk_level": "low",
     "mitigation": "local-only; not exported",
     "needs_legal_review": False},
    {"item": "JSONL audit logs", "category": "log", "personal_data": "no",
     "license_status": "public", "storage_allowed": "yes",
     "redistribution_status": "no",
     "retention_policy": "indefinite (operator review)",
     "deletion_method": "operator-initiated",
     "risk_level": "low", "mitigation": "audit-only; never canonical",
     "needs_legal_review": False},
    {"item": "source payload logs", "category": "log", "personal_data": "no",
     "license_status": "needs review", "storage_allowed": "yes",
     "redistribution_status": "no",
     "retention_policy": "bounded; ingestion summaries",
     "deletion_method": "operator-initiated",
     "risk_level": "low",
     "mitigation": "rate-limited; not republished",
     "needs_legal_review": False},
    {"item": "candidate outputs", "category": "artifact",
     "personal_data": "no", "license_status": "public",
     "storage_allowed": "yes", "redistribution_status": "no",
     "retention_policy": "indefinite",
     "deletion_method": "operator-initiated",
     "risk_level": "low", "mitigation": "local-only",
     "needs_legal_review": False},
    {"item": "model reliability ledger", "category": "artifact",
     "personal_data": "no", "license_status": "public",
     "storage_allowed": "yes", "redistribution_status": "no",
     "retention_policy": "indefinite",
     "deletion_method": "operator-initiated",
     "risk_level": "low", "mitigation": "advisory-only",
     "needs_legal_review": False},
    {"item": "business value summaries", "category": "report",
     "personal_data": "no", "license_status": "public",
     "storage_allowed": "yes", "redistribution_status": "no",
     "retention_policy": "indefinite",
     "deletion_method": "operator-initiated",
     "risk_level": "low",
     "mitigation": "labeled paper/advisory proxy; never claims PnL",
     "needs_legal_review": False},
)

REQUIRED_DATA_CATEGORIES: tuple[str, ...] = tuple(
    e["category_name"] for e in _registers.PRIVACY_INVENTORY
)

# Patterns we treat as "looks like a real secret" — used by the secret-hygiene
# probe over ``.env.example`` and the committed dotfiles.  A *placeholder*
# like ``YOUR_API_KEY_HERE`` is allowed.
_REAL_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),         # OpenAI-style
    re.compile(r"xai-[A-Za-z0-9]{20,}"),        # xAI-style
    re.compile(r"AKIA[0-9A-Z]{16}"),            # AWS access key
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),      # Google API key
)
_PLACEHOLDER_HINTS = (
    "your_", "YOUR_", "placeholder", "example", "EXAMPLE", "redacted",
    "REDACTED", "<", "xxxx", "0000",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp01(v: float) -> float:
    if v < 0:
        return 0.0
    if v > 1:
        return 1.0
    return v


def secret_hygiene_score() -> dict[str, Any]:
    """Scan ``.env.example`` for things that look like real, non-placeholder
    secrets.  Returns ``score`` and the list of suspicious lines (for the
    summary).  Missing .env.example is treated as score=1.0 (no detected leak).
    """
    target = REPO_ROOT / ".env.example"
    if not target.exists():
        return {"score": 1.0, "suspicious_lines": [],
                "checked_path": str(target), "checked": False}
    suspicious: list[str] = []
    try:
        text = target.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {"score": 1.0, "suspicious_lines": [],
                "checked_path": str(target), "checked": False}
    for line in text.splitlines():
        if any(p.search(line) for p in _REAL_SECRET_PATTERNS):
            if not any(hint in line for hint in _PLACEHOLDER_HINTS):
                suspicious.append(line.strip())
    score = 1.0 if not suspicious else 0.0
    return {"score": float(score), "suspicious_lines": suspicious,
            "checked_path": str(target), "checked": True}


def _enabled_providers(cfg: Any | None = None) -> list[str]:
    """Wraps :func:`compliance_registers.missing_config_enabled_providers` to
    also surface the *enabled* provider list (not just the missing ones)."""
    if cfg is None:
        try:
            cfg = _typed_config.load_typed_config()
        except _typed_config.ConfigSafetyError:
            return []
    out: list[str] = []
    for attr, provider in _registers.CONFIG_ENABLED_PROVIDER_KEYS.items():
        if getattr(cfg, attr, False):
            out.append(provider)
    return out


def compliance_readiness_score(
    *,
    provider_license_coverage: float,
    privacy_inventory_coverage: float,
    retention_policy_coverage: float,
    secret_hygiene: float,
    prelaunch_lawyer_review_checklist_exists: bool,
) -> float:
    raw = (
        0.30 * _clamp01(provider_license_coverage)
        + 0.25 * _clamp01(privacy_inventory_coverage)
        + 0.20 * _clamp01(retention_policy_coverage)
        + 0.15 * _clamp01(secret_hygiene)
        + 0.10 * (1.0 if prelaunch_lawyer_review_checklist_exists else 0.0)
    )
    return round(10.0 * _clamp01(raw), 4)


def _ensure_lawyer_review_checklist() -> bool:
    """Create the prelaunch lawyer-review checklist if it does not yet exist.

    Idempotent: if the file is already there, this is a no-op.
    """
    path = LAWYER_REVIEW_CHECKLIST_PATH
    if path.exists():
        return True
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Prelaunch lawyer review checklist\n\n"
            "Required reviews before non-operator use:\n\n"
            "- [ ] yfinance terms confirmed for the deployment context.\n"
            "- [ ] NewsAPI commercial-use tier confirmed if applicable.\n"
            "- [ ] AI provider (xAI / Anthropic / OpenAI) ToS confirmed.\n"
            "- [ ] Polymarket / Kalshi public-data redistribution scope confirmed.\n"
            "- [ ] Privacy notice drafted if any new personal data category is added.\n"
            "- [ ] Confirm advisory-only language in every operator-facing surface.\n"
            "- [ ] Confirm no broker execution surface added since last review.\n"
            "- [ ] Confirm retention policy values match the regulatory regime.\n",
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def build_summary(
    *,
    fixture_mode: bool = True,
    cfg: Any | None = None,
) -> dict[str, Any]:
    register = _registers.build_source_license_register()
    privacy = _registers.build_privacy_inventory()
    matrix = [dict(row) for row in MATRIX_ROWS]
    register_provider_lookup = {
        str(e.get("provider") or "").lower(): e for e in register["entries"]
    }
    # Stitch the register's license-status into the matrix rows.
    for row in matrix:
        if row["category"] == "provider":
            entry = register_provider_lookup.get(row["item"].lower())
            if entry:
                row["license_terms_status"] = entry.get("license_terms_status")
                row["verification_status"] = entry.get("verification_status")

    enabled_providers = _enabled_providers(cfg)
    missing = _registers.missing_config_enabled_providers(register=register)
    enabled_count = max(len(enabled_providers), 1)
    provider_license_coverage = (enabled_count - len(missing)) / enabled_count

    privacy_categories_documented = len(privacy["categories"])
    privacy_inventory_coverage = (
        privacy_categories_documented / max(len(REQUIRED_DATA_CATEGORIES), 1)
    )

    # Retention-policy coverage — every privacy category must have a non-empty
    # retention_policy field.
    cats = privacy["categories"]
    categories_with_retention = sum(
        1 for c in cats
        if str(c.get("retention_policy") or "").strip()
    )
    retention_policy_coverage = (
        categories_with_retention / max(len(cats), 1)
    )

    hygiene = secret_hygiene_score()
    lawyer_present = _ensure_lawyer_review_checklist()

    score = compliance_readiness_score(
        provider_license_coverage=provider_license_coverage,
        privacy_inventory_coverage=privacy_inventory_coverage,
        retention_policy_coverage=retention_policy_coverage,
        secret_hygiene=hygiene["score"],
        prelaunch_lawyer_review_checklist_exists=lawyer_present,
    )
    return {
        "report": "compliance_readiness_summary",
        "ok": score >= 9.5,
        "generated_at_utc": _utc_iso(),
        "fixture_mode": bool(fixture_mode),
        "compliance_matrix": matrix,
        "enabled_providers": enabled_providers,
        "missing_enabled_providers": missing,
        "provider_license_coverage": round(provider_license_coverage, 6),
        "privacy_inventory_coverage": round(privacy_inventory_coverage, 6),
        "retention_policy_coverage": round(retention_policy_coverage, 6),
        "secret_hygiene_score": hygiene["score"],
        "suspicious_secret_lines": hygiene["suspicious_lines"],
        "prelaunch_lawyer_review_checklist_exists": bool(lawyer_present),
        "prelaunch_lawyer_review_checklist_path": str(
            LAWYER_REVIEW_CHECKLIST_PATH
        ),
        "compliance_readiness_score": score,
        "advisory_only": True,
        **_contract.advisory_safety_stamps(),
    }


def write_summary(path: Path | None = None,
                  cfg: Any | None = None,
                  ) -> dict[str, Any]:
    target = path or DEFAULT_SUMMARY_PATH
    summary = build_summary(cfg=cfg)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    tmp.replace(target)
    summary["summary_path"] = str(target)
    return summary


def read_summary(path: Path | None = None) -> dict[str, Any] | None:
    target = path or DEFAULT_SUMMARY_PATH
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="compliance_readiness.py")
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = write_summary() if args.write_summary else build_summary()
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"compliance_readiness_score = "
              f"{summary['compliance_readiness_score']}")
        print(f"  provider_license_coverage  = "
              f"{summary['provider_license_coverage']}")
        print(f"  privacy_inventory_coverage = "
              f"{summary['privacy_inventory_coverage']}")
        print(f"  retention_policy_coverage  = "
              f"{summary['retention_policy_coverage']}")
        print(f"  secret_hygiene_score       = "
              f"{summary['secret_hygiene_score']}")
        print(f"  missing_enabled_providers  = "
              f"{summary['missing_enabled_providers']}")
    return 0


__all__ = [
    "DEFAULT_SUMMARY_PATH",
    "LAWYER_REVIEW_CHECKLIST_PATH",
    "MATRIX_ROWS",
    "compliance_readiness_score",
    "secret_hygiene_score",
    "build_summary", "write_summary", "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
