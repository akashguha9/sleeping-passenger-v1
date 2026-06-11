"""Advisory-only hard boundary — machine proof that nothing places trades.

The product promise is structural, not aspirational: this system is
advisory-only. It does not place trades, route orders, custody assets, or
connect to broker execution APIs. Several gates already defend pieces of
that promise (architecture_fitness blocks broker SDK imports,
repo_hygiene_gate blocks broker-named files, the frontend language tests
block execution wording). This audit closes the remaining gap with
content-level checks across the whole tracked tree and fails CI when any
of these appear in CODE (not docs, not guard lists, not tests):

  * broker SDK imports (alpaca / ib_insync / ibapi / ccxt / oanda / …);
  * order-placement call shapes (place_order(, submit_order(,
    create_market_order(, order.submit(…), …);
  * execution-semantic HTTP routes (/execute, /orders/place, /buy, /sell);
  * live-trading-loop / auto-execute constructs;
  * portfolio-rebalancing *execution* (scoring/suggesting is fine);
  * webhook calls to broker execution domains.

False-positive policy (test-pinned in tests/test_advisory_only_boundary.py):

  * documentation may say "no broker execution" — negated/denial lines and
    Markdown files never count;
  * guard scripts that *detect* these tokens declare themselves in
    GUARD_FILES below (the tokens appear there as detection patterns);
  * test files are exempt (they hold banlists and runtime-assembled
    probes); the adversarial tests prove real execution code still fails;
  * paper simulation and the manual trade *journal* (records of trades a
    human already made elsewhere) are allowed and reported separately.

A disclaimer audit additionally requires README.md and SECURITY.md to
carry the advisory-only statement — but a disclaimer can never substitute
for the code scan: both run unconditionally.

Stdlib only:  python scripts/audit_advisory_only_boundary.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Files whose JOB is to name forbidden tokens (detection lists/regexes).
# Keep this list short, reviewed, and justified — adding an entry here is
# a security review event, not a convenience.
GUARD_FILES = frozenset({
    "scripts/audit_advisory_only_boundary.py",   # this audit
    "scripts/architecture_fitness.py",            # broker-import fitness gate
    "scripts/repo_hygiene_gate.py",               # broker-filename gate
    "scripts/config_contract.py",                 # rejects broker env keys
    "scripts/compliance_preflight.py",            # compliance wording checks
    "scripts/private_scope_guard.py",             # scope classification lists
    "scripts/release_gate.py",                    # release gate wording checks
    "scripts/local_mvp_audit.py",                 # local no-execution audit
    "scripts/advisory_contract.py",               # shared forbidden-token list
    "scripts/dead_diagnostic_audit.py",           # broker-call-pattern audit
    "scripts/phase_c_final_audit.py",             # forbidden-route audit
    "configs/no_execution_policy.yaml",           # loader no-execution policy
})

_CODE_SUFFIXES = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".sh", ".ps1",
    ".yml", ".yaml",
})

_NEGATORS = (
    " no ", " not ", "never", "must not", "doesn't", "does not", "without",
    "forbidden", "refuse", "refused", "refusing", "blocked", "blocks",
    "rejects", "reject", "none", "absent", "instead of", "rather than",
)

# (category, compiled pattern). Patterns target SHAPES of execution code,
# not vocabulary: journaling a manual trade or scoring a signal never
# matches; calling a broker does.
_EXECUTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("broker_sdk_import", re.compile(
        r"(?:^|\s)(?:import|from)\s+"
        r"(?:alpaca\w*|ib_insync|ibapi|ccxt|oandapyV20|robin_stocks|"
        r"kiteconnect|tradier\w*)\b"
    )),
    ("order_call", re.compile(
        r"\b(?:place|submit|send|create)_(?:market_|limit_|bracket_)?"
        r"order[s]?\s*\("
    )),
    ("order_method_call", re.compile(
        r"\border[s]?\.(?:submit|place|execute|send)\s*\("
    )),
    ("execution_route", re.compile(
        r"""["'](?:/api)?/(?:execute|orders?/(?:place|submit|new|create)|"""
        r"""buy|sell|trade/execute|rebalance/execute)["']"""
    )),
    ("live_trading_loop", re.compile(
        # no \b before "live": underscores are word chars, and
        # run_live_trading_loop must still match.
        r"(?i)live[\s_-]?trading[\s_-]?loop|\bauto[\s_-]?execute\b|"
        r"\bautoexecut\w+\b"
    )),
    ("rebalancing_execution", re.compile(
        r"(?i)\brebalanc\w+[\s_-]?(?:execution|executor|order)\b"
    )),
    ("broker_webhook", re.compile(
        r"(?i)https?://[\w.-]*(?:alpaca\.markets|interactivebrokers|"
        r"ibkr|tradier|oanda)\.?[\w.-]*/"
    )),
)

