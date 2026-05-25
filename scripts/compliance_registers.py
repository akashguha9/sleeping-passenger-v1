"""Machine-readable compliance registers — privacy + source-license JSON.

Integrated Sprint — Part 7.  Writes the two JSON registers the release gate
consumes:

  * ``runtime/compliance/privacy_inventory.json``
  * ``runtime/compliance/source_license_register.json``

The data is embedded here so the artifact can always be re-generated
deterministically.  Anything that needs a lawyer is marked
``needs_review`` / ``NEEDS_REVIEW`` so the operator cannot accidentally
claim certainty.

Pure module + thin CLI; read-only w.r.t. the runtime DB; no broker calls;
no execution; no AI execution.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import typed_config as _typed_config
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import typed_config as _typed_config  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPLIANCE_DIR = REPO_ROOT / "runtime" / "compliance"
PRIVACY_INVENTORY_PATH = DEFAULT_COMPLIANCE_DIR / "privacy_inventory.json"
SOURCE_LICENSE_REGISTER_PATH = DEFAULT_COMPLIANCE_DIR / "source_license_register.json"


PRIVACY_INVENTORY: list[dict[str, Any]] = [
    {
        "category_name": "Operator manual trades",
        "source": "Operator manual entries (manual_trades + paper-trade ledger)",
        "contains_personal_data": False,
        "examples": ["manual_trades rows", "paper_trade_ledger entries"],
        "storage_location": "runtime/mvp_local.db, logs/*.jsonl",
        "retention_policy": "indefinite (operator-owned)",
        "deletion_method": "operator-initiated DELETE / quarantine",
        "access_scope": "local single-operator",
        "third_party_processor": "none",
        "risk_level": "low",
        "mitigation": "local-only storage; not exported by default",
    },
    {
        "category_name": "Provider payloads",
        "source": "yfinance, SEC EDGAR, GDELT, NewsAPI, Polymarket, Kalshi, xAI",
        "contains_personal_data": False,
        "examples": ["signal_events rows", "ingestion summaries"],
        "storage_location": "runtime/mvp_local.db; ingestion summaries",
        "retention_policy": "bounded by table size + per-source TTL",
        "deletion_method": "scripts/toxic_signal_quarantine.py",
        "access_scope": "local single-operator",
        "third_party_processor": "each provider in transit; no other processor",
        "risk_level": "low",
        "mitigation": "read-only; not republished; rate-limited",
    },
    {
        "category_name": "AI reports",
        "source": "xAI (Grok) and other interpretation lanes",
        "contains_personal_data": False,
        "examples": ["data/ai_reports/*.json"],
        "storage_location": "data/ai_reports/; canonical DB via ai_report_ingestion",
        "retention_policy": "indefinite (operator-owned)",
        "deletion_method": "operator-initiated",
        "access_scope": "local single-operator",
        "third_party_processor": "AI inference provider when called",
        "risk_level": "medium",
        "mitigation": "ai_output_schema redacts secrets; advisory-only invariants",
    },
    {
        "category_name": "Candidate outputs",
        "source": "Daily synthesis + promotion pipeline",
        "contains_personal_data": False,
        "examples": ["data/daily_payload/*.json", "runtime/*.json"],
        "storage_location": "data/daily_payload/, runtime/, mvp_local.db",
        "retention_policy": "indefinite",
        "deletion_method": "operator-initiated",
        "access_scope": "local single-operator",
        "third_party_processor": "none",
        "risk_level": "low",
        "mitigation": "local-only; never shipped to providers",
    },
    {
        "category_name": "Operator audit log",
        "source": "scripts/operator_audit_log.py",
        "contains_personal_data": False,
        "examples": ["runtime/operator_audit_log.jsonl"],
        "storage_location": "runtime/operator_audit_log.jsonl",
        "retention_policy": "indefinite (operator review)",
        "deletion_method": "operator-initiated",
        "access_scope": "local single-operator",
        "third_party_processor": "none",
        "risk_level": "low",
        "mitigation": "no secrets recorded; advisory-only stamps in every row",
    },
    {
        "category_name": "Local secrets (.env)",
        "source": "Operator-entered API keys",
        "contains_personal_data": False,
        "examples": [".env (gitignored)"],
        "storage_location": ".env (gitignored)",
        "retention_policy": "until operator rotates / deletes",
        "deletion_method": "operator-initiated",
        "access_scope": "local single-operator",
        "third_party_processor": "none (used to authenticate to providers)",
        "risk_level": "high",
        "mitigation": ".env gitignored; export scan; .env.example uses placeholders",
    },
]


SOURCE_LICENSE_ENTRIES: list[dict[str, Any]] = [
    {
        "provider": "yfinance",
        "source_type": "price",
        "auth_required": False,
        "license_terms_status": "needs review",
        "redistribution_allowed": "no",
        "commercial_use_status": "needs review",
        "rate_limit_known": False,
        "attribution_required": "unknown",
        "storage_allowed": "yes (local, personal)",
        "notes": "Public/unofficial Yahoo API; personal non-commercial only.",
        "verification_status": "NEEDS_REVIEW",
    },
    {
        "provider": "SEC EDGAR",
        "source_type": "filings",
        "auth_required": False,
        "license_terms_status": "public",
        "redistribution_allowed": "yes (attribution)",
        "commercial_use_status": "yes",
        "rate_limit_known": True,
        "attribution_required": "yes",
        "storage_allowed": "yes",
        "notes": "Public; fair-access policy requires User-Agent + 10 req/s cap.",
        "verification_status": "VERIFIED",
    },
    {
        "provider": "GDELT",
        "source_type": "news_event",
        "auth_required": False,
        "license_terms_status": "public",
        "redistribution_allowed": "yes (attribution)",
        "commercial_use_status": "yes",
        "rate_limit_known": True,
        "attribution_required": "yes",
        "storage_allowed": "yes",
        "notes": "Public; attribution requested.",
        "verification_status": "VERIFIED",
    },
    {
        "provider": "NewsAPI",
        "source_type": "news_event",
        "auth_required": True,
        "license_terms_status": "needs review",
        "redistribution_allowed": "no",
        "commercial_use_status": "needs review",
        "rate_limit_known": True,
        "attribution_required": "yes",
        "storage_allowed": "yes (local)",
        "notes": "Developer tier non-commercial; commercial use requires upgrade.",
        "verification_status": "NEEDS_REVIEW",
    },
    {
        "provider": "Polymarket Gamma",
        "source_type": "prediction_market",
        "auth_required": False,
        "license_terms_status": "needs review",
        "redistribution_allowed": "needs review",
        "commercial_use_status": "needs review",
        "rate_limit_known": False,
        "attribution_required": "unknown",
        "storage_allowed": "yes (local)",
        "notes": "Read-only market data; this MVP never trades on the platform.",
        "verification_status": "NEEDS_REVIEW",
    },
    {
        "provider": "Polymarket CLOB",
        "source_type": "prediction_market",
        "auth_required": False,
        "license_terms_status": "needs review",
        "redistribution_allowed": "needs review",
        "commercial_use_status": "needs review",
        "rate_limit_known": False,
        "attribution_required": "unknown",
        "storage_allowed": "yes (local)",
        "notes": "Read-only public order book; never used to place orders.",
        "verification_status": "NEEDS_REVIEW",
    },
    {
        "provider": "Kalshi",
        "source_type": "prediction_market",
        "auth_required": True,
        "license_terms_status": "needs review",
        "redistribution_allowed": "needs review",
        "commercial_use_status": "needs review",
        "rate_limit_known": False,
        "attribution_required": "unknown",
        "storage_allowed": "yes (local)",
        "notes": "Read-only via scripts/kalshi_runner; never places trades.",
        "verification_status": "NEEDS_REVIEW",
    },
    {
        "provider": "Etherscan",
        "source_type": "onchain",
        "auth_required": True,
        "license_terms_status": "needs review",
        "redistribution_allowed": "needs review",
        "commercial_use_status": "needs review",
        "rate_limit_known": True,
        "attribution_required": "yes",
        "storage_allowed": "yes (local)",
        "notes": "Read-only chain data; rate-limited.",
        "verification_status": "NEEDS_REVIEW",
    },
    {
        "provider": "Blockscout",
        "source_type": "onchain",
        "auth_required": False,
        "license_terms_status": "needs review",
        "redistribution_allowed": "needs review",
        "commercial_use_status": "needs review",
        "rate_limit_known": False,
        "attribution_required": "unknown",
        "storage_allowed": "yes (local)",
        "notes": "Read-only EVM chain explorer.",
        "verification_status": "NEEDS_REVIEW",
    },
    {
        "provider": "xAI (Grok)",
        "source_type": "ai_report",
        "auth_required": True,
        "license_terms_status": "needs review",
        "redistribution_allowed": "needs review",
        "commercial_use_status": "needs review",
        "rate_limit_known": True,
        "attribution_required": "unknown",
        "storage_allowed": "yes (local)",
        "notes": "AI interpretation; outputs treated as advisory only.",
        "verification_status": "NEEDS_REVIEW",
    },
    {
        "provider": "Local fixtures",
        "source_type": "local_fixture",
        "auth_required": False,
        "license_terms_status": "public",
        "redistribution_allowed": "yes",
        "commercial_use_status": "yes",
        "rate_limit_known": True,
        "attribution_required": "no",
        "storage_allowed": "yes",
        "notes": "Synthetic perf fixtures; PERF_FIXTURE_* prefix and sidecar.",
        "verification_status": "VERIFIED",
    },
]

# Providers the typed config can enable.  Used by the release-gate check that
# warns when a config-enabled provider is missing from the register.
CONFIG_ENABLED_PROVIDER_KEYS: dict[str, str] = {
    "yfinance_enabled": "yfinance",
    "sec_edgar_enabled": "SEC EDGAR",
    "gdelt_enabled": "GDELT",
    "newsapi_enabled": "NewsAPI",
    "ai_reports_enabled": "xAI (Grok)",
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_privacy_inventory() -> dict[str, Any]:
    return {
        "report": "privacy_inventory",
        "generated_at_utc": _utc_iso(),
        "categories": list(PRIVACY_INVENTORY),
        "advisory_only": True,
        "engineering_honesty_disclaimer":
            "Not legal advice. Lawyer review required before non-operator use.",
        **_contract.advisory_safety_stamps(),
    }


def build_source_license_register() -> dict[str, Any]:
    return {
        "report": "source_license_register",
        "generated_at_utc": _utc_iso(),
        "entries": list(SOURCE_LICENSE_ENTRIES),
        "advisory_only": True,
        "engineering_honesty_disclaimer":
            "Not legal advice. Lawyer review required before non-operator use.",
        **_contract.advisory_safety_stamps(),
    }


def write_registers(
    *,
    privacy_path: Path | None = None,
    register_path: Path | None = None,
) -> tuple[Path, Path]:
    """Write both registers; create parent dir.  Returns the written paths."""
    try:
        cfg = _typed_config.load_typed_config()
        dir_path = cfg.compliance_dir
        p_path = privacy_path or cfg.privacy_inventory_path
        r_path = register_path or cfg.source_license_register_path
    except _typed_config.ConfigSafetyError:
        dir_path = DEFAULT_COMPLIANCE_DIR
        p_path = privacy_path or PRIVACY_INVENTORY_PATH
        r_path = register_path or SOURCE_LICENSE_REGISTER_PATH

    dir_path.mkdir(parents=True, exist_ok=True)
    p_data = build_privacy_inventory()
    r_data = build_source_license_register()
    p_tmp = p_path.with_suffix(".json.tmp")
    p_tmp.write_text(json.dumps(p_data, indent=2, default=str), encoding="utf-8")
    p_tmp.replace(p_path)
    r_tmp = r_path.with_suffix(".json.tmp")
    r_tmp.write_text(json.dumps(r_data, indent=2, default=str), encoding="utf-8")
    r_tmp.replace(r_path)
    return p_path, r_path


def read_register(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def missing_config_enabled_providers(
    cfg: Any | None = None,
    *,
    register: dict[str, Any] | None = None,
) -> list[str]:
    """Return config-enabled providers that have no register entry.

    Used by :mod:`scripts.release_gate` to warn the operator when a new
    provider is wired but not yet documented.
    """
    if cfg is None:
        try:
            cfg = _typed_config.load_typed_config()
        except _typed_config.ConfigSafetyError:
            return []
    if register is None:
        register = read_register(SOURCE_LICENSE_REGISTER_PATH) or build_source_license_register()
    known = {str(entry.get("provider") or "").lower()
             for entry in register.get("entries", [])}
    missing: list[str] = []
    for attr, provider in CONFIG_ENABLED_PROVIDER_KEYS.items():
        if not getattr(cfg, attr, False):
            continue
        if provider.lower() not in known:
            missing.append(provider)
    return missing


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="compliance_registers.py",
        description=(
            "Write the privacy + source-license registers as machine-readable "
            "JSON. Read-only; advisory-only; no broker calls."
        ),
    )
    p.add_argument("--write", action="store_true",
                   help="persist both registers under runtime/compliance/")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.write:
        p, r = write_registers()
        out = {
            "privacy_inventory_path": str(p),
            "source_license_register_path": str(r),
            "ok": True,
            "advisory_only": True,
        }
    else:
        out = {
            "privacy_inventory": build_privacy_inventory(),
            "source_license_register": build_source_license_register(),
        }
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        if args.write:
            print(f"wrote: {out['privacy_inventory_path']}")
            print(f"wrote: {out['source_license_register_path']}")
        else:
            print("Compliance Registers (dry-run, advisory)")
            print("========================================")
            print(f"privacy categories : {len(PRIVACY_INVENTORY)}")
            print(f"license entries    : {len(SOURCE_LICENSE_ENTRIES)}")
    return 0


__all__ = [
    "PRIVACY_INVENTORY",
    "SOURCE_LICENSE_ENTRIES",
    "CONFIG_ENABLED_PROVIDER_KEYS",
    "PRIVACY_INVENTORY_PATH",
    "SOURCE_LICENSE_REGISTER_PATH",
    "build_privacy_inventory",
    "build_source_license_register",
    "write_registers",
    "read_register",
    "missing_config_enabled_providers",
]


if __name__ == "__main__":
    raise SystemExit(main())
