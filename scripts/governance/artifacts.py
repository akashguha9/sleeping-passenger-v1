"""Machine-readable artifact writer for the Daily Governance Gate.

Writes the six mandated artifacts, each stamped with the advisory/safety
header. Canonical files live in ``out_dir``; a dated, run-id-scoped archive
copy is preserved under ``out_dir/governance_history/`` so a re-run never
silently destroys a prior day's record.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from scripts.governance.models import DailyGovernanceResult, to_jsonable
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from governance.models import DailyGovernanceResult, to_jsonable  # type: ignore[no-redef]

SCHEMA_VERSION = "1.0.0"

ARTIFACT_NAMES = (
    "daily_governance_result.json",
    "daily_risk_blocks.json",
    "daily_phantom_quarantine.json",
    "daily_existing_holding_review.json",
    "daily_moltbook_entry.json",
    "daily_final_decision_board.json",
)


def _header(result: DailyGovernanceResult, run_id: str | None) -> dict[str, Any]:
    return {
        "run_date": result.run_date,
        "run_id": run_id,
        "created_at": result.created_at,
        "schema_version": SCHEMA_VERSION,
        "source_health_status": result.source_health_status,
        "execution_gate_status": result.execution_gate_status,
        "new_risk_permission": result.new_risk_permission,
        "human_execution_required": True,
        "broker_execution_allowed": False,
    }


def build_artifacts(result: DailyGovernanceResult, *, run_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Return {filename: payload} for the six governance artifacts."""
    header = _header(result, run_id)
    return {
        "daily_governance_result.json": {**header, "result": result.to_dict()},
        "daily_risk_blocks.json": {**header, "risk_blocks": to_jsonable(result.risk_blocks)},
        "daily_phantom_quarantine.json": {
            **header,
            "names_to_quarantine": result.names_to_quarantine,
            "phantom_quarantine_board": to_jsonable(result.phantom_quarantine_board),
        },
        "daily_existing_holding_review.json": {
            **header,
            "existing_holding_review_board": to_jsonable(result.existing_holding_review_board),
            "reduce_exit_review_board": to_jsonable(result.reduce_exit_review_board),
        },
        "daily_moltbook_entry.json": {**header, "moltbook_entry": result.moltbook_entry},
        "daily_final_decision_board.json": {**header, "final_daily_decision_board": result.final_daily_decision_board},
    }


def write_governance_artifacts(
    result: DailyGovernanceResult, out_dir: str | Path, *, run_id: str | None = None
) -> list[Path]:
    """Write the six artifacts to ``out_dir`` plus a preserved dated archive."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    run_token = run_id or "norun"
    archive = out / "governance_history" / f"{result.run_date}__{run_token}"
    archive.mkdir(parents=True, exist_ok=True)

    artifacts = build_artifacts(result, run_id=run_id)
    written: list[Path] = []
    for name, payload in artifacts.items():
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        for target in (out / name, archive / name):
            target.write_text(text, encoding="utf-8")
            written.append(target)
    return written
