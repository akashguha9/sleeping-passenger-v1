"""Business / demo value report — what the defensive layers actually caught.

A read-only, advisory-only summary of the *defensive* value the MVP provides:
stale signals detected, duplicate AI theses detected, closed losses repaired
into Moltbook, fake demo pollution prevented, operator overload flagged, the
unreconciled-risk backlog, and (Integrated Sprint Part 6) a *defensive-alpha
proxy* + ``business_value_summary.json`` artifact the release gate consumes.

Honesty contract (Kanté "no unlogged loss")
-------------------------------------------
* This report NEVER claims a P/L improvement, a return, or a profit. It counts
  *risk-prevention* events; any computed defensive-alpha proxy is labelled
  *paper/advisory proxy*, *not realized PnL*, *not investment advice*, *not
  proof of future returns*.
* It always carries the advisory-only disclaimer and "human execution
  required".
* Missing data is reported honestly (``db_available=False`` + a note) rather
  than invented.

Read-only: no DB writes, no refresh, no broker calls.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "runtime" / "mvp_local.db"
DEFAULT_SUMMARY_PATH = REPO_ROOT / "runtime" / "release" / "business_value_summary.json"

PROXY_LABELS: tuple[str, ...] = (
    "paper/advisory proxy",
    "not realized PnL",
    "not investment advice",
    "not proof of future returns",
)

ADVISORY_DISCLAIMER = (
    "Advisory-only. This report counts risk-prevention and record-keeping "
    "events; it makes NO claim of profit, return, or P/L improvement. Every "
    "trade decision requires a human. No broker order is ever placed."
)

# Default per-day operator capacity used to flag overload.  Conservative.
_OPERATOR_CAPACITY = 8.0


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


def _scalar(conn: sqlite3.Connection, sql: str) -> int:
    try:
        row = conn.execute(sql).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except sqlite3.Error:
        return 0


def build_report(db_path: Path | None = None) -> dict[str, Any]:
    """Build the business/demo value report (read-only, advisory-only)."""
    db = Path(db_path) if db_path is not None else DEFAULT_DB
    base: dict[str, Any] = {
        "report": "business_value_report",
        "db_path": str(db),
        "db_available": False,
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        "claims_pl_improvement": False,
        "human_execution_required": True,
        "stale_signals_detected": 0,
        "duplicate_ai_thesis_detected": 0,
        "closed_losses_repaired_into_moltbook": 0,
        "fake_demo_pollution_active": 0,
        "fake_demo_pollution_prevented": True,
        "operator_overload_flagged": False,
        "operator_load_score": 0.0,
        "unreconciled_risk_count": 0,
        "notes": [],
        **_contract.advisory_safety_stamps(),
    }

    conn = _readonly_connect(db)
    if conn is None:
        base["notes"].append(
            "DB not available — all counts default to zero. This is reported "
            "honestly, not invented."
        )
        return base
    base["db_available"] = True

    try:
        # Stale signals: signal cells whose freshness degraded.
        base["stale_signals_detected"] = _scalar(
            conn,
            "SELECT COUNT(*) FROM signal_cell_index"
            " WHERE LOWER(freshness_state) IN ('stale','expired')",
        )
        # Duplicate AI thesis: a fingerprint seen more than once is an echo.
        base["duplicate_ai_thesis_detected"] = _scalar(
            conn,
            "SELECT COUNT(*) FROM duplicate_fingerprints WHERE seen_count > 1",
        )
        # Closed losses repaired into Moltbook (loss-review entries).
        base["closed_losses_repaired_into_moltbook"] = _scalar(
            conn,
            "SELECT COUNT(*) FROM moltbook_entries WHERE mistake_type IN"
            " ('trade_loss','manual_exit_loss','stop_loss_breach')",
        )
        # Fake demo pollution still active (unlinked FABRIC/demo rows).
        active_pollution = _scalar(
            conn,
            "SELECT COUNT(*) FROM moltbook_entries"
            " WHERE (UPPER(event_id) LIKE 'FABRIC%'"
            "        OR original_signal_thesis LIKE 'Persistence above 0.8%'"
            "        OR original_signal_thesis = 'Thesis A')"
            " AND COALESCE(NULLIF(TRIM(manual_trade_log_id),''),'') = ''",
        )
        base["fake_demo_pollution_active"] = active_pollution
        base["fake_demo_pollution_prevented"] = active_pollution == 0

        # Unreconciled risk: operator-logged trades with no reconciliation row.
        mt_cols = {r[1] for r in conn.execute("PRAGMA table_info(manual_trades)")}
        provenance = (
            " AND created_via = 'manual_trade_log'"
            if "created_via" in mt_cols else ""
        )
        status_filter = (
            " AND COALESCE(NULLIF(TRIM(reconciliation_status),''),'') = ''"
            if "reconciliation_status" in mt_cols else ""
        )
        unreconciled = _scalar(
            conn,
            "SELECT COUNT(*) FROM manual_trades mt"
            " WHERE NOT EXISTS (SELECT 1 FROM reconciliation_results rr"
            "                   WHERE rr.trade_id = mt.trade_id)"
            + provenance + status_filter,
        )
        base["unreconciled_risk_count"] = unreconciled
    finally:
        conn.close()

    # Operator overload via the queueing attention gate (advisory).
    try:
        try:
            from scripts.complex_systems_diagnostics import (
                compute_queueing_attention_gate,
            )
        except ModuleNotFoundError:
            from complex_systems_diagnostics import (  # type: ignore[no-redef]
                compute_queueing_attention_gate,
            )
        gate = compute_queueing_attention_gate({
            "unreconciled_manual_trades": base["unreconciled_risk_count"],
            "moltbook_pending_review": 0,
            "operator_capacity": _OPERATOR_CAPACITY,
        })
        base["operator_load_score"] = gate["operator_load_score"]
        base["operator_overload_flagged"] = bool(gate["no_new_risk_flag"])
    except Exception:  # pragma: no cover - defensive
        base["notes"].append("operator load gate unavailable; defaulted to 0.")

    return base


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="business_value_report.py",
        description=(
            "Read-only advisory summary of defensive value (risk prevented, "
            "losses repaired). Never claims P/L. No broker calls."
        ),
    )
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--write-summary", action="store_true",
                   help="also write runtime/release/business_value_summary.json "
                        "(includes defensive-alpha proxy + business_value_score)")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rep = build_report(args.db_path)
    summary = None
    if args.write_summary:
        # Empty candidate outcomes is OK — the summary will simply report
        # the proxy as 0.0 with the proxy labels, never as realized PnL.
        summary = build_business_value_summary(
            db_path=args.db_path,
            candidate_outcomes=[],
            write_summary=True,
        )
    if args.json:
        payload = {"report": rep}
        if summary is not None:
            payload["summary"] = summary
        print(json.dumps(payload, indent=2, default=str))
    else:
        print("Business / Demo Value Report (advisory-only)")
        print("=" * 44)
        print(f"  DB available                : {rep['db_available']}")
        print(f"  stale signals detected      : {rep['stale_signals_detected']}")
        print(f"  duplicate AI thesis detected: {rep['duplicate_ai_thesis_detected']}")
        print(f"  losses repaired to Moltbook : {rep['closed_losses_repaired_into_moltbook']}")
        print(f"  fake pollution active       : {rep['fake_demo_pollution_active']}")
        print(f"  operator overload flagged   : {rep['operator_overload_flagged']}")
        print(f"  unreconciled risk count     : {rep['unreconciled_risk_count']}")
        for note in rep["notes"]:
            print(f"  note: {note}")
        if summary is not None:
            print(f"  summary written           : {summary.get('summary_path')}")
            print(f"  defensive_alpha_proxy     : {summary['defensive_alpha_proxy']}")
            print(f"  business_value_score      : {summary['business_value_score']}")
        print(f"\n  {rep['advisory_disclaimer']}")
    return 0


# ---------------------------------------------------------------------------
# Defensive-alpha proxy + business-value summary (Integrated Sprint — Part 6).
# These functions are pure and operate on records the caller assembles; they
# never claim realized PnL.  When passed an empty list they return zeros and
# the proxy-label list — never a hidden "we made money" inference.
# ---------------------------------------------------------------------------


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp01(value: float) -> float:
    if value is None or math.isnan(value):
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def defensive_alpha_proxy(
    candidates: Iterable[dict[str, Any]],
    *,
    loss_threshold: float = 0.05,
) -> dict[str, Any]:
    """Compute the defensive-alpha proxy from candidate-outcome records.

    Each candidate row supports the keys:
      * ``blocked``  (bool/0|1) — MVP blocked this candidate
      * ``block_reason`` (str) — for diagnostic counts
      * ``r_candidate`` (float) — subsequent return if it had been taken
      * ``r_benchmark`` (float) — benchmark return over same horizon

    Returns the proxy values with explicit *paper/advisory proxy* labels.
    """
    rows = list(candidates)
    n = len(rows)
    if n == 0:
        return {
            "candidate_count": 0,
            "blocked_count": 0,
            "blocked_with_outcome": 0,
            "avoided_loss_sum": 0.0,
            "defensive_alpha_proxy": 0.0,
            "defensive_alpha_vs_benchmark": 0.0,
            "labels": list(PROXY_LABELS),
        }

    avoided_loss_sum = 0.0
    blocked_count = 0
    blocked_with_outcome = 0
    benchmark_sum = 0.0
    benchmark_blocked_outcomes = 0

    for r in rows:
        blocked = bool(r.get("blocked"))
        r_cand = r.get("r_candidate")
        r_bench = r.get("r_benchmark")
        if blocked:
            blocked_count += 1
        if blocked and isinstance(r_cand, (int, float)):
            blocked_with_outcome += 1
            bad = float(r_cand) < -float(loss_threshold)
            if bad:
                avoided_loss_sum += abs(float(r_cand))
            if isinstance(r_bench, (int, float)):
                benchmark_sum += max(0.0, float(r_bench) - float(r_cand))
                benchmark_blocked_outcomes += 1

    proxy = avoided_loss_sum / max(n, 1)
    bench_proxy = (
        benchmark_sum / benchmark_blocked_outcomes
        if benchmark_blocked_outcomes else 0.0
    )
    return {
        "candidate_count": n,
        "blocked_count": blocked_count,
        "blocked_with_outcome": blocked_with_outcome,
        "avoided_loss_sum": round(avoided_loss_sum, 6),
        "defensive_alpha_proxy": round(proxy, 6),
        "defensive_alpha_vs_benchmark": round(bench_proxy, 6),
        "labels": list(PROXY_LABELS),
    }


def business_value_score(
    *,
    days_with_records: int,
    blocked_candidates_with_outcome: int,
    source_verified_ratio: float,
    demo_sessions_logged: int,
    operator_time_saved_score: float,
) -> float:
    """``business_value_score`` per the sprint spec; clamped to [0,1] then * 10."""
    score = (
        0.30 * min(1.0, days_with_records / 30.0)
        + 0.25 * min(1.0, blocked_candidates_with_outcome / 25.0)
        + 0.20 * _clamp01(source_verified_ratio)
        + 0.15 * min(1.0, demo_sessions_logged / 5.0)
        + 0.10 * _clamp01(operator_time_saved_score)
    )
    return round(_clamp01(score), 6)


# ---------------------------------------------------------------------------
# Sprint-2 additions: demo sessions, decision time saved, confidence lift.
# These compose with business_value_score above — they don't replace it, so
# the existing test surface (test_business_value_summary.py) keeps passing.
# ---------------------------------------------------------------------------


def decision_time_saved_score(
    baseline_decision_seconds: float, observed_decision_seconds: float,
) -> float:
    """``(baseline - observed) / baseline`` clamped to [0,1]; 0 if no baseline.

    Honest about being a *proxy* — see PROXY_LABELS / ADVISORY_DISCLAIMER."""
    baseline = max(0.0, float(baseline_decision_seconds))
    observed = max(0.0, float(observed_decision_seconds))
    if baseline <= 0:
        return 0.0
    saved = baseline - observed
    if saved <= 0:
        return 0.0
    return round(_clamp01(saved / baseline), 6)


def confidence_lift_score(
    user_confidence_before: float, user_confidence_after: float,
) -> float:
    """``(after - before)``, clamped to [0,1].  Returns 0 if confidence
    dropped — we don't *penalize* business value for honest self-reported
    declines, but we also don't reward them."""
    before = _clamp01(float(user_confidence_before or 0.0))
    after = _clamp01(float(user_confidence_after or 0.0))
    return round(_clamp01(after - before), 6)


