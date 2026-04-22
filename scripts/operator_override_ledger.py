from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from scripts.action_engine import build_action_report
    from scripts.execution_governance import (
        classify_override,
        evaluate_first_principles_gate,
        evaluate_interaction_quality,
        evaluate_model_quality,
        evaluate_operator_quality,
        load_execution_governance_config,
    )
    from scripts.runtime_common import (
        INTERACTION_FEEDBACK_LEDGER_PATH,
        MODEL_FEEDBACK_LEDGER_PATH,
        OPERATOR_FEEDBACK_LEDGER_PATH,
        OPERATOR_OVERRIDE_LEDGER_PATH,
        append_jsonl,
        load_current_pipeline_state,
        repo_relative,
        stamp_payload,
        utc_timestamp,
    )
except ModuleNotFoundError:
    from action_engine import build_action_report
    from execution_governance import (
        classify_override,
        evaluate_first_principles_gate,
        evaluate_interaction_quality,
        evaluate_model_quality,
        evaluate_operator_quality,
        load_execution_governance_config,
    )
    from runtime_common import (
        INTERACTION_FEEDBACK_LEDGER_PATH,
        MODEL_FEEDBACK_LEDGER_PATH,
        OPERATOR_FEEDBACK_LEDGER_PATH,
        OPERATOR_OVERRIDE_LEDGER_PATH,
        append_jsonl,
        load_current_pipeline_state,
        repo_relative,
        stamp_payload,
        utc_timestamp,
    )


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"|")
    return f"{prefix}_{digest.hexdigest()[:12]}"


