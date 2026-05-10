"""
Phase C Final Integration Audit — static checks only.

Verifies that all Phase 1 + Phase 2 sources are consistently wired across
the runner modules, CLI scripts, API server, frontend types, frontend UI,
and README documentation.

Rules
-----
- No internet required.
- No API keys required.
- No DB mutations.
- Reads source files only; never executes them.
- Prints a clear PASS / FAIL summary with one line per check.

Usage
-----
  python scripts/phase_c_final_audit.py
  python scripts/phase_c_final_audit.py --verbose
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

_REPO = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Expected source registry
# ---------------------------------------------------------------------------

PHASE1_SOURCES = ["polymarket", "gdelt", "sec_edgar"]
PHASE2_SOURCES = [
    "newsapi",
    "event_registry",
    "etherscan",
    "grok_xai",
    "market_data",
    "india",
    "global_filings",
    "asia_disclosure",
]
ALL_SOURCES = PHASE1_SOURCES + PHASE2_SOURCES

# ---------------------------------------------------------------------------
# Key file paths
# ---------------------------------------------------------------------------

_RUNNER1 = _REPO / "scripts" / "live_source_runner.py"
_RUNNER2 = _REPO / "scripts" / "live_source_runner_phase2.py"
_CLI1 = _REPO / "scripts" / "run_live_sources_phase1.py"
_CLI2 = _REPO / "scripts" / "run_live_sources_phase2.py"
_API = _REPO / "scripts" / "api_server.py"
_TS_TYPES = _REPO / "frontend" / "src" / "types" / "index.ts"
_UI_PAGE = _REPO / "frontend" / "src" / "app" / "live-signals" / "page.tsx"
_README = _REPO / "README.md"

# ---------------------------------------------------------------------------
# Forbidden execution patterns
# ---------------------------------------------------------------------------

# Route-level: must NOT appear as FastAPI route decorator args in api_server.py
_FORBIDDEN_ROUTE_PATTERNS = [
    r'"/buy"',
    r'"/sell"',
    r'"/trade"',
    r'"/execute"',
    r'"/orders"',
    r'"/place-order"',
    r'"/broker/order"',
    r'"/wallet/sign"',
    r'"/transaction/broadcast"',
]

# Source-level: must NOT appear in the runner/persistence/API files
_FORBIDDEN_EXEC_PATTERNS = [
    r"private_key\s*=",
    r"wallet\.sign\b",
    r"send_transaction\(",
    r"place_order\(",
    r"submit_order\(",
    r"broker_api_called\s*=\s*True",
]

# Frontend forbidden button labels
_FORBIDDEN_UI_LABELS = ["Buy", "Sell", "Execute", "Auto-trade", "Place Order",
                        "Send Transaction", "Sign Transaction"]

# Frontend allowed label substrings (these are fine even if they partially match)
_ALLOWED_UI_SUBSTRINGS = ["Log Manual Trade", "Human Review", "Advisory Only",
                           "Execution Locked", "Watchlist", "Request Evidence",
                           "Mark Noise"]

# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


class CheckResult(NamedTuple):
    name: str
    passed: bool
    detail: str


_results: list[CheckResult] = []


def _check(name: str, passed: bool, detail: str = "") -> bool:
    _results.append(CheckResult(name, passed, detail))
    return passed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _file_exists(path: Path, label: str) -> bool:
    return _check(f"file_exists:{label}", path.exists(), str(path))


# ---------------------------------------------------------------------------
# 1. File existence
# ---------------------------------------------------------------------------


def check_files_exist() -> None:
    for path, label in [
        (_RUNNER1, "live_source_runner.py"),
        (_RUNNER2, "live_source_runner_phase2.py"),
        (_CLI1, "run_live_sources_phase1.py"),
        (_CLI2, "run_live_sources_phase2.py"),
        (_API, "api_server.py"),
        (_TS_TYPES, "frontend/types/index.ts"),
        (_UI_PAGE, "frontend/live-signals/page.tsx"),
        (_README, "README.md"),
    ]:
        _file_exists(path, label)


# ---------------------------------------------------------------------------
# 2. Source registry coverage
# ---------------------------------------------------------------------------


def check_source_registry() -> None:
    r1 = _read(_RUNNER1)
    r2 = _read(_RUNNER2)
    cli1 = _read(_CLI1)
    cli2 = _read(_CLI2)
    ts = _read(_TS_TYPES)
    ui = _read(_UI_PAGE)
    readme = _read(_README)

    # Phase 1 runner
    for src in PHASE1_SOURCES:
        _check(
            f"runner1:source:{src}",
            f'"{src}"' in r1 or f"'{src}'" in r1,
            f"Expected '{src}' in live_source_runner.py",
        )

    # Phase 2 runner
    for src in PHASE2_SOURCES:
        _check(
            f"runner2:source:{src}",
            f'"{src}"' in r2 or f"'{src}'" in r2,
            f"Expected '{src}' in live_source_runner_phase2.py",
        )

    # Phase 1 CLI choices
    for src in PHASE1_SOURCES:
        _check(
            f"cli1:source:{src}",
            src in cli1,
            f"Expected '{src}' referenced in run_live_sources_phase1.py",
        )

    # Phase 2 CLI choices
    for src in PHASE2_SOURCES:
        _check(
            f"cli2:source:{src}",
            src in cli2,
            f"Expected '{src}' referenced in run_live_sources_phase2.py",
        )

    # TypeScript LiveSignalSource union
    for src in ALL_SOURCES:
        _check(
            f"ts_type:LiveSignalSource:{src}",
            f"'{src}'" in ts or f'"{src}"' in ts,
            f"Expected '{src}' in LiveSignalSource type in index.ts",
        )

    # Frontend SOURCE_OPTIONS
    for src in ALL_SOURCES:
        _check(
            f"ui:SOURCE_OPTIONS:{src}",
            f"'{src}'" in ui or f'"{src}"' in ui,
            f"Expected '{src}' in SOURCE_OPTIONS in live-signals/page.tsx",
        )

    # README mentions all sources
    for src in ALL_SOURCES:
        _check(
            f"readme:mentions:{src}",
            src in readme,
            f"Expected '{src}' mentioned in README.md",
        )


# ---------------------------------------------------------------------------
# 3. Safety invariants in runner modules
# ---------------------------------------------------------------------------


def check_safety_invariants() -> None:
    r1 = _read(_RUNNER1)
    r2 = _read(_RUNNER2)

    for label, content in [("runner1", r1), ("runner2", r2)]:
        _check(
            f"{label}:advisory_status=ADVISORY_ONLY",
            'ADVISORY_ONLY"' in content or "_ADVISORY_STATUS" in content,
            f"advisory_status=ADVISORY_ONLY constant missing in {label}",
        )
        _check(
            f"{label}:execution_gate=LOCKED",
            '"LOCKED"' in content or "_EXECUTION_GATE" in content,
            f"execution_gate=LOCKED constant missing in {label}",
        )
        _check(
            f"{label}:ai_execution_count=0",
            "_AI_EXECUTION_COUNT = 0" in content,
            f"_AI_EXECUTION_COUNT=0 constant missing in {label}",
        )
        _check(
            f"{label}:human_review_required=True",
            "human_review_required" in content and "True" in content,
            f"human_review_required=True missing in {label}",
        )

    # Phase 2 runner also carries broker fields
    _check(
        "runner2:broker_api_called=False",
        "_BROKER_API_CALLED = False" in r2,
        "_BROKER_API_CALLED=False constant missing in live_source_runner_phase2.py",
    )
    _check(
        "runner2:broker_order_id=NONE",
        '"NONE"' in r2 or "broker_order_id" in r2,
        "broker_order_id=NONE pattern missing in live_source_runner_phase2.py",
    )


# ---------------------------------------------------------------------------
# 4. Forbidden execution patterns in runtime files
# ---------------------------------------------------------------------------


def check_forbidden_patterns() -> None:
    # Forbidden route patterns in API server
    api_content = _read(_API)
    for pattern in _FORBIDDEN_ROUTE_PATTERNS:
        raw = pattern.strip('"').strip("'")
        found = bool(re.search(pattern, api_content))
        _check(
            f"api:no_forbidden_route:{raw}",
            not found,
            f"Forbidden route pattern {raw!r} found in api_server.py",
        )

    # Forbidden execution patterns in all key Python files
    python_files = [_RUNNER1, _RUNNER2, _CLI1, _CLI2, _API]
    for fpath in python_files:
        content = _read(fpath)
        for pattern in _FORBIDDEN_EXEC_PATTERNS:
            found = bool(re.search(pattern, content))
            _check(
                f"exec_pattern:absent:{fpath.name}:{pattern[:30]}",
                not found,
                f"Forbidden exec pattern {pattern!r} found in {fpath.name}",
            )


# ---------------------------------------------------------------------------
# 5. Frontend safety
# ---------------------------------------------------------------------------


def check_frontend_safety() -> None:
    ui = _read(_UI_PAGE)

    # Forbidden UI labels: check button text (inside JSX)
    # Scan for button/anchor labels that would imply execution
    for label in _FORBIDDEN_UI_LABELS:
        # Look for the label in JSX text nodes / aria labels / title attrs
        # Simple heuristic: label must not appear as a standalone word between tags or in strings
        pattern = rf">{re.escape(label)}<|['\"]{{label}}['\"]|={re.escape(label)}"
        found = bool(re.search(rf"[>\"']{re.escape(label)}[<\"']", ui))
        _check(
            f"frontend:no_forbidden_label:{label}",
            not found,
            f"Forbidden UI label '{label}' found in live-signals/page.tsx",
        )

    # Required source filter values
    for src in ALL_SOURCES:
        _check(
            f"frontend:source_value:{src}",
            f"'{src}'" in ui or f'"{src}"' in ui,
            f"Source value '{src}' missing from live-signals/page.tsx",
        )

    # TypeScript type completeness
    ts = _read(_TS_TYPES)
    for src in ALL_SOURCES:
        _check(
            f"frontend:ts_type:{src}",
            f"'{src}'" in ts or f'"{src}"' in ts,
            f"Source '{src}' missing from LiveSignalSource in index.ts",
        )


# ---------------------------------------------------------------------------
# 6. API audit
# ---------------------------------------------------------------------------


def check_api() -> None:
    api = _read(_API)

    required_routes = [
        ('GET /live-signals', r'@app\.get\("/live-signals"\)'),
        ('GET /source-health', r'@app\.get\("/source-health"\)'),
        ('GET /db/status', r'@app\.get\("/db/status"\)'),
        ('GET /health', r'@app\.get\("/health"\)'),
    ]
    for label, pattern in required_routes:
        _check(
            f"api:route_exists:{label}",
            bool(re.search(pattern, api)),
            f"Required route {label} missing from api_server.py",
        )

    # source filtering via ?source=
    _check(
        "api:live_signals_source_filter",
        "source_name=source" in api or "source_name = source" in api,
        "GET /live-signals does not pass source param to persistence layer",
    )


# ---------------------------------------------------------------------------
# 7. README source matrix
# ---------------------------------------------------------------------------


def check_readme_matrix() -> None:
    readme = _read(_README)

    _check(
        "readme:phase_c_matrix_section",
        "Phase C Integrated Source Matrix" in readme,
        "README is missing the 'Phase C Integrated Source Matrix' section",
    )

    for src in ALL_SOURCES:
        _check(
            f"readme:matrix:mentions:{src}",
            src in readme,
            f"Source '{src}' not mentioned in README",
        )

    _check(
        "readme:advisory_safety_rules",
        "Advisory safety rules" in readme or "advisory safety rules" in readme,
        "README is missing the advisory safety rules section",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_audit(verbose: bool = False) -> int:
    check_files_exist()
    check_source_registry()
    check_safety_invariants()
    check_forbidden_patterns()
    check_frontend_safety()
    check_api()
    check_readme_matrix()

    passed = [r for r in _results if r.passed]
    failed = [r for r in _results if not r.passed]

    if verbose or failed:
        for r in _results:
            icon = "PASS" if r.passed else "FAIL"
            detail = f"  → {r.detail}" if r.detail and not r.passed else ""
            print(f"  [{icon}] {r.name}{detail}")
        print()

    total = len(_results)
    print(f"Phase C Final Integration Audit: {len(passed)}/{total} checks passed")
    if failed:
        print(f"FAILED ({len(failed)} checks):")
        for r in failed:
            print(f"  ✗ {r.name}")
            if r.detail:
                print(f"      {r.detail}")
        return 1
    print("ALL CHECKS PASSED — advisory-only MVP stack is fully integrated.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase C Final Integration Audit — static checks, no internet, no DB."
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print all check results, not just failures.",
    )
    args = parser.parse_args()
    return run_audit(verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
