"""Compliance preflight — read-only legal/privacy/posture checks.

The legal floor of the Kanté sprint: prove, with cheap read-only checks, that
the repo's *visible behaviour and disclosures* match its advisory-only posture.

Checks
------
* no broker execution routes exposed by the API server,
* no positive autonomous-trading / "we trade for you" claims in surface docs,
* an advisory-only disclosure is present (``docs/ADVISORY_DISCLOSURE.md``),
* "human makes the final decision" language is present,
* a data-source license register exists,
* secrets are gitignored (``.env`` patterns) and a safe ``.env.example`` exists,
* JSONL is audit-only and SQLite is canonical (from the shared contract),
* committed exports contain no obvious secret-like tokens,
* no "personalized financial advice / your financial advisor" claim.

Contract
--------
**This module never touches the network** (no ``urllib`` / ``requests`` /
``socket`` import) and never calls a broker.  It is purely a filesystem +
contract reader.  This is engineering honesty, not legal advice.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"

# Surface docs scanned for forbidden positive claims.
_SURFACE_DOCS = (
    "README.md",
    "docs/ADVISORY_ONLY_SAFETY_MODEL.md",
    "docs/LEGAL_PRIVACY_NOTES.md",
    "docs/ADVISORY_DISCLOSURE.md",
    "docs/LEGAL_PRIVACY_COMPLIANCE_MODEL.md",
    "docs/DATA_SOURCE_LICENSE_REGISTER.md",
)

# Positive-claim phrases that must NEVER appear (chosen so they cannot collide
# with the existing negated "what this is NOT" language).
_EXECUTION_CLAIM_PHRASES = (
    "executes trades for you",
    "places orders automatically",
    "trades on your behalf",
    "automated execution of trades",
    "fully autonomous trading",
    "we will trade",
)

_ADVISER_CLAIM_PHRASES = (
    "personalized financial advice",
    "your personal financial advisor",
    "personalized investment advice",
    "we act as your financial advisor",
)

# Broker-like route tokens that must not appear in the API server.
_BROKER_ROUTE_TOKENS = (
    "/place_order", "/submit_order", "/execute_trade", "/broker",
    "place_broker_order", "submit_broker_order",
)

# Secret-like token patterns for export scanning.
_SECRET_RE: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(api[_-]?key|secret|bearer)\s*[=:]\s*\S{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"xai-[A-Za-z0-9]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def _check(name: str, status: str, detail: str, **extra: Any) -> dict[str, Any]:
    out = {"name": name, "status": status, "detail": detail}
    out.update(extra)
    return out


# Negation tokens — a phrase preceded by one of these (within a short window)
# is a *negated* mention ("does not provide X"), not a positive claim.
_NEGATORS = (
    "no ", "not ", "never ", "n't ", "without ", "does not ", "do not ",
    "cannot ", "won't ", "neither ", "nor ",
)


def _positive_mention(text: Any, phrases: tuple[str, ...]) -> bool:
    """True if any phrase appears as a *positive* (non-negated) claim.

    Markdown emphasis (``*`` / ``_``) is stripped from the lookback window so
    ``does **not** provide X`` is correctly read as a negation.
    """
    lowered = str(text or "").lower()
    for phrase in phrases:
        start = 0
        while True:
            idx = lowered.find(phrase, start)
            if idx == -1:
                break
            window = lowered[max(0, idx - 30):idx].replace("*", "").replace("_", "")
            if not any(neg in window for neg in _NEGATORS):
                return True
            start = idx + len(phrase)
    return False


def has_execution_claim(text: Any) -> bool:
    """True if ``text`` contains a positive autonomous-execution claim."""
    return _positive_mention(text, _EXECUTION_CLAIM_PHRASES)


def has_adviser_claim(text: Any) -> bool:
    """True if ``text`` contains a personalized-financial-adviser claim."""
    return _positive_mention(text, _ADVISER_CLAIM_PHRASES)


def find_secret_like(text: Any) -> list[str]:
    """Return the secret-pattern names that match ``text`` (no values leaked)."""
    s = str(text or "")
    hits: list[str] = []
    for pattern in _SECRET_RE:
        if pattern.search(s):
            hits.append(pattern.pattern[:24])
    return hits


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _scan_surface_docs(repo_root: Path, predicate, label: str, name: str) -> dict[str, Any]:
    offenders: list[str] = []
    for rel in _SURFACE_DOCS:
        path = repo_root / rel
        if path.exists() and predicate(_read(path)):
            offenders.append(rel)
    if offenders:
        return _check(name, FAIL, f"{label} found in: {offenders}.",
                      offenders=offenders)
    return _check(name, PASS, f"no {label} in surface docs.")


def check_no_broker_route(repo_root: Path) -> dict[str, Any]:
    api = repo_root / "scripts" / "api_server.py"
    if not api.exists():
        return _check("no_broker_execution_routes", INFO, "api_server.py absent.")
    text = _read(api).lower()
    hits = [t for t in _BROKER_ROUTE_TOKENS if t in text]
    if hits:
        return _check("no_broker_execution_routes", FAIL,
                      f"broker-like route token(s): {hits}.", hits=hits)
    return _check("no_broker_execution_routes", PASS,
                  "no broker / order-placement route exposed.")


def check_no_autonomous_claims(repo_root: Path) -> dict[str, Any]:
    return _scan_surface_docs(repo_root, has_execution_claim,
                              "autonomous-execution claim",
                              "no_autonomous_trading_claims")


def check_no_adviser_claims(repo_root: Path) -> dict[str, Any]:
    return _scan_surface_docs(repo_root, has_adviser_claim,
                              "personalized-adviser claim",
                              "no_personalized_adviser_claim")


def check_advisory_disclosure(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "docs" / "ADVISORY_DISCLOSURE.md"
    if not path.exists():
        return _check("advisory_disclosure_present", FAIL,
                      "docs/ADVISORY_DISCLOSURE.md is missing.")
    text = _read(path).lower()
    if "advisory-only" not in text and "advisory only" not in text:
        return _check("advisory_disclosure_present", FAIL,
                      "ADVISORY_DISCLOSURE.md lacks the advisory-only statement.")
    return _check("advisory_disclosure_present", PASS,
                  "advisory-only disclosure present.")


def check_human_decision_language(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "docs" / "ADVISORY_DISCLOSURE.md"
    text = _read(path).lower()
    markers = ("human makes the final decision", "final human decision",
               "human final decision", "a human makes")
    if any(m in text for m in markers):
        return _check("human_final_decision_language", PASS,
                      "human-final-decision language present.")
    return _check("human_final_decision_language", FAIL,
                  "no human-final-decision language in the disclosure.")


def check_source_register(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "docs" / "DATA_SOURCE_LICENSE_REGISTER.md"
    if not path.exists():
        return _check("data_source_register_exists", FAIL,
                      "docs/DATA_SOURCE_LICENSE_REGISTER.md is missing.")
    return _check("data_source_register_exists", PASS,
                  "data-source license register present.")


def check_secrets_gitignored(repo_root: Path) -> dict[str, Any]:
    gitignore = repo_root / ".gitignore"
    if not gitignore.exists():
        return _check("secrets_not_committed", WARN, ".gitignore absent.")
    body = _read(gitignore)
    has_env = any(line.strip() in {".env", ".env.*", "*.env"}
                  or line.strip().startswith(".env")
                  for line in body.splitlines())
    example = (repo_root / ".env.example").exists()
    if has_env:
        return _check("secrets_not_committed", PASS,
                      f".env patterns are gitignored (.env.example present={example}).")
    return _check("secrets_not_committed", FAIL,
                  ".env is not covered by .gitignore — secrets may be committed.")


def check_jsonl_audit_only() -> dict[str, Any]:
    truth = _contract.canonical_truth_declaration()
    if truth["jsonl_is_canonical"] is False and truth["sqlite_is_canonical"] is True:
        return _check("jsonl_audit_only_sqlite_canonical", PASS,
                      "SQLite canonical; JSONL audit-only (per shared contract).")
    return _check("jsonl_audit_only_sqlite_canonical", FAIL,
                  "truth model violated — JSONL must not be canonical.")


def check_exports_no_secrets(repo_root: Path) -> dict[str, Any]:
    exports = repo_root / "exports"
    if not exports.exists():
        return _check("exports_no_secrets", INFO, "exports/ absent.")
    offenders: list[str] = []
    for path in sorted(exports.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".csv", ".json", ".txt", ".md", ".jsonl"}:
            continue
        if find_secret_like(_read(path)):
            offenders.append(path.name)
    if offenders:
        return _check("exports_no_secrets", FAIL,
                      f"secret-like tokens in exports: {offenders}.",
                      offenders=offenders)
    return _check("exports_no_secrets", PASS,
                  "no obvious secret-like tokens in committed exports.")


def run_compliance_preflight(repo_root: Path | None = None) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    checks = [
        check_no_broker_route(root),
        check_no_autonomous_claims(root),
        check_advisory_disclosure(root),
        check_human_decision_language(root),
        check_source_register(root),
        check_secrets_gitignored(root),
        check_jsonl_audit_only(),
        check_exports_no_secrets(root),
        check_no_adviser_claims(root),
    ]
    counts = {PASS: 0, WARN: 0, FAIL: 0, INFO: 0}
    for c in checks:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    overall = FAIL if counts[FAIL] else WARN if counts[WARN] else PASS
    return {
        "report": "compliance_preflight",
        "repo_root": str(root),
        "overall": overall,
        "checks": checks,
        "counts": counts,
        "disclaimer": (
            "Engineering honesty, not legal advice. A qualified lawyer should "
            "review every external-facing claim before any non-operator use."
        ),
        **_contract.advisory_safety_stamps(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="compliance_preflight.py",
        description=(
            "Read-only legal/privacy/posture checks. Never touches the "
            "network; never calls a broker."
        ),
    )
    p.add_argument("--repo-root", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = run_compliance_preflight(args.repo_root)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Compliance Preflight: {report['overall']}")
        for c in report["checks"]:
            print(f"  [{c['status']:<4}] {c['name']:<34} {c['detail']}")
        print(f"\n  {report['disclaimer']}")
    return 0 if report["overall"] != FAIL else 1


__all__ = [
    "PASS", "WARN", "FAIL", "INFO",
    "has_execution_claim", "has_adviser_claim", "find_secret_like",
    "run_compliance_preflight",
]


if __name__ == "__main__":
    raise SystemExit(main())
