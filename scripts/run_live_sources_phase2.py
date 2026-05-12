"""
Phase 2 live source ingestion CLI.

Usage
-----
  python scripts/run_live_sources_phase2.py --source newsapi --dry-run
  python scripts/run_live_sources_phase2.py --source newsapi --write
  python scripts/run_live_sources_phase2.py --source event_registry --dry-run --json
  python scripts/run_live_sources_phase2.py --source event_registry --write
  python scripts/run_live_sources_phase2.py --source etherscan --address 0xABCD... --dry-run --json
  python scripts/run_live_sources_phase2.py --source etherscan --address 0xABCD... --write
  python scripts/run_live_sources_phase2.py --source grok_xai --dry-run --json
  python scripts/run_live_sources_phase2.py --source grok_xai --write
  python scripts/run_live_sources_phase2.py --source grok_xai --grok-query "What macro themes dominate?" --dry-run
  python scripts/run_live_sources_phase2.py --source market_data --dry-run --json
  python scripts/run_live_sources_phase2.py --source market_data --write
  python scripts/run_live_sources_phase2.py --source market_data --symbols AAPL,MSFT,BTC-USD --period 5d --dry-run
  python scripts/run_live_sources_phase2.py --source india --dry-run --json
  python scripts/run_live_sources_phase2.py --source india --write
  python scripts/run_live_sources_phase2.py --source india --india-symbols "NIFTY 50,NIFTY BANK" --dry-run
  python scripts/run_live_sources_phase2.py --source global_filings --dry-run --json
  python scripts/run_live_sources_phase2.py --source global_filings --write
  python scripts/run_live_sources_phase2.py --source global_filings --global-provider asx --dry-run
  python scripts/run_live_sources_phase2.py --source global_filings --global-region AU --dry-run
  python scripts/run_live_sources_phase2.py --source global_filings --global-query "quarterly report" --dry-run
  python scripts/run_live_sources_phase2.py --source asia_disclosure --dry-run --json
  python scripts/run_live_sources_phase2.py --source asia_disclosure --write
  python scripts/run_live_sources_phase2.py --source asia_disclosure --asia-provider hkex,sse --dry-run
  python scripts/run_live_sources_phase2.py --source asia_disclosure --asia-jurisdiction HK --dry-run
  python scripts/run_live_sources_phase2.py --source asia_disclosure --asia-query "earnings" --dry-run

Optional flags (NewsAPI)
------------------------
  --query <query>           NewsAPI search query (default: "markets economy finance").
  --max-articles <N>        Max articles to fetch (default: 20).
  --language <lang>         Language code for NewsAPI (default: en).

Optional flags (Event Registry)
--------------------------------
  --er-keywords <kw>        Comma-separated keywords for Event Registry (default: economy,markets,finance).
  --er-max-articles <N>     Max articles to fetch from Event Registry (default: 20).
  --er-language <lang>      Language code for Event Registry (default: eng).

Optional flags (Etherscan)
---------------------------
  --address <addr>          Ethereum address to fetch transactions for. Skips cleanly if omitted.
  --max-transactions <N>    Max transactions to fetch (default: 25).
  --chain <chain>           Chain name (default: ethereum). Currently only ethereum is supported.

Optional flags (Grok/xAI)
--------------------------
  --grok-query <query>      Custom prompt for Grok/xAI interpretation. Uses built-in default if omitted.
  --grok-max-items <N>      Max interpretation items per call (default: 1).
  --grok-model <model>      xAI model name (default: grok-3-mini). Falls back on 400.

Optional flags (Market Data — Phase C.5)
-----------------------------------------
  --symbols <sym>           Comma-separated ticker symbols (default: SPY,QQQ,GLD,TLT).
  --period <period>         yfinance history period (default: 5d). E.g. 1d, 5d, 1mo.
  --interval <interval>     yfinance bar interval (default: 1d). E.g. 1h, 1d, 1wk.
  --market-provider <prov>  Data provider (default: yahoo). Paid providers skip cleanly.

Optional flags (India — Phase C.6)
------------------------------------
  --india-symbols <sym>     Comma-separated NSE index names (default: NIFTY 50,NIFTY BANK,INDIA VIX).
  --india-date <date>       ISO date filter e.g. 2026-05-10 (informational; NSE always returns latest).
  --india-max-items <N>     Max India records to return (default: 50).

Optional flags (Global Filings — Phase C.7)
--------------------------------------------
  --global-provider <prov>  Comma-separated provider names (default: all configured).
                            Supported: asx, hkex, sgx, uk_rns, esma, sedar, tdnet.
                            Inactive/placeholder providers skip cleanly.
  --global-query <query>    Filter by issuer name or disclosure description.
  --global-region <region>  Filter providers by jurisdiction (AU, HK, SG, UK, EU, CA, JP).
  --global-max-items <N>    Max global filings records to return (default: 50).

Optional flags (Asia Disclosure — Phase C.8)
---------------------------------------------
  --asia-provider <prov>    Comma-separated Asia provider names (default: all configured).
                            Supported: sse, szse, hkex, tdnet, sgx, dart.
                            All are currently placeholders; they skip cleanly.
  --asia-query <query>      Filter by issuer name, ticker, title, or disclosure description.
  --asia-jurisdiction <jur> Filter providers by jurisdiction code (CN, HK, JP, SG, KR).
  --asia-max-items <N>      Max Asia disclosure records to return (default: 50).
  --asia-date <date>        Informational date filter (ISO string, e.g. 2026-05-10).

Common flags
------------
  --json                    Output full report as JSON.

Safety
------
  ALL outputs are ADVISORY_ONLY.  Execution is HUMAN_ONLY.  AI execution count = 0.
  No broker API calls.  No order placement.  No private keys.  No wallet signing.
  broker_order_id is always NONE on all asia_disclosure outputs.
  NEWS_API_KEY env var must be set; missing key skips NewsAPI cleanly.
  EVENT_REGISTRY_API_KEY env var must be set; missing key skips Event Registry cleanly.
  ETHERSCAN_API_KEY env var must be set; missing key or address skips Etherscan cleanly.
  XAI_API_KEY env var must be set; missing key skips Grok/xAI cleanly.
  Grok/xAI output is hypothesis/interpretation only, never truth.
  Market data is read-only price confirmation; no execution path exists.
  yfinance skips cleanly if the package is unavailable.
  India sources (NSE/RBI/SEBI) require no API key. Public endpoints skip cleanly on failure.
  Global Filings: ASX requires no API key. All other providers are placeholders that skip cleanly.
  Asia Disclosure: All providers are currently placeholders — they skip cleanly.
  SGX and DART require API keys; missing keys skip cleanly.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _env_any(*names: str) -> "str | None":
    """Return the first non-empty value among the given env var names, or None."""
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None

from scripts.live_source_runner_phase2 import run_phase2  # noqa: E402

_SUPPORTED_SOURCES = ["newsapi", "event_registry", "etherscan", "grok_xai", "market_data", "india", "global_filings", "asia_disclosure"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 2 live source ingestion — "
            "NewsAPI, Event Registry, Etherscan, Grok/xAI, and Market Data (Phase C.5)."
        )
    )
    parser.add_argument(
        "--source",
        required=True,
        choices=_SUPPORTED_SOURCES,
        help=(
            "Source to run. Supported: newsapi, event_registry, "
            "etherscan, grok_xai, market_data."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Fetch and normalize signals but do NOT write to SQLite.",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="Fetch, normalize, and persist signals to SQLite.",
    )
    parser.add_argument(
        "--query",
        default="markets economy finance",
        metavar="QUERY",
        help='NewsAPI search query (default: "markets economy finance").',
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=20,
        metavar="N",
        help="Max articles per request (default: 20).",
    )
    parser.add_argument(
        "--language",
        default="en",
        metavar="LANG",
        help="Language code for NewsAPI (default: en).",
    )
    parser.add_argument(
        "--er-keywords",
        default="economy,markets,finance",
        metavar="KEYWORDS",
        help="Comma-separated keywords for Event Registry (default: economy,markets,finance).",
    )
    parser.add_argument(
        "--er-max-articles",
        type=int,
        default=20,
        metavar="N",
        help="Max articles per request for Event Registry (default: 20).",
    )
    parser.add_argument(
        "--er-language",
        default="eng",
        metavar="LANG",
        help="Language code for Event Registry (default: eng).",
    )
    parser.add_argument(
        "--address",
        default=None,
        metavar="ADDR",
        help="Ethereum address for Etherscan (e.g. 0xABCD...). Skips cleanly if omitted.",
    )
    parser.add_argument(
        "--max-transactions",
        type=int,
        default=25,
        metavar="N",
        help="Max transactions to fetch from Etherscan (default: 25).",
    )
    parser.add_argument(
        "--chain",
        default="ethereum",
        metavar="CHAIN",
        help="Chain for Etherscan (default: ethereum). Currently only ethereum is supported.",
    )
    parser.add_argument(
        "--grok-query",
        default=None,
        dest="grok_query",
        metavar="QUERY",
        help="Custom prompt for Grok/xAI interpretation. Uses built-in default if omitted.",
    )
    parser.add_argument(
        "--grok-max-items",
        type=int,
        default=1,
        dest="grok_max_items",
        metavar="N",
        help="Max interpretation items per Grok call (default: 1).",
    )
    parser.add_argument(
        "--grok-model",
        default="grok-3-mini",
        dest="grok_model",
        metavar="MODEL",
        help="xAI model name (default: grok-3-mini). Falls back through grok-3, grok-2-latest on 400.",
    )
    parser.add_argument(
        "--symbols",
        default=None,
        metavar="SYMBOLS",
        help=(
            "Comma-separated ticker symbols for market_data "
            "(default: SPY,QQQ,GLD,TLT). E.g. AAPL,MSFT,RELIANCE.NS,BTC-USD,ETH-USD."
        ),
    )
    parser.add_argument(
        "--period",
        default="5d",
        metavar="PERIOD",
        help="yfinance history period for market_data (default: 5d). E.g. 1d, 5d, 1mo.",
    )
    parser.add_argument(
        "--interval",
        default="1d",
        metavar="INTERVAL",
        help="yfinance bar interval for market_data (default: 1d). E.g. 1h, 1d, 1wk.",
    )
    parser.add_argument(
        "--market-provider",
        default="yahoo",
        dest="market_provider",
        metavar="PROVIDER",
        help="Market data provider (default: yahoo). Paid providers skip cleanly.",
    )
    parser.add_argument(
        "--india-symbols",
        default=None,
        dest="india_symbols",
        metavar="SYMBOLS",
        help=(
            "Comma-separated NSE index names for india source "
            "(default: NIFTY 50,NIFTY BANK,INDIA VIX)."
        ),
    )
    parser.add_argument(
        "--india-date",
        default=None,
        dest="india_date",
        metavar="DATE",
        help=(
            "ISO date for India source e.g. 2026-05-10 "
            "(informational; NSE API always returns latest data)."
        ),
    )
    parser.add_argument(
        "--india-max-items",
        type=int,
        default=50,
        dest="india_max_items",
        metavar="N",
        help="Max India records to return (default: 50).",
    )
    parser.add_argument(
        "--global-provider",
        default=None,
        dest="global_provider",
        metavar="PROVIDER",
        help=(
            "Comma-separated global filings provider names "
            "(default: all configured). E.g. asx,hkex."
        ),
    )
    parser.add_argument(
        "--global-query",
        default=None,
        dest="global_query",
        metavar="QUERY",
        help="Filter global filings by issuer name or disclosure description.",
    )
    parser.add_argument(
        "--global-region",
        default=None,
        dest="global_region",
        metavar="REGION",
        help=(
            "Filter global filings providers by jurisdiction code "
            "(e.g. AU, HK, SG, UK, EU, CA, JP)."
        ),
    )
    parser.add_argument(
        "--global-max-items",
        type=int,
        default=50,
        dest="global_max_items",
        metavar="N",
        help="Max global filings records to return (default: 50).",
    )
    parser.add_argument(
        "--asia-provider",
        default=None,
        dest="asia_provider",
        metavar="PROVIDER",
        help=(
            "Comma-separated Asia disclosure provider names "
            "(default: all configured). E.g. hkex,sse,dart. "
            "All are currently placeholders that skip cleanly."
        ),
    )
    parser.add_argument(
        "--asia-query",
        default=None,
        dest="asia_query",
        metavar="QUERY",
        help="Filter Asia disclosures by issuer name, ticker, title, or disclosure description.",
    )
    parser.add_argument(
        "--asia-jurisdiction",
        default=None,
        dest="asia_jurisdiction",
        metavar="JURISDICTION",
        help=(
            "Filter Asia disclosure providers by jurisdiction code "
            "(e.g. CN, HK, JP, SG, KR)."
        ),
    )
    parser.add_argument(
        "--asia-max-items",
        type=int,
        default=50,
        dest="asia_max_items",
        metavar="N",
        help="Max Asia disclosure records to return (default: 50).",
    )
    parser.add_argument(
        "--asia-date",
        default=None,
        dest="asia_date",
        metavar="DATE",
        help=(
            "Informational date filter for Asia disclosures e.g. 2026-05-10 "
            "(passed through as metadata; provider availability determines actual data)."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Print full report as JSON to stdout.",
    )
    return parser.parse_args()


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    args = _parse_args()
    dry_run: bool = args.dry_run

    er_keywords = [kw.strip() for kw in args.er_keywords.split(",") if kw.strip()]
    market_symbols = (
        [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else None
    )
    india_syms = (
        [s.strip() for s in args.india_symbols.split(",") if s.strip()]
        if args.india_symbols
        else None
    )
    global_providers = (
        [p.strip() for p in args.global_provider.split(",") if p.strip()]
        if args.global_provider
        else None
    )
    asia_providers = (
        [p.strip() for p in args.asia_provider.split(",") if p.strip()]
        if args.asia_provider
        else None
    )

    # Validate Etherscan address early for a cleaner error message.
    if args.source == "etherscan" and args.address:
        from scripts.ingestion.etherscan_loader import _validate_eth_address
        addr_err = _validate_eth_address(args.address)
        if addr_err:
            print(f"[ERROR] --address validation failed: {addr_err}", file=sys.stderr)
            return 1

    if not args.output_json:
        print(f"[Phase 2 Source Runner] mode={'dry-run' if dry_run else 'write'}")
        print(f"  Sources: {args.source}")
        print("  Advisory policy: ADVISORY_ONLY | HUMAN_ONLY | AI_EXECUTION=0 | BROKER_API=false")
        if args.source == "grok_xai":
            print("  Grok/xAI: interpretation only — hypothesis, not truth")
        if args.source == "market_data":
            print("  Market data: read-only price confirmation — no execution path")
        if args.source == "india":
            print("  India: NSE/RBI/SEBI read-only — advisory only, no execution path")
        if args.source == "global_filings":
            print("  Global Filings: public exchange/regulator disclosures — advisory only, no execution path")
        if args.source == "asia_disclosure":
            print("  Asia Disclosure: China/HK/Japan/Singapore/Korea exchange disclosures — advisory only, all providers placeholder")
        print()

    report = run_phase2(
        dry_run=dry_run,
        newsapi_query=args.query,
        newsapi_max_articles=args.max_articles,
        newsapi_language=args.language,
        event_registry_keywords=er_keywords,
        event_registry_max_articles=args.er_max_articles,
        event_registry_language=args.er_language,
        etherscan_address=args.address,
        etherscan_max_transactions=args.max_transactions,
        etherscan_chain=args.chain,
        grok_query=args.grok_query,
        grok_max_items=args.grok_max_items,
        grok_model=args.grok_model,
        market_data_tickers=market_symbols,
        market_data_period=args.period,
        market_data_interval=args.interval,
        market_data_provider=args.market_provider,
        india_symbols=india_syms,
        india_date=args.india_date,
        india_max_items=args.india_max_items,
        global_filings_providers=global_providers,
        global_filings_query=args.global_query,
        global_filings_region=args.global_region,
        global_filings_max_items=args.global_max_items,
        asia_disclosure_providers=asia_providers,
        asia_disclosure_query=args.asia_query,
        asia_disclosure_jurisdiction=args.asia_jurisdiction,
        asia_disclosure_max_items=args.asia_max_items,
        sources=[args.source],
    )

    if args.output_json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    for src in report.sources:
        label = {"ok": "OK", "skipped": "SKIPPED", "error": "ERROR"}.get(
            src.status, src.status.upper()
        )
        print(
            f"  [{label}] {src.source_name}: "
            f"fetched={src.fetched_count}, "
            f"persisted={src.events_persisted}, "
            f"duration={src.duration_ms}ms"
        )
        if src.skipped_reason:
            print(f"         reason: {src.skipped_reason}")
        if src.error_message:
            print(f"         error: {src.error_message}")

    print()
    print(f"Total fetched:   {report.total_fetched}")
    print(f"Total persisted: {report.total_persisted}")
    print(f"Dry-run mode:    {report.dry_run}")
    print(f"Advisory status: {report.advisory_status}")
    print(f"AI exec count:   {report.ai_execution_count}")
    print(f"Broker API:      {report.broker_api_called}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
