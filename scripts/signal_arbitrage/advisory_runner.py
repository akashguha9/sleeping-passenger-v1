"""Advisory runner with opt-in forward decision capture.

This wires forward-logging into the actual Mythos->Fable advisory boundary
(``run_aggregated_pipeline``): when a daily/advisory decision is produced, the
runner can capture a feature-bearing snapshot to ``decisions.jsonl`` so future
calibration becomes automatic — but only when explicitly enabled.

Safety contract:
  * default = capture DISABLED -> NO write ever happens.
  * a single flag/env enables capture; nothing else changes about the advisory.
  * capture failure is NON-FATAL by default (advisory still returns); strict
    mode escalates to a hard failure.
  * snapshots are deduped by decision_id; reruns don't pollute the corpus.
  * advisory-only / real-money-prohibited; no execution path exists here.

The snapshot format is the canonical CalibrationRecord superset (no second
calibration format), so ``run_real_calibration`` consumes it unchanged.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .mythos import MythosObservation
from .mythos_aggregator import run_aggregated_pipeline
from .mythos_capture import (
    capture_decision_snapshot, decision_id_for,
    CAPTURED_WRITTEN, DUPLICATE_SKIPPED as _SNAP_DUP, NO_OBSERVATIONS,
)
from .mythos_corpus import (
    PAPER_TRADE, SYNTHETIC_FIXTURE, ELIGIBLE_SOURCE_TYPES, _RESOLVED, SCHEMA,
    MIN_PROVISIONAL, MIN_FIRST_PASS, MIN_STRONGER, INCONCLUSIVE,
)
from .mythos_capture import OPEN_OR_UNRESOLVED

PIPELINE_VERSION = "mythos-fable/1.0"
DEFAULT_CAPTURE_PATH = "data/calibration_corpus/decisions.jsonl"

# Runner-level capture statuses.
CAPTURE_DISABLED = "CAPTURE_DISABLED"
CAPTURE_DRY_RUN = "CAPTURE_DRY_RUN"
CAPTURE_WRITTEN = "CAPTURE_WRITTEN"
DUPLICATE_SKIPPED = "DUPLICATE_SKIPPED"
CAPTURE_FAILED_NON_FATAL = "CAPTURE_FAILED_NON_FATAL"
CAPTURE_FAILED_STRICT = "CAPTURE_FAILED_STRICT"

# Corpus readiness statuses.
NO_CORPUS_FOUND = "NO_CORPUS_FOUND"
CAPTURE_STARTED_NO_LABELS = "CAPTURE_STARTED_NO_LABELS"
PROVISIONAL_DIAGNOSTIC_READY = "PROVISIONAL_DIAGNOSTIC_READY"
FIRST_PASS_CALIBRATION_READY = "FIRST_PASS_CALIBRATION_READY"
STRONGER_CALIBRATION_READY = "STRONGER_CALIBRATION_READY"

_TRUE = {"1", "true", "True", "yes", "on"}


class CaptureError(RuntimeError):
    """Raised only in strict capture mode when capture fails."""


@dataclass(frozen=True)
class CaptureConfig:
    enabled: bool = False
    path: str = DEFAULT_CAPTURE_PATH
    strict: bool = False
    write: bool = True          # when enabled: True=write, False=dry-run
    source_type: str = PAPER_TRADE


def resolve_capture_config(
    *, enabled: bool | None = None, path: str | None = None,
    strict: bool | None = None, write: bool | None = None,
    source_type: str | None = None, env: dict[str, str] | None = None,
) -> CaptureConfig:
    """Explicit args win; otherwise read SIGNAL_CAPTURE_* env; default disabled."""
    e = env if env is not None else os.environ
    enabled = (enabled if enabled is not None
               else e.get("SIGNAL_CAPTURE_DECISIONS", "0") in _TRUE)
    path = path or e.get("SIGNAL_CAPTURE_PATH") or DEFAULT_CAPTURE_PATH
    strict = (strict if strict is not None
              else e.get("SIGNAL_CAPTURE_STRICT", "0") in _TRUE)
    if write is None:
        write = e.get("SIGNAL_CAPTURE_MODE", "write") != "dry_run"
    source_type = source_type or PAPER_TRADE
    return CaptureConfig(enabled=enabled, path=path, strict=strict, write=write,
                         source_type=source_type)


def _build_decision_context(
    observations: list[MythosObservation], cfg: CaptureConfig, *,
    run_id: str, runner_name: str, decision_timestamp: str, decision_date: int | None,
    strategy_family: str, universe: str, decision_source: str, extra: dict | None,
) -> tuple[dict[str, Any], list[str]]:
    reasons: list[str] = []

    def f(name: str, value: Any) -> Any:
        if value is None or value == "":
            reasons.append(f"MISSING:{name}")
            return None
        return value

    entity = observations[0].entity if observations else None
    advisory_output_id = f"{run_id}:{decision_id_for(observations)}" if run_id else decision_id_for(observations)
    ctx = {
        "run_id": f("run_id", run_id),
        "runner_name": runner_name,
        "pipeline_version": PIPELINE_VERSION,
        "advisory_output_id": advisory_output_id,
        "decision_source": decision_source or runner_name,
        "decision_timestamp": f("decision_timestamp", decision_timestamp),
        "decision_date": decision_date if decision_date is not None else None,
        "strategy_family": strategy_family,
        "universe": f("universe", universe),
        "dry_run": not (cfg.enabled and cfg.write),
        "capture_mode": ("write" if (cfg.enabled and cfg.write)
                         else "dry_run" if cfg.enabled else "disabled"),
        "capture_path": cfg.path if cfg.enabled else None,
        "entity": entity,
        "ticker": (extra or {}).get("ticker"),
    }
    if decision_date is None:
        reasons.append("MISSING:decision_date")
    if extra:
        ctx.update({k: v for k, v in extra.items() if k not in ctx})
    return ctx, reasons


def run_advisory_with_capture(
    observations: list[MythosObservation], *,
    capture: CaptureConfig | None = None,
    run_id: str = "", runner_name: str = "mythos_advisory_runner",
    decision_timestamp: str = "", decision_date: int | None = None,
    strategy_family: str = "mythos_fable", universe: str = "",
    decision_source: str = "", decision_context_extra: dict | None = None,
    capture_fn: Callable[..., Any] = capture_decision_snapshot,
) -> dict[str, Any]:
    """Produce the Mythos->Fable advisory decision, then optionally capture it.

    The advisory result is ALWAYS returned unchanged under ``advisory``; capture
    is opt-in and (by default) non-fatal."""
    cfg = capture if capture is not None else resolve_capture_config()

    # 1. Advisory decision — original behavior, untouched.
    advisory = run_aggregated_pipeline(observations)

    ctx, reason_codes = _build_decision_context(
        observations, cfg, run_id=run_id, runner_name=runner_name,
        decision_timestamp=decision_timestamp, decision_date=decision_date,
        strategy_family=strategy_family, universe=universe,
        decision_source=decision_source, extra=decision_context_extra)

    capture_report: dict[str, Any] | None = None
    capture_error: str | None = None

    if not cfg.enabled:
        capture_status = CAPTURE_DISABLED
    else:
        snap_mode = "write" if cfg.write else "dry_run"
        try:
            rep = capture_fn(observations, output_path=cfg.path, mode=snap_mode,
                             decision_context=ctx, source_type=cfg.source_type,
                             created_at=decision_timestamp)
            capture_report = rep.to_dict()
            if not cfg.write:
                capture_status = CAPTURE_DRY_RUN
            elif rep.status == CAPTURED_WRITTEN:
                capture_status = CAPTURE_WRITTEN
            elif rep.status == _SNAP_DUP:
                capture_status = DUPLICATE_SKIPPED
            elif rep.status == NO_OBSERVATIONS:
                capture_status = CAPTURE_FAILED_NON_FATAL
                capture_error = "no observations to capture"
            else:
                capture_status = CAPTURE_DRY_RUN
        except Exception as exc:  # capture must not break the advisory by default
            capture_error = f"{type(exc).__name__}: {exc}"
            if cfg.strict:
                raise CaptureError(f"{CAPTURE_FAILED_STRICT}: {capture_error}") from exc
            capture_status = CAPTURE_FAILED_NON_FATAL

    return {
        "advisory": advisory,                       # original advisory preserved
        "pre_scoring_decision": advisory["pre_scoring_decision"],
        "routed_to_fable": advisory["routed_to_fable"],
        "capture_status": capture_status,
        "capture": capture_report,
        "capture_error": capture_error,
        "decision_context": ctx,
        "context_reason_codes": reason_codes,
        "advisory_status": "ADVISORY_ONLY",
        "real_money_execution": "PROHIBITED",
        "broker_api_called": False,
    }


# ==========================================================================
# Corpus readiness checker
# ==========================================================================
def check_decision_capture_corpus(path: str) -> dict[str, Any]:
    """Inspect a forward-logged decisions.jsonl and report calibration readiness."""
    p = Path(path)
    if not p.exists():
        return {"status": NO_CORPUS_FOUND, "path": path, "total_snapshots": 0,
                "advisory_status": "ADVISORY_ONLY"}

    snapshots: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                snapshots.append(json.loads(line))
            except Exception:
                continue

    if not snapshots:
        return {"status": NO_CORPUS_FOUND, "path": path, "total_snapshots": 0,
                "advisory_status": "ADVISORY_ONLY"}

    unresolved = resolved = eligible = synthetic = 0
    schema_versions: dict[str, int] = {}
    missing_fields: dict[str, int] = {}
    dates: list[str] = []
    required_top = ("identity", "mythos", "aggregation", "ledger", "outcome")

    for s in snapshots:
        outcome = s.get("outcome", {})
        label = outcome.get("outcome_label", INCONCLUSIVE)
        final_status = outcome.get("final_outcome_status")
        stype = s.get("source_type")
        if label == INCONCLUSIVE or final_status == OPEN_OR_UNRESOLVED:
            unresolved += 1
        if label in _RESOLVED:
            resolved += 1
        if s.get("calibratable") and stype in ELIGIBLE_SOURCE_TYPES and label in _RESOLVED:
            eligible += 1
        if stype == SYNTHETIC_FIXTURE:
            synthetic += 1
        sv = s.get("schema_version", "unknown")
        schema_versions[sv] = schema_versions.get(sv, 0) + 1
        for grp in required_top:
            if grp not in s:
                missing_fields[grp] = missing_fields.get(grp, 0) + 1
        created = (s.get("metadata", {}) or {}).get("created_at") or ""
        if created:
            dates.append(created)

    if eligible >= MIN_STRONGER:
        status = STRONGER_CALIBRATION_READY
    elif eligible >= MIN_FIRST_PASS:
        status = FIRST_PASS_CALIBRATION_READY
    elif eligible >= MIN_PROVISIONAL:
        status = PROVISIONAL_DIAGNOSTIC_READY
    else:
        status = CAPTURE_STARTED_NO_LABELS

    return {
        "status": status, "path": path,
        "total_snapshots": len(snapshots),
        "unresolved": unresolved, "resolved": resolved,
        "calibration_eligible": eligible, "synthetic_ineligible": synthetic,
        "schema_version_counts": schema_versions,
        "missing_required_fields": missing_fields,
        "first_snapshot_date": (sorted(dates)[0] if dates else None),
        "latest_snapshot_date": (sorted(dates)[-1] if dates else None),
        "thresholds": {"provisional": MIN_PROVISIONAL, "first_pass": MIN_FIRST_PASS,
                       "stronger": MIN_STRONGER},
        "advisory_status": "ADVISORY_ONLY",
    }


# ==========================================================================
# Operational CLI — one safe loop over the existing functions.
#   python -m scripts.signal_arbitrage.advisory_runner [action] [flags]
# Default is read-only / no-write.  Writes happen only with explicit flags.
# ==========================================================================
NO_OBSERVATIONS_PROVIDED = "NO_OBSERVATIONS_PROVIDED"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scripts.signal_arbitrage.advisory_runner",
        description="Mythos->Fable advisory/capture/calibration operational loop "
                    "(advisory-only; never executes real-money trades; no writes by default).")
    # actions (default = advisory run)
    p.add_argument("--check-corpus", action="store_true",
                   help="Report calibration-readiness of the decisions corpus (read-only).")
    p.add_argument("--resolve-outcome", action="store_true",
                   help="Attach a realized outcome to a captured decision.")
    p.add_argument("--run-calibration", action="store_true",
                   help="Run calibration over resolved eligible records (read-only).")
    # capture controls
    p.add_argument("--capture-decisions", action="store_true",
                   help="Enable forward decision capture (off by default).")
    p.add_argument("--capture-mode", choices=("write", "dry_run"), default="dry_run",
                   help="write actually appends; dry_run computes but never writes (default).")
    p.add_argument("--capture-path", default=DEFAULT_CAPTURE_PATH,
                   help=f"decisions.jsonl path (default {DEFAULT_CAPTURE_PATH}).")
    p.add_argument("--strict-capture", action="store_true",
                   help="Fail the run if capture fails (default: non-fatal).")
    # observation source for an advisory run
    p.add_argument("--demo", action="store_true",
                   help="Use a built-in demo cluster (forced SYNTHETIC_FIXTURE; "
                        "never calibration-eligible).")
    p.add_argument("--observations", default=None,
                   help="Path to a JSON list of observation dicts for a real run.")
    p.add_argument("--source-type", default=None,
                   help="Source type for --observations (default PAPER_TRADE).")
    # outcome resolution
    p.add_argument("--decision-id", default=None)
    p.add_argument("--realized-return", type=float, default=None)
    p.add_argument("--resolved-at", default="")
    p.add_argument("--outcome-label", default=None)
    p.add_argument("--allow-conflict", action="store_true")
    # advisory-run context
    p.add_argument("--run-id", default="")
    p.add_argument("--universe", default="")
    p.add_argument("--decision-date", type=int, default=None)
    return p


def _load_observations(args: argparse.Namespace) -> tuple[list[MythosObservation] | None, str]:
    if args.demo:
        from .mythos_fixtures import multi_source_reality_cluster
        return multi_source_reality_cluster(), SYNTHETIC_FIXTURE  # demo never eligible
    if args.observations:
        from .mythos_corpus import _obs_from_dict
        data = json.loads(Path(args.observations).read_text(encoding="utf-8") or "[]")
        return [_obs_from_dict(o) for o in data], (args.source_type or PAPER_TRADE)
    return None, PAPER_TRADE


def cli(argv: list[str] | None = None) -> dict[str, Any]:
    """Structured CLI dispatch (returns the result dict; ``main`` prints it)."""
    from .mythos_corpus import run_real_calibration
    from .mythos_capture import resolve_decision_outcome
    args = _build_parser().parse_args(argv)
    path = args.capture_path

    if args.check_corpus:
        return check_decision_capture_corpus(path)
    if args.run_calibration:
        return run_real_calibration(records_path=path)
    if args.resolve_outcome:
        update: dict[str, Any] = {"realized_return": args.realized_return}
        if args.outcome_label:
            update["outcome_label"] = args.outcome_label
        mode = "write" if args.capture_mode == "write" else "dry_run"
        rep = resolve_decision_outcome(
            path, args.decision_id or "", update, output_path=path, mode=mode,
            allow_conflict=args.allow_conflict, resolved_at=args.resolved_at)
        return rep.to_dict()

    # default action: advisory run (with optional capture)
    obs, stype = _load_observations(args)
    if obs is None:
        return {"status": NO_OBSERVATIONS_PROVIDED,
                "hint": "supply --demo or --observations <path.json>",
                "advisory_status": "ADVISORY_ONLY", "real_money_execution": "PROHIBITED"}
    cfg = CaptureConfig(enabled=args.capture_decisions, path=path,
                        strict=args.strict_capture, write=(args.capture_mode == "write"),
                        source_type=stype)
    return run_advisory_with_capture(
        obs, capture=cfg, run_id=args.run_id, universe=args.universe,
        decision_date=args.decision_date, decision_timestamp=args.resolved_at,
        runner_name="advisory_runner_cli")


def main(argv: list[str] | None = None) -> int:
    try:
        result = cli(argv)
    except CaptureError as exc:
        print(json.dumps({"status": CAPTURE_FAILED_STRICT, "error": str(exc),
                          "advisory_status": "ADVISORY_ONLY"}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


__all__ = [
    "CaptureConfig", "CaptureError", "resolve_capture_config",
    "run_advisory_with_capture", "check_decision_capture_corpus",
    "cli", "main", "NO_OBSERVATIONS_PROVIDED",
    "PIPELINE_VERSION", "DEFAULT_CAPTURE_PATH",
    "CAPTURE_DISABLED", "CAPTURE_DRY_RUN", "CAPTURE_WRITTEN", "DUPLICATE_SKIPPED",
    "CAPTURE_FAILED_NON_FATAL", "CAPTURE_FAILED_STRICT",
    "NO_CORPUS_FOUND", "CAPTURE_STARTED_NO_LABELS", "PROVISIONAL_DIAGNOSTIC_READY",
    "FIRST_PASS_CALIBRATION_READY", "STRONGER_CALIBRATION_READY",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
