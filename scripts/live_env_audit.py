"""Live-data environment audit — read-only inventory of env requirements.

Scans .env.example for variable names, checks presence in .env (NAMES ONLY —
values are never read into the report, never printed), classifies each
variable for live read-only data wiring, and verifies .env is git-ignored.

Classifications:
  READ_ONLY_OK              safe read-only data access
  TRADING_FORBIDDEN         would imply execution/trading — never to be set
  SAFETY_LOCK               execution locks that must stay locked
  OPTIONAL                  nice-to-have provider
  REQUIRED_FOR_LIVE         needed for a specific live feed
  PUBLIC_FALLBACK_AVAILABLE keyless public endpoint exists
  MISSING_FAIL_CLOSED       required and absent — feature fails closed

ADVISORY_ONLY. No secrets in output. No network.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
_REPO_ROOT = Path(__file__).resolve().parents[1]

# (pattern, classification, purpose, read_only, public_fallback, safe_to_request)
_RULES: list[tuple[str, str, str, bool, bool, bool]] = [
    (r"^SEC_USER_AGENT$", "REQUIRED_FOR_LIVE",
     "EDGAR identity header (required by SEC fair-access policy)",
     True, False, True),
    (r"^(POLY_GAMMA_BASE_URL|POLY_DATA_BASE_URL|POLY_CLOB_BASE_URL)$",
     "READ_ONLY_OK", "Polymarket public read-only endpoints (keyless)",
     True, True, True),
    (r"^KALSHI_API_BASE$", "READ_ONLY_OK",
     "Kalshi public market-data endpoint (keyless)", True, True, True),
    (r"^KALSHI_USE_MOCK_FIXTURES$", "OPTIONAL",
     "opt-in mock fixtures for Kalshi tests", True, True, True),
    (r"^YFINANCE", "READ_ONLY_OK",
     "yfinance public equity prices (no key)", True, True, True),
    (r"^(SEC_EDGAR_ENABLED|SEC_EDGAR_LIVE_ENABLED|SEC_DEFAULT_CIK|SEC_DEFAULT_WATCHLIST)$",
     "READ_ONLY_OK", "EDGAR read-only toggles/defaults", True, True, True),
    (r"^(GDELT_|NEWSAPI_ENABLED)", "OPTIONAL",
     "news chain toggles (GDELT keyless; observed network-blocked here)",
     True, True, True),
    (r"^NEWSAPI_KEY$", "OPTIONAL",
     "NewsAPI key — news fallback #2 (read-only)", True, False, True),
    (r"^(EDINET_API_KEY|JAPAN_EDINET_API_KEY|KOREA_DART_API_KEY|OPENDART_API_KEY)$",
     "OPTIONAL", "Asia disclosure read-only keys", True, False, True),
    (r"^(ETHERSCAN_API_KEY|BLOCKSCOUT_API_KEY|BLOCKSCOUT_)",
     "OPTIONAL", "chain-explorer read-only", True, True, True),
    (r"^(ETHEREUM_ADDRESS|ETHERSCAN_ADDRESS|PUBLIC_ETH_ADDRESS)$",
     "READ_ONLY_OK", "public addresses for read-only explorer lookups "
     "(NOT keys)", True, True, True),
    (r"^XAI_", "OPTIONAL", "xAI interpreter (read-only analysis)", True,
     False, True),
    (r"^(PIPELINE_ENABLE_LIVE_EXECUTION)$", "TRADING_FORBIDDEN",
     "would enable live execution — must remain false forever", False,
     False, False),
    (r"^(EXECUTION_GATE|HUMAN_EXECUTION_REQUIRED|ADVISORY_ONLY|PIPELINE_ENABLE_PAPER_EXECUTION|SIGNAL_REFINERY_ENABLE_PAPER_ONLY)$",
     "SAFETY_LOCK", "execution safety locks — keep locked/advisory", False,
     False, False),
    (r"^(MVP_API_TOKEN|MVP_API_TOKEN_HASH|SECRET_PROVIDER)$", "OPTIONAL",
     "local API auth (not a trading credential)", True, False, True),
    (r".*(PRIVATE_KEY|WALLET|ORDER_KEY|BROKER).*", "TRADING_FORBIDDEN",
     "broker/wallet/private-key material — never requested, never stored",
     False, False, False),
]
_DEFAULT = ("OPTIONAL", "repo/runtime configuration", True, True, True)


def _classify(name: str) -> dict[str, Any]:
    for pattern, cls, purpose, ro, fallback, safe in _RULES:
        if re.match(pattern, name):
            return {"classification": cls, "purpose": purpose,
                    "read_only": ro, "public_no_key_fallback": fallback,
                    "safe_to_request_from_user": safe}
    cls, purpose, ro, fallback, safe = _DEFAULT
    return {"classification": cls, "purpose": purpose, "read_only": ro,
            "public_no_key_fallback": fallback,
            "safe_to_request_from_user": safe}


def _env_names(path: Path) -> dict[str, bool]:
    """{name: has_nonempty_value} — values themselves are never retained."""
    out: dict[str, bool] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        out[name.strip()] = bool(value.strip())
    return out


def build_report(root: Path = _REPO_ROOT) -> dict[str, Any]:
    example = _env_names(root / ".env.example")
    actual = _env_names(root / ".env")
    gitignore = (root / ".gitignore").read_text(encoding="utf-8") \
        if (root / ".gitignore").exists() else ""
    env_ignored = bool(re.search(r"^\.env$", gitignore, re.M)
                       or re.search(r"^\.env\.\*$", gitignore, re.M))
    rows = []
    for name in sorted(set(example) | set(actual)):
        cls = _classify(name)
        required = cls["classification"] in ("REQUIRED_FOR_LIVE",)
        present = actual.get(name, False)
        status = ("PRESENT" if present else
                  ("MISSING_FAIL_CLOSED" if required else "MISSING"))
        rows.append({"variable_name": name,
                     "required_or_optional": ("REQUIRED_FOR_LIVE" if required
                                              else "OPTIONAL"),
                     **cls, "current_status": status})
    return {
        "env_file_git_ignored": env_ignored,
        "n_variables": len(rows),
        "n_present": sum(1 for r in rows if r["current_status"] == "PRESENT"),
        "trading_forbidden": [r["variable_name"] for r in rows
                              if r["classification"] == "TRADING_FORBIDDEN"],
        "safety_locks": [r["variable_name"] for r in rows
                         if r["classification"] == "SAFETY_LOCK"],
        "missing_fail_closed": [r["variable_name"] for r in rows
                                if r["current_status"] == "MISSING_FAIL_CLOSED"],
        "variables": rows,
        "advisory_status": ADVISORY_STATUS,
        "note": "Values are never read into this report. Trading/broker/"
                "wallet keys are never requested.",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Environment requirements audit (read-only)", "",
             f".env git-ignored: **{report['env_file_git_ignored']}**  ",
             f"Variables: {report['n_variables']} · present: "
             f"{report['n_present']}", "",
             "| variable | class | required | status | read-only | "
             "public fallback |", "|---|---|---|---|---|---|"]
    for r in report["variables"]:
        lines.append(
            f"| {r['variable_name']} | {r['classification']} | "
            f"{r['required_or_optional']} | {r['current_status']} | "
            f"{r['read_only']} | {r['public_no_key_fallback']} |")
    lines += ["", f"TRADING_FORBIDDEN: {report['trading_forbidden']}",
              f"SAFETY_LOCKS (keep locked): {report['safety_locks']}",
              "", report["note"]]
    return "\n".join(lines)


def _main() -> int:
    ap = argparse.ArgumentParser(description="Env requirements audit")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    report = build_report()
    if args.write:
        out_json = _REPO_ROOT / "runtime" / "env_requirements_report.json"
        out_md = _REPO_ROOT / "runtime" / "env_requirements_report.md"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(report, indent=2, sort_keys=True),
                            encoding="utf-8")
        out_md.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "variables"},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
