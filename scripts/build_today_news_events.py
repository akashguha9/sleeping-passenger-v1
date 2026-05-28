"""Builder — today's ticker-tagged news/narrative event payload.

Writes ``data/daily_payload/today_news_events.json``.

When no live news provider is wired this writes a valid, honestly-labelled
structure. By default the events list is EMPTY (we do not invent headlines).
A small static narrative-watch list can be emitted with ``--with-static-watch``;
those rows are still labelled ``freshness="UNVERIFIED"`` / ``is_live=false`` and
carry ``confidence=0.0`` so they can never be mistaken for confirmed news.

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
NEWS_EVENTS_PATH = DAILY_PAYLOAD_DIR / "today_news_events.json"

# Optional static sector/narrative watch tickers (UNVERIFIED, never live).
_STATIC_NARRATIVE_WATCH: tuple[str, ...] = ("RTX", "RHM.DE", "XOM", "NVDA")

_FALLBACK_WHY_TODAY = (
    "No live news event confirmed; kept as sector/narrative watch candidate only."
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_directory(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _placeholder_event(ticker: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "headline": None,
        "event_type": "news",
        "timestamp_utc": None,
        "source": None,
        "freshness": "UNVERIFIED",
        "source_health": "UNVERIFIED",
        "provider": "STATIC_OR_EMPTY_FALLBACK",
        "is_live": False,
        "why_today": _FALLBACK_WHY_TODAY,
        "narrative_velocity": None,
        "confidence": 0.0,
    }


def build_today_news_events(
    run_date: str,
    generated_at_utc: str | None = None,
    with_static_watch: bool = False,
    live_events: list[dict[str, Any]] | None = None,
    live_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the news-events payload.

    When ``live_events`` are supplied by the signal_events bridge they are used
    verbatim and the envelope is_live/source_health/provider come from
    ``live_meta`` (honestly derived from genuinely-fresh live rows). Otherwise
    the builder degrades to the honest empty/static fallback — it never claims
    live data on a fallback.
    """
    if live_events:
        meta = live_meta or {}
        return {
            "run_date": run_date,
            "generated_at_utc": generated_at_utc or utc_timestamp(),
            "source_health": meta.get("source_health", "DEGRADED_LIVE_UNMAPPED"),
            "provider": meta.get("provider", "SIGNAL_EVENTS_BRIDGE"),
            "is_live": bool(meta.get("is_live", True)),
            "executable_allowed": bool(meta.get("executable_allowed", False)),
            "bridge_diagnostics": meta.get("diagnostics", {}),
            "events": live_events,
            "records": live_events,
        }

    events = (
        [_placeholder_event(t) for t in _STATIC_NARRATIVE_WATCH]
        if with_static_watch
        else []
    )
    return {
        "run_date": run_date,
        "generated_at_utc": generated_at_utc or utc_timestamp(),
        "source_health": "UNVERIFIED",
        "provider": "STATIC_OR_EMPTY_FALLBACK",
        "is_live": False,
        "executable_allowed": False,
        "fallback_reason": (live_meta or {}).get("fallback_reason", "NO_FRESH_SIGNAL_EVENTS"),
        "events": events,
        "records": events,
    }


def write_today_news_events(
    run_date: str,
    path: Path | None = None,
    generated_at_utc: str | None = None,
    with_static_watch: bool = False,
    live_events: list[dict[str, Any]] | None = None,
    live_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = build_today_news_events(
        run_date, generated_at_utc, with_static_watch, live_events, live_meta
    )
    _write_json(path or NEWS_EVENTS_PATH, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build today's news/narrative event payload.")
    parser.add_argument("--run-date", default=None, help="YYYY-MM-DD (default: today UTC)")
    parser.add_argument(
        "--with-static-watch",
        action="store_true",
        help="emit static UNVERIFIED narrative-watch rows instead of an empty list",
    )
    args = parser.parse_args(argv)
    run_date = args.run_date or utc_timestamp()[:10]
    payload = write_today_news_events(run_date, with_static_watch=args.with_static_watch)
    sys.stdout.write(
        f"today_news_events.json written: source_health={payload['source_health']} "
        f"is_live={payload['is_live']} events={len(payload['events'])}\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
