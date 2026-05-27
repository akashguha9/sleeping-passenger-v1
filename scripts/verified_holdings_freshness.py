"""verified_current_holdings.json freshness guard.

proof_loop_hardening_sprint, Phase 13.

Computes a freshness state for ``data/daily_payload/verified_current_holdings.json``
so the rest of the system (Moltbook learning, reconciliation) can warn
when the manual truth file has become stale.

Status table::

    file missing                   -> MISSING
    file unreadable                -> UNREADABLE
    holdings_age_days <= 1         -> FRESH
    1 <  holdings_age_days <= 3    -> AGING
    holdings_age_days >  3         -> STALE

This module is *advisory*.  It NEVER mutates SQLite.  It never blocks
operator workflows on its own.  Callers (Moltbook write paths, the
cockpit warning panel) decide what to do with the status.

Safety
~~~~~~
* Read-only.  No DB writes, no network.
* No broker / order / fill / position / execution path.
* Advisory-only stamps on every output.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]


SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}


STATUS_MISSING = "MISSING"
STATUS_UNREADABLE = "UNREADABLE"
STATUS_FRESH = "FRESH"
STATUS_AGING = "AGING"
STATUS_STALE = "STALE"

DEFAULT_HOLDINGS_PATH = (
    _REPO_ROOT / "data" / "daily_payload" / "verified_current_holdings.json"
)


@dataclass(frozen=True)
class VerifiedHoldingsFreshness:
    status: str
    age_days: float | None
    run_date: str | None
    path: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified_holdings_status": self.status,
            "verified_holdings_age_days": (
                round(self.age_days, 4) if self.age_days is not None else None
            ),
            "verified_holdings_run_date": self.run_date,
            "verified_holdings_path": self.path,
            "note": self.note,
            **SAFETY_STAMPS,
        }


def _parse_run_date(text: str | None) -> datetime | None:
    if not text:
        return None
    candidates = (text.strip(), text.strip() + "T00:00:00+00:00")
    for raw in candidates:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def compute_freshness(
    *,
    path: Path | None = None,
    now: datetime | None = None,
) -> VerifiedHoldingsFreshness:
    p = Path(path) if path is not None else DEFAULT_HOLDINGS_PATH
    now = now or datetime.now(timezone.utc)
    if not p.exists():
        return VerifiedHoldingsFreshness(
            status=STATUS_MISSING,
            age_days=None,
            run_date=None,
            path=str(p),
            note="verified_current_holdings.json missing",
        )
    try:
        body = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return VerifiedHoldingsFreshness(
            status=STATUS_UNREADABLE,
            age_days=None,
            run_date=None,
            path=str(p),
            note="verified_current_holdings.json could not be parsed",
        )
    run_date_raw = body.get("run_date") if isinstance(body, dict) else None
    run_dt = _parse_run_date(run_date_raw)
    if run_dt is None:
        return VerifiedHoldingsFreshness(
            status=STATUS_UNREADABLE,
            age_days=None,
            run_date=str(run_date_raw or ""),
            path=str(p),
            note="verified_current_holdings.json missing or invalid run_date",
        )
    age_sec = (now - run_dt).total_seconds()
    age_days = max(0.0, age_sec / 86400.0)
    if age_days <= 1.0:
        status = STATUS_FRESH
        note = "verified holdings fresh (<= 1 day)"
    elif age_days <= 3.0:
        status = STATUS_AGING
        note = "verified holdings aging (1-3 days)"
    else:
        status = STATUS_STALE
        note = "verified holdings stale (> 3 days) — Moltbook writes should warn"
    return VerifiedHoldingsFreshness(
        status=status,
        age_days=age_days,
        run_date=str(run_date_raw or ""),
        path=str(p),
        note=note,
    )


def is_safe_for_moltbook_writes(state: VerifiedHoldingsFreshness) -> bool:
    """Policy: Moltbook writes are safe when state is FRESH or AGING.

    STALE / MISSING / UNREADABLE → unsafe; callers should warn or
    refuse.  This function does not enforce the policy; it reports it.
    """
    return state.status in (STATUS_FRESH, STATUS_AGING)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute verified_current_holdings.json freshness state.  "
            "Advisory only.  Never mutates state."
        )
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_HOLDINGS_PATH,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the freshness JSON to this path.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    state = compute_freshness(path=Path(args.path))
    payload = state.to_dict()
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(
            f"verified_holdings_status={state.status} age_days="
            f"{round(state.age_days, 4) if state.age_days is not None else 'NA'} "
            f"path={state.path}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
