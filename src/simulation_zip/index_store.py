"""Incremental local SQLite index for zip simulation runs (Sprint 2, Phase 3).

Makes reruns on the large local zip faster and deterministic by caching
per-member derived metadata keyed by a content-aware cache key.  Only compact
derived metadata + features are stored — never large raw content.

The database lives under ``runtime/simulation_cache/`` which is git-ignored.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from src.simulation_zip.labels import PARSER_VERSION

SCANNER_VERSION = "2.0.0"
DEFAULT_INDEX_PATH = "runtime/simulation_cache/zip_corpus_index.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS zip_runs (
    run_id TEXT PRIMARY KEY,
    timestamp TEXT,
    zip_path TEXT,
    zip_size_bytes INTEGER,
    zip_sha256_prefix TEXT,
    scanner_version TEXT,
    parser_version TEXT,
    status TEXT
);
CREATE TABLE IF NOT EXISTS zip_members (
    run_id TEXT,
    provenance_id TEXT,
    cache_key TEXT,
    cache_key_strong TEXT,
    archive_path TEXT,
    extension TEXT,
    compressed_size_bytes INTEGER,
    uncompressed_size_bytes INTEGER,
    compression_ratio REAL,
    modified_datetime TEXT,
    file_sha256 TEXT,
    dataset_family TEXT,
    family_confidence REAL,
    safety_status TEXT,
    parser_candidate TEXT,
    parse_status TEXT,
    parse_error TEXT,
    PRIMARY KEY (run_id, provenance_id)
);
CREATE INDEX IF NOT EXISTS idx_members_cache_strong ON zip_members(cache_key_strong);
CREATE INDEX IF NOT EXISTS idx_members_cache ON zip_members(cache_key);
CREATE TABLE IF NOT EXISTS parsed_records (
    run_id TEXT,
    provenance_id TEXT,
    family TEXT,
    record_type TEXT,
    record_json TEXT,
    parser_version TEXT
);
"""


def _norm(s: str) -> str:
    return str(s).replace("\\", "/").strip()


def cache_key(
    zip_abs_path: str,
    zip_size_bytes: int,
    archive_path: str,
    compressed_size_bytes: int,
    uncompressed_size_bytes: int,
    modified_datetime: str,
) -> str:
    material = "::".join(
        [
            _norm(zip_abs_path),
            str(zip_size_bytes),
            _norm(archive_path),
            str(compressed_size_bytes),
            str(uncompressed_size_bytes),
            str(modified_datetime),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def cache_key_strong(
    zip_abs_path: str, archive_path: str, file_sha256: str | None
) -> str | None:
    if not file_sha256:
        return None
    material = "::".join([_norm(zip_abs_path), _norm(archive_path), file_sha256])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class ZipCorpusIndex:
    """Thin SQLite wrapper.  No raw content; compact metadata only."""

    def __init__(self, db_path: str | Path = DEFAULT_INDEX_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "ZipCorpusIndex":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- known strong keys (for cache-hit accounting) ----------------------- #
    def known_strong_keys(self) -> set[str]:
        cur = self.conn.execute(
            "SELECT DISTINCT cache_key_strong FROM zip_members "
            "WHERE cache_key_strong IS NOT NULL"
        )
        return {row[0] for row in cur.fetchall()}

    def record_run(self, run: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO zip_runs VALUES (?,?,?,?,?,?,?,?)",
            (
                run["run_id"], run["timestamp"], run["zip_path"],
                run["zip_size_bytes"], run["zip_sha256_prefix"],
                run["scanner_version"], run["parser_version"], run["status"],
            ),
        )
        self.conn.commit()

    def upsert_member(self, run_id: str, member: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO zip_members VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id, member["provenance_id"], member.get("cache_key"),
                member.get("cache_key_strong"), member["archive_path"],
                member["extension"], member["compressed_size_bytes"],
                member["uncompressed_size_bytes"], member["compression_ratio"],
                member.get("modified_datetime", ""), member.get("file_sha256"),
                member["dataset_family"], member.get("family_confidence", 0.0),
                member["safety_status"], member.get("parser_candidate", "none"),
                member.get("parse_status", "PENDING"), member.get("parse_error"),
            ),
        )

    def add_parsed_record(
        self, run_id: str, provenance_id: str, family: str,
        record_type: str, record: dict,
    ) -> None:
        self.conn.execute(
            "INSERT INTO parsed_records VALUES (?,?,?,?,?,?)",
            (
                run_id, provenance_id, family, record_type,
                json.dumps(record, sort_keys=True, default=str), PARSER_VERSION,
            ),
        )

    def commit(self) -> None:
        self.conn.commit()

    def member_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM zip_members").fetchone()[0]


def compute_cache_hits(
    members: list[dict], known_strong: set[str]
) -> dict[str, object]:
    """cache_hit_i = 1 if cache_key_strong_i already in the index."""
    total = len(members)
    hits = sum(
        1 for m in members
        if m.get("cache_key_strong") and m["cache_key_strong"] in known_strong
    )
    return {
        "total_members": total,
        "cache_hits": hits,
        "cache_misses": total - hits,
        "cache_hit_rate": round(hits / max(total, 1), 6),
    }


__all__ = [
    "ZipCorpusIndex",
    "cache_key",
    "cache_key_strong",
    "compute_cache_hits",
    "SCANNER_VERSION",
    "DEFAULT_INDEX_PATH",
]
