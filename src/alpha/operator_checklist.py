"""Operator data-quality checklist: what to journal to unlock calibration.

The calibration gate locks position-candidate verdicts until ~50
resolved advisory outcomes exist.  This module turns that abstract
blocker into concrete instructions: which fields are missing from the
journal today, how many resolved records exist, how many are still
needed, and the exact next actions.

    records_needed =
        max(0, minimum_records_for_calibration − current_resolved_records)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.alpha import ADVISORY_DISCLAIMER
from src.utils.math_utils import clip

MINIMUM_RECORDS_FOR_CALIBRATION = 50

# Per-record fields the calibration loop needs, with the replay-record
# location each one is read from.
REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("as_of_date", "as_of_date"),
    ("ticker", "ticker"),
    ("original_score", "raw_score"),
    ("original_verdict", "verdict"),
    ("subsequent_outcome_window", "subsequent_observation_window_days"),
    ("realized_outcome", "observed_outcome.price_return"),
    ("drawdown", "observed_outcome.drawdown"),
    ("fundamental_confirmation", "observed_outcome.fundamental_confirmation"),
    ("narrative_persistence", "observed_outcome.narrative_persistence"),
    ("filing_confirmation", "observed_outcome.filing_confirmation"),
)


def _field_present(record: dict[str, Any], path: str) -> bool:
    node: Any = record
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    if node is None:
        return False
    if isinstance(node, str) and not node.strip():
        return False
    return True


def build_operator_checklist(
    db_path: Path | str | None = None,
    *,
    bridge_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect the journal (or a pre-built bridge result) and prescribe.

    Never crashes on an absent DB: an empty journal is the honest
    starting state, and the checklist's whole job is to say so.
    """
    if bridge_result is None:
        from src.alpha.journal_replay_bridge import build_replay_records_from_journal

        bridge_result = build_replay_records_from_journal(db_path)
    records = list(bridge_result.get("records") or [])
    resolved = len(records)
    records_needed = max(0, MINIMUM_RECORDS_FOR_CALIBRATION - resolved)

    # Field completeness across usable records: a field counts as covered
    # when at least half the records carry it.
    missing_fields: list[str] = []
    field_coverage: dict[str, float] = {}
    for label, path in REQUIRED_FIELDS:
        if not records:
            field_coverage[label] = 0.0
            missing_fields.append(label)
            continue
        present = sum(1 for record in records if _field_present(record, path))
        coverage = present / len(records)
        field_coverage[label] = coverage
        if coverage < 0.5:
            missing_fields.append(label)

    volume_score = 60.0 * min(1.0, resolved / MINIMUM_RECORDS_FOR_CALIBRATION)
    completeness_score = 40.0 * (
        sum(field_coverage.values()) / len(REQUIRED_FIELDS)
    )
    data_quality_score = clip(volume_score + completeness_score, 0.0, 100.0)

    next_actions: list[str] = []
    if records_needed > 0:
        next_actions.append(
            f"Journal and reconcile {records_needed} more advisory outcome(s) "
            "(log the trade idea with its score, then reconcile the outcome "
            "after the observation window)."
        )
    skip_reasons = dict(bridge_result.get("skip_reasons") or {})
    if skip_reasons.get("open_or_unknown_outcome"):
        next_actions.append(
            f"Reconcile {skip_reasons['open_or_unknown_outcome']} open journal "
            "entr(ies): unresolved outcomes teach the calibrator nothing."
        )
    if skip_reasons.get("missing_score_at_entry"):
        next_actions.append(
            f"Record score_at_entry for {skip_reasons['missing_score_at_entry']} "
            "entr(ies): outcomes without the original score cannot calibrate it."
        )
    for label in missing_fields:
        if label in (
            "drawdown",
            "narrative_persistence",
            "filing_confirmation",
            "fundamental_confirmation",
            "realized_outcome",
        ):
            next_actions.append(
                f"Capture '{label}' at reconciliation time — it is currently "
                "absent from most usable records."
            )
    if not next_actions:
        next_actions.append(
            "Data floor reached: re-fit calibration "
            "(scripts/build_alpha_replay_from_journal.py --fit-calibration) "
            "and review the reliability diagram."
        )

    return {
        "required_fields": [label for label, _ in REQUIRED_FIELDS],
        "missing_fields": missing_fields,
        "field_coverage": field_coverage,
        "data_quality_score": data_quality_score,
        "minimum_records_for_calibration": MINIMUM_RECORDS_FOR_CALIBRATION,
        "current_resolved_records": resolved,
        "records_needed": records_needed,
        "discovered_records": int(bridge_result.get("discovered_records") or 0),
        "skip_reasons": skip_reasons,
        "next_actions": next_actions,
        "disclaimer": ADVISORY_DISCLAIMER,
    }
