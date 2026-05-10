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

Common flags
------------
  --json                    Output full report as JSON.

Safety
------
  ALL outputs are ADVISORY_ONLY.  Execution is HUMAN_ONLY.  AI execution count = 0.
  No broker API calls.  No order placement.  No private keys.  No wallet signing.
  NEWS_API_KEY env var must be set; missing key skips NewsAPI cleanly.
  EVENT_REGISTRY_API_KEY env var must be set; missing key skips Event Registry cleanly.
  ETHERSCAN_API_KEY env var must be set; missing key or address skips Etherscan cleanly.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.live_source_runner_phase2 import run_phase2  # noqa: E402

_SUPPORTED_SOURCES = ["newsapi", "event_registry", "etherscan"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 2 live source ingestion — NewsAPI, Event Registry, and Etherscan."
    )
    parser.add_argument(
        "--source",
        required=True,
        choices=_SUPPORTED_SOURCES,
        help="Source to run. Supported: newsapi, event_registry, etherscan.",
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
        "--json",
        action="store_true",
        dest="output_json",
        help="Print full report as JSON to stdout.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    dry_run: bool = args.dry_run

    er_keywords = [kw.strip() for kw in args.er_keywords.split(",") if kw.strip()]

    if not args.output_json:
        print(f"[Phase 2 Source Runner] mode={'dry-run' if dry_run else 'write'}")
        print(f"  Sources: {args.source}")
        print("  Advisory policy: ADVISORY_ONLY | HUMAN_ONLY | AI_EXECUTION=0 | BROKER_API=false")
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
