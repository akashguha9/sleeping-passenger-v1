"""Sprint 3 proofs — container & supply chain (S4, S10, S6, D3).

These are textual proofs (Dockerfile / CI YAML inspection) plus a runtime
check that ``_safe_exc_summary`` never returns identifying detail.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# S4 — non-root containers, prod-only deps, no dangling adapters
# ---------------------------------------------------------------------------


def test_s4_backend_runs_as_non_root():
    df = Path("Dockerfile.backend").read_text()
    assert "USER app" in df, "S4 regression: backend missing USER directive"
    assert "useradd" in df, "S4 regression: backend missing user creation"


def test_s4_backend_does_not_ship_dev_deps():
    """Inspect non-comment lines only.  References inside a comment are
    documentation, not behaviour."""
    code_lines = [
        ln
        for ln in Path("Dockerfile.backend").read_text().splitlines()
        if not ln.lstrip().startswith("#")
    ]
    blob = "\n".join(code_lines)
    assert "requirements-dev.txt" not in blob, (
        "S4 regression: dev deps shipping to runtime image"
    )


def test_s4_backend_no_dangling_adapters_copy():
    df = Path("Dockerfile.backend").read_text()
    assert "COPY adapters" not in df, (
        "S4 regression: dangling COPY adapters re-introduced"
    )


def test_s4_frontend_runs_as_node_user():
    df = Path("Dockerfile.frontend").read_text()
    assert "USER node" in df, "S4 regression: frontend missing USER directive"


def test_s4_compose_binds_loopback_by_default():
    yml = Path("docker-compose.yml").read_text()
    assert '"${HOST_BIND:-127.0.0.1}:8000:8000"' in yml
    assert '"${HOST_BIND:-127.0.0.1}:3000:3000"' in yml


# ---------------------------------------------------------------------------
# S10 — CI runs dependency audits
# ---------------------------------------------------------------------------


def test_s10_ci_has_pip_audit_and_npm_audit():
    yml = Path(".github/workflows/dep_audit.yml").read_text()
    assert "pip-audit" in yml
    assert "npm audit" in yml
    assert "--audit-level=high" in yml


def test_s10_ci_runs_on_push_and_schedule():
    yml = Path(".github/workflows/dep_audit.yml").read_text()
    assert "push:" in yml
    assert "pull_request" in yml
    assert "schedule:" in yml


# ---------------------------------------------------------------------------
# S6 — exception detail no longer leaked
# ---------------------------------------------------------------------------


def test_s6_safe_exc_summary_returns_type_only():
    from scripts.api_server import _safe_exc_summary

    try:
        raise FileNotFoundError("/etc/secret/very-revealing-path")
    except Exception as exc:
        out = _safe_exc_summary(exc)
    assert out == "FileNotFoundError"
    assert "/etc/secret" not in out
    assert "very-revealing-path" not in out


def test_s6_no_str_exc_in_route_responses():
    src = Path("scripts/api_server.py").read_text()
    # Per-route handlers used to embed raw exception text into the JSON
    # response.  The remaining str(exc) usages are pydantic re-raises
    # (validators) and the source-health summary's own sanitiser path —
    # both intentionally kept.  Assert that the per-route response leak
    # pattern is gone.
    assert "'error': str(exc)" not in src
    assert '"error": str(exc)' not in src


# ---------------------------------------------------------------------------
# D3 — secret-scan tooling wired
# ---------------------------------------------------------------------------


def test_d3_precommit_has_gitleaks():
    cfg = Path(".pre-commit-config.yaml").read_text()
    assert "gitleaks" in cfg
    assert "detect-private-key" in cfg


def test_d3_ci_runs_gitleaks():
    yml = Path(".github/workflows/dep_audit.yml").read_text()
    assert "gitleaks" in yml.lower()


def test_d3_gitignore_blocks_env_files():
    gi = Path(".gitignore").read_text()
    assert ".env" in gi
    assert "*.env" in gi
