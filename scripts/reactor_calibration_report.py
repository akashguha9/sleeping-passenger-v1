"""
Reactor calibration report — honest, evidence-bounded readout.

Purpose
-------
A diagnostic system without outcome calibration becomes theatre.  This
script reads `manual_trades` and `reconciliation_results` from the local
SQLite database and produces a single read-only report whose job is to
tell the operator three things:

1. How much *reconciled* data we actually have.
2. What confidence the operator should place in any reactor-related
   inference given the current sample size.
3. Which fields are missing for proper reactor-vs-outcome calibration.

Crucially this report does NOT claim a reactor hit-rate or false-
positive rate when the sample size is small.  It does NOT unlock
execution, ever.  It surfaces gaps; it does not paper over them.

Confidence bands
----------------

    n < 10   -> "very_low"
    n < 30   -> "low"
    n < 100  -> "medium"
    n >= 100 -> "higher_but_contextual"

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

    python scripts/reactor_calibration_report.py
    python scripts/reactor_calibration_report.py --json
    python scripts/reactor_calibration_report.py --db-path runtime/mvp_local.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

VERY_LOW_THRESHOLD = 10
LOW_THRESHOLD = 30
MEDIUM_THRESHOLD = 100

_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}

ADVISORY_DISCLAIMER = (
    "Reactor calibration report is advisory-only.  It cannot grant "
    "execution permission, cannot unlock the pre-real-money preflight, "
    "and cannot override an unreconciled-backlog block.  Sample-size "
    "thresholds are deliberately conservative."
)

# Reactor-related fields the operator would need to compute hit-rate,
# false-positive rate, gallardo-block value, etc.  None of these are
# persisted at decision-time yet — see "limitations" in the output.
REACTOR_DECISION_FIELDS: tuple[str, ...] = (
    "reactor_state_at_decision",
    "decision_grade_energy_at_decision",
    "echo_risk_score_at_decision",
    "meltdown_risk_at_decision",
    "fusion_validity_at_decision",
    "fission_branch_clarity_at_decision",
    "operator_heat_at_decision",
    "gallardo_block_at_decision",
    "preflight_state_at_decision",
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


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return False
    return any(r[1] == column for r in rows)


def _confidence_band(n: int) -> str:
    if n < VERY_LOW_THRESHOLD:
        return "very_low"
    if n < LOW_THRESHOLD:
        return "low"
    if n < MEDIUM_THRESHOLD:
        return "medium"
    return "higher_but_contextual"


def _safe_count(conn: sqlite3.Connection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    try:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    except sqlite3.Error:
        return 0
    return int(row["n"]) if row else 0


def _outcome_distribution(conn: sqlite3.Connection) -> dict[str, int]:
    if not _table_exists(conn, "reconciliation_results"):
        return {}
    try:
        rows = conn.execute(
            "SELECT outcome_status AS k, COUNT(*) AS n"
            " FROM reconciliation_results GROUP BY outcome_status"
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {str(r["k"] or "UNKNOWN"): int(r["n"]) for r in rows}


def _process_error_distribution(conn: sqlite3.Connection) -> dict[str, int]:
    if not _table_exists(conn, "reconciliation_results"):
        return {}
    if not _column_exists(conn, "reconciliation_results", "process_error"):
        return {}
    try:
        rows = conn.execute(
            "SELECT process_error AS k, COUNT(*) AS n"
            " FROM reconciliation_results"
            " WHERE process_error IS NOT NULL AND process_error != ''"
            " GROUP BY process_error"
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {str(r["k"]): int(r["n"]) for r in rows}


_WARNING_REACTOR_STATES = frozenset(
    {"HOT_CONTAINMENT_REQUIRED", "OPERATOR_CONTROL_RODS", "ECHO_SUPPRESSED"}
)
_BENIGN_REACTOR_STATES = frozenset({"COLD_OBSERVE", "WARM_WATCH"})
_FAVOURABLE_REACTOR_STATES = frozenset({"FUSION_REVIEW_CANDIDATE"})
_OPERATOR_HEAT_HIGH_THRESHOLD = 0.6
_ECHO_RISK_HIGH_THRESHOLD = 0.6


def _calibration_aggregates(conn: sqlite3.Connection) -> dict[str, Any]:
    """Per-trade calibration roll-up from manual_trades + reconciliation_results.

    Only counts rows where the reactor-at-decision snapshot is present
    (``reactor_state_at_decision`` non-empty).  Each row is classified by
    a small, conservative rule set; ratios are NOT exposed because sample
    sizes are tiny and the labels are imperfect proxies for skill.

    Returns a dict with:
      - reactor_snapshot_count           (n trades with reactor snapshot)
      - reactor_snapshot_with_outcome    (subset that has a reconciliation)
      - calibration_labels               (dict[label, int])
      - high_operator_heat_count         (snapshot rows with heat >= 0.6)
      - high_echo_risk_count             (snapshot rows with echo >= 0.6)
      - gallardo_block_at_decision_count
      - fusion_validity_buckets          (dict[bucket, int])
      - lessons_captured                 (rows with non-empty lesson)
    """
    empty: dict[str, Any] = {
        "reactor_snapshot_count": 0,
        "reactor_snapshot_with_outcome": 0,
        "calibration_labels": {},
        "high_operator_heat_count": 0,
        "high_echo_risk_count": 0,
        "gallardo_block_at_decision_count": 0,
        "fusion_validity_buckets": {},
        "lessons_captured": 0,
    }
    if not _table_exists(conn, "manual_trades"):
        return empty
    # All 9 reactor-at-decision columns must be present before we attempt
    # calibration; otherwise existing fixture DBs would raise OperationalError.
    for col in REACTOR_DECISION_FIELDS:
        if not _column_exists(conn, "manual_trades", col):
            return empty

    rec_join = _table_exists(conn, "reconciliation_results")
    select_extra = (
        ", rr.outcome_status, rr.process_error, rr.outcome_quality"
        if rec_join
        else ", '' AS outcome_status, '' AS process_error, '' AS outcome_quality"
    )
    join_clause = (
        " LEFT JOIN reconciliation_results rr ON rr.trade_id = mt.trade_id"
        if rec_join
        else ""
    )
    try:
        rows = conn.execute(
            f"SELECT mt.reactor_state_at_decision AS reactor_state,"
            f"  mt.decision_grade_energy_at_decision AS dge,"
            f"  mt.echo_risk_score_at_decision AS echo,"
            f"  mt.meltdown_risk_at_decision AS meltdown,"
            f"  mt.fusion_validity_at_decision AS fusion,"
            f"  mt.fission_branch_clarity_at_decision AS fission,"
            f"  mt.operator_heat_at_decision AS heat,"
            f"  mt.gallardo_block_at_decision AS gallardo,"
            f"  mt.preflight_state_at_decision AS preflight,"
            f"  mt.lesson AS lesson"
            f"  {select_extra}"
            f" FROM manual_trades mt"
            f" {join_clause}"
        ).fetchall()
    except sqlite3.Error:
        return empty

    snapshot_rows = [r for r in rows if (r["reactor_state"] or "").strip()]
    if not snapshot_rows:
        return empty

    labels: dict[str, int] = {
        "reactor_warned_correctly": 0,
        "reactor_false_positive": 0,
        "reactor_false_negative": 0,
        "reactor_helped": 0,
        "reactor_no_call": 0,
        "gallardo_block_ignored": 0,
        "operator_heat_damage_suspected": 0,
        "insufficient_outcome_data": 0,
    }
    fusion_buckets: dict[str, int] = {}
    high_heat = 0
    high_echo = 0
    gallardo_count = 0
    lessons = 0
    with_outcome = 0

    for r in snapshot_rows:
        state = (r["reactor_state"] or "").strip()
        outcome = (r["outcome_status"] or "").strip().upper() if rec_join else ""
        gallardo = bool(r["gallardo"])
        heat = r["heat"]
        echo = r["echo"]
        process_error = (r["process_error"] or "").strip() if rec_join else ""
        fusion = (r["fusion"] or "").strip() or "unknown"
        lesson = (r["lesson"] or "").strip()

        fusion_buckets[fusion] = fusion_buckets.get(fusion, 0) + 1
        if gallardo:
            gallardo_count += 1
        if heat is not None and heat >= _OPERATOR_HEAT_HIGH_THRESHOLD:
            high_heat += 1
        if echo is not None and echo >= _ECHO_RISK_HIGH_THRESHOLD:
            high_echo += 1
        if lesson:
            lessons += 1

        if outcome in {"WIN", "LOSS", "BREAKEVEN"}:
            with_outcome += 1
        else:
            labels["insufficient_outcome_data"] += 1
            continue

        # Gallardo block ignored: the operator logged a trade despite the
        # block being active at decision time.  We can't measure "obeyed"
        # from the trade table alone — that's the absence of a log.
        if gallardo:
            labels["gallardo_block_ignored"] += 1

        if state in _WARNING_REACTOR_STATES:
            if outcome == "LOSS":
                labels["reactor_warned_correctly"] += 1
            elif outcome == "WIN":
                labels["reactor_false_positive"] += 1
            # BREAKEVEN: no label increment — ambiguous.
        elif state in _BENIGN_REACTOR_STATES:
            if outcome == "LOSS":
                labels["reactor_false_negative"] += 1
        elif state in _FAVOURABLE_REACTOR_STATES:
            if outcome == "WIN":
                labels["reactor_helped"] += 1
        else:
            labels["reactor_no_call"] += 1

        if (
            heat is not None
            and heat >= _OPERATOR_HEAT_HIGH_THRESHOLD
            and process_error
        ):
            labels["operator_heat_damage_suspected"] += 1

    return {
        "reactor_snapshot_count": len(snapshot_rows),
        "reactor_snapshot_with_outcome": with_outcome,
        "calibration_labels": labels,
        "high_operator_heat_count": high_heat,
        "high_echo_risk_count": high_echo,
        "gallardo_block_at_decision_count": gallardo_count,
        "fusion_validity_buckets": fusion_buckets,
        "lessons_captured": lessons,
    }


def _journal_completeness_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Average journal completeness across reconciled trades, using
    `self_test_journal_quality.score_journal_entry` if available."""
    empty: dict[str, Any] = {
        "available": False,
        "trade_count": 0,
        "average_completeness": 0.0,
        "learning_ready_count": 0,
    }
    if not (
        _table_exists(conn, "manual_trades")
        and _table_exists(conn, "reconciliation_results")
    ):
        return empty
    try:
        try:
            from scripts.self_test_journal_quality import (  # type: ignore[import-not-found]
                score_journal_entries,
                score_journal_entry,
            )
        except ModuleNotFoundError:
            from self_test_journal_quality import (  # type: ignore[no-redef]
                score_journal_entries,
                score_journal_entry,
            )
    except Exception:
        return empty

    cols_present = {
        c: _column_exists(conn, "manual_trades", c)
        for c in (
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
    }
    select_cols = ["mt.trade_id", "mt.event_id", "mt.quantity", "mt.thesis"]
    for c, present in cols_present.items():
        if present:
            select_cols.append(f"mt.{c}")
    select_cols += ["rr.outcome_status", "rr.outcome_notes"]
    try:
        rows = conn.execute(
            f"SELECT {', '.join(select_cols)}"  # noqa: S608
            " FROM manual_trades mt"
            " INNER JOIN reconciliation_results rr ON rr.trade_id = mt.trade_id"
        ).fetchall()
    except sqlite3.Error:
        return empty

    entries: list[dict[str, Any]] = []
    for row in rows:
        row_dict = {k: row[k] for k in row.keys()}
        entries.append(
            {
                "signal_id": str(row_dict.get("event_id") or ""),
                "thesis": str(row_dict.get("thesis") or ""),
                "invalidation_level": str(row_dict.get("invalidation_level") or ""),
                "expected_horizon": str(row_dict.get("expected_horizon") or ""),
                "position_size": float(row_dict.get("quantity") or 0.0),
                "risk_reason": str(row_dict.get("risk_reason") or ""),
                "entry_reason": str(row_dict.get("entry_reason") or ""),
                "exit_plan": str(row_dict.get("exit_plan") or ""),
                "confidence_before": row_dict.get("confidence_before"),
                "emotional_state": str(row_dict.get("emotional_state") or ""),
                "post_trade_outcome": str(row_dict.get("outcome_notes") or ""),
                "reconciliation_status": str(row_dict.get("outcome_status") or ""),
                "mistake_tags": [
                    t.strip()
                    for t in str(row_dict.get("mistake_tags") or "").split(",")
                    if t.strip()
                ],
                "lesson": str(row_dict.get("lesson") or ""),
            }
        )

    agg = score_journal_entries(entries)
    # Per-entry only used for completeness — never displayed.
    for entry in entries:
        score_journal_entry(entry)
    return {
        "available": True,
        "trade_count": int(agg.get("entry_count", 0)),
        "average_completeness": float(agg.get("average_completeness", 0.0)),
        "average_learning_readiness": float(
            agg.get("average_learning_readiness", 0.0)
        ),
        "learning_ready_count": int(agg.get("learning_ready_count", 0)),
    }


def _reactor_self_check_via_self_test() -> dict[str, Any]:
    """Inherit the existing reactor self-check from self_test_report so the
    calibration report and the self-test report agree on reactor health."""
    try:
        try:
            from scripts.self_test_report import _reactor_self_check  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            from self_test_report import _reactor_self_check  # type: ignore[no-redef]
        return _reactor_self_check()
    except Exception:
        return {
            "available": False,
            "reactor_state": "INSUFFICIENT_DATA",
            "recommendation": "observe",
            "safety_invariants_ok": False,
            "import_error": "self_test_report._reactor_self_check unavailable",
        }


def build_report(db_path: Path | None = None) -> dict[str, Any]:
    """Build the calibration report.  Read-only; never raises."""
    db_path = Path(db_path) if db_path else _default_db_path()
    limitations: list[str] = []

    if not db_path.exists():
        out: dict[str, Any] = {
            "report": "reactor_calibration_report",
            "db_path": str(db_path),
            "db_available": False,
            "limitations": ["db_missing"],
            "advisory_disclaimer": ADVISORY_DISCLAIMER,
        }
        out.update(_SAFETY_STAMPS)
        return out

    conn = _readonly_connect(db_path)
    if conn is None:
        out = {
            "report": "reactor_calibration_report",
            "db_path": str(db_path),
            "db_available": False,
            "limitations": ["db_open_failed"],
            "advisory_disclaimer": ADVISORY_DISCLAIMER,
        }
        out.update(_SAFETY_STAMPS)
        return out

    try:
        manual_trade_count = _safe_count(conn, "manual_trades")
        reconciled_count = _safe_count(conn, "reconciliation_results")
        outcome_dist = _outcome_distribution(conn)
        process_error_dist = _process_error_distribution(conn)
        journal = _journal_completeness_summary(conn)
        calibration = _calibration_aggregates(conn)

        # Confidence band derives from the reconciled-trade count — that
        # is the only number where signal-vs-outcome attribution exists.
        confidence = _confidence_band(reconciled_count)
        # A second, stricter band: how many trades have BOTH a reactor
        # snapshot at decision time AND a reconciled outcome.  This is
        # the real ceiling for reactor calibration claims.
        calibration_confidence = _confidence_band(
            int(calibration.get("reactor_snapshot_with_outcome", 0))
        )

        # Inventory missing reactor-at-decision fields.  When a migration
        # has not yet added them, calibration cannot be computed and the
        # report surfaces this as a hard gap.
        missing_decision_fields: list[str] = []
        for col in REACTOR_DECISION_FIELDS:
            # manual_trades is the natural place to attach them.
            if not _column_exists(conn, "manual_trades", col):
                missing_decision_fields.append(col)

        if not _table_exists(conn, "manual_trades"):
            limitations.append("manual_trades_table_missing")
        if not _table_exists(conn, "reconciliation_results"):
            limitations.append("reconciliation_results_table_missing")
        if manual_trade_count == 0:
            limitations.append("no_manual_trades_logged_yet")
        if reconciled_count == 0:
            limitations.append("no_reconciled_trades_yet")
        if missing_decision_fields:
            limitations.append("reactor_at_decision_fields_not_persisted")
        elif int(calibration.get("reactor_snapshot_count", 0)) == 0:
            limitations.append("no_trades_with_reactor_snapshot_yet")
        elif int(calibration.get("reactor_snapshot_with_outcome", 0)) == 0:
            limitations.append("no_reactor_snapshot_paired_with_outcome_yet")
        if not journal.get("available"):
            limitations.append("journal_quality_helper_unavailable")
        if confidence in ("very_low", "low"):
            limitations.append("sample_size_too_small_for_calibration_claims")
        if calibration_confidence in ("very_low", "low"):
            limitations.append("calibration_sample_too_small_for_reactor_claims")
    finally:
        conn.close()

    reactor_self_check = _reactor_self_check_via_self_test()

    out = {
        "report": "reactor_calibration_report",
        "db_path": str(db_path),
        "db_available": True,
        "manual_trade_count": manual_trade_count,
        "reconciled_count": reconciled_count,
        "outcome_distribution": outcome_dist,
        "process_error_distribution": process_error_dist,
        "journal": journal,
        "calibration": calibration,
        "reactor_self_check": reactor_self_check,
        "confidence_band": confidence,
        "calibration_confidence_band": calibration_confidence,
        "confidence_thresholds": {
            "very_low_lt": VERY_LOW_THRESHOLD,
            "low_lt": LOW_THRESHOLD,
            "medium_lt": MEDIUM_THRESHOLD,
        },
        "missing_decision_fields": missing_decision_fields,
        "limitations": limitations,
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        # Explicit non-claims — what this report CANNOT honestly say yet.
        "non_claims": [
            "reactor_hit_rate is NOT exposed as a ratio; per-label counts "
            "are reported so the operator can read raw evidence.",
            "gallardo_block 'obeyed' is NOT measurable from manual_trades "
            "alone; only 'ignored' (a logged trade despite the block) is.",
            "Echo-risk utility is NOT computed as a ratio; only counts of "
            "high-echo decisions are exposed.",
            "Calibration confidence is bounded by the count of trades "
            "with BOTH a reactor snapshot AND a reconciled outcome.",
            "Per-label counts at small n are descriptive evidence, not "
            "estimates of skill; do not infer alpha from these numbers.",
        ],
    }
    out.update(_SAFETY_STAMPS)
    return out


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Reactor Calibration Report")
    lines.append("=" * 28)
    if not payload.get("db_available", False):
        lines.append(f"DB: {payload['db_path']} (unavailable)")
        for lim in payload.get("limitations", []):
            lines.append(f"  - {lim}")
        return "\n".join(lines) + "\n"
    lines.append(f"DB: {payload['db_path']}")
    lines.append(f"Manual trades logged   : {payload['manual_trade_count']}")
    lines.append(f"Reconciled trades      : {payload['reconciled_count']}")
    lines.append(f"Confidence band        : {payload['confidence_band']}")
    lines.append(
        f"Calibration confidence : {payload.get('calibration_confidence_band', 'very_low')}"
    )
    calibration = payload.get("calibration") or {}
    if calibration:
        lines.append(
            f"Reactor snapshot count : {calibration.get('reactor_snapshot_count', 0)}"
            f" (with outcome: {calibration.get('reactor_snapshot_with_outcome', 0)})"
        )
        lab = calibration.get("calibration_labels") or {}
        if any(lab.values()):
            lines.append("Calibration labels (counts only — not ratios):")
            for k, v in sorted(lab.items()):
                if v:
                    lines.append(f"  - {k}: {v}")
    journal = payload.get("journal", {}) or {}
    if journal.get("available"):
        lines.append(
            f"Avg journal completeness: {journal['average_completeness']:.3f}"
            f" (learning-ready {journal['learning_ready_count']})"
        )
    rsc = payload.get("reactor_self_check", {}) or {}
    lines.append(
        f"Reactor self-check     : available={rsc.get('available', False)},"
        f" state={rsc.get('reactor_state', 'INSUFFICIENT_DATA')},"
        f" invariants_ok={rsc.get('safety_invariants_ok', False)}"
    )
    if payload.get("outcome_distribution"):
        lines.append("Outcome distribution:")
        for k, v in sorted(payload["outcome_distribution"].items()):
            lines.append(f"  - {k}: {v}")
    if payload.get("missing_decision_fields"):
        lines.append("Reactor-at-decision fields NOT persisted yet:")
        for f in payload["missing_decision_fields"]:
            lines.append(f"  - {f}")
    if payload.get("limitations"):
        lines.append("Limitations:")
        for lim in payload["limitations"]:
            lines.append(f"  - {lim}")
    lines.append("Non-claims (what this report CANNOT honestly say):")
    for nc in payload.get("non_claims", []):
        lines.append(f"  - {nc}")
    lines.append("")
    lines.append(payload["advisory_disclaimer"])
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="reactor_calibration_report.py",
        description=(
            "Read-only honest readout of reactor-vs-outcome calibration "
            "evidence.  Never grants execution permission."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    payload = build_report(db_path)
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2, default=str))
    else:
        print(_render_text(payload))
    return 0 if payload.get("db_available", False) else 1


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "ADVISORY_DISCLAIMER",
    "VERY_LOW_THRESHOLD",
    "LOW_THRESHOLD",
    "MEDIUM_THRESHOLD",
    "REACTOR_DECISION_FIELDS",
    "build_report",
]


if __name__ == "__main__":
    raise SystemExit(main())
