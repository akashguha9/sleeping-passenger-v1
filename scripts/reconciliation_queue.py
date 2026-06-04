"""
Local reconciliation queue — surfaces unreconciled manual trades.

Purpose
-------
A manual trade that is never reconciled does not produce a learning event.
The self-test report counts unreconciled trades; this helper turns that
count into an inspectable *queue* the operator can iterate through.

Read-only.  No DB writes.  No broker calls.  No execution permission.

Definition of "unreconciled"
----------------------------
A row in ``manual_trades`` is unreconciled if ALL of the following hold:

1. It was created through the Manual Trade Log UI/API
   (``created_via = 'manual_trade_log'``).  Rows with empty / unknown
   provenance (smoke seeds, demo fixtures, JSONL imports, historical
   sample rows like SPY/QQQ "Strong persistence…" / "Exit on kill rate…")
   are excluded — Reconciliation is the live operator surface, not a
   dump of every row in the table.
2. It has not been soft-cancelled (``reconciliation_status`` is not
   ``CANCELLED_DUPLICATE`` / ``CANCELLED_LOG``).
3. It has no row in ``reconciliation_results`` with the same ``trade_id``.
4. Defence in depth: ``broker_api_called`` is 0 and
   ``ai_execution_count`` is 0.  This app never sets either, but a
   corrupt/imported row that did would still be excluded.

Output shape
------------
Per item: the trade fields plus journal-quality metadata (completeness
score, learning-ready flag, missing fields) plus ``age_days`` since the
trade's ``executed_at``.

Summary: unreconciled_count, oldest_unreconciled_age_days,
average_journal_completeness, learning_ready_count, missing_field
distribution, plus by_ticker / by_emotional_state / by_expected_horizon
break-downs.

Safety contract
---------------

    advisory_status        = "ADVISORY_ONLY"
    execution_gate         = "LOCKED"
    broker_api_called      = False
    ai_execution_count     = 0
    execution_permission   = False
    can_execute            = False

Usage
-----
    python scripts/reconciliation_queue.py
    python scripts/reconciliation_queue.py --json
    python scripts/reconciliation_queue.py --limit 50 --json
    python scripts/reconciliation_queue.py --db-path runtime/mvp_local.db
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sqlite3
from pathlib import Path
from typing import Any

# Safety constants sourced from the single shared advisory contract so this
# read-only queue cannot drift to an inconsistent stamp.  Values unchanged.
try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

ADVISORY_STATUS = _contract.ADVISORY_STATUS
EXECUTION_GATE_LOCKED = _contract.EXECUTION_GATE_LOCKED

# Provenance contract for the Reconciliation queue.  ONLY rows whose
# created_via column equals this exact value AND that pass the user-
# manual classifier appear in the live queue.  Empty / unknown
# provenance, probe theses, test event_ids, and synthetic trade_modes
# are excluded by design — Reconciliation is the human operator's
# record-keeping surface, not a dump of every row in the manual_trades
# table.  See scripts/manual_trade_origin.py for the full predicate.
MANUAL_TRADE_LOG_PROVENANCE = "manual_trade_log"

try:
    from scripts.manual_trade_origin import (
        PROBE_THESIS_VALUES,
        PROBE_EVENT_ID_PREFIXES,
        EXCLUDED_LOGGED_BY,
        EXCLUDED_TRADE_MODES,
        USER_TRADE_MODES,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from manual_trade_origin import (  # type: ignore[no-redef]
        PROBE_THESIS_VALUES,
        PROBE_EVENT_ID_PREFIXES,
        EXCLUDED_LOGGED_BY,
        EXCLUDED_TRADE_MODES,
        USER_TRADE_MODES,
    )

ADVISORY_DISCLAIMER = (
    "Reconciliation queue is advisory-only. Listing a trade here does not "
    "place, modify, or cancel any broker order. Reconciliation is operator-"
    "entered record keeping."
)

OPERATOR_ACTION = (
    "Reconcile each listed trade by recording actual fill price, quantity, "
    "outcome status, outcome quality, process error (if any), and a one-line "
    "lesson. Do this within 1-3 trading days of the trade to keep learning value high."
)

_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}


_JOURNAL_FIELDS: tuple[str, ...] = (
    "invalidation_level",
    "expected_horizon",
    "risk_reason",
    "entry_reason",
    "exit_plan",
    "confidence_before",
    "emotional_state",
    "mistake_tags",
    "lesson",
)


def _default_db_path() -> Path:
    try:
        try:
            from scripts.persistence import DB_PATH  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            from persistence import DB_PATH  # type: ignore[no-redef]
        return Path(DB_PATH)
    except Exception:
        return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.Error:
            return None
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _columns_present(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return set()
    return {r[1] for r in rows}


def _parse_iso8601(value: Any) -> _dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt


def _age_days(executed_at: Any, now: _dt.datetime) -> float | None:
    dt = _parse_iso8601(executed_at)
    if dt is None:
        return None
    delta = now - dt
    return round(delta.total_seconds() / 86400.0, 4)


def _empty_summary() -> dict[str, Any]:
    return {
        "unreconciled_count": 0,
        "oldest_unreconciled_age_days": None,
        "average_journal_completeness": 0.0,
        "average_learning_readiness": 0.0,
        "learning_ready_count": 0,
        "missing_field_distribution": {},
        "by_ticker": {},
        "by_emotional_state": {},
        "by_expected_horizon": {},
    }


# constrained_first_priority is computed by the PURE signal-geometry layer.
# We import it lazily/defensively so a missing module degrades to the legacy
# executed_at ordering rather than breaking the queue.  Importing it here adds
# no side effects — the function is pure and read-only.
try:
    from scripts.signal_geometry_reflection import compute_constrained_first_priority
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    try:
        from signal_geometry_reflection import compute_constrained_first_priority  # type: ignore[no-redef]
    except ImportError:
        compute_constrained_first_priority = None  # type: ignore[assignment]
except ImportError:  # pragma: no cover
    compute_constrained_first_priority = None  # type: ignore[assignment]

# Unreconciled trades age out of usefulness; map age to a pseudo-freshness so
# the constrained-first scorer surfaces the most stale items first.  A trade
# older than this many days is treated as fully stale (freshness 0).
_STALE_FRESHNESS_DAYS = 30.0


def _priority_signal_from_item(item: dict[str, Any]) -> dict[str, Any]:
    """Translate a queue item into the input dict the constrained-first
    priority scorer understands.

    Only fields that genuinely apply to an *unreconciled* manual trade are
    populated.  Outcome-driven factors (stop-loss / take-profit breach,
    reconciliation mismatch, realized loss) have no value yet for a trade
    that has not been reconciled, so they default to absent.  The factors
    that DO apply here are: staleness (age), missing exit data, duplicate
    ambiguity, and leverage exposure.  Advisory ordering only — never an
    execution instruction.
    """
    age = item.get("age_days")
    if isinstance(age, (int, float)):
        freshness = max(0.0, 1.0 - (float(age) / _STALE_FRESHNESS_DAYS))
    else:
        freshness = 0.0  # unknown age => treat as stale => higher priority
    # Missing exit data: no invalidation level AND no exit plan recorded.
    has_invalidation = bool(str(item.get("invalidation_level") or "").strip())
    has_exit_plan = bool(str(item.get("exit_plan") or "").strip())
    missing_exit_data = not (has_invalidation or has_exit_plan)
    exit_options_score = 0.1 if missing_exit_data else 0.8
    ambiguity = 0.8 if item.get("possible_duplicate") else 0.0
    return {
        "freshness_score": freshness,
        "ambiguity_score": ambiguity,
        "exit_options_score": exit_options_score,
        "leverage": item.get("leverage", 1.0),
        # No reconciliation outcome yet for an unreconciled trade.
        "stop_loss_breached": False,
        "take_profit_breached": False,
        "reconciliation_mismatch": False,
        "chaos_score": 0.0,
    }


def _attach_priority(item: dict[str, Any]) -> None:
    """Compute and attach constrained_first_priority fields to a queue item.

    Mutates ``item`` in place.  Pure / advisory: adds a fragility score and a
    handle_now / handle_soon / handle_later bucket.  Never an order action.
    """
    if compute_constrained_first_priority is None:
        item["constrained_first_priority"] = 0.0
        item["priority_bucket"] = "handle_later"
        return
    scored = compute_constrained_first_priority(_priority_signal_from_item(item))
    item["constrained_first_priority"] = float(
        scored.get("constrained_first_priority") or 0.0
    )
    item["priority_bucket"] = str(scored.get("priority_bucket") or "handle_later")
    item["priority_components"] = scored.get("components", {})


def _build_journal_entry(row: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
    """Shape one trade row into the dict expected by score_journal_entry()."""
    return {
        "signal_id": str(row.get("event_id") or ""),
        "thesis": str(row.get("thesis") or ""),
        "invalidation_level": str(row.get("invalidation_level") or ""),
        "expected_horizon": str(row.get("expected_horizon") or ""),
        "position_size": float(row.get("quantity") or 0.0),
        "risk_reason": str(row.get("risk_reason") or ""),
        "entry_reason": str(row.get("entry_reason") or ""),
        "exit_plan": str(row.get("exit_plan") or ""),
        "confidence_before": row.get("confidence_before"),
        "emotional_state": str(row.get("emotional_state") or ""),
        "post_trade_outcome": outcome.get("outcome_notes") or "",
        "reconciliation_status": outcome.get("outcome_status") or "",
        "mistake_tags": [
            t.strip()
            for t in str(row.get("mistake_tags") or "").split(",")
            if t.strip()
        ],
        "lesson": str(row.get("lesson") or ""),
    }


def build_queue(
    db_path: Path | None = None,
    *,
    limit: int | None = None,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Return the unreconciled-trade queue + summary, plus safety stamps.

    Parameters
    ----------
    db_path : Path | None
        Defaults to the persistence module's DB_PATH.
    limit : int | None
        Cap the number of items returned. ``None`` returns all.  The
        summary is always computed across the full unreconciled set
        regardless of limit, so the operator never gets a misleadingly
        small ``oldest_unreconciled_age_days``.
    now : datetime | None
        Override the current time for deterministic tests.

    Read-only.  Never raises on a missing/unopenable DB; instead returns
    an empty queue and a ``warnings`` list explaining why.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    path = Path(db_path) if db_path else _default_db_path()
    warnings: list[str] = []
    base: dict[str, Any] = {
        "report": "reconciliation_queue",
        "db_path": str(path),
        "db_available": False,
        "items": [],
        "summary": _empty_summary(),
        "warnings": warnings,
        "operator_action": OPERATOR_ACTION,
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    base.update(_SAFETY_STAMPS)

    if not path.exists():
        warnings.append("db_missing")
        return base

    conn = _readonly_connect(path)
    if conn is None:
        warnings.append("db_open_failed")
        return base

    try:
        if not _table_exists(conn, "manual_trades"):
            warnings.append("manual_trades_table_missing")
            return base
        if not _table_exists(conn, "reconciliation_results"):
            warnings.append("reconciliation_results_table_missing")
            # Continue anyway — every trade is unreconciled in this case.

        cols = _columns_present(conn, "manual_trades")
        select_cols = [c for c in (
            "trade_id", "event_id", "ticker", "side", "quantity", "price",
            "executed_at", "thesis", "leverage", *_JOURNAL_FIELDS,
        ) if c in cols]
        if "trade_id" not in select_cols:
            warnings.append("manual_trades_missing_trade_id_column")
            return base

        # Exclude soft-cancelled log rows (e.g. duplicate manual entries the
        # operator cancelled from the Reconciliation tab).  Cancelled rows
        # keep their audit trail in manual_trades but must not appear here
        # as "awaiting reconciliation" — they were record-keeping mistakes,
        # not trades waiting on an outcome.
        cancel_clause = ""
        if "reconciliation_status" in cols:
            cancel_clause = (
                " AND COALESCE(mt.reconciliation_status, '') NOT IN"
                " ('CANCELLED_DUPLICATE', 'CANCELLED_LOG')"
            )
        # Provenance filter: only show rows the operator entered through
        # the Manual Trade Log UI/API.  Empty / unknown provenance is
        # excluded by default so smoke seeds, demo fixtures, JSONL
        # imports, and historical sample rows never pollute the live
        # queue.  When the column is missing on a very old DB we emit a
        # warning and refuse to fall back to unfiltered listing — better
        # to surface an empty queue than to leak seeds.
        if "created_via" in cols:
            provenance_clause = (
                " AND COALESCE(mt.created_via, '') = ?"
            )
            provenance_params: tuple[Any, ...] = (MANUAL_TRADE_LOG_PROVENANCE,)
        else:
            warnings.append("manual_trades_missing_created_via_column")
            provenance_clause = " AND 1=0"  # exclude everything
            provenance_params = ()
        # Defence in depth: refuse to surface rows that ever claimed
        # broker_api_called=1 or ai_execution_count!=0, even though this
        # app never sets either.  Keeps the contract honest if a corrupt
        # row is ever imported.
        broker_clause = (
            " AND COALESCE(mt.broker_api_called, 0) = 0"
            if "broker_api_called" in cols else ""
        )
        ai_clause = (
            " AND COALESCE(mt.ai_execution_count, 0) = 0"
            if "ai_execution_count" in cols else ""
        )
        # Secondary, content-based filters that the SQL provenance gate
        # cannot catch on its own: probe theses, test event_id prefixes,
        # automation logged_by sources, and unsafe trade_modes.  These
        # mirror the canonical predicate in scripts/manual_trade_origin
        # so the queue, learning completeness, and the cancel guard all
        # agree on what counts as a user-entered manual log.
        thesis_placeholders = ",".join("?" for _ in PROBE_THESIS_VALUES)
        probe_thesis_clause = (
            f" AND LOWER(TRIM(COALESCE(mt.thesis, ''))) NOT IN ({thesis_placeholders})"
            if "thesis" in cols and PROBE_THESIS_VALUES else ""
        )
        probe_thesis_params: tuple[Any, ...] = tuple(PROBE_THESIS_VALUES)
        if "event_id" in cols and PROBE_EVENT_ID_PREFIXES:
            # Escape underscores so SQL LIKE 'EV_%' matches the literal
            # prefix 'EV_' rather than 'EV<single-char>'.  Without ESCAPE
            # the underscore is a SQL wildcard and would exclude legit
            # event_ids like 'EV1' / 'EV2'.
            event_id_clauses = " AND ".join(
                "COALESCE(mt.event_id, '') NOT LIKE ? ESCAPE '\\'"
                for _ in PROBE_EVENT_ID_PREFIXES
            )
            probe_event_id_clause = f" AND ({event_id_clauses})"
            # NB: keep the backslash escape OUT of the f-string expression —
            # backslashes inside f-string braces are a SyntaxError on Py<3.12,
            # which silently broke this module's import (and the preflight
            # reconciliation subcheck) until 3.12.
            _esc_underscore = "\\_"
            probe_event_id_params: tuple[Any, ...] = tuple(
                p.replace("_", _esc_underscore) + "%" for p in PROBE_EVENT_ID_PREFIXES
            )
        else:
            probe_event_id_clause = ""
            probe_event_id_params = ()
        if "logged_by" in cols and EXCLUDED_LOGGED_BY:
            lb_placeholders = ",".join("?" for _ in EXCLUDED_LOGGED_BY)
            excluded_logged_by_clause = (
                f" AND LOWER(TRIM(COALESCE(mt.logged_by, ''))) NOT IN ({lb_placeholders})"
            )
            excluded_logged_by_params: tuple[Any, ...] = tuple(EXCLUDED_LOGGED_BY)
        else:
            excluded_logged_by_clause = ""
            excluded_logged_by_params = ()
        if "trade_mode" in cols and EXCLUDED_TRADE_MODES:
            tm_placeholders = ",".join("?" for _ in EXCLUDED_TRADE_MODES)
            excluded_trade_mode_clause = (
                f" AND UPPER(TRIM(COALESCE(mt.trade_mode, ''))) NOT IN ({tm_placeholders})"
            )
            excluded_trade_mode_params: tuple[Any, ...] = tuple(EXCLUDED_TRADE_MODES)
        else:
            excluded_trade_mode_clause = ""
            excluded_trade_mode_params = ()
        select_clause = ", ".join(select_cols)
        try:
            rows = conn.execute(
                f"SELECT {select_clause} FROM manual_trades mt"  # noqa: S608
                " WHERE NOT EXISTS ("
                "   SELECT 1 FROM reconciliation_results rr"
                "   WHERE rr.trade_id = mt.trade_id"
                " )"
                + cancel_clause
                + provenance_clause
                + broker_clause
                + ai_clause
                + probe_thesis_clause
                + probe_event_id_clause
                + excluded_logged_by_clause
                + excluded_trade_mode_clause
                + " ORDER BY mt.executed_at ASC",
                provenance_params
                + probe_thesis_params
                + probe_event_id_params
                + excluded_logged_by_params
                + excluded_trade_mode_params,
            ).fetchall()
        except sqlite3.Error as exc:
            warnings.append(f"query_failed:{type(exc).__name__}")
            return base

        try:
            from scripts.self_test_journal_quality import (  # type: ignore[import-not-found]
                score_journal_entry,
            )
        except ModuleNotFoundError:
            try:
                from self_test_journal_quality import (  # type: ignore[no-redef]
                    score_journal_entry,
                )
            except ImportError:
                score_journal_entry = None  # type: ignore[assignment]
                warnings.append("journal_quality_helper_unavailable")

        base["db_available"] = True

        try:
            from scripts.manual_trade_origin import duplicate_group_key
        except ModuleNotFoundError:  # pragma: no cover - script fallback
            from manual_trade_origin import duplicate_group_key  # type: ignore[no-redef]

        # Build duplicate-group counts up front so each item can carry a
        # flag without an N^2 inner loop.  Same ticker+side+qty+price in
        # the same UTC minute is treated as a duplicate of a manual log
        # (e.g. operator double-clicked Log).  Real distinct trades that
        # differ in size, price, or executed_at are unaffected.
        dup_group_counts: dict[str, int] = {}
        all_dicts: list[dict[str, Any]] = []
        for row in rows:
            row_dict = {k: row[k] for k in row.keys()}
            all_dicts.append(row_dict)
            key = duplicate_group_key(row_dict)
            dup_group_counts[key] = dup_group_counts.get(key, 0) + 1

        items: list[dict[str, Any]] = []
        for row_dict in all_dicts:
            outcome = {"outcome_status": "", "outcome_notes": ""}
            entry = _build_journal_entry(row_dict, outcome)
            if score_journal_entry is not None:
                quality = score_journal_entry(entry)
                completeness = float(quality.get("journal_completeness_score") or 0.0)
                readiness = float(quality.get("learning_readiness_score") or 0.0)
                learning_ready = bool(quality.get("learning_ready"))
                missing = list(quality.get("missing_fields") or [])
            else:
                completeness = 0.0
                readiness = 0.0
                learning_ready = False
                missing = list(_JOURNAL_FIELDS)

            dup_key = duplicate_group_key(row_dict)
            dup_count = dup_group_counts.get(dup_key, 1)
            item: dict[str, Any] = {
                "trade_id": str(row_dict.get("trade_id") or ""),
                "event_id": str(row_dict.get("event_id") or ""),
                "ticker": str(row_dict.get("ticker") or ""),
                "side": str(row_dict.get("side") or ""),
                "quantity": float(row_dict.get("quantity") or 0.0),
                "price": float(row_dict.get("price") or 0.0),
                "executed_at": str(row_dict.get("executed_at") or ""),
                "age_days": _age_days(row_dict.get("executed_at"), now),
                "thesis": str(row_dict.get("thesis") or ""),
                "leverage": float(row_dict.get("leverage") or 1.0),
                "origin_label": "USER_MANUAL",
                "duplicate_group_key": dup_key,
                "duplicate_count": dup_count,
                "possible_duplicate": dup_count > 1,
                "invalidation_level": str(row_dict.get("invalidation_level") or ""),
                "expected_horizon": str(row_dict.get("expected_horizon") or ""),
                "risk_reason": str(row_dict.get("risk_reason") or ""),
                "entry_reason": str(row_dict.get("entry_reason") or ""),
                "exit_plan": str(row_dict.get("exit_plan") or ""),
                "confidence_before": row_dict.get("confidence_before"),
                "emotional_state": str(row_dict.get("emotional_state") or ""),
                "mistake_tags": str(row_dict.get("mistake_tags") or ""),
                "lesson": str(row_dict.get("lesson") or ""),
                "journal_completeness_score": round(completeness, 6),
                "learning_readiness_score": round(readiness, 6),
                "learning_ready": learning_ready,
                "missing_journal_fields": missing,
                "needs_reconciliation": True,
            }
            item.update(_SAFETY_STAMPS)
            _attach_priority(item)
            items.append(item)

        # Build summary over the FULL unreconciled set, not the limited view.
        oldest_age: float | None = None
        completeness_sum = 0.0
        readiness_sum = 0.0
        learning_ready_count = 0
        missing_dist: dict[str, int] = {}
        by_ticker: dict[str, int] = {}
        by_emotional_state: dict[str, int] = {}
        by_expected_horizon: dict[str, int] = {}

        for it in items:
            age = it.get("age_days")
            if isinstance(age, (int, float)):
                if oldest_age is None or age > oldest_age:
                    oldest_age = float(age)
            completeness_sum += float(it.get("journal_completeness_score") or 0.0)
            readiness_sum += float(it.get("learning_readiness_score") or 0.0)
            if it.get("learning_ready"):
                learning_ready_count += 1
            for field in it.get("missing_journal_fields") or []:
                missing_dist[field] = missing_dist.get(field, 0) + 1
            tkr = it["ticker"] or "UNKNOWN"
            by_ticker[tkr] = by_ticker.get(tkr, 0) + 1
            em = it["emotional_state"] or "UNRECORDED"
            by_emotional_state[em] = by_emotional_state.get(em, 0) + 1
            hz = it["expected_horizon"] or "UNRECORDED"
            by_expected_horizon[hz] = by_expected_horizon.get(hz, 0) + 1

        n = len(items)
        avg_completeness = (completeness_sum / n) if n else 0.0
        avg_readiness = (readiness_sum / n) if n else 0.0

        summary = {
            "unreconciled_count": n,
            "oldest_unreconciled_age_days": (
                round(oldest_age, 4) if oldest_age is not None else None
            ),
            "average_journal_completeness": round(avg_completeness, 6),
            "average_learning_readiness": round(avg_readiness, 6),
            "learning_ready_count": learning_ready_count,
            "missing_field_distribution": missing_dist,
            "by_ticker": by_ticker,
            "by_emotional_state": by_emotional_state,
            "by_expected_horizon": by_expected_horizon,
        }
        base["summary"] = summary

        # constrained_first_priority ordering: surface the most fragile /
        # high-risk items first.  Stable sort by descending priority keeps the
        # underlying executed_at-ASC order as the tiebreaker, so equal-priority
        # items still read oldest-first.  Advisory ordering ONLY — this does
        # not authorize, place, modify, or cancel any order.
        items.sort(key=lambda it: it.get("constrained_first_priority", 0.0), reverse=True)
        base["ordering"] = "constrained_first_priority"
        base["ordering_advisory_only"] = True

        if isinstance(limit, int) and limit >= 0:
            base["items"] = items[:limit]
            if limit < n:
                base["truncated"] = True
                base["truncated_to"] = limit
        else:
            base["items"] = items

        return base
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Reconciliation Queue")
    lines.append("=" * 24)
    summary = payload["summary"]
    lines.append(f"Unreconciled: {summary['unreconciled_count']}")
    age = summary["oldest_unreconciled_age_days"]
    lines.append(f"Oldest age days: {age if age is not None else '-'}")
    lines.append(
        f"Avg journal completeness: {summary['average_journal_completeness']:.3f}"
    )
    lines.append(
        f"Avg learning readiness:  {summary['average_learning_readiness']:.3f}"
    )
    lines.append(f"Learning-ready: {summary['learning_ready_count']}")
    if payload.get("warnings"):
        lines.append("Warnings: " + ", ".join(payload["warnings"]))
    lines.append("")
    lines.append("Operator action:")
    lines.append(f"  {payload['operator_action']}")
    lines.append("")
    lines.append(payload["advisory_disclaimer"])
    items = payload["items"]
    if items:
        lines.append("")
        lines.append("Items:")
        for it in items:
            lines.append(
                f"  - {it['trade_id']:>14} {it['ticker']:>6} {it['side']:<4} "
                f"qty={it['quantity']} age={it['age_days']} "
                f"complete={it['journal_completeness_score']:.2f} "
                f"ready={it['learning_ready']}"
            )
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="reconciliation_queue.py",
        description=(
            "Read-only local queue of unreconciled manual trades. Never "
            "places, modifies, or cancels broker orders."
        ),
    )
    p.add_argument("--db-path", type=str, default=None,
                   help="Path to runtime/mvp_local.db (default: persistence module).")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap the number of items in the listing (summary still global).")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    payload = build_queue(db_path, limit=args.limit)
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2, default=str))
    else:
        print(_render_text(payload))
    return 0 if payload.get("db_available", False) else 1


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "ADVISORY_DISCLAIMER",
    "OPERATOR_ACTION",
    "MANUAL_TRADE_LOG_PROVENANCE",
    "build_queue",
]


if __name__ == "__main__":
    raise SystemExit(main())
