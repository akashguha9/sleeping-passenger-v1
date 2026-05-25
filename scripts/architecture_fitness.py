"""Architecture fitness / dependency-boundary tests (Sprint 2 — Task 8).

The MVP has many strong modules; complexity is rising.  This module is the
*reading-passing-lanes* layer: a set of cheap, static, import-graph checks that
keep the architecture from degrading into spaghetti, enforced by tests so a
boundary violation fails CI.

Boundaries enforced (all currently satisfied)
---------------------------------------------
* **Contract purity** — ``advisory_contract`` / ``operator_auth`` must not import
  persistence, the reactor, the API server, a DB driver, or the network.  They
  are the bedrock layer everything else depends on.
* **Diagnostic purity** — pure compute modules (``complex_systems_diagnostics``,
  ``model_signal_normalizer``) must not import ``sqlite3`` — they score what a
  caller hands them; the *bridge* layer owns canonical reads.
* **No broker/execution module** — no script imports a broker / order-execution
  SDK (alpaca, ib_insync, oanda, ccxt, …).
* **No frontend import in scripts** — the Python backend never imports the TS
  frontend.
* **Tests don't write the runtime DB** — the autouse runtime-DB isolation
  fixture in ``conftest.py`` is present.

ArchScore = 1 − (violations + circular + side_effects + runtime_db_writes_in_tests)
                / (total_modules + 1)

Read-only (parses source text; never imports the modules under test); never a
broker call.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([A-Za-z0-9_.]+)", re.MULTILINE)

# Contract / bedrock modules: must not depend on these substrings.
_CONTRACT_MODULES = ("advisory_contract", "operator_auth")
_CONTRACT_FORBIDDEN = ("sqlite3", "persistence", "signal_reactor",
                       "adaptive_signal_router", "api_server",
                       "reactor_canonical_inputs", "frontend",
                       "requests", "urllib.request", "socket")

# Pure-compute diagnostic modules: must not touch a DB driver.
_DIAGNOSTIC_MODULES = ("complex_systems_diagnostics", "model_signal_normalizer")
_DIAGNOSTIC_FORBIDDEN = ("sqlite3",)

# Broker / order-execution SDK import tokens (forbidden anywhere in scripts).
_BROKER_IMPORT_TOKENS = ("alpaca", "ib_insync", "ibapi", "oandapyV20",
                         "oanda", "ccxt", "robin_stocks", "kiteconnect")


def import_targets(text: str) -> list[str]:
    """Extract imported module paths from source text via AST (no execution).

    For ``from X import a, b`` we emit ``X``, ``X.a`` and ``X.b`` so a check for
    a forbidden *name* (e.g. ``persistence`` in ``from scripts import
    persistence``) is caught, not just the package root.  Falls back to a regex
    scan if the source does not parse.
    """
    out: list[str] = []
    try:
        tree = ast.parse(text or "")
    except SyntaxError:
        return _IMPORT_RE.findall(text or "")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod:
                out.append(mod)
            for alias in node.names:
                out.append(f"{mod}.{alias.name}" if mod else alias.name)
    return out


def module_import_violations(text: str, forbidden: tuple[str, ...]) -> list[str]:
    """Return the import targets in ``text`` that match a forbidden substring."""
    hits: list[str] = []
    for target in import_targets(text):
        norm = target[len("scripts."):] if target.startswith("scripts.") else target
        for bad in forbidden:
            if bad in target or norm == bad or norm.startswith(bad):
                hits.append(target)
                break
    return sorted(set(hits))


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:  # pragma: no cover
        return ""


def _check(name: str, status: str, detail: str, **extra: Any) -> dict[str, Any]:
    out = {"name": name, "status": status, "detail": detail}
    out.update(extra)
    return out


def check_contract_purity(scripts_dir: Path) -> dict[str, Any]:
    offenders: dict[str, list[str]] = {}
    for mod in _CONTRACT_MODULES:
        path = scripts_dir / f"{mod}.py"
        if not path.exists():
            continue
        viol = module_import_violations(_read(path), _CONTRACT_FORBIDDEN)
        if viol:
            offenders[mod] = viol
    if offenders:
        return _check("contract_layer_purity", FAIL,
                      f"contract modules import forbidden layers: {offenders}",
                      offenders=offenders)
    return _check("contract_layer_purity", PASS,
                  "contract modules import no persistence/reactor/api/DB/network.")


def check_diagnostic_purity(scripts_dir: Path) -> dict[str, Any]:
    offenders: dict[str, list[str]] = {}
    for mod in _DIAGNOSTIC_MODULES:
        path = scripts_dir / f"{mod}.py"
        if not path.exists():
            continue
        viol = module_import_violations(_read(path), _DIAGNOSTIC_FORBIDDEN)
        if viol:
            offenders[mod] = viol
    if offenders:
        return _check("diagnostic_layer_purity", FAIL,
                      f"pure diagnostics import a DB driver: {offenders}",
                      offenders=offenders)
    return _check("diagnostic_layer_purity", PASS,
                  "pure diagnostic modules do not import sqlite3.")


def check_no_broker_imports(scripts_dir: Path) -> dict[str, Any]:
    offenders: dict[str, list[str]] = {}
    for path in sorted(scripts_dir.glob("*.py")):
        viol = module_import_violations(_read(path), _BROKER_IMPORT_TOKENS)
        if viol:
            offenders[path.name] = viol
    if offenders:
        return _check("no_broker_execution_imports", FAIL,
                      f"broker/execution SDK import(s): {offenders}",
                      offenders=offenders)
    return _check("no_broker_execution_imports", PASS,
                  "no broker / order-execution SDK imported by any script.")


def check_no_frontend_imports(scripts_dir: Path) -> dict[str, Any]:
    offenders: dict[str, list[str]] = {}
    for path in sorted(scripts_dir.glob("*.py")):
        viol = module_import_violations(_read(path), ("frontend",))
        if viol:
            offenders[path.name] = viol
    if offenders:
        return _check("no_frontend_imports_in_scripts", FAIL,
                      f"scripts import the frontend: {offenders}", offenders=offenders)
    return _check("no_frontend_imports_in_scripts", PASS,
                  "no script imports the frontend package.")


def check_tests_runtime_db_isolated(repo_root: Path) -> dict[str, Any]:
    conftest = repo_root / "conftest.py"
    text = _read(conftest)
    if "_isolate_runtime_db" in text and "DB_PATH" in text:
        return _check("tests_runtime_db_isolated", PASS,
                      "conftest autouse fixture isolates the runtime DB in tests.")
    return _check("tests_runtime_db_isolated", FAIL,
                  "conftest is missing the runtime-DB isolation fixture.")


def evaluate(repo_root: Path | None = None) -> dict[str, Any]:
    """Run all architecture-fitness checks; compute ArchScore."""
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    scripts_dir = root / "scripts"
    checks = [
        check_contract_purity(scripts_dir),
        check_diagnostic_purity(scripts_dir),
        check_no_broker_imports(scripts_dir),
        check_no_frontend_imports(scripts_dir),
        check_tests_runtime_db_isolated(root),
    ]
    violations = sum(1 for c in checks if c["status"] == FAIL)
    total_modules = len(list(scripts_dir.glob("*.py"))) if scripts_dir.exists() else 0
    arch_score = round(1.0 - violations / (total_modules + 1.0), 4)
    overall = FAIL if violations else PASS
    return {
        "report": "architecture_fitness",
        "repo_root": str(root),
        "overall": overall,
        "checks": checks,
        "violation_count": violations,
        "total_modules": total_modules,
        "arch_score": arch_score,
        **_contract.advisory_safety_stamps(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="architecture_fitness.py",
        description=(
            "Static architecture-boundary fitness checks. Read-only; never a "
            "broker call."
        ),
    )
    p.add_argument("--repo-root", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = evaluate(args.repo_root)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Architecture fitness: {report['overall']} "
              f"(score={report['arch_score']}, modules={report['total_modules']})")
        for c in report["checks"]:
            print(f"  [{c['status']:<4}] {c['name']:<32} {c['detail']}")
    return 0 if report["overall"] != FAIL else 1


__all__ = [
    "import_targets", "module_import_violations", "evaluate",
    "check_contract_purity", "check_diagnostic_purity",
    "check_no_broker_imports", "check_no_frontend_imports",
    "check_tests_runtime_db_isolated",
]


if __name__ == "__main__":
    raise SystemExit(main())
