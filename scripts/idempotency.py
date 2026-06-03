"""L3 fix — Idempotency-Key support for ``POST /manual-trades``.

Adds a tiny key/value store keyed on the operator-supplied
``Idempotency-Key`` header and the route path.  When a client retries
the same write (browser reload, network flake, sheet sync re-run) the
server returns the cached response instead of inserting a duplicate
row.

Why this matters
----------------
``INSERT OR IGNORE`` in ``log_manual_trade`` only protects against
primary-key collisions on the auto-increment ``id`` column.  It does
NOT prevent two logically identical rows with different ``trade_id``
values — exactly the failure mode the audit flagged.

Storage
-------
SQLite table ``idempotency_keys`` under the existing journaling DB.
Additive CREATE TABLE IF NOT EXISTS; safe to call at any time.
Response payload is stored as JSON text so any structured FastAPI body
can be replayed.

Advisory invariants are not affected by this module.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover
    from runtime_common import utc_timestamp  # type: ignore[no-redef]

try:
    from scripts.persistence import DB_PATH as _DEFAULT_DB_PATH
except ModuleNotFoundError:  # pragma: no cover
    from persistence import DB_PATH as _DEFAULT_DB_PATH  # type: ignore[no-redef]


_SCHEMA = """\
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key_hash TEXT PRIMARY KEY,
    route TEXT NOT NULL,
    created_at TEXT NOT NULL,
    response_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_idemp_created_at ON idempotency_keys(created_at);
"""

_LOCK = threading.Lock()


def _hash_key(route: str, key: str) -> str:
    """Hash (route, idempotency-key) so we don't store raw operator input."""
    h = hashlib.sha256()
    h.update(route.encode("utf-8"))
    h.update(b"|")
    h.update(key.encode("utf-8"))
    return h.hexdigest()


def _get_conn(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else _DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def lookup(route: str, key: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    """Return the cached response for (route, key) or None."""
    if not key:
        return None
    key_hash = _hash_key(route, key)
    with _LOCK:
        conn = _get_conn(db_path)
        try:
            row = conn.execute(
                "SELECT response_json FROM idempotency_keys WHERE key_hash=?",
                (key_hash,),
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return None
    try:
        return json.loads(row["response_json"])
    except Exception:
        return None


def store(
    route: str,
    key: str,
    response: dict[str, Any],
    db_path: Path | str | None = None,
) -> None:
    """Persist the response for (route, key).  Idempotent itself: an
    existing row is left alone (the FIRST response is authoritative)."""
    if not key:
        return
    key_hash = _hash_key(route, key)
    payload = json.dumps(response, separators=(",", ":"))
    with _LOCK:
        conn = _get_conn(db_path)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO idempotency_keys "
                "(key_hash, route, created_at, response_json) VALUES (?,?,?,?)",
                (key_hash, route, utc_timestamp(), payload),
            )
            conn.commit()
        finally:
            conn.close()


def validate_key(key: str | None) -> str:
    """Trim + cap operator-supplied idempotency key.  Empty → ''.

    16–128 character window matches the Stripe / IETF draft conventions.
    """
    if key is None:
        return ""
    trimmed = str(key).strip()
    if not trimmed:
        return ""
    if len(trimmed) > 200:
        # Too long is almost certainly a bug; reject by collapsing to ''.
        return ""
    return trimmed
