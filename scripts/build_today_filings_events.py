"""Builder — today's ticker-tagged filings/regulatory event payload.

Writes ``data/daily_payload/today_filings_events.json``.

No live filing source (SEC/EDGAR/etc.) is wired, so this writes a valid,
honestly-labelled EMPTY structure (``provider="EMPTY_FALLBACK"``,
``is_live=false``). We never fabricate filings. When a live source is later
wired, each event must carry: ticker, filing_type, timestamp_utc, source,
freshness, source_health, materiality_score, why_today.

Backward compatibility: the loader reads the list under ``events``; we also
mirror it under ``records`` for the fresh-payload synthesis contract.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import REPO_ROOT, ensure_directory, utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from runtime_common import REPO_ROOT, ensure_directory, utc_timestamp


DAILY_PAYLOAD_DIR = REPO_ROOT / "data" / "daily_payload"
FILINGS_EVENTS_PATH = DAILY_PAYLOAD_DIR / "today_filings_events.json"

VALID_FILING_TYPES = ("8-K", "10-Q", "10-K", "insider", "regulatory", "earnings")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_directory(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def normalize_filing_event(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce a (future, live) filing row into the canonical event shape.

    Used when a real EDGAR/regulatory source is wired. Pure/null-safe.
    """
    filing_type = str(raw.get("filing_type") or "regulatory")
    if filing_type not in VALID_FILING_TYPES:
        filing_type = "regulatory"
    return {
        "ticker": str(raw.get("ticker") or "").strip().upper(),
        "filing_type": filing_type,
        "timestamp_utc": raw.get("timestamp_utc"),
        "source": raw.get("source") or "UNVERIFIED",
        "freshness": str(raw.get("freshness") or "UNVERIFIED"),
        "source_health": str(raw.get("source_health") or "UNVERIFIED"),
        "is_live": bool(raw.get("is_live", False)),
        "provider": str(raw.get("provider") or "EMPTY_FALLBACK"),
        "materiality_score": raw.get("materiality_score"),
        "why_today": raw.get("why_today")
        or "Fresh filing/regulatory event detected.",
    }


def build_today_filings_events(
    run_date: str,
    generated_at_utc: str | None = None,
    live_events: list[dict[str, Any]] | None = None,
    live_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the filings-events payload (pure; honest empty fallback).

    Two live paths:
      * bridge path (``live_meta`` supplied): ``live_events`` are already
        normalized signal_events-bridge rows; the envelope comes from
        ``live_meta`` (honest is_live/source_health derived from fresh rows).
      * legacy path (``live_meta`` is None): ``live_events`` are raw provider
        rows coerced via :func:`normalize_filing_event`.
    """
    if live_events and live_meta is not None:
        return {
            "run_date": run_date,
            "generated_at_utc": generated_at_utc or utc_timestamp(),
            "source_health": live_meta.get("source_health", "DEGRADED_LIVE_UNMAPPED"),
            "provider": live_meta.get("provider", "SIGNAL_EVENTS_BRIDGE"),
            "is_live": bool(live_meta.get("is_live", True)),
            "executable_allowed": bool(live_meta.get("executable_allowed", False)),
            "bridge_diagnostics": live_meta.get("diagnostics", {}),
            "events": live_events,
            "records": live_events,
        }
    if live_events:
        events = [normalize_filing_event(e) for e in live_events if isinstance(e, dict)]
        provider = "LIVE_FILING_SOURCE"
        source_health = "PARTIAL"
        is_live = True
    else:
        events = []
        provider = "EMPTY_FALLBACK"
        source_health = "UNVERIFIED"
        is_live = False
    return {
        "run_date": run_date,
        "generated_at_utc": generated_at_utc or utc_timestamp(),
        "source_health": source_health,
        "provider": provider,
        "is_live": is_live,
        "executable_allowed": False,
        "fallback_reason": (live_meta or {}).get("fallback_reason", "NO_FRESH_SIGNAL_EVENTS")
        if not live_events
        else None,
        "events": events,
        "records": events,
    }


def write_today_filings_events(
    run_date: str,
    path: Path | None = None,
    generated_at_utc: str | None = None,
    live_events: list[dict[str, Any]] | None = None,
    live_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = build_today_filings_events(run_date, generated_at_utc, live_events, live_meta)
    _write_json(path or FILINGS_EVENTS_PATH, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build today's filings/regulatory event payload.")
    parser.add_argument("--run-date", default=None, help="YYYY-MM-DD (default: today UTC)")
    args = parser.parse_args(argv)
    run_date = args.run_date or utc_timestamp()[:10]
    payload = write_today_filings_events(run_date)
    sys.stdout.write(
        f"today_filings_events.json written: source_health={payload['source_health']} "
        f"is_live={payload['is_live']} events={len(payload['events'])}\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