_REQUIRED_DISCLAIMER = (
    "advisory-only. It does not place trades, route orders, custody "
    "assets, or connect to broker execution APIs"
)


def _is_exempt(rel_path: str) -> bool:
    if rel_path in GUARD_FILES:
        return True
    if rel_path.startswith(("tests/", "archived_experimental/")):
        return True
    name = Path(rel_path).name
    return ".spec." in name or ".test." in name or name.startswith("test_")


def _line_is_denial(line: str) -> bool:
    """Comment/doc lines that *deny* execution are the product promise."""
    stripped = line.strip()
    is_comment = stripped.startswith(("#", "//", "*", "/*", "<!--", "-", ">"))
    lowered = f" {stripped.lower()} "
    return is_comment and any(neg in lowered for neg in _NEGATORS)


def scan_text(text: str, rel_path: str) -> list[str]:
    """Return execution-boundary violations for one file's content."""
    if _is_exempt(rel_path) or Path(rel_path).suffix.lower() not in _CODE_SUFFIXES:
        return []
    violations: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _line_is_denial(line):
            continue
        for category, pattern in _EXECUTION_PATTERNS:
            if pattern.search(line):
                violations.append(
                    f"{rel_path}:{lineno}: {category} — execution-shaped "
                    f"construct in an advisory-only repo"
                )
                break
    return violations


def _tracked_files(repo_root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=repo_root,
        capture_output=True, text=True, check=True,
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def classify_paper_simulation(tracked: list[str]) -> list[str]:
    """Paper simulation is ALLOWED; reported separately for transparency."""
    return sorted(
        p for p in tracked
        if Path(p).suffix == ".py" and "paper_" in Path(p).name
    )


def audit_disclaimers(repo_root: Path = _REPO_ROOT) -> list[str]:
    """README + SECURITY must carry the exact advisory-only statement."""
    violations = []
    for doc in ("README.md", "SECURITY.md"):
        path = repo_root / doc
        if not path.exists() or _REQUIRED_DISCLAIMER not in path.read_text(
            encoding="utf-8"
        ):
            violations.append(
                f"{doc}: missing the advisory-only disclaimer statement"
            )
    return violations


def scan_repo(repo_root: Path = _REPO_ROOT) -> list[str]:
    violations: list[str] = []
    for rel in _tracked_files(repo_root):
        path = repo_root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        violations.extend(scan_text(text, rel))
    return violations


def main() -> int:
    tracked = _tracked_files(_REPO_ROOT)
    code_violations = scan_repo()
    disclaimer_violations = audit_disclaimers()
    paper = classify_paper_simulation(tracked)

    print(f"advisory-only boundary audit: {_REPO_ROOT}")
    print(f"  paper-simulation modules (allowed, advisory/paper-safe): "
          f"{len(paper)}")
    violations = code_violations + disclaimer_violations
    if violations:
        print(f"FAIL — {len(violations)} violation(s):")
        for v in violations:
            print(f"  - {v}")
        print(
            "This repo is advisory-only by contract. Execution-shaped code "
            "is forbidden; a documentation disclaimer alone never satisfies "
            "this audit."
        )
        return 1
    print(
        "PASS — no broker SDKs, order calls, execution routes, trading "
        "loops, or broker webhooks in code; advisory-only disclaimers "
        "present in README.md and SECURITY.md."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
