"""NBI track record ledger — case quality, edge-claim gate, advisory ledger.

Three honesty mechanisms for the evidence factory:

1. **Evidence Quality Score (EQS)** — a corpus-hygiene multiplier so garbage
   cases can never feed calibration:

       EQS = Citation x OutcomeClarity x PriceCompleteness
             x BranchLabelCompleteness x OperatorDecisionCompleteness
       EQS10 = 10 * EQS;   calibration-eligible  <=>  EQS10 >= 7
                                                  AND case_kind == REAL

2. **Edge-claim permission gate** — the system may claim edge only when ALL
   of these hold (any missing component -> false):

       N_real_closed_eligible >= 30
       Brier_model < Brier_baseline          (baseline = outcome base rate)
       ECE <= 0.10
       MeanR > 0
       MaxDrawdown <= limit (5 R)

3. **Advisory track record ledger** — open/close/summarize recommendation
   entries in canonical SQLite.  Fixtures never count; below the minimum
   closed count the summary is TRACK_RECORD_INSUFFICIENT and refuses
   hit-rate/mean-R performance claims.

Advisory-only.  Paper bookkeeping; no broker, no execution, no sizing.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.advisory_contract import advisory_safety_stamps
from scripts.nbi_store import (
    CANONICAL_DB_PATH,
    CASE_KIND_REAL,
    init_nbi_schema,
)

LEDGER_VERSION = "nbi-ledger-v1.0"

EQS_CALIBRATION_ELIGIBLE_MIN = 7.0
EDGE_MIN_ELIGIBLE_CASES = 30
EDGE_ECE_MAX = 0.10
EDGE_DRAWDOWN_LIMIT_R = 5.0
TRACK_RECORD_MIN_CLOSED = 10
TRACK_RECORD_INSUFFICIENT = "TRACK_RECORD_INSUFFICIENT"

_LEDGER_SCHEMA = """CREATE TABLE IF NOT EXISTS nbi_track_record (
    recommendation_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    operator_action TEXT NOT NULL DEFAULT '',
    action_class TEXT NOT NULL DEFAULT '',
    ticker_basket_json TEXT NOT NULL DEFAULT '[]',
    initial_score REAL,
    initial_branch_probabilities_json TEXT NOT NULL DEFAULT '{}',
    initial_rumor_risk REAL,
    initial_hedge_need REAL,
    invalidation_condition TEXT NOT NULL DEFAULT '',
    close_timestamp TEXT,
    close_reason TEXT NOT NULL DEFAULT '',
    realized_return REAL,
    benchmark_return REAL,
    return_vs_benchmark REAL,
    r_multiple REAL,
    evidence_quality_score REAL,
    calibration_eligible INTEGER NOT NULL DEFAULT 0,
    is_fixture INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT ''
)"""


def _resolve(db_path: Path | str | None) -> Path:
    return Path(db_path) if db_path is not None else CANONICAL_DB_PATH


def _connect(db_path: Path | str | None) -> sqlite3.Connection:
    path = _resolve(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _now_iso(now_iso: str | None) -> str:
    if now_iso:
        return now_iso
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def init_ledger_schema(db_path: Path | str | None = None) -> None:
    init_nbi_schema(db_path)
    conn = _connect(db_path)
    try:
        conn.execute(_LEDGER_SCHEMA)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Evidence Quality Score
# ---------------------------------------------------------------------------

_KNOWN_OUTCOMES = frozenset({
    "CORE_HELD_INTACT", "CORE_HELD_SUB_BRANCH_COLLAPSED", "CORE_DIED",
    "RUMOR_TRUE", "RUMOR_FALSE",
})
_BRANCH_LABEL_KEYS = ("core", "venue", "delegation", "deals")


def compute_case_quality(case: dict[str, Any]) -> dict[str, Any]:
    """EQS over one backtest case dict (as returned by the store)."""
    labels = case.get("resolution_labels") or {}
    refs = case.get("evidence_refs") or []

    citation = 1.0 if refs else 0.3
    outcome = str(labels.get("outcome_label") or "")
    label_confidence = labels.get("label_confidence")
    try:
        label_confidence = float(label_confidence)
    except (TypeError, ValueError):
        label_confidence = 0.7  # undeclared confidence -> haircut, not credit
    outcome_clarity = (
        max(0.0, min(1.0, label_confidence)) if outcome in _KNOWN_OUTCOMES else 0.0
    )
    price = 1.0 if case.get("return_vs_benchmark") is not None else 0.4
    branch_outcomes = labels.get("branch_outcomes") or {}
    branch_completeness = sum(
        1 for k in _BRANCH_LABEL_KEYS if branch_outcomes.get(k) is not None
    ) / len(_BRANCH_LABEL_KEYS)
    operator = 1.0 if labels.get("operator_actions") else 0.5

    eqs = citation * outcome_clarity * price * branch_completeness * operator
    eqs10 = round(10.0 * eqs, 4)
    eligible = (
        eqs10 >= EQS_CALIBRATION_ELIGIBLE_MIN
        and not case.get("is_fixture")
        and case.get("case_kind", CASE_KIND_REAL) == CASE_KIND_REAL
        and bool(case.get("resolution_timestamp"))
    )
    return {
        "EQS10": eqs10,
        "calibration_eligible": eligible,
        "components": {
            "citation_completeness": citation,
            "outcome_clarity": round(outcome_clarity, 4),
            "price_data_completeness": price,
            "branch_label_completeness": round(branch_completeness, 4),
            "operator_decision_completeness": operator,
        },
    }


def eligible_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in cases if compute_case_quality(c)["calibration_eligible"]]


# ---------------------------------------------------------------------------
# Edge-claim permission gate
# ---------------------------------------------------------------------------


def compute_edge_claim_permission(
    backtest_cases: list[dict[str, Any]],
    calibration_report: dict[str, Any] | None = None,
    track_summary: dict[str, Any] | None = None,
    *,
    ece_max: float = EDGE_ECE_MAX,
    drawdown_limit_r: float = EDGE_DRAWDOWN_LIMIT_R,
) -> dict[str, Any]:
    """EdgeClaimAllowed only when every requirement is met and measured.

    A missing component is a failed requirement — absence of evidence is
    never treated as passing evidence.
    """
    eligible = eligible_cases(backtest_cases)
    n = len(eligible)
    missing: list[str] = []

    if n < EDGE_MIN_ELIGIBLE_CASES:
        missing.append(
            f"eligible_real_closed_cases {n} < {EDGE_MIN_ELIGIBLE_CASES}"
        )

    metrics = (calibration_report or {}).get("metrics") or {}
    brier = metrics.get("brier")
    baseline = (calibration_report or {}).get("baseline_brier")
    if brier is None or baseline is None:
        missing.append("brier/baseline not computable")
    elif not brier < baseline:
        missing.append(f"brier {brier} not better than baseline {baseline}")
    ece = metrics.get("ece")
    if ece is None:
        missing.append("ece not computable")
    elif ece > ece_max:
        missing.append(f"ece {ece} > {ece_max}")

    r_values = [
        c.get("r_multiple") for c in eligible if c.get("r_multiple") is not None
    ]
    if not r_values:
        missing.append("no r_multiple outcomes recorded")
    else:
        mean_r = sum(r_values) / len(r_values)
        if mean_r <= 0:
            missing.append(f"mean R {mean_r:.3f} <= 0")
        drawdown = _max_drawdown_r(r_values)
        if drawdown > drawdown_limit_r:
            missing.append(f"max drawdown {drawdown:.2f}R > {drawdown_limit_r}R")

    if track_summary and track_summary.get("status") == TRACK_RECORD_INSUFFICIENT:
        missing.append("track record insufficient")

    allowed = not missing
    return {
        "edge_claim_allowed": allowed,
        "reason": (
            "all requirements met — human calibration review still required"
            if allowed else "requirements not met"
        ),
        "missing_requirements": missing,
        "current_case_count": n,
        "required_case_count": EDGE_MIN_ELIGIBLE_CASES,
        "calibration_status": (calibration_report or {}).get(
            "status", "NOT_RUN"
        ),
        "performance_status": "MEASURED" if r_values else "NO_PRICE_OUTCOMES",
        "safety": advisory_safety_stamps(),
    }


def _max_drawdown_r(r_values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for r in r_values:
        equity += r
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


# ---------------------------------------------------------------------------
# Track record ledger
# ---------------------------------------------------------------------------


def create_track_record_entry(
    *,
    recommendation_id: str,
    event_id: str,
    operator_action: str,
    action_class: str,
    ticker_basket: list[str],
    initial_score: float | None,
    initial_branch_probabilities: dict[str, float],
    initial_rumor_risk: float | None,
    initial_hedge_need: float | None,
    invalidation_condition: str,
    is_fixture: bool = False,
    notes: str = "",
    db_path: Path | str | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    init_ledger_schema(db_path)
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO nbi_track_record (
                recommendation_id, event_id, timestamp, operator_action,
                action_class, ticker_basket_json, initial_score,
                initial_branch_probabilities_json, initial_rumor_risk,
                initial_hedge_need, invalidation_condition, is_fixture, notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                recommendation_id, event_id, _now_iso(now_iso),
                operator_action, action_class, json.dumps(ticker_basket),
                initial_score, json.dumps(initial_branch_probabilities),
                initial_rumor_risk, initial_hedge_need,
                invalidation_condition, 1 if is_fixture else 0, notes,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {"created": True, "recommendation_id": recommendation_id,
            "is_fixture": is_fixture}


def close_track_record_entry(
    recommendation_id: str,
    *,
    close_reason: str,
    realized_return: float | None = None,
    benchmark_return: float | None = None,
    r_multiple: float | None = None,
    evidence_quality_score: float | None = None,
    calibration_eligible: bool = False,
    db_path: Path | str | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    init_ledger_schema(db_path)
    rvb = None
    if realized_return is not None and benchmark_return is not None:
        rvb = realized_return - benchmark_return
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """UPDATE nbi_track_record SET
                close_timestamp = ?, close_reason = ?, realized_return = ?,
                benchmark_return = ?, return_vs_benchmark = ?, r_multiple = ?,
                evidence_quality_score = ?, calibration_eligible = ?
            WHERE recommendation_id = ?""",
            (
                _now_iso(now_iso), close_reason, realized_return,
                benchmark_return, rvb, r_multiple, evidence_quality_score,
                1 if calibration_eligible else 0, recommendation_id,
            ),
        )
        conn.commit()
        found = cur.rowcount > 0
    finally:
        conn.close()
    return {"closed": found, "recommendation_id": recommendation_id,
            "return_vs_benchmark": rvb}


def load_track_record(
    db_path: Path | str | None = None, *, include_fixtures: bool = False,
) -> list[dict[str, Any]]:
    init_ledger_schema(db_path)
    conn = _connect(db_path)
    try:
        query = "SELECT * FROM nbi_track_record"
        if not include_fixtures:
            query += " WHERE is_fixture = 0"
        rows = [dict(r) for r in conn.execute(
            query + " ORDER BY timestamp, recommendation_id"
        )]
    finally:
        conn.close()
    for row in rows:
        for key in ("ticker_basket_json", "initial_branch_probabilities_json"):
            try:
                row[key.removesuffix("_json")] = json.loads(row.pop(key))
            except ValueError:
                row[key.removesuffix("_json")] = None
    return rows


def summarize_track_record(
    db_path: Path | str | None = None,
    *,
    min_closed: int = TRACK_RECORD_MIN_CLOSED,
) -> dict[str, Any]:
    """Honest ledger census.  Below ``min_closed`` closed non-fixture entries
    the summary refuses hit-rate / mean-R performance claims entirely."""
    entries = load_track_record(db_path)
    closed = [e for e in entries if e.get("close_timestamp")]
    open_entries = [e for e in entries if not e.get("close_timestamp")]
    summary: dict[str, Any] = {
        "report": "nbi_track_record_summary",
        "ledger_version": LEDGER_VERSION,
        "entries_total": len(entries),
        "entries_open": len(open_entries),
        "entries_closed": len(closed),
        "min_closed_for_performance": min_closed,
        "safety": advisory_safety_stamps(),
    }
    if len(closed) < min_closed:
        summary["status"] = TRACK_RECORD_INSUFFICIENT
        summary["performance"] = None
        summary["performance_refusal_reason"] = (
            f"closed entries {len(closed)} < {min_closed}: no hit rate, "
            "no mean R, no drawdown claim"
        )
        return summary
    r_values = [e["r_multiple"] for e in closed if e.get("r_multiple") is not None]
    wins = sum(1 for e in closed
               if (e.get("return_vs_benchmark") or 0) > 0)
    summary["status"] = "MEASURED"
    summary["performance"] = {
        "hit_rate": round(wins / len(closed), 4),
        "mean_r": round(sum(r_values) / len(r_values), 4) if r_values else None,
        "max_drawdown_r": round(_max_drawdown_r(r_values), 4) if r_values else None,
        "n_with_r_multiple": len(r_values),
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NBI track record ledger summary (advisory-only)."
    )
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)
    print(json.dumps(summarize_track_record(args.db), indent=2))
    return 0


__all__ = [
    "LEDGER_VERSION", "EQS_CALIBRATION_ELIGIBLE_MIN",
    "EDGE_MIN_ELIGIBLE_CASES", "EDGE_ECE_MAX", "EDGE_DRAWDOWN_LIMIT_R",
    "TRACK_RECORD_MIN_CLOSED", "TRACK_RECORD_INSUFFICIENT",
    "init_ledger_schema", "compute_case_quality", "eligible_cases",
    "compute_edge_claim_permission", "create_track_record_entry",
    "close_track_record_entry", "load_track_record",
    "summarize_track_record", "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
