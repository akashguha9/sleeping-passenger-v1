"""Resolved-outcome import + streak audit: the bridge from doctrine to
evidence, and the guard against the model believing its own streak.

**Import contract** — one JSON row per resolved case:

    {"id": "case_001", "ticker": "XYZ",
     "entry_date": "2025-01-01", "entry_price": 100.0,
     "exit_date": "2025-03-01", "exit_price": 118.0,
     "benchmark_entry": 5000.0, "benchmark_exit": 5100.0,
     "predicted_edge": 0.18, "predicted_expiry_days": 45,
     "actual_resolution_days": 32,
     "narrative_phase_entry": "early", "narrative_phase_exit":
     "consensus", "thesis_tags": ["belief_gap"]}

Computed per row (the mission's formulas, verbatim):

    realized_alpha   = R_asset − R_benchmark
    prediction_error = |predicted_edge − realized_alpha|
    expiry_accuracy  = |t_predicted_expiry − t_actual_resolution|

Invalid rows fail safely into an errors list — one bad row never
poisons the batch. Every row carries a data tier; this loader does not
fetch anything (no live feeds): it accepts what the operator imports
and labels it honestly.

**Streak audit** — streak is not edge:

    streak_reliability  = attributed wins / total wins
    overconfidence_gap  = mean stated confidence − realized win rate
    hot_hand_risk       = trailing-streak share × (1 − reliability)
                          + max(overconfidence_gap, 0)

Causal confidence is capped by BOTH the realized win rate and the data
tier (synthetic 0.40 / backtest 0.60 / empirical 0.90): three wins on
fixtures cannot mint conviction, and confidence can never exceed what
the calibration tier could possibly support. ADVISORY_ONLY.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from src.utils.math_utils import clamp01, safe_div
from src.utils.validation_utils import coerce_float, normalized_score

DATA_TIERS: tuple[str, ...] = (
    "synthetic_fixture", "backtest_replay", "empirical",
)
TIER_CONFIDENCE_CAPS: dict[str, float] = {
    "synthetic_fixture": 0.40,
    "backtest_replay": 0.60,
    "empirical": 0.90,
}
REQUIRED_FIELDS: tuple[str, ...] = (
    "id", "ticker", "entry_date", "entry_price", "exit_date",
    "exit_price", "benchmark_entry", "benchmark_exit",
)
MIN_SAMPLE = 10


@dataclass(slots=True)
class ImportedOutcome:
    """One resolved case scored against its own prediction."""

    case_id: str
    ticker: str
    data_tier: str
    holding_days: int
    asset_return: float
    benchmark_return: float
    realized_alpha: float
    win: bool
    predicted_edge: float | None
    prediction_error: float | None
    predicted_expiry_days: float | None
    actual_resolution_days: float | None
    expiry_accuracy: float | None
    expired_before_resolution: bool | None
    narrative_phase_entry: str = ""
    narrative_phase_exit: str = ""
    thesis_tags: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class OutcomeImportReport:
    """A batch import: scored rows, rejected rows, honest summary."""

    data_tier: str
    imported: list[ImportedOutcome] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["imported"] = [o.to_dict() for o in self.imported]
        return payload


def _parse_row(row: dict[str, Any], data_tier: str) -> ImportedOutcome:
    missing = [f for f in REQUIRED_FIELDS if row.get(f) in (None, "")]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")
    entry_price = float(row["entry_price"])
    exit_price = float(row["exit_price"])
    bench_entry = float(row["benchmark_entry"])
    bench_exit = float(row["benchmark_exit"])
    if entry_price <= 0 or bench_entry <= 0:
        raise ValueError("entry prices must be positive")
    entry_day = date.fromisoformat(str(row["entry_date"]))
    exit_day = date.fromisoformat(str(row["exit_date"]))
    holding_days = (exit_day - entry_day).days
    if holding_days < 0:
        raise ValueError("exit_date precedes entry_date")

    asset_return = exit_price / entry_price - 1.0
    benchmark_return = bench_exit / bench_entry - 1.0
    realized_alpha = round(asset_return - benchmark_return, 6)

    predicted_edge = (
        coerce_float(row["predicted_edge"])
        if row.get("predicted_edge") is not None else None
    )
    prediction_error = (
        round(abs(predicted_edge - realized_alpha), 6)
        if predicted_edge is not None else None
    )
    predicted_expiry = (
        coerce_float(row["predicted_expiry_days"])
        if row.get("predicted_expiry_days") is not None else None
    )
    actual_resolution = (
        coerce_float(row["actual_resolution_days"])
        if row.get("actual_resolution_days") is not None else None
    )
    expiry_accuracy = (
        round(abs(predicted_expiry - actual_resolution), 2)
        if predicted_expiry is not None and actual_resolution is not None
        else None
    )
    expired_before = (
        predicted_expiry < actual_resolution
        if predicted_expiry is not None and actual_resolution is not None
        else None
    )

    rationale = [
        f"alpha {realized_alpha:+.4f} = asset {asset_return:+.4f} − "
        f"benchmark {benchmark_return:+.4f} over {holding_days}d",
    ]
    if prediction_error is not None:
        rationale.append(
            f"prediction error {prediction_error:.4f} = |predicted "
            f"{predicted_edge:+.4f} − realized {realized_alpha:+.4f}|"
        )
    if expiry_accuracy is not None:
        rationale.append(
            f"expiry accuracy {expiry_accuracy:.1f}d "
            f"(predicted {predicted_expiry:.0f}d vs actual "
            f"{actual_resolution:.0f}d)"
            + ("; the edge was predicted to die before resolution"
               if expired_before else "")
        )
    return ImportedOutcome(
        case_id=str(row["id"]),
        ticker=str(row["ticker"]).upper(),
        data_tier=data_tier,
        holding_days=holding_days,
        asset_return=round(asset_return, 6),
        benchmark_return=round(benchmark_return, 6),
        realized_alpha=realized_alpha,
        win=realized_alpha > 0,
        predicted_edge=predicted_edge,
        prediction_error=prediction_error,
        predicted_expiry_days=predicted_expiry,
        actual_resolution_days=actual_resolution,
        expiry_accuracy=expiry_accuracy,
        expired_before_resolution=expired_before,
        narrative_phase_entry=str(row.get("narrative_phase_entry", "")),
        narrative_phase_exit=str(row.get("narrative_phase_exit", "")),
        thesis_tags=[str(t) for t in row.get("thesis_tags", []) or []],
        rationale=rationale,
    )


def load_resolved_outcomes(
    rows: list[dict[str, Any]],
    *,
    data_tier: str = "synthetic_fixture",
) -> OutcomeImportReport:
    """Import a batch of resolved cases; bad rows land in ``errors``.

    ``data_tier`` is REQUIRED honesty: only the operator knows whether
    these rows are fixtures, backtests, or real resolved decisions —
    unknown tiers collapse to synthetic, never upward.
    """
    tier = data_tier if data_tier in DATA_TIERS else "synthetic_fixture"
    imported: list[ImportedOutcome] = []
    errors: list[dict[str, str]] = []
    for index, row in enumerate(rows or []):
        if not isinstance(row, dict):
            errors.append({"row": str(index), "error": "not an object"})
            continue
        try:
            imported.append(_parse_row(row, tier))
        except (ValueError, TypeError, KeyError) as exc:
            errors.append({
                "row": str(row.get("id", index)), "error": str(exc),
            })

    count = len(imported)
    wins = sum(1 for o in imported if o.win)
    prediction_errors = [
        o.prediction_error for o in imported
        if o.prediction_error is not None
    ]
    expiry_accuracies = [
        o.expiry_accuracy for o in imported if o.expiry_accuracy is not None
    ]
    summary = {
        "count": count,
        "rejected": len(errors),
        "data_tier": tier,
        "status": "require_more_data" if count < MIN_SAMPLE else "scored",
        "win_rate": round(wins / count, 4) if count else None,
        "mean_realized_alpha": (
            round(sum(o.realized_alpha for o in imported) / count, 6)
            if count else None
        ),
        "mean_prediction_error": (
            round(sum(prediction_errors) / len(prediction_errors), 6)
            if prediction_errors else None
        ),
        "mean_expiry_accuracy_days": (
            round(sum(expiry_accuracies) / len(expiry_accuracies), 2)
            if expiry_accuracies else None
        ),
        "rationale": [
            f"{count} imported / {len(errors)} rejected at tier '{tier}'"
            + ("; below the floor of "
               f"{MIN_SAMPLE} — metrics reported, conclusions withheld"
               if count < MIN_SAMPLE else ""),
            "synthetic rows prove the plumbing, never the model",
        ],
    }
    return OutcomeImportReport(
        data_tier=tier, imported=imported, errors=errors, summary=summary,
    )


# ---------------------------------------------------------------------------
# Streak audit: streak is not edge
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class StreakAudit:
    """Did the model win on mechanism, or just on variance?"""

    sample_size: int
    win_rate: float | None
    trailing_win_streak: int
    attributed_wins: int
    streak_reliability: float | None  # attributed wins / wins
    mean_stated_confidence: float | None
    overconfidence_gap: float | None  # confidence − win rate
    hot_hand_risk: float
    causal_confidence: float  # capped by win rate AND data tier
    confidence_cap: float
    data_tier: str
    warnings: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def streak_inputs_from_outcomes(
    outcomes: list[ImportedOutcome],
) -> list[dict[str, Any]]:
    """Bridge imported outcomes into streak-audit rows. A win counts as
    ATTRIBUTED only when the case carries thesis tags — a named, reused
    causal mechanism; tagless wins are wins of unknown cause."""
    return [
        {
            "win": o.win,
            "attributed": bool(o.thesis_tags),
            "confidence": (
                clamp01(0.5 + o.predicted_edge)
                if o.predicted_edge is not None else 0.5
            ),
        }
        for o in outcomes
    ]


def audit_streak(
    rows: list[dict[str, Any]],
    *,
    data_tier: str = "synthetic_fixture",
) -> StreakAudit:
    """Decompose a run of results into mechanism vs variance.

    ``rows``: ``{"win": bool, "attributed": bool, "confidence": float}``
    in chronological order. Three eyes-closed wins do not mint
    conviction: causal confidence ≤ min(stated, win rate, tier cap).
    """
    tier = data_tier if data_tier in DATA_TIERS else "synthetic_fixture"
    cap = TIER_CONFIDENCE_CAPS[tier]
    clean = [r for r in (rows or []) if isinstance(r, dict)]
    n = len(clean)
    if n == 0:
        return StreakAudit(
            sample_size=0, win_rate=None, trailing_win_streak=0,
            attributed_wins=0, streak_reliability=None,
            mean_stated_confidence=None, overconfidence_gap=None,
            hot_hand_risk=0.0, causal_confidence=0.0,
            confidence_cap=cap, data_tier=tier,
            warnings=["NO_RESOLVED_OUTCOMES"],
            rationale=["no resolved rows — no streak, no edge, no story"],
        )

    wins = sum(1 for r in clean if bool(r.get("win")))
    win_rate = wins / n
    streak = 0
    for row in reversed(clean):
        if bool(row.get("win")):
            streak += 1
        else:
            break
    attributed = sum(
        1 for r in clean if bool(r.get("win")) and bool(r.get("attributed"))
    )
    reliability = safe_div(attributed, wins) if wins else None
    confidences = [
        normalized_score(r.get("confidence", 0.5), 0.5) for r in clean
    ]
    mean_confidence = sum(confidences) / n
    overconfidence = round(mean_confidence - win_rate, 4)

    streak_share = streak / max(n, 3)  # 3-row floor: a 2/2 run ≠ 100%
    hot_hand = clamp01(
        streak_share * (1.0 - (reliability or 0.0))
        + max(overconfidence, 0.0)
    )
    causal = round(min(mean_confidence, win_rate, cap), 4)

    warnings: list[str] = []
    if n < MIN_SAMPLE:
        warnings.append("SMALL_SAMPLE")
    if wins and (reliability or 0.0) < 0.5:
        warnings.append("WINS_WITHOUT_ATTRIBUTION")
    if overconfidence > 0.15:
        warnings.append("OVERCONFIDENCE")
    if hot_hand >= 0.5:
        warnings.append("HOT_HAND_RISK")
    if causal < mean_confidence:
        warnings.append("CONFIDENCE_CAPPED_BY_TIER_OR_RECORD")

    rationale = [
        f"{wins}/{n} wins (rate {win_rate:.2f}), trailing streak "
        f"{streak}; {attributed} win(s) carry a named mechanism "
        f"(reliability {reliability if reliability is None else round(reliability, 2)})",
        f"hot-hand risk {hot_hand:.2f} = streak share {streak_share:.2f} "
        f"× (1 − reliability) + overconfidence {max(overconfidence, 0):.2f}",
        f"causal confidence {causal:.2f} = min(stated "
        f"{mean_confidence:.2f}, win rate {win_rate:.2f}, "
        f"{tier} cap {cap:.2f}) — streak is not edge; a tier cannot "
        "support more conviction than its evidence",
    ]
    return StreakAudit(
        sample_size=n,
        win_rate=round(win_rate, 4),
        trailing_win_streak=streak,
        attributed_wins=attributed,
        streak_reliability=(
            round(reliability, 4) if reliability is not None else None
        ),
        mean_stated_confidence=round(mean_confidence, 4),
        overconfidence_gap=overconfidence,
        hot_hand_risk=round(hot_hand, 4),
        causal_confidence=causal,
        confidence_cap=cap,
        data_tier=tier,
        warnings=warnings,
        rationale=rationale,
    )
