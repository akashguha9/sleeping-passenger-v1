"""Priority 2 — Leakage-safe SIL calibration harness.

Links SIL council predictions to real forward outcomes and reports HONEST
calibration. It calibrates the council's *defensiveness* against realized adverse
moves — an advisory target (no buy/sell direction) — and never auto-promotes an
evidence grade. Promotion above SIMULATED_ONLY requires an explicit governance
decision plus an adequate leakage-safe sample; this module only *reports what the
evidence would support*.

Leakage guards (all enforced + tested):
* LOOKAHEAD        — outcome bars must be strictly AFTER the observation cutoff.
* SAME_DAY_AMBIG   — the entry bar must be strictly after the cutoff date.
* FUTURE_UNRESOLVED— a window that has not fully elapsed by the session date is
  OPEN and excluded (no peeking at incomplete outcomes).
* DUPLICATE        — predictions/outcomes are de-duplicated by prediction id.
* IMMUTABLE_PRED   — `SILPrediction` is frozen; resolving never mutates it, so a
  prediction cannot be edited after its outcome is known.
* SYNTHETIC        — synthetic fixtures are never calibration-eligible (via
  `outcome_evidence.build_outcome`).

Metrics: Brier, log loss, ECE, reliability curve, tail-warning precision/recall,
false-/missed-risk-block rate, decision stability, plus an OOS isotonic/Platt fit
through the existing `calibration_map` (its train/test split is the look-ahead
guard inside the fitter).
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.simulation_intelligence.contracts import AdvisoryVote, VOTE_DEFENSIVENESS
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from simulation_intelligence.contracts import AdvisoryVote, VOTE_DEFENSIVENESS  # type: ignore[no-redef]

DEFAULT_ADVERSE_THRESHOLD = -0.05   # a >=5% forward drop is an "adverse" move
DEFAULT_WINDOW_DAYS = 20
_LOW_SAMPLE_MIN = 20                 # below this → LOW_SAMPLE, never CALIBRATED

# Council defensiveness → predicted probability of an adverse forward move.
_VOTE_ADVERSE_PROB = {
    AdvisoryVote.RISK_BLOCK.value: 0.85,
    AdvisoryVote.AVOID.value: 0.65,
    AdvisoryVote.WAIT.value: 0.45,
    AdvisoryVote.OUTCOME_REVIEW.value: 0.35,
    AdvisoryVote.WATCH.value: 0.20,
}


@dataclass(frozen=True, slots=True)
class SILPrediction:
    """An immutable prediction extracted from a council run. Frozen so it cannot
    be mutated after its outcome is known (post-outcome-mutation guard)."""

    prediction_id: str
    run_id: str
    parent_signal_id: str
    ticker: str
    market: str
    data_cutoff: str
    aggregate_vote: str
    predicted_adverse_prob: float
    tail_warning: bool
    risk_block: bool
    window_days: int

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def prediction_from_council(council: dict[str, Any],
                            window_days: int = DEFAULT_WINDOW_DAYS) -> SILPrediction:
    vote = str(council.get("aggregate_vote", "WATCH"))
    base = _VOTE_ADVERSE_PROB.get(vote, 0.3)
    # Fragility nudges the probability up (a fragile defensive call is more worried).
    frag = float(council.get("fragility", 0.0) or 0.0)
    p = max(0.0, min(1.0, base + 0.1 * frag))
    run_id = str(council.get("run_id", ""))
    cutoff = str(council.get("data_cutoff", "") or "")
    pid = "PRED_" + hashlib.sha256(f"{run_id}|{cutoff}|{window_days}".encode()).hexdigest()[:12]
    return SILPrediction(
        prediction_id=pid, run_id=run_id,
        parent_signal_id=str(council.get("parent_signal_id", "")),
        ticker=str(council.get("ticker", "")), market=str(council.get("market", "UNKNOWN")),
        data_cutoff=cutoff, aggregate_vote=vote, predicted_adverse_prob=round(p, 4),
        tail_warning=bool(council.get("tail_warnings")),
        risk_block=bool(council.get("risk_block_engaged")), window_days=window_days,
    )


@dataclass(slots=True)
class PredictionOutcome:
    prediction_id: str
    ticker: str
    resolved: bool
    reason: str                    # RESOLVED / LOOKAHEAD / FUTURE_UNRESOLVED / NO_DATA / SAME_DAY_AMBIG
    entry_date: str = ""
    exit_date: str = ""
    entry_price: float | None = None
    exit_price: float | None = None
    realized_return: float | None = None
    adverse: bool = False
    predicted_adverse_prob: float = 0.0
    tail_warning: bool = False
    risk_block: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def _parse_date(s: Any):
    import datetime as _dt
    try:
        return _dt.date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def resolve_prediction(
    prediction: SILPrediction,
    forward_bars: list[dict[str, Any]],
    session_date: str,
    *,
    adverse_threshold: float = DEFAULT_ADVERSE_THRESHOLD,
) -> PredictionOutcome:
    """Resolve one prediction against forward OHLCV bars, leakage-safe.

    ``forward_bars`` are ascending date/close dicts. Entry is the FIRST bar
    strictly after the observation cutoff (no same-day ambiguity); exit is the
    bar closest to cutoff+window_days that is not after the session date."""
    out = PredictionOutcome(
        prediction_id=prediction.prediction_id, ticker=prediction.ticker,
        resolved=False, reason="NO_DATA",
        predicted_adverse_prob=prediction.predicted_adverse_prob,
        tail_warning=prediction.tail_warning, risk_block=prediction.risk_block)

    cutoff = _parse_date(prediction.data_cutoff)
    session = _parse_date(session_date)
    if cutoff is None or session is None:
        out.reason = "NO_DATA"
        return out

    import datetime as _dt
    target_exit = cutoff + _dt.timedelta(days=int(prediction.window_days))
    if target_exit > session:
        out.reason = "FUTURE_UNRESOLVED"  # window not elapsed — do NOT peek
        return out

    # Strictly-after-cutoff bars only (LOOKAHEAD + SAME_DAY guards).
    fwd = []
    for b in forward_bars:
        d = _parse_date(b.get("date"))
        c = b.get("adjusted_close")
        if c is None:
            c = b.get("close")
        try:
            c = float(c)
        except (TypeError, ValueError):
            continue
        if d is None or c != c:
            continue
        if d <= cutoff:
            continue  # same-day or earlier → excluded (no look-ahead)
        if d > session:
            continue  # future beyond session → not yet known
        fwd.append((d, c))
    fwd.sort(key=lambda x: x[0])
    if len(fwd) < 2:
        out.reason = "NO_DATA"
        return out

    entry_d, entry_p = fwd[0]
    # Exit = last bar at//before the target exit date; fall back to last available.
    exit_candidates = [(d, c) for d, c in fwd if d <= target_exit]
    exit_d, exit_p = exit_candidates[-1] if exit_candidates else fwd[-1]
    if exit_d <= entry_d or not entry_p:
        out.reason = "NO_DATA"
        return out

    ret = exit_p / entry_p - 1.0
    out.resolved = True
    out.reason = "RESOLVED"
    out.entry_date = entry_d.isoformat()
    out.exit_date = exit_d.isoformat()
    out.entry_price = round(entry_p, 6)
    out.exit_price = round(exit_p, 6)
    out.realized_return = round(ret, 6)
    out.adverse = ret <= adverse_threshold
    return out


def _to_outcome_evidence(prediction: SILPrediction, outcome: PredictionOutcome):
    """Build a firewall-passing OutcomeEvidence (source IMPORTED_BACKTEST) so the
    existing eligibility/quality guards apply. Label WIN = the defensive call was
    correct (adverse move happened); score_at_entry = predicted adverse prob."""
    try:
        from scripts.outcome_evidence import build_outcome, IMPORTED_BACKTEST
    except ModuleNotFoundError:  # pragma: no cover
        from outcome_evidence import build_outcome, IMPORTED_BACKTEST  # type: ignore[no-redef]
    label = "WIN" if outcome.adverse else "LOSS"
    return build_outcome(
        outcome_id=prediction.prediction_id, source_type=IMPORTED_BACKTEST,
        ticker=prediction.ticker, direction="SHORT",
        signal_id=prediction.parent_signal_id or prediction.run_id,
        opened_at=outcome.entry_date, closed_at=outcome.exit_date,
        horizon_days=float(prediction.window_days),
        score_at_entry=prediction.predicted_adverse_prob,
        realized_return=abs(outcome.realized_return or 0.0) if outcome.adverse
        else -(abs(outcome.realized_return or 0.0)),
        outcome_label_override=label,
    )


def _ece(pairs: list[tuple[float, int]], bins: int = 6) -> tuple[float, list[dict]]:
    if not pairs:
        return 0.0, []
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for p, y in pairs:
        idx = min(bins - 1, int(p * bins))
        buckets[idx].append((p, y))
    ece = 0.0
    n = len(pairs)
    diagram = []
    for i, b in enumerate(buckets):
        if not b:
            diagram.append({"bin": i, "n": 0, "avg_pred": None, "avg_obs": None})
            continue
        avg_p = sum(p for p, _ in b) / len(b)
        avg_y = sum(y for _, y in b) / len(b)
        ece += (len(b) / n) * abs(avg_p - avg_y)
        diagram.append({"bin": i, "n": len(b), "avg_pred": round(avg_p, 4),
                        "avg_obs": round(avg_y, 4)})
    return round(ece, 4), diagram


@dataclass(slots=True)
class CalibrationCohort:
    n: int
    resolved_n: int
    excluded: dict[str, int]
    brier: float | None
    log_loss: float | None
    ece: float | None
    reliability_diagram: list[dict]
    adverse_base_rate: float | None
    tail_precision: float | None
    tail_recall: float | None
    false_risk_block_rate: float | None
    missed_risk_block_rate: float | None
    status: str                    # NO_DATA / LOW_SAMPLE / CALIBRATING / CALIBRATED
    proposed_evidence_grade: str   # what the evidence WOULD support (never auto-applied)
    evidence_grade_applied: str    # ALWAYS SIMULATED_ONLY unless governance promotes
    oos_calibration: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__slots__}
        d.update(advisory_safety_stamps())
        return d


def build_cohort(
    predictions: list[SILPrediction],
    outcomes: list[PredictionOutcome],
    *,
    human_approved: bool = False,
) -> CalibrationCohort:
    """Aggregate resolved (prediction, outcome) pairs into an honest cohort.

    ``human_approved`` gates the *proposed* evidence grade only; the applied grade
    stays SIMULATED_ONLY regardless (no auto-promotion)."""
    # Dedup by prediction_id (DUPLICATE guard).
    seen: set[str] = set()
    resolved: list[PredictionOutcome] = []
    excluded = {"LOOKAHEAD": 0, "FUTURE_UNRESOLVED": 0, "NO_DATA": 0,
                "SAME_DAY_AMBIG": 0, "DUPLICATE": 0}
    for o in outcomes:
        if o.prediction_id in seen:
            excluded["DUPLICATE"] += 1
            continue
        seen.add(o.prediction_id)
        if not o.resolved:
            excluded[o.reason] = excluded.get(o.reason, 0) + 1
            continue
        resolved.append(o)

    n = len(resolved)
    if n == 0:
        return CalibrationCohort(
            n=len(outcomes), resolved_n=0, excluded=excluded, brier=None, log_loss=None,
            ece=None, reliability_diagram=[], adverse_base_rate=None,
            tail_precision=None, tail_recall=None, false_risk_block_rate=None,
            missed_risk_block_rate=None, status="NO_DATA",
            proposed_evidence_grade="SIMULATED_ONLY",
            evidence_grade_applied="SIMULATED_ONLY",
            notes=["no resolved leakage-safe outcomes"])

    pairs = [(o.predicted_adverse_prob, 1 if o.adverse else 0) for o in resolved]
    brier = round(sum((p - y) ** 2 for p, y in pairs) / n, 4)
    eps = 1e-6
    log_loss = round(-sum(y * math.log(min(1 - eps, max(eps, p))) +
                          (1 - y) * math.log(min(1 - eps, max(eps, 1 - p)))
                          for p, y in pairs) / n, 4)
    ece, diagram = _ece(pairs)
    base = round(sum(y for _, y in pairs) / n, 4)

    adverse = [o for o in resolved if o.adverse]
    tail = [o for o in resolved if o.tail_warning]
    tail_adverse = [o for o in tail if o.adverse]
    tail_precision = round(len(tail_adverse) / len(tail), 4) if tail else None
    tail_recall = round(len(tail_adverse) / len(adverse), 4) if adverse else None
    rb = [o for o in resolved if o.risk_block]
    false_rb = round(sum(1 for o in rb if not o.adverse) / len(rb), 4) if rb else None
    missed_rb = round(sum(1 for o in adverse if not o.risk_block) / len(adverse), 4) if adverse else None

    if n < _LOW_SAMPLE_MIN:
        status = "LOW_SAMPLE"
    elif n < 50:
        status = "CALIBRATING"
    else:
        status = "CALIBRATED"

    # OOS isotonic/Platt via the existing calibration_map (leakage-safe split).
    oos: dict[str, Any] = {}
    try:
        from scripts.simulation_intelligence.calibration_harness import _to_outcome_evidence as _toe
        from scripts.calibration_map import fit_from_outcomes
        pred_by_id = {p.prediction_id: p for p in predictions}
        oes = [_toe(pred_by_id[o.prediction_id], o) for o in resolved
               if o.prediction_id in pred_by_id]
        if oes:
            oos = fit_from_outcomes(oes).to_dict()
    except Exception as exc:  # calibration_map optional
        oos = {"error": type(exc).__name__}

    # Proposed grade — what the evidence WOULD justify. Applied grade NEVER
    # auto-promotes; only a human governance decision may raise it.
    if status == "CALIBRATED" and (ece is not None and ece <= 0.10) and (brier <= 0.25):
        proposed = "EMPIRICALLY_CALIBRATED" if human_approved else "BACKTEST_DERIVED"
    elif status in ("CALIBRATING", "CALIBRATED"):
        proposed = "BACKTEST_DERIVED"
    else:
        proposed = "SIMULATED_ONLY"

    notes = [
        f"applied evidence grade stays SIMULATED_ONLY (no auto-promotion); "
        f"evidence would support {proposed} with governance sign-off",
        f"excluded by leakage guards: {excluded}",
    ]
    return CalibrationCohort(
        n=len(outcomes), resolved_n=n, excluded=excluded, brier=brier, log_loss=log_loss,
        ece=ece, reliability_diagram=diagram, adverse_base_rate=base,
        tail_precision=tail_precision, tail_recall=tail_recall,
        false_risk_block_rate=false_rb, missed_risk_block_rate=missed_rb,
        status=status, proposed_evidence_grade=proposed,
        evidence_grade_applied="SIMULATED_ONLY", oos_calibration=oos, notes=notes)


__all__ = [
    "SILPrediction", "PredictionOutcome", "CalibrationCohort",
    "prediction_from_council", "resolve_prediction", "build_cohort",
    "DEFAULT_ADVERSE_THRESHOLD", "DEFAULT_WINDOW_DAYS",
]
