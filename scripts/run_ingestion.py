"""Run public-data ingestion for the read-only signal refinery MVP."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.ingestion.polymarket_public_client import PolymarketPublicClient
from src.ingestion.snapshot_writer import write_snapshot_file
from src.storage.sqlite_store import SQLiteStore
from src.utils.logging_utils import get_logger, log_event

LOGGER = get_logger("run_ingestion")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run read-only public-data ingestion.")
    parser.add_argument("--summary", action="store_true", help="Print a concise summary.")
    args = parser.parse_args()

    client = PolymarketPublicClient()
    store = SQLiteStore()
    snapshots = client.fetch_markets()
    store.write_market_snapshots(snapshots)
    raw_path = write_snapshot_file(snapshots, Path("data/raw/latest_market_snapshots.json"))
    log_event(LOGGER, "ingestion_completed", module="run_ingestion", market_count=len(snapshots), raw_path=str(raw_path))
    if args.summary:
        print("Signal Refinery Ingestion")
        print(f"markets_ingested={len(snapshots)}")
        print(f"database_path={store.db_path}")
        print(f"raw_snapshot_path={raw_path}")
        print("truth_origin=public_or_mock")
        print("external_reality_connected=false")


if __name__ == "__main__":
    main()
