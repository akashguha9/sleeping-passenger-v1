"""Post-outcome review loop for advisory signals (Pass 4).

For every resolved advisory signal, answer the questions that actually
improve a model: did the thesis play out, was the confidence calibrated,
was the evidence stale at decision time, should the model have abstained,
and what feature carried too much of the score.

Math (test-pinned on synthetic predictions with known answers):

    Error_i          = y_i − p_i              (binary outcome vs probability)
    AbsoluteError_i  = |y_i − p_i|
    PredictionError_i = R_actual_i − R_expected_i
    MAE  = (1/N) Σ |PredictionError_i|
    Bias = (1/N) Σ PredictionError_i

Inputs are review samples (dicts):

    {"signal_id", "symbol", "p": predicted_prob, "y": 0/1 outcome,
     "expected_return", "actual_return", "benchmark_return",
     "evidence_age_days_at_decision", "dominant_feature",
     "stability_recommendation"}   # from sensitivity_analysis, optional

Advisory-only: this reviews the past; nothing here acts on the future.
See docs/POST_OUTCOME_REVIEW.md for the operating cadence.
"""
from __future__ import annotations

import datetime as _dt
import statistics

_STALE_EVIDENCE_DAYS = 14.0
_CALIBRATION_GAP_FLAG = 0.3


class ReviewError(ValueError):
    """Raised on malformed review input."""


def review_sample(sample: dict) -> dict:
    """Review one resolved signal; returns per-signal findings + lessons."""
    p = sample.get("p")
    y = sample.get("y")
    if p is not None and not (0.0 <= float(p) <= 1.0):
        raise ReviewError(f"p={p} outside [0,1]")
    if y is not None and y not in (0, 1):
        raise ReviewError(f"y={y!r} must be 0/1")

    out: dict = {
        "signal_id": sample.get("signal_id", "?"),
        "symbol": str(sample.get("symbol", "")).upper(),
        "lessons": [],
        "advisory_only": True,
    }
    if p is not None and y is not None:
        out["error"] = float(y) - float(p)
        out["absolute_error"] = abs(out["error"])
        if out["absolute_error"] >= _CALIBRATION_GAP_FLAG:
            out["lessons"].append(
                f"confidence was off by {out['absolute_error']:.2f} — "
                + ("overconfident" if out["error"] < 0 else "underconfident")
            )
    exp_r, act_r = sample.get("expected_return"), sample.get("actual_return")
    if exp_r is not None and act_r is not None:
        out["prediction_error"] = float(act_r) - float(exp_r)
    if act_r is not None and sample.get("benchmark_return") is not None:
        out["excess_vs_benchmark"] = float(act_r) - float(sample["benchmark_return"])
        if out["excess_vs_benchmark"] < 0 and (act_r or 0) > 0:
            out["lessons"].append(
                "positive return but UNDER the benchmark — the signal added "
                "nothing the index didn't"
            )
    age = sample.get("evidence_age_days_at_decision")
    if isinstance(age, (int, float)) and age > _STALE_EVIDENCE_DAYS:
        out["evidence_was_stale"] = True
        out["lessons"].append(
            f"decision rested on {age:.0f}-day-old evidence (> "
            f"{_STALE_EVIDENCE_DAYS:.0f}d) — stale inputs, fresh conviction"
        )
    else:
        out["evidence_was_stale"] = False
    if sample.get("stability_recommendation") == "ABSTAIN" and y == 0:
        out["should_have_abstained"] = True
        out["lessons"].append(
            "sensitivity analysis recommended ABSTAIN and the signal failed "
            "— the abstain signal was right"
        )
    if sample.get("dominant_feature") and y == 0:
        out["lessons"].append(
            f"score leaned on {sample['dominant_feature']!r}; review whether "
            "that feature was over-weighted"
        )
    out["thesis_played_out"] = bool(y) if y is not None else None
    return out


def aggregate_review(samples: list[dict]) -> dict:
    """Aggregate MAE/Bias + calibration drift over many reviews."""
    reviews = [review_sample(s) for s in samples]
    pred_errors = [r["prediction_error"] for r in reviews if "prediction_error" in r]
    abs_errors = [r["absolute_error"] for r in reviews if "absolute_error" in r]
    n = len(reviews)
    report = {
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "n_reviewed": n,
        "mae_return": statistics.fmean(map(abs, pred_errors)) if pred_errors else None,
        "bias_return": statistics.fmean(pred_errors) if pred_errors else None,
        "mean_absolute_probability_error": (
            statistics.fmean(abs_errors) if abs_errors else None
        ),
        "stale_evidence_rate": (
            sum(1 for r in reviews if r.get("evidence_was_stale")) / n if n else None
        ),
        "thesis_hit_rate": (
            statistics.fmean(
                1.0 if r["thesis_played_out"] else 0.0
                for r in reviews if r["thesis_played_out"] is not None
            )
            if any(r["thesis_played_out"] is not None for r in reviews)
            else None
        ),
        "reviews": reviews,
        "top_lessons": sorted(
            {lesson for r in reviews for lesson in r["lessons"]}
        )[:20],
        "advisory_only": True,
        "human_review_required": True,
    }
    if report["bias_return"] is not None and abs(report["bias_return"]) > 0.02:
        direction = "optimistic" if report["bias_return"] < 0 else "pessimistic"
        report["top_lessons"].append(
            f"systematic {direction} bias of {report['bias_return']:+.3f} per "
            "signal — recalibrate expected returns"
        )
    return report
