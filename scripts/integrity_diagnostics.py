from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _timestamp_text(value: Any) -> str | None:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return parsed.isoformat()


def build_reproducibility_summary(
    *,
    repo_root: Path,
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = report if isinstance(report, dict) else {}
    requirements_path = repo_root / "requirements.txt"
    workflow_dir = repo_root / ".github" / "workflows"
    workflow_names = sorted(path.name for path in workflow_dir.glob("*.y*ml"))
    exposed_runtime_keys = {
        "run_id": payload.get("run_id"),
        "commit_hash": payload.get("commit_hash"),
        "config_fingerprint": payload.get("config_fingerprint"),
    }
    reported_keys = sorted(key for key, value in exposed_runtime_keys.items() if value)
    return {
        "python_version": platform.python_version(),
        "requirements_txt_exists": requirements_path.exists(),
        "requirements_txt_path": str(requirements_path),
        "ci_workflow_exists": workflow_dir.exists() and bool(workflow_names),
        "ci_workflow_files": workflow_names,
        "runtime_metadata_exposed": len(reported_keys) == 3,
        "runtime_metadata_keys_present": reported_keys,
    }


def classify_signal_source_row(row: dict[str, Any]) -> str:
    origin = str(row.get("signal_origin") or "").strip().lower()
    source_name = str(row.get("source_name") or "signal_ledger").strip().lower()
    if (
        origin == "external"
        or source_name.startswith("polymarket")
        or source_name in {"external_price_observation", "external_observation"}
    ):
        return "external"
    if source_name == "signal_ledger" or origin in {
        "seeded_runtime",
        "seeded",
        "synthetic_runtime_fallback",
    }:
        return "seeded"
    return "unknown"


def build_signal_segmentation_summary(
    *,
    per_signal_rows: list[dict[str, Any]] | None,
    external_candidate_count: int,
    external_observation_valid_count: int,
    scm_external_row_count: int,
    scm_seeded_row_count: int,
) -> dict[str, Any]:
    rows = per_signal_rows if isinstance(per_signal_rows, list) else []
    seeded = 0
    external = 0
    unknown = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = classify_signal_source_row(row)
        if label == "seeded":
            seeded += 1
        elif label == "external":
            external += 1
        else:
            unknown += 1

    mixed = seeded > 0 and external > 0
    warning = None
    if mixed:
        warning = (
            "Seeded and external evidence are both present. Combined counts are advisory only "
            "and do not prove external validation readiness."
        )
    if mixed and external_candidate_count > 0:
        risk = "HIGH"
    elif mixed:
        risk = "MEDIUM"
    elif external > 0 or external_candidate_count > 0 or external_observation_valid_count > 0:
        risk = "LOW"
    else:
        risk = "NONE"

    return {
        "seeded_signal_count": seeded,
        "external_signal_count": external,
        "unknown_signal_count": unknown,
        "seeded_scm_row_count": int(scm_seeded_row_count or 0),
        "external_scm_row_count": int(scm_external_row_count or 0),
        "external_candidate_count": int(external_candidate_count or 0),
        "external_observation_valid_count": int(external_observation_valid_count or 0),
        "mixed_signal_metric_warning": warning,
        "evidence_contamination_risk": risk,
        "external_validation_readiness_note": (
            "External and seeded counts are segmented explicitly. External candidates never "
            "upgrade deployment readiness, and seeded rows never count as external validation."
        ),
    }


def validate_candidate_observation_timestamp(
    observed_at_utc: Any,
    decision_timestamp: Any,
) -> tuple[bool, str | None]:
    observed = _parse_timestamp(observed_at_utc)
    if observed is None:
        return False, "missing_or_malformed_observation_timestamp"
    decision = _parse_timestamp(decision_timestamp)
    if decision is None:
        return False, "missing_or_malformed_decision_timestamp"
    if observed > decision:
        return False, "future_observation_timestamp"
    return True, None


def build_temporal_integrity_summary(
    *,
    decision_timestamp: Any,
    reconciliation_timestamp: Any = None,
    observations: Iterable[Any] | None = None,
    feature_rows: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []
    violation_count = 0
    hard_failure = False
    decision = _parse_timestamp(decision_timestamp)
    if decision is None:
        return {
            "temporal_integrity_state": "UNKNOWN",
            "temporal_integrity_violation_count": 0,
            "temporal_integrity_warnings": ["decision_timestamp_unavailable"],
            "decision_timestamp": None,
            "reconciliation_timestamp": _timestamp_text(reconciliation_timestamp),
        }

    for row in observations or []:
        observed_value = getattr(row, "observed_at_utc", None)
        if observed_value is None and isinstance(row, dict):
            observed_value = row.get("observed_at_utc")
        observed = _parse_timestamp(observed_value)
        if observed is None:
            violation_count += 1
            hard_failure = True
            warnings.append("external_observation_missing_or_malformed_timestamp")
            continue
        if observed > decision:
            violation_count += 1
            hard_failure = True
            warnings.append("external_observation_after_decision_timestamp")

    for row in feature_rows or []:
        if not isinstance(row, dict):
            continue
        feature_value = (
            row.get("feature_timestamp")
            or row.get("signal_timestamp")
            or row.get("timestamp")
        )
        if feature_value is None:
            continue
        feature_ts = _parse_timestamp(feature_value)
        if feature_ts is None:
            violation_count += 1
            warnings.append("feature_timestamp_malformed")
            continue
        if feature_ts > decision:
            violation_count += 1
            warnings.append("feature_timestamp_after_decision_timestamp")

    reconciliation = _parse_timestamp(reconciliation_timestamp)
    if reconciliation is not None and reconciliation < decision:
        violation_count += 1
        warnings.append("reconciliation_timestamp_precedes_decision_timestamp")

    if hard_failure:
        state = "FAILED"
    elif violation_count > 0:
        state = "WARNING"
    else:
        state = "CLEAN"

    return {
        "temporal_integrity_state": state,
        "temporal_integrity_violation_count": violation_count,
        "temporal_integrity_warnings": warnings,
        "decision_timestamp": decision.isoformat(),
        "reconciliation_timestamp": reconciliation.isoformat() if reconciliation else None,
    }


def build_truth_metrics_summary(
    *,
    signal_summary: dict[str, Any] | None,
    per_signal_rows: list[dict[str, Any]] | None,
    feedback_report: dict[str, Any] | None,
    signal_segmentation: dict[str, Any] | None,
) -> dict[str, Any]:
    summary = signal_summary if isinstance(signal_summary, dict) else {}
    rows = per_signal_rows if isinstance(per_signal_rows, list) else []
    feedback = feedback_report if isinstance(feedback_report, dict) else {}
    segmentation = signal_segmentation if isinstance(signal_segmentation, dict) else {}

    above_threshold = int(summary.get("signals_above_ce_threshold", 0) or 0)
    if above_threshold > 0:
        candidate_survival_rate: dict[str, Any] = {
            "value": round(
                int(summary.get("status_counts_above_threshold", {}).get("WATCHLIST", 0) or 0)
                / above_threshold,
                4,
            ),
            "reason": None,
        }
    else:
        candidate_survival_rate = {"value": None, "reason": "insufficient_evidence"}

    blocker_count = 0
    total_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        total_rows += 1
        blocker = str(row.get("blocker_attribution") or "").strip().upper()
        if blocker and blocker not in {"NONE", "UNKNOWN"}:
            blocker_count += 1
    if total_rows > 0:
        governance_trip_rate: dict[str, Any] = {
            "value": round(blocker_count / total_rows, 4),
            "reason": None,
        }
    else:
        governance_trip_rate = {"value": None, "reason": "insufficient_evidence"}

    if segmentation:
        seeded_count = int(segmentation.get("seeded_signal_count", 0) or 0)
        external_count = int(segmentation.get("external_signal_count", 0) or 0)
        seeded_vs_external_delta: dict[str, Any] = {
            "value": seeded_count - external_count,
            "reason": None,
        }
    else:
        seeded_vs_external_delta = {
            "value": None,
            "reason": "not_derivable_from_current_artifacts",
        }

    raw_success = feedback.get("raw_success_rate")
    clean_success = feedback.get("clean_success_rate")
    if raw_success is not None and clean_success is not None:
        feedback_information_gain: dict[str, Any] = {
            "value": round(float(clean_success) - float(raw_success), 4),
            "reason": None,
        }
    else:
        feedback_information_gain = {"value": None, "reason": "insufficient_evidence"}

    return {
        "candidate_survival_rate": candidate_survival_rate,
        "governance_trip_rate": governance_trip_rate,
        "divergence_detection_latency": {
            "value": None,
            "reason": "not_derivable_from_current_artifacts",
        },
        "seeded_vs_external_delta": seeded_vs_external_delta,
        "feedback_information_gain": feedback_information_gain,
    }


GOLDEN_HEALTH_KEYS = (
    "system_readiness_state",
    "can_deploy_capital",
    "policy_state",
    "scm_state",
    "bridge_mode",
    "scm_input_origin",
    "position_integrity_state",
    "feedback_learning_state",
)


def build_stable_health_snapshot(report: dict[str, Any]) -> dict[str, Any]:
    snapshot = {
        "system_readiness_state": report.get("system_readiness_state"),
        "can_deploy_capital": report.get("can_deploy_capital"),
        "policy_state": ((report.get("policy") or {}).get("policy_state")),
        "scm_state": ((report.get("scm") or {}).get("scm_state")),
        "bridge_mode": report.get("bridge_mode"),
        "scm_input_origin": report.get("scm_input_origin"),
        "position_integrity_state": report.get("position_integrity_state"),
        "feedback_learning_state": report.get("feedback_learning_state"),
    }
    return {key: snapshot.get(key) for key in sorted(snapshot)}


def compute_stable_health_snapshot_hash(report: dict[str, Any]) -> str:
    payload = json.dumps(
        build_stable_health_snapshot(report),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