def summarize_demo_sessions(
    sessions: Iterable[dict[str, Any]],
    *,
    baseline_decision_seconds: float = 600.0,
) -> dict[str, Any]:
    """Per-cohort averages for time-saved + confidence-lift.

    Each session may carry:
      * average_time_to_decision_seconds
      * user_confidence_before / user_confidence_after
      * candidates_reviewed / blocked_candidates
    Returns 0-defaults for an empty cohort.
    """
    rows = [s for s in sessions if isinstance(s, dict)]
    if not rows:
        return {
            "demo_sessions_logged": 0,
            "average_decision_time_saved_score": 0.0,
            "average_confidence_lift_score": 0.0,
            "total_candidates_reviewed": 0,
            "total_blocked_candidates": 0,
            "baseline_decision_seconds": baseline_decision_seconds,
        }
    time_saved_scores = [
        decision_time_saved_score(
            baseline_decision_seconds,
            float(s.get("average_time_to_decision_seconds") or 0.0),
        )
        for s in rows
        if s.get("average_time_to_decision_seconds") is not None
    ]
    lifts = [
        confidence_lift_score(
            float(s.get("user_confidence_before") or 0.0),
            float(s.get("user_confidence_after") or 0.0),
        )
        for s in rows
        if (s.get("user_confidence_before") is not None
            or s.get("user_confidence_after") is not None)
    ]
    return {
        "demo_sessions_logged": len(rows),
        "average_decision_time_saved_score": round(
            sum(time_saved_scores) / len(time_saved_scores), 6
        ) if time_saved_scores else 0.0,
        "average_confidence_lift_score": round(
            sum(lifts) / len(lifts), 6
        ) if lifts else 0.0,
        "total_candidates_reviewed": sum(
            int(s.get("candidates_reviewed") or 0) for s in rows
        ),
        "total_blocked_candidates": sum(
            int(s.get("blocked_candidates") or 0) for s in rows
        ),
        "baseline_decision_seconds": float(baseline_decision_seconds),
    }


