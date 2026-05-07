"""Run paper-trade creation for PAPER_TRADE-qualified signals only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.models.market import MarketSnapshot
from src.models.signal import SignalScore
from src.paper.paper_trade_engine import build_paper_trade
from src.storage.sqlite_store import SQLiteStore
from src.utils.config_loader import load_yaml_config
from src.utils.logging_utils import get_logger, log_event

LOGGER = get_logger("run_paper_trading")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run read-only paper-trading simulation.")
    parser.add_argument("--summary", action="store_true", help="Print a concise summary.")
    args = parser.parse_args()

    thresholds = load_yaml_config("config/thresholds.yaml").get("thresholds", {})
    edge_threshold = float(thresholds.get("edge_threshold", 0.08))
    stake = float(thresholds.get("simulated_stake", 100.0))
    store = SQLiteStore()
    snapshots = {row["market_id"]: MarketSnapshot(**row) for row in store.read_latest_market_snapshots()}
    score_rows = [SignalScore(**row) for row in store.read_latest_signal_scores()]
    trades = []
    for score in score_rows:
        snapshot = snapshots.get(score.market_id)
        if snapshot is None:
            continue
        trade = build_paper_trade(
            snapshot=snapshot,
            signal_score=score,
            edge_threshold=edge_threshold,
            simulated_stake=stake,
        )
        if trade is not None:
            trades.append(trade)
            store.write_paper_trade(trade)
            log_event(LOGGER, "paper_trade_created", module="run_paper_trading", market_id=trade.market_id, state=trade.state_at_entry)
    output_path = Path("data/paper_trades/latest_paper_trades.json")
    output_path.write_text(json.dumps([trade.to_dict() for trade in trades], indent=2, sort_keys=True), encoding="utf-8")
    if args.summary:
        print("Signal Refinery Paper Trading")
        print(f"paper_trades_created={len(trades)}")
        print(f"paper_trade_path={output_path}")
        print("paper_only=true")
        print("live_trading=false")


if __name__ == "__main__":
    main()
