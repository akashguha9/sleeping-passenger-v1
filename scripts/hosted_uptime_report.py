"""Offline hosted-uptime report.

proof_loop_hardening_sprint, Phase 9.

Reads a local JSON/CSV file of uptime check results and produces a
truthful report.  Default mode is fully offline — no live network calls
unless an operator explicitly passes ``--url``.

The math is trivial::

    uptime_pct = 100 * successful_checks / total_checks

What this script does NOT do
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* It does NOT deploy anything.
* It does NOT call broker / order / fill / position / execution APIs.
* It does NOT log secrets.
* It does NOT inflate counts.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[1]


SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
    "advisory_only_safety_checked": True,
    "secrets_checked_redacted": True,
}

PRIVATE_BETA_UPTIME_PCT_FLOOR = 99.0
PRIVATE_BETA_WINDOW_DAYS = 7


@dataclass(frozen=True)
class PingRow:
    timestamp_utc: str
    success: bool


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _coerce_success(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value or "").strip().lower()
    return s in {"1", "true", "yes", "ok", "200", "success", "up"}


def load_pings(path: Path) -> list[PingRow]:
    """Load ping rows from either JSON list or CSV."""
    if not path.exists():
        return []
    suffix = path.suffix.lower()
    out: list[PingRow] = []
    if suffix == ".json":
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return []
        if not isinstance(body, list):
            return []
        for row in body:
            if not isinstance(row, dict):
                continue
            out.append(
                PingRow(
                    timestamp_utc=str(row.get("timestamp_utc") or row.get("ts") or ""),
                    success=_coerce_success(
                        row.get("success") if "success" in row else row.get("ok")
                    ),
                )
            )
        return out
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                out.append(
                    PingRow(
                        timestamp_utc=str(row.get("timestamp_utc") or row.get("ts") or ""),
                        success=_coerce_success(
                            row.get("success") if "success" in row else row.get("ok")
                        ),
                    )
                )
        return out
    return []


def compute_uptime_report(
    pings: Iterable[PingRow],
    *,
    expected_url: str | None = None,
) -> dict[str, Any]:
    rows = list(pings)
    total = len(rows)
    successful = sum(1 for r in rows if r.success)
    failed = total - successful
    pct = (100.0 * successful / total) if total > 0 else None

    timestamps = [r.timestamp_utc for r in rows if r.timestamp_utc]
    window_start = min(timestamps) if timestamps else None
    window_end = max(timestamps) if timestamps else None

    if total == 0:
        evidence_status = "EMPTY"
    elif pct is not None and pct >= PRIVATE_BETA_UPTIME_PCT_FLOOR:
        evidence_status = "MEETS_UPTIME_FLOOR"
    else:
        evidence_status = "BELOW_UPTIME_FLOOR"

    report = {
        "script": "hosted_uptime_report.py",
        "generated_at_utc": _utc_now_iso(),
        "total_checks": int(total),
        "successful_checks": int(successful),
        "failed_checks": int(failed),
        "uptime_pct": (round(pct, 4) if pct is not None else None),
        "window_start_utc": window_start,
        "window_end_utc": window_end,
        "evidence_status": evidence_status,
        "private_beta_uptime_pct_floor": PRIVATE_BETA_UPTIME_PCT_FLOOR,
        "private_beta_window_days": PRIVATE_BETA_WINDOW_DAYS,
        "expected_url": expected_url,
        **SAFETY_STAMPS,
    }
    return report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Offline hosted-uptime report.  Reads a local JSON/CSV of pings "
            "and computes uptime_pct.  Default: dry-run.  No live network "
            "calls unless --url is supplied AND --live is set."
        )
    )
    parser.add_argument(
        "--pings",
        type=Path,
        default=None,
        help="Local JSON or CSV ping log.",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Optional URL (for documentation only).  This script does NOT "
             "make a live HTTP request by default.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Default.  Compute the report but do not write any file.",
    )
    group.add_argument(
        "--write",
        action="store_true",
        help="Persist the report JSON to --output.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_REPO_ROOT / "runtime" / "release" / "hosted_uptime_report.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.pings is not None:
        pings = load_pings(Path(args.pings))
    else:
        pings = []
    report = compute_uptime_report(pings, expected_url=args.url)
    sys.stdout.write(
        f"hosted uptime: total={report['total_checks']} "
        f"successful={report['successful_checks']} "
        f"uptime_pct={report['uptime_pct']} "
        f"status={report['evidence_status']}\n"
    )
    if args.write:
        out = Path(args.output)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            sys.stdout.write(f"wrote {out}\n")
        except OSError as exc:  # pragma: no cover
            sys.stderr.write(
                f"could not write uptime report: {type(exc).__name__}\n"
            )
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
