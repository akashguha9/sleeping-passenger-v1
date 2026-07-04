"""Operator alert bridge — one push-style alert channel, no new secrets.

Feed-the-Loop sprint (2026-07-04).  Every failure signal in this system was
pull-based (logs, JSON records, exit codes); nothing ever *told* the
operator.  This module is the simplest honest channel that works offline:

* an append-only JSONL queue at ``runtime/alerts/operator_alerts.jsonl``
  (one alert per line, never rewritten),
* a ``runtime/alerts/latest_alerts.json`` snapshot for the truth surface
  and the frontend cockpit,
* console output (the scheduler's stdout lands in the scheduled-task log).

No email, no webhook, no credentials — deliberately.  If a webhook/email is
configured later it can consume the same queue.

Alert shape::

    alert_id, created_at, severity ∈ {INFO, WARNING, CRITICAL}, category,
    title, message, source, dedupe_key, requires_operator_action, run_id

Dedupe::

    dedupe_key = SHA256(category + source + normalized_message + date_bucket)

One alert per condition per day — a BLOCKED state that persists re-alerts
tomorrow, not every cycle.

Triggers (from the operational truth surface): BROKEN/BLOCKED overall state,
missing/unconfirmed stops, leveraged positions without usable stops, stale
holdings, stale artifacts, zero evidence velocity after the producer is
scheduled, maturation failure, zero-persist sinks, scheduler failure,
provider canary fail.

Advisory-only: this module only reads status and writes its own queue.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:  # package layout
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.runtime_common import REPO_ROOT, write_json_atomic
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from runtime_common import REPO_ROOT, write_json_atomic  # type: ignore[no-redef]

ALERTS_DIR = REPO_ROOT / "runtime" / "alerts"
QUEUE_PATH = ALERTS_DIR / "operator_alerts.jsonl"
LATEST_PATH = ALERTS_DIR / "latest_alerts.json"


def _resolved(default: Path) -> Path:
    """Honor NBI_ARTIFACT_DIR (test isolation, same convention as the NBI
    exporters): hermetic tests must never write the operator's real queue."""
    import os as _os

    override = _os.environ.get("NBI_ARTIFACT_DIR")
    if not override:
        return default
    d = Path(override) / "alerts"
    d.mkdir(parents=True, exist_ok=True)
    return d / default.name

SEV_INFO = "INFO"
SEV_WARNING = "WARNING"
SEV_CRITICAL = "CRITICAL"


def _now(now_utc: datetime | None) -> datetime:
    return now_utc or datetime.now(timezone.utc)


def _normalize(message: str) -> str:
    """Strip volatile numbers so the same condition dedupes across cycles."""
    return re.sub(r"[0-9]+(\.[0-9]+)?", "#", message).strip().lower()


def dedupe_key(category: str, source: str, message: str, date_bucket: str) -> str:
    raw = f"{category}|{source}|{_normalize(message)}|{date_bucket}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _alert(
    *, now: datetime, severity: str, category: str, title: str, message: str,
    source: str, requires_operator_action: bool, run_id: str | None,
) -> dict[str, Any]:
    date_bucket = now.strftime("%Y-%m-%d")
    key = dedupe_key(category, source, message, date_bucket)
    return {
        "alert_id": f"AL_{date_bucket}_{key[:12]}",
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "severity": severity,
        "category": category,
        "title": title,
        "message": message,
        "source": source,
        "dedupe_key": key,
        "requires_operator_action": bool(requires_operator_action),
        "run_id": run_id,
    }


