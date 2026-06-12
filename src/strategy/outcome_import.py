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
    holding_days: int | None
    asset_return: float
    benchmark_return: float | None
    realized_alpha: float | None
    win: bool
    predicted_edge: float | None
    prediction_error: float | None
    predicted_expiry_days: float | None
    actual_resolution_days: float | None
    expiry_accuracy: float | None
    expired_before_resolution: bool | None
    # How the numbers were obtained — journals record returns, not
    # price quads; forcing prices would mean fabricating them.
    return_basis: str = "prices"  # prices | recorded_return
    alpha_basis: str = "vs_benchmark"  # vs_benchmark | absolute_return_no_benchmark
    source_record: str = ""  # repo-relative citation for real rows
    gate_interaction: dict[str, Any] = field(default_factory=dict)
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
    """Two honest modes:

    * **prices** — entry/exit + benchmark quads (the full contract).
    * **recorded_return** — the journal recorded a resolved return
      (``realized_return_pct``) but not raw prices; importing it as-is
      beats fabricating price pairs. Benchmark stays optional: with no
      benchmark there is NO alpha claim — only an absolute return, and
      the row says so (``alpha_basis``).
    """
    has_prices = all(
        row.get(f) not in (None, "") for f in REQUIRED_FIELDS
    )
    has_recorded = row.get("realized_return_pct") is not None
    if not has_prices and not has_recorded:
        missing = [f for f in REQUIRED_FIELDS if row.get(f) in (None, "")]
        raise ValueError(
            "needs either the price contract (missing: "
            f"{', '.join(missing)}) or realized_return_pct"
        )

    holding_days: int | None = None
    if row.get("entry_date") and row.get("exit_date"):
        entry_day = date.fromisoformat(str(row["entry_date"]))
        exit_day = date.fromisoformat(str(row["exit_date"]))
        holding_days = (exit_day - entry_day).days
        if holding_days < 0:
            raise ValueError("exit_date precedes entry_date")
    elif has_prices:
        raise ValueError("price mode requires entry_date and exit_date")

    benchmark_return: float | None = None
    if has_prices:
        return_basis = "prices"
        entry_price = float(row["entry_price"])
        exit_price = float(row["exit_price"])
        bench_entry = float(row["benchmark_entry"])
        bench_exit = float(row["benchmark_exit"])
        if entry_price <= 0 or bench_entry <= 0:
            raise ValueError("entry prices must be positive")
        asset_return = exit_price / entry_price - 1.0
        benchmark_return = bench_exit / bench_entry - 1.0
    else:
        return_basis = "recorded_return"
        asset_return = coerce_float(row["realized_return_pct"]) / 100.0
        if (
            row.get("benchmark_entry") not in (None, "")
            and row.get("benchmark_exit") not in (None, "")
        ):
            bench_entry = float(row["benchmark_entry"])
            if bench_entry <= 0:
                raise ValueError("benchmark entry must be positive")
            benchmark_return = float(row["benchmark_exit"]) / bench_entry - 1.0

    if benchmark_return is not None:
        alpha_basis = "vs_benchmark"
        realized_alpha = round(asset_return - benchmark_return, 6)
    else:
        alpha_basis = "absolute_return_no_benchmark"
        realized_alpha = None

    # Prediction error scores against alpha when a benchmark exists,
    # else against the absolute return — and the rationale says which.
    realized_for_scoring = (
        realized_alpha if realized_alpha is not None else asset_return
    )
    predicted_edge = (
        coerce_float(row["predicted_edge"])
        if row.get("predicted_edge") is not None else None
    )
    prediction_error = (
        round(abs(predicted_edge - realized_for_scoring), 6)
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

    span = f" over {holding_days}d" if holding_days is not None else ""
    if realized_alpha is not None:
        rationale = [
            f"alpha {realized_alpha:+.4f} = asset {asset_return:+.4f} − "
            f"benchmark {benchmark_return:+.4f}{span}",
        ]
    else:
        rationale = [
            f"absolute return {asset_return:+.4f}{span} — no benchmark "
            "supplied, so NO alpha claim is made for this row",
        ]
    if return_basis == "recorded_return":
        rationale.append(
            "return imported as recorded by the journal (no raw prices "
            "fabricated)"
        )
    if prediction_error is not None:
        rationale.append(
            f"prediction error {prediction_error:.4f} = |predicted "
            f"{predicted_edge:+.4f} − realized "
            f"{realized_for_scoring:+.4f}| ({alpha_basis})"
        )
    if expiry_accuracy is not None:
        rationale.append(
            f"expiry accuracy {expiry_accuracy:.1f}d "
            f"(predicted {predicted_expiry:.0f}d vs actual "
            f"{actual_resolution:.0f}d)"
            + ("; the edge was predicted to die before resolution"
               if expired_before else "")
        )
    if row.get("id") in (None, "") or row.get("ticker") in (None, ""):
        raise ValueError("missing required field(s): id, ticker")
    return ImportedOutcome(
        case_id=str(row["id"]),
        ticker=str(row["ticker"]).upper(),
        data_tier=data_tier,
        holding_days=holding_days,
        asset_return=round(asset_return, 6),
        benchmark_return=(
            round(benchmark_return, 6) if benchmark_return is not None
            else None
        ),
        realized_alpha=realized_alpha,
        win=(realized_alpha if realized_alpha is not None
             else asset_return) > 0,
        return_basis=return_basis,
        alpha_basis=alpha_basis,
        source_record=str(row.get("source_record", "")),
        gate_interaction=dict(row.get("gate_interaction") or {}),
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
        # Alpha averages only over rows that HAVE a benchmark; rows
        # without one contribute to the absolute-return mean instead —
        # the two are never blended.
        "mean_realized_alpha": (
            round(sum(alphas) / len(alphas), 6)
            if (alphas := [o.realized_alpha for o in imported
                           if o.realized_alpha is not None])
            else None
        ),
        "mean_absolute_return": (
            round(sum(o.asset_return for o in imported) / count, 6)
            if count else None
        ),
        "rows_without_benchmark": sum(
            1 for o in imported if o.realized_alpha is None
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


# ---------------------------------------------------------------------------
# Gate utility from resolved outcomes
# ---------------------------------------------------------------------------

GATE_MIN_OBSERVATIONS = 3


def summarize_gate_outcomes(
    outcomes: list[ImportedOutcome],
) -> dict[str, Any]:
    """What did the gates actually do, judged by resolutions?

    Rows may carry ``gate_interaction``: ``{"gate": name,
    "fired": bool, "overridden": bool}``. The only configuration that
    yields a clean counterfactual is FIRED + OVERRIDDEN — the gate said
    no, the operator entered anyway, and the outcome shows who was
    right:

        fired + overridden + loss -> the gate was HELPFUL (it would
                                     have avoided the loss)
        fired + overridden + win  -> the gate was HARMFUL (it would
                                     have skipped the win)
        fired + followed          -> unobservable (no counterfactual)
        not fired                 -> pass-through (neutral context)

    Verdicts are per gate and stay ``insufficient_data`` below
    GATE_MIN_OBSERVATIONS observed counterfactuals — two overrides are
    an anecdote, not a measurement.
    """
    gates: dict[str, dict[str, int]] = {}
    for outcome in outcomes:
        interaction = outcome.gate_interaction
        if not interaction or "gate" not in interaction:
            continue
        name = str(interaction["gate"])
        stats = gates.setdefault(name, {
            "helpful": 0, "harmful": 0, "unobservable": 0,
            "pass_through": 0,
        })
        fired = bool(interaction.get("fired"))
        overridden = bool(interaction.get("overridden"))
        if fired and overridden:
            stats["helpful" if not outcome.win else "harmful"] += 1
        elif fired:
            stats["unobservable"] += 1
        else:
            stats["pass_through"] += 1

    report: dict[str, Any] = {"gates": {}, "advisory_status": "ADVISORY_ONLY"}
    for name, stats in sorted(gates.items()):
        observed = stats["helpful"] + stats["harmful"]
        if observed < GATE_MIN_OBSERVATIONS:
            verdict = "insufficient_data"
        elif stats["helpful"] > stats["harmful"]:
            verdict = "helpful"
        elif stats["harmful"] > stats["helpful"]:
            verdict = "harmful"
        else:
            verdict = "neutral"
        leaning = (
            "helpful" if stats["helpful"] > stats["harmful"]
            else "harmful" if stats["harmful"] > stats["helpful"]
            else "none"
        )
        report["gates"][name] = {
            **stats,
            "observed_counterfactuals": observed,
            "verdict": verdict,
            "leaning": leaning,
            "note": (
                f"{observed} observed counterfactual(s) — below the "
                f"floor of {GATE_MIN_OBSERVATIONS}; leaning is reported, "
                "a verdict is not"
                if verdict == "insufficient_data"
                else "judged on overridden firings only — the sole "
                "configuration with a clean counterfactual"
            ),
        }
    return report
