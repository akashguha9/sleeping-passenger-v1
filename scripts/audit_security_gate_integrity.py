"""Security-gate self-audit — the gates themselves must not silently drift.

The repo's secret-scanning posture is a *pipeline*, not a single tool:

    secret_fixture_lint  →  gitleaks full-tree (--no-git)  →  gitleaks
    (early bait guard)      (defense in depth)                commit scan
                                                              (--log-opts=-1)

all driven by a checksum-pinned gitleaks CLI with an explicit
``--config=.gitleaks.toml`` that only extends the default ruleset.  Any of
a dozen one-line edits (a removed flag, a ``continue-on-error: true``, a
re-introduced ``gitleaks/gitleaks-action``, a broad allowlist in the
config, a workflow file quietly moved into a subdirectory GitHub never
reads) would weaken the gate while CI stays green.  This audit makes those
edits loud: it inspects every workflow file plus ``.gitleaks.toml`` /
``.gitleaksignore`` / ``.gitignore`` and exits 1 on the first regression.

Wired into pytest (tests/test_security_gate_integrity.py), the kante
defensive gate, and the dep-audit policy job, so a drift fails three
independent CI surfaces.

Stdlib only:  python scripts/audit_security_gate_integrity.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"

try:
    from scripts import audit_github_actions_pinning as _pinning
except ModuleNotFoundError:  # pragma: no cover - script-style invocation
    sys.path.insert(0, str(_REPO_ROOT))
    from scripts import audit_github_actions_pinning as _pinning

# The one pinned gitleaks the repo trusts. Bump BOTH together (the new
# checksum comes from the upstream release's checksums file) — the audit
# fails if a workflow downloads any other version or skips verification.
PINNED_GITLEAKS_VERSION = "8.24.3"
PINNED_GITLEAKS_SHA256 = (
    "9991e0b2903da4c8f6122b5c3186448b927a5da4deef1fe45271c3793f4ee29c"
)

_SECURITY_KEYWORDS = ("gitleaks", "secret_fixture_lint", "audit_")

_DOWNLOAD_RE = re.compile(
    r"gitleaks/releases/download/v(?P<version>[0-9][\w.]*)/"
)
def _code_only(text: str) -> str:
    """Drop YAML comment lines so prose can neither trip nor satisfy checks.

    (e.g. the workflow's own comment explaining WHY gitleaks-action was
    removed must not count as using it — and a comment that merely
    *mentions* secret_fixture_lint.py must not satisfy the lint-step check.)
    """
    return "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith("#")
    )


def _flatten_detect_invocations(text: str) -> list[str]:
    """Return each ``gitleaks detect`` invocation with line continuations joined."""
    invocations: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if "gitleaks detect" in line:
            joined = line.strip()
            while joined.endswith("\\") and i + 1 < len(lines):
                i += 1
                joined = joined[:-1].rstrip() + " " + lines[i].strip()
            invocations.append(joined)
        i += 1
    return invocations


def _split_jobs(text: str) -> dict[str, str]:
    """Very small YAML-shape parser: return {job_id: job_block_text}.

    Operates on the conventional two-space-indented ``jobs:`` layout used
    by every workflow in this repo (and by the synthetic snippets in the
    regression tests). Not a general YAML parser — does not need to be:
    a workflow exotic enough to evade it would already fail the other
    structural checks below.
    """
    lines = text.splitlines()
    jobs: dict[str, list[str]] = {}
    in_jobs = False
    current: str | None = None
    for line in lines:
        if re.match(r"^jobs:\s*$", line):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if re.match(r"^[A-Za-z_#]", line):  # left-margin key ends jobs:
            in_jobs = False
            continue
        m = re.match(r"^  ([\w-]+):\s*$", line)
        if m:
            current = m.group(1)
            jobs[current] = []
            continue
        if current is not None:
            jobs[current].append(line)
    return {k: "\n".join(v) for k, v in jobs.items()}


def _job_has_conforming_secrets_pipeline(job_text: str) -> list[str]:
    """Return [] iff this job implements the full required pipeline."""
    problems: list[str] = []
    job_text = _code_only(job_text)

    dl = _DOWNLOAD_RE.search(job_text)
    if not dl:
        problems.append("no pinned gitleaks CLI download")
    elif dl.group("version") != PINNED_GITLEAKS_VERSION:
        problems.append(
            f"gitleaks version {dl.group('version')} != pinned "
            f"{PINNED_GITLEAKS_VERSION}"
        )
    if PINNED_GITLEAKS_SHA256 not in job_text or "sha256sum --check" not in job_text:
        problems.append("gitleaks download not verified against pinned SHA-256")

    detects = _flatten_detect_invocations(job_text)
    tree_scans = [d for d in detects if "--no-git" in d]
    commit_scans = [d for d in detects if "--log-opts=-1" in d]
    if not tree_scans:
        problems.append("full-tree --no-git scan missing")
    if not commit_scans:
        problems.append("commit-scope scan (--log-opts=-1) missing")
    if not any("--report-format=sarif" in d for d in commit_scans):
        problems.append("commit scan does not produce a SARIF report")
    if "upload-artifact@" not in job_text or ".sarif" not in job_text:
        problems.append("SARIF artifact upload step missing")

    lint_pos = job_text.find("scripts/secret_fixture_lint.py")
    first_detect = job_text.find("gitleaks detect")
    if lint_pos == -1:
        problems.append("secret_fixture_lint.py step missing")
    elif first_detect != -1 and lint_pos > first_detect:
        problems.append("secret_fixture_lint.py must run BEFORE gitleaks")

    if "fetch-depth: 0" not in job_text:
        problems.append(
            "checkout fetch-depth is not 0 (commit scan scope requires "
            "real history, not a grafted shallow tip)"
        )
    return problems


def audit_workflows(workflows_dir: Path = _WORKFLOWS_DIR) -> list[str]:
    """Workflow-level invariants. Returns human-readable violations."""
    violations: list[str] = []
    files = sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml"))
    if not files:
        return [f"no workflow files found under {workflows_dir}"]

    # Renamed-file / nested-path bypass: GitHub only executes top-level
    # files in .github/workflows — a workflow "moved" into a subdirectory
    # is silently disabled while still looking present in the repo.
    for nested in sorted(workflows_dir.rglob("*")):
        if nested.is_file() and nested.parent != workflows_dir and (
            nested.suffix in (".yml", ".yaml")
        ):
            violations.append(
                f"nested workflow file is silently ignored by GitHub: "
                f"{nested.relative_to(workflows_dir)}"
            )

    conforming_jobs = 0
    for wf in files:
        text = _code_only(wf.read_text(encoding="utf-8"))

        if "gitleaks/gitleaks-action" in text:
            violations.append(
                f"{wf.name}: uses gitleaks/gitleaks-action (runtime license/"
                "API dependency); the pinned CLI is the contract"
            )

        # Every gitleaks invocation anywhere must use the explicit config
        # and must not neutralize the exit code.
        for d in _flatten_detect_invocations(text):
            if "--config=.gitleaks.toml" not in d:
                violations.append(
                    f"{wf.name}: gitleaks detect without --config=.gitleaks.toml"
                )
            if "--exit-code=0" in d:
                violations.append(
                    f"{wf.name}: gitleaks detect with --exit-code=0 "
                    "(leaks would not fail the job)"
                )
        for dl in _DOWNLOAD_RE.finditer(text):
            if dl.group("version") != PINNED_GITLEAKS_VERSION:
                violations.append(
                    f"{wf.name}: downloads gitleaks v{dl.group('version')} "
                    f"(pinned: v{PINNED_GITLEAKS_VERSION})"
                )
        if "gitleaks/releases/download/" in text and (
            PINNED_GITLEAKS_SHA256 not in text or "sha256sum --check" not in text
        ):
            violations.append(
                f"{wf.name}: gitleaks download without pinned SHA-256 verification"
            )

        # Security steps must fail closed: continue-on-error inside any
        # job that touches the security pipeline is a silent bypass.
        for job_id, job_text in _split_jobs(text).items():
            lowered = job_text.lower()
            if "continue-on-error: true" in lowered and any(
                kw in lowered for kw in _SECURITY_KEYWORDS
            ):
                violations.append(
                    f"{wf.name}: job '{job_id}' marks security steps "
                    "continue-on-error: true"
                )
            if not _job_has_conforming_secrets_pipeline(job_text):
                conforming_jobs += 1

        # Least privilege / SHA pinning / persist-credentials /
        # pull_request_target — delegated to the pinning audit so the two
        # gates cannot drift apart.
        violations.extend(_pinning.audit_workflow(wf))

    if conforming_jobs == 0:
        # Report what the closest candidate is missing, for fixability.
        best: tuple[int, str, str, list[str]] | None = None
        for wf in files:
            wf_code = _code_only(wf.read_text(encoding="utf-8"))
            for job_id, job_text in _split_jobs(wf_code).items():
                if "gitleaks" not in job_text:
                    continue
                probs = _job_has_conforming_secrets_pipeline(job_text)
                if best is None or len(probs) < best[0]:
                    best = (len(probs), wf.name, job_id, probs)
        if best is None:
            violations.append(
                "no workflow job runs the gitleaks secret-scan pipeline at all"
            )
        else:
            for p in best[3]:
                violations.append(f"{best[1]}: job '{best[2]}': {p}")
    return violations


def audit_gitleaks_config(config_path: Path | None = None) -> list[str]:
    """``.gitleaks.toml`` must extend defaults and never carve out scope."""
    path = config_path or (_REPO_ROOT / ".gitleaks.toml")
    if not path.exists():
        return [f"{path.name}: missing — gitleaks --config would fail"]
    violations: list[str] = []
    code_lines = [
        line for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    code = "\n".join(code_lines)
    if "[extend]" not in code or "useDefault = true" not in code:
        violations.append(
            f"{path.name}: must extend the FULL default ruleset "
            "([extend] / useDefault = true)"
        )
    lowered = code.lower()
    for forbidden, why in (
        ("allowlist", "allowlists hide findings"),
        ("[[rules]]", "custom rules can shadow/disable defaults"),
        ("stopword", "stopwords suppress matches"),
        ("usedefault = false", "drops the default ruleset"),
    ):
        if forbidden in lowered:
            violations.append(
                f"{path.name}: contains {forbidden!r} outside comments ({why}); "
                "fix the offending fixture instead, or use a fingerprint-"
                "specific .gitleaksignore entry with a justification"
            )
    return violations


def audit_gitleaksignore(path: Path | None = None) -> list[str]:
    """If .gitleaksignore exists, entries must be full fingerprints only."""
    target = path or (_REPO_ROOT / ".gitleaksignore")
    if not target.exists():
        return []
    violations: list[str] = []
    fingerprint_re = re.compile(r"^[0-9a-f]{40}:.+:[\w-]+:\d+$")
    for lineno, line in enumerate(
        target.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not fingerprint_re.match(stripped):
            violations.append(
                f".gitleaksignore:{lineno}: not a commit-specific fingerprint "
                f"(broad suppressions are forbidden): {stripped!r}"
            )
    return violations


def audit_gitignore(path: Path | None = None) -> list[str]:
    """Scanner output must never become a tracked artifact."""
    target = path or (_REPO_ROOT / ".gitignore")
    if not target.exists():
        return [".gitignore missing"]
    lines = {
        line.strip()
        for line in target.read_text(encoding="utf-8-sig").splitlines()
    }
    if "*.sarif" not in lines:
        return [".gitignore missing protection: *.sarif (scanner reports "
                "must not be committed)"]
    return []


def audit_all(repo_root: Path = _REPO_ROOT) -> list[str]:
    violations: list[str] = []
    violations.extend(audit_workflows(repo_root / ".github" / "workflows"))
    violations.extend(audit_gitleaks_config(repo_root / ".gitleaks.toml"))
    violations.extend(audit_gitleaksignore(repo_root / ".gitleaksignore"))
    violations.extend(audit_gitignore(repo_root / ".gitignore"))
    return violations


def main() -> int:
    violations = audit_all()
    print(f"security-gate integrity audit: {_REPO_ROOT}")
    if violations:
        print(f"FAIL — {len(violations)} regression(s) in the security gates:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print(
        "PASS — gitleaks pipeline intact (pinned v"
        f"{PINNED_GITLEAKS_VERSION} + SHA-256, explicit config, lint-first, "
        "tree + commit scans, SARIF artifact, fail-closed, no nested/"
        "renamed-workflow bypass, config extends defaults only)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