def build_alerts_from_surface(
    surface: dict[str, Any],
    *,
    now_utc: datetime | None = None,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Map the operational truth surface onto the alert trigger list."""
    now = _now(now_utc)
    alerts: list[dict[str, Any]] = []

    def add(severity: str, category: str, title: str, message: str,
            action: bool = True, source: str = "truth_surface") -> None:
        alerts.append(_alert(
            now=now, severity=severity, category=category, title=title,
            message=message, source=source,
            requires_operator_action=action, run_id=run_id,
        ))

    state = surface.get("overall_operational_state")
    if state == "BROKEN":
        add(SEV_CRITICAL, "operational_state", "System BROKEN",
            "; ".join(surface.get("state_reasons", [])) or "state BROKEN")
    elif state == "BLOCKED":
        add(SEV_CRITICAL, "operational_state", "System BLOCKED",
            "; ".join(surface.get("state_reasons", [])) or "state BLOCKED")

    missing = int(surface.get("missing_stop_count") or 0)
    unconfirmed = int(surface.get("unconfirmed_stop_count") or 0)
    if missing or unconfirmed:
        add(SEV_WARNING, "missing_stops", "Stops missing or unconfirmed",
            f"{missing} missing, {unconfirmed} unconfirmed of "
            f"{surface.get('canonical_holding_count')} holdings — run "
            "scripts/holdings_truth_gate.py --write-template, confirm, then "
            "--apply-confirmed --write")
    if int(surface.get("leveraged_without_stop_count") or 0):
        add(SEV_CRITICAL, "leveraged_missing_stop",
            "LEVERAGED positions without usable stops",
            f"{surface.get('leveraged_without_stop_count')} leveraged "
            "position(s) carry no confirmed stop — largest un-instrumented "
            "loss path in the book")
    if surface.get("holdings_truth_status") in (
        "HOLDINGS_TRUTH_STALE", "HOLDINGS_TRUTH_MISSING",
        "HOLDINGS_TRUTH_INVALID",
    ):
        add(SEV_WARNING, "stale_holdings", "Holdings truth not current",
            f"status={surface.get('holdings_truth_status')} age_minutes="
            f"{surface.get('holdings_freshness_age_minutes')}")

    arts = surface.get("artifacts") or {}
    stale_arts = [
        name for name, info in arts.items()
        if not info.get("exists")
        or (info.get("age_minutes") is not None
            and info["age_minutes"] > 26 * 60)
    ]
    if stale_arts:
        add(SEV_WARNING, "stale_artifacts", "Operator artifacts stale",
            f"stale/missing: {', '.join(sorted(stale_arts))}")

    if surface.get("producer_scheduled") and (
        (surface.get("evidence_velocity_7d") or 0) == 0
    ):
        add(SEV_WARNING, "evidence_velocity", "Evidence velocity is zero",
            "no new locked predictions in 7 days despite the scheduled "
            "producer — the compounding loop has stalled")
    if str(surface.get("scheduler_status", "")).startswith(
        ("BROKEN", "FAILED")
    ) or "MATURATION_CRASHED" in str(surface.get("scheduler_status", "")):
        add(SEV_CRITICAL, "scheduler_failure", "Scheduler run failed",
            f"last scheduler status: {surface.get('scheduler_status')}")

    rows = (surface.get("rows_persisted_status") or {}).get("sources", {})
    silent = [k for k, v in rows.items() if v.get("status") != "OK"]
    if silent:
        add(SEV_WARNING, "rows_persisted", "Sinks persisting nothing",
            f"zero-persist beyond tolerance: {', '.join(sorted(silent))}")

    canary = surface.get("provider_canary_status")
    if canary and canary != "PASS":
        add(SEV_WARNING, "provider_canary", "Provider canary failing",
            f"canary status: {canary}")
    if surface.get("fresh_discovery_status") in ("BLOCKED", "BROKEN"):
        add(SEV_WARNING, "fresh_discovery", "Fresh discovery blocked",
            f"discovery status: {surface.get('fresh_discovery_status')}")
    return alerts


def _existing_keys_today(queue_path: Path, date_bucket: str) -> set[str]:
    keys: set[str] = set()
    if not queue_path.exists():
        return keys
    for line in queue_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("created_at", "")).startswith(date_bucket):
            keys.add(str(row.get("dedupe_key")))
    return keys


def dispatch_alerts(
    alerts: list[dict[str, Any]],
    *,
    write: bool = False,
    queue_path: Any = None,
    latest_path: Any = None,
    now_utc: datetime | None = None,
    echo: bool = True,
) -> dict[str, Any]:
    """Dedupe against today's queue, append new alerts, refresh the snapshot."""
    now = _now(now_utc)
    qpath = Path(queue_path) if queue_path else _resolved(QUEUE_PATH)
    lpath = Path(latest_path) if latest_path else _resolved(LATEST_PATH)
    date_bucket = now.strftime("%Y-%m-%d")
    seen = _existing_keys_today(qpath, date_bucket)
    fresh = [a for a in alerts if a["dedupe_key"] not in seen]
    deduped = len(alerts) - len(fresh)
    if write and fresh:
        qpath.parent.mkdir(parents=True, exist_ok=True)
        with open(qpath, "a", encoding="utf-8") as fh:
            for a in fresh:
                fh.write(json.dumps(a, ensure_ascii=False) + "\n")
    if write:
        lpath.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(lpath, {
            "report": "latest_operator_alerts",
            "generated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "alerts": alerts,
            "new_this_dispatch": len(fresh),
            "deduped_this_dispatch": deduped,
            **advisory_safety_stamps(),
        })
    if echo:
        for a in fresh:
            print(f"[ALERT {a['severity']}] {a['title']} — {a['message']}")
    return {
        "report": "operator_alert_dispatch",
        "generated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "alerts_evaluated": len(alerts),
        "alerts_new": len(fresh),
        "alerts_deduped": deduped,
        "write_mode": bool(write),
        "queue_path": str(qpath),
        **advisory_safety_stamps(),
    }


def latest_alerts(
    *, latest_path: Any = None, limit: int = 10
) -> list[dict[str, Any]]:
    """Most recent alert snapshot for the truth surface / frontend."""
    lpath = Path(latest_path) if latest_path else _resolved(LATEST_PATH)
    try:
        payload = json.loads(lpath.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    alerts = payload.get("alerts", [])
    return alerts[:limit] if isinstance(alerts, list) else []


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dispatch", action="store_true",
                   help="write to the queue (dry-run otherwise)")
    p.add_argument("--dry-run", action="store_true", help="explicit dry-run")
    args = p.parse_args(argv)
    try:
        from scripts.truth_surface_report import compute_truth_surface
    except ModuleNotFoundError:  # pragma: no cover
        from truth_surface_report import compute_truth_surface  # type: ignore
    surface = compute_truth_surface()
    alerts = build_alerts_from_surface(surface)
    result = dispatch_alerts(alerts, write=args.dispatch and not args.dry_run)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
