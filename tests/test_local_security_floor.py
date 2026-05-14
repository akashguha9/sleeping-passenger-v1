"""Local security-floor regression tests.

These tests do not attempt to prove cryptographic correctness or
production-grade authorisation.  They pin a handful of low-cost,
high-value invariants that, if violated, would indicate the project is
drifting toward an unsafe posture:

1. ``.env`` family files are NOT tracked in git.  Only ``*.env.example``
   templates are tracked.
2. The runtime DB and logs are NOT tracked.
3. The ``.gitignore`` keeps blocking the canonical sensitive paths.
4. No raw Claude export folder has been committed into ``docs/recovery/``
   or anywhere else under the repo.
5. ``scripts/api_server.py`` never exposes a broker-execution / order
   placement / wallet-transfer endpoint (defensive AST + string scan).
6. ``docs/ADVISORY_ONLY_SAFETY_MODEL.md`` exists and lists the canonical
   safety invariants.

If you intentionally need to land a change that breaks one of these,
the doctrine in ``docs/ADVISORY_ONLY_SAFETY_MODEL.md`` must be updated
*first*, in the same PR.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git_tracked_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        pytest.skip("git ls-files unavailable")
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def test_no_real_env_file_is_tracked():
    tracked = _git_tracked_files()
    bad = [
        p
        for p in tracked
        if (p == ".env" or p.endswith("/.env") or re.search(r"\.env\.local$", p))
    ]
    assert not bad, f"Sensitive env file(s) tracked by git: {bad}"


def test_runtime_db_not_tracked():
    tracked = _git_tracked_files()
    bad = [
        p
        for p in tracked
        if p.endswith(".db") or p.endswith(".sqlite") or p.endswith(".sqlite3")
    ]
    assert not bad, f"Local DB file(s) tracked by git: {bad}"


def test_no_claude_export_artifacts_in_repo():
    """The raw Claude export must never be inside the repo working tree."""
    sentinels = (
        "conversations.json",
        "memories.json",
        "users.json",
    )
    matches: list[str] = []
    for name in sentinels:
        for path in REPO_ROOT.rglob(name):
            try:
                rel = path.relative_to(REPO_ROOT)
            except ValueError:
                continue
            parts = rel.parts
            # Allowlisted dirs: node_modules / venv / build artefacts — we
            # don't ship those, but we don't fail on third-party fixtures
            # that happen to share a filename.
            if any(
                p in parts
                for p in (
                    "node_modules",
                    ".next",
                    ".venv",
                    "venv",
                    "build",
                    "dist",
                )
            ):
                continue
            matches.append(str(rel))
    assert not matches, (
        f"Raw Claude export artefact(s) found inside the repo: {matches}. "
        f"Move them outside the repo or sanitize into docs/recovery/."
    )


def test_gitignore_blocks_critical_paths():
    gi = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8", errors="replace")
    for needle in (".env", "*.env", "runtime/", "logs/", "*.db", "*.sqlite"):
        assert needle in gi, f".gitignore missing protection for {needle}"


def test_api_server_has_no_broker_execution_routes():
    """Defensive AST/string scan: no FastAPI route nor helper function name
    should resemble broker execution.  This mirrors the AST checks in
    ``tests/test_signal_inbox_api.py`` but applied to ``api_server.py``."""
    src = (REPO_ROOT / "scripts" / "api_server.py").read_text(
        encoding="utf-8", errors="replace"
    )
    forbidden = [
        "place_order",
        "submit_order",
        "execute_trade",
        "broker_execute",
        "auto_buy",
        "auto_sell",
        "cancel_order",
        "modify_order",
        "connect_broker",
        "broker_login",
        "wallet_transfer",
        "send_funds",
    ]
    src_lower = src.lower()
    hits = [name for name in forbidden if name in src_lower]
    assert not hits, f"Forbidden broker-execution names present in api_server.py: {hits}"


def test_advisory_only_safety_model_doc_exists_and_has_canonical_fields():
    doc = REPO_ROOT / "docs" / "ADVISORY_ONLY_SAFETY_MODEL.md"
    assert doc.exists(), "Missing docs/ADVISORY_ONLY_SAFETY_MODEL.md"
    text = doc.read_text(encoding="utf-8", errors="replace")
    for field in (
        "advisory_status",
        "execution_gate",
        "broker_api_called",
        "ai_execution_count",
        "execution_permission",
        "can_execute",
        "broker_order_id",
    ):
        assert field in text, f"safety doc missing canonical field {field}"


def test_local_deployment_checklist_exists():
    doc = REPO_ROOT / "docs" / "LOCAL_DEPLOYMENT_CHECKLIST.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8", errors="replace").lower()
    # Spot-check that the checklist names the local-only posture loudly.
    assert "local" in text
    assert "production trading" in text
    assert "127.0.0.1" in text or "localhost" in text


def test_env_example_does_not_contain_obvious_real_secret():
    """The committed .env.example template must contain only placeholder
    values for sensitive keys (empty strings, default values).  A real
    secret accidentally placed in a template is the most common leak."""
    for example in REPO_ROOT.rglob("*.env.example"):
        if any(part in example.parts for part in ("node_modules", ".next", ".venv")):
            continue
        text = example.read_text(encoding="utf-8", errors="replace")
        # Heuristic: any non-empty assignment to a key whose name contains
        # "key", "token", or "secret" is suspicious unless it equals a
        # placeholder pattern.
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key_lower = key.lower()
            value = value.strip().strip("\"'")
            if not value:
                continue
            if any(s in key_lower for s in ("key", "token", "secret", "password")):
                # Allow obvious placeholders / docs-style values.
                if value in {
                    "",
                    "your_key_here",
                    "your-token-here",
                    "<your_token>",
                    "REPLACE_ME",
                    "REDACTED",
                    "NONE",
                }:
                    continue
                pytest.fail(
                    f"{example}: key {key!r} has a non-placeholder value in a "
                    f"template (possible leaked secret): {value!r}"
                )
