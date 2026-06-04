"""Repo-wide no-execution guard (widens the ingestion-only AST policy).

The original guard (tests/test_no_execution_policy_config.py) only scanned
scripts/ingestion/.  This widens enforcement to ALL backend application code
(scripts/ + src/) and the frontend, and adds a dependency guard so a broker /
order-execution SDK cannot be added to requirements or package.json without an
explicit read-only allowlist entry.

What it forbids (the unambiguous execution surface):
  * function / method DEFINITIONS named place_order, submit_order,
    modify_order, cancel_order, execute_trade, auto_buy, auto_sell.
  * CALLS to any of those names (``x.place_order(...)``, ``execute_trade(...)``).

What it deliberately allows (no false positives):
  * String literals listing forbidden tokens (policy files, the advisory
    contract's FORBIDDEN_EXECUTION_TOKENS, smoke-test blocklists). Those are
    SAFETY scaffolding, not execution code, and AST def/call detection ignores
    plain strings.
  * The legitimate paper-simulation module (scripts/paper_execution.py) which
    only builds simulated ledger rows (close_paper_position, build_paper_*),
    never a broker order.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Unambiguous execution method names — defining or calling any of these is a
# real broker/order surface, regardless of which file it lives in.
FORBIDDEN_NAMES = {
    "place_order",
    "submit_order",
    "modify_order",
    "cancel_order",
    "execute_trade",
    "auto_buy",
    "auto_sell",
    "create_order",
    "send_order",
    "route_order",
}

# Directories whose *.py we scan.  We intentionally include scripts/external
# so vendored code cannot smuggle an order path in.
_SCAN_DIRS = ("scripts", "src")


def _py_files() -> list[Path]:
    files: list[Path] = []
    for d in _SCAN_DIRS:
        root = REPO_ROOT / d
        if root.exists():
            files.extend(sorted(root.rglob("*.py")))
    return files


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


@pytest.mark.parametrize("py_file", _py_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_forbidden_definitions_or_calls(py_file: Path) -> None:
    # utf-8-sig so a leading BOM (some shipped files carry one; Python's import
    # machinery strips it) does not masquerade as a SyntaxError.
    source = py_file.read_text(encoding="utf-8-sig")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:  # a syntax error in shipped code is itself a fail
        pytest.fail(f"{py_file}: SyntaxError: {exc}")

    def_violations: set[str] = set()
    call_violations: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in FORBIDDEN_NAMES:
                def_violations.add(node.name)
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            if name in FORBIDDEN_NAMES:
                call_violations.add(name)

    rel = py_file.relative_to(REPO_ROOT)
    assert not def_violations, (
        f"{rel} DEFINES forbidden execution method(s): {sorted(def_violations)} — "
        "advisory-only MVP must not define order/broker execution functions."
    )
    assert not call_violations, (
        f"{rel} CALLS forbidden execution method(s): {sorted(call_violations)} — "
        "advisory-only MVP must not invoke order/broker execution."
    )


def _scan_snippet(source: str) -> tuple[set[str], set[str]]:
    """Mirror of the file scanner, for self-testing the detector."""
    tree = ast.parse(source)
    defs: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in FORBIDDEN_NAMES:
                defs.add(node.name)
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            if name in FORBIDDEN_NAMES:
                calls.add(name)
    return defs, calls


def test_detector_catches_forbidden_definition() -> None:
    defs, _ = _scan_snippet("def place_order(x):\n    return x\n")
    assert "place_order" in defs


def test_detector_catches_forbidden_method_call() -> None:
    _, calls = _scan_snippet("broker.submit_order(1)\n")
    assert "submit_order" in calls


def test_detector_catches_bare_execute_trade_call() -> None:
    _, calls = _scan_snippet("execute_trade(symbol='X')\n")
    assert "execute_trade" in calls


def test_detector_ignores_string_literals() -> None:
    # Token lists / policy strings must NOT trip the detector.
    defs, calls = _scan_snippet('FORBIDDEN = ["place_order", "submit_order"]\n')
    assert not defs and not calls


def test_scan_covers_more_than_ingestion() -> None:
    """Regression guard: the widened scan must reach far beyond ingestion."""
    files = _py_files()
    ingestion = [f for f in files if "ingestion" in f.parts]
    assert len(files) > 100, "scan should cover the whole backend, not a handful"
    assert len(files) > len(ingestion) * 3, "scan is still effectively ingestion-only"


# ---------------------------------------------------------------------------
# Dependency guard — broker / order-execution SDKs are blocked unless an
# explicit read-only allowlist entry is added (none today).
# ---------------------------------------------------------------------------

# Substrings that imply an order-execution trading SDK.  Read-only market-data
# libraries (yfinance, pandas, requests, …) are NOT listed.
BROKER_EXECUTION_SDKS = (
    "ib_insync",
    "ibapi",
    "interactivebrokers",
    "alpaca-trade-api",
    "alpaca_trade_api",
    "alpaca-py",
    "kiteconnect",
    "tda-api",
    "tda_api",
    "robin_stocks",
    "robinhood",
    "ccxt",  # exchange trading SDK (read+trade); flag unless allowlisted
    "binance-connector",
    "python-binance",
    "oandapyV20",
    "fyers-apiv",
    "upstox",
    "smartapi",
    "angel-one",
)

# Explicit read-only allowlist.  Empty by design: nothing here needs a trading
# SDK.  To allow a library that merely *names* one of the substrings for a
# read-only purpose, add it here with justification.
DEPENDENCY_ALLOWLIST: set[str] = set()


def _requirement_lines() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name in ("requirements.txt", "requirements-dev.txt"):
        p = REPO_ROOT / name
        if not p.exists():
            continue
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("-r"):
                continue
            out.append((name, line))
    return out


def test_no_broker_execution_sdk_in_requirements() -> None:
    violations: list[str] = []
    for fname, line in _requirement_lines():
        low = line.lower()
        for sdk in BROKER_EXECUTION_SDKS:
            if sdk in low and sdk not in DEPENDENCY_ALLOWLIST:
                violations.append(f"{fname}: {line!r} matches blocked SDK {sdk!r}")
    assert not violations, (
        "Broker/order-execution SDK found in Python requirements — the MVP is "
        "advisory-only and must not ship a trading SDK:\n" + "\n".join(violations)
    )


def test_no_broker_execution_sdk_in_frontend_package_json() -> None:
    pkg = REPO_ROOT / "frontend" / "package.json"
    if not pkg.exists():
        pytest.skip("no frontend/package.json")
    import json

    data = json.loads(pkg.read_text(encoding="utf-8"))
    deps: dict[str, str] = {}
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        deps.update(data.get(key, {}) or {})
    violations = [
        name
        for name in deps
        for sdk in BROKER_EXECUTION_SDKS
        if sdk in name.lower() and sdk not in DEPENDENCY_ALLOWLIST
    ]
    assert not violations, (
        "Broker/order-execution SDK found in frontend deps: " + ", ".join(violations)
    )
