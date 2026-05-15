"""
Manual-trade origin classifier — single source of truth for "is this row a
real user-entered manual trade?"

Reconciliation queue, Learning Completeness, the frontend Awaiting list,
and the Cancel Log guard all consult :func:`classify_manual_trade_origin`
so they cannot drift.  When the dashboard says "Reconciliation shows only
trades entered via Manual Trade Log; seed/demo/system rows are excluded",
this module is what makes that statement true.

A row counts as USER_MANUAL only when every gate is satisfied:

* ``created_via`` is exactly ``"manual_trade_log"``.
* ``trade_mode`` (when present) is one of the user-facing modes
  (``REAL_MANUAL`` / ``PAPER``).  Anything stamped SEED / DEMO / SYSTEM /
  FIXTURE / TEST / SAMPLE / MOCK is excluded by name.
* ``logged_by`` is not on the automation deny-list (smoke tests,
  fixtures, calibration seeds, system harnesses).
* ``thesis`` is not one of the synthetic placeholders (``probe``,
  ``test``, ``seed`` …) that test rigs use — those are clearly test
  probes regardless of how they were inserted.  Real user trades carry a
  real thesis sentence.
* ``event_id`` does not start with one of the test/fixture prefixes
  (``EV_``, ``SEED_``, ``DEMO_`` …).
* Defence-in-depth: ``broker_api_called`` is 0 and
  ``ai_execution_count`` is 0.  This app never sets either, but if a
  corrupt/imported row ever did it must not pollute the queue.

The classifier returns a short structured verdict so the frontend can
display *why* an excluded row was excluded ("seed-like probe"), and so
audit scripts can group polluted rows.

No broker calls.  No execution.  Read-only.
"""
from __future__ import annotations

from typing import Any

MANUAL_TRADE_LOG_PROVENANCE: str = "manual_trade_log"

# trade_mode values the operator can legitimately produce.  PAPER comes
# from paper-ledger CSV imports the operator opted into.  REAL_MANUAL is
# the default when the Manual Trade Log form posts.
USER_TRADE_MODES: frozenset[str] = frozenset({"REAL_MANUAL", "PAPER", ""})

# trade_mode values that are always synthetic.  The persistence boundary
# normalises unknown values to REAL_MANUAL so these are very rare in
# practice, but listed here for completeness.
EXCLUDED_TRADE_MODES: frozenset[str] = frozenset(
    {"SEED", "DEMO", "SYSTEM", "FIXTURE", "TEST", "SAMPLE", "MOCK"}
)

# logged_by values that mark a row as inserted by automation rather than
# by a human typing into the Manual Trade Log form.  "human" and "" are
# the real-user defaults.  paper_ledger_import is excluded — paper
# imports come from CSVs but the user-facing screen for them is the
# Paper Trade Ledger, not the live Reconciliation queue, so they should
# not pollute it either.
EXCLUDED_LOGGED_BY: frozenset[str] = frozenset(
    {
        "seed",
        "demo",
        "system",
        "fixture",
        "smoke_test",
        "smoke",
        "test",
        "mock",
        "sample",
        "calibration_seed",
        "paper_ledger_import",
    }
)

# Synthetic theses produced by test/fixture rigs.  A real trader writes a
# sentence; ``probe`` / ``test`` / ``seed`` are placeholders, not theses.
# Match is case-insensitive and exact-word — a real thesis that happens
# to contain "probe" (e.g. "Codex-selected paper probe ...") still
# qualifies as USER_MANUAL.
PROBE_THESIS_VALUES: frozenset[str] = frozenset(
    {"probe", "test", "seed", "demo", "fixture", "smoke", "sample", "mock"}
)

# event_id prefixes that exclusively name seed / fixture rows in this
# repo.  Production code paths generate event_ids like ``PAPER_20260514_…``
# or the live-source-runner stable hashes (``polymarket_…``, ``gdelt_…`` …),
# none of which collide with these prefixes.  ``EV_…`` is intentionally
# NOT listed here — it is widely used by legitimate tests for ergonomic
# unit-test event IDs, and the probe-thesis check is the stronger signal
# for the actual leaked rows.
PROBE_EVENT_ID_PREFIXES: tuple[str, ...] = (
    "SEED_",
    "DEMO_",
    "FIXTURE_",
    "SMOKE_",
    "TEST_",
    "MOCK_",
    "SAMPLE_",
)

# Reconciliation statuses that pull a row out of the live queue.  The row
# stays in the DB for audit but it is not "awaiting" anything.
CANCELLED_RECONCILIATION_STATUSES: frozenset[str] = frozenset(
    {"CANCELLED_LOG", "CANCELLED_DUPLICATE"}
)

# Verdicts returned by classify_manual_trade_origin.  Stable strings — the
# frontend pattern-matches on these and the audit script groups by them.
ORIGIN_USER_MANUAL = "USER_MANUAL"
ORIGIN_EXCLUDED_PROVENANCE = "EXCLUDED_PROVENANCE"
ORIGIN_EXCLUDED_TRADE_MODE = "EXCLUDED_TRADE_MODE"
ORIGIN_EXCLUDED_LOGGED_BY = "EXCLUDED_LOGGED_BY"
ORIGIN_EXCLUDED_PROBE_THESIS = "EXCLUDED_PROBE_THESIS"
ORIGIN_EXCLUDED_EVENT_ID = "EXCLUDED_EVENT_ID"
ORIGIN_EXCLUDED_BROKER_FLAG = "EXCLUDED_BROKER_FLAG"
ORIGIN_EXCLUDED_AI_COUNT = "EXCLUDED_AI_COUNT"

