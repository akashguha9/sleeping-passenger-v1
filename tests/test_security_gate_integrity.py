"""Adversarial regression tests for scripts/audit_security_gate_integrity.py.

Each test simulates a plausible future-agent mistake (the exact one-line
edits that would weaken the secret gate while CI stays green) against a
synthetic workflow tree in tmp_path, and proves the audit fails closed.
The real repo must pass the audit (trust closure for the current tree).
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from scripts import audit_security_gate_integrity as gate

# A minimal conforming workflow: mirrors the real secrets job shape and
# satisfies the pinning audit (SHA-pinned uses + version comments,
# read-only permissions, persist-credentials: false).
GOOD_WORKFLOW = textwrap.dedent(
    f"""\
    name: dep-audit
    on:
      push:
    permissions:
      contents: read
    jobs:
      secrets:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@{"a" * 40} # v4.3.1
            with:
              fetch-depth: 0
              persist-credentials: false
          - name: lint
            run: python3 scripts/secret_fixture_lint.py
          - name: install gitleaks
            run: |
              curl -sSfL -o /tmp/g.tar.gz https://github.com/gitleaks/releases/download/v{gate.PINNED_GITLEAKS_VERSION}/g.tar.gz
              echo "{gate.PINNED_GITLEAKS_SHA256}  /tmp/g.tar.gz" | sha256sum --check --strict -
          - name: tree scan
            run: |
              gitleaks detect --no-git --config=.gitleaks.toml --redact \\
                --exit-code=2 --report-path=/tmp/tree.sarif
          - name: commit scan
            run: |
              gitleaks detect --config=.gitleaks.toml --redact --exit-code=2 \\
                --report-format=sarif --report-path=results.sarif --log-opts=-1
          - name: upload
            uses: actions/upload-artifact@{"b" * 40} # v4.6.2
            with:
              path: results.sarif
    """
)


def _audit(tmp_path: Path, text: str, filename: str = "scan.yml") -> list[str]:
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / filename).write_text(text, encoding="utf-8")
    return gate.audit_workflows(wf_dir)


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------


def test_real_repo_passes_the_full_audit():
    assert gate.audit_all() == []


def test_good_synthetic_workflow_passes():
    assert _audit(Path(__import__("tempfile").mkdtemp()), GOOD_WORKFLOW) == []


# ---------------------------------------------------------------------------
# Adversarial bypasses — each must FAIL the audit
# ---------------------------------------------------------------------------


def test_continue_on_error_on_secrets_job_fails(tmp_path):
    bad = GOOD_WORKFLOW.replace(
        "    runs-on: ubuntu-latest",
        "    runs-on: ubuntu-latest\n    continue-on-error: true",
    )
    assert bad != GOOD_WORKFLOW
    violations = _audit(tmp_path, bad)
    assert any("continue-on-error" in v for v in violations), violations


def test_removing_no_git_tree_scan_fails(tmp_path):
    bad = GOOD_WORKFLOW.replace("--no-git ", "")
    violations = _audit(tmp_path, bad)
    assert any("--no-git" in v for v in violations), violations


def test_reintroducing_gitleaks_action_fails(tmp_path):
    bad = GOOD_WORKFLOW + textwrap.dedent(
        f"""\
          legacy:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@{"a" * 40} # v4.3.1
                with:
                  persist-credentials: false
              - uses: gitleaks/gitleaks-action@{"c" * 40} # v2
        """
    )
    violations = _audit(tmp_path, bad)
    assert any("gitleaks-action" in v for v in violations), violations


def test_unpinned_gitleaks_version_fails(tmp_path):
    bad = GOOD_WORKFLOW.replace(
        f"download/v{gate.PINNED_GITLEAKS_VERSION}/", "download/v99.0.0/"
    )
    violations = _audit(tmp_path, bad)
    assert any("99.0.0" in v for v in violations), violations


def test_dropping_checksum_verification_fails(tmp_path):
    bad = "\n".join(
        line for line in GOOD_WORKFLOW.splitlines()
        if "sha256sum" not in line
    )
    violations = _audit(tmp_path, bad)
    assert any("SHA-256" in v for v in violations), violations


def test_dropping_explicit_config_fails(tmp_path):
    bad = GOOD_WORKFLOW.replace("--config=.gitleaks.toml ", "", 1)
    violations = _audit(tmp_path, bad)
    assert any("--config=.gitleaks.toml" in v for v in violations), violations


def test_neutralized_exit_code_fails(tmp_path):
    bad = GOOD_WORKFLOW.replace("--exit-code=2", "--exit-code=0")
    violations = _audit(tmp_path, bad)
    assert any("--exit-code=0" in v for v in violations), violations


def test_removing_sarif_artifact_fails(tmp_path):
    bad = GOOD_WORKFLOW.split("      - name: upload")[0]
    assert bad != GOOD_WORKFLOW
    violations = _audit(tmp_path, bad)
    assert any("SARIF artifact" in v for v in violations), violations


def test_lint_step_after_gitleaks_fails(tmp_path):
    lint_step = "      - name: lint\n        run: python3 scripts/secret_fixture_lint.py\n"
    assert lint_step in GOOD_WORKFLOW
    moved = GOOD_WORKFLOW.replace(lint_step, "") + lint_step
    violations = _audit(tmp_path, moved)
    assert any("BEFORE gitleaks" in v for v in violations), violations


def test_shallow_fetch_depth_fails(tmp_path):
    bad = GOOD_WORKFLOW.replace("fetch-depth: 0", "fetch-depth: 1")
    violations = _audit(tmp_path, bad)
    assert any("fetch-depth" in v for v in violations), violations


def test_renamed_workflow_file_still_audited(tmp_path):
    # Renaming the file must not evade the audit: the pipeline is found
    # in any top-level workflow file, and absent everywhere it fails.
    assert _audit(tmp_path, GOOD_WORKFLOW, filename="totally-innocent.yml") == []


def test_workflow_moved_to_nested_dir_fails(tmp_path):
    # GitHub silently ignores nested files under .github/workflows — a
    # "moved" security workflow is a disabled security workflow.
    wf_dir = tmp_path / ".github" / "workflows"
    (wf_dir / "archive").mkdir(parents=True)
    (wf_dir / "archive" / "scan.yml").write_text(GOOD_WORKFLOW, encoding="utf-8")
    (wf_dir / "other.yml").write_text(
        textwrap.dedent(
            f"""\
            name: other
            on:
              push:
            permissions:
              contents: read
            jobs:
              build:
                runs-on: ubuntu-latest
                steps:
                  - uses: actions/checkout@{"a" * 40} # v4.3.1
                    with:
                      persist-credentials: false
            """
        ),
        encoding="utf-8",
    )
    violations = gate.audit_workflows(wf_dir)
    assert any("nested workflow" in v for v in violations), violations
    assert any("gitleaks" in v for v in violations), violations


def test_deleting_all_workflows_fails(tmp_path):
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    assert gate.audit_workflows(wf_dir) != []


# ---------------------------------------------------------------------------
# .gitleaks.toml policy
# ---------------------------------------------------------------------------


def test_current_gitleaks_config_passes():
    assert gate.audit_gitleaks_config() == []


def test_config_with_allowlist_fails(tmp_path):
    cfg = tmp_path / ".gitleaks.toml"
    cfg.write_text(
        '[extend]\nuseDefault = true\n\n[allowlist]\npaths = ["tests/"]\n',
        encoding="utf-8",
    )
    violations = gate.audit_gitleaks_config(cfg)
    assert any("allowlist" in v for v in violations), violations


def test_config_dropping_defaults_fails(tmp_path):
    cfg = tmp_path / ".gitleaks.toml"
    cfg.write_text("[extend]\nuseDefault = false\n", encoding="utf-8")
    violations = gate.audit_gitleaks_config(cfg)
    assert violations, violations


def test_missing_config_fails(tmp_path):
    assert gate.audit_gitleaks_config(tmp_path / ".gitleaks.toml") != []


def test_commented_allowlist_is_allowed(tmp_path):
    cfg = tmp_path / ".gitleaks.toml"
    cfg.write_text(
        "# never add an allowlist here\n[extend]\nuseDefault = true\n",
        encoding="utf-8",
    )
    assert gate.audit_gitleaks_config(cfg) == []


# ---------------------------------------------------------------------------
# .gitleaksignore policy — fingerprint-specific entries only
# ---------------------------------------------------------------------------


def test_broad_gitleaksignore_entry_fails(tmp_path):
    ignore = tmp_path / ".gitleaksignore"
    ignore.write_text("tests/*\n", encoding="utf-8")
    violations = gate.audit_gitleaksignore(ignore)
    assert any("fingerprint" in v for v in violations), violations


def test_fingerprint_specific_gitleaksignore_entry_passes(tmp_path):
    ignore = tmp_path / ".gitleaksignore"
    ignore.write_text(
        "# justified: synthetic fixture, see ledger\n"
        + "a" * 40 + ":tests/test_x.py:generic-api-key:12\n",
        encoding="utf-8",
    )
    assert gate.audit_gitleaksignore(ignore) == []


# ---------------------------------------------------------------------------
# Negative proof: a real-looking leak still fails the pinned scanner
# ---------------------------------------------------------------------------


def test_realistic_leak_still_fails_gitleaks(tmp_path):
    """End-to-end negative test: gitleaks (the pinned binary) exits non-zero
    on a realistic AWS-style key. Skipped where the binary is unavailable
    (e.g. the CI pytest job) — the dep-audit secrets job always has it.

    The leak value is assembled at runtime in a tmp dir OUTSIDE the repo,
    so neither the lint nor the tree scan ever sees it in tracked source.
    """
    import subprocess

    import pytest

    from scripts.audit_historical_secret_ledger import find_gitleaks
    from tests.helpers import scanner_probes as probes

    gitleaks = find_gitleaks()
    if gitleaks is None:
        pytest.skip("gitleaks binary not available in this environment")

    fake_key = probes.assemble("AK", "IA") + "JX7Q2P9R4TND5WB3"
    (tmp_path / "oops.py").write_text(
        f'AWS_DEPLOY = "{fake_key}"\n', encoding="utf-8"
    )
    config = Path(__file__).resolve().parents[1] / ".gitleaks.toml"
    proc = subprocess.run(
        [gitleaks, "detect", "--no-git", f"--config={config}", "--redact",
         "--exit-code=2", f"--source={tmp_path}"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
