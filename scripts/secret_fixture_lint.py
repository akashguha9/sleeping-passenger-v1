"""Secret-fixture hygiene lint — blocks scanner bait before gitleaks sees it.

Why this exists
---------------
CI runs gitleaks on every push (.github/workflows/dep_audit.yml). Its
``generic-api-key`` rule cannot tell a *synthetic* test fixture from a real
leak — and it must not, or it would stop catching real leaks. This repo has
repeatedly broken its own secret scan by committing realistic-looking fake
credentials next to words like ``api_key``/``token`` (e.g. a test claim
embedding an api-key assignment with a 16-char fake value — described
here, not quoted, because the literal would trip the scanners this lint
exists to keep quiet). The durable rule, documented in SECURITY.md and
CONTRIBUTING.md:

  Never commit a ``<keyword><operator><value>`` credential shape, even with
  a fake or REDACTED value. Tests that need secret-shaped strings assemble
  them at runtime via ``tests/helpers/scanner_probes.py``; everything else
  uses the approved sentinels below.

What it checks (per line, tracked text files only):

  1. a faithful port of gitleaks' ``generic-api-key`` rule (same keyword
     proximity, operators, value charset, and >= 3.5 Shannon entropy) so a
     change that would fail CI's secret scan fails HERE first, with a
     fix-it message instead of a scary leak report;
  2. ``REDACTED`` used as a credential value (scanners and human reviewers
     cannot tell a redacted-looking fixture from a half-scrubbed real
     leak, so it is forbidden outright);
  3. realistic token shapes (``sk-…``, ``xai-…``, ``ghp_…``, ``AKIA…``,
     Slack/JWT/private-key shapes) anywhere outside the approved probe
     helper, fake or not.

This lint runs locally (``python scripts/secret_fixture_lint.py``), as a
pytest guard (tests/test_secret_fixture_hygiene.py), via pre-commit, and as
a CI step *before* gitleaks. It is an early tripwire, NOT a replacement for
gitleaks: gitleaks still runs with its full default ruleset and still fails
the build on real leaks.

Stdlib only. Exit 0 = clean, exit 1 = violations found.
"""
from __future__ import annotations

import math
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Sentinels that are always allowed as values next to credential keywords:
# self-describing, no digits, low entropy — secret scanners ignore them too.
ALLOWED_SENTINELS = frozenset({
    "DUMMY_VALUE_FOR_TESTS_ONLY",
    "SENTINEL_VALUE_FOR_TESTS_ONLY",
    "PLACEHOLDER_VALUE_FOR_TESTS_ONLY",
    "NOT_A_SECRET_TEST_VALUE",
})

# The ONLY files allowed to contain probe machinery or this lint's own
# forbidden patterns. Keep this list short and justified:
#   * scanner_probes.py — the sanctioned runtime assembler for
#     secret-shaped test probes (fragments only, no whole shapes);
#   * this lint and its pytest wrapper — they must name the very
#     patterns they forbid.
ALLOWLISTED_FILES = frozenset({
    "scripts/secret_fixture_lint.py",
    "tests/helpers/scanner_probes.py",
    "tests/test_secret_fixture_hygiene.py",
})

# Tracked file extensions worth scanning (source, docs, config, CI).
SCAN_SUFFIXES = frozenset({
    ".py", ".md", ".txt", ".yml", ".yaml", ".toml", ".ini", ".cfg",
    ".json", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".sh",
    ".ps1", ".env", ".example",
})

# Machine-generated files where hash-like blobs are expected and benign.
SKIPPED_FILES = frozenset({
    "frontend/package-lock.json",
})

# --- rule 1: gitleaks generic-api-key, ported -------------------------------
# Same structure as gitleaks v8.24.3 (keyword within 0-20 chars of an
# operator, value of 10-150 [\w.=-] chars, closing delimiter, >= 3.5
# Shannon entropy). gitleaks additionally prunes with a large stopword
# allowlist; this port approximates that with shape checks in
# _generic_value_is_suspicious so ordinary identifiers don't alert.
_GENERIC_API_KEY_RE = re.compile(
    r"(?i)[\w.-]{0,50}?(?:access|auth|api[\w.-]*|credential|creds|key|"
    r"passw(?:or)?d|secret|token)(?:[\w.-]{0,20})?[\s'\"]{0,3}"
    r"(?:=|>|:{1,3}=|\|\||:|=>|\?=|,)[\x60'\"\s=]{0,5}"
    r"([\w.=-]{10,150}|[a-z0-9][a-z0-9+/]{11,}={0,3})"
    r"(?:[\x60'\"\s;]|\\[nr]|$)"
)
_GENERIC_ENTROPY_THRESHOLD = 3.5  # gitleaks' threshold for this rule


