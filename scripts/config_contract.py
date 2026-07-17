"""Typed config / environment contract + drift detector (Kanté Sprint 2 — Task 6).

The MVP runs entirely on local environment variables.  This module makes that
surface a **typed contract** instead of a scatter of ``os.environ.get`` calls,
and detects three classes of problem before they bite:

* a mandatory runtime path is missing/blank → ``FAIL``,
* an optional source key is unset → ``WARN`` (that source simply stays off),
* a **dangerous / execution-related** env var appears → ``FAIL`` (the advisory
  MVP must never carry a broker / live-execution toggle).

It also computes **config drift**: the symmetric difference between the
contract's declared variables and the variables present in ``.env.example``, so
the documented example and the code's expectations can never silently diverge.

ConfigScore = valid_required / required − penalty(dangerous) − penalty(missing_example)
Drift       = | vars(example) △ vars(contract) |

Read-only: never prints a secret *value* (only names + presence booleans),
never touches the DB, never a broker call.
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

DEFAULT_DB_PATH = "runtime/mvp_local.db"

# Variable kinds.
_REQUIRED = "required"      # must resolve (env or documented default)
_SECRET = "secret"          # optional API key / token — never printed
_SOURCE = "source"          # optional source configuration
_PLAIN = "plain"            # non-secret server/runtime setting
_EXEC_FLAG = "exec_flag"    # execution permission flag — must stay OFF

# The typed contract.  Keys MUST match .env.example (drift detector enforces it).
CONTRACT: dict[str, str] = {
    # server / runtime
    "API_HOST": _PLAIN,
    "API_PORT": _PLAIN,
    "ALLOWED_ORIGINS": _PLAIN,
    "MVP_ENVIRONMENT": _PLAIN,
    "MVP_DB_PATH": _REQUIRED,
    # local token (optional)
    "MVP_API_TOKEN": _SECRET,
    # source secrets (optional)
    "EDINET_API_KEY": _SECRET,
    "JAPAN_EDINET_API_KEY": _SECRET,
    "OPENDART_API_KEY": _SECRET,
    "KOREA_DART_API_KEY": _SECRET,
    "ETHERSCAN_API_KEY": _SECRET,
    "BLOCKSCOUT_API_KEY": _SECRET,
    "XAI_API_KEY": _SECRET,
    # source configuration (optional)
    "SEC_USER_AGENT": _SOURCE,
    "SEC_DEFAULT_CIK": _SOURCE,
    "SEC_DEFAULT_WATCHLIST": _SOURCE,
    "GDELT_TIMEOUT_SECONDS": _SOURCE,
    "ETHERSCAN_ADDRESS": _SOURCE,
    "ETHEREUM_ADDRESS": _SOURCE,
    "PUBLIC_ETH_ADDRESS": _SOURCE,
    "BLOCKSCOUT_API_BASE_URL": _SOURCE,
    "BLOCKSCOUT_DEFAULT_CHAIN_ID": _SOURCE,
    "POLY_CLOB_BASE_URL": _SOURCE,
    "POLY_DATA_BASE_URL": _SOURCE,
    "POLY_GAMMA_BASE_URL": _SOURCE,
    "KALSHI_API_BASE": _SOURCE,
    "KALSHI_USE_MOCK_FIXTURES": _SOURCE,
    "XAI_API_BASE_URL": _SOURCE,
    "XAI_MODEL": _SOURCE,
    "PIPELINE_QUOTE_PROVIDER": _SOURCE,
    "SIGNAL_REFINERY_DB_PATH": _SOURCE,
    "SIGNAL_REFINERY_EDGE_THRESHOLD": _SOURCE,
    "SIGNAL_REFINERY_ENABLE_PAPER_ONLY": _SOURCE,
    "SIGNAL_REFINERY_PUBLIC_ONLY": _SOURCE,
    "SIGNAL_REFINERY_SIMULATED_STAKE": _SOURCE,
    # execution flags — known, but must stay OFF for advisory-only
    "PIPELINE_ENABLE_LIVE_EXECUTION": _EXEC_FLAG,
    "PIPELINE_ENABLE_PAPER_EXECUTION": _EXEC_FLAG,
    # Integrated sprint — typed config schema (scripts/typed_config.py).
    "DIAGNOSTICS_SNAPSHOT_TTL_SECONDS": _PLAIN,
    "DIAGNOSTICS_COLD_RECOMPUTE_BUDGET_MS": _PLAIN,
    "DIAGNOSTICS_HOT_CACHE_BUDGET_MS": _PLAIN,
    "DIAGNOSTICS_MAX_ROW_SCAN_ON_COLD_PATH": _PLAIN,
    "YFINANCE_ENABLED": _SOURCE,
    "SEC_EDGAR_ENABLED": _SOURCE,
    "GDELT_ENABLED": _SOURCE,
    "NEWSAPI_ENABLED": _SOURCE,
    "NEWSAPI_KEY": _SECRET,
    "SOURCE_PRICE_SLA_HOURS": _PLAIN,
    "SOURCE_FILINGS_SLA_HOURS": _PLAIN,
    "SOURCE_NEWS_SLA_HOURS": _PLAIN,
    "SOURCE_AI_REPORT_SLA_HOURS": _PLAIN,
    "AI_REPORTS_ENABLED": _SOURCE,
    "AI_REPORTS_DIR": _SOURCE,
    "MODEL_RELIABILITY_LEDGER_PATH": _SOURCE,
    "ADVISORY_ONLY": _PLAIN,
    "HUMAN_EXECUTION_REQUIRED": _PLAIN,
    "EXECUTION_GATE": _PLAIN,
    # Sprint 3 — operator-run live provider refresh (yfinance / SEC / GDELT).
    # MVP_LIVE_REFRESH_OK is the operator opt-in; the others are knobs the
    # operator may want to override.  None of them grants execution.
    "MVP_LIVE_REFRESH_OK": _PLAIN,
    "LIVE_REFRESH_TIMEOUT_SECONDS": _PLAIN,
    "LIVE_REFRESH_PROVIDER_ALLOWLIST": _PLAIN,
    "OPERATOR_LIVE_REFRESH_TTL_HOURS": _PLAIN,
    "YFINANCE_LIVE_ENABLED": _SOURCE,
    "SEC_EDGAR_LIVE_ENABLED": _SOURCE,
    "GDELT_LIVE_ENABLED": _SOURCE,
    "LIVE_REFRESH_MAX_TICKERS": _PLAIN,
    "LIVE_REFRESH_REQUIRE_ADVISORY_ONLY": _PLAIN,
    # Simulation Intelligence Layer (SIL) — advisory-only simulation council.
    # None of these grants execution; they gate simulation breadth and the two
    # OPTIONAL, OFF-by-default engine adapters (Stockfish subprocess, COPASI lib).
    "SIL_ENABLED": _PLAIN,
    "SIL_STOCKFISH_ENABLED": _PLAIN,
    "SIL_COPASI_ENABLED": _PLAIN,
    "SIL_MAX_RUNS": _PLAIN,
    "SIL_MAX_SCENARIOS": _PLAIN,
    "SIL_TIMEOUT_MS": _PLAIN,
}

REQUIRED_VARS = tuple(k for k, v in CONTRACT.items() if v == _REQUIRED)

# Dangerous *unknown* variable-name patterns: any env var matching one of these
# that is NOT a declared contract var indicates broker / live-execution intent.
_DANGEROUS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)broker"),
    re.compile(r"(?i)alpaca"),
    re.compile(r"(?i)ibkr"),
    re.compile(r"(?i)interactive[_-]?brokers"),
    re.compile(r"(?i)oanda"),
    re.compile(r"(?i)robinhood"),
    re.compile(r"(?i)zerodha|kite_api"),
    re.compile(r"(?i)place[_-]?order"),
    re.compile(r"(?i)auto[_-]?trade"),
    re.compile(r"(?i)execute[_-]?order"),
    re.compile(r"(?i)live[_-]?trading"),
)

_TRUTHY = {"1", "true", "yes", "on"}


def _check(name: str, status: str, detail: str, **extra: Any) -> dict[str, Any]:
    out = {"name": name, "status": status, "detail": detail}
    out.update(extra)
    return out


def parse_env_example(repo_root: Path) -> set[str]:
    """Return the set of variable names declared in ``.env.example``."""
    path = repo_root / ".env.example"
    if not path.exists():
        return set()
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        names.add(s.split("=", 1)[0].strip())
    return names


def detect_drift(repo_root: Path) -> dict[str, Any]:
    """Symmetric difference between contract vars and .env.example vars."""
    example = parse_env_example(repo_root)
    contract = set(CONTRACT)
    missing_from_example = sorted(contract - example)   # in contract, not documented
    missing_from_contract = sorted(example - contract)  # documented, not in contract
    drift = sorted(set(missing_from_example) | set(missing_from_contract))
    return {
        "example_present": bool(example),
        "drift_count": len(drift),
        "missing_from_example": missing_from_example,
        "missing_from_contract": missing_from_contract,
    }


def evaluate(
    env: dict[str, str] | None = None,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Validate the environment against the contract.  Never prints values."""
    import os

    environ = dict(env) if env is not None else dict(os.environ)
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    checks: list[dict[str, Any]] = []

    # 1. Mandatory runtime DB path: resolvable (env or default), non-blank.
    raw_db = environ.get("MVP_DB_PATH", DEFAULT_DB_PATH)
    if "MVP_DB_PATH" in environ and not str(environ.get("MVP_DB_PATH") or "").strip():
        checks.append(_check("runtime_db_path", FAIL,
                             "MVP_DB_PATH is set but blank — mandatory runtime DB "
                             "path missing."))
    elif not str(raw_db).strip():
        checks.append(_check("runtime_db_path", FAIL,
                             "no runtime DB path could be resolved."))
    else:
        source = "env" if environ.get("MVP_DB_PATH") else "default"
        checks.append(_check("runtime_db_path", PASS,
                             f"runtime DB path resolved from {source}."))

    # 2. Optional source keys: WARN when unset (that source stays off).
    unset_sources = [k for k, kind in CONTRACT.items()
                     if kind in (_SECRET, _SOURCE)
                     and not str(environ.get(k, "")).strip()]
    if unset_sources:
        checks.append(_check("optional_source_keys", WARN,
                             f"{len(unset_sources)} optional source key(s) unset — "
                             "those sources stay disabled (not an error).",
                             unset=unset_sources))
    else:
        checks.append(_check("optional_source_keys", PASS,
                             "all optional source keys present."))

    # 3. Execution flags must stay OFF for advisory-only.
    exec_on = [k for k, kind in CONTRACT.items() if kind == _EXEC_FLAG
               and str(environ.get(k, "")).strip().lower() in _TRUTHY]
    live_on = "PIPELINE_ENABLE_LIVE_EXECUTION" in exec_on
    if live_on:
        checks.append(_check("execution_flags_off", FAIL,
                             "PIPELINE_ENABLE_LIVE_EXECUTION is truthy — advisory "
                             "MVP must keep live execution OFF.", enabled=exec_on))
    elif exec_on:
        checks.append(_check("execution_flags_off", WARN,
                             f"paper-execution flag enabled: {exec_on} (simulation "
                             "only; broker still never called).", enabled=exec_on))
    else:
        checks.append(_check("execution_flags_off", PASS,
                             "no execution flags enabled."))

    # 4. Dangerous unknown vars (broker / live-trading intent).
    dangerous: list[str] = []
    for name in environ:
        if name in CONTRACT:
            continue
        if any(p.search(name) for p in _DANGEROUS_PATTERNS):
            dangerous.append(name)
    if dangerous:
        checks.append(_check("no_dangerous_env_vars", FAIL,
                             f"execution-related env var(s) present: "
                             f"{sorted(dangerous)} — not allowed in advisory MVP.",
                             dangerous=sorted(dangerous)))
    else:
        checks.append(_check("no_dangerous_env_vars", PASS,
                             "no broker / live-trading env vars present."))

    # 5. Config drift vs .env.example.
    drift = detect_drift(root)
    if not drift["example_present"]:
        checks.append(_check("env_example_drift", WARN,
                             ".env.example is missing — cannot verify drift."))
    elif drift["drift_count"]:
        checks.append(_check("env_example_drift", WARN,
                             f"config drift: {drift['drift_count']} var(s) differ "
                             "between contract and .env.example.",
                             **{k: drift[k] for k in
                                ("missing_from_example", "missing_from_contract")}))
    else:
        checks.append(_check("env_example_drift", PASS,
                             "contract matches .env.example (no drift)."))

    # --- score + verdict ---------------------------------------------------
    counts = {PASS: 0, WARN: 0, FAIL: 0, INFO: 0}
    for c in checks:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    overall = FAIL if counts[FAIL] else WARN if counts[WARN] else PASS

    valid_required = sum(
        1 for c in checks if c["name"] == "runtime_db_path" and c["status"] == PASS
    )
    config_score = round(
        (valid_required / max(len(REQUIRED_VARS), 1))
        - (0.5 if counts[FAIL] else 0.0)
        - (0.1 if not drift["example_present"] else 0.0),
        4,
    )

    return {
        "report": "config_contract",
        "overall": overall,
        "checks": checks,
        "counts": counts,
        "config_score": config_score,
        "drift": drift,
        "required_vars": list(REQUIRED_VARS),
        "contract_var_count": len(CONTRACT),
        **_contract.advisory_safety_stamps(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="config_contract.py",
        description=(
            "Validate the environment against the typed config contract. "
            "Never prints secret values; never a broker call."
        ),
    )
    p.add_argument("--repo-root", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = evaluate(repo_root=args.repo_root)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Config contract: {report['overall']} (score={report['config_score']})")
        for c in report["checks"]:
            print(f"  [{c['status']:<4}] {c['name']:<22} {c['detail']}")
    return 0 if report["overall"] != FAIL else 1


__all__ = [
    "PASS", "WARN", "FAIL", "INFO",
    "CONTRACT", "REQUIRED_VARS",
    "parse_env_example", "detect_drift", "evaluate",
]


if __name__ == "__main__":
    raise SystemExit(main())
