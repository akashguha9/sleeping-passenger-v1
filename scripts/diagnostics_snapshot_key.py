"""Deterministic diagnostics-snapshot content key (Integrated Sprint — Part 1).

The diagnostics snapshot cache (:mod:`scripts.diagnostics_snapshot_cache`)
already validates a cached snapshot against the runtime DB *file mtime* + TTL.
That is sufficient for "the file changed" but does not capture the deeper
question the cockpit asks: **did the canonical inputs change?**  A snapshot
must be evictable when:

  * the signal_event row count changed, OR
  * the most recent ``fetched_at`` for any signal_event advanced, OR
  * the source-health watermark advanced, OR
  * the route/parameters used to compute the snapshot changed, OR
  * the schema or diagnostics module version moved.

This module hashes those canonical inputs into one deterministic key so the
cache validator can use:

    valid_cache = (snapshot_key == current_snapshot_key
                   AND age_seconds <= DIAGNOSTICS_SNAPSHOT_TTL_SECONDS
                   AND not stale AND not degraded_mode)

Pure module; read-only w.r.t. the canonical DB.  No broker calls.  No
execution.  No AI execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import runtime_config as _runtime_config
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import runtime_config as _runtime_config  # type: ignore[no-redef]


SCHEMA_VERSION = "1.0.0"
DIAGNOSTICS_VERSION = "2026-05-24"

DEFAULT_ROUTE_PARAMS_HASH = "default"


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        try:
            return sqlite3.connect(str(db_path))
        except sqlite3.Error:
            return None


def _scalar(conn: sqlite3.Connection, sql: str) -> Any:
    try:
        row = conn.execute(sql).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    return row[0]


def collect_canonical_inputs(
    db_path: Path | None = None,
    *,
    route_params_hash: str = DEFAULT_ROUTE_PARAMS_HASH,
) -> dict[str, Any]:
    """Read the canonical inputs the snapshot key must capture.

    A missing DB returns zeros/None entries rather than raising — the key still
    distinguishes "no DB" from "empty DB" because ``db_exists`` enters the hash.
    """
    target = Path(db_path) if db_path is not None else _runtime_config.get_db_path()
    inputs: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "diagnostics_version": DIAGNOSTICS_VERSION,
        "canonical_db_path": str(target),
        "db_exists": target.exists(),
        "signal_event_count": 0,
        "max_signal_event_updated_at_utc": None,
        "source_health_watermark_utc": None,
        "route_params_hash": route_params_hash,
    }
    conn = _readonly_connect(target)
    if conn is None:
        return inputs
    try:
        # signal_events row count + most-recent fetched_at watermark.
        try:
            count_row = conn.execute(
                "SELECT COUNT(*), MAX(fetched_at) FROM signal_events"
            ).fetchone()
            if count_row:
                inputs["signal_event_count"] = int(count_row[0] or 0)
                inputs["max_signal_event_updated_at_utc"] = count_row[1]
        except sqlite3.Error:
            pass
        # source_run_log latest run end as the source-health watermark.
        try:
            watermark = _scalar(
                conn,
                "SELECT MAX(run_ended_at) FROM source_run_log",
            )
            if watermark:
                inputs["source_health_watermark_utc"] = watermark
        except sqlite3.Error:
            pass
    finally:
        conn.close()
    return inputs


def compute_snapshot_key(inputs: dict[str, Any]) -> str:
    """SHA-256 hex digest over the canonical inputs (stable JSON encoding)."""
    payload = json.dumps(inputs, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def current_snapshot_key(
    db_path: Path | None = None,
    *,
    route_params_hash: str = DEFAULT_ROUTE_PARAMS_HASH,
) -> dict[str, Any]:
    """Convenience: read the inputs + return the digest + inputs together."""
    inputs = collect_canonical_inputs(
        db_path, route_params_hash=route_params_hash)
    key = compute_snapshot_key(inputs)
    return {
        "snapshot_key": key,
        "inputs": inputs,
        "generated_at_utc": datetime.now(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
        **_contract.advisory_safety_stamps(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="diagnostics_snapshot_key.py",
        description=(
            "Compute the deterministic diagnostics snapshot key from canonical "
            "DB inputs. Read-only; no broker calls; no execution."
        ),
    )
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--route-params-hash", type=str,
                   default=DEFAULT_ROUTE_PARAMS_HASH)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = current_snapshot_key(
        args.db_path, route_params_hash=args.route_params_hash)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print("Diagnostics Snapshot Key (deterministic, content-derived)")
        print("=========================================================")
        print(f"  snapshot_key   : {result['snapshot_key']}")
        for k, v in result["inputs"].items():
            print(f"  {k:<32} : {v}")
    return 0


__all__ = [
    "SCHEMA_VERSION",
    "DIAGNOSTICS_VERSION",
    "DEFAULT_ROUTE_PARAMS_HASH",
    "collect_canonical_inputs",
    "compute_snapshot_key",
    "current_snapshot_key",
]


if __name__ == "__main__":
    raise SystemExit(main())
