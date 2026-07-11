"""Titration calibration & stability report — temporally honest, refusal-first.

Answers, from persisted evidence→response observations, the questions the
titration layer must eventually be judged on:

* Are PRIMED (and other) states followed by transitions more often than the
  base rate?
* Do the titration features (evidence dose, active evidence, LRR, PAG) rank
  future transitions better than trivial baselines — out of time?
* What is measured vs proxy, and how much sample exists at each level?

Refusal discipline (the point of this module):

* Below ``MIN_EVAL_OBSERVATIONS`` matured observations per horizon, or with
  a single outcome class, the verdict is
  ``INSUFFICIENT_EVIDENCE_FOR_PERFORMANCE_CLAIM`` — no AUCs, no hit rates,
  no lift numbers are printed from tiny samples.
* The transition-hazard layer is fit ONLY when matured outcomes exceed
  ``MIN_OUTCOMES_FOR_HAZARD``; otherwise it reports
  ``BLOCKED_INSUFFICIENT_OUTCOMES`` with the exact sample shortfall.
* Temporal evaluation is a 70/30 time-ordered split with an overlap purge:
  training observations whose forward window could cross the split
  boundary are dropped (approximate purge on calendar days ≈ trading
  horizon × 1.6, documented).
* Nothing here is a probability.  Feature rankings use AUC (rank statistic)
  and top-tercile transition rates with Wilson intervals — explicitly
  labelled score comparisons.

Reuses the platform's calibration conventions:
``score_calibration.classify_calibration_status`` sample gates and the
reactor-report confidence bands (n<10 very_low, <30 low, <100 medium).

Advisory-only.  Read-only against the local SQLite DB.

CLI:
    python scripts/titration_calibration_report.py --json
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import persistence
    from scripts.score_calibration import classify_calibration_status
    from scripts.titration_outcome_contract import MATURED
    from scripts.titration_susceptibility import estimate_catalytic_convexity
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import persistence  # type: ignore[no-redef]
    from score_calibration import classify_calibration_status  # type: ignore[no-redef]
    from titration_outcome_contract import MATURED  # type: ignore[no-redef]
    from titration_susceptibility import (  # type: ignore[no-redef]
        estimate_catalytic_convexity,
    )

REPORT_VERSION = "titration_calibration_report_v1"

MIN_EVAL_OBSERVATIONS = 30
MIN_TEST_OBSERVATIONS = 15
MIN_STATE_SAMPLE = 10
MIN_OUTCOMES_FOR_HAZARD = 40

INSUFFICIENT = "INSUFFICIENT_EVIDENCE_FOR_PERFORMANCE_CLAIM"
HAZARD_BLOCKED = "BLOCKED_INSUFFICIENT_OUTCOMES"

SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
    "human_review_required": True,
}

NON_CLAIMS: tuple[str, ...] = (
    "no_alpha_proven",
    "no_probability_calibration_claimed_without_sample",
    "rank_statistics_are_not_probabilities",
    "measured_susceptibility_is_response_magnitude_not_direction",
    "in_sample_numbers_are_never_reported_as_validation",
)


def _confidence_band(n: int) -> str:
    """Reactor-report convention: n<10 very_low, <30 low, <100 medium."""
    if n < 10:
        return "very_low"
    if n < 30:
        return "low"
    if n < 100:
        return "medium"
    return "higher_but_contextual"


def _wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = wins / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round(max(0.0, center - half), 6), round(min(1.0, center + half), 6))


def _auc(scores: list[float], labels: list[int]) -> float | None:
    """Mann-Whitney AUC of a score ranking binary labels.  None when a
    single class is present."""
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return None
    wins = 0.0
    for p in pos:
        for q in neg:
            if p > q:
                wins += 1.0
            elif p == q:
                wins += 0.5
    return round(wins / (len(pos) * len(neg)), 6)


def _parse_ts(ts: str) -> datetime | None:
    try:
        text = ts.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def _feature(obs: dict[str, Any], key: str) -> float | None:
    val = obs.get(key)
    if isinstance(val, bool) or val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


COMPARATORS: tuple[tuple[str, str], ...] = (
    # (name, observation feature column) — all observable at event time.
    ("evidence_dose", "dose"),
    ("active_evidence", "active_after"),
    ("lrr", "lrr"),
    ("pre_alpha_gap", "pag"),
)


def _evaluate_horizon(matured: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    """Temporal out-of-sample comparator evaluation for one horizon."""
    rows = [
        o for o in matured
        if int(o.get("horizon", -1)) == horizon and o.get("y_absolute") in (0, 1)
    ]
    rows.sort(key=lambda o: str(o.get("event_ts", "")))
    n = len(rows)
    base = {
        "horizon": horizon,
        "matured_n": n,
        "transition_base_rate": None,
        "verdict": INSUFFICIENT,
        "comparators": {},
        "sample_needed": max(0, MIN_EVAL_OBSERVATIONS - n),
    }
    if n == 0:
        return base
    positives = sum(int(o["y_absolute"]) for o in rows)
    base["transition_base_rate"] = round(positives / n, 6)
    base["transition_base_rate_wilson"] = _wilson(positives, n)
    if n < MIN_EVAL_OBSERVATIONS or positives == 0 or positives == n:
        base["refusal_reason"] = (
            "below_minimum_sample" if n < MIN_EVAL_OBSERVATIONS else "single_outcome_class"
        )
        return base

    # Time-ordered 70/30 split with an overlap purge: drop the tail of the
    # training window whose forward horizon could cross the boundary.
    split_idx = int(0.7 * n)
    boundary_ts = _parse_ts(str(rows[split_idx].get("event_ts", "")))
    purge_days = max(2, int(horizon * 1.6))  # trading->calendar approx.
    train: list[dict[str, Any]] = []
    purged = 0
    for o in rows[:split_idx]:
        ts = _parse_ts(str(o.get("event_ts", "")))
        if boundary_ts is not None and ts is not None and (
            boundary_ts - ts
        ) < timedelta(days=purge_days):
            purged += 1
            continue
        train.append(o)
    test = rows[split_idx:]
    test_pos = sum(int(o["y_absolute"]) for o in test)
    if len(test) < MIN_TEST_OBSERVATIONS or test_pos == 0 or test_pos == len(test):
        base["refusal_reason"] = "test_window_insufficient_or_single_class"
        base["purged_overlap_count"] = purged
        return base

    test_labels = [int(o["y_absolute"]) for o in test]
    test_base_rate = test_pos / len(test)
    comparators: dict[str, Any] = {
        "base_rate": {
            "auc": 0.5,
            "note": "constant predictor reference",
            "test_transition_rate": round(test_base_rate, 6),
        }
    }
    for name, column in COMPARATORS:
        scores = [(_feature(o, column), y) for o, y in zip(test, test_labels)]
        usable = [(s, y) for s, y in scores if s is not None]
        if len(usable) < MIN_TEST_OBSERVATIONS:
            comparators[name] = {"status": "feature_unavailable_in_test_window"}
            continue
        xs = [s for s, _ in usable]
        ys = [y for _, y in usable]
        auc = _auc(xs, ys)
        # Top-tercile transition rate with Wilson interval.
        order = sorted(range(len(xs)), key=lambda i: xs[i], reverse=True)
        top = order[: max(1, len(order) // 3)]
        top_pos = sum(ys[i] for i in top)
        comparators[name] = {
            "auc": auc,
            "top_tercile_transition_rate": round(top_pos / len(top), 6),
            "top_tercile_wilson": _wilson(top_pos, len(top)),
            "test_n": len(usable),
            "lift_vs_base_rate": (
                round((top_pos / len(top)) - test_base_rate, 6)
                if len(top) else None
            ),
            "semantics": "rank_statistic_not_probability",
        }
    base.update({
        "verdict": "TEMPORAL_OOS_COMPARISON_AVAILABLE",
        "train_n": len(train),
        "test_n": len(test),
        "purged_overlap_count": purged,
        "test_transition_rate": round(test_base_rate, 6),
        "comparators": comparators,
        "split": "time_ordered_70_30_with_overlap_purge",
        "confidence_band": _confidence_band(len(test)),
    })
    return base


def _state_performance(matured: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    rows = [
        o for o in matured
        if int(o.get("horizon", -1)) == horizon and o.get("y_absolute") in (0, 1)
    ]
    out: dict[str, Any] = {}
    states = sorted({str(o.get("titration_state") or "") for o in rows})
    for state in states:
        sub = [o for o in rows if o.get("titration_state") == state]
        n = len(sub)
        pos = sum(int(o["y_absolute"]) for o in sub)
        if n < MIN_STATE_SAMPLE:
            out[state] = {"n": n, "status": "insufficient_sample"}
        else:
            out[state] = {
                "n": n,
                "transition_rate": round(pos / n, 6),
                "wilson": _wilson(pos, n),
                "confidence_band": _confidence_band(n),
            }
    return out


def build_stability_section(
    observations: list[dict[str, Any]],
    estimates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Drift / stability diagnostics with explicit warnings."""
    warnings: list[str] = []
    # State frequency (one count per event, not per horizon-row).
    state_counts: dict[str, int] = {}
    seen: set[str] = set()
    for o in observations:
        eid = str(o.get("event_id") or o.get("obs_id") or "")
        if eid in seen:
            continue
        seen.add(eid)
        state = str(o.get("titration_state") or "UNKNOWN")
        state_counts[state] = state_counts.get(state, 0) + 1
    total_events = sum(state_counts.values())
    if total_events:
        for state, count in state_counts.items():
            share = count / total_events
            if share > 0.8:
                warnings.append(f"state_dominance:{state}:{round(share, 3)}")
    measured_scopes = sum(1 for e in estimates if e.get("chi_norm") is not None)
    if not estimates:
        warnings.append("all_susceptibility_outputs_use_heuristic_proxy")
    maturation_counts: dict[str, int] = {}
    for o in observations:
        m = str(o.get("maturation") or "UNKNOWN")
        maturation_counts[m] = maturation_counts.get(m, 0) + 1
    matured_n = maturation_counts.get(MATURED, 0)
    if observations and matured_n == 0:
        warnings.append("no_matured_outcomes_yet")
    if not observations:
        warnings.append("no_response_observations_built")
    return {
        "historical_state_counts": state_counts,
        "maturation_counts": maturation_counts,
        "observation_count": len(observations),
        "matured_count": matured_n,
        "susceptibility_estimate_count": len(estimates),
        "measured_scope_count": measured_scopes,
        "proxy_fallback_expected": not estimates,
        "warnings": warnings,
    }


