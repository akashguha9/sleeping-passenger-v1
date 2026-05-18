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

# ---------------------------------------------------------------------------
# Stricter fake-marker rules (Sprint-recovery 2026-05-18).
#
# The classifier above stops obvious seed/probe rows from getting the
# ``manual_trade_log`` provenance stamp in the first place, but it
# preserves "EV_<thing>" event_ids and substring-of-thesis text because
# legitimate operator entries collide with both patterns in real life.
# The Manual Trade Log surface in the UI needs a stricter veto — the
# leaked-AAPL incident showed that any thesis-by-thesis exact-match
# rule leaves room for fabrications like ``thesis="no currency given"``
# (a unit-test marker that doesn't look obviously synthetic).
#
# These rules layer ON TOP of ``classify_manual_trade_origin``: a row
# must pass the canonical classifier AND not match any fake-marker rule
# to be visible.  Tests, the quarantine script, the GET filter, and the
# POST guard all import from this module so the rules cannot drift.
# ---------------------------------------------------------------------------

# Hard-block specific trade_ids that have been confirmed synthetic.  These
# are the operator's reported "this must never appear again" rows.
FAKE_TRADE_IDS: frozenset[str] = frozenset(
    {
        "MT_6b11745fc3f3",  # AAPL/5/$180 thesis="no currency given"
        "MT_b1554a7e78a7",  # AAPL/10/$180 thesis="probe"
    }
)

# Thesis / notes / risk_reason substrings.  Matched case-insensitively as
# substrings so a sentence like "AI networking peer probe after CSCO" is
# excluded even though the literal value is not "probe".  Real operator
# theses describing a setup do not contain these test/fixture words.
FAKE_THESIS_SUBSTRINGS: tuple[str, ...] = (
    "probe",
    "test",
    "seed",
    "demo",
    "fixture",
    "smoke",
    "sample",
    "mock",
    "no currency given",
)

# event_id prefixes that name only synthetic rows.  ``EV_AAPL`` is listed
# specifically because the leaked rows used it; bare ``EV_`` is too broad
# (legitimate tests use ``EV_<TICKER>`` ergonomically) and stays out.
FAKE_EVENT_ID_PREFIXES: tuple[str, ...] = (
    "EV_AAPL",
    "TEST_",
    "SEED_",
    "DEMO_",
    "MOCK_",
    "SAMPLE_",
    "SMOKE_",
    "FIXTURE_",
    "FABRIC_",
)

# logged_by / source / created_by values indicating non-human origin.
# Wider than EXCLUDED_LOGGED_BY because this set is used at the
# VISIBLE/POST layer where any whiff of automation must veto display.
FAKE_LOGGED_BY_VALUES: frozenset[str] = frozenset(
    {
        "automation",
        "seed",
        "smoke_test",
        "smoke",
        "fixture",
        "mock",
        "sample",
        "calibration_seed",
        "probe",
        "system",
        "demo",
        "test",
    }
)

# AAPL/$180 with quantity 5 or 10 is the fingerprint of the leaked rows.
# Ticker upper, price exact, quantity in {5,10}.
FAKE_AAPL_QUANTITIES: frozenset[float] = frozenset({5.0, 10.0})
FAKE_AAPL_PRICE: float = 180.0
FAKE_AAPL_TICKER: str = "AAPL"

# Provenance stamp written by the quarantine script.  Picked so the
# canonical classifier reads the row as ORIGIN_EXCLUDED_PROVENANCE and
# the GET filter drops it without any new code path.
QUARANTINE_PROVENANCE: str = "quarantined_fake_manual_trade"

# Rejection reason emitted by the POST guard and surfaced in the
# structured 400 response so the frontend can pattern-match.
REJECT_REASON_NON_USER_MARKER: str = "rejected_non_user_manual_trade_marker"

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


def _contains_marker_substring(text: str) -> str:
    """Return the first FAKE_THESIS_SUBSTRINGS hit in ``text`` (lowercased),
    or ``""`` if none.  Substring match — a single occurrence anywhere in
    the value triggers the rule."""
    if not text:
        return ""
    lowered = text.strip().lower()
    if not lowered:
        return ""
    for marker in FAKE_THESIS_SUBSTRINGS:
        if marker in lowered:
            return marker
    return ""


