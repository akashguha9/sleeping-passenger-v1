"""Replayable advisory signal-quality harness.

Evaluates historical advisory signals against later observations to
measure *signal quality* — never investment performance.  All inputs are
caller-supplied or fixture records; no live price calls happen here.

Metrics:
    precision_at_k                       top-k by score that later confirmed
    hit_rate_by_verdict                  confirmation rate per advisory verdict
    average_score_by_outcome_bucket      mean score among confirmed/refuted/unresolved
    brier_score                          mean (p − y)² over event probabilities
    bucketed_calibration_error           |mean predicted − empirical| per probability bucket
    narrative_decay_error                mean |predicted persistence − observed persistence|
    trap_flag_false_positive_rate        trap-flagged signals that later confirmed

A record confirms when its observed outcome shows fundamental
confirmation, filing confirmation, or a positive price return — a
signal-quality definition, not a return claim.
"""

from __future__ import annotations

from src.alpha import ADVISORY_DISCLAIMER
from src.utils.math_utils import clamp01, clip

OUTCOME_BUCKETS = ("confirmed", "refuted", "unresolved")

REPLAY_DISCLAIMER = (
    f"{ADVISORY_DISCLAIMER} Replay metrics measure historical advisory "
    "signal quality only; they are not performance results and imply "
    "nothing about future outcomes."
)


def classify_outcome(record: dict[str, object]) -> str:
    """Bucket one replay record by its observed outcome.

    ``confirmed`` needs at least one explicit positive observation;
    ``refuted`` needs at least one explicit negative one; records with
    no observations stay ``unresolved``.
    """
    observed = record.get("observed_outcome") or {}
    if not isinstance(observed, dict):
        return "unresolved"
    fundamental = observed.get("fundamental_confirmation")
    filing = observed.get("filing_confirmation")
    price_return = observed.get("price_return")
    positives = [
        fundamental is True,
        filing is True,
        isinstance(price_return, (int, float)) and float(price_return) > 0,
    ]
    negatives = [
        fundamental is False,
        filing is False,
        isinstance(price_return, (int, float)) and float(price_return) < 0,
    ]
    if any(positives):
        return "confirmed"
    if any(negatives):
        return "refuted"
    return "unresolved"


def precision_at_k(records: list[dict[str, object]], k: int) -> float | None:
    """Fraction of the top-k records (by opportunity score) that confirmed.

    Unresolved records count against precision — an advisory system gets
    no credit for unverifiable calls.  Returns ``None`` when no records.
    """
    if not records or k <= 0:
        return None
    ranked = sorted(
        records,
        key=lambda r: float(r.get("opportunity_score", 0.0)),
        reverse=True,
    )[:k]
    confirmed = sum(1 for record in ranked if classify_outcome(record) == "confirmed")
    return confirmed / len(ranked)


def brier_score(probability_pairs: list[tuple[float, int]]) -> float | None:
    """Mean (p − y)² over (predicted probability, binary outcome) pairs."""
    if not probability_pairs:
        return None
    total = 0.0
    for probability, outcome in probability_pairs:
        p = clamp01(float(probability))
        y = 1.0 if outcome else 0.0
        total += (p - y) ** 2
    return total / len(probability_pairs)


def bucketed_calibration_error(
    probability_pairs: list[tuple[float, int]], bucket_count: int = 5
) -> list[dict[str, object]]:
    """Per-bucket |mean predicted probability − empirical frequency|."""
    if bucket_count <= 0:
        return []
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bucket_count)]
    for probability, outcome in probability_pairs:
        p = clamp01(float(probability))
        index = min(bucket_count - 1, int(p * bucket_count))
        buckets[index].append((p, 1 if outcome else 0))
    rows: list[dict[str, object]] = []
    for index, bucket in enumerate(buckets):
        low = index / bucket_count
        high = (index + 1) / bucket_count
        if not bucket:
            rows.append(
                {
                    "bucket": f"[{low:.1f}, {high:.1f})",
                    "count": 0,
                    "mean_predicted": None,
                    "empirical_frequency": None,
                    "abs_error": None,
                }
            )
            continue
        mean_predicted = sum(p for p, _ in bucket) / len(bucket)
        empirical = sum(y for _, y in bucket) / len(bucket)
        rows.append(
            {
                "bucket": f"[{low:.1f}, {high:.1f})",
                "count": len(bucket),
                "mean_predicted": mean_predicted,
                "empirical_frequency": empirical,
                "abs_error": abs(mean_predicted - empirical),
            }
        )
    return rows