ALL_ORIGIN_LABELS: frozenset[str] = frozenset(
    {
        ORIGIN_USER_MANUAL,
        ORIGIN_EXCLUDED_PROVENANCE,
        ORIGIN_EXCLUDED_TRADE_MODE,
        ORIGIN_EXCLUDED_LOGGED_BY,
        ORIGIN_EXCLUDED_PROBE_THESIS,
        ORIGIN_EXCLUDED_EVENT_ID,
        ORIGIN_EXCLUDED_BROKER_FLAG,
        ORIGIN_EXCLUDED_AI_COUNT,
    }
)


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def classify_manual_trade_origin(row: dict[str, Any]) -> str:
    """Return one of the ``ORIGIN_*`` labels for ``row``.

    ``row`` is a dict-shaped manual_trades record (the same shape
    ``persistence.get_all_manual_trades`` returns).  Missing keys are
    treated as empty.
    """
    if not isinstance(row, dict):
        return ORIGIN_EXCLUDED_PROVENANCE

    created_via = str(row.get("created_via") or "").strip().lower()
    if created_via != MANUAL_TRADE_LOG_PROVENANCE:
        return ORIGIN_EXCLUDED_PROVENANCE

    trade_mode = str(row.get("trade_mode") or "").strip().upper()
    if trade_mode in EXCLUDED_TRADE_MODES:
        return ORIGIN_EXCLUDED_TRADE_MODE
    if trade_mode and trade_mode not in USER_TRADE_MODES:
        return ORIGIN_EXCLUDED_TRADE_MODE

    logged_by = str(row.get("logged_by") or "").strip().lower()
    if logged_by in EXCLUDED_LOGGED_BY:
        return ORIGIN_EXCLUDED_LOGGED_BY

    if _int_or_zero(row.get("broker_api_called")) != 0:
        return ORIGIN_EXCLUDED_BROKER_FLAG
    if _int_or_zero(row.get("ai_execution_count")) != 0:
        return ORIGIN_EXCLUDED_AI_COUNT

    thesis = str(row.get("thesis") or "").strip().lower()
    if thesis in PROBE_THESIS_VALUES:
        return ORIGIN_EXCLUDED_PROBE_THESIS

    event_id = str(row.get("event_id") or "").strip()
    if event_id.startswith(PROBE_EVENT_ID_PREFIXES):
        return ORIGIN_EXCLUDED_EVENT_ID

    return ORIGIN_USER_MANUAL


def is_user_manual_trade(row: dict[str, Any]) -> bool:
    """Boolean shortcut around :func:`classify_manual_trade_origin`."""
    return classify_manual_trade_origin(row) == ORIGIN_USER_MANUAL


def is_cancelled_log(row: dict[str, Any]) -> bool:
    """True iff the row is a soft-cancelled manual log (CANCELLED_LOG /
    CANCELLED_DUPLICATE).  Cancelled rows stay in the DB but never appear
    in the live Reconciliation queue."""
    status = str(row.get("reconciliation_status") or "").strip().upper()
    return status in CANCELLED_RECONCILIATION_STATUSES


def duplicate_group_key(row: dict[str, Any]) -> str:
    """Stable key used to flag duplicate manual logs.

    Two rows share a duplicate-group-key when they have the same ticker,
    side, quantity and price to the configured precision and were logged
    within the same UTC minute.  This catches "the operator clicked Log
    twice", which is what the Cancel Log affordance is for, without
    merging two trades the operator entered hours apart.
    """
    ticker = str(row.get("ticker") or "").strip().upper()
    side = str(row.get("side") or "").strip().upper()
    try:
        qty = round(float(row.get("quantity") or 0.0), 6)
    except (TypeError, ValueError):
        qty = 0.0
    try:
        price = round(float(row.get("price") or 0.0), 6)
    except (TypeError, ValueError):
        price = 0.0
    executed_at = str(row.get("executed_at") or "").strip()
    # Truncate to the minute so back-to-back logs collapse but two real
    # trades minutes apart do not.
    if len(executed_at) >= 16:
        bucket = executed_at[:16]
    else:
        bucket = executed_at
    return f"{ticker}|{side}|{qty}|{price}|{bucket}"


__all__ = [
    "MANUAL_TRADE_LOG_PROVENANCE",
    "USER_TRADE_MODES",
    "EXCLUDED_TRADE_MODES",
    "EXCLUDED_LOGGED_BY",
    "PROBE_THESIS_VALUES",
    "PROBE_EVENT_ID_PREFIXES",
    "CANCELLED_RECONCILIATION_STATUSES",
    "ORIGIN_USER_MANUAL",
    "ORIGIN_EXCLUDED_PROVENANCE",
    "ORIGIN_EXCLUDED_TRADE_MODE",
    "ORIGIN_EXCLUDED_LOGGED_BY",
    "ORIGIN_EXCLUDED_PROBE_THESIS",
    "ORIGIN_EXCLUDED_EVENT_ID",
    "ORIGIN_EXCLUDED_BROKER_FLAG",
    "ORIGIN_EXCLUDED_AI_COUNT",
    "ALL_ORIGIN_LABELS",
    "classify_manual_trade_origin",
    "is_user_manual_trade",
    "is_cancelled_log",
    "duplicate_group_key",
]