def _row_float(row: dict[str, Any], key: str) -> float:
    try:
        return float(row.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def fake_manual_trade_reason(row: dict[str, Any]) -> str:
    """Return a short reason code if ``row`` matches a fake-marker rule,
    or ``""`` if it does not.  Read-only; no side effects; no broker
    calls.  Used by the GET filter, POST guard, and quarantine script
    so the three paths cannot drift.

    Reason codes are stable strings the operator surface and audit log
    pattern-match on.  Multiple rules may match — the first hit wins so
    the most specific reason is reported (trade_id > AAPL fingerprint
    > event_id > thesis > logged_by > thesis-empty-ai-model).
    """
    if not isinstance(row, dict):
        return ""

    trade_id = str(row.get("trade_id") or "").strip()
    if trade_id in FAKE_TRADE_IDS:
        return "fake_trade_id_blocklist"

    ticker = str(row.get("ticker") or "").strip().upper()
    price = _row_float(row, "price")
    quantity = _row_float(row, "quantity")
    if (
        ticker == FAKE_AAPL_TICKER
        and price == FAKE_AAPL_PRICE
        and quantity in FAKE_AAPL_QUANTITIES
    ):
        return "fake_aapl_fingerprint"

    event_id = str(row.get("event_id") or "").strip()
    if event_id.startswith(FAKE_EVENT_ID_PREFIXES):
        return "fake_event_id_prefix"

    thesis_hit = _contains_marker_substring(str(row.get("thesis") or ""))
    if thesis_hit:
        return f"fake_thesis_marker:{thesis_hit}"
    notes_hit = _contains_marker_substring(str(row.get("notes") or ""))
    if notes_hit:
        return f"fake_notes_marker:{notes_hit}"
    reason_hit = _contains_marker_substring(str(row.get("risk_reason") or ""))
    if reason_hit:
        return f"fake_risk_reason_marker:{reason_hit}"

    # logged_by / created_by / source: any of the three signalling
    # automation/test/seed origin triggers a veto, even when the row
    # has otherwise survived the canonical classifier.
    for source_key in ("logged_by", "created_by", "source"):
        source_val = str(row.get(source_key) or "").strip().lower()
        if source_val in FAKE_LOGGED_BY_VALUES:
            return f"fake_source:{source_key}={source_val}"

    # Empty ai_model_used + marker-like thesis/notes.  This is a softer
    # gate kept distinct from the substring rule so the audit log can
    # show "this row had no AI attribution AND a placeholder note",
    # which is the exact fingerprint of the leaked rows.  In practice
    # the substring rule already catches them, but the explicit gate
    # documents intent and survives any future relaxation of the
    # substring list.
    ai_model_used = str(row.get("ai_model_used") or "").strip()
    if not ai_model_used:
        for field in ("thesis", "notes"):
            if _contains_marker_substring(str(row.get(field) or "")):
                return "fake_empty_ai_model_with_marker"

    return ""


def is_fake_manual_trade_row(row: dict[str, Any]) -> bool:
    """Boolean shortcut around :func:`fake_manual_trade_reason`."""
    return bool(fake_manual_trade_reason(row))


def is_visible_manual_trade(row: dict[str, Any]) -> bool:
    """True iff ``row`` is BOTH a canonical user-manual row AND not a
    fake-marker match.  This is the predicate the Manual Trade Log GET
    route uses — origin filter alone is insufficient (see incident
    2026-05-18 where a fake row stamped ``manual_trade_log`` survived
    the origin-only filter)."""
    if not is_user_manual_trade(row):
        return False
    return not is_fake_manual_trade_row(row)


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
    "FAKE_TRADE_IDS",
    "FAKE_THESIS_SUBSTRINGS",
    "FAKE_EVENT_ID_PREFIXES",
    "FAKE_LOGGED_BY_VALUES",
    "FAKE_AAPL_QUANTITIES",
    "FAKE_AAPL_PRICE",
    "FAKE_AAPL_TICKER",
    "QUARANTINE_PROVENANCE",
    "REJECT_REASON_NON_USER_MARKER",
    "fake_manual_trade_reason",
    "is_fake_manual_trade_row",
    "is_visible_manual_trade",
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
