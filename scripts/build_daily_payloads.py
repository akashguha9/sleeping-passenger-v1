"""Orchestrator — rebuild all daily payload files in one command.

    python scripts/build_daily_payloads.py

Rebuilds:
    * today_market_snapshot.json
    * today_price_movers.json
    * today_news_events.json
    * today_filings_events.json
    * yesterday_final_candidates.json

Preserves (never overwritten here):
    * verified_current_holdings.json   (operator-verified portfolio truth)
    * do_not_treat_as_open.json        (operator override)
    * closed_positions.json / sold_positions.json (historical truth)

Prints an honest summary: files written, live-vs-fallback status, record counts,
and whether discovery is live or underpowered. This builder NEVER claims live
data when a static/empty fallback was used.

Advisory-only: no broker, no execution, no DB writes — it only writes the daily
payload JSON inputs that feed the (separate) five-model synthesis.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.build_today_filings_events import write_today_filings_events
    from scripts.build_today_market_snapshot import write_today_market_snapshot
    from scripts.build_today_news_events import write_today_news_events
    from scripts.build_today_price_movers import write_today_price_movers
    from scripts.build_yesterday_final_candidates import write_yesterday_final_candidates
    from scripts.runtime_common import REPO_ROOT, utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from build_today_filings_events import write_today_filings_events
    from build_today_market_snapshot import write_today_market_snapshot
    from build_today_news_events import write_today_news_events
    from build_today_price_movers import write_today_price_movers
    from build_yesterday_final_candidates import write_yesterday_final_candidates
    from runtime_common import REPO_ROOT, utc_timestamp


DAILY_PAYLOAD_DIR = REPO_ROOT / "data" / "daily_payload"

# Files this orchestrator must never touch.
PRESERVED_FILES: tuple[str, ...] = (
    "verified_current_holdings.json",
    "do_not_treat_as_open.json",
    "closed_positions.json",
    "sold_positions.json",
)


def build_all_daily_payloads(
    run_date: str | None = None,
    payload_dir: Path | None = None,
    with_static_news_watch: bool = False,
) -> dict[str, Any]:
    """Rebuild the five regenerable payloads and return a summary dict."""
    base = payload_dir or DAILY_PAYLOAD_DIR
    generated_at = utc_timestamp()
    run_date = run_date or generated_at[:10]

    snapshot = write_today_market_snapshot(
        run_date, path=base / "today_market_snapshot.json", generated_at_utc=generated_at
    )
    movers = write_today_price_movers(
        run_date, path=base / "today_price_movers.json", generated_at_utc=generated_at
    )
    news = write_today_news_events(
        run_date,
        path=base / "today_news_events.json",
        generated_at_utc=generated_at,
        with_static_watch=with_static_news_watch,
    )
    filings = write_today_filings_events(
        run_date, path=base / "today_filings_events.json", generated_at_utc=generated_at
    )
    yesterday = write_yesterday_final_candidates(
        run_date, path=base / "yesterday_final_candidates.json", generated_at_utc=generated_at
    )

    files = {
        "today_market_snapshot.json": {
            "is_live": snapshot["is_live"],
            "source_health": snapshot["source_health"],
            "provider": snapshot["provider"],
            "record_count": len(snapshot["indices"]) + len(snapshot["macro_proxies"]),
        },
        "today_price_movers.json": {
            "is_live": movers["is_live"],
            "source_health": movers["source_health"],
            "provider": movers["provider"],
            "record_count": len(movers["movers"]),
        },
        "today_news_events.json": {
            "is_live": news["is_live"],
            "source_health": news["source_health"],
            "provider": news["provider"],
            "record_count": len(news["events"]),
        },
        "today_filings_events.json": {
            "is_live": filings["is_live"],
            "source_health": filings["source_health"],
            "provider": filings["provider"],
            "record_count": len(filings["events"]),
        },
        "yesterday_final_candidates.json": {
            "is_live": False,
            "source_health": "N/A",
            "provider": yesterday["source"],
            "record_count": len(yesterday["final_candidates"]),
        },
    }

    any_live = any(meta["is_live"] for meta in files.values())
    # Discovery is "live" only if at least one fresh feed produced live records.
    discovery_live = bool(movers["is_live"] or news["is_live"] or filings["is_live"])
    return {
        "run_date": run_date,
        "generated_at_utc": generated_at,
        "files_written": list(files.keys()),
        "preserved_files": list(PRESERVED_FILES),
        "files": files,
        "any_live": any_live,
        "discovery_live": discovery_live,
        "discovery_status": "LIVE" if discovery_live else "UNDERPOWERED_FALLBACK",
        "safety": advisory_safety_stamps(),
    }


def _print_summary(summary: dict[str, Any]) -> None:
    out = sys.stdout
    out.write("=" * 60 + "\n")
    out.write(f"build_daily_payloads — run_date {summary['run_date']}\n")
    out.write("=" * 60 + "\n")
    for name in summary["files_written"]:
        meta = summary["files"][name]
        out.write(
            f"  WROTE {name:36s} live={str(meta['is_live']):5s} "
            f"health={meta['source_health']:<10s} provider={meta['provider']:<24s} "
            f"records={meta['record_count']}\n"
        )
    out.write("\n  PRESERVED (not overwritten): " + ", ".join(summary["preserved_files"]) + "\n")
    out.write(
        f"\n  discovery_status: {summary['discovery_status']} "
        f"(discovery_live={summary['discovery_live']})\n"
    )
    if not summary["discovery_live"]:
        out.write(
            "  NOTE: no live provider produced records — discovery is UNDERPOWERED "
            "and running on honest static/empty fallbacks (is_live=false, "
            "freshness=UNVERIFIED). Candidates are research-grade only.\n"
        )
    out.write(
        f"\n  safety: execution_gate={summary['safety']['execution_gate']} "
        f"broker_api_called={summary['safety']['broker_api_called']} "
        f"ai_execution_count={summary['safety']['ai_execution_count']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild all daily payload files.")
    parser.add_argument("--run-date", default=None, help="YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--json", action="store_true", help="print JSON summary")
    parser.add_argument(
        "--with-static-news-watch",
        action="store_true",
        help="emit static UNVERIFIED narrative-watch rows in the news payload",
    )
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    summary = build_all_daily_payloads(
        run_date=args.run_date, with_static_news_watch=args.with_static_news_watch
    )
    if args.json:
        sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    else:
        _print_summary(summary)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
