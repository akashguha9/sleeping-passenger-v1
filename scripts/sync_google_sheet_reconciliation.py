"""Local Google Sheets -> MVP reconciliation sync.

BOOKKEEPING / RECONCILIATION ONLY
=================================
This script reads a Google Sheet that the operator maintains by hand and
posts the corresponding reconciliation entries to the local MVP backend
so the audit log, learning surfaces, and reconciliation queue stay in
sync with what the operator actually did.

SAFETY CONTRACT (do NOT relax):
    * Never places broker orders.
    * Never calls broker APIs.
    * Never marks broker execution as completed.
    * ``ADVISORY_ONLY``                  is always True on every outbound
      payload and reasserted on every response by the backend.
    * ``HUMAN_EXECUTION_REQUIRED``        is always True.
    * ``broker_api_called``               is always False.
    * ``ai_execution_count``              is always 0.
    * ``execution_gate``                  is always ``LOCKED``.

There is no execution endpoint here, no trading automation, no order
placement, and no broker credentials.  The only external calls this
script makes are:
    1. Google Sheets read   (gspread, via service-account JSON)
    2. Google Sheets write  (status columns V/W/X/Y/Z only)
    3. HTTP POST to the local MVP reconciliation endpoint
       (default: http://127.0.0.1:8000/reconciliation/auto-update)

Sheet columns (A:Z)
-------------------
    A SL. No.                           N  RIDE
    B DATE                              O  PROFIT/LOSS
    C TICKER                            P  LIVE PRICE
    D BUY PRICE                         Q  STOP LOSS
    E SELL PRICE                        R  CUMULATIVE P/L
    F LEVERAGE                          S  TP PRICE
    G COUNTRY                           T  TRADE STATE
    H CURRENCY                          U  ACTION REQUIRED
    I AI MODEL USED                     V  PARTIAL TP LOGGED?
    J MONEY ALLOCATED                   W  BOOKED %
    K CAPITAL PRE-TRADE                 X  RIDE %
    L TAKE PROFIT                       Y  LAST ACTION / UPDATED AT
    M STOP LOSS                         Z  MVP RECON STATUS

Action mapping (column U -> outbound action)
-------------------------------------------
    "LOG PARTIAL TP"            and V != "YES"   ->  LOG_PARTIAL_TP
                                                     booked=70, ride=30
    "STOP HIT"                                    ->  STOP_HIT
    "CLOSE TRADE"                                 ->  CLOSE_TRADE
    "RECONCILE / UPDATE OUTCOME"                  ->  RECONCILE_UPDATE_OUTCOME

Sheet writeback after a successful POST
---------------------------------------
    LOG_PARTIAL_TP
        V = YES
        W = 70%
        X = 30%
        Y = "<now> | LOG_PARTIAL_TP_SYNCED"
        Z = PARTIAL_TP_LOGGED
    STOP_HIT
        Y = "<now> | STOP_HIT_SYNCED"
        Z = STOP_HIT_PENDING_CLOSE
    CLOSE_TRADE
        Y = "<now> | CLOSE_TRADE_SYNCED"
        Z = CLOSED
    RECONCILE_UPDATE_OUTCOME
        Y = "<now> | RECONCILED"
        Z = OPEN_RECONCILED
            (unless Z is already PARTIAL_TP_LOGGED or CLOSED)

CLI
---
    python scripts/sync_google_sheet_reconciliation.py --dry-run
    python scripts/sync_google_sheet_reconciliation.py
    python scripts/sync_google_sheet_reconciliation.py --loop --interval-minutes 30

Environment variables
---------------------
    GOOGLE_SHEET_ID                Spreadsheet ID (from the Sheet URL).
    GOOGLE_SERVICE_ACCOUNT_JSON    Absolute path to the service-account
                                   JSON key file shared with the Sheet.
    GOOGLE_SHEET_WORKSHEET_NAME    Worksheet/tab name (optional;
                                   defaults to the first sheet).
    MVP_RECONCILIATION_ENDPOINT    Full URL to the bookkeeping endpoint.
                                   Default: http://127.0.0.1:8000/reconciliation/auto-update
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

DEFAULT_MVP_ENDPOINT = "http://127.0.0.1:8000/reconciliation/auto-update"

# 0-indexed column offsets used when slicing a list-of-cells row from A:Z.
COL_TICKER = 2       # C
COL_BUY_PRICE = 3    # D
COL_SELL_PRICE = 4   # E
COL_LEVERAGE = 5     # F
COL_MONEY_ALLOC = 9  # J
COL_PROFIT_LOSS = 14 # O
COL_LIVE_PRICE = 15  # P
COL_STOP_LOSS = 16   # Q
COL_TP_PRICE = 18    # S
COL_TRADE_STATE = 19 # T
COL_ACTION_REQ = 20  # U
COL_PARTIAL_TP_LOGGED = 21  # V
COL_BOOKED_PCT = 22  # W
COL_RIDE_PCT = 23    # X
COL_LAST_ACTION = 24 # Y
COL_RECON_STATUS = 25  # Z
NUM_SHEET_COLUMNS = 26  # A:Z inclusive

# Sheet writeback column letters (these are what gspread expects).
WB_PARTIAL_TP_LOGGED = "V"
WB_BOOKED_PCT = "W"
WB_RIDE_PCT = "X"
WB_LAST_ACTION = "Y"
WB_RECON_STATUS = "Z"

# Action labels (U column).  Compared case-insensitively after stripping.
ACTION_LOG_PARTIAL_TP = "LOG PARTIAL TP"
ACTION_STOP_HIT = "STOP HIT"
ACTION_CLOSE_TRADE = "CLOSE TRADE"
ACTION_RECONCILE_UPDATE = "RECONCILE / UPDATE OUTCOME"

# Outbound action codes (sent to the MVP endpoint).
OUT_LOG_PARTIAL_TP = "LOG_PARTIAL_TP"
OUT_STOP_HIT = "STOP_HIT"
OUT_CLOSE_TRADE = "CLOSE_TRADE"
OUT_RECONCILE_UPDATE = "RECONCILE_UPDATE_OUTCOME"

# Z-column status values that LOG_PARTIAL_TP / RECONCILE writeback must NOT
# downgrade.  Once a row is PARTIAL_TP_LOGGED or CLOSED, a later
# RECONCILE_UPDATE_OUTCOME must NOT push it back to OPEN_RECONCILED.
TERMINAL_RECON_STATUSES: frozenset[str] = frozenset(
    {"PARTIAL_TP_LOGGED", "CLOSED"}
)

logger = logging.getLogger("sync_google_sheet_reconciliation")


# ---------------------------------------------------------------------------
# Pure-logic helpers — testable without gspread / requests
# ---------------------------------------------------------------------------


def _pad_row(row: list[Any], width: int = NUM_SHEET_COLUMNS) -> list[str]:
    """Return ``row`` padded with empty strings so every column index is
    safe to read.  gspread truncates trailing-empty cells, so a row that
    only has data through column F comes back with length 6."""
    padded = [("" if cell is None else str(cell)) for cell in row]
    if len(padded) < width:
        padded.extend([""] * (width - len(padded)))
    return padded


def _coerce_optional_float(value: Any) -> float | None:
    """Coerce a cell value to ``float`` or ``None`` if blank / unparseable.

    Strips currency / percent / thousands punctuation so cells like
    "$156.72", "30%", or "1,234.5" still parse cleanly.  Never raises.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    cleaned = text.replace(",", "").replace("$", "").replace("%", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalise_action_label(raw: Any) -> str:
    """Normalise a U-column value to its canonical action label.

    Strips whitespace, collapses internal whitespace runs, uppercases.
    Returns empty string when the cell is blank.
    """
    text = str(raw or "").strip().upper()
    if not text:
        return ""
    return " ".join(text.split())


def _normalise_yes_no(raw: Any) -> str:
    """Normalise a Y/N cell (e.g. column V) to ``"YES"``, ``"NO"`` or
    ``""`` for blanks.  Accepts variants like ``true``, ``y``, ``done``."""
    text = str(raw or "").strip().upper()
    if not text:
        return ""
    if text in {"YES", "Y", "TRUE", "1", "DONE"}:
        return "YES"
    if text in {"NO", "N", "FALSE", "0"}:
        return "NO"
    return text


@dataclass
class SheetRowDecision:
    """The outcome of evaluating one sheet row.

    ``action`` is the outbound MVP action code, or ``None`` when the row
    is a no-op (blank / already-synced / unknown action label).
    """

    sheet_row_number: int
    ticker: str
    action: str | None
    live_price: float | None = None
    tp_price: float | None = None
    sl_price: float | None = None
    booked_percent: float | None = None
    ride_percent: float | None = None
    skip_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def is_actionable(self) -> bool:
        return self.action is not None

    def to_payload(self) -> dict[str, Any]:
        """Build the POST body — always carries the LOCKED safety stamps."""
        return {
            "ticker": self.ticker,
            "action": self.action,
            "live_price": self.live_price,
            "tp_price": self.tp_price,
            "sl_price": self.sl_price,
            "booked_percent": self.booked_percent,
            "ride_percent": self.ride_percent,
            "sheet_row_number": self.sheet_row_number,
            "source": "google_sheet_sync",
            "advisory_only": True,
            "human_execution_required": True,
            "broker_api_called": False,
            "ai_execution_count": 0,
            "execution_gate": "LOCKED",
        }


def decide_row(row: list[Any], sheet_row_number: int) -> SheetRowDecision:
    """Pure function: given one A:Z row, decide what to send (if anything).

    Header row (row 1) and rows without a ticker are skipped.  The
    ``LOG_PARTIAL_TP`` action is suppressed when column V is already
    ``YES`` so the sync is idempotent across re-runs.
    """
    padded = _pad_row(row)
    ticker = padded[COL_TICKER].strip()
    action_label = _normalise_action_label(padded[COL_ACTION_REQ])
    partial_tp_logged = _normalise_yes_no(padded[COL_PARTIAL_TP_LOGGED])
    live_price = _coerce_optional_float(padded[COL_LIVE_PRICE])
    tp_price = _coerce_optional_float(padded[COL_TP_PRICE])
    sl_price = _coerce_optional_float(padded[COL_STOP_LOSS])

    decision = SheetRowDecision(
        sheet_row_number=sheet_row_number,
        ticker=ticker,
        action=None,
        live_price=live_price,
        tp_price=tp_price,
        sl_price=sl_price,
        raw={
            "trade_state": padded[COL_TRADE_STATE].strip(),
            "action_required": padded[COL_ACTION_REQ].strip(),
            "partial_tp_logged": partial_tp_logged,
            "recon_status": padded[COL_RECON_STATUS].strip(),
        },
    )

    if not ticker:
        decision.skip_reason = "blank_ticker"
        return decision
    if not action_label:
        decision.skip_reason = "no_action_required"
        return decision

    if action_label == ACTION_LOG_PARTIAL_TP:
        if partial_tp_logged == "YES":
            decision.skip_reason = "partial_tp_already_logged"
            return decision
        decision.action = OUT_LOG_PARTIAL_TP
        decision.booked_percent = 70.0
        decision.ride_percent = 30.0
        return decision

    if action_label == ACTION_STOP_HIT:
        decision.action = OUT_STOP_HIT
        return decision

    if action_label == ACTION_CLOSE_TRADE:
        decision.action = OUT_CLOSE_TRADE
        return decision

    if action_label == ACTION_RECONCILE_UPDATE:
        decision.action = OUT_RECONCILE_UPDATE
        return decision

    decision.skip_reason = f"unknown_action:{action_label}"
    return decision


def build_writeback_updates(
    decision: SheetRowDecision,
    now_iso: str,
    existing_recon_status: str = "",
) -> list[tuple[str, str]]:
    """Compute the (column_letter, new_value) cell updates that should
    be applied to the sheet after a successful MVP POST.  Returns an
    empty list if ``decision`` is a no-op or unknown action.

    ``now_iso`` should be an ISO-8601 timestamp.  The caller supplies it
    so tests can pin the value.
    """
    if decision.action is None:
        return []

    updates: list[tuple[str, str]] = []
    if decision.action == OUT_LOG_PARTIAL_TP:
        updates.append((WB_PARTIAL_TP_LOGGED, "YES"))
        updates.append((WB_BOOKED_PCT, "70%"))
        updates.append((WB_RIDE_PCT, "30%"))
        updates.append((WB_LAST_ACTION, f"{now_iso} | LOG_PARTIAL_TP_SYNCED"))
        updates.append((WB_RECON_STATUS, "PARTIAL_TP_LOGGED"))
        return updates

    if decision.action == OUT_STOP_HIT:
        updates.append((WB_LAST_ACTION, f"{now_iso} | STOP_HIT_SYNCED"))
        updates.append((WB_RECON_STATUS, "STOP_HIT_PENDING_CLOSE"))
        return updates

    if decision.action == OUT_CLOSE_TRADE:
        updates.append((WB_LAST_ACTION, f"{now_iso} | CLOSE_TRADE_SYNCED"))
        updates.append((WB_RECON_STATUS, "CLOSED"))
        return updates

    if decision.action == OUT_RECONCILE_UPDATE:
        updates.append((WB_LAST_ACTION, f"{now_iso} | RECONCILED"))
        existing = (existing_recon_status or "").strip().upper()
        if existing not in TERMINAL_RECON_STATUSES:
            updates.append((WB_RECON_STATUS, "OPEN_RECONCILED"))
        return updates

    return updates


# ---------------------------------------------------------------------------
# Google Sheets I/O — lazy imports so tests can run without gspread.
# ---------------------------------------------------------------------------


def _open_worksheet(
    sheet_id: str,
    service_account_json: str,
    worksheet_name: str | None,
):  # pragma: no cover — exercised manually against the real Sheet
    """Open the configured Google Sheet/worksheet via gspread.

    Lazy import so unit tests do not need ``gspread`` / ``google-auth``
    installed.  The script exits with a clear error if the dependency
    is missing at runtime.
    """
    try:
        import gspread  # type: ignore[import-not-found]
        from google.oauth2.service_account import (  # type: ignore[import-not-found]
            Credentials,
        )
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: gspread / google-auth.  "
            "Install with: python -m pip install gspread google-auth"
        ) from exc

    if not Path(service_account_json).is_file():
        raise SystemExit(
            f"Service-account JSON not found: {service_account_json}"
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(
        service_account_json, scopes=scopes
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)
    if worksheet_name:
        return spreadsheet.worksheet(worksheet_name)
    return spreadsheet.sheet1


def _read_rows(worksheet) -> list[list[Any]]:  # pragma: no cover — I/O
    """Read every row in the A:Z range as a list of lists."""
    return worksheet.get("A1:Z10000")


def _apply_updates(
    worksheet,
    sheet_row_number: int,
    updates: Iterable[tuple[str, str]],
) -> None:  # pragma: no cover — I/O
    """Apply (column_letter, value) cell writes for a given row."""
    batch = [
        {"range": f"{col}{sheet_row_number}", "values": [[value]]}
        for col, value in updates
    ]
    if batch:
        worksheet.batch_update(batch)


# ---------------------------------------------------------------------------
# MVP endpoint POST — lazy import of requests so tests can stub it
# ---------------------------------------------------------------------------


def _post_to_mvp(endpoint: str, payload: dict[str, Any], timeout: int = 20):
    """POST one payload.  Returns the ``requests.Response``-like object.

    Lazy import so the pure-logic tests don't pull ``requests`` unless
    actually needed.  Raises ``SystemExit`` if ``requests`` is missing
    at runtime, mirroring the gspread guard.
    """
    try:
        import requests  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Missing dependency: requests.  "
            "Install with: python -m pip install requests"
        ) from exc
    return requests.post(endpoint, json=payload, timeout=timeout)


