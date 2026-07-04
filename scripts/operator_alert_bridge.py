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


# ---------------------------------------------------------------------------
# Open-the-Gate sprint (2026-07-04): escalation + operator checklist
# ---------------------------------------------------------------------------

ESCALATE_L2_HOURS = 24.0
ESCALATE_L3_HOURS = 72.0

CHECKLIST_PATH = REPO_ROOT / "OPERATOR_ACTION_CHECKLIST.md"


def compute_escalations(
    *, queue_path: Any = None, now_utc: datetime | None = None,
) -> list[dict[str, Any]]:
    """Escalate CRITICAL conditions that persist across days.

    A CRITICAL category first seen more than 24h ago that is STILL being
    raised today escalates to level 2; more than 72h -> level 3.  A BLOCKED
    truth surface persisting >24h raises a persistent_blocker alert.
    Resolution is implicit: a condition that stops being raised stops
    escalating (its dedupe key no longer appears in today's alerts).
    """
    now = _now(now_utc)
    qpath = Path(queue_path) if queue_path else _resolved(QUEUE_PATH)
    if not qpath.exists():
        return []
    today = now.strftime("%Y-%m-%d")
    first_seen: dict[str, str] = {}
    active_today: dict[str, dict[str, Any]] = {}
    for line in qpath.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("severity") != SEV_CRITICAL:
            continue
        cat = str(row.get("category"))
        created = str(row.get("created_at") or "")
        if cat not in first_seen or created < first_seen[cat]:
            first_seen[cat] = created
        if created.startswith(today):
            active_today[cat] = row
    out: list[dict[str, Any]] = []
    for cat, row in active_today.items():
        try:
            first_dt = datetime.fromisoformat(
                first_seen[cat].replace("Z", "+00:00")
            )
        except ValueError:
            continue
        age_h = (now - first_dt).total_seconds() / 3600.0
        level = 3 if age_h > ESCALATE_L3_HOURS else 2 if age_h > ESCALATE_L2_HOURS else 1
        if level == 1:
            continue
        title = (
            f"ESCALATION L{level}: {row.get('title')}"
            if cat != "operational_state"
            else f"PERSISTENT BLOCKER (L{level}): system not HEALTHY for "
            f"{age_h:.0f}h"
        )
        out.append(_alert(
            now=now, severity=SEV_CRITICAL,
            category=f"escalation_{cat}",
            title=title,
            message=(
                f"CRITICAL condition '{cat}' unresolved for {age_h:.0f} hours "
                f"(first seen {first_seen[cat]}). Escalation level {level}."
            ),
            source="alert_escalation",
            requires_operator_action=True, run_id=None,
        ) | {"escalation_level": level, "unresolved_hours": round(age_h, 1)})
    return out


def generate_operator_checklist(
    surface: dict[str, Any],
    *,
    calendar: dict[str, Any] | None = None,
    now_utc: datetime | None = None,
) -> str:
    """Truth-surface-driven operator checklist (markdown)."""
    now = _now(now_utc)
    state = surface.get("overall_operational_state", "UNKNOWN")
    missing = int(surface.get("missing_stop_count") or 0)
    unconfirmed = int(surface.get("unconfirmed_stop_count") or 0)
    lev = int(surface.get("leveraged_without_stop_count") or 0)
    lines = [
        "# OPERATOR ACTION CHECKLIST",
        "",
        f"_Generated {now.strftime('%Y-%m-%dT%H:%M:%SZ')} from the live "
        f"truth surface. State: **{state}**._",
        "",
        "Work top to bottom; each item names its command.",
        "",
    ]
    n = 0

    def item(text: str, done: bool = False) -> None:
        nonlocal n
        n += 1
        mark = "x" if done else " "
        lines.append(f"{n}. [{mark}] {text}")

    stops_done = missing + unconfirmed == 0
    item(
        "Confirm stop-losses for every position "
        f"({missing} missing, {unconfirmed} unconfirmed): edit "
        "`data/daily_payload/stop_loss_backfill_template.json` per "
        "`STOP_LOSS_CONFIRMATION_REQUIRED.md`, then run "
        "`python scripts/holdings_truth_gate.py --apply-confirmed --write`",
        done=stops_done,
    )
    if lev:
        item(
            f"Review the {lev} LEVERAGED position(s) and set "
            "`leverage_risk_acknowledged: true` only after reading the "
            "max-loss-at-stop numbers in the template",
        )
    item(
        "Refresh holdings truth (set `holdings_confirmed_current: true` + "
        "timestamp in the template before --apply-confirmed) — current "
        f"freshness: {surface.get('holdings_truth_status')}",
        done=surface.get("holdings_truth_status") == "OK",
    )
    item(
        "Re-run the risk gate and read the summary: "
        "`python scripts/holdings_truth_gate.py --show-summary`",
    )
    item(
        "Let the daily loop run (or force one): "
        "`python -m scripts.nbi_scheduler run-once` — it produces locked "
        "predictions, matures due outcomes, harvests settlements, refreshes "
        "discovery, and dispatches alerts",
    )
    item(
        "Prove the Sheets loop when you configure it: "
        "`python scripts/sheets_roundtrip_probe.py --fixture` (logic proof) "
        "or `--live-safe` with SHEETS_PROBE_SHEET_ID set",
    )
    item(
        "Inspect alerts: `runtime/alerts/operator_alerts.jsonl` (or the "
        "cockpit panel) — "
        f"{len(surface.get('latest_alerts') or [])} in the latest snapshot",
    )
    next_maturity = (calendar or {}).get("next_maturity_date")
    projected = (calendar or {}).get("projected_n_end_of_window")
    item(
        "Wait for the next maturity date "
        + (f"({next_maturity}; projected N -> {projected})"
           if next_maturity else "(none pending — produce more predictions)")
        + " — do NOT try to shortcut outcomes",
    )
    lines += [
        "",
        "---",
        "",
        "**DO NOT use real money.** The readiness gates are not passed: "
        f"calibration is {surface.get('calibration_status')} "
        f"(N={surface.get('matured_real_outcome_count')}), risk state is "
        f"{state}. The execution lock stays LOCKED regardless.",
        "",
        f"Next required action (truth surface): "
        f"{surface.get('next_required_operator_action')}",
        "",
    ]
    return "\n".join(lines)


def write_operator_checklist(
    surface: dict[str, Any], *,
    calendar: dict[str, Any] | None = None,
    path: Any = None, now_utc: datetime | None = None,
) -> str:
    target = Path(path) if path else _resolved(CHECKLIST_PATH)
    target.write_text(
        generate_operator_checklist(surface, calendar=calendar,
                                    now_utc=now_utc),
        encoding="utf-8",
    )
    return str(target)


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
    alerts += compute_escalations()
    result = dispatch_alerts(alerts, write=args.dispatch and not args.dry_run)
    if args.dispatch and not args.dry_run:
        try:
            from scripts.evidence_calendar import build_evidence_calendar

            calendar = build_evidence_calendar()
        except Exception:  # noqa: BLE001
            calendar = None
        result["checklist_path"] = write_operator_checklist(
            surface, calendar=calendar
        )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
