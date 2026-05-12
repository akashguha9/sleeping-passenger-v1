"""
Phase 1 live source ingestion CLI.

Usage
-----
  python scripts/run_live_sources_phase1.py --dry-run                        # all sources, fetch only
  python scripts/run_live_sources_phase1.py --write                          # all sources, persist to SQLite
  python scripts/run_live_sources_phase1.py --source polymarket --dry-run    # Polymarket only, fetch only
  python scripts/run_live_sources_phase1.py --source polymarket --write      # Polymarket only, persist
  python scripts/run_live_sources_phase1.py --source polymarket --dry-run --json  # JSON output

Optional flags
--------------
  --source <src>           Run a single source only. Choices: polymarket, gdelt, sec_edgar.
                           Omit to run all three.
  --sec-cik <CIK>          SEC EDGAR entity CIK (e.g. 0000320193). Requires SEC_USER_AGENT env var.
  --sec-form <form>        SEC EDGAR form type (default: 10-K).
  --polymarket-limit <N>   Max Polymarket markets to fetch (default: 20).
  --gdelt-max <N>          Max GDELT articles to fetch (default: 25).
  --json                   Output full report as JSON.

Safety
------
  ALL outputs are ADVISORY_ONLY.  Execution is HUMAN_ONLY.  AI execution count = 0.
  No broker API calls.  No order placement.  SEC EDGAR requires SEC_USER_AGENT env var.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.live_source_runner import run_phase1, _PHASE1_SOURCES  # noqa: E402

_SUPPORTED_SOURCES = _PHASE1_SOURCES


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 1 live source ingestion — Polymarket, GDELT, SEC EDGAR."
    )
    parser.add_argument(
        "--source",
        default=None,
        choices=_SUPPORTED_SOURCES,
        help="Run a single source only. Omit to run all (polymarket, gdelt, sec_edgar).",
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
        "--sec-cik",
        default=None,
        metavar="CIK",
        help="SEC EDGAR CIK (e.g. 0000320193). Requires SEC_USER_AGENT env var.",
    )
    parser.add_argument(
        "--sec-form",
        default="10-K",
        metavar="FORM",
        help="SEC EDGAR form type (default: 10-K).",
    )
    parser.add_argument(
        "--polymarket-limit",
        type=int,
        default=20,
        metavar="N",
        help="Max Polymarket markets per request (default: 20).",
    )
    parser.add_argument(
        "--gdelt-max",
        type=int,
        default=25,
        metavar="N",
        help="Max GDELT articles per request (default: 25).",
    )
    parser.add_argument(
        "--sec-default-watchlist",
        action="store_true",
        dest="sec_default_watchlist",
        help=(
            "Use the built-in SEC EDGAR watchlist when no --sec-cik is supplied. "
            "Watchlist: Apple, Microsoft, Nvidia, Tesla, Amazon, Meta, Alphabet."
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
    sources = [args.source] if args.source else None

    if not args.output_json:
        src_label = args.source or "Polymarket, GDELT, SEC EDGAR"
        print(f"[Phase 1 Source Runner] mode={'dry-run' if dry_run else 'write'}")
        print(f"  Sources: {src_label}")
        print("  Advisory policy: ADVISORY_ONLY | HUMAN_ONLY | AI_EXECUTION=0")
        print()

    report = run_phase1(
        dry_run=dry_run,
        polymarket_limit=args.polymarket_limit,
        gdelt_max_records=args.gdelt_max,
        sec_cik=args.sec_cik,
        sec_form_type=args.sec_form,
        sec_default_watchlist=args.sec_default_watchlist,
        sources=sources,
    )

    if args.output_json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    for src in report.sources:
        label = src.status.upper()
        print(
            f"  [{label}] {src.source_name}: "
            f"fetched={src.fetched_count}, "
            f"accepted={src.accepted_count}, "
            f"rejected={src.rejected_count}, "
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