# ---------------------------------------------------------------------------
# Configuration loader — env-vars + CLI overrides
# ---------------------------------------------------------------------------


@dataclass
class SyncConfig:
    sheet_id: str
    service_account_json: str
    worksheet_name: str | None
    mvp_endpoint: str
    dry_run: bool
    loop: bool
    interval_minutes: int


def _load_config(args: argparse.Namespace) -> SyncConfig:
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    worksheet_name = os.getenv("GOOGLE_SHEET_WORKSHEET_NAME", "").strip() or None
    mvp_endpoint = (
        os.getenv("MVP_RECONCILIATION_ENDPOINT", "").strip()
        or DEFAULT_MVP_ENDPOINT
    )
    missing: list[str] = []
    if not sheet_id:
        missing.append("GOOGLE_SHEET_ID")
    if not sa_json:
        missing.append("GOOGLE_SERVICE_ACCOUNT_JSON")
    if missing and not args.dry_run_without_env:
        raise SystemExit(
            "Missing required environment variable(s): "
            + ", ".join(missing)
        )
    return SyncConfig(
        sheet_id=sheet_id,
        service_account_json=sa_json,
        worksheet_name=worksheet_name,
        mvp_endpoint=mvp_endpoint,
        dry_run=bool(args.dry_run),
        loop=bool(args.loop),
        interval_minutes=int(args.interval_minutes),
    )


