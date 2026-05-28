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
    from scripts.runtime_common import REPO_ROOT, ensure_directory, utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from build_today_filings_events import write_today_filings_events
    from build_today_market_snapshot import write_today_market_snapshot
    from build_today_news_events import write_today_news_events
    from build_today_price_movers import write_today_price_movers
    from build_yesterday_final_candidates import write_yesterday_final_candidates
    from runtime_common import REPO_ROOT, ensure_directory, utc_timestamp


DAILY_PAYLOAD_DIR = REPO_ROOT / "data" / "daily_payload"
DAILY_PAYLOAD_MANIFEST = DAILY_PAYLOAD_DIR / "daily_payload_manifest.json"

# Files this orchestrator must never touch.
PRESERVED_FILES: tuple[str, ...] = (
    "verified_current_holdings.json",
    "do_not_treat_as_open.json",
    "closed_positions.json",
    "sold_positions.json",
)


def _write_manifest(
    base: Path,
    *,
    generated_at: str,
    db_path: Path | None,
    news_bridge: dict[str, Any],
    filings_bridge: dict[str, Any],
    price_bridge: dict[str, Any],
) -> dict[str, Any]:
    """Write daily_payload_manifest.json with honest bridge diagnostics."""
    news_meta = news_bridge.get("meta", {})
    filings_meta = filings_bridge.get("meta", {})
    price_meta = price_bridge.get("meta", {})
    news_diag = news_meta.get("diagnostics", {})
    filings_diag = filings_meta.get("diagnostics", {})

    bridge_status = "LIVE" if (news_meta.get("is_live") or filings_meta.get("is_live")) else "FALLBACK"
    manifest = {
        "run_timestamp_utc": generated_at,
        "db_path": str(db_path) if db_path else None,
        "signal_events_bridge_attempted": True,
        "signal_events_bridge_status": bridge_status,
        "fresh_news_events_count": news_diag.get("fresh_count", 0),
        "fresh_filings_events_count": filings_diag.get("fresh_count", 0),
        "mapped_events_count": news_diag.get("mapped_count", 0) + filings_diag.get("mapped_count", 0),
        "unmapped_events_count": news_diag.get("unmapped_count", 0) + filings_diag.get("unmapped_count", 0),
        "fallback_reason": {
            "news": news_meta.get("fallback_reason"),
            "filings": filings_meta.get("fallback_reason"),
            "price": price_meta.get("fallback_reason"),
        },
        "price_bridge_status": "LIVE" if price_meta.get("is_live") else "FALLBACK",
        "price_valid_count": price_meta.get("valid_price_count", 0),
        "existing_risk_visibility_degraded": bool(price_meta.get("existing_risk_visibility_degraded")),
        "existing_holdings_missing_price": price_meta.get("existing_holdings_missing_price", []),
        "source_health_summary": {
            "news": news_meta.get("source_health", "STATIC_OR_EMPTY_FALLBACK"),
            "filings": filings_meta.get("source_health", "STATIC_OR_EMPTY_FALLBACK"),
            "price": price_meta.get("source_health", "PRICE_PROVIDER_UNAVAILABLE"),
        },
        "safety": advisory_safety_stamps(),
    }
    ensure_directory(base)
    tmp = (base / "daily_payload_manifest.json").with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp.replace(base / "daily_payload_manifest.json")
    return manifest


def _load_truth_for_bridge(base: Path) -> tuple[list[str], set[str], dict[str, str]]:
    """Return (holdings, phantom/closed/sold set, holding->country) for bridges.

    Best-effort and fail-safe: any error degrades to empty truth so payload
    building never crashes.
    """
    try:
        try:
            from scripts.daily_payload import load_daily_payload, normalize_ticker
            from scripts.portfolio_truth_gate import build_portfolio_truth_gate
        except ModuleNotFoundError:  # pragma: no cover
            from daily_payload import load_daily_payload, normalize_ticker  # type: ignore
            from portfolio_truth_gate import build_portfolio_truth_gate  # type: ignore
        payload = load_daily_payload(base)
        gate = build_portfolio_truth_gate(payload=payload)
        holdings = list(gate["verified_open_holdings"])
        phantom = set(gate["closed_or_sold"]) | set(gate["do_not_treat_as_open"]) | set(
            gate.get("phantom_position_candidates", [])
        )
        countries: dict[str, str] = {}
        for row in payload["verified_holdings"]["positions"]:
            ticker = normalize_ticker(row.get("normalized_ticker") or row.get("ticker"))
            if ticker and row.get("country"):
                countries[ticker] = str(row["country"])
        return holdings, phantom, countries
    except Exception:
        return [], set(), {}


