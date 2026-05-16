"""Sprint ceiling-push — private operator performance baseline.

Measurement-only.  Walks the read-only surfaces a single-user MVP
already exposes (the SQLite DB, the live-refresh summary JSON, the
backup directory, the calibration gate, the local audit) and emits a
structured timing report.  No optimization is performed; the script
exists to give the operator a stable baseline so a future change can
be judged against it instead of vibes.

Safety
------
* Read-only.  Never mutates the DB or any operator artifact.
* stdlib only — no third-party imports.
* No network calls.
* Never reads ``.env``.  Never prints credentials or secret-shaped values.
* Carries the standard ADVISORY_ONLY / execution_gate=LOCKED stamps.
* Degrades gracefully: if a probe is unavailable the report records
  a ``warnings`` entry instead of raising.

Usage
-----
    python scripts/performance_baseline.py
    python scripts/performance_baseline.py --json
    python scripts/performance_baseline.py --db-path /path/to/mvp_local.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "runtime" / "mvp_local.db"
_REFRESH_SUMMARY = _REPO_ROOT / "logs" / "live_signal_refresh_summary.json"
_BACKUP_ROOT = _REPO_ROOT / "backup_local_state"
_LOGS_DIR = _REPO_ROOT / "logs"

_ADVISORY_STAMPS = {
    "advisory_only": True,
    "advisory_status": "ADVISORY_ONLY",
    "human_execution_required": True,
    "execution_gate": "LOCKED",
    "broker_order_permission": False,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
    "paper_trade_only_for_paper_rows": True,
    "real_capital_at_risk_for_paper_rows": False,
}

_NO_CLAIMS = (
    "Performance baseline is measurement only.",
    "No optimization or scalability claim is implied.",
    "Timings depend on the operator's local hardware and current load.",
)

# Audit-probe timing thresholds.  audit_source_health is dominated by an
# out-of-process scheduler probe on Windows, so a slow run is expected;
# we still want to flag a regression instead of letting it drift.
_AUDIT_SOURCE_HEALTH_WARN_MS = 5000
_AUDIT_SOURCE_HEALTH_SEVERE_MS = 10000


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ms_since(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000.0, 3)


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _user_tables(conn: sqlite3.Connection) -> list[str]:
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    except sqlite3.Error:
        return []
    return [r[0] for r in rows]


def _safe_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return -1


def _dir_size(path: Path) -> tuple[int, int]:
    total = 0
    count = 0
    if not path.is_dir():
        return total, count
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
            count += 1
    return total, count


def _measure_db(db_path: Path, *, top_n: int = 5) -> dict[str, Any]:
    out: dict[str, Any] = {
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "db_size_bytes": None,
        "table_count": 0,
        "top_tables": [],
        "timing_ms": {},
        "warnings": [],
    }
    if not db_path.exists():
        out["warnings"].append("db_missing")
        return out
    try:
        out["db_size_bytes"] = db_path.stat().st_size
    except OSError as exc:
        out["warnings"].append(f"db_stat_failed: {exc}")
    t0 = time.perf_counter()
    conn = _readonly_connect(db_path)
    out["timing_ms"]["open_readonly"] = _ms_since(t0)
    if conn is None:
        out["warnings"].append("db_open_failed")
        return out
    try:
        t0 = time.perf_counter()
        tables = _user_tables(conn)
        out["timing_ms"]["list_tables"] = _ms_since(t0)
        out["table_count"] = len(tables)

        counts: list[dict[str, Any]] = []
        t0 = time.perf_counter()
        for name in tables:
            counts.append({"table": name, "row_count": _safe_count(conn, name)})
        out["timing_ms"]["count_all_tables"] = _ms_since(t0)
        # Top-N by row count, with negative (errored) counts dropped to
        # the bottom.
        counts.sort(key=lambda d: (-d["row_count"] if d["row_count"] >= 0 else 1, d["table"]))
        out["top_tables"] = counts[:top_n]
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass
    return out


def _measure_calibration_gate(db_path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"available": False, "timing_ms": None, "status": None, "warnings": []}
    try:
        try:
            from scripts.calibration_gate import build_report
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from calibration_gate import build_report  # type: ignore[no-redef]
    except Exception as exc:  # pragma: no cover - defensive
        out["warnings"].append(f"import_failed: {type(exc).__name__}")
        return out
    t0 = time.perf_counter()
    try:
        rep = build_report(db_path)
    except Exception as exc:
        out["warnings"].append(f"build_report_failed: {type(exc).__name__}")
        return out
    out["timing_ms"] = _ms_since(t0)
    out["available"] = bool(rep.get("db_available"))
    paper = rep.get("paper") or {}
    real = rep.get("real") or {}
    out["status"] = {
        "paper": paper.get("status"),
        "real": real.get("status"),
    }
    return out


def _measure_audit_section(
    section_name: str,
    fn,  # noqa: ANN001
    *args,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "section": section_name,
        "available": False,
        "timing_ms": None,
        "warnings": [],
    }
    try:
        t0 = time.perf_counter()
        rep = fn(*args)
        out["timing_ms"] = _ms_since(t0)
        out["available"] = True
        if isinstance(rep, dict):
            # Surface a couple of stable scalar fields so the baseline
            # is comparable across runs, but never copy any list/dict
            # payload that might balloon the output.
            for key in ("paper_trade_count", "real_manual_trade_count", "source_count"):
                if key in rep:
                    out[key] = rep[key]
    except Exception as exc:
        out["warnings"].append(f"section_failed: {type(exc).__name__}")
    return out


def _measure_audit(db_path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"available": False, "sections": {}, "warnings": []}
    try:
        try:
            from scripts.local_mvp_audit import (
                paper_ledger_section,
                source_health_section,
            )
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from local_mvp_audit import (  # type: ignore[no-redef]
                paper_ledger_section,
                source_health_section,
            )
    except Exception as exc:  # pragma: no cover - defensive
        out["warnings"].append(f"import_failed: {type(exc).__name__}")
        return out
    out["available"] = True
    out["sections"]["paper_ledger"] = _measure_audit_section(
        "paper_ledger", paper_ledger_section, db_path
    )
    out["sections"]["source_health"] = _measure_audit_section(
        "source_health", source_health_section
    )
    return out


def _measure_refresh_summary() -> dict[str, Any]:
    out: dict[str, Any] = {
        "path": str(_REFRESH_SUMMARY),
        "exists": _REFRESH_SUMMARY.exists(),
        "size_bytes": None,
        "timing_ms": None,
        "last_run_at": None,
        "warnings": [],
    }
    if not _REFRESH_SUMMARY.exists():
        out["warnings"].append("refresh_summary_missing")
        return out
    try:
        out["size_bytes"] = _REFRESH_SUMMARY.stat().st_size
    except OSError as exc:
        out["warnings"].append(f"stat_failed: {exc}")
    t0 = time.perf_counter()
    try:
        text = _REFRESH_SUMMARY.read_text(encoding="utf-8")
    except OSError as exc:
        out["warnings"].append(f"read_failed: {exc}")
        return out
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        out["warnings"].append(f"parse_failed: {exc.msg}")
        return out
    out["timing_ms"] = _ms_since(t0)
    if isinstance(payload, dict):
        for key in (
            "run_started_at",
            "run_finished_at",
            "started_at",
            "finished_at",
        ):
            if key in payload:
                out["last_run_at"] = payload[key]
                break
    return out


def _measure_backups() -> dict[str, Any]:
    out: dict[str, Any] = {
        "backup_root": str(_BACKUP_ROOT),
        "exists": _BACKUP_ROOT.is_dir(),
        "backup_count": 0,
        "total_bytes": 0,
        "latest": None,
        "warnings": [],
    }
    if not _BACKUP_ROOT.is_dir():
        out["warnings"].append("backup_root_missing")
        return out
    backups = sorted(
        [p for p in _BACKUP_ROOT.iterdir() if p.is_dir()],
        key=lambda p: p.name,
    )
    out["backup_count"] = len(backups)
    total, _files = _dir_size(_BACKUP_ROOT)
    out["total_bytes"] = total
    if backups:
        out["latest"] = backups[-1].name
    return out


def _measure_logs() -> dict[str, Any]:
    out: dict[str, Any] = {
        "logs_dir": str(_LOGS_DIR),
        "exists": _LOGS_DIR.is_dir(),
        "total_bytes": 0,
        "file_count": 0,
        "warnings": [],
    }
    if not _LOGS_DIR.is_dir():
        out["warnings"].append("logs_dir_missing")
        return out
    total, count = _dir_size(_LOGS_DIR)
    out["total_bytes"] = total
    out["file_count"] = count
    return out


def build_report(
    db_path: Path = _DEFAULT_DB,
    *,
    include_audit: bool = True,
    include_calibration_gate: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    db = _measure_db(db_path)
    cg = _measure_calibration_gate(db_path) if include_calibration_gate else {
        "available": False,
        "warnings": ["skipped"],
    }
    audit = _measure_audit(db_path) if include_audit else {
        "available": False,
        "warnings": ["skipped"],
    }
    refresh = _measure_refresh_summary()
    backups = _measure_backups()
    logs = _measure_logs()

    timing_ms = {
        "db": db.get("timing_ms") or {},
        "calibration_gate": cg.get("timing_ms"),
        "audit_paper_ledger": (
            audit.get("sections", {}).get("paper_ledger", {}).get("timing_ms")
        ),
        "audit_source_health": (
            audit.get("sections", {}).get("source_health", {}).get("timing_ms")
        ),
        "refresh_summary": refresh.get("timing_ms"),
        "total_ms": _ms_since(started),
    }

    warnings: list[str] = []
    for chunk in (db, cg, audit, refresh, backups, logs):
        warnings.extend(chunk.get("warnings", []))

    # Threshold check — surfaces a regression without claiming
    # optimisation.  Failures here are observability only.
    audit_sh_ms = timing_ms.get("audit_source_health")
    if isinstance(audit_sh_ms, (int, float)):
        if audit_sh_ms >= _AUDIT_SOURCE_HEALTH_SEVERE_MS:
            audit_sh_severity = "severe_warn"
        elif audit_sh_ms >= _AUDIT_SOURCE_HEALTH_WARN_MS:
            audit_sh_severity = "warn"
        else:
            audit_sh_severity = "ok"
    else:
        audit_sh_severity = "unknown"
    timing_thresholds = {
        "audit_source_health_warn_ms": _AUDIT_SOURCE_HEALTH_WARN_MS,
        "audit_source_health_severe_ms": _AUDIT_SOURCE_HEALTH_SEVERE_MS,
        "audit_source_health_severity": audit_sh_severity,
    }
    if audit_sh_severity in {"warn", "severe_warn"}:
        warnings.append(
            f"audit_source_health_slow: {audit_sh_ms} ms "
            f">= {_AUDIT_SOURCE_HEALTH_WARN_MS} ms threshold "
            "(probe is scheduler subprocess on Windows; observability only)"
        )

    return {
        "report": "performance_baseline",
        "generated_at": _utc_iso(),
        "repo_root": str(_REPO_ROOT),
        "db_path": str(db_path),
        "db_exists": db.get("db_exists", False),
        "db_size_bytes": db.get("db_size_bytes"),
        "table_count": db.get("table_count", 0),
        "top_tables": db.get("top_tables", []),
        "table_counts": {
            entry["table"]: entry["row_count"]
            for entry in (db.get("top_tables") or [])
            if isinstance(entry, dict)
        },
        "calibration_gate": cg,
        "audit": audit,
        "refresh_summary": refresh,
        "backups": backups,
        "logs": logs,
        "timing_ms": timing_ms,
        "timing_thresholds": timing_thresholds,
        "warnings": warnings,
        "no_claims": list(_NO_CLAIMS),
        **_ADVISORY_STAMPS,
    }


def _emit_text(report: dict[str, Any]) -> None:
    print("Sleeping Passenger - Performance Baseline")
    print("=" * 41)
    print(f"generated_at      : {report.get('generated_at')}")
    print(f"db_path           : {report.get('db_path')}")
    print(f"db_exists         : {report.get('db_exists')}")
    if report.get("db_exists"):
        size = report.get("db_size_bytes") or 0
        print(f"db_size_bytes     : {size:,}")
        print(f"table_count       : {report.get('table_count')}")
        top = report.get("top_tables") or []
        if top:
            print("top tables:")
            for entry in top:
                print(
                    f"  - {entry.get('table'):<32} {entry.get('row_count'):>12} rows"
                )
    timing = report.get("timing_ms") or {}
    print("")
    print("timing_ms:")
    for key, val in timing.items():
        print(f"  {key:<30} {val}")
    cg = report.get("calibration_gate") or {}
    if cg.get("available"):
        print("")
        status = cg.get("status") or {}
        print(
            f"calibration_gate  : paper={status.get('paper')}  real={status.get('real')}"
        )
    refresh = report.get("refresh_summary") or {}
    if refresh.get("exists"):
        print(
            f"refresh_summary   : size={refresh.get('size_bytes')} bytes  "
            f"last_run_at={refresh.get('last_run_at')}"
        )
    backups = report.get("backups") or {}
    if backups.get("exists"):
        print(
            f"backups           : count={backups.get('backup_count')}  "
            f"latest={backups.get('latest')}  total_bytes={backups.get('total_bytes')}"
        )
    logs_info = report.get("logs") or {}
    if logs_info.get("exists"):
        print(
            f"logs              : files={logs_info.get('file_count')}  "
            f"total_bytes={logs_info.get('total_bytes')}"
        )
    warnings = report.get("warnings") or []
    if warnings:
        print("")
        print("warnings:")
        for w in warnings:
            print(f"  - {w}")
    print("")
    for line in _NO_CLAIMS:
        print(f"NOTE: {line}")
    print(
        "Safety: ADVISORY_ONLY, execution_gate=LOCKED, broker_api_called=false, "
        "ai_execution_count=0, can_execute=false."
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="performance_baseline.py",
        description=(
            "Read-only performance baseline for the private-operator MVP.  "
            "Measures DB size, table counts, key script timings, refresh "
            "summary freshness, backup + log sizes.  No optimization, no "
            "broker call, no order placement."
        ),
    )
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--no-audit",
        action="store_true",
        help="Skip the local_mvp_audit timing probes.",
    )
    p.add_argument(
        "--no-calibration-gate",
        action="store_true",
        help="Skip the calibration_gate timing probe.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = (args.db_path or _DEFAULT_DB).expanduser().resolve()
    report = build_report(
        db,
        include_audit=not args.no_audit,
        include_calibration_gate=not args.no_calibration_gate,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        _emit_text(report)
    return 0


__all__ = ["build_report", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