# ---------------------------------------------------------------------------
# Sync orchestration
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_once(
    config: SyncConfig,
    *,
    now_iso_fn=_utc_now_iso,
) -> dict[str, int]:  # pragma: no cover — wraps real I/O
    """Read the sheet once, process every actionable row, return counts."""
    worksheet = _open_worksheet(
        config.sheet_id,
        config.service_account_json,
        config.worksheet_name,
    )
    rows = _read_rows(worksheet)
    return _process_rows(
        rows,
        config=config,
        worksheet=worksheet,
        now_iso_fn=now_iso_fn,
    )


def _process_rows(
    rows: list[list[Any]],
    *,
    config: SyncConfig,
    worksheet,
    now_iso_fn,
    poster=None,
    updater=None,
) -> dict[str, int]:
    """Iterate over rows, post + writeback each actionable row.

    ``poster`` and ``updater`` exist so tests can swap in fakes.  The
    real wiring uses ``_post_to_mvp`` and ``_apply_updates``.
    """
    if poster is None:
        poster = _post_to_mvp
    if updater is None:
        updater = _apply_updates

    counts = {
        "scanned": 0,
        "skipped": 0,
        "posted": 0,
        "failed": 0,
        "writeback_applied": 0,
    }
    for idx, row in enumerate(rows, start=1):
        counts["scanned"] += 1
        if idx == 1:
            counts["skipped"] += 1
            continue
        decision = decide_row(row, sheet_row_number=idx)
        if not decision.is_actionable():
            counts["skipped"] += 1
            if decision.skip_reason and decision.ticker:
                logger.info(
                    "row %d (%s) skipped: %s",
                    idx,
                    decision.ticker,
                    decision.skip_reason,
                )
            continue

        payload = decision.to_payload()
        logger.info(
            "row %d (%s) -> %s | dry_run=%s",
            idx,
            decision.ticker,
            decision.action,
            config.dry_run,
        )
        if config.dry_run:
            counts["posted"] += 1
            continue

        try:
            response = poster(config.mvp_endpoint, payload)
            status_code = getattr(response, "status_code", 0)
            if 200 <= status_code < 300:
                counts["posted"] += 1
            else:
                counts["failed"] += 1
                logger.warning(
                    "row %d (%s) POST failed: %s %s",
                    idx,
                    decision.ticker,
                    status_code,
                    getattr(response, "text", "")[:300],
                )
                continue
        except Exception as exc:
            counts["failed"] += 1
            logger.warning(
                "row %d (%s) POST raised: %s", idx, decision.ticker, exc
            )
            continue

        # Writeback runs only on a successful POST.
        existing_recon_status = decision.raw.get("recon_status", "")
        updates = build_writeback_updates(
            decision,
            now_iso=now_iso_fn(),
            existing_recon_status=existing_recon_status,
        )
        if not updates:
            continue
        try:
            updater(worksheet, decision.sheet_row_number, updates)
            counts["writeback_applied"] += 1
        except Exception as exc:
            logger.warning(
                "row %d (%s) writeback failed: %s",
                idx,
                decision.ticker,
                exc,
            )
    return counts


