"""Real Evidence Sprint — Phase 2: live decision -> outcome labelling flow.

Grows the *real forward* calibration corpus honestly by attaching realized
binary outcomes ``y_i`` to the ``model_probability`` ``p_i`` that was persisted
at decision time (``decision_probability_snapshots``).  It NEVER fabricates an
outcome and NEVER counts an unresolved decision.

Eligibility (a pair counts toward the REAL forward calibration gate only when
ALL hold)::

    Eligible_i = I(p_i not NULL) · I(0 <= p_i <= 1) · I(y_i in {0,1})
               · I(is_real_outcome_i) · I(horizon_elapsed_i)
               · I(not excluded_from_calibration_i)
               · I(outcome_kind_i == 'real_forward')

Two corpora are tracked separately and never mixed for claims:

    D_real_forward   actual paper/live advisory decisions + later outcomes
    D_historical_proxy  backtest/proxy labels (research/evidence only)

``D_historical_proxy`` can never unlock ``predictive_claim_allowed`` — only
``D_real_forward`` (and then only when N>=200, Brier<=0.25, ECE<=0.10, computed
elsewhere in the audited calibration path).

This module is additive: it extends ``decision_probability_snapshots`` with
nullable columns and writes only outcome metadata.  No execution path exists.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # package layout
    from scripts.decision_probability_snapshot import TABLE, ensure_schema
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    from decision_probability_snapshot import TABLE, ensure_schema  # type: ignore[no-redef]

# Outcome kinds.
REAL_FORWARD = "real_forward"
HISTORICAL_PROXY = "historical_proxy"

# Reasons a decision is attached-but-excluded, or rejected outright.
REASON_MISSING_PROBABILITY = "MISSING_PROBABILITY"
REASON_INVALID_LABEL = "OUTCOME_LABEL_MUST_BE_0_OR_1"
REASON_NOT_REAL_OUTCOME = "NOT_A_REAL_OUTCOME"
REASON_OPEN_TRADE = "OPEN_TRADE_NOT_RESOLVED"
REASON_HORIZON_NOT_ELAPSED = "HORIZON_NOT_ELAPSED"
REASON_SNAPSHOT_NOT_FOUND = "SNAPSHOT_NOT_FOUND"
REASON_OK = "OK"

# Additive columns this flow needs on the snapshot table.
_NEW_COLUMNS: dict[str, str] = {
    "outcome_source": "TEXT",
    "is_real_outcome": "INTEGER",
    "outcome_kind": "TEXT",
    "excluded_from_calibration": "INTEGER DEFAULT 0",
    "exclusion_reason": "TEXT",
    "horizon_elapsed": "INTEGER",
}

_SAFETY = {
    "advisory_status": "ADVISORY_ONLY",
    "human_execution_required": True,
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_outcome_columns(conn: sqlite3.Connection) -> None:
    ensure_schema(conn)
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({TABLE})")}
    for col, decl in _NEW_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {decl}")
    conn.commit()


def _valid_p(p: Any) -> bool:
    try:
        pf = float(p)
    except (TypeError, ValueError):
        return False
    return 0.0 <= pf <= 1.0


# --------------------------------------------------------------------------- #
# Outcome -> y_i mapping helpers (pure)
# --------------------------------------------------------------------------- #
def realized_return(entry_price: float, exit_price: float) -> float:
    """(P_exit - P_entry) / P_entry."""
    if entry_price == 0:
        raise ZeroDivisionError("entry_price must be non-zero")
    return (exit_price - entry_price) / entry_price


def label_return_ge_threshold(
    entry_price: float, exit_price: float, target_return_threshold: float
) -> int:
    """y = I(r >= threshold)."""
    return int(realized_return(entry_price, exit_price) >= target_return_threshold)


def label_alpha_ge_threshold(
    entry_price: float,
    exit_price: float,
    benchmark_entry: float,
    benchmark_exit: float,
    alpha_threshold: float,
) -> int:
    """y = I(alpha >= threshold) where alpha = r_asset - r_benchmark."""
    alpha = realized_return(entry_price, exit_price) - realized_return(
        benchmark_entry, benchmark_exit
    )
    return int(alpha >= alpha_threshold)


def label_stop_loss_vs_target(*, stop_loss_hit: bool, target_hit: bool) -> int | None:
    """y = 0 if stop hit before target, 1 if target hit before stop.

    Ambiguous (both/neither resolved) -> ``None`` (not labellable).
    """
    if stop_loss_hit and not target_hit:
        return 0
    if target_hit and not stop_loss_hit:
        return 1
    return None


# --------------------------------------------------------------------------- #
# Attach a realized outcome to a decision snapshot
# --------------------------------------------------------------------------- #
def attach_outcome(
    db_path: str | Path,
    decision_id: str,
    y: Any,
    *,
    outcome_timestamp: str | None = None,
    outcome_source: str = "manual_reconciliation",
    is_real_outcome: bool = True,
    outcome_kind: str = REAL_FORWARD,
    horizon_elapsed: bool = True,
    trade_open: bool = False,
    now_utc: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """Attach a realized outcome ``y`` to decision snapshot ``decision_id``.

    Rejected (nothing stored) when: snapshot missing, ``y`` not in {0,1}, the
    outcome is not a real outcome (fabricated/mock), the trade is still open, or
    the prediction horizon has not elapsed.

    Stored-but-excluded (recorded, but never calibration-eligible) when the
    decision carried no usable ``model_probability`` at decision time.
    """
    result: dict[str, Any] = {
        "decision_id": decision_id,
        "attached": False,
        "calibration_eligible": False,
        "excluded_from_calibration": False,
        "outcome_kind": outcome_kind,
        "reason": REASON_OK,
        **_SAFETY,
    }

    # Hard rejections that never write an outcome -------------------------- #
    if y not in (0, 1):
        result["reason"] = REASON_INVALID_LABEL
        return result
    if not is_real_outcome:
        result["reason"] = REASON_NOT_REAL_OUTCOME
        return result
    if trade_open:
        result["reason"] = REASON_OPEN_TRADE
        return result
    if not horizon_elapsed:
        result["reason"] = REASON_HORIZON_NOT_ELAPSED
        return result

    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        _ensure_outcome_columns(conn)
        row = conn.execute(
            f"SELECT model_probability FROM {TABLE} WHERE snapshot_id = ?",
            (decision_id,),
        ).fetchone()
        if row is None:
            result["reason"] = REASON_SNAPSHOT_NOT_FOUND
            return result

        p = row["model_probability"]
        excluded = not _valid_p(p)
        exclusion_reason = REASON_MISSING_PROBABILITY if excluded else None

        conn.execute(
            f"UPDATE {TABLE} SET"
            "  outcome_label = ?,"
            "  outcome_timestamp_utc = ?,"
            "  outcome_source = ?,"
            "  is_real_outcome = ?,"
            "  outcome_kind = ?,"
            "  excluded_from_calibration = ?,"
            "  exclusion_reason = ?,"
            "  horizon_elapsed = ?"
            " WHERE snapshot_id = ?",
            (
                int(y),
                outcome_timestamp or now_utc or _utc_now_iso(),
                str(outcome_source),
                1 if is_real_outcome else 0,
                str(outcome_kind),
                1 if excluded else 0,
                exclusion_reason or (reason or None),
                1 if horizon_elapsed else 0,
                decision_id,
            ),
        )
        conn.commit()

        result["attached"] = True
        result["excluded_from_calibration"] = excluded
        eligible = (
            (not excluded)
            and is_real_outcome
            and horizon_elapsed
            and outcome_kind == REAL_FORWARD
            and _valid_p(p)
        )
        result["calibration_eligible"] = bool(eligible)
        result["reason"] = exclusion_reason or REASON_OK
        return result
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Corpus summary
# --------------------------------------------------------------------------- #
def build_outcome_corpus_summary(db_path: str | Path) -> dict[str, Any]:
    """Honest accounting of the decision/outcome corpus.

    Never mixes ``real_forward`` and ``historical_proxy`` pairs.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        _ensure_outcome_columns(conn)
        rows = conn.execute(
            f"SELECT model_probability, outcome_label, is_real_outcome,"
            f" outcome_kind, excluded_from_calibration, exclusion_reason,"
            f" horizon_elapsed FROM {TABLE}"
        ).fetchall()
    finally:
        conn.close()

    n_snapshots = len(rows)
    n_with_outcome = 0
    n_valid_p = 0
    n_real_forward_pairs = 0
    n_historical_proxy_pairs = 0
    n_excluded = 0
    exclusion_reasons: dict[str, int] = {}

    for r in rows:
        p = r["model_probability"]
        y = r["outcome_label"]
        p_ok = _valid_p(p)
        if p_ok:
            n_valid_p += 1
        has_outcome = y in (0, 1)
        if has_outcome:
            n_with_outcome += 1
        excluded = bool(r["excluded_from_calibration"])
        if excluded:
            n_excluded += 1
            key = r["exclusion_reason"] or "UNSPECIFIED"
            exclusion_reasons[key] = exclusion_reasons.get(key, 0) + 1

        kind = r["outcome_kind"]
        is_real = bool(r["is_real_outcome"])
        horizon_ok = bool(r["horizon_elapsed"])

        if has_outcome and p_ok and not excluded:
            if kind == REAL_FORWARD and is_real and horizon_ok:
                n_real_forward_pairs += 1
            elif kind == HISTORICAL_PROXY:
                n_historical_proxy_pairs += 1

    return {
        "n_snapshots": n_snapshots,
        "n_with_outcome": n_with_outcome,
        "n_valid_p": n_valid_p,
        "n_real_forward_pairs": n_real_forward_pairs,
        "n_historical_proxy_pairs": n_historical_proxy_pairs,
        "n_excluded": n_excluded,
        "exclusion_reasons": exclusion_reasons,
        # The forward gate can never be unlocked from here.
        "predictive_claim_allowed": False,
        "calibration_status": (
            "INSUFFICIENT_EVIDENCE" if n_real_forward_pairs < 200 else "PENDING_METRICS"
        ),
        **_SAFETY,
    }


__all__ = [
    "REAL_FORWARD",
    "HISTORICAL_PROXY",
    "REASON_MISSING_PROBABILITY",
    "REASON_INVALID_LABEL",
    "REASON_NOT_REAL_OUTCOME",
    "REASON_OPEN_TRADE",
    "REASON_HORIZON_NOT_ELAPSED",
    "REASON_SNAPSHOT_NOT_FOUND",
    "realized_return",
    "label_return_ge_threshold",
    "label_alpha_ge_threshold",
    "label_stop_loss_vs_target",
    "attach_outcome",
    "build_outcome_corpus_summary",
]
