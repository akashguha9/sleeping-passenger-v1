"""Private-beta readiness report.

Full Role-Uplift Sprint, Phase 8.

Purpose
-------
Score how close the local-first MVP is to private-beta readiness —
**not** public SaaS.  The math is intentionally conservative and the
ceiling is hard-capped at 6.2 unless real auth + hosted DB + staging
deploy land.

Read-only; advisory-only.  No broker, no order, no execution.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.advisory_contract import (  # noqa: E402
    AUDIT_ONLY_STORE,
    CANONICAL_STORE,
    advisory_safety_stamps,
)


DEFAULT_REPORT_PATH = (
    _REPO_ROOT / "runtime" / "release" / "private_beta_readiness_report.json"
)
DESIGN_DOC_DIR = _REPO_ROOT / "docs" / "private_beta"
REAL_AUTH_TEST = (
    _REPO_ROOT / "tests" / "test_api_token_gate_contract.py"
)
USER_ISOLATION_TEST = (
    _REPO_ROOT / "tests" / "test_private_beta_user_isolation_stub.py"
)
STAGING_SMOKE_DOC = DESIGN_DOC_DIR / "STAGING_SMOKE_CHECK.md"
LEGAL_NOTES = _REPO_ROOT / "docs" / "LEGAL_PRIVACY_NOTES.md"
LEGAL_COMPLIANCE = _REPO_ROOT / "docs" / "LEGAL_PRIVACY_COMPLIANCE_MODEL.md"
HOSTED_DEPLOYMENT_PLAN = _REPO_ROOT / "docs" / "HOSTED_DEPLOYMENT_PLAN.md"
BACKUP_LOCAL_STATE_SCRIPT = _REPO_ROOT / "scripts" / "backup_local_state.py"
BACKUP_DB_SCRIPT = _REPO_ROOT / "scripts" / "backup_db.py"

PRIVATE_BETA_CEILING_DESIGN_ONLY = 6.2
PRIVATE_BETA_WEIGHTS: dict[str, float] = {
    "auth": 0.20,
    "hosted_db": 0.20,
    "user_isolation": 0.15,
    "staging_deploy": 0.15,
    "monitoring": 0.10,
    "legal": 0.10,
    "backup": 0.10,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _score_auth(repo_root: Path) -> tuple[float, str]:
    """Auth = 1 if real multi-user auth + session lifecycle test passes;
    else 0.  The MVP today ships only a local API-token gate; we
    deliberately do NOT call that "real auth" — it is a single-operator
    placeholder.
    """
    return 0.0, "No real multi-user auth shipped; LocalApiTokenPanel is single-operator only."


def _score_hosted_db(repo_root: Path) -> tuple[float, str]:
    """HostedDB = 1 if a hosted DB is configured AND smoke-tested.

    A documented plan does not unlock this dimension — only a passing
    smoke test against a real hosted DB does.  Until then, 0.
    """
    return 0.0, "Hosted DB not configured; canonical store is local SQLite."


def _score_user_isolation(repo_root: Path) -> tuple[float, str]:
    """UserIsolation = 1 when an actual per-user namespace test exists,
    0.5 when only the design doc exists, 0 otherwise.
    """
    test_path = repo_root / "tests" / "test_private_beta_user_isolation_stub.py"
    design_doc = repo_root / "docs" / "private_beta" / "AUTH_AND_USER_ISOLATION_PLAN.md"
    if test_path.exists():
        return 1.0, "Per-user namespace contract test present."
    if design_doc.exists():
        return 0.5, "Design doc present; no contract test yet."
    return 0.0, "No design doc, no contract test."


def _score_staging_deploy(repo_root: Path) -> tuple[float, str]:
    """StagingDeploy = 1 only when a real staging URL passes the smoke
    contract.  A documented contract counts as 0.

    The smoke doc presence does not gate any execution path; it is
    informational only.
    """
    if not STAGING_SMOKE_DOC.exists():
        return 0.0, "No staging smoke contract documented."
    return 0.0, (
        "Staging smoke contract documented at "
        f"{STAGING_SMOKE_DOC.relative_to(repo_root)}, but no live staging URL yet."
    )


def _score_monitoring(repo_root: Path) -> tuple[float, str]:
    """Monitoring = 1 when health/metrics endpoints + log retention
    are documented AND testable locally; 0.5 when only docs exist; 0
    otherwise.
    """
    release_proof = repo_root / "runtime" / "release" / "release_gate_proof.json"
    if release_proof.exists():
        return 0.5, "release_gate_proof.json present; full observability stack not yet wired."
    return 0.0, "No release-gate proof artifact."


def _score_legal(repo_root: Path) -> tuple[float, str]:
    """Legal = 1 when privacy + disclaimer + source-ToS docs all
    exist; 0.5 when a draft exists; 0 otherwise.
    """
    have_notes = LEGAL_NOTES.exists()
    have_compliance = LEGAL_COMPLIANCE.exists()
    if have_notes and have_compliance:
        return 1.0, "Privacy + compliance docs present."
    if have_notes or have_compliance:
        return 0.5, "Partial legal doc set present."
    return 0.0, "No legal docs."


def _score_backup(repo_root: Path) -> tuple[float, str]:
    """Backup = 1 when a restore drill passes; 0.5 when only a backup
    script exists; 0 otherwise.
    """
    if BACKUP_LOCAL_STATE_SCRIPT.exists() or BACKUP_DB_SCRIPT.exists():
        return 0.5, "Local backup script present; no restore drill recorded."
    return 0.0, "No backup script."


def build_report(*, repo_root: Path = _REPO_ROOT) -> dict[str, Any]:
    auth, auth_reason = _score_auth(repo_root)
    hosted_db, hosted_db_reason = _score_hosted_db(repo_root)
    user_isolation, ui_reason = _score_user_isolation(repo_root)
    staging_deploy, staging_reason = _score_staging_deploy(repo_root)
    monitoring, monitoring_reason = _score_monitoring(repo_root)
    legal, legal_reason = _score_legal(repo_root)
    backup, backup_reason = _score_backup(repo_root)

    weights = PRIVATE_BETA_WEIGHTS
    raw_score = 10.0 * (
        weights["auth"] * auth
        + weights["hosted_db"] * hosted_db
        + weights["user_isolation"] * user_isolation
        + weights["staging_deploy"] * staging_deploy
        + weights["monitoring"] * monitoring
        + weights["legal"] * legal
        + weights["backup"] * backup
    )

    # If neither real auth nor hosted DB exist, hold the score below 6.2
    # so the gate stays honest about being a *design* surface only.
    capped = bool(auth < 1.0 and hosted_db < 1.0)
    private_beta_score = min(raw_score, PRIVATE_BETA_CEILING_DESIGN_ONLY) if capped else raw_score

    safety = advisory_safety_stamps()
    return {
        "script": "private_beta_readiness_report.py",
        "generated_at_utc": _utc_now_iso(),
        "advisory_status": safety["advisory_status"],
        "execution_gate": safety["execution_gate"],
        "broker_api_called": safety["broker_api_called"],
        "ai_execution_count": safety["ai_execution_count"],
        "can_execute": safety["can_execute"],
        "execution_permission": safety["execution_permission"],
        "human_review_required": safety["human_review_required"],
        "broker_order_id": safety["broker_order_id"],
        "canonical_store": CANONICAL_STORE,
        "audit_only_store": AUDIT_ONLY_STORE,
        "jsonl_is_canonical": False,
        "weights": weights,
        "auth": auth,
        "auth_reason": auth_reason,
        "hosted_db": hosted_db,
        "hosted_db_reason": hosted_db_reason,
        "user_isolation": user_isolation,
        "user_isolation_reason": ui_reason,
        "staging_deploy": staging_deploy,
        "staging_deploy_reason": staging_reason,
        "monitoring": monitoring,
        "monitoring_reason": monitoring_reason,
        "legal": legal,
        "legal_reason": legal_reason,
        "backup": backup,
        "backup_reason": backup_reason,
        "raw_score": round(raw_score, 4),
        "private_beta_score": round(private_beta_score, 4),
        "private_beta_ceiling_design_only": PRIVATE_BETA_CEILING_DESIGN_ONLY,
        "capped_to_design_only": capped,
        "warning": (
            "Private beta is not production; public SaaS remains "
            "NOT_TARGETED_THIS_YEAR."
        ),
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Score private-beta readiness across auth, hosted DB, user "
            "isolation, staging deploy, monitoring, legal, and backup. "
            "Read-only.  Advisory-only."
        ),
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write the readiness report JSON to this path.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_report()
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json is not None:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    sys.stdout.write(payload + "\n")
    return 0


__all__ = [
    "PRIVATE_BETA_WEIGHTS",
    "PRIVATE_BETA_CEILING_DESIGN_ONLY",
    "build_report",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