def _run_dry_offline(config: SyncConfig) -> dict[str, int]:
    """``--dry-run`` path that does NOT hit Google Sheets.

    We still want a single ``--dry-run`` invocation to validate plumbing
    (env vars, action enumeration, payload shape) without authoring a
    sheet read.  We synthesize a single empty-row scan so the caller
    sees a consistent counts dict.
    """
    logger.info(
        "[dry-run] would read https://docs.google.com/spreadsheets/d/%s",
        config.sheet_id or "<unset>",
    )
    logger.info(
        "[dry-run] would POST actionable rows to %s",
        config.mvp_endpoint,
    )
    logger.info(
        "[dry-run] accepted actions: %s, %s, %s, %s",
        OUT_LOG_PARTIAL_TP,
        OUT_STOP_HIT,
        OUT_CLOSE_TRADE,
        OUT_RECONCILE_UPDATE,
    )
    return {"scanned": 0, "skipped": 0, "posted": 0, "failed": 0,
            "writeback_applied": 0}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Sync the operator's Google Sheet into the local MVP "
            "reconciliation audit log.  Bookkeeping only — never places "
            "broker orders."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent without writing the sheet or "
             "posting to the endpoint.",
    )
    p.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously, re-syncing every --interval-minutes.",
    )
    p.add_argument(
        "--interval-minutes",
        type=int,
        default=30,
        help="Interval (minutes) between re-syncs when --loop is set.",
    )
    p.add_argument(
        "--dry-run-without-env",
        action="store_true",
        help="Allow --dry-run even when env vars are unset (debugging).",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level (default: INFO).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = _load_config(args)

    logger.info(
        "sheet_sync starting | sheet=%s | worksheet=%s | endpoint=%s | "
        "dry_run=%s | loop=%s | interval_min=%s",
        config.sheet_id or "<unset>",
        config.worksheet_name or "<default>",
        config.mvp_endpoint,
        config.dry_run,
        config.loop,
        config.interval_minutes,
    )

    if config.dry_run and (
        not config.sheet_id or not config.service_account_json
    ):
        counts = _run_dry_offline(config)
        logger.info("dry-run counts: %s", json.dumps(counts))
        return 0

    def _one_pass() -> int:
        counts = run_once(config)
        logger.info("sync counts: %s", json.dumps(counts))
        return 0 if counts.get("failed", 0) == 0 else 1

    if not config.loop:
        return _one_pass()

    interval_sec = max(60, config.interval_minutes * 60)
    while True:
        rc = _one_pass()
        if rc != 0:
            logger.warning(
                "previous pass reported failures; will retry after %ds",
                interval_sec,
            )
        time.sleep(interval_sec)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
