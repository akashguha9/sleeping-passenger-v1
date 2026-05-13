"""
Safe 6-hour live source refresh orchestrator.

This script is a thin wrapper around the existing phase1 and phase2 runners.
Its job is **operational clarity**, not new ingestion logic:

  - present a single CLI for "refresh all configured live sources"
  - default to --dry-run; --write must be explicit
  - skip sources whose credentials are not configured, instead of failing
  - emit per-source status that the operator (or the scheduler) can read
  - stamp the advisory-safety contract on every output
  - never log secret values

Examples
--------
  # Plan-only: shows what would run, never calls anything.
  python scripts/run_live_refresh.py --source all --dry-run --plan-only

  # Dry-run: phase1/phase2 runners are called in their own --dry-run mode.
  python scripts/run_live_refresh.py --source all --dry-run

  # Write: explicit opt-in to actually persist signal events.
  python scripts/run_live_refresh.py --source all --write

  # Single source:
  python scripts/run_live_refresh.py --source polymarket --dry-run

  # JSON output for scripted scheduling:
  python scripts/run_live_refresh.py --source all --dry-run --json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.live_source_registry import (
    ADAPTER_IMPLEMENTED,
    ADAPTER_PARTIAL,
    ADAPTER_PLANNED,
    ADVISORY_STATUS,
    ALL_SOURCE_KEYS,
    DEFAULT_REFRESH_HOURS,
    EXECUTION_GATE_LOCKED,
    build_refresh_plan,
    detect_source_credential_state,
    get_source_family,
)

# Sources handled by the phase1 runner vs the phase2 runner. Keep in sync with
# scripts/run_live_sources_phase1.py and scripts/run_live_sources_phase2.py.
_PHASE1_KEYS = ("polymarket", "gdelt", "sec_edgar")
_PHASE2_KEYS = (
    "newsapi",
    "event_registry",
    "etherscan",
    "grok_xai",
    "market_data",
    "india",
    "global_filings",
    "asia_disclosure",
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Safe 6-hour live source refresh orchestrator. Wraps the existing "
            "phase1 and phase2 runners. Default mode is --dry-run."
        ),
    )
    parser.add_argument(
        "--source",
        default="all",
        help=(
            "Single source key (e.g. polymarket, gdelt, sec_edgar, newsapi, "
            "event_registry, etherscan, grok_xai, market_data, india, "
            "global_filings, asia_disclosure) or 'all' for every configured "
            "source. Default: all."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Default. Fetch / plan only, do not persist any signal events.",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="Explicit opt-in to actually persist signal events to SQLite.",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help=(
            "Print the refresh plan derived from the registry and exit. "
            "Never invokes any adapter."
        ),
    )
    parser.add_argument(
        "--cadence-hours",
        type=int,
        default=DEFAULT_REFRESH_HOURS,
        help="Refresh cadence in hours (default: 6).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the report as JSON instead of human-readable text.",
    )
    args = parser.parse_args(argv)
    if not args.write:
        # Default mode is dry-run.
        args.dry_run = True
    return args


def _resolve_source_keys(arg: str) -> list[str]:
    raw = (arg or "all").strip().lower()
    if raw == "all":
        return list(ALL_SOURCE_KEYS)
    return [raw]


def _build_skip_entry(
    source_key: str, reason: str, *, write_mode: bool
) -> dict[str, Any]:
    family = get_source_family(source_key)
    return {
        "source_key": source_key,
        "display_name": family["display_name"],
        "adapter_status": family["adapter_status"],
        "action": "skipped",
        "reason": reason,
        "fetched_count": 0,
        "persisted_count": 0,
        "error_summary": "",
        "credential_configured": False,
        "advisory_status": ADVISORY_STATUS,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_review_required": True,
        "write_mode": bool(write_mode),
    }


def _build_would_run_entry(
    source_key: str, *, write_mode: bool, credential_configured: bool
) -> dict[str, Any]:
    family = get_source_family(source_key)
    return {
        "source_key": source_key,
        "display_name": family["display_name"],
        "adapter_status": family["adapter_status"],
        "action": "would_run" if not write_mode else "would_write",
        "reason": "",
        "fetched_count": 0,
        "persisted_count": 0,
        "error_summary": "",
        "credential_configured": credential_configured,
        "advisory_status": ADVISORY_STATUS,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_review_required": True,
        "write_mode": bool(write_mode),
    }


def _classify_for_execution(
    source_key: str,
    credential_state: dict[str, dict[str, Any]],
    *,
    write_mode: bool,
) -> dict[str, Any]:
    """Decide what should happen for a given source in this run.

    Returns a fully-formed per-source entry that downstream code can either
    return as-is (dry-run / plan-only path) or hand off to the real runners
    (write path — actual invocation is intentionally NOT performed by this
    file in this sprint; it returns "would_run" entries so the operator can
    invoke phase1/phase2 directly).
    """
    family = get_source_family(source_key)
    cred = credential_state.get(source_key, {})
    cred_configured = bool(cred.get("configured"))

    if family["adapter_status"] == ADAPTER_PLANNED:
        return _build_skip_entry(
            source_key, "adapter_planned_not_implemented", write_mode=write_mode
        )
    if family["requires_api_key"] and not cred_configured:
        missing = ", ".join(cred.get("missing_env_keys", ())) or "credentials"
        return _build_skip_entry(
            source_key,
            f"missing_credentials: {missing}",
            write_mode=write_mode,
        )
    if family["adapter_status"] == ADAPTER_PARTIAL:
        # Partial means *some* providers in the family are implemented. The
        # underlying phase2 runner is responsible for skipping placeholders.
        return _build_would_run_entry(
            source_key, write_mode=write_mode, credential_configured=cred_configured
        )
    return _build_would_run_entry(
        source_key, write_mode=write_mode, credential_configured=cred_configured
    )


def build_orchestrator_report(
    source_keys: list[str],
    *,
    write_mode: bool,
    plan_only: bool,
    cadence_hours: int,
) -> dict[str, Any]:
    """Compute the orchestrator report.

    This function is intentionally pure — it does not call any live adapter,
    and it does not write to disk. Tests can call it directly and assert on
    the structured output.
    """
    started_at = time.time()
    plan = build_refresh_plan(source_keys, cadence_hours=cadence_hours)
    credential_state = detect_source_credential_state()

    entries: list[dict[str, Any]] = []
    for key in plan["requested_source_keys"]:
        entry = _classify_for_execution(
            key, credential_state, write_mode=write_mode and not plan_only
        )
        entries.append(entry)

    skipped = sum(1 for e in entries if e["action"] == "skipped")
    would_run = sum(1 for e in entries if e["action"] == "would_run")
    would_write = sum(1 for e in entries if e["action"] == "would_write")

    return {
        "started_at_epoch": started_at,
        "cadence_hours": int(cadence_hours),
        "mode": "write" if write_mode and not plan_only else "dry_run",
        "plan_only": bool(plan_only),
        "requested_source_keys": plan["requested_source_keys"],
        "entries": entries,
        "summary": {
            "total": len(entries),
            "skipped": skipped,
            "would_run": would_run,
            "would_write": would_write,
        },
        "advisory_status": ADVISORY_STATUS,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_review_required": True,
        "phase1_invocation_hint": (
            "python scripts/run_live_sources_phase1.py --source <key> --dry-run|--write"
        ),
        "phase2_invocation_hint": (
            "python scripts/run_live_sources_phase2.py --source <key> --dry-run|--write"
        ),
    }


def _format_text_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("Sleeping Passenger — live source refresh orchestrator")
    lines.append("=" * 72)
    lines.append(f"Mode: {report['mode']}")
    lines.append(f"Plan-only: {report['plan_only']}")
    lines.append(f"Cadence: every {report['cadence_hours']}h")
    lines.append(f"Advisory: {report['advisory_status']}  |  "
                 f"Execution gate: {report['execution_gate']}  |  "
                 f"Broker calls: {report['broker_api_called']}")
    lines.append("")
    lines.append("Per-source:")
    for entry in report["entries"]:
        lines.append(
            f"  - {entry['source_key']:<16} "
            f"status={entry['adapter_status']:<11} "
            f"action={entry['action']:<11} "
            f"cred={'yes' if entry['credential_configured'] else 'no':<3} "
            + (f"reason={entry['reason']}" if entry["reason"] else "")
        )
    s = report["summary"]
    lines.append("")
    lines.append(
        f"Summary: total={s['total']}  skipped={s['skipped']}  "
        f"would_run={s['would_run']}  would_write={s['would_write']}"
    )
    if report["mode"] == "write":
        lines.append("")
        lines.append("NOTE: --write is the explicit opt-in mode. This orchestrator")
        lines.append("does NOT itself call live APIs in this sprint — to actually")
        lines.append("persist, run the phase1 / phase2 runners directly:")
        lines.append("  " + report["phase1_invocation_hint"])
        lines.append("  " + report["phase2_invocation_hint"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        source_keys = _resolve_source_keys(args.source)
        # Validate each source key against the registry.
        for key in source_keys:
            get_source_family(key)
    except KeyError as exc:
        message = str(exc).strip("'\"")
        if args.json:
            sys.stdout.write(json.dumps({
                "error": "unknown_source",
                "detail": message,
                "advisory_status": ADVISORY_STATUS,
            }) + "\n")
        else:
            sys.stderr.write(f"[error] Unknown source: {message}\n")
        return 2

    report = build_orchestrator_report(
        source_keys,
        write_mode=bool(args.write),
        plan_only=bool(args.plan_only),
        cadence_hours=int(args.cadence_hours),
    )

    if args.json:
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    else:
        sys.stdout.write(_format_text_report(report) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