def build_all_daily_payloads(
    run_date: str | None = None,
    payload_dir: Path | None = None,
    with_static_news_watch: bool = False,
    db_path: Path | None = None,
    now_utc: Any = None,
    enable_signal_events_bridge: bool = True,
    enable_price_bridge: bool = True,
    market_state: str = "unknown",
) -> dict[str, Any]:
    """Rebuild the five regenerable payloads and return a summary dict.

    When ``enable_signal_events_bridge`` is set, fresh SQLite ``signal_events``
    are bridged into the news/filings payloads; when ``enable_price_bridge`` is
    set, canonical ``market_data`` marks are bridged into the price-movers
    payload. Both degrade honestly to the static/empty fallback when no fresh
    live data is available — they never claim live data on a fallback.
    """
    base = payload_dir or DAILY_PAYLOAD_DIR
    generated_at = utc_timestamp()
    run_date = run_date or generated_at[:10]

    holdings, phantom_set, holding_countries = _load_truth_for_bridge(base)

    # --- Signal-events bridge (news + filings) ---
    news_bridge: dict[str, Any] = {"events": [], "meta": {}}
    filings_bridge: dict[str, Any] = {"events": [], "meta": {}}
    if enable_signal_events_bridge:
        try:
            try:
                from scripts.signal_events_to_daily_payload import (
                    build_filings_payload_from_signal_events,
                    build_news_payload_from_signal_events,
                )
            except ModuleNotFoundError:  # pragma: no cover
                from signal_events_to_daily_payload import (  # type: ignore
                    build_filings_payload_from_signal_events,
                    build_news_payload_from_signal_events,
                )
            news_bridge = build_news_payload_from_signal_events(
                db_path, now_utc=now_utc, phantom_set=phantom_set
            )
            filings_bridge = build_filings_payload_from_signal_events(
                db_path, now_utc=now_utc, phantom_set=phantom_set
            )
        except Exception as exc:  # pragma: no cover - defensive
            news_bridge = {"events": [], "meta": {"fallback_reason": f"BRIDGE_ERROR:{type(exc).__name__}"}}
            filings_bridge = dict(news_bridge)

    # --- Price bridge (movers + holdings review) ---
    price_bridge: dict[str, Any] = {"meta": {}}
    live_movers: list[dict[str, Any]] | None = None
    price_meta: dict[str, Any] | None = None
    if enable_price_bridge:
        try:
            try:
                from scripts.live_price_movers_bridge import build_live_price_movers
                from scripts.minimum_daily_universe import minimum_universe_tickers
            except ModuleNotFoundError:  # pragma: no cover
                from live_price_movers_bridge import build_live_price_movers  # type: ignore
                from minimum_daily_universe import minimum_universe_tickers  # type: ignore
            mapped_event_tickers = [
                r["ticker"]
                for r in news_bridge["events"] + filings_bridge["events"]
                if r.get("ticker")
            ]
            candidate_tickers = list(dict.fromkeys(minimum_universe_tickers() + mapped_event_tickers))
            price_bridge = build_live_price_movers(
                db_path,
                now_utc=now_utc,
                holdings=holdings,
                candidate_tickers=candidate_tickers,
                holding_countries=holding_countries,
                market_state=market_state,
            )
            price_meta = price_bridge["meta"]
            if price_meta.get("is_live"):
                live_movers = (
                    price_bridge["existing_position_price_review"]
                    + price_bridge["new_candidate_price_movers"]
                )
        except Exception as exc:  # pragma: no cover - defensive
            price_bridge = {"meta": {"fallback_reason": f"PRICE_BRIDGE_ERROR:{type(exc).__name__}"}}

    snapshot = write_today_market_snapshot(
        run_date, path=base / "today_market_snapshot.json", generated_at_utc=generated_at
    )
    movers = write_today_price_movers(
        run_date,
        path=base / "today_price_movers.json",
        generated_at_utc=generated_at,
        live_movers=live_movers,
        live_meta=price_meta,
    )
    news = write_today_news_events(
        run_date,
        path=base / "today_news_events.json",
        generated_at_utc=generated_at,
        with_static_watch=with_static_news_watch,
        live_events=news_bridge["events"] or None,
        live_meta=news_bridge["meta"],
    )
    filings = write_today_filings_events(
        run_date,
        path=base / "today_filings_events.json",
        generated_at_utc=generated_at,
        live_events=filings_bridge["events"] or None,
        live_meta=filings_bridge["meta"],
    )
    yesterday = write_yesterday_final_candidates(
        run_date, path=base / "yesterday_final_candidates.json", generated_at_utc=generated_at
    )

    _write_manifest(
        base,
        generated_at=generated_at,
        db_path=db_path,
        news_bridge=news_bridge,
        filings_bridge=filings_bridge,
        price_bridge=price_bridge,
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
        "files_written": list(files.keys()) + ["daily_payload_manifest.json"],
        "preserved_files": list(PRESERVED_FILES),
        "files": files,
        "any_live": any_live,
        "discovery_live": discovery_live,
        "discovery_status": "LIVE" if discovery_live else "UNDERPOWERED_FALLBACK",
        "signal_events_bridge": {
            "news_fresh": news_bridge.get("meta", {}).get("diagnostics", {}).get("fresh_count", 0),
            "filings_fresh": filings_bridge.get("meta", {}).get("diagnostics", {}).get("fresh_count", 0),
            "price_valid": price_bridge.get("meta", {}).get("valid_price_count", 0),
        },
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
