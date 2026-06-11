"""Tamper-evident, append-only audit log for sensitive owner actions.

Hash-chained JSONL: each event commits to everything before it, so any
edit, deletion, or insertion breaks the chain and is detected by
``scripts/verify_audit_log.py``.

Chain formula (test-pinned):

    event_hash_n = SHA256( canonical_json(event_n minus event_hash)
                           || previous_hash_n )
    previous_hash_0 = "0" * 64

Logged events (emitted by the API middleware and the backup/restore
tooling): journal mutations, imports/exports, reconciliation, settings
changes, backup/restore runs, failed-auth bursts, unsafe-override boots,
lockdown blocks, and beyond-loopback dashboard access.

Redaction rules (test-pinned): metadata passes through ``redact_metadata``
which drops/blanks anything secret-shaped (token, secret, password, key,
authorization, hash values) and truncates long strings — the log records
THAT something happened, never the private payload. No raw tokens, no
provider secrets, no full prompt payloads, no journal body text.

The log lives at ``logs/audit_log.jsonl`` (``MVP_AUDIT_LOG_PATH``
override) — ``logs/`` is gitignored, so the chain never leaves the
owner's machine. Append uses a process-wide lock; this MVP is pinned to
one uvicorn worker (A4), so single-process append-only discipline holds.

Advisory-only: audit logging observes; it never executes anything.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import threading
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
GENESIS_HASH = "0" * 64
_LOCK = threading.Lock()

_SECRET_KEY_FRAGMENTS = (
    "token", "secret", "password", "passwd", "authorization", "api_key",
    "apikey", "credential", "bearer", "cookie", "private_key",
)
_MAX_META_STRING = 160

EVENT_TYPES = frozenset({
    "journal_write", "journal_delete", "import", "export", "reconciliation",
    "settings_change", "token_rotation", "backup", "restore",
    "auth_failure_burst", "unsafe_override_boot", "lockdown_block",
    "lockdown_engaged", "dashboard_nonloopback_access", "evidence_recorded",
    "other",
})


def audit_log_path() -> Path:
    raw = os.environ.get("MVP_AUDIT_LOG_PATH", "").strip()
    return Path(raw) if raw else _REPO_ROOT / "logs" / "audit_log.jsonl"


def canonical_json(obj: dict) -> str:
    """Deterministic serialization the chain hashes are computed over."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_event_hash(event_without_hash: dict, previous_hash: str) -> str:
    payload = canonical_json(event_without_hash) + previous_hash
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def redact_metadata(metadata: dict | None) -> dict:
    """Aggressively strip secret-shaped and oversized values."""
    if not metadata:
        return {}
    clean: dict = {}
    for key, value in metadata.items():
        lk = str(key).lower()
        if any(frag in lk for frag in _SECRET_KEY_FRAGMENTS):
            clean[str(key)] = "<redacted>"
            continue
        if isinstance(value, str):
            # 64-hex strings look like hashes/keys; never persist them.
            stripped = value.strip()
            if len(stripped) == 64 and all(c in "0123456789abcdef" for c in stripped.lower()):
                clean[str(key)] = "<redacted>"
                continue
            clean[str(key)] = (
                stripped[:_MAX_META_STRING] + "…" if len(stripped) > _MAX_META_STRING else stripped
            )
        elif isinstance(value, (int, float, bool)) or value is None:
            clean[str(key)] = value
        else:
            clean[str(key)] = f"<{type(value).__name__}>"
    return clean


def _last_hash(path: Path) -> str:
    """Previous hash = event_hash of the final valid line (genesis if none)."""
    try:
        with path.open("rb") as fh:
            last_line = b""
            for line in fh:
                if line.strip():
                    last_line = line
        if not last_line:
            return GENESIS_HASH
        return json.loads(last_line.decode("utf-8")).get("event_hash", GENESIS_HASH)
    except (FileNotFoundError, OSError, json.JSONDecodeError, UnicodeDecodeError):
        return GENESIS_HASH


def append_event(
    event_type: str,
    *,
    actor: str = "owner",
    action: str = "",
    outcome: str = "ok",
    metadata: dict | None = None,
    path: Path | None = None,
) -> dict:
    """Append one chained event; returns the written record.

    Never raises into the caller's request path: on I/O failure the
    record is returned with outcome annotated, and the failure is the
    caller's signal that local logging is broken (itself suspicious).
    """
    log_path = path or audit_log_path()
    if event_type not in EVENT_TYPES:
        event_type = "other"
    if actor not in ("owner", "system", "unknown"):
        actor = "unknown"
    with _LOCK:
        previous_hash = _last_hash(log_path)
        event = {
            "ts_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "event_type": event_type,
            "actor": actor,
            "action": str(action)[:200],
            "outcome": str(outcome)[:80],
            "metadata": redact_metadata(metadata),
            "previous_hash": previous_hash,
        }
        event["event_hash"] = compute_event_hash(
            {k: v for k, v in event.items() if k != "event_hash"}, previous_hash
        )
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(canonical_json(event) + "\n")
        except OSError as exc:  # pragma: no cover - disk failure path
            event["outcome"] = f"audit_write_failed:{exc.__class__.__name__}"
        return event
