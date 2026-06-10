"""S4-A3: local per-role API token registry — hashed at rest, role floors.

Residual being closed: a single shared MVP_API_TOKEN was the only auth —
one secret, no roles, no revocation, no rotation.

Model (deliberately local-scale, not SaaS auth):
* tokens look like ``mvp_<token_id>_<random>``; the id prefix selects
  exactly one registry row so verification is a SINGLE timing-safe
  comparison (no scan over all hashes);
* only ``HMAC_SHA256(pepper, token)`` is stored — never plaintext.  The
  pepper comes from ``MVP_TOKEN_PEPPER`` or an auto-generated owner-only
  key file under ``runtime/diagnostics_cache/``;
* roles: VIEWER (read-only) < OPERATOR (journal writes) < ADMIN
  (backup/restore/token management);
* revocation and rotation invalidate the old token immediately;
* the legacy single MVP_API_TOKEN keeps working as a BOOTSTRAP ADMIN
  credential for backward compatibility, and /health/full flags it as
  deprecated whenever it is configured.

Advisory invariants: authentication only — no broker, no execution.
"""
from __future__ import annotations

import hmac
import hashlib
import logging
import os
import secrets
import sqlite3
from pathlib import Path
from typing import Any

try:
    from scripts import persistence as _persistence
    from scripts.runtime_common import (
        RUNTIME_DIR,
        restrict_file_permissions,
        utc_timestamp,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import persistence as _persistence  # type: ignore[no-redef]
    from runtime_common import (  # type: ignore[no-redef]
        RUNTIME_DIR,
        restrict_file_permissions,
        utc_timestamp,
    )

_logger = logging.getLogger("scripts.token_registry")

ROLES = ("VIEWER", "OPERATOR", "ADMIN")
_ROLE_RANK = {"VIEWER": 0, "OPERATOR": 1, "ADMIN": 2}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_tokens (
    token_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT,
    rotated_at TEXT
);
"""


def role_at_least(role: str | None, floor: str) -> bool:
    if role is None:
        return False
    return _ROLE_RANK.get(str(role).upper(), -1) >= _ROLE_RANK.get(floor, 99)


def _conn(db_path: Path | None) -> sqlite3.Connection:
    conn = _persistence._get_conn(db_path or _persistence.DB_PATH)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _pepper_path() -> Path:
    return RUNTIME_DIR / "diagnostics_cache" / "token_pepper.key"


def _pepper() -> bytes:
    env = os.environ.get("MVP_TOKEN_PEPPER", "").strip()
    if env:
        return env.encode("utf-8")
    path = _pepper_path()
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_bytes(32)
    path.write_bytes(value)
    restrict_file_permissions(path)
    _logger.info("generated token pepper key file (owner-only)")
    return value


def _hash_token(plaintext: str) -> str:
    return hmac.new(_pepper(), plaintext.encode("utf-8"), hashlib.sha256).hexdigest()


def create_token(
    name: str, role: str, db_path: Path | None = None
) -> dict[str, Any]:
    """Create a token.  The PLAINTEXT is returned once and never stored."""
    role_u = str(role).upper()
    if role_u not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {role!r}")
    token_id = secrets.token_hex(6)
    plaintext = f"mvp_{token_id}_{secrets.token_urlsafe(32)}"
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT INTO api_tokens (token_id, name, role, token_hash, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (token_id, str(name)[:120], role_u, _hash_token(plaintext), utc_timestamp()),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "token_id": token_id,
        "name": name,
        "role": role_u,
        "plaintext_token_shown_once": plaintext,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
    }


def verify_token(plaintext: str, db_path: Path | None = None) -> dict[str, Any]:
    """Single timing-safe verification.  Returns {valid, role, token_id}."""
    invalid = {"valid": False, "role": None, "token_id": None}
    if not plaintext or not plaintext.startswith("mvp_"):
        return invalid
    if not (db_path or _persistence.DB_PATH).exists():
        return invalid
    parts = plaintext.split("_", 2)
    if len(parts) != 3:
        return invalid
    token_id = parts[1]
    conn = _conn(db_path)
    try:
        row = conn.execute(
            "SELECT token_id, role, token_hash, revoked_at FROM api_tokens"
            " WHERE token_id=?",
            (token_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or row["revoked_at"] is not None:
        return invalid
    if not hmac.compare_digest(_hash_token(plaintext), str(row["token_hash"])):
        return invalid
    return {"valid": True, "role": str(row["role"]), "token_id": token_id}


def list_tokens(db_path: Path | None = None) -> list[dict[str, Any]]:
    conn = _conn(db_path)
    try:
        rows = conn.execute(
            "SELECT token_id, name, role, created_at, revoked_at, rotated_at"
            " FROM api_tokens ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def revoke_token(token_id: str, db_path: Path | None = None) -> bool:
    conn = _conn(db_path)
    try:
        cur = conn.execute(
            "UPDATE api_tokens SET revoked_at=? WHERE token_id=? AND revoked_at IS NULL",
            (utc_timestamp(), token_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def rotate_token(token_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    """Replace the hash with a new token; the old plaintext dies instantly."""
    conn = _conn(db_path)
    try:
        row = conn.execute(
            "SELECT token_id FROM api_tokens WHERE token_id=? AND revoked_at IS NULL",
            (token_id,),
        ).fetchone()
        if row is None:
            return None
        plaintext = f"mvp_{token_id}_{secrets.token_urlsafe(32)}"
        conn.execute(
            "UPDATE api_tokens SET token_hash=?, rotated_at=? WHERE token_id=?",
            (_hash_token(plaintext), utc_timestamp(), token_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "token_id": token_id,
        "plaintext_token_shown_once": plaintext,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
    }


def registry_token_count(db_path: Path | None = None) -> int:
    """Active (unrevoked) registry tokens — used by health/auth wiring."""
    try:
        # Read-only probe: never create the DB/table as a side effect of
        # counting (auth checks run against arbitrary monkeypatched paths).
        target = db_path or _persistence.DB_PATH
        if not target.exists():
            return 0
        conn = sqlite3.connect(str(target))
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM api_tokens WHERE revoked_at IS NULL"
            ).fetchone()
            return int(row[0]) if row else 0
        except sqlite3.OperationalError:
            return 0  # table absent — no registry tokens
        finally:
            conn.close()
    except Exception:
        _logger.exception("token registry unavailable")
        return 0