def _signal_lookup(runtime_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in runtime_state.get("per_signal_attribution", []):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            mapping[ticker] = row
    return mapping


def _action_lookup(action_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in action_rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            mapping[ticker] = row
    return mapping


def _manual_reasoning_row(
    action_row: dict[str, Any],
    why_this_move: str,
    trigger: str,
    invalidation: str,
    regime: str,
    why_now: str,
    note: str | None = None,
) -> dict[str, Any]:
    reasons = [
        text
        for text in [
            why_this_move,
            trigger,
            invalidation,
            regime,
            why_now,
            note or "",
        ]
        if str(text or "").strip()
    ]
    row = dict(action_row)
    row.update(
        {
            "why_this_move": why_this_move,
            "trigger": trigger,
            "invalidation": invalidation,
            "regime": regime,
            "why_now": why_now,
            "reasons": reasons,
        }
    )
    return row


def record_operator_override(
    ticker: str,
    override_action: str,
    why_this_move: str = "",
    trigger: str = "",
    invalidation: str = "",
    regime: str = "",
    why_now: str = "",
    signal_id: str | None = None,
    suggested_action: str | None = None,
    operator_id: str | None = None,
    emotional_state: str | None = None,
    confidence_source: str | None = None,
    note: str | None = None,
    runtime_state: dict[str, Any] | None = None,
    action_report: dict[str, Any] | None = None,
    override_ledger_path: Path | None = None,
    operator_feedback_path: Path | None = None,
    model_feedback_path: Path | None = None,
    interaction_feedback_path: Path | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = runtime_state or load_current_pipeline_state()
    report = action_report or build_action_report(runtime_state=state, write_runtime=False)
    action_lookup = _action_lookup(report.get("actions", []))
    signal_lookup = _signal_lookup(state)

    normalized_ticker = str(ticker or "").upper().strip()
    if not normalized_ticker:
        raise ValueError("ticker is required")

    suggested_row = action_lookup.get(normalized_ticker, {})
    resolved_suggested_action = (
        suggested_action
        or suggested_row.get("action")
        or "UNKNOWN"
    )
    if not str(resolved_suggested_action).strip():
        raise ValueError(f"no suggested action found for ticker: {normalized_ticker}")

    signal_row = signal_lookup.get(normalized_ticker, {})
    resolved_signal_id = (
        signal_id
        or suggested_row.get("signal_id")
        or signal_row.get("signal_id")
        or ""
    )
    model_quality = {}
    governance = (
        suggested_row.get("execution_governance", {})
        if isinstance(suggested_row.get("execution_governance"), dict)
        else {}
    )
    if isinstance(governance.get("model_quality"), dict):
        model_quality = governance["model_quality"]
    if not model_quality:
        model_quality = evaluate_model_quality(suggested_row or {"ticker": normalized_ticker})

    override_meta = classify_override(
        suggested_action=str(resolved_suggested_action),
        override_action=str(override_action),
    )
    active_config = config or load_execution_governance_config()
    manual_action_row = _manual_reasoning_row(
        action_row=suggested_row or {"ticker": normalized_ticker, "action": resolved_suggested_action},
        why_this_move=why_this_move,
        trigger=trigger,
        invalidation=invalidation,
        regime=regime,
        why_now=why_now,
        note=note,
    )
    manual_fpeg = evaluate_first_principles_gate(
        action_row=manual_action_row,
        signal_row=signal_row,
        runtime_state=state,
        config=active_config,
    )

    override_id = _stable_id(
        "override",
        utc_timestamp(),
        normalized_ticker,
        resolved_signal_id,
        resolved_suggested_action,
        override_action,
        operator_id or "",
    )
    override_entry = stamp_payload(
        {
            "artifact_kind": "operator_override_entry",
            "override_id": override_id,
            "signal_id": resolved_signal_id,
            "ticker": normalized_ticker,
            "suggested_action": str(resolved_suggested_action).upper(),
            "override_action": str(override_action or "").upper(),
            "override_classification": override_meta["override_classification"],
            "risk_direction": override_meta["risk_direction"],
            "operator_id": str(operator_id or "").strip() or None,
            "emotional_state": str(emotional_state or "").strip() or None,
            "confidence_source": str(confidence_source or "").strip() or None,
            "why_this_move": why_this_move,
            "trigger": trigger,
            "invalidation": invalidation,
            "regime": regime,
            "why_now": why_now,
            "note": str(note or "").strip() or None,
            "manual_fpeg_score": manual_fpeg["fpeg_score"],
            "manual_fpeg_state": manual_fpeg["fpeg_state"],
            "model_quality_score": model_quality.get("model_quality_score"),
            "model_quality_state": model_quality.get("model_quality_state"),
            "suggestion_only": True,
            "human_execution_required": True,
            "approval_state": "MANUAL_OVERRIDE_LOGGED",
            "logged_at": utc_timestamp(),
        },
        runtime_state=state,
    )
    operator_quality = evaluate_operator_quality(override_entry, config=active_config)
    interaction_quality = evaluate_interaction_quality(
        override_payload=override_entry,
        operator_quality=operator_quality,
        model_quality=model_quality,
        config=active_config,
    )

    operator_feedback_entry = stamp_payload(
        {
            "artifact_kind": "operator_quality_feedback_entry",
            "override_id": override_id,
            "signal_id": resolved_signal_id,
            "ticker": normalized_ticker,
            **operator_quality,
        },
        runtime_state=state,
    )
    model_feedback_entry = stamp_payload(
        {
            "artifact_kind": "model_quality_feedback_entry",
            "override_id": override_id,
            "signal_id": resolved_signal_id,
            "ticker": normalized_ticker,
            **model_quality,
        },
        runtime_state=state,
    )
    interaction_feedback_entry = stamp_payload(
        {
            "artifact_kind": "interaction_quality_feedback_entry",
            "override_id": override_id,
            "signal_id": resolved_signal_id,
            "ticker": normalized_ticker,
            **interaction_quality,
        },
        runtime_state=state,
    )

    append_jsonl(override_ledger_path or OPERATOR_OVERRIDE_LEDGER_PATH, override_entry, stamp=False)
    append_jsonl(operator_feedback_path or OPERATOR_FEEDBACK_LEDGER_PATH, operator_feedback_entry, stamp=False)
    append_jsonl(model_feedback_path or MODEL_FEEDBACK_LEDGER_PATH, model_feedback_entry, stamp=False)
    append_jsonl(
        interaction_feedback_path or INTERACTION_FEEDBACK_LEDGER_PATH,
        interaction_feedback_entry,
        stamp=False,
    )

    return {
        "override_id": override_id,
        "ticker": normalized_ticker,
        "signal_id": resolved_signal_id,
        "suggested_action": str(resolved_suggested_action).upper(),
        "override_action": str(override_action or "").upper(),
        "override_classification": override_meta["override_classification"],
        "manual_fpeg_state": manual_fpeg["fpeg_state"],
        "manual_fpeg_score": manual_fpeg["fpeg_score"],
        "operator_quality_state": operator_quality["operator_quality_state"],
        "model_quality_state": model_quality["model_quality_state"],
        "interaction_quality_state": interaction_quality["interaction_quality_state"],
        "override_ledger_path": repo_relative(override_ledger_path or OPERATOR_OVERRIDE_LEDGER_PATH),
        "operator_feedback_path": repo_relative(operator_feedback_path or OPERATOR_FEEDBACK_LEDGER_PATH),
        "model_feedback_path": repo_relative(model_feedback_path or MODEL_FEEDBACK_LEDGER_PATH),
        "interaction_feedback_path": repo_relative(
            interaction_feedback_path or INTERACTION_FEEDBACK_LEDGER_PATH
        ),
    }


def format_override_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Operator Override Ledger",
            f"ticker={report['ticker']}",
            f"signal_id={report['signal_id'] or 'NONE'}",
            f"suggested_action={report['suggested_action']}",
            f"override_action={report['override_action']}",
            f"override_classification={report['override_classification']}",
            f"manual_fpeg_state={report['manual_fpeg_state']}",
            f"operator_quality_state={report['operator_quality_state']}",
            f"interaction_quality_state={report['interaction_quality_state']}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Record a human override against the current suggestion path with "
            "first-principles reasoning and interaction-quality feedback."
        )
    )
    parser.add_argument("--ticker", required=True, help="Ticker for the override event.")
    parser.add_argument(
        "--override-action",
        required=True,
        help="Human-selected action, e.g. REVIEW_FOR_ENTRY, MONITOR, EXIT_NOW.",
    )
    parser.add_argument("--signal-id", default=None, help="Optional explicit signal id.")
    parser.add_argument(
        "--suggested-action",
        default=None,
        help="Optional explicit model suggestion. If omitted, resolve from current action report.",
    )
    parser.add_argument("--why-this-move", default="", help="First-principles why this move.")
    parser.add_argument("--trigger", default="", help="What explicitly triggers the move.")
    parser.add_argument("--invalidation", default="", help="Where the thesis fails.")
    parser.add_argument("--regime", default="", help="Regime / state classification.")
    parser.add_argument("--why-now", default="", help="Why now instead of later.")
    parser.add_argument("--operator-id", default=None, help="Optional operator identifier.")
    parser.add_argument(
        "--emotional-state",
        default=None,
        help="Optional emotional-state tag for later audit.",
    )
    parser.add_argument(
        "--confidence-source",
        default=None,
        help="Optional source tag, e.g. internal_evidence or paper_history.",
    )
    parser.add_argument("--note", default=None, help="Optional extra note.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = record_operator_override(
        ticker=args.ticker,
        override_action=args.override_action,
        why_this_move=args.why_this_move,
        trigger=args.trigger,
        invalidation=args.invalidation,
        regime=args.regime,
        why_now=args.why_now,
        signal_id=args.signal_id,
        suggested_action=args.suggested_action,
        operator_id=args.operator_id,
        emotional_state=args.emotional_state,
        confidence_source=args.confidence_source,
        note=args.note,
    )
    if args.summary:
        print(format_override_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