def build_business_value_summary(
    *,
    db_path: Path | None = None,
    candidate_outcomes: Iterable[dict[str, Any]] | None = None,
    days_with_records: int | None = None,
    source_verified_ratio: float = 0.0,
    demo_sessions_logged: int = 0,
    operator_time_saved_score: float = 0.0,
    demo_sessions: Iterable[dict[str, Any]] | None = None,
    baseline_decision_seconds: float = 600.0,
    write_summary: bool = True,
    summary_path: Path | None = None,
) -> dict[str, Any]:
    """Top-level: combine defensive-value counts with the defensive-alpha proxy.

    Persists ``runtime/release/business_value_summary.json`` so the release
    gate can read it; the artifact is always tagged with the proxy labels.
    """
    base_report = build_report(db_path)
    proxy = defensive_alpha_proxy(list(candidate_outcomes or []))

    blocked_with_outcome = int(proxy.get("blocked_with_outcome", 0))
    candidates_reviewed = int(proxy.get("candidate_count", 0))
    if days_with_records is None:
        # Conservative inference: one calendar day per 8 blocked-with-outcome
        # records (no claim that this matches the operator's actual cadence).
        days_with_records = max(1, blocked_with_outcome // 8) if blocked_with_outcome else 0

    demo_cohort = summarize_demo_sessions(
        list(demo_sessions or []),
        baseline_decision_seconds=baseline_decision_seconds,
    )
    # Folding the cohort into the existing per-spec score: if the caller
    # provided demo_sessions, prefer the *observed* counts over the legacy
    # explicit scalars; otherwise honor the caller's pre-aggregated args.
    if demo_sessions:
        demo_sessions_logged = demo_cohort["demo_sessions_logged"]
        operator_time_saved_score = max(
            operator_time_saved_score,
            demo_cohort["average_decision_time_saved_score"],
        )

    bv_score = business_value_score(
        days_with_records=days_with_records,
        blocked_candidates_with_outcome=blocked_with_outcome,
        source_verified_ratio=source_verified_ratio,
        demo_sessions_logged=demo_sessions_logged,
        operator_time_saved_score=operator_time_saved_score,
    )

    block_reasons: dict[str, int] = {}
    for r in candidate_outcomes or []:
        reason = str(r.get("block_reason") or "").upper()
        if not reason:
            continue
        block_reasons[reason] = block_reasons.get(reason, 0) + 1

    summary = {
        "report": "business_value_summary",
        "ok": True,
        "generated_at_utc": _utc_iso(),
        "days_covered": int(days_with_records),
        "candidates_reviewed": candidates_reviewed,
        "blocked_count": int(proxy.get("blocked_count", 0)),
        "stale_blocks": int(block_reasons.get("STALE", 0)
                            + block_reasons.get("PRICE_SOURCE_STALE", 0)
                            + block_reasons.get("FILINGS_SOURCE_STALE", 0)
                            + block_reasons.get("NEWS_SOURCE_STALE", 0)),
        "disagreement_blocks": int(block_reasons.get("MODEL_DISAGREEMENT_HIGH", 0)),
        "diablo_blocks": int(block_reasons.get("DIABLO_MODEL_VETO", 0)),
        "defensive_alpha_proxy": proxy["defensive_alpha_proxy"],
        "defensive_alpha_vs_benchmark": proxy["defensive_alpha_vs_benchmark"],
        "blocked_candidates_with_outcome": blocked_with_outcome,
        "business_value_score": bv_score,
        "demo_sessions_logged": int(demo_cohort["demo_sessions_logged"]),
        "average_decision_time_saved_score": demo_cohort[
            "average_decision_time_saved_score"
        ],
        "average_confidence_lift_score": demo_cohort[
            "average_confidence_lift_score"
        ],
        "baseline_decision_seconds": demo_cohort["baseline_decision_seconds"],
        "demo_total_candidates_reviewed": demo_cohort[
            "total_candidates_reviewed"
        ],
        "demo_total_blocked_candidates": demo_cohort[
            "total_blocked_candidates"
        ],
        "labels": list(PROXY_LABELS) + ["human review required",
                                        "no broker execution"],
        "block_reason_distribution": block_reasons,
        "base_defensive_value": {
            k: base_report.get(k)
            for k in (
                "stale_signals_detected",
                "duplicate_ai_thesis_detected",
                "closed_losses_repaired_into_moltbook",
                "fake_demo_pollution_active",
                "fake_demo_pollution_prevented",
                "operator_overload_flagged",
                "unreconciled_risk_count",
            )
        },
        "advisory_only": True,
        "human_review_required": True,
        "claims_pl_improvement": False,
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        **_contract.advisory_safety_stamps(),
    }

    if write_summary:
        target = summary_path or DEFAULT_SUMMARY_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(summary, indent=2, default=str),
                       encoding="utf-8")
        tmp.replace(target)
        summary["summary_path"] = str(target)
    return summary


def read_summary(path: Path | None = None) -> dict[str, Any] | None:
    target = path or DEFAULT_SUMMARY_PATH
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


__all__ = [
    "ADVISORY_DISCLAIMER",
    "PROXY_LABELS",
    "DEFAULT_SUMMARY_PATH",
    "build_report",
    "defensive_alpha_proxy",
    "business_value_score",
    "decision_time_saved_score",
    "confidence_lift_score",
    "summarize_demo_sessions",
    "build_business_value_summary",
    "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