def _generic_value_is_suspicious(value: str) -> bool:
    """Shape checks standing in for gitleaks' stopword allowlist.

    Code identifiers routinely sit next to credential keywords
    (``score_key="…_v2_score"``); they are word chains with at most a
    version digit or two. Realistic fake secrets carry digit runs.
    """
    if value in ALLOWED_SENTINELS:
        return False
    if "." in value:  # attribute chain, e.g. process.env.X
        return False
    if re.fullmatch(r"[A-Z0-9_=]+", value):  # SCREAMING_CASE constant/env ref
        return False
    has_alpha = any(c.isalpha() for c in value)
    digits = sum(c.isdigit() for c in value)
    if not has_alpha or digits < 3:
        return False
    return shannon_entropy(value) >= _GENERIC_ENTROPY_THRESHOLD


# --- rule 2: REDACTED as a credential value ---------------------------------
# Case-sensitive on REDACTED: lowercase "<redacted>" is the output of
# legitimate redaction *code* (e.g. ``x.replace(key, "<redacted>")``);
# uppercase REDACTED beside a keyword is the forbidden fixture idiom.
_KEYWORDS = (
    r"(?:api[_-]?key|apikey|access[_-]?key|secret|token|passw(?:or)?d|"
    r"credential)"
)
_REDACTED_VALUE_RE = re.compile(
    r"(?i:" + _KEYWORDS
    + r"[\w.-]{0,20}[\"']?\s*(?:[:=]{1,3}|=>|,)\s*)[\"'(\[<{]*REDACTED"
)

# --- rule 3: realistic token shapes, anywhere -------------------------------
# Patterns spell out shapes only — none of these lines contain a match.
_TOKEN_SHAPE_RES = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),             # OpenAI-style
    re.compile(r"\bxai-[A-Za-z0-9_-]{8,}"),            # xAI-style
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),       # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),     # GitHub fine-grained
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),               # AWS access key id
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),     # Slack
    re.compile(r"eyJ[A-Za-z0-9_-]{17,}\.eyJ"),         # JWT pair
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def shannon_entropy(value: str) -> float:
    """Bits/char Shannon entropy — the same measure gitleaks uses."""
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    total = len(value)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def scan_text(text: str, rel_path: str) -> list[str]:
    """Return violations for one file's content (empty list = clean)."""
    violations: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _REDACTED_VALUE_RE.search(line):
            violations.append(
                f"{rel_path}:{lineno}: REDACTED used as a credential value — "
                "use an ALLOWED_SENTINELS value or assemble the probe at "
                "runtime via tests/helpers/scanner_probes.py"
            )
            continue
        shape = next(
            (p for p in _TOKEN_SHAPE_RES if p.search(line)), None
        )
        if shape is not None:
            violations.append(
                f"{rel_path}:{lineno}: realistic token shape "
                f"({shape.pattern!r}) — even fake ones read as leaks to "
                "scanners; assemble probes at runtime via "
                "tests/helpers/scanner_probes.py"
            )
            continue
        m = _GENERIC_API_KEY_RE.search(line)
        if m and _generic_value_is_suspicious(m.group(1)):
            violations.append(
                f"{rel_path}:{lineno}: would trip gitleaks generic-api-key "
                f"(credential keyword + high-entropy value "
                f"{m.group(1)!r}) — use an ALLOWED_SENTINELS value or "
                "tests/helpers/scanner_probes.py"
            )
    return violations


def _tracked_files(repo_root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def scan_repo(repo_root: Path = _REPO_ROOT) -> list[str]:
    violations: list[str] = []
    for rel in _tracked_files(repo_root):
        if rel in ALLOWLISTED_FILES or rel in SKIPPED_FILES:
            continue
        path = repo_root / rel
        if path.suffix.lower() not in SCAN_SUFFIXES and path.name != ".env.example":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable — gitleaks still covers it
        violations.extend(scan_text(text, rel))
    return violations


def main() -> int:
    violations = scan_repo()
    print(f"secret-fixture hygiene lint: {_REPO_ROOT}")
    if violations:
        print(f"FAIL — {len(violations)} scanner-bait fixture(s):")
        for v in violations:
            print(f"  - {v}")
        print(
            "Rule: never commit <keyword>=<value> credential shapes, even "
            "fake/REDACTED ones. See SECURITY.md (Secret fixture hygiene)."
        )
        return 1
    print("PASS — no scanner-bait fixtures in tracked files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
