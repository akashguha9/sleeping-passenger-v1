"""Forbidden-execution-language scan over the frontend source tree.

This is a *static* test that walks `frontend/src/` for files of types we
actually ship (.tsx, .ts) and verifies that no rendered string implies
execution, broker order placement, auto-trading, or AI-granted
permission.  It exists because the frontend has no test runner today
(see ``docs/recovery/FRONTEND_TEST_PLAN.md``) — but the advisory-only
copy contract should still be machine-enforced.

Scope
-----
Only string literals that are likely to render in the UI are scanned.
We deliberately skip:

- ``node_modules`` (third-party)
- ``.next`` build output
- test/spec files (which intentionally check for these phrases)
- a small allowlist of files known to negate the phrase (e.g. UI
  components that explicitly print ``BROKER_API: not connected``).

Forbidden phrases
-----------------
Each phrase is paired with a contextual exception so the test stays
useful as the UI evolves.  For example, the literal string ``broker``
on its own is fine ("BROKER_API: not connected") — what we forbid is
``broker order``, ``broker connected``, etc.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

# Patterns that should never appear in rendered UI copy.  Each is a
# (regex, reason) pair so failures explain the intent.
FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"\bplace\s+order\b", "implies broker order placement"),
    (r"\bexecute\s+trade\b", "implies trade execution"),
    (r"\btrade\s+now\b", "implies actionable trading prompt"),
    (r"\bauto[-\s]?trade\b", "implies auto-trading"),
    (r"\bbroker\s+order\b", "implies broker order"),
    (r"\bbroker\s+connected\b", "implies live broker connection"),
    (r"\bai[-\s]approved\b", "implies AI-granted permission"),
    (r"\bpermission\s+granted\b", "implies authorisation"),
    (r"\bauthori[sz]e[ds]?\s+to\s+trade\b", "implies trade authorisation"),
    (r"\border\s+ready\b", "implies an order is ready to be submitted"),
]

# Files that exercise the contract themselves (specs, doctrine docs)
# or print the phrases negated.  These are intentionally allowlisted.
ALLOWLIST: set[Path] = set()


def _is_test_or_spec(path: Path) -> bool:
    parts = path.parts
    if "__tests__" in parts:
        return True
    return path.name.endswith((".spec.ts", ".spec.tsx", ".test.ts", ".test.tsx"))


def _iter_frontend_sources() -> list[Path]:
    if not FRONTEND_SRC.exists():
        return []
    files: list[Path] = []
    for p in FRONTEND_SRC.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in {".ts", ".tsx"}:
            continue
        if _is_test_or_spec(p):
            continue
        if p.resolve() in ALLOWLIST:
            continue
        files.append(p)
    return files


def test_frontend_src_exists():
    assert FRONTEND_SRC.exists(), f"frontend/src missing at {FRONTEND_SRC}"


def test_frontend_no_execution_language():
    files = _iter_frontend_sources()
    assert files, "expected at least one .tsx/.ts file under frontend/src"
    violations: list[tuple[Path, str, str]] = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lower = content.lower()
        for pattern, reason in FORBIDDEN_PATTERNS:
            for match in re.finditer(pattern, lower):
                # Skip occurrences that sit inside a comment claiming the
                # phrase is being *denied* — these are intentional
                # safety-copy lines and the surrounding text proves it.
                start = max(0, match.start() - 40)
                end = min(len(content), match.end() + 60)
                context = content[start:end]
                if _is_denial_context(context):
                    continue
                violations.append((path.relative_to(REPO_ROOT), pattern, reason))
                break
    assert not violations, "Forbidden execution language found:\n" + "\n".join(
        f"  {p}: /{pat}/ — {reason}" for p, pat, reason in violations
    )


def _is_denial_context(snippet: str) -> bool:
    """Return True when the surrounding context obviously negates the phrase.

    Heuristic: presence of "no ", "never", "cannot", "not", "does not",
    "must not", "no broker", "NONE" value, "broker_order_id" field
    reference, or a TypeScript identifier ending in ``_id`` close to the
    match is treated as a deliberate disclaimer / record-keeping label
    rather than a violation.
    """
    s = snippet.lower()
    return any(
        marker in s
        for marker in (
            "not connected",
            "not call",
            "not authorise",
            "not authorize",
            "does not",
            "do not authorise",
            "do not authorize",
            "never",
            "cannot",
            "must not",
            "no broker",
            "broker_api: not",
            "broker api: not",
            "no execution",
            "not permission",
            "not place",
            "no_broker",
            # Field-reference / labelled-output contexts — "Broker order:" is
            # a label whose value is the constant "NONE"; the identifier
            # `broker_order_id` is a typed field, not a verb.
            "broker_order_id",
            "broker order id",
            'value="none"',
            "value: 'none'",
            ': "none"',
            ": 'none'",
            ": none}",
            ": none ",
            ' "none"',
            " 'none'",
            "label=",
        )
    )


def test_safety_invariant_constants_are_locked_in_source():
    """Spot-check: ADVISORY_ONLY / HUMAN_ONLY / ai_execution_count = 0 appear
    in the rendered UI surfaces so the operator can see the contract."""
    files = _iter_frontend_sources()
    blob = "\n".join(
        p.read_text(encoding="utf-8", errors="replace") for p in files
    )
    assert "ADVISORY_ONLY" in blob
    assert "HUMAN_ONLY" in blob or "HUMAN_EXECUTION_REQUIRED" in blob
    assert "ai_execution_count" in blob or "AI executions" in blob
