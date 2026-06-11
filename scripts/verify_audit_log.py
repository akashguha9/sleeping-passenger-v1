"""Verify the tamper-evident audit log chain (scripts/audit_log.py).

Detects (exit 1 on any): invalid JSON lines, a broken previous_hash link,
a recomputed event_hash mismatch (modified event), a non-genesis first
link (missing leading events), truncation/insertion anywhere in the
chain, and non-monotonic timestamps (warning-grade: clock skew is
possible, so it is reported but does not fail the chain by itself).

Usage:  python scripts/verify_audit_log.py [--path logs/audit_log.jsonl]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.audit_log import (
        GENESIS_HASH,
        audit_log_path,
        compute_event_hash,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from audit_log import (  # type: ignore[no-redef]
        GENESIS_HASH,
        audit_log_path,
        compute_event_hash,
    )

_REQUIRED_FIELDS = (
    "ts_utc", "event_type", "actor", "action", "outcome",
    "metadata", "previous_hash", "event_hash",
)


def verify_chain(path: Path) -> dict:
    """Return {valid, events, errors, warnings}. Empty log = valid."""
    errors: list[str] = []
    warnings: list[str] = []
    count = 0
    expected_previous = GENESIS_HASH
    last_ts = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {"valid": True, "events": 0, "errors": [],
                "warnings": ["log file does not exist (no events yet)"]}
    except OSError as exc:
        return {"valid": False, "events": 0,
                "errors": [f"unreadable log: {exc}"], "warnings": []}

    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        count += 1
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"line {lineno}: invalid JSON")
            # Chain is unverifiable past this point.
            expected_previous = None
            continue
        missing = [f for f in _REQUIRED_FIELDS if f not in event]
        if missing:
            errors.append(f"line {lineno}: missing fields {missing}")
            expected_previous = None
            continue
        if expected_previous is not None and event["previous_hash"] != expected_previous:
            errors.append(
                f"line {lineno}: broken chain — previous_hash does not match "
                "the prior event (event missing, reordered, or tampered)"
            )
        recomputed = compute_event_hash(
            {k: v for k, v in event.items() if k != "event_hash"},
            event["previous_hash"],
        )
        if recomputed != event["event_hash"]:
            errors.append(f"line {lineno}: event_hash mismatch — event modified")
        if last_ts is not None and str(event["ts_utc"]) < str(last_ts):
            warnings.append(
                f"line {lineno}: non-monotonic timestamp ({event['ts_utc']} < {last_ts})"
            )
        last_ts = event["ts_utc"]
        expected_previous = event["event_hash"]

    return {"valid": not errors, "events": count, "errors": errors, "warnings": warnings}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", default=None)
    args = parser.parse_args(argv)
    path = Path(args.path) if args.path else audit_log_path()
    result = verify_chain(path)
    print(f"audit log verification: {path}")
    print(f"  events: {result['events']}")
    for w in result["warnings"]:
        print(f"  warn: {w}")
    if result["valid"]:
        print("PASS — hash chain intact.")
        return 0
    print(f"FAIL — {len(result['errors'])} error(s):")
    for e in result["errors"]:
        print(f"  - {e}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
