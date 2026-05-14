"""
Source refresh audit — proves source-discipline cadence without calling APIs.

Purpose
-------
The live-source registry already classifies sources as implemented /
partial / planned and reports per-source freshness. This audit rolls
those into operator-facing counts and computes cadence-compliance /
reliability scores from the SQLite ``source_run_log`` history, *if
present*.

Read-only.  Never calls a live API.  Never prints secret values.

Safety contract
---------------

    advisory_status        = "ADVISORY_ONLY"
    execution_gate         = "LOCKED"
    broker_api_called      = False
    ai_execution_count     = 0
    execution_permission   = False
    can_execute            = False

Usage
-----
    python scripts/source_refresh_audit.py
    python scripts/source_refresh_audit.py --json
    python scripts/source_refresh_audit.py --days 7 --json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sqlite3
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}


def _default_db_path() -> Path:
    try:
        try:
            from scripts.persistence import DB_PATH  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            from persistence import DB_PATH  # type: ignore[no-redef]
        return Path(DB_PATH)
    except Exception:
        return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


def _import_registry():
    try:
        try:
            from scripts.live_source_registry import (  # type: ignore[import-not-found]
                DEFAULT_REFRESH_HOURS,
                compute_source_freshness,
                detect_source_credential_state,
                list_live_source_families,
            )
        except ModuleNotFoundError:
            from live_source_registry import (  # type: ignore[no-redef]
                DEFAULT_REFRESH_HOURS,
                compute_source_freshness,
                detect_source_credential_state,
                list_live_source_families,
            )
        return (
            DEFAULT_REFRESH_HOURS,
            list_live_source_families,
            detect_source_credential_state,
            compute_source_freshness,
        )
    except Exception:
        return None


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.Error:
            return None
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _run_history(
    conn: sqlite3.Connection, since_iso: str | None
) -> list[dict[str, Any]]:
    if not _table_exists(conn, "source_run_log"):
        return []
    try:
        if since_iso:
            rows = conn.execute(
                "SELECT source_name, status, fetched_count, skipped_reason,"
                " error_message, timestamp_utc, duration_ms"
                " FROM source_run_log WHERE timestamp_utc >= ?",
                (since_iso,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT source_name, status, fetched_count, skipped_reason,"
                " error_message, timestamp_utc, duration_ms"
                " FROM source_run_log"
            ).fetchall()
    except sqlite3.Error:
        return []
    return [dict(r) for r in rows]


def _latest_per_source(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = str(r.get("source_name") or "")
        ts = str(r.get("timestamp_utc") or "")
        if key not in latest or ts > str(latest[key].get("timestamp_utc") or ""):
            latest[key] = r
    return list(latest.values())


def _summarize_failure_reasons(
    rows: list[dict[str, Any]], limit: int = 5
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for r in rows:
        status = str(r.get("status") or "").upper()
        if status in {"FAIL", "ERROR"}:
            reason = (
                str(r.get("error_message") or "") or
                str(r.get("skipped_reason") or "") or
                "unspecified"
            )
            # Truncate noisy stack traces to first 120 chars to avoid log bloat.
            reason = reason.strip()[:120] or "unspecified"
            counts[reason] = counts.get(reason, 0) + 1
    out = sorted(
        ({"reason": k, "count": v} for k, v in counts.items()),
        key=lambda d: (-d["count"], d["reason"]),
    )
    return out[:limit]


def _source_reliability(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Per-source: successful_runs / total_attempts."""
    totals: dict[str, dict[str, int]] = {}
    for r in rows:
        key = str(r.get("source_name") or "")
        if not key:
            continue
        totals.setdefault(key, {"ok": 0, "skip": 0, "fail": 0, "total": 0})
        status = str(r.get("status") or "").upper()
        totals[key]["total"] += 1
        if status == "OK":
            totals[key]["ok"] += 1
        elif status in {"SKIP", "SKIPPED"}:
            totals[key]["skip"] += 1
        elif status in {"FAIL", "ERROR"}:
            totals[key]["fail"] += 1
    out: dict[str, dict[str, Any]] = {}
    for key, t in totals.items():
        denom = max(1, t["total"])
        out[key] = {
            "total_attempts": t["total"],
            "ok_count": t["ok"],
            "skip_count": t["skip"],
            "fail_count": t["fail"],
            "reliability_score": round(t["ok"] / denom, 6),
        }
    return out


