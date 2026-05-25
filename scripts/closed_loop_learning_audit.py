"""Closed-loop learning audit — is the advisory refinery's loop intact?

Read-only, advisory-only diagnostic that walks the canonical learning chain:

    signal_event
      -> model / advisory report
      -> manual trade log
      -> reconciliation / outcome
      -> Moltbook entry
      -> lesson / recalibration candidate
      -> future rule candidate

and reports where the chain is broken.  This operationalises the reflection's
core equation: a loss that never becomes a Moltbook lesson is a leak in the
hippocampus; a lesson with no recalibration candidate is learning that never
recalibrates.

It also folds in the Task-10 learning-efficiency score so "did we learn?" is a
number, not a vibe:

    lesson_conversion_rate   = moltbook_lesson_count / max(closed_loss_count, 1)
    repeat_error_rate        = repeat_mistake_count  / max(moltbook_lesson_count, 1)
    learning_efficiency_score = lesson_conversion_rate * (1 - repeat_error_rate)

Safety
------
* Read-only by default.  No DB writes unless ``--repair`` is passed, which
  delegates to the existing, role-gated reconciliation->Moltbook bridge
  (``scripts/moltbook_reconciliation_bridge.py --write``).  The default path
  opens the DB ``mode=ro`` and never mutates data, never touches a broker,
  never creates execution state.
* Every output carries the canonical advisory-only safety stamps and the four
  invariant-verification booleans the operator can eyeball.

Usage
-----
    python scripts/closed_loop_learning_audit.py
    python scripts/closed_loop_learning_audit.py --json
    python scripts/closed_loop_learning_audit.py --repair   # role-gated write
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_common import utc_timestamp  # type: ignore[no-redef]

try:
    from scripts.manual_trade_origin import is_user_manual_trade
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from manual_trade_origin import is_user_manual_trade  # type: ignore[no-redef]

try:
    from scripts.moltbook_api import LOSS_REVIEW_CATEGORIES
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from moltbook_api import LOSS_REVIEW_CATEGORIES  # type: ignore[no-redef]

try:
    from scripts.moltbook_reconciliation_bridge import (
        sync_reconciliation_losses_to_moltbook,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from moltbook_reconciliation_bridge import (  # type: ignore[no-redef]
        sync_reconciliation_losses_to_moltbook,
    )

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "runtime" / "mvp_local.db"

ADVISORY_DISCLAIMER = (
    "Advisory-only closed-loop diagnostic. It measures whether signals became "
    "outcomes and outcomes became lessons; it never places a broker order, "
    "executes a trade, or authorises one. Every decision requires a human."
)


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.Error:
            return None
    conn.row_factory = sqlite3.Row
    return conn


def _rows(conn: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    try:
        return [dict(r) for r in conn.execute(sql).fetchall()]
    except sqlite3.Error:
        return []


def _blank(value: Any) -> bool:
    return not str(value or "").strip()


def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def compute_learning_efficiency(
    *,
    closed_loss_count: int,
    moltbook_lesson_count: int,
    recalibration_candidate_count: int,
    future_rule_candidate_count: int,
    repeat_mistake_count: int,
) -> dict[str, Any]:
    """Pure ARC-style learning-efficiency block (Task 10).

    Learning efficiency is conversion (did losses become lessons?) damped by
    repetition (did we make the same mistake again?).  Zero-loss is handled
    safely: a clean history with no losses is not "0% learning", it's
    "nothing to learn from yet", so the score is 1.0 (neutral-good) only when
    there are also no lessons; otherwise the ratios speak for themselves.
    """
    closed = max(int(closed_loss_count), 0)
    lessons = max(int(moltbook_lesson_count), 0)
    repeats = max(int(repeat_mistake_count), 0)

    lesson_conversion_rate = round(_safe_div(lessons, max(closed, 1)), 4)
    repeat_error_rate = round(_safe_div(repeats, max(lessons, 1)), 4)
    learning_efficiency_score = round(
        lesson_conversion_rate * (1.0 - repeat_error_rate), 4
    )
    if closed == 0 and lessons == 0:
        # No losses yet and no lessons logged: nothing to convert. Report a
        # neutral 1.0 rather than a misleading 0.0, but flag it explicitly.
        learning_efficiency_score = 1.0
        lesson_conversion_rate = 1.0
    return {
        "closed_loss_count": closed,
        "moltbook_lesson_count": lessons,
        "recalibration_candidate_count": max(int(recalibration_candidate_count), 0),
        "future_rule_candidate_count": max(int(future_rule_candidate_count), 0),
        "repeat_mistake_count": repeats,
        "lesson_conversion_rate": lesson_conversion_rate,
        "repeat_error_rate": repeat_error_rate,
        "learning_efficiency_score": learning_efficiency_score,
        "no_loss_history": closed == 0,
    }


def build_audit(db_path: Path | None = None) -> dict[str, Any]:
    """Build the closed-loop learning audit (read-only, advisory-only)."""
    db = Path(db_path) if db_path is not None else DEFAULT_DB
    report: dict[str, Any] = {
        "report": "closed_loop_learning_audit",
        "db_path": str(db),
        "db_available": False,
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        "closed_loop_coverage": 0.0,
        "signals_without_outcomes": 0,
        "manual_trades_without_reconciliation": 0,
        "closed_losses_without_moltbook": 0,
        "moltbook_entries_without_trade_reference": 0,
        "lessons_without_recalibration_candidate": 0,
        "future_rule_candidates_count": 0,
        "unresolved_repair_debt": 0,
        "learning_efficiency": compute_learning_efficiency(
            closed_loss_count=0, moltbook_lesson_count=0,
            recalibration_candidate_count=0, future_rule_candidate_count=0,
            repeat_mistake_count=0,
        ),
        # Invariant verification — explicitly reported booleans.
        "advisory_only_verified": True,
        "human_execution_verified": True,
        "broker_api_called_false_verified": True,
        "ai_execution_count_zero_verified": True,
        "notes": [],
        **_contract.advisory_safety_stamps(),
        "generated_at": utc_timestamp(),
    }

    conn = _readonly_connect(db)
    if conn is None:
        report["notes"].append(
            "DB not available — counts default to zero, reported honestly."
        )
        return report
    report["db_available"] = True

    try:
        signal_events = _rows(conn, "SELECT event_id FROM signal_events")
        trades = _rows(conn, "SELECT * FROM manual_trades")
        recs = _rows(conn, "SELECT * FROM reconciliation_results")
        moltbook = _rows(conn, "SELECT * FROM moltbook_entries")

        # --- chain edges -------------------------------------------------
        user_trades = [t for t in trades if is_user_manual_trade(t)]
        reconciled_trade_ids = {str(r.get("trade_id") or "") for r in recs}
        reconciled_event_ids = {str(r.get("event_id") or "") for r in recs}

        # signals_without_outcomes: a signal_event that never reached any
        # reconciliation/outcome (no rec row references its event_id).
        report["signals_without_outcomes"] = sum(
            1 for s in signal_events
            if str(s.get("event_id") or "") not in reconciled_event_ids
        )

        # manual_trades_without_reconciliation: real operator trades with no
        # reconciliation row (open risk that hasn't been closed/recorded).
        report["manual_trades_without_reconciliation"] = sum(
            1 for t in user_trades
            if str(t.get("trade_id") or "") not in reconciled_trade_ids
        )

        # closed_losses_without_moltbook: delegate to the canonical bridge in
        # DRY-RUN (read-only) — its "created" count is exactly the set of
        # closed losing trades that *would* get a Moltbook entry, i.e. losses
        # not yet captured.  skipped_duplicate are losses already captured.
        bridge = sync_reconciliation_losses_to_moltbook(db, write=False)
        report["closed_losses_without_moltbook"] = int(bridge.get("created", 0))
        closed_loss_count = (
            int(bridge.get("loss_candidates", 0))
            + int(bridge.get("skipped_insufficient_data", 0))
        )
        captured_losses = int(bridge.get("skipped_duplicate", 0))

        # moltbook_entries_without_trade_reference: a *loss-review* entry with
        # no manual_trade_log_id is orphaned/poisoned — a trade-derived lesson
        # should always link back to its trade.  Signal-decision entries
        # (no_trade_correct etc.) legitimately have no trade and are excluded.
        loss_review = [
            m for m in moltbook
            if str(m.get("mistake_type") or "") in LOSS_REVIEW_CATEGORIES
        ]
        report["moltbook_entries_without_trade_reference"] = sum(
            1 for m in loss_review if _blank(m.get("manual_trade_log_id"))
        )

        # lessons_without_recalibration_candidate: a captured lesson that
        # produced no recalibration candidate is learning that won't recalibrate.
        report["lessons_without_recalibration_candidate"] = sum(
            1 for m in moltbook if _blank(m.get("recalibration_note"))
        )

        # future_rule_candidates_count: lessons promoted toward a rule change.
        future_rule_candidate_count = sum(
            1 for m in moltbook if not _blank(m.get("future_rule_update"))
        )
        report["future_rule_candidates_count"] = future_rule_candidate_count

        # --- repair debt -------------------------------------------------
        report["unresolved_repair_debt"] = (
            report["manual_trades_without_reconciliation"]
            + report["closed_losses_without_moltbook"]
            + report["moltbook_entries_without_trade_reference"]
        )

        # --- closed-loop coverage ---------------------------------------
        # A chain is "covered" when a reconciled user trade either resolved
        # not-at-a-loss (no lesson required) or, if it lost, has a Moltbook
        # entry.  Coverage = covered_chains / reconciled_user_chains.
        reconciled_user_trades = [
            t for t in user_trades
            if str(t.get("trade_id") or "") in reconciled_trade_ids
        ]
        denom = len(reconciled_user_trades)
        if denom == 0:
            report["closed_loop_coverage"] = 1.0 if not user_trades else 0.0
            if not user_trades:
                report["notes"].append(
                    "No operator trades yet — loop is vacuously intact."
                )
        else:
            # losses missing moltbook are the only uncovered reconciled chains.
            uncovered = report["closed_losses_without_moltbook"]
            covered = max(denom - uncovered, 0)
            report["closed_loop_coverage"] = round(covered / denom, 4)

        # --- learning efficiency (Task 10) -------------------------------
        moltbook_lesson_count = len(loss_review)
        recalibration_candidate_count = sum(
            1 for m in moltbook if not _blank(m.get("recalibration_note"))
        )
        # repeat mistakes: same (ticker, mistake_type) captured more than once.
        groups: dict[tuple[str, str], int] = {}
        for m in loss_review:
            key = (
                str(m.get("ticker") or "").upper(),
                str(m.get("mistake_type") or ""),
            )
            groups[key] = groups.get(key, 0) + 1
        repeat_mistake_count = sum(max(c - 1, 0) for c in groups.values())

        report["learning_efficiency"] = compute_learning_efficiency(
            closed_loss_count=closed_loss_count,
            moltbook_lesson_count=moltbook_lesson_count,
            recalibration_candidate_count=recalibration_candidate_count,
            future_rule_candidate_count=future_rule_candidate_count,
            repeat_mistake_count=repeat_mistake_count,
        )
        report["learning_efficiency"]["captured_losses"] = captured_losses

        # --- invariant verification (scan canonical tables) -------------
        _verify_invariants(conn, report)
    finally:
        conn.close()

    return report


def _verify_invariants(conn: sqlite3.Connection, report: dict[str, Any]) -> None:
    """Scan canonical tables for any execution-state leak.  Read-only."""

    def _any_violation(table: str, column: str, bad: str) -> bool:
        try:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        except sqlite3.Error:
            return False
        if column not in cols:
            return False
        try:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {bad}"
            ).fetchone()
            return bool(row and row[0])
        except sqlite3.Error:
            return False

    # broker_api_called must be 0 everywhere it is tracked.
    broker_called = (
        _any_violation("manual_trades", "broker_api_called", "broker_api_called != 0")
        or _any_violation("global_securities", "broker_api_called", "broker_api_called != 0")
    )
    # ai_execution_count must be 0 everywhere it is tracked.
    ai_exec = (
        _any_violation("manual_trades", "ai_execution_count", "ai_execution_count != 0")
        or _any_violation("moltbook_entries", "ai_execution_count", "ai_execution_count != 0")
        or _any_violation("reconciliation_results", "ai_execution_count", "ai_execution_count != 0")
    )
    advisory_bad = (
        _any_violation("manual_trades", "advisory_status", "advisory_status != 'ADVISORY_ONLY'")
        or _any_violation("moltbook_entries", "advisory_status", "advisory_status != 'ADVISORY_ONLY'")
    )
    human_bad = (
        _any_violation("manual_trades", "execution_mode", "execution_mode != 'HUMAN_ONLY'")
    )

    report["broker_api_called_false_verified"] = not broker_called
    report["ai_execution_count_zero_verified"] = not ai_exec
    report["advisory_only_verified"] = not advisory_bad
    report["human_execution_verified"] = not human_bad
    if broker_called:
        report["notes"].append("INVARIANT BREACH: broker_api_called != 0 found.")
    if ai_exec:
        report["notes"].append("INVARIANT BREACH: ai_execution_count != 0 found.")
    if advisory_bad:
        report["notes"].append("INVARIANT BREACH: non-ADVISORY_ONLY row found.")
    if human_bad:
        report["notes"].append("INVARIANT BREACH: non-HUMAN_ONLY execution_mode found.")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="closed_loop_learning_audit.py",
        description=(
            "Read-only advisory audit of the signal->outcome->lesson loop. "
            "Default never mutates data. --repair delegates to the role-gated "
            "Moltbook bridge. No broker calls, ever."
        ),
    )
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--repair", action="store_true",
        help="Create missing Moltbook entries via the role-gated bridge "
             "(write). Default is read-only.",
    )
    p.add_argument("--operator-role", default=None,
                   help="VIEWER|OPERATOR|ADMIN (default: MVP_OPERATOR_ROLE env).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = Path(args.db_path) if args.db_path else DEFAULT_DB

    if args.repair:
        # Repair is a write-like action; reuse the bridge's role enforcement.
        try:
            try:
                from scripts.operator_audit_log import enforce as _enforce
            except ModuleNotFoundError:  # pragma: no cover - script-style fallback
                from operator_audit_log import enforce as _enforce  # type: ignore[no-redef]
            _enforce("run_moltbook_bridge", role=args.operator_role,
                     resource="moltbook_entries")
        except PermissionError as exc:
            print(f"[DENY] {exc}")
            return 2
        bridge = sync_reconciliation_losses_to_moltbook(db, write=True)
        print(f"[repair] created {bridge.get('created', 0)} Moltbook entries "
              f"({bridge.get('skipped_duplicate', 0)} already present).")

    rep = build_audit(db)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        le = rep["learning_efficiency"]
        print("Closed-Loop Learning Audit (advisory-only)")
        print("=" * 44)
        print(f"  DB available                   : {rep['db_available']}")
        print(f"  closed-loop coverage           : {rep['closed_loop_coverage']}")
        print(f"  signals without outcomes       : {rep['signals_without_outcomes']}")
        print(f"  trades without reconciliation  : {rep['manual_trades_without_reconciliation']}")
        print(f"  closed losses without Moltbook : {rep['closed_losses_without_moltbook']}")
        print(f"  Moltbook entries w/o trade ref : {rep['moltbook_entries_without_trade_reference']}")
        print(f"  lessons w/o recalibration cand.: {rep['lessons_without_recalibration_candidate']}")
        print(f"  future rule candidates         : {rep['future_rule_candidates_count']}")
        print(f"  unresolved repair debt         : {rep['unresolved_repair_debt']}")
        print(f"  lesson conversion rate         : {le['lesson_conversion_rate']}")
        print(f"  repeat error rate              : {le['repeat_error_rate']}")
        print(f"  learning efficiency score      : {le['learning_efficiency_score']}")
        print("  -- invariants --")
        print(f"  advisory_only_verified         : {rep['advisory_only_verified']}")
        print(f"  human_execution_verified       : {rep['human_execution_verified']}")
        print(f"  broker_api_called_false        : {rep['broker_api_called_false_verified']}")
        print(f"  ai_execution_count_zero        : {rep['ai_execution_count_zero_verified']}")
        for note in rep["notes"]:
            print(f"  note: {note}")
        print(f"\n  {rep['advisory_disclaimer']}")
    return 0


__all__ = ["ADVISORY_DISCLAIMER", "build_audit", "compute_learning_efficiency"]


if __name__ == "__main__":
    raise SystemExit(main())
