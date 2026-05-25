"""Repo-hygiene guard.

Proves that operator-private artefacts the b1db5cd / cleanup commits were
written to scrub from the working tree are *still* untracked and that the
ignore rules that block them from being re-staged remain in place.

This is a static, file-system-only test — no network, no DB, no execution.
It's intentionally tiny: every additional pattern we have to ignore lives
in ``.gitignore`` plus the explicit ``_PRIVATE_PATTERNS`` list below.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Patterns the cleanup commit (b8fdda7 "Clean Kalshi sprint commit scope")
# explicitly removed from history-going-forward.  These must never reappear
# in the tracked file list, and the gitignore rules that block them must
# stay in place.
_PRIVATE_PATTERNS: tuple[tuple[str, str], ...] = (
    # gitignore-glob-pattern, human-friendly label
    ("Prompt_*.txt", "operator-private LLM prompt drafts"),
    ("data/manual_trades_by_date.json", "operator-private manual trade log"),
)


def _git(*args: str) -> str:
    """Run a git command from the repo root and return stripped stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _is_git_repo() -> bool:
    return (REPO_ROOT / ".git").exists()


@pytest.mark.skipif(not _is_git_repo(), reason="not a git checkout")
def test_no_operator_private_files_tracked() -> None:
    """Each of the operator-private patterns must NOT appear in `git ls-files`.

    A failure here means somebody has accidentally re-introduced a file that
    the hardening sprint explicitly removed.  Fix by `git rm --cached` and
    re-running.
    """
    tracked = _git("ls-files").splitlines()
    offenders: list[str] = []
    for pattern, label in _PRIVATE_PATTERNS:
        # Translate a simple shell glob into a regex.  We deliberately avoid
        # fnmatch.fnmatch on every tracked file (slow on large trees) and
        # instead pre-compile a single regex per pattern.
        regex_src = re.escape(pattern).replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
        regex = re.compile(f"(^|/){regex_src}$")
        for path in tracked:
            if regex.search(path):
                offenders.append(f"{path}  [{label}]")
    assert offenders == [], (
        "Operator-private files are tracked — they must be removed:\n  - "
        + "\n  - ".join(offenders)
    )


@pytest.mark.skipif(not _is_git_repo(), reason="not a git checkout")
def test_gitignore_blocks_operator_private_patterns() -> None:
    """Every pattern in ``_PRIVATE_PATTERNS`` must be matched by .gitignore.

    We use ``git check-ignore`` so we exercise the SAME matcher git itself
    uses — case-insensitive matches, negated rules, and nested patterns are
    all handled correctly.
    """
    not_ignored: list[str] = []
    for pattern, label in _PRIVATE_PATTERNS:
        sample_path = pattern.replace("*", "draft")
        # `git check-ignore -q` exits 0 when the path is ignored, 1 when not.
        result = subprocess.run(
            ["git", "check-ignore", "-q", sample_path],
            cwd=str(REPO_ROOT),
            check=False,
        )
        if result.returncode != 0:
            not_ignored.append(f"{sample_path}  [{label}]")
    assert not_ignored == [], (
        ".gitignore does not block operator-private paths:\n  - "
        + "\n  - ".join(not_ignored)
    )


def test_private_patterns_listed_in_gitignore_text() -> None:
    """Belt-and-braces: each pattern is mentioned literally in .gitignore.

    Catches the case where a hook or git config monkey-patch makes
    ``check-ignore`` pass for the wrong reason.  This test is intentionally
    coarse (substring match) — exact-string-equality would make it brittle
    to comment edits.
    """
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8", errors="replace")
    missing: list[str] = []
    for pattern, _label in _PRIVATE_PATTERNS:
        if pattern not in gitignore:
            missing.append(pattern)
    assert missing == [], (
        f"Patterns missing from .gitignore: {missing}. Add them under the "
        "'LOCAL OPERATOR-PRIVATE FILES' section."
    )