def evaluate_replay(
    records: list[dict[str, object]] | None,
    *,
    k: int = 5,
    calibration_buckets: int = 5,
) -> dict[str, object]:
    """Compute the full deterministic replay report for a record set."""
    records = list(records or [])
    missing_inputs: list[str] = []
    if not records:
        missing_inputs.append("replay_records")

    outcome_by_record = [classify_outcome(record) for record in records]

    hit_rate_by_verdict: dict[str, dict[str, object]] = {}
    for record, outcome in zip(records, outcome_by_record):
        verdict = str(record.get("verdict", "unknown"))
        row = hit_rate_by_verdict.setdefault(
            verdict, {"total": 0, "confirmed": 0, "hit_rate": None}
        )
        row["total"] = int(row["total"]) + 1
        if outcome == "confirmed":
            row["confirmed"] = int(row["confirmed"]) + 1
    for row in hit_rate_by_verdict.values():
        total = int(row["total"])
        row["hit_rate"] = (int(row["confirmed"]) / total) if total else None

    average_score_by_outcome: dict[str, float | None] = {}
    for bucket in OUTCOME_BUCKETS:
        scores = [
            float(record.get("opportunity_score", 0.0))
            for record, outcome in zip(records, outcome_by_record)
            if outcome == bucket
        ]
        average_score_by_outcome[bucket] = (
            sum(scores) / len(scores) if scores else None
        )

    probability_pairs: list[tuple[float, int]] = []
    for record, outcome in zip(records, outcome_by_record):
        probability = record.get("event_probability")
        if probability is None or outcome == "unresolved":
            continue
        probability_pairs.append(
            (float(probability), 1 if outcome == "confirmed" else 0)
        )

    decay_errors: list[float] = []
    for record in records:
        predicted = record.get("predicted_narrative_persistence")
        observed = (record.get("observed_outcome") or {}).get(
            "narrative_persistence"
        )
        if predicted is None or observed is None:
            continue
        decay_errors.append(abs(clamp01(float(predicted)) - clamp01(float(observed))))

    flagged = [
        (record, outcome)
        for record, outcome in zip(records, outcome_by_record)
        if record.get("trap_flags")
    ]
    resolved_flagged = [
        outcome for _, outcome in flagged if outcome != "unresolved"
    ]
    trap_flag_false_positive_rate = (
        sum(1 for outcome in resolved_flagged if outcome == "confirmed")
        / len(resolved_flagged)
        if resolved_flagged
        else None
    )

    confirmed_count = outcome_by_record.count("confirmed")
    return {
        "record_count": len(records),
        "outcome_counts": {
            bucket: outcome_by_record.count(bucket) for bucket in OUTCOME_BUCKETS
        },
        "precision_at_k": precision_at_k(records, k),
        "k": k,
        "hit_rate_by_verdict": hit_rate_by_verdict,
        "average_score_by_outcome_bucket": average_score_by_outcome,
        "brier_score": brier_score(probability_pairs),
        "scored_probability_count": len(probability_pairs),
        "bucketed_calibration": bucketed_calibration_error(
            probability_pairs, calibration_buckets
        ),
        "narrative_decay_error": (
            sum(decay_errors) / len(decay_errors) if decay_errors else None
        ),
        "trap_flag_false_positive_rate": trap_flag_false_positive_rate,
        "calibration_support": clip(
            100.0 * min(1.0, len(probability_pairs) / 50.0), 0.0, 100.0
        ),
        "missing_inputs": missing_inputs,
        "explanation": [
            f"{len(records)} record(s): {confirmed_count} confirmed, "
            f"{outcome_by_record.count('refuted')} refuted, "
            f"{outcome_by_record.count('unresolved')} unresolved.",
            "Unresolved records count against precision; an advisory "
            "system gets no credit for unverifiable calls.",
            f"Calibration support {min(1.0, len(probability_pairs) / 50.0) * 100:.0f}/100 "
            "(needs ~50 resolved event probabilities to mature).",
        ],
        "disclaimer": REPLAY_DISCLAIMER,
    }


def demo_replay_dataset() -> list[dict[str, object]]:
    """Deterministic fixture records for dashboard/demo use.

    Clearly synthetic: every record carries source ``manual_stub`` and a
    demo signal id.  TODO(replay): replace with reconciled outcomes from
    the journal DB once enough advisory history accumulates.
    """
    return [
        {
            "signal_id": "DEMO_PLUMBING_DISTRIBUTOR",
            "as_of_date": "2026-01-05",
            "theme": "residential plumbing",
            "ticker": "DEMO_A",
            "source": "manual_stub",
            "opportunity_score": 62.0,
            "confidence": 55.0,
            "verdict": "deep_research",
            "event_probability": 0.7,
            "predicted_narrative_persistence": 0.8,
            "trap_flags": [],
            "subsequent_observation_window_days": 30,
            "observed_outcome": {
                "price_return": 0.04,
                "drawdown": -0.02,
                "fundamental_confirmation": True,
                "narrative_persistence": 0.7,
                "filing_confirmation": True,
            },
        },
        {
            "signal_id": "DEMO_MEME_THEME",
            "as_of_date": "2026-01-05",
            "theme": "viral consumer fad",
            "ticker": "DEMO_B",
            "source": "manual_stub",
            "opportunity_score": 38.0,
            "confidence": 30.0,
            "verdict": "watchlist",
            "event_probability": 0.6,
            "predicted_narrative_persistence": 0.5,
            "trap_flags": ["high_narrative_low_proof"],
            "subsequent_observation_window_days": 30,
            "observed_outcome": {
                "price_return": -0.12,
                "drawdown": -0.25,
                "fundamental_confirmation": False,
                "narrative_persistence": 0.1,
                "filing_confirmation": False,
            },
        },
        {
            "signal_id": "DEMO_UNRESOLVED_EVENT",
            "as_of_date": "2026-01-20",
            "theme": "water infrastructure funding",
            "ticker": "DEMO_C",
            "source": "manual_stub",
            "opportunity_score": 48.0,
            "confidence": 40.0,
            "verdict": "event_trade_only",
            "event_probability": 0.4,
            "predicted_narrative_persistence": 0.6,
            "trap_flags": [],
            "subsequent_observation_window_days": 30,
            "observed_outcome": {
                "price_return": None,
                "drawdown": None,
                "fundamental_confirmation": None,
                "narrative_persistence": None,
                "filing_confirmation": None,
            },
        },
    ]
