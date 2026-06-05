"""Auditable export envelope — metadata + checksum + round-trip.

The CSV exports already escape formula-injection, but they ship without a
machine-readable schema declaration, generation timestamp, provenance, source
count, or content hash — so an auditor cannot verify *what* an export is or
*whether it is complete*.  This module wraps any export payload in a stable
envelope that carries:

    schema_version, generated_at_utc, provenance_type, source_count,
    content_checksum (sha256 over the canonical rows)

and round-trips losslessly through JSON: ``parse_envelope(dump_envelope(e))``
reproduces the rows and re-verifies the checksum.  This is the auditability
backbone the operational-readiness audit measures and uses for its own JSON
output.

Pure module: no DB, no network, no broker calls.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA_VERSION = "1.0.0"

# Provenance a row-set may declare.  NO_DATA is legal (an empty, honest export).
_VALID_PROVENANCE = frozenset(
    {
        "LIVE_MANUAL", "PAPER", "IMPORTED_BACKTEST", "SYNTHETIC",
        "RUNTIME_DB", "LOCAL_LOG", "STATIC_CODE", "NO_DATA",
    }
)


def content_checksum(rows: list[dict[str, Any]]) -> str:
    """Deterministic sha256 over canonicalized rows (key order independent)."""
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_envelope(
    *,
    export_name: str,
    rows: list[dict[str, Any]],
    provenance_type: str,
    generated_at_utc: Optional[str] = None,
    extra_meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Wrap ``rows`` in an auditable, checksummed envelope."""
    if provenance_type not in _VALID_PROVENANCE:
        raise ValueError(
            f"provenance_type must be one of {sorted(_VALID_PROVENANCE)}, "
            f"got {provenance_type!r}"
        )
    rows = list(rows or [])
    generated = generated_at_utc or (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    meta = {
        "export_name": export_name,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated,
        "provenance_type": provenance_type,
        "source_count": len(rows),
        "content_checksum": content_checksum(rows),
        # Advisory invariants travel with every export.
        "advisory_only": True,
        "broker_api_called": False,
    }
    if extra_meta:
        meta.update(extra_meta)
    return {"meta": meta, "rows": rows}


def dump_envelope(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, indent=2, sort_keys=False, default=str)


def parse_envelope(text: str) -> dict[str, Any]:
    """Parse + verify an envelope. Raises ValueError if the checksum is stale."""
    data = json.loads(text)
    if not isinstance(data, dict) or "meta" not in data or "rows" not in data:
        raise ValueError("not a valid export envelope")
    meta = data["meta"]
    rows = data["rows"]
    recomputed = content_checksum(rows)
    if meta.get("content_checksum") != recomputed:
        raise ValueError(
            f"checksum mismatch: stored={meta.get('content_checksum')!r} "
            f"recomputed={recomputed!r}"
        )
    if meta.get("source_count") != len(rows):
        raise ValueError("source_count does not match row count")
    return data


def envelope_has_required_metadata(envelope: dict[str, Any]) -> bool:
    """True iff the envelope carries every required audit metadata field."""
    meta = envelope.get("meta", {}) if isinstance(envelope, dict) else {}
    required = {
        "schema_version", "generated_at_utc", "provenance_type",
        "source_count", "content_checksum",
    }
    return required.issubset(meta.keys())


def round_trip_ok(envelope: dict[str, Any]) -> bool:
    """True iff the envelope survives dump -> parse -> verify unchanged."""
    try:
        parsed = parse_envelope(dump_envelope(envelope))
    except (ValueError, json.JSONDecodeError):
        return False
    return parsed["rows"] == envelope["rows"]


__all__ = [
    "SCHEMA_VERSION",
    "content_checksum",
    "build_envelope",
    "dump_envelope",
    "parse_envelope",
    "envelope_has_required_metadata",
    "round_trip_ok",
]
