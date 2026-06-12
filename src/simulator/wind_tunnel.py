"""The Wind Tunnel: walk-forward replay of the FULL simulator pipeline.

Closes the loop nobody had connected: the repo's walk-forward backtest
discipline (``scripts/backtest_calibration.py`` — strict no-lookahead,
mandatory price provenance) on one side, and the simulator's telemetry
resolution -> calibration bridge on the other.

At each historical decision point the ENTIRE pipeline runs (physics,
consent, strategy, stewards' room) on strictly backward-looking bars; the
verdict is then resolved against the realized forward return, producing
the first outcome-grounded calibration evidence in the system — including
the question every prior report flagged as the one that matters:

    Do CONTRADICTION_HOLD verdicts actually underperform clean ones?

Honesty ladder (provenance is REQUIRED, mirroring backtest_calibration):
    * price_provenance="SYNTHETIC" -> telemetry data_source fixture_replay
    * price_provenance="IMPORTED"  -> telemetry data_source backtest_replay
Backtest evidence is real prices with counterfactual decisions — it can
measure drift but never clears autotune, and nothing here is a return
promise. ADVISORY_ONLY; no orders exist anywhere in this system.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from scripts.backtest_calibration import momentum_score

from src.simulator.calibration_bridge import build_calibration_report
from src.simulator.pipeline import evaluate_candidate_payload
from src.simulator.telemetry import (
    DecisionTelemetry,
    classify_outcome,
    resolve_telemetry_outcome,
)
from src.utils.math_utils import clamp01, clip

PROV_IMPORTED = "IMPORTED"
PROV_SYNTHETIC = "SYNTHETIC"

MIN_HISTORY_BARS = 30
MAX_BARS = 2000
MAX_DECISIONS = 200


@dataclass(slots=True)
class WindTunnelDecision:
    """One walk-forward decision and its realized outcome."""

    bar_index: int
    date: str
    final_state: str
    score: float
    contradiction_hold: bool
    forward_return: float
    result_good: bool
    outcome_class: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CohortStats:
    """Outcome statistics for one verdict cohort."""

    count: int
    win_rate: float | None
    mean_forward_return: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class WindTunnelReport:
    """Full walk-forward replay result with calibration evidence."""

    ticker: str
    price_provenance: str
    data_source: str
    bars_used: int
    decision_count: int
    horizon_days: int
    decisions: list[WindTunnelDecision] = field(default_factory=list)
    state_performance: dict[str, dict[str, object]] = field(default_factory=dict)
    contradiction_hold_cohort: CohortStats | None = None
    clean_cohort: CohortStats | None = None
    hold_underperformance: float | None = None
    calibration: dict[str, Any] = field(default_factory=dict)
    persisted_evaluations: int = 0
    rationale: list[str] = field(default_factory=list)
    advisory_note: str = (
        "ADVISORY_ONLY — counterfactual walk-forward replay; real prices "
        "do not make simulated decisions real. Not a return promise; "
        "autotune remains locked on backtest evidence."
    )
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["decisions"] = [d.to_dict() for d in self.decisions]
        return payload


def default_payload_builder(
    ticker: str, visible_bars: list[dict[str, Any]]
) -> dict[str, Any]:
    """Deterministic payload from strictly backward-looking bars.

    Maps price history onto simulator inputs: momentum drives opportunity
    and valuation heat (chased strength is hot), realized volatility and
    drawdown drive risk factors. Every number derives from ``visible_bars``
    only — the no-lookahead test corrupts future bars to prove it.
    """
    closes = [float(b["close"]) for b in visible_bars]
    momentum = momentum_score(closes)
    returns = [
        closes[i] / closes[i - 1] - 1.0
        for i in range(max(len(closes) - 20, 1), len(closes))
    ]
    mean_return = sum(returns) / len(returns) if returns else 0.0
    volatility = (
        (sum((r - mean_return) ** 2 for r in returns) / len(returns)) ** 0.5
        if returns
        else 0.0
    )
    recent = closes[-20:]
    peak = max(recent)
    drawdown = (peak - closes[-1]) / peak if peak > 0 else 0.0

    return {
        "ticker": ticker,
        "theme": "wind_tunnel_replay",
        "opportunity_quality": momentum,
        "hard_evidence_score": clamp01(0.4 + 0.4 * momentum),
        "confirmation_level": clamp01(0.3 + 0.3 * momentum),
        "predicted_probability": clip(0.30 + 0.45 * momentum, 0.05, 0.95),
        "narrative": {
            "narrative": "price replay",
            "mention_count": 12,
            "origin_count": 10,
            "independent_origin_count": 9,
            "source_quality": 0.7,
            "narrative_velocity": clip(mean_return * 20.0, -1.0, 1.0),
            "narrative_acceleration": 0.0,
        },
        "circuit": {"market_cap_usd": 5_000_000_000},
        "theme_assessment": {
            "policy_fit": 0.5,
            "macro_fit": clamp01(0.4 + 0.4 * momentum),
            "sector_momentum": momentum,
            "liquidity_support": 0.6,
            "valuation_heat": clamp01(momentum * 0.7),
            "crowding": clamp01(momentum * 0.5),
            "regulatory_friction": 0.2,
        },
        "exposure": {
            "revenue_exposure": clamp01(0.3 + 0.4 * momentum),
            "margin_sensitivity": 0.5,
            "backlog_linkage": clamp01(0.2 + 0.4 * momentum),
            "customer_linkage": 0.4,
            "geographic_fit": 0.5,
            "policy_fit": 0.4,
            "supply_chain_position": 0.5,
        },
        "inflection": {
            "delta_narrative_velocity": clip(mean_return * 30.0, -1.0, 1.0),
            "delta_volume_quality": clip((momentum - 0.5), -1.0, 1.0),
            "delta_filing_evidence": clip((momentum - 0.4), -1.0, 1.0),
        },
        "signals": [
            {
                "signal_type": "earnings_beat",
                "raw_strength": 40.0 + 50.0 * momentum,
                "signal_age_hours": 48.0,
                "source_quality": 0.8,
            }
        ],
        "aero": {
            "evidence": {
                "filing_evidence": clamp01(0.4 + 0.3 * momentum),
                "cash_flow_quality": 0.5,
                "backlog_evidence": 0.4,
                "insider_alignment": 0.4,
                "primary_source_confirmation": 0.5,
            },
            "noise_level": clamp01(volatility * 10.0),
            "contradiction_level": 0.1,
            "duplication_level": 0.2,
            "ambiguity_level": 0.2,
            "promotional_bias": 0.1,
            "stock_specific_thrust": momentum,
            "hidden_fundamental_improvement": 0.3,
            "data_quality": 0.9,
        },
        "risk_factors": {
            "high_valuation": clamp01(momentum * 0.45),
            "low_volume": clamp01(volatility * 8.0),
            "price_already_ran": clamp01(
                momentum - 0.5 if drawdown < 0.03 else 0.0
            ),
        },
        "meal_box": {
            "thesis": "momentum continuation thesis from replayed bars",
            "evidence": "trailing price/volume structure in visible bars",
            "catalyst": "continuation over the configured horizon",
            "invalidation": "exit when momentum score decays below 0.4",
        },
        "driver": {
            "license_level": "pro_am",
            "thesis_logging_quality": 0.8,
            "invalidation_compliance": 0.8,
            "position_sizing_discipline": 0.8,
            "confirmation_patience": 0.7,
            "replay_audit_completion": 0.8,
            "calibration_honesty": 0.8,
        },
    }


def _cohort(decisions: list[WindTunnelDecision]) -> CohortStats:
    if not decisions:
        return CohortStats(count=0, win_rate=None, mean_forward_return=None)
    wins = sum(1 for d in decisions if d.result_good)
    return CohortStats(
        count=len(decisions),
        win_rate=wins / len(decisions),
        mean_forward_return=(
            sum(d.forward_return for d in decisions) / len(decisions)
        ),
    )


@dataclass(slots=True)
class GateExperimentReport:
    """A/B walk-forward replay: self-fed adaptation gates ON vs OFF.

    Answers the question a new gate must face before it earns trust:
    do the bars where the gate changed the verdict actually carry worse
    forward returns? Honest by construction — when the gate never
    diverges on a series, the verdict is "insufficient evidence", not
    success.
    """

    ticker: str
    price_provenance: str
    decision_count: int
    divergent_count: int
    capped_cohort: CohortStats | None = None
    undiverged_cohort: CohortStats | None = None
    capped_return_disadvantage: float | None = None
    gates_helping: bool | None = None
    divergent_bars: list[dict[str, object]] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    advisory_note: str = (
        "ADVISORY_ONLY — counterfactual gate experiment on replayed "
        "decisions; never a return promise, never clears autotune."
    )
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def run_gate_experiment(
    *,
    ticker: str,
    bars: list[dict[str, Any]],
    price_provenance: str,
    horizon_days: int = 10,
    every_n_bars: int = 5,
    payload_builder: Callable[[str, list[dict[str, Any]]], dict[str, Any]]
    | None = None,
) -> GateExperimentReport:
    """Replay the same bars twice — self-feed gates on, then off — and
    compare forward returns on the bars where the gate changed the
    verdict. A gate that caps bars with worse-than-average forward
    returns is earning its keep; one that never fires has proven
    nothing either way."""
    builder = payload_builder or default_payload_builder

    def ungated_builder(
        tick: str, visible: list[dict[str, Any]]
    ) -> dict[str, Any]:
        payload = builder(tick, visible)
        payload["self_feed"] = {"enabled": False}
        return payload

    gated = run_wind_tunnel(
        ticker=ticker, bars=bars, price_provenance=price_provenance,
        horizon_days=horizon_days, every_n_bars=every_n_bars,
        payload_builder=builder,
    )
    ungated = run_wind_tunnel(
        ticker=ticker, bars=bars, price_provenance=price_provenance,
        horizon_days=horizon_days, every_n_bars=every_n_bars,
        payload_builder=ungated_builder,
    )

    ungated_by_bar = {d.bar_index: d for d in ungated.decisions}
    divergent: list[WindTunnelDecision] = []
    undiverged: list[WindTunnelDecision] = []
    divergent_bars: list[dict[str, object]] = []
    for decision in gated.decisions:
        control = ungated_by_bar.get(decision.bar_index)
        if control is None:
            continue
        if decision.final_state != control.final_state:
            divergent.append(decision)
            divergent_bars.append({
                "bar_index": decision.bar_index,
                "date": decision.date,
                "gated_state": decision.final_state,
                "ungated_state": control.final_state,
                "forward_return": decision.forward_return,
            })
        else:
            undiverged.append(decision)

    capped_stats = _cohort(divergent)
    undiverged_stats = _cohort(undiverged)
    disadvantage = (
        undiverged_stats.mean_forward_return - capped_stats.mean_forward_return
        if capped_stats.mean_forward_return is not None
        and undiverged_stats.mean_forward_return is not None
        else None
    )
    helping = disadvantage > 0 if disadvantage is not None else None

    rationale = [
        f"{len(gated.decisions)} gated vs {len(ungated.decisions)} ungated "
        f"walk-forward decisions; gate diverged on {len(divergent)} bar(s)",
    ]
    if disadvantage is None:
        rationale.append(
            "insufficient evidence: the gate never changed a verdict on "
            "this series — nothing proven, nothing disproven"
            if not divergent
            else f"gate diverged on all {len(divergent)} decision(s); no "
            "undiverged baseline on this series — directional value "
            "unmeasured"
        )
    else:
        rationale.append(
            f"capped bars mean forward return "
            f"{capped_stats.mean_forward_return:+.4f} vs undiverged "
            f"{undiverged_stats.mean_forward_return:+.4f} "
            f"(disadvantage {disadvantage:+.4f}) — "
            + (
                "the gate is pointing at worse bars (helping)"
                if helping
                else "the gate is NOT yet avoiding losses on this series"
            )
        )
    rationale.append(
        "counterfactual A/B replay: measures gate value, never clears "
        "autotune"
    )

    return GateExperimentReport(
        ticker=str(ticker).upper(),
        price_provenance=str(price_provenance).upper(),
        decision_count=len(gated.decisions),
        divergent_count=len(divergent),
        capped_cohort=capped_stats,
        undiverged_cohort=undiverged_stats,
        capped_return_disadvantage=disadvantage,
        gates_helping=helping,
        divergent_bars=divergent_bars,
        rationale=rationale,
    )


def run_wind_tunnel(
    *,
    ticker: str,
    bars: list[dict[str, Any]],
    price_provenance: str,
    horizon_days: int = 10,
    every_n_bars: int = 5,
    payload_builder: Callable[[str, list[dict[str, Any]]], dict[str, Any]]
    | None = None,
    persist: bool = False,
) -> WindTunnelReport:
    """Walk the bars forward, decide, resolve, calibrate.

    ``bars`` are dicts with ``date`` and ``close`` (the shape
    ``backtest_calibration.load_ohlcv_from_db`` returns), oldest first.
    ``price_provenance`` is REQUIRED: "IMPORTED" only for genuine
    historical prices; anything else is treated as SYNTHETIC and labeled
    fixture_replay. No default — silence is not provenance.
    """
    provenance = str(price_provenance).upper()
    data_source = (
        "backtest_replay" if provenance == PROV_IMPORTED else "fixture_replay"
    )
    builder = payload_builder or default_payload_builder
    series = list(bars)[:MAX_BARS]
    horizon = max(int(horizon_days), 1)
    step = max(int(every_n_bars), 1)

    decisions: list[WindTunnelDecision] = []
    telemetry_rows: list[dict[str, Any]] = []
    persisted = 0
    previous_state: str | None = None

    indices = range(MIN_HISTORY_BARS, len(series) - horizon, step)
    for bar_index in list(indices)[:MAX_DECISIONS]:
        visible = series[:bar_index]  # STRICTLY backward-looking
        payload = builder(ticker, visible)
        payload["data_source"] = data_source
        if previous_state:
            payload.setdefault("previous_state", previous_state)
        result = evaluate_candidate_payload(payload)
        decision = result["decision"]
        previous_state = decision["final_state"]

        entry = float(series[bar_index]["close"])
        exit_price = float(series[bar_index + horizon]["close"])
        forward_return = (exit_price - entry) / entry if entry else 0.0
        result_good = forward_return > 0.0

        telemetry = DecisionTelemetry(**result["telemetry"])
        telemetry.decision_time = str(series[bar_index].get("date", bar_index))
        telemetry = resolve_telemetry_outcome(
            telemetry,
            actual_outcome=1.0 if result_good else 0.0,
            outcome_class=classify_outcome(
                process_was_good=decision["gate_results"].get(
                    "meal_box_gate", False
                ),
                result_was_good=result_good,
            ),
        )
        telemetry_rows.append(telemetry.to_dict())

        if persist:
            from scripts import simulator_store

            result["telemetry"] = telemetry.to_dict()
            evaluation_id = simulator_store.record_evaluation(result)
            persisted += 1 if evaluation_id else 0

        decisions.append(
            WindTunnelDecision(
                bar_index=bar_index,
                date=str(series[bar_index].get("date", bar_index)),
                final_state=decision["final_state"],
                score=float(decision["final_candidate_score"]),
                contradiction_hold=bool(
                    result["unified_verdict"]["contradiction_hold"]
                ),
                forward_return=forward_return,
                result_good=result_good,
                outcome_class=str(telemetry.outcome_class),
            )
        )

    # Per-state and hold-vs-clean performance splits.
    by_state: dict[str, list[WindTunnelDecision]] = {}
    for decision_row in decisions:
        by_state.setdefault(decision_row.final_state, []).append(decision_row)
    state_performance = {
        state: _cohort(rows).to_dict() for state, rows in sorted(by_state.items())
    }
    held = [d for d in decisions if d.contradiction_hold]
    clean = [d for d in decisions if not d.contradiction_hold]
    held_stats = _cohort(held)
    clean_stats = _cohort(clean)
    underperformance = (
        clean_stats.mean_forward_return - held_stats.mean_forward_return
        if held_stats.mean_forward_return is not None
        and clean_stats.mean_forward_return is not None
        else None
    )

    calibration = build_calibration_report(telemetry_rows).to_dict()

    rationale = [
        f"{len(decisions)} walk-forward decision(s) over {len(series)} bars "
        f"(horizon {horizon} bars, every {step}); provenance {provenance} -> "
        f"calibration tier '{data_source}'",
        "no-lookahead: every payload built from bars[:i] only",
    ]
    if underperformance is not None:
        rationale.append(
            f"CONTRADICTION_HOLD cohort ({held_stats.count}) vs clean "
            f"({clean_stats.count}): hold underperformance "
            f"{underperformance:+.4f} mean forward return — "
            + (
                "holds are earning their keep"
                if underperformance > 0
                else "holds are NOT yet predictive on this series"
            )
        )
    rationale.append(
        "counterfactual replay: measures drift, never clears autotune"
    )

    return WindTunnelReport(
        ticker=str(ticker).upper(),
        price_provenance=provenance,
        data_source=data_source,
        bars_used=len(series),
        decision_count=len(decisions),
        horizon_days=horizon,
        decisions=decisions,
        state_performance=state_performance,
        contradiction_hold_cohort=held_stats,
        clean_cohort=clean_stats,
        hold_underperformance=underperformance,
        calibration=calibration,
        persisted_evaluations=persisted,
        rationale=rationale,
    )
