"""SQLite storage for read-only ingestion, scores, and paper trades."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from src.models.market import MarketSnapshot
from src.models.paper_trade import PaperTrade
from src.models.signal import AttentionCluster, SignalScore

DEFAULT_DB_PATH = Path("data/processed/signal_refinery.sqlite")


class SQLiteStore:
    """Simple SQLite persistence layer built on the standard library."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cursor = self.connection.cursor()
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS raw_market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS processed_signal_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                scored_at TEXT NOT NULL,
                state TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rejected_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                scored_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attention_clusters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT NOT NULL,
                market_id TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                module TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def write_market_snapshots(self, snapshots: list[MarketSnapshot]) -> None:
        self.connection.executemany(
            "INSERT INTO raw_market_snapshots (market_id, fetched_at, payload_json) VALUES (?, ?, ?)",
            [(snapshot.market_id, snapshot.fetched_at, json.dumps(snapshot.to_dict(), sort_keys=True)) for snapshot in snapshots],
        )
        self.connection.commit()

    def read_latest_market_snapshots(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT payload_json
            FROM raw_market_snapshots
            WHERE id IN (
                SELECT MAX(id) FROM raw_market_snapshots GROUP BY market_id
            )
            ORDER BY market_id
            """
        ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def write_signal_scores(self, scores: list[SignalScore]) -> None:
        self.connection.executemany(
            "INSERT INTO processed_signal_scores (market_id, scored_at, state, payload_json) VALUES (?, ?, ?, ?)",
            [(score.market_id, score.scored_at, score.state, json.dumps(score.to_dict(), sort_keys=True)) for score in scores],
        )
        self.connection.commit()

    def write_rejected_signal(self, score: SignalScore) -> None:
        self.connection.execute(
            "INSERT INTO rejected_signals (market_id, scored_at, payload_json) VALUES (?, ?, ?)",
            (score.market_id, score.scored_at, json.dumps(score.to_dict(), sort_keys=True)),
        )
        self.connection.commit()

    def read_latest_signal_scores(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT payload_json
            FROM processed_signal_scores
            WHERE id IN (
                SELECT MAX(id) FROM processed_signal_scores GROUP BY market_id
            )
            ORDER BY market_id
            """
        ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def write_attention_clusters(self, clusters: list[AttentionCluster]) -> None:
        self.connection.executemany(
            "INSERT INTO attention_clusters (market_id, timestamp, payload_json) VALUES (?, ?, ?)",
            [(cluster.market_id, cluster.timestamp, json.dumps(cluster.to_dict(), sort_keys=True)) for cluster in clusters],
        )
        self.connection.commit()

    def read_attention_clusters(self) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT payload_json FROM attention_clusters ORDER BY id DESC").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def write_paper_trade(self, trade: PaperTrade) -> None:
        self.connection.execute(
            "INSERT INTO paper_trades (trade_id, market_id, entry_time, status, payload_json) VALUES (?, ?, ?, ?, ?)",
            (trade.trade_id, trade.market_id, trade.entry_time, trade.status, json.dumps(trade.to_dict(), sort_keys=True)),
        )
        self.connection.commit()

    def read_paper_trades(self) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT payload_json FROM paper_trades ORDER BY id DESC").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def write_system_log(self, timestamp: str, module: str, payload: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO system_logs (timestamp, module, payload_json) VALUES (?, ?, ?)",
            (timestamp, module, json.dumps(payload, sort_keys=True)),
        )
        self.connection.commit()