def _cadence_compliance(
    rows: list[dict[str, Any]],
    cadence_hours: int,
    window_hours: int,
    now: _dt.datetime,
) -> dict[str, float | None]:
    """Compute on-time / expected per-source over the window."""
    expected = max(1, int(window_hours / max(1, cadence_hours)))
    per_source_ok: dict[str, int] = {}
    seen_sources: set[str] = set()
    for r in rows:
        seen_sources.add(str(r.get("source_name") or ""))
        if str(r.get("status") or "").upper() == "OK":
            per_source_ok[str(r.get("source_name") or "")] = (
                per_source_ok.get(str(r.get("source_name") or ""), 0) + 1
            )
    out: dict[str, float | None] = {}
    for src in seen_sources:
        ok = per_source_ok.get(src, 0)
        out[src] = round(min(ok / expected, 1.0), 6)
    return out


def run_audit(
    db_path: Path | None = None,
    *,
    days: int | None = None,
    now: _dt.datetime | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the source refresh audit payload.

    Parameters
    ----------
    db_path : Path | None
        Defaults to persistence.DB_PATH.
    days : int | None
        Filter run history to the last N days. ``None`` returns all-time.
    now : datetime | None
        Override the current time for tests.
    env : dict | None
        Override environment for credential checks.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    path = Path(db_path) if db_path else _default_db_path()

    warnings: list[str] = []
    payload: dict[str, Any] = {
        "report": "source_refresh_audit",
        "db_path": str(path),
        "days_window": int(days) if days else None,
        "cadence_hours": 6,
        "ok": False,
        "warnings": warnings,
        "operator_action": "",
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    payload.update(_SAFETY_STAMPS)

    bundle = _import_registry()
    if bundle is None:
        warnings.append("live_source_registry_unavailable")
        payload["operator_action"] = (
            "scripts/live_source_registry.py could not be imported. The "
            "audit cannot continue without it."
        )
        return payload

    default_cadence, list_sources, detect_creds, compute_freshness = bundle
    payload["cadence_hours"] = int(default_cadence)

    sources = list_sources()
    payload["source_count"] = len(sources)
    payload["implemented_count"] = sum(
        1 for s in sources if s["adapter_status"] == "implemented"
    )
    payload["partial_count"] = sum(
        1 for s in sources if s["adapter_status"] == "partial"
    )
    payload["planned_count"] = sum(
        1 for s in sources if s["adapter_status"] == "planned"
    )

    cred_state = detect_creds(env=env)
    payload["credential_missing_count"] = sum(
        1 for v in cred_state.values()
        if v.get("requires_api_key") and v.get("missing_env_keys")
    )

    # History from source_run_log.
    since_dt = None
    since_iso = None
    if days and days > 0:
        since_dt = now - _dt.timedelta(days=int(days))
        since_iso = since_dt.isoformat()
    history: list[dict[str, Any]] = []
    if path.exists():
        conn = _readonly_connect(path)
        if conn is None:
            warnings.append("db_open_failed")
        else:
            try:
                history = _run_history(conn, since_iso)
            finally:
                conn.close()
    else:
        warnings.append("db_missing")

    payload["run_history_count"] = len(history)

    if history:
        latest = _latest_per_source(history)
        freshness = compute_freshness(
            latest_runs=latest,
            cadence_hours=int(default_cadence),
            now_epoch=now.timestamp(),
            env=env,
        )
    else:
        freshness = compute_freshness(
            latest_runs=[],
            cadence_hours=int(default_cadence),
            now_epoch=now.timestamp(),
            env=env,
        )

    source_statuses: list[dict[str, Any]] = []
    state_counts: dict[str, int] = {}
    for src in sources:
        key = src["source_key"]
        info = freshness.get(key, {})
        state = info.get("freshness_state", "never_run")
        state_counts[state] = state_counts.get(state, 0) + 1
        source_statuses.append({
            "source_key": key,
            "display_name": src["display_name"],
            "adapter_status": src["adapter_status"],
            "freshness_state": state,
            "credential_configured": info.get("credential_configured"),
            "last_success_at": info.get("last_success_at"),
            "hours_since_last_success": info.get("hours_since_last_success"),
            "next_expected_refresh_at": info.get("next_expected_refresh_at"),
            "advisory_status": ADVISORY_STATUS,
            "execution_gate": EXECUTION_GATE_LOCKED,
            "broker_api_called": False,
            "ai_execution_count": 0,
        })

    payload["source_statuses"] = source_statuses
    payload["fresh_count"] = state_counts.get("fresh", 0)
    payload["stale_count"] = state_counts.get("stale", 0)
    payload["overdue_count"] = state_counts.get("overdue", 0)
    payload["skipped_count"] = state_counts.get("skipped", 0)
    payload["failed_count"] = state_counts.get("failed", 0)
    payload["never_run_count"] = state_counts.get("never_run", 0)

    # Reliability + cadence compliance from history.
    if history:
        payload["source_reliability_scores"] = _source_reliability(history)
        if days and days > 0:
            payload["cadence_compliance_scores"] = _cadence_compliance(
                history, int(default_cadence), int(days) * 24, now,
            )
        else:
            payload["cadence_compliance_scores"] = None
        payload["top_failure_reasons"] = _summarize_failure_reasons(history)
    else:
        payload["source_reliability_scores"] = None
        payload["cadence_compliance_scores"] = None
        payload["top_failure_reasons"] = []
        warnings.append("no_run_history_available")

    # Operator action.
    ok = True
    if payload["failed_count"] > 0:
        ok = False
    if payload["overdue_count"] > payload["fresh_count"]:
        ok = False
    payload["ok"] = ok

    if not ok:
        payload["operator_action"] = (
            "Source health is degraded. Run plan-only refresh to inspect: "
            "`python scripts/run_live_refresh.py --source all --plan-only --json`. "
            "Do NOT make manual trades against overdue narrative sources without "
            "fresh confirmation."
        )
    elif warnings:
        payload["operator_action"] = (
            "Source registry healthy but with warnings (see warnings list). "
            "Re-check after the next refresh cycle."
        )
    else:
        payload["operator_action"] = (
            "Source refresh discipline OK across implemented sources."
        )
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Source Refresh Audit")
    lines.append(f"DB: {payload['db_path']}")
    lines.append(
        f"Sources: {payload.get('source_count', 0)} "
        f"(implemented={payload.get('implemented_count', 0)}, "
        f"partial={payload.get('partial_count', 0)}, "
        f"planned={payload.get('planned_count', 0)})"
    )
    lines.append(
        f"Freshness: fresh={payload.get('fresh_count', 0)}, "
        f"stale={payload.get('stale_count', 0)}, "
        f"overdue={payload.get('overdue_count', 0)}, "
        f"skipped={payload.get('skipped_count', 0)}, "
        f"failed={payload.get('failed_count', 0)}, "
        f"never_run={payload.get('never_run_count', 0)}"
    )
    if payload.get("warnings"):
        lines.append("Warnings: " + ", ".join(payload["warnings"]))
    lines.append(f"RESULT: {'PASS' if payload['ok'] else 'FAIL'}")
    lines.append("")
    lines.append("Operator action:")
    lines.append(f"  {payload['operator_action']}")
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="source_refresh_audit.py",
        description=(
            "Read-only source refresh / cadence audit. Never calls a live API."
        ),
    )
    p.add_argument("--db-path", type=str, default=None,
                   help="Path to runtime/mvp_local.db (default: persistence).")
    p.add_argument("--days", type=int, default=None,
                   help="Filter run history to the last N days.")
    p.add_argument("--json", action="store_true", help="Emit JSON.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    payload = run_audit(db_path, days=args.days)
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2, default=str))
    else:
        print(_render_text(payload))
    return 0 if payload["ok"] else 1


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "run_audit",
]


if __name__ == "__main__":
    raise SystemExit(main())
