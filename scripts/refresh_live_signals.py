"""
scripts/refresh_live_signals.py — local 6-hour live source refresh.

This is the *executing* orchestrator that actually invokes the phase1 and
phase2 runners. It is intentionally distinct from
``scripts/run_live_refresh.py``, which remains a plan-only reporter.

Behavior
--------
* Calls existing ``run_phase1`` and ``run_phase2`` runners — no new
  ingestion logic is introduced here.
* One source failing must not crash the whole refresh.
* Sources missing required credentials are *skipped*, not failed; their env
  key name is recorded as the reason (never the value).
* Per-source attempt rows are persisted to ``live_source_refresh_runs`` and
  the run summary is written to ``logs/live_signal_refresh_summary.json``.
* Default mode is ``--dry-run``. ``--write`` is the explicit opt-in that
  persists ``signal_events`` rows. ``--dry-run`` invokes the runners in
  their own dry-run mode and persists *only* the metadata row for the
  attempt — no ``signal_events`` change.

Safety
------
Every persisted row and emitted report stamps ADVISORY_ONLY, LOCKED
execution gate, ``broker_api_called=False``, ``can_execute=False``,
``ai_execution_count=0``. No broker code path is reachable from this file.

Examples
--------
  # Plan + dry-run all sources, write a metadata row + JSON summary.
  python scripts/refresh_live_signals.py

  # Explicit dry-run, all sources, with JSON to stdout.
  python scripts/refresh_live_signals.py --dry-run --json

  # Actually persist signal_events rows (this is the cadence-scheduled mode).
  python scripts/refresh_live_signals.py --write

  # Single source / subset:
  python scripts/refresh_live_signals.py --sources newsapi,event_registry --write

  # Print the planned summary without invoking adapters or persisting.
  python scripts/refresh_live_signals.py --summary
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover — optional dep
    pass

from scripts.live_source_registry import (
    ADAPTER_PLANNED,
    ADVISORY_STATUS,
    ALL_SOURCE_KEYS,
    DEFAULT_REFRESH_HOURS,
    EXECUTION_GATE_LOCKED,
    detect_source_credential_state,
    get_source_family,
)

_LOG_DIR = _REPO_ROOT / "logs"
_SUMMARY_PATH = _LOG_DIR / "live_signal_refresh_summary.json"

# Env-var override for tests/operators who want the summary written to a
# different path without monkeypatching module-level constants.  Empty /
# unset means "use the default ``logs/live_signal_refresh_summary.json``".
# Defensive-isolation purpose only: tests must never accidentally clobber
# the real operator summary file when they exercise ``run_refresh``.
_SUMMARY_PATH_ENV_VAR = "MVP_LIVE_REFRESH_SUMMARY_PATH"


def _resolve_summary_path(explicit: Path | str | None = None) -> Path:
    """Return the path ``run_refresh`` should write its summary JSON to.

    Precedence: explicit kwarg > ``MVP_LIVE_REFRESH_SUMMARY_PATH`` env
    var > module-level ``_SUMMARY_PATH``.  Returning a Path means the
    caller can always ``.parent.mkdir(parents=True, exist_ok=True)`` it
    without branching on the value.
    """
    if explicit:
        return Path(explicit)
    import os as _os

    env_val = (_os.environ.get(_SUMMARY_PATH_ENV_VAR, "") or "").strip()
    if env_val:
        return Path(env_val)
    return _SUMMARY_PATH

_PHASE1_KEYS = ("polymarket", "kalshi", "gdelt", "sec_edgar")
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

_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "advisory_only": True,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "can_execute": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "human_review_required": True,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Local 6-hour live source refresh — invokes phase1/phase2 runners "
            "safely with credential-aware skip behavior. ADVISORY-ONLY."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Default. Runners run in their own dry-run mode (no signal_events written).",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="Explicit opt-in to persist signal_events. Refresh metadata is always persisted.",
    )
    parser.add_argument(
        "--sources",
        default="",
        help=(
            "Comma-separated source keys. Default: all registry sources. "
            "Examples: polymarket,gdelt or newsapi,event_registry,etherscan."
        ),
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Compute and print the planned summary without invoking any adapter.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the run summary as JSON on stdout.",
    )
    parser.add_argument(
        "--cadence-hours",
        type=int,
        default=DEFAULT_REFRESH_HOURS,
        help=f"Cadence hours (default {DEFAULT_REFRESH_HOURS}).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress human-readable per-source lines (envelope still printed).",
    )
    args = parser.parse_args(argv)
    if not args.write and not args.summary:
        args.dry_run = True
    return args


def _resolve_sources(raw: str) -> list[str]:
    if not raw:
        return list(ALL_SOURCE_KEYS)
    seen: set[str] = set()
    out: list[str] = []
    for token in str(raw).split(","):
        key = token.strip().lower()
        if not key or key in seen:
            continue
        try:
            get_source_family(key)
        except KeyError as exc:
            raise SystemExit(f"unknown_source: {exc}") from exc
        seen.add(key)
        out.append(key)
    return out


# Derived passes run AFTER the provider phases over rows already persisted
# this cycle (e.g. the Polymarket x Kalshi disagreement scanner).  Before
# this registration the key fell through _phase_for as "unknown" and was
# silently skipped on every scheduled refresh.
_DERIVED_KEYS = ("prediction_market_disagreement",)


def _phase_for(key: str) -> str:
    if key in _PHASE1_KEYS:
        return "phase1"
    if key in _PHASE2_KEYS:
        return "phase2"
    if key in _DERIVED_KEYS:
        return "derived"
    return "unknown"


def _count_rows_for_source(source_name: str) -> int:
    try:
        from scripts.persistence import count_signal_events_by_source
    except ModuleNotFoundError:  # pragma: no cover
        from persistence import count_signal_events_by_source  # type: ignore[no-redef]
    try:
        counts = count_signal_events_by_source()
        return int(counts.get(source_name, 0))
    except Exception:
        return 0


def _safe_record_metadata(**kwargs: Any) -> None:
    """Persist one refresh-run row. Failures here must NOT crash the loop."""
    try:
        try:
            from scripts.persistence import record_live_source_refresh_run
        except ModuleNotFoundError:  # pragma: no cover
            from persistence import record_live_source_refresh_run  # type: ignore[no-redef]
        record_live_source_refresh_run(**kwargs)
    except Exception:
        pass


def _build_skip_entry(
    run_id: str,
    source_key: str,
    reason: str,
    *,
    write_mode: bool,
    db_path: str,
) -> dict[str, Any]:
    now = _utc_now_iso()
    rows_before = _count_rows_for_source(source_key)
    family = get_source_family(source_key)
    entry: dict[str, Any] = {
        "run_id": run_id,
        "source_name": source_key,
        "display_name": family["display_name"],
        "phase": _phase_for(source_key),
        "attempted": True,
        "success": False,
        "skipped": True,
        "started_at": now,
        "finished_at": now,
        "duration_seconds": 0.0,
        "rows_before": rows_before,
        "rows_after": rows_before,
        "rows_added": 0,
        "skipped_reason": reason,
        "error_message": "",
        "db_path": db_path,
        "write_mode": bool(write_mode),
    }
    entry.update(_SAFETY_STAMPS)
    _safe_record_metadata(
        run_id=entry["run_id"],
        source_name=entry["source_name"],
        attempted=True,
        success=False,
        skipped=True,
        started_at=entry["started_at"],
        finished_at=entry["finished_at"],
        duration_seconds=0.0,
        rows_before=rows_before,
        rows_after=rows_before,
        rows_added=0,
        error_message="",
        skipped_reason=reason,
    )
    return entry


def _env_truthy(name: str) -> bool:
    """Return True if env var ``name`` is a truthy string (yes/true/1/on)."""
    import os as _os

    return _os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_sec_phase1_kwargs() -> dict[str, Any]:
    """Build SEC EDGAR kwargs for ``run_phase1`` from environment.

    Recognised env vars (all optional):
      * ``SEC_DEFAULT_CIK`` — single CIK to fetch (e.g. ``0000320193``).
        Wins over the watchlist flag if both are set.
      * ``SEC_DEFAULT_WATCHLIST`` / ``SEC_USE_DEFAULT_WATCHLIST`` —
        truthy enables the built-in 7-stock watchlist.

    When neither is set, SEC skips cleanly with
    ``no_cik_or_watchlist_provided`` so the operator sees a precise reason
    instead of a generic "skipped".
    """
    import os as _os

    out: dict[str, Any] = {}
    cik_raw = (_os.environ.get("SEC_DEFAULT_CIK", "") or "").strip()
    if cik_raw:
        out["sec_cik"] = cik_raw
        return out
    if _env_truthy("SEC_DEFAULT_WATCHLIST") or _env_truthy("SEC_USE_DEFAULT_WATCHLIST"):
        out["sec_default_watchlist"] = True
    return out


def _resolve_gdelt_phase1_kwargs() -> dict[str, Any]:
    """Build GDELT kwargs for ``run_phase1`` from environment.

    Recognised env vars (all optional):
      * ``GDELT_TIMEOUT_SECONDS`` — int seconds for the primary HTTP call.
        Below-1 / non-numeric values are ignored.
    """
    import os as _os

    out: dict[str, Any] = {}
    raw = (_os.environ.get("GDELT_TIMEOUT_SECONDS", "") or "").strip()
    if raw:
        try:
            n = int(raw)
            if n >= 1:
                out["gdelt_timeout"] = n
        except ValueError:
            pass
    return out


def _invoke_phase1_single(source_key: str, *, dry_run: bool) -> dict[str, Any]:
    """Run a single phase1 source. Returns the SourceRunResult-as-dict.

    SEC and GDELT pick up env-driven defaults (SEC_DEFAULT_CIK /
    SEC_DEFAULT_WATCHLIST, GDELT_TIMEOUT_SECONDS) so the scheduled refresh
    can fetch filings and respect a tighter timeout without a CLI flag.
    """
    from scripts.live_source_runner import run_phase1

    kwargs: dict[str, Any] = {"dry_run": dry_run, "sources": [source_key]}
    if source_key == "sec_edgar":
        kwargs.update(_resolve_sec_phase1_kwargs())
    elif source_key == "gdelt":
        kwargs.update(_resolve_gdelt_phase1_kwargs())

    report = run_phase1(**kwargs)
    if not report.sources:
        return {"status": "skipped", "skipped_reason": "phase1_returned_no_source"}
    return report.sources[0].to_dict()


def _invoke_phase2_single(source_key: str, *, dry_run: bool) -> dict[str, Any]:
    from scripts.live_source_runner_phase2 import run_phase2

    report = run_phase2(dry_run=dry_run, sources=[source_key])
    if not report.sources:
        return {"status": "skipped", "skipped_reason": "phase2_returned_no_source"}
    return report.sources[0].to_dict()


def _invoke_derived_single(source_key: str, *, dry_run: bool) -> dict[str, Any]:
    """Run a derived pass over rows persisted this cycle.

    Currently only the cross-venue disagreement scanner.  The scanner's
    ``run`` CLI returns an exit code; nonzero is reported as an error so
    the refresh summary stays truthful.
    """
    if source_key != "prediction_market_disagreement":
        return {"status": "skipped",
                "skipped_reason": f"unregistered derived source: {source_key}"}
    from scripts.prediction_market_disagreement_scanner import run as scan_run

    argv = ["--json", "--write"] if not dry_run else ["--json"]
    rc = scan_run(argv)
    if rc != 0:
        return {"status": "error",
                "error_message": f"disagreement scanner exit code {rc}"}
    return {"status": "ok"}


def _run_one_source(
    run_id: str,
    source_key: str,
    *,
    write_mode: bool,
    credential_state: dict[str, dict[str, Any]],
    db_path: str,
) -> dict[str, Any]:
    family = get_source_family(source_key)
    cred = credential_state.get(source_key, {})

    if family["adapter_status"] == ADAPTER_PLANNED:
        return _build_skip_entry(
            run_id,
            source_key,
            "adapter_planned_not_implemented",
            write_mode=write_mode,
            db_path=db_path,
        )

    if family["requires_api_key"] and not bool(cred.get("configured")):
        missing = ", ".join(cred.get("missing_env_keys", ())) or "credentials"
        return _build_skip_entry(
            run_id,
            source_key,
            f"missing_credentials: {missing}",
            write_mode=write_mode,
            db_path=db_path,
        )

    phase = _phase_for(source_key)
    rows_before = _count_rows_for_source(source_key)
    started_iso = _utc_now_iso()
    t0 = time.monotonic()
    success = False
    skipped = False
    error_message = ""
    skipped_reason = ""
    runner_result: dict[str, Any] = {}

    try:
        if phase == "phase1":
            runner_result = _invoke_phase1_single(source_key, dry_run=not write_mode)
        elif phase == "phase2":
            runner_result = _invoke_phase2_single(source_key, dry_run=not write_mode)
        elif phase == "derived":
            runner_result = _invoke_derived_single(source_key, dry_run=not write_mode)
        else:
            skipped = True
            skipped_reason = f"unknown_phase: {phase}"
    except Exception as exc:  # noqa: BLE001 — orchestrator must not crash
        error_message = f"{type(exc).__name__}: {str(exc)[:200]}"
        skipped = False
        success = False
    else:
        status = str(runner_result.get("status", "")).lower()
        if status == "ok" or status == "ok_filtered":
            success = True
        elif status in {"skipped", "rate_limited", "timeout", "placeholder", "http_error"}:
            skipped = True
            skipped_reason = runner_result.get("skipped_reason", "") or status
        else:
            error_message = runner_result.get("error_message", "") or f"unexpected_status: {status}"

    finished_iso = _utc_now_iso()
    duration_seconds = time.monotonic() - t0
    rows_after = _count_rows_for_source(source_key)
    rows_added = max(0, rows_after - rows_before)

    entry: dict[str, Any] = {
        "run_id": run_id,
        "source_name": source_key,
        "display_name": family["display_name"],
        "phase": phase,
        "attempted": True,
        "success": success,
        "skipped": skipped,
        "started_at": started_iso,
        "finished_at": finished_iso,
        "duration_seconds": round(duration_seconds, 4),
        "rows_before": rows_before,
        "rows_after": rows_after,
        "rows_added": rows_added,
        "skipped_reason": skipped_reason,
        "error_message": error_message,
        "db_path": db_path,
        "write_mode": bool(write_mode),
        "runner_status": str(runner_result.get("status", "")),
        "fetched_count": int(runner_result.get("fetched_count", 0) or 0),
        "events_persisted": int(runner_result.get("events_persisted", 0) or 0),
    }
    entry.update(_SAFETY_STAMPS)

    _safe_record_metadata(
        run_id=run_id,
        source_name=source_key,
        attempted=True,
        success=success,
        skipped=skipped,
        started_at=started_iso,
        finished_at=finished_iso,
        duration_seconds=duration_seconds,
        rows_before=rows_before,
        rows_after=rows_after,
        rows_added=rows_added,
        error_message=error_message,
        skipped_reason=skipped_reason,
    )
    return entry


def _safe_db_path() -> str:
    try:
        from scripts.persistence import DB_PATH

        return str(DB_PATH)
    except Exception:
        return "runtime/mvp_local.db"


def _build_planned_summary(
    source_keys: Iterable[str],
    *,
    write_mode: bool,
    cadence_hours: int,
) -> dict[str, Any]:
    """Return what a run *would* do, without invoking any adapter."""
    started_iso = _utc_now_iso()
    credential_state = detect_source_credential_state()
    plan: list[dict[str, Any]] = []
    for key in source_keys:
        family = get_source_family(key)
        cred = credential_state.get(key, {})
        if family["adapter_status"] == ADAPTER_PLANNED:
            action = "skip"
            reason = "adapter_planned_not_implemented"
        elif family["requires_api_key"] and not bool(cred.get("configured")):
            missing = ", ".join(cred.get("missing_env_keys", ())) or "credentials"
            action = "skip"
            reason = f"missing_credentials: {missing}"
        else:
            action = "would_write" if write_mode else "would_run"
            reason = ""
        plan.append(
            {
                "source_name": key,
                "display_name": family["display_name"],
                "phase": _phase_for(key),
                "adapter_status": family["adapter_status"],
                "credential_configured": bool(cred.get("configured")),
                "action": action,
                "reason": reason,
            }
        )

    return {
        "operation": "refresh_live_signals_summary",
        "mode": "write" if write_mode else "dry_run",
        "summary_only": True,
        "started_at": started_iso,
        "cadence_hours": int(cadence_hours),
        "plan": plan,
        "total_sources_planned": len(plan),
        "db_path": _safe_db_path(),
        **_SAFETY_STAMPS,
    }


def run_refresh(
    source_keys: list[str] | None = None,
    *,
    write_mode: bool = False,
    cadence_hours: int = DEFAULT_REFRESH_HOURS,
    summary_only: bool = False,
    summary_path: Path | str | None = None,
) -> dict[str, Any]:
    """Execute a refresh cycle and return the structured summary.

    ``summary_path`` (optional) — explicit JSON destination for this run.
    When omitted, falls back to the ``MVP_LIVE_REFRESH_SUMMARY_PATH``
    env var, then to the default ``logs/live_signal_refresh_summary.json``.
    Tests should pass an explicit path (typically ``tmp_path / ...``) or
    set the env var so test runs do not clobber the operator's real
    summary file.
    """
    keys = source_keys if source_keys is not None else list(ALL_SOURCE_KEYS)

    if summary_only:
        return _build_planned_summary(
            keys, write_mode=write_mode, cadence_hours=cadence_hours
        )

    run_id = uuid.uuid4().hex[:16]
    refresh_started_at = _utc_now_iso()
    started_monotonic = time.monotonic()
    credential_state = detect_source_credential_state()
    db_path = _safe_db_path()

    entries: list[dict[str, Any]] = []
    for key in keys:
        entry = _run_one_source(
            run_id,
            key,
            write_mode=write_mode,
            credential_state=credential_state,
            db_path=db_path,
        )
        entries.append(entry)

    refresh_finished_at = _utc_now_iso()
    total_duration = round(time.monotonic() - started_monotonic, 3)
    succeeded = sum(1 for e in entries if e["success"])
    skipped = sum(1 for e in entries if e["skipped"])
    failed = sum(1 for e in entries if not e["success"] and not e["skipped"])

    summary: dict[str, Any] = {
        "operation": "refresh_live_signals",
        "run_id": run_id,
        "mode": "write" if write_mode else "dry_run",
        "refresh_started_at": refresh_started_at,
        "refresh_finished_at": refresh_finished_at,
        "total_seconds": total_duration,
        "cadence_hours": int(cadence_hours),
        "total_sources_attempted": len(entries),
        "total_sources_succeeded": succeeded,
        "total_sources_failed": failed,
        "total_sources_skipped": skipped,
        "db_path": db_path,
        "entries": entries,
        **_SAFETY_STAMPS,
    }

    target_path = _resolve_summary_path(summary_path)
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass

    return summary


def _format_summary_lines(summary: dict[str, Any], *, quiet: bool) -> list[str]:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("Sleeping Passenger - Live Signal Refresh")
    lines.append("=" * 72)
    lines.append(f"Mode: {summary['mode']}  cadence_hours={summary['cadence_hours']}")
    lines.append(
        f"Advisory: {summary['advisory_status']}  Execution gate: "
        f"{summary['execution_gate']}  broker_api_called={summary['broker_api_called']}  "
        f"can_execute={summary['can_execute']}"
    )
    if summary.get("summary_only"):
        lines.append(f"db_path: {summary['db_path']}")
        if not quiet:
            for plan in summary.get("plan", []):
                lines.append(
                    f"  - {plan['source_name']:<16} action={plan['action']:<11} "
                    f"phase={plan['phase']:<6} cred={'yes' if plan['credential_configured'] else 'no':<3} "
                    + (f"reason={plan['reason']}" if plan["reason"] else "")
                )
            lines.append(
                f"Planned: total={summary['total_sources_planned']}"
            )
        return lines

    lines.append(
        f"started_at={summary['refresh_started_at']}  finished_at={summary['refresh_finished_at']}"
    )
    lines.append(f"db_path: {summary['db_path']}")
    if not quiet:
        for e in summary.get("entries", []):
            mark = "OK " if e["success"] else ("SKIP" if e["skipped"] else "FAIL")
            extra = ""
            if e["skipped_reason"]:
                extra = f"  ({e['skipped_reason']})"
            elif e["error_message"]:
                extra = f"  ({e['error_message']})"
            lines.append(
                f"  [{mark}] {e['source_name']:<16} phase={e['phase']:<6} "
                f"rows_added={e['rows_added']}  duration_s={e['duration_seconds']}{extra}"
            )
    lines.append(
        f"Totals: attempted={summary['total_sources_attempted']}  "
        f"succeeded={summary['total_sources_succeeded']}  "
        f"failed={summary['total_sources_failed']}  "
        f"skipped={summary['total_sources_skipped']}"
    )
    return lines


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        source_keys = _resolve_sources(args.sources)
    except SystemExit as exc:
        if args.json:
            sys.stdout.write(
                json.dumps(
                    {
                        "error": str(exc),
                        **_SAFETY_STAMPS,
                    }
                )
                + "\n"
            )
        else:
            sys.stderr.write(f"[error] {exc}\n")
        return 2

    summary = run_refresh(
        source_keys=source_keys,
        write_mode=bool(args.write),
        cadence_hours=int(args.cadence_hours),
        summary_only=bool(args.summary),
    )

    if args.json:
        sys.stdout.write(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(
            "\n".join(_format_summary_lines(summary, quiet=bool(args.quiet))) + "\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
