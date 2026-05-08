"""Replay runner — deterministic CLI for the replay-with-labels fixture.

This runner loads a replay fixture (JSON or CSV), routes its records
through ``ReplayTruthSource``, populates an ``EvidenceLedger``, runs the
canonical action-permission resolver, computes per-baseline outcome
metrics, and emits a deterministic JSON summary.

Replay-labelled records are treated as ``REPLAY_LABELED`` (externally
checkable, but not live external truth). Capital deployment must remain
blocked.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    from scripts.action_permission import resolve_action_permission
    from scripts.baseline_strategies import (
        AlwaysHoldBaseline,
        BaselineStrategy,
        NaiveMomentumBaseline,
        RandomChoiceBaseline,
        summarise_baseline_decisions,
    )
    from scripts.evidence_ledger import EvidenceLedger
    from scripts.outcome_accounting import compute_outcome_accounting
    from scripts.runtime_contracts import (
        TruthOrigin,
        ValidationStatus,
    )
    from scripts.truth_sources import (
        OutcomeLabel,
        ReplayTruthSource,
    )
except ModuleNotFoundError:  # pragma: no cover
    from action_permission import resolve_action_permission  # type: ignore[no-redef]
    from baseline_strategies import (  # type: ignore[no-redef]
        AlwaysHoldBaseline,
        BaselineStrategy,
        NaiveMomentumBaseline,
        RandomChoiceBaseline,
        summarise_baseline_decisions,
    )
    from evidence_ledger import EvidenceLedger  # type: ignore[no-redef]
    from outcome_accounting import compute_outcome_accounting  # type: ignore[no-redef]
    from runtime_contracts import (  # type: ignore[no-redef]
        TruthOrigin,
        ValidationStatus,
    )
    from truth_sources import (  # type: ignore[no-redef]
        OutcomeLabel,
        ReplayTruthSource,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "replay_with_labels"


def _load_records_from_path(path: Path) -> tuple[list[dict[str, Any]], list[Path]]:
    """Load records from a JSON file, JSON directory, or CSV file."""

    files: list[Path] = []
    records: list[dict[str, Any]] = []
    if path.is_dir():
        for entry in sorted(path.iterdir()):
            if entry.is_file() and entry.suffix.lower() in {".json", ".csv"}:
                files.append(entry)
                records.extend(_read_one_file(entry))
        if not files:
            raise FileNotFoundError(
                f"replay fixture directory has no .json/.csv files: {path}"
            )
    elif path.is_file():
        files.append(path)
        records.extend(_read_one_file(path))
    else:
        raise FileNotFoundError(f"replay fixture not found: {path}")
    return records, files


def _read_one_file(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "records" in payload:
            records = payload["records"]
        elif isinstance(payload, list):
            records = payload
        else:
            raise ValueError(
                f"unsupported JSON shape in {path} — expected list or {{records: [...]}}"
            )
        if not isinstance(records, list):
            raise ValueError(f"{path} 'records' must be a list")
        return [record for record in records if isinstance(record, dict)]
    if path.suffix.lower() == ".csv":
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rows.append({key: row[key] for key in row})
        return rows
    raise ValueError(f"unsupported fixture file type: {path}")


def _build_truth_source(records: Sequence[dict[str, Any]]) -> ReplayTruthSource:
    labels: list[OutcomeLabel] = []
    for record in records:
        outcome = record.get("outcome_label")
        if outcome is None or str(outcome).strip() == "":
            continue
        labels.append(
            OutcomeLabel(
                record_id=str(record.get("record_id") or ""),
                instrument=str(
                    record.get("instrument") or record.get("ticker") or ""
                ),
                observed_outcome=str(outcome),
                observed_at=str(record.get("outcome_timestamp") or ""),
                source=str(record.get("source") or "replay_fixture"),
            )
        )
    return ReplayTruthSource(records=records, labels=labels, name="replay_runner_fixture")


def _populate_evidence_ledger(
    truth_source: ReplayTruthSource,
    records: Sequence[dict[str, Any]],
) -> EvidenceLedger:
    ledger = EvidenceLedger()
    for truth_record in truth_source.fetch():
        confidence = 0.0
        for raw in records:
            if str(raw.get("record_id") or "") == truth_record.record_id:
                try:
                    confidence = float(raw.get("feature_value", 0.0) or 0.0)
                except (TypeError, ValueError):
                    confidence = 0.0
                break
        evidence_record = truth_record.to_evidence(
            confidence=confidence,
            labels=("replay-labeled",) if truth_record.label is not None else (),
        )
        ledger.add(evidence_record)
    return ledger


def _baseline_outcome_pairs(
    decisions: Sequence[dict[str, Any]],
    label_lookup: dict[str, str],
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for decision in decisions:
        label = label_lookup.get(str(decision.get("record_id") or ""))
        if label is None:
            continue
        pairs.append(
            {
                "predicted_action": decision.get("predicted_action"),
                "outcome_label": label,
            }
        )
    return pairs


def _resolve_canonical_permission(evidence_ledger: EvidenceLedger) -> dict[str, Any]:
    summary = evidence_ledger.summary()
    truth_origin = (
        TruthOrigin.REPLAY_LABELED
        if summary.replay_labeled_signal_count > 0
        else TruthOrigin.REPLAY
    )
    permission_result = resolve_action_permission(
        truth_origin=truth_origin,
        external_signal_count=summary.external_signal_count,
        position_integrity_state="UNKNOWN",
        policy_state="RESTRICTED",
        chaos_veto_active=False,
        chaos_veto_quarantine=False,
        calibration_missing=True,
        calibration_heuristic_only=True,
        contextual_interpretation_enabled=False,
        evidence_summary=summary,
        jail_mode_active=False,
    )
    return {
        "canonical_action_permission": permission_result.canonical_action_permission.value,
        "veto_reasons": [reason.value for reason in permission_result.veto_reasons],
        "allowed_use": list(permission_result.allowed_use),
        "forbidden_use": list(permission_result.forbidden_use),
        "warnings": list(permission_result.warnings),
        "explanation": permission_result.explanation,
        "confidence_downgrade": permission_result.confidence_downgrade,
    }


def build_replay_summary(
    records: Sequence[dict[str, Any]],
    *,
    files: Sequence[Path] | None = None,
    baselines: Sequence[BaselineStrategy] | None = None,
) -> dict[str, Any]:
    """Build a deterministic replay summary from a list of fixture records."""

    files_list = list(files or [])
    truth_source = _build_truth_source(records)
    truth_records = list(truth_source.fetch())
    evidence_ledger = _populate_evidence_ledger(truth_source, records)
    summary = evidence_ledger.summary()

    label_lookup = {
        str(record.get("record_id") or ""): str(record["outcome_label"])
        for record in records
        if record.get("outcome_label") not in (None, "")
    }

    labeled_count = sum(1 for tr in truth_records if tr.label is not None)
    unlabeled_count = len(truth_records) - labeled_count
    externally_checkable = sum(
        1 for tr in truth_records if tr.is_externally_checkable
    )

    baseline_strategies = list(baselines or [
        AlwaysHoldBaseline(),
        RandomChoiceBaseline(seed=0),
        NaiveMomentumBaseline(),
    ])
    baseline_blocks: list[dict[str, Any]] = []
    for strategy in baseline_strategies:
        decisions = [decision.to_dict() for decision in strategy.decide(records)]
        pairs = _baseline_outcome_pairs(decisions, label_lookup)
        accounting = compute_outcome_accounting(pairs)
        baseline_blocks.append(
            {
                "summary": summarise_baseline_decisions(strategy.name, [
                    decision for decision in strategy.decide(records)
                ]),
                "decisions": decisions,
                "outcome_accounting": accounting.to_dict(),
            }
        )

    # System (raw fixture-predicted) accounting — what the recorded
    # ``predicted_action`` would have looked like against the labels.
    system_pairs = []
    for record in records:
        outcome = record.get("outcome_label")
        if outcome is None or str(outcome).strip() == "":
            continue
        system_pairs.append(
            {
                "predicted_action": record.get("predicted_action"),
                "outcome_label": outcome,
            }
        )
    system_accounting = compute_outcome_accounting(system_pairs)

    canonical_permission = _resolve_canonical_permission(evidence_ledger)

    return {
        "fixture_files": [str(path) for path in files_list],
        "record_count": len(records),
        "labeled_record_count": labeled_count,
        "unlabeled_record_count": unlabeled_count,
        "externally_checkable_count": externally_checkable,
        "evidence_ledger_summary": summary.to_dict(),
        "canonical_action_permission_block": canonical_permission,
        "system_outcome_accounting": system_accounting.to_dict(),
        "baselines": baseline_blocks,
        "honesty_note": (
            "replay-labeled records are externally checkable but never "
            "live external truth. Replay metrics describe agreement on a "
            "labelled slice; they do not validate live predictive power. "
            "Capital deployment remains blocked."
        ),
    }


def run_replay(fixture_path: Path) -> dict[str, Any]:
    records, files = _load_records_from_path(fixture_path)
    return build_replay_summary(records, files=files)


def format_replay_summary(payload: dict[str, Any]) -> str:
    permission = payload.get("canonical_action_permission_block", {})
    summary = payload.get("evidence_ledger_summary", {})
    lines = [
        "Replay Runner Summary",
        f"fixture_files={', '.join(payload.get('fixture_files', [])) or 'none'}",
        f"total_records={payload.get('record_count', 0)}",
        f"labeled_records={payload.get('labeled_record_count', 0)}",
        f"unlabeled_records={payload.get('unlabeled_record_count', 0)}",
        f"externally_checkable_count={payload.get('externally_checkable_count', 0)}",
        f"evidence_external_signal_count={summary.get('external_signal_count', 0)}",
        f"evidence_payload_hash={summary.get('payload_hash', '')}",
        f"canonical_action_permission={permission.get('canonical_action_permission', 'BLOCK_CAPITAL')}",
        "veto_reasons=[" + ",".join(permission.get("veto_reasons", []) or ["NONE"]) + "]",
        "forbidden_use=" + "; ".join(permission.get("forbidden_use", []) or ["none"]),
        "honesty_note=" + str(payload.get("honesty_note", "")),
    ]
    accounting = payload.get("system_outcome_accounting", {})
    lines.append(
        "system_outcome_accounting=" + json.dumps(
            {
                k: accounting.get(k)
                for k in (
                    "sample_count",
                    "labeled_count",
                    "true_positive",
                    "false_positive",
                    "true_negative",
                    "false_negative",
                    "precision",
                    "recall",
                )
            },
            sort_keys=True,
        )
    )
    for block in payload.get("baselines", []):
        baseline_summary = block.get("summary", {})
        accounting = block.get("outcome_accounting", {})
        lines.append(
            f"baseline={baseline_summary.get('baseline_name')} "
            f"decision_count={baseline_summary.get('decision_count')} "
            f"action_counts={json.dumps(baseline_summary.get('action_counts', {}), sort_keys=True)} "
            f"precision={accounting.get('precision')} recall={accounting.get('recall')}"
        )
    return "\n".join(lines)


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay runner — load a labelled replay fixture, populate an "
            "EvidenceLedger, and emit deterministic replay metrics. "
            "Records are tagged REPLAY_LABELED, never LIVE_EXTERNAL."
        )
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="Path to a fixture directory or JSON/CSV file.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full deterministic JSON summary instead of the compact one.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_cli_parser().parse_args(argv)
    payload = run_replay(args.fixture)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(format_replay_summary(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
