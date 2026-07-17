"""Decision Twin — a frozen, immutable, replayable representation of a decision
at a specific information cutoff. THE keystone of the closed learning loop.

A Decision Twin is NOT a clone of the user and imitates no personality. It is a
falsifiable snapshot: what the system knew and did not know, what each lens and
the council believed, which action states were available, what it *predicted*,
and — critically — what it *refused* to predict. Its content is hashed so any
later mutation is detectable; outcomes and operator choices attach via SEPARATE
append-only records and never rewrite the twin.

This makes the whole decision process falsifiable, replayable, comparable,
calibratable, auditable and learnable — and lets the system learn from *decision-
process quality*, not merely realised returns.

Pure/deterministic: identical (council, observation) → identical twin + hash.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.simulation_intelligence.contracts import (
        MarketObservation, AdvisoryVote, VOTE_DEFENSIVENESS, CONTRACT_VERSION,
    )
    from scripts.simulation_intelligence import regime as regime_mod
    from scripts.simulation_intelligence import actionable_uncertainty as unc_mod
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        MarketObservation, AdvisoryVote, VOTE_DEFENSIVENESS, CONTRACT_VERSION,
    )
    from simulation_intelligence import regime as regime_mod  # type: ignore[no-redef]
    from simulation_intelligence import actionable_uncertainty as unc_mod  # type: ignore[no-redef]

TWIN_CONTRACT_VERSION = "twin-1.0.0"

# Council defensiveness → predicted probability of an adverse forward move
# (shared with the calibration harness's advisory target).
_VOTE_ADVERSE_PROB = {
    AdvisoryVote.RISK_BLOCK.value: 0.85, AdvisoryVote.AVOID.value: 0.65,
    AdvisoryVote.WAIT.value: 0.45, AdvisoryVote.OUTCOME_REVIEW.value: 0.35,
    AdvisoryVote.WATCH.value: 0.20,
}
ADVERSE_THRESHOLD = -0.05
TAIL_THRESHOLD = -0.10
DEFAULT_WINDOW_DAYS = 20


def _hash(payload: Any) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FalsifiablePrediction:
    """One frozen, resolvable prediction. Frozen so it can never be edited after
    its outcome is known (post-outcome-mutation guard)."""

    prediction_id: str
    twin_id: str
    candidate_id: str
    parent_signal_id: str
    info_cutoff: str
    target_variable: str            # e.g. "drawdown<=-5% within window"
    kind: str                       # PROBABILITY | INTERVAL
    probability: float | None       # for PROBABILITY predictions
    interval_low: float | None      # for INTERVAL predictions
    interval_high: float | None
    outcome_window_days: int
    benchmark: str
    resolution_method: str          # how a resolver derives the realized value
    invalidation_condition: str
    evidence_grade: str
    calibration_cohort: str         # regime key for cohorting
    immutability_hash: str
    status: str = "FROZEN"          # FROZEN | RESOLVED | UNRESOLVED | EXPIRED

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def _mk_prediction(twin_id, obs, cutoff, cohort, *, pid_suffix, target, kind,
                   probability=None, lo=None, hi=None, window, resolution,
                   invalidation, grade, parent) -> FalsifiablePrediction:
    core = {
        "twin_id": twin_id, "candidate_id": obs.ticker, "info_cutoff": cutoff,
        "target": target, "kind": kind, "probability": probability,
        "interval_low": lo, "interval_high": hi, "window": window,
    }
    h = _hash(core)
    pid = "PRED_" + hashlib.sha256(f"{twin_id}|{pid_suffix}".encode()).hexdigest()[:12]
    return FalsifiablePrediction(
        prediction_id=pid, twin_id=twin_id, candidate_id=obs.ticker,
        parent_signal_id=parent, info_cutoff=cutoff, target_variable=target,
        kind=kind, probability=probability, interval_low=lo, interval_high=hi,
        outcome_window_days=window, benchmark="entry_close",
        resolution_method=resolution, invalidation_condition=invalidation,
        evidence_grade=grade, calibration_cohort=cohort, immutability_hash=h)


def _realized_vol(rets: list[float]) -> float:
    rets = [float(x) for x in rets if x == x]
    if len(rets) < 2:
        return 0.02
    m = sum(rets) / len(rets)
    return (sum((x - m) ** 2 for x in rets) / (len(rets) - 1)) ** 0.5


@dataclass(frozen=True, slots=True)
class DecisionTwin:
    twin_id: str
    candidate_id: str
    parent_signal_id: str
    run_id: str
    info_cutoff: str
    as_of: str
    contract_version: str
    twin_contract_version: str
    # What the system knew / did not know.
    known: dict[str, Any]
    unknown: list[str]              # missing fields
    stale_evidence: list[str]
    active_assumptions: list[dict[str, Any]]
    # What each lens + the council believed.
    lens_beliefs: list[dict[str, Any]]
    council_belief: dict[str, Any]
    available_action_states: list[str]
    # Regime + uncertainty + VoI.
    regime: dict[str, Any]
    uncertainty: dict[str, Any]
    top_research_action: dict[str, Any]
    # Predictions — and what it REFUSED to predict.
    predictions: list[FalsifiablePrediction]
    refused_predictions: list[dict[str, Any]]
    advisory_state: str
    immutability_hash: str
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__slots__ if k != "predictions"}
        d["predictions"] = [p.to_dict() for p in self.predictions]
        d.update(advisory_safety_stamps())
        return d

    def verify_integrity(self) -> bool:
        """Recompute the hash over the frozen content and compare."""
        return _hash(self._hash_payload()) == self.immutability_hash

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id, "info_cutoff": self.info_cutoff,
            "run_id": self.run_id, "council_belief": self.council_belief,
            "predictions": [p.immutability_hash for p in self.predictions],
            "advisory_state": self.advisory_state,
            "unknown": sorted(self.unknown),
        }


def build_twin(
    council: dict[str, Any],
    obs: MarketObservation,
    *,
    top_research_action: dict[str, Any] | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    created_at: str = "",
) -> DecisionTwin:
    """Freeze a Decision Twin from a council result + its observation."""
    cutoff = str(council.get("data_cutoff", "") or obs.data_cutoff or "")
    run_id = str(council.get("run_id", ""))
    parent = str(council.get("parent_signal_id", ""))
    twin_id = "TWIN_" + hashlib.sha256(f"{run_id}|{cutoff}|{window_days}".encode()).hexdigest()[:12]
    reg = regime_mod.classify_regime(obs)
    cohort = reg.regime_key
    unc = unc_mod.decompose(obs, council)

    vote = str(council.get("aggregate_vote", "WATCH"))
    frag = float(council.get("fragility", 0.0) or 0.0)
    robust = float(council.get("robustness", 0.0) or 0.0)
    rets = list(obs.returns or [])
    rvol = _realized_vol(rets)

    # --- freeze falsifiable, resolvable predictions --------------------------
    predictions: list[FalsifiablePrediction] = []
    refused: list[dict[str, Any]] = []

    has_price_history = len(rets) >= 2 and obs.price is not None
    if has_price_history:
        p_adverse = max(0.0, min(1.0, _VOTE_ADVERSE_PROB.get(vote, 0.3) + 0.1 * frag))
        predictions.append(_mk_prediction(
            twin_id, obs, cutoff, cohort, pid_suffix="adverse", parent=parent,
            target=f"max drawdown from entry <= {ADVERSE_THRESHOLD:.0%} within {window_days}d",
            kind="PROBABILITY", probability=round(p_adverse, 4), window=window_days,
            resolution="min(forward_close)/entry_close - 1 <= threshold",
            invalidation="price history revised or delisted",
            grade="MODEL_INFERRED" if vote != "WATCH" else "SIMULATED_ONLY"))

        p_tail = max(0.0, min(1.0, 0.25 * p_adverse + 0.4 * frag))
        predictions.append(_mk_prediction(
            twin_id, obs, cutoff, cohort, pid_suffix="tail", parent=parent,
            target=f"tail drawdown <= {TAIL_THRESHOLD:.0%} within {window_days}d",
            kind="PROBABILITY", probability=round(p_tail, 4), window=window_days,
            resolution="min(forward_close)/entry_close - 1 <= tail_threshold",
            invalidation="price history revised", grade="MODEL_INFERRED"))

        p_up = max(0.0, min(1.0, 0.5 + 0.3 * robust - 0.4 * (p_adverse - 0.3)))
        predictions.append(_mk_prediction(
            twin_id, obs, cutoff, cohort, pid_suffix="up", parent=parent,
            target=f"forward return > 0 at {window_days}d",
            kind="PROBABILITY", probability=round(p_up, 4), window=window_days,
            resolution="exit_close/entry_close - 1 > 0",
            invalidation="price history revised", grade="MODEL_INFERRED"))

        dd_lo, dd_hi = round(-3.0 * rvol - 0.02, 4), round(-0.5 * rvol, 4)
        predictions.append(_mk_prediction(
            twin_id, obs, cutoff, cohort, pid_suffix="ddband", parent=parent,
            target=f"realized max drawdown in band over {window_days}d",
            kind="INTERVAL", lo=dd_lo, hi=dd_hi, window=window_days,
            resolution="realized_max_drawdown in [low, high]",
            invalidation="price history revised", grade="MODEL_INFERRED"))

        vlo, vhi = round(0.5 * rvol, 5), round(2.0 * rvol, 5)
        predictions.append(_mk_prediction(
            twin_id, obs, cutoff, cohort, pid_suffix="volband", parent=parent,
            target=f"realized daily volatility in band over {window_days}d",
            kind="INTERVAL", lo=vlo, hi=vhi, window=window_days,
            resolution="stdev(forward daily returns) in [low, high]",
            invalidation="price history revised", grade="MODEL_INFERRED"))
    else:
        # The twin REFUSES to predict what it cannot: this is a feature, not a gap.
        refused.append({
            "target": "any price-path prediction",
            "reason": "insufficient price history / missing price at cutoff",
            "missing": list(obs.missing_fields or []),
            "evidence_grade": "INSUFFICIENT_DATA"})

    lens_beliefs = [{
        "lens": lr.get("lens"), "vote": lr.get("advisory_vote"),
        "evidence_label": lr.get("evidence_label"),
        "confidence": lr.get("confidence"), "tail_warning": lr.get("tail_warning", ""),
    } for lr in council.get("lens_results", [])]

    council_belief = {
        "aggregate_vote": vote, "disagreement_class": council.get("disagreement_class"),
        "evidence_label": council.get("evidence_label"),
        "aggregate_confidence": council.get("aggregate_confidence"),
        "robustness": robust, "fragility": frag,
        "risk_block_engaged": council.get("risk_block_engaged"),
        "simulation_only": council.get("simulation_only"),
    }

    known = {
        "price": obs.price, "returns_n": len(rets), "volatility": obs.volatility,
        "spread_bps": obs.spread_bps, "adv_usd": obs.adv_usd, "sector": obs.sector,
        "source_count": obs.source_count, "freshness_status": obs.freshness_status,
        "provenance": dict(obs.provenance or {}),
    }
    stale = [f for f in (obs.provenance or {}) if "stale" in str(obs.provenance.get(f, "")).lower()]
    if (obs.freshness_status or "").upper() in ("AGING", "STALE"):
        stale.append(f"freshness={obs.freshness_status}")
    assumptions = [{"name": a.get("name", ""), "value": a.get("value")}
                   for a in (getattr(obs, "catalysts", None) or [])]

    twin = DecisionTwin(
        twin_id=twin_id, candidate_id=obs.ticker, parent_signal_id=parent,
        run_id=run_id, info_cutoff=cutoff, as_of=str(council.get("as_of", "") or obs.as_of),
        contract_version=CONTRACT_VERSION, twin_contract_version=TWIN_CONTRACT_VERSION,
        known=known, unknown=list(obs.missing_fields or []), stale_evidence=stale,
        active_assumptions=assumptions, lens_beliefs=lens_beliefs,
        council_belief=council_belief,
        available_action_states=[v.value for v in AdvisoryVote],
        regime=reg.to_dict(), uncertainty=unc.to_dict(),
        top_research_action=top_research_action or {},
        predictions=predictions, refused_predictions=refused,
        advisory_state=vote, immutability_hash="", created_at=created_at)
    # Compute the integrity hash over the frozen payload and re-freeze with it.
    h = _hash(twin._hash_payload())
    return dataclasses.replace(twin, immutability_hash=h)


__all__ = [
    "TWIN_CONTRACT_VERSION", "FalsifiablePrediction", "DecisionTwin", "build_twin",
    "ADVERSE_THRESHOLD", "TAIL_THRESHOLD", "DEFAULT_WINDOW_DAYS",
]