def build_report(db_path: Path | None = None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if db_path is not None:
        kwargs["db_path"] = db_path
    try:
        observations = persistence.get_titration_observations(**kwargs)
    except Exception:
        observations = []
    try:
        estimates = persistence.get_titration_susceptibility_estimates(**kwargs)
    except Exception:
        estimates = []

    matured = [o for o in observations if o.get("maturation") == MATURED]
    horizons = sorted({int(o["horizon"]) for o in observations}) if observations else []

    # Sample inventory.
    by_market: dict[str, int] = {}
    by_state: dict[str, int] = {}
    for o in matured:
        by_market[str(o.get("market") or "UNKNOWN")] = by_market.get(
            str(o.get("market") or "UNKNOWN"), 0
        ) + 1
        by_state[str(o.get("titration_state") or "UNKNOWN")] = by_state.get(
            str(o.get("titration_state") or "UNKNOWN"), 0
        ) + 1
    join_rate = None
    if observations:
        joined = sum(1 for o in observations if o.get("entry_bar_date"))
        join_rate = round(joined / len(observations), 6)

    horizon_reports = {str(h): _evaluate_horizon(matured, h) for h in horizons}
    state_reports = {str(h): _state_performance(matured, h) for h in horizons}

    # Catalytic convexity (experimental, gated inside the estimator).
    convexity = {}
    for h in horizons:
        rows_h = [
            {
                "dose": o.get("dose"),
                "z": abs(float(o["z"])),
                "event_ts": o.get("event_ts"),
            }
            for o in matured
            if int(o["horizon"]) == h and isinstance(o.get("z"), (int, float))
        ]
        convexity[str(h)] = estimate_catalytic_convexity(rows_h, horizon=h)

    # Transition hazard: fit only above the outcome gate; otherwise report
    # the exact shortfall.  (No fit is implemented below the gate — by
    # design, not omission.)
    matured_primary = [o for o in matured if o.get("y_absolute") in (0, 1)]
    hazard: dict[str, Any]
    if len(matured_primary) < MIN_OUTCOMES_FOR_HAZARD:
        hazard = {
            "status": HAZARD_BLOCKED,
            "matured_outcomes": len(matured_primary),
            "minimum_required": MIN_OUTCOMES_FOR_HAZARD,
            "additional_outcomes_needed": MIN_OUTCOMES_FOR_HAZARD - len(matured_primary),
            "note": (
                "hazard fitting deliberately not performed below the sample "
                "gate; heuristic readiness scores remain the operational layer"
            ),
        }
    else:
        hazard = {
            "status": "SAMPLE_GATE_PASSED_FIT_PENDING",
            "matured_outcomes": len(matured_primary),
            "note": (
                "outcome sample exceeds the gate; hazard fitting is the "
                "designated next sprint (walk-forward, purged, embargoed)"
            ),
        }

    calibration_status = classify_calibration_status(len(matured_primary))

    return {
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "data_inventory": {
            "observation_rows": len(observations),
            "matured_rows": len(matured),
            "ohlcv_join_rate": join_rate,
            "matured_by_market": by_market,
            "matured_by_state": by_state,
            "horizons": horizons,
        },
        "calibration_status": calibration_status,
        "overall_confidence_band": _confidence_band(len(matured_primary)),
        "horizon_evaluations": horizon_reports,
        "state_transition_rates": state_reports,
        "catalytic_convexity": convexity,
        "transition_hazard": hazard,
        "stability": build_stability_section(observations, estimates),
        "non_claims": list(NON_CLAIMS),
        "limitations": [
            "labels use the ABSOLUTE volatility-scaled family (direction unavailable)",
            "overlap purge is approximate (calendar-day proxy for trading days)",
            "AUC / tercile lifts are rank comparisons, not calibrated probabilities",
            "susceptibility estimates measure response magnitude, not direction",
        ],
        **SAFETY_STAMPS,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Titration calibration & stability report (advisory-only)."
    )
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = build_report(Path(args.db_path) if args.db_path else None)
    print(json.dumps(report, indent=2, default=str))
    return 0


__all__ = [
    "REPORT_VERSION",
    "MIN_EVAL_OBSERVATIONS",
    "MIN_OUTCOMES_FOR_HAZARD",
    "INSUFFICIENT",
    "HAZARD_BLOCKED",
    "build_report",
    "build_stability_section",
]


if __name__ == "__main__":
    raise SystemExit(main())
