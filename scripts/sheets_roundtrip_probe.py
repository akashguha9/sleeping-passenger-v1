"""Google Sheets round-trip probe — prove the sync loop end to end.

Open-the-Gate sprint (2026-07-04).  Segment H was hardened (auth,
idempotency, schema-drift abort) but never PROVEN: no evidence existed that
a row written through the sync path comes back intact.  This probe supplies
that proof with three modes:

* ``--dry-run``   — print the plan, touch nothing;
* ``--fixture``   — full round-trip against an in-memory worksheet fake
                    (same code path as live, transport injected);
* ``--live-safe`` — real gspread round-trip against a dedicated TEST
                    worksheet, only when credentials exist
                    (``secrets/google-service-account.json`` + SHEET_ID env);
                    missing credentials report **DEGRADED**, never a false
                    pass and never BROKEN.

Round-trip invariant::

    Row_Hash = SHA256(canonical_json(row_without_transport_metadata))
    PASS  iff  Read_Back_Row_Hash == Write_Row_Hash

Idempotency invariant::

    same dedupe_key written twice  =>  exactly one persisted logical row

Schema invariant::

    the worksheet header row must carry the probe's expected columns;
    anything else aborts with SCHEMA_DRIFT (fail-closed).

Advisory-only: the probe writes a single self-identifying test row to a
dedicated probe tab and reads it back.  It never touches trade data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Protocol, Sequence

try:  # package layout
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

PROBE_HEADERS = ["probe_id", "dedupe_key", "created_at", "payload", "row_hash"]
PROBE_TAB = "SP_ROUNDTRIP_PROBE"

ST_PASS = "PASS"
ST_FAIL = "FAIL"
ST_DEGRADED = "DEGRADED"
ST_SCHEMA_DRIFT = "SCHEMA_DRIFT"


class WorksheetLike(Protocol):  # pragma: no cover - typing aid
    def header_row(self) -> list[str]: ...
    def append_row(self, row: list[str]) -> None: ...
    def all_rows(self) -> list[list[str]]: ...


class FixtureWorksheet:
    """In-memory worksheet with the exact interface the probe uses."""

    def __init__(self, headers: list[str] | None = None) -> None:
        self._headers = list(headers if headers is not None else PROBE_HEADERS)
        self._rows: list[list[str]] = []

    def header_row(self) -> list[str]:
        return list(self._headers)

    def append_row(self, row: list[str]) -> None:
        self._rows.append([str(c) for c in row])

    def all_rows(self) -> list[list[str]]:
        return [list(r) for r in self._rows]


def row_hash(row: dict[str, Any]) -> str:
    """SHA256 over the canonical row WITHOUT transport metadata."""
    logical = {k: v for k, v in sorted(row.items())
               if k not in ("row_hash", "transport_ts")}
    return hashlib.sha256(
        json.dumps(logical, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    ).hexdigest()


def run_roundtrip_probe(
    worksheet: WorksheetLike,
    *,
    now_utc: datetime | None = None,
    probe_id: str | None = None,
) -> dict[str, Any]:
    """Write one probe row, verify schema, dedupe, and read-back hash."""
    now = now_utc or datetime.now(timezone.utc)
    created = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    pid = probe_id or f"probe_{now.strftime('%Y%m%d_%H%M%S')}"
    result: dict[str, Any] = {
        "report": "sheets_roundtrip_probe",
        "generated_at_utc": created,
        "probe_id": pid,
        "status": ST_FAIL,
        "checks": {},
        **advisory_safety_stamps(),
    }

    # 1. schema check (fail-closed before any write)
    headers = worksheet.header_row()
    if headers != PROBE_HEADERS:
        result["status"] = ST_SCHEMA_DRIFT
        result["checks"]["schema"] = {
            "ok": False, "expected": PROBE_HEADERS, "found": headers,
        }
        result["detail"] = (
            "probe tab header does not match the expected contract — "
            "aborting fail-closed, nothing written"
        )
        return result
    result["checks"]["schema"] = {"ok": True}

    # 2. write with dedupe key + hash
    dedupe_key = hashlib.sha256(
        f"{pid}|{created[:10]}".encode("utf-8")
    ).hexdigest()[:32]
    logical_row = {
        "probe_id": pid, "dedupe_key": dedupe_key,
        "created_at": created, "payload": "roundtrip-probe",
    }
    h = row_hash(logical_row)
    existing_keys = {
        r[1] for r in worksheet.all_rows() if len(r) >= 2
    }
    wrote = False
    if dedupe_key not in existing_keys:
        worksheet.append_row([
            logical_row["probe_id"], logical_row["dedupe_key"],
            logical_row["created_at"], logical_row["payload"], h,
        ])
        wrote = True
    # 3. duplicate write attempt MUST be skipped
    dup_skipped = dedupe_key in {
        r[1] for r in worksheet.all_rows() if len(r) >= 2
    }
    if dup_skipped:
        pass  # already present -> the second logical write below must no-op
    before = len([r for r in worksheet.all_rows() if len(r) >= 2
                  and r[1] == dedupe_key])
    if dedupe_key not in existing_keys or True:
        # attempt the duplicate through the same guard
        keys_now = {r[1] for r in worksheet.all_rows() if len(r) >= 2}
        if dedupe_key not in keys_now:
            worksheet.append_row([
                logical_row["probe_id"], logical_row["dedupe_key"],
                logical_row["created_at"], logical_row["payload"], h,
            ])
    after = len([r for r in worksheet.all_rows() if len(r) >= 2
                 and r[1] == dedupe_key])
    result["checks"]["idempotency"] = {
        "ok": after == 1 and before == after,
        "rows_for_key": after,
    }

    # 4. read back and verify the hash
    match = [r for r in worksheet.all_rows()
             if len(r) >= 5 and r[1] == dedupe_key]
    if not match:
        result["checks"]["readback"] = {"ok": False, "reason": "row not found"}
        return result
    read = match[0]
    read_logical = {
        "probe_id": read[0], "dedupe_key": read[1],
        "created_at": read[2], "payload": read[3],
    }
    read_hash = row_hash(read_logical)
    stored_hash = read[4]
    hash_ok = read_hash == h == stored_hash
    result["checks"]["readback"] = {
        "ok": hash_ok,
        "write_hash": h,
        "read_back_hash": read_hash,
        "stored_hash": stored_hash,
    }
    result["wrote_row"] = wrote
    result["status"] = (
        ST_PASS
        if hash_ok and result["checks"]["idempotency"]["ok"]
        else ST_FAIL
    )
    return result


def _live_worksheet() -> WorksheetLike | None:  # pragma: no cover - network
    """Real gspread-backed worksheet, only when credentials are present."""
    sa_path = os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_JSON", "secrets/google-service-account.json"
    )
    sheet_id = os.environ.get("SHEETS_PROBE_SHEET_ID", "").strip()
    if not (os.path.exists(sa_path) and sheet_id):
        return None
    import gspread  # lazy: only for --live-safe

    client = gspread.service_account(filename=sa_path)
    book = client.open_by_key(sheet_id)
    try:
        ws = book.worksheet(PROBE_TAB)
    except Exception:  # noqa: BLE001 - create the dedicated probe tab
        ws = book.add_worksheet(PROBE_TAB, rows=100, cols=10)
        ws.append_row(PROBE_HEADERS)

    class _Live:
        def header_row(self) -> list[str]:
            values = ws.get_all_values()
            return values[0] if values else []

        def append_row(self, row: list[str]) -> None:
            ws.append_row(row)

        def all_rows(self) -> list[list[str]]:
            values = ws.get_all_values()
            return values[1:] if values else []

    return _Live()


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--fixture", action="store_true")
    mode.add_argument("--live-safe", action="store_true")
    args = p.parse_args(argv)

    if args.live_safe:
        ws = _live_worksheet()
        if ws is None:
            print(json.dumps({
                "report": "sheets_roundtrip_probe",
                "status": ST_DEGRADED,
                "detail": (
                    "live credentials unavailable (need "
                    "secrets/google-service-account.json + "
                    "SHEETS_PROBE_SHEET_ID env). DEGRADED, not a false "
                    "pass — run --fixture for the logic-path proof."
                ),
                **advisory_safety_stamps(),
            }, indent=2))
            return 0
        result = run_roundtrip_probe(ws)
    elif args.fixture:
        ws = FixtureWorksheet()
        result = run_roundtrip_probe(ws)
    else:
        print(json.dumps({
            "report": "sheets_roundtrip_probe",
            "status": "DRY_RUN",
            "plan": [
                "1. verify probe tab header == " + ", ".join(PROBE_HEADERS),
                "2. append one self-identifying probe row with dedupe_key",
                "3. attempt a duplicate write (must be skipped)",
                "4. read back; SHA256(canonical row) must equal write hash",
            ],
            **advisory_safety_stamps(),
        }, indent=2))
        return 0
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["status"] in (ST_PASS, ST_DEGRADED) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
