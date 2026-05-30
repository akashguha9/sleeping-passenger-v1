"""Wiring Sprint — the live advisory decision path (pure, advisory-only).

The previous sprint built five tested foundation modules but left them
*unwired*: nothing in a live decision path called them, so a candidate could
never actually be downgraded by a stale source, a bad Moltbook history, an
exhausted capacity budget, or a hard state veto — and ``n_valid_p`` could only
ever grow inside the foundation tests.

This module is the single orchestrator that wires them together in one
deterministic order::

    1. source freshness   -> source_freshness_contract.classify_canonical_status
    2. base probability   -> probability_snapshot.build_probability_snapshot
    3. Moltbook adjust    -> moltbook_adjustment.apply_moltbook_adjustment
    4. capacity guard     -> capital_rotation_guard.evaluate_capacity
    5. admission gates    -> admission_gates.evaluate_admission_gates
    6. snapshot persist   -> decision_probability_snapshot.record_decision_probability
    7. advisory output    (final_advisory_class + every metadata block)

It is ADVISORY-ONLY by construction:

* every output spreads ``advisory_safety_stamps()`` so ``execution_gate`` is
  ``LOCKED``, ``broker_api_called`` is ``False`` and ``ai_execution_count`` is
  ``0``;
* no broker / order / execute / buy / sell code path exists here;
* Moltbook can only *lower* a probability or downgrade a class — never unlock
  execution;
* ``predictive_claim_allowed`` is always ``False`` — this module never claims
  calibration (that requires N>=200 labelled outcomes and Brier/ECE gates that
  live in ``calibration_report``).

The only side effect is an *additive* INSERT into the ``decision_probability_
snapshots`` table when a ``db_path`` is supplied; pass ``db_path=None`` to run
the path with no side effects at all.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

try:  # pragma: no cover - exercised both ways across the suite
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.source_freshness_contract import classify_canonical_status, DEFAULT_TTL_HOURS
    from scripts.probability_snapshot import build_probability_snapshot
    from scripts.moltbook_adjustment import (
        DEFAULT_DOWNGRADE_THRESHOLD, adjust_admission,
        apply_moltbook_adjustment, signature_from_dict,
    )
    from scripts.capital_rotation_guard import evaluate_capacity
    from scripts.admission_gates import ADVISORY_CANDIDATE, WATCHLIST, evaluate_admission_gates
    from scripts.decision_probability_snapshot import build_decision_snapshot, record_decision_probability
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from source_freshness_contract import classify_canonical_status, DEFAULT_TTL_HOURS  # type: ignore[no-redef]
    from probability_snapshot import build_probability_snapshot  # type: ignore[no-redef]
    from moltbook_adjustment import (  # type: ignore[no-redef]
        DEFAULT_DOWNGRADE_THRESHOLD, adjust_admission,
        apply_moltbook_adjustment, signature_from_dict,
    )
    from capital_rotation_guard import evaluate_capacity  # type: ignore[no-redef]
    from admission_gates import ADVISORY_CANDIDATE, WATCHLIST, evaluate_admission_gates  # type: ignore[no-redef]
    from decision_probability_snapshot import build_decision_snapshot, record_decision_probability  # type: ignore[no-redef]

# Calibration gate sample-size floor (mirrored for the honest status string).
N_MIN: int = 200


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def run_live_decision_path(
    *,
    signal_id: str,
    axes: Mapping[str, Any] | None = None,
    ticker: str | None = None,
    country: str | None = None,
    signal_class: str | None = None,
    sector: str | None = None,
    market_regime: str | None = None,
    failure_type: str | None = None,
    source_mix: Any = None,
    trade_id: str | None = None,
    prediction_horizon_days: float | None = None,
    target_event_definition: str | None = None,
    api_health_status: str = "OK",
    rows_added: int = 0,
    canonical_age_hours: float | None = None,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    mock_flag: bool = False,
    backfill_only: bool = False,
    filtered: bool = False,
    latest_canonical_signal_timestamp: str | None = None,
    state: str | None = None,
    shock_override: str | None = None,
    chaos_risk: float = 0.0,
    moltbook_entries: Iterable[Mapping[str, Any]] | None = None,
    capital: float | None = None,
    cash_available: float | None = None,
    entry_price: float | None = None,
    hard_stop_price: float | None = None,
    leverage: float = 1.0,
    leverage_valid: bool = True,
    side: str = "BUY",
    regime_ok: bool = True,
    existing_country_exposure: float = 0.0,
    db_path: Any = None,
) -> dict[str, Any]:
    """Run one candidate through the full advisory decision path.

    Returns a single advisory-only dict.  ``db_path=None`` makes the call
    completely side-effect free (the snapshot is built but not persisted).
    """
    stamps = advisory_safety_stamps()
    axes_map = dict(axes or {})

    # ----- 1. Source freshness -------------------------------------------
    source_truth = classify_canonical_status(
        api_health_status=api_health_status,
        rows_added=int(rows_added or 0),
        age_hours=canonical_age_hours,
        ttl_hours=ttl_hours,
        mock_flag=bool(mock_flag),
        backfill_only=bool(backfill_only),
        filtered=bool(filtered),
    )
    is_live_canonical = bool(source_truth["live_canonical"])
    source_truth_score = float(source_truth["C_s"])
    fresh_score = float(source_truth["freshness_score"])
    # A non-live-canonical source feeds C_s (==0 unless live) to the freshness
    # gate, so ZERO_FRESH_ROWS / STALE / MOCK / BACKFILL force a block — no way
    # to fake liveness.
    data_freshness_for_gate = source_truth_score
    staleness_penalty = max(0.0, 1.0 - fresh_score)
    mock_penalty = 1.0 if mock_flag else 0.0

    # ----- 2. Base probability -------------------------------------------
    if axes_map:
        snap = build_probability_snapshot(
            signal_id=signal_id, axes=axes_map, chaos_risk=chaos_risk,
            staleness_penalty=staleness_penalty, mock_penalty=mock_penalty,
        )
        p_base: float | None = float(snap.model_probability)
        p_base_reason = "OK"
    else:
        p_base = None
        p_base_reason = "NO_SCORE_VECTOR_AT_DECISION"

    # ----- 3. Moltbook adjustment ----------------------------------------
    signature = signature_from_dict({
        "country": country, "signal_class": signal_class, "source_mix": source_mix,
        "sector": sector, "market_regime": market_regime, "failure_type": failure_type,
    })
    entries = list(moltbook_entries or [])
    if p_base is None:
        moltbook = {
            "p_base": None, "p_adj": None, "moltbook_penalty": 0.0,
            "moltbook_pattern_n": 0, "moltbook_bad_rate": 0.0,
            "moltbook_adjustment_applied": False, "reason": "NO_BASE_PROBABILITY",
            "moltbook_can_unlock_execution": False,
        }
        p_after_moltbook: float | None = None
        moltbook_penalty = 0.0
    else:
        moltbook = apply_moltbook_adjustment(p_base, signature, entries)
        p_after_moltbook = float(moltbook["p_adj"])
        moltbook_penalty = float(moltbook["moltbook_penalty"])

    # ----- 4. Capacity guard ---------------------------------------------
    capacity = evaluate_capacity(
        ticker=ticker or signal_id, country=country,
        capital=_f(capital, 0.0), cash_available=_f(cash_available, 0.0),
        entry_price=entry_price, hard_stop_price=hard_stop_price,
        leverage=_f(leverage, 1.0), leverage_valid=bool(leverage_valid), side=side,
        p_adj=p_after_moltbook if p_after_moltbook is not None else 0.5,
        freshness_score=fresh_score, moltbook_penalty=moltbook_penalty,
        regime_ok=bool(regime_ok), existing_country_exposure=_f(existing_country_exposure, 0.0),
    )
    # Capacity is UNKNOWN when no capital context was provided at all — we then
    # refuse to promote to candidate (block/downgrade), never silently size 0.
    capacity_unknown = capital is None or cash_available is None
    if capacity_unknown:
        capacity["capacity_status"] = "CAPACITY_UNKNOWN"
        capacity_ok = False
    else:
        capacity["capacity_status"] = (
            "CAPACITY_OK" if capacity.get("portfolio_capacity_ok") else "CAPACITY_BLOCKED"
        )
        capacity_ok = bool(capacity.get("portfolio_capacity_ok"))
    # Advisory-language alias — never frame size as an order quantity.
    capacity["suggested_paper_notional"] = capacity.get("position_notional")

    # ----- 5. Admission gates --------------------------------------------
    gate_candidate = {
        "base_candidate": True,
        "state": state,
        "shock_override": shock_override,
        "chaos_risk": chaos_risk,
        "data_freshness": data_freshness_for_gate,
        "leverage_valid": bool(leverage_valid),
        "portfolio_capacity_ok": capacity_ok,
        "moltbook_block": False,
        "advisory_only": True,
        "human_execution_required": True,
    }
    gate = evaluate_admission_gates(gate_candidate)
    final_advisory_class = gate.advisory_class

    # ----- 5b. Moltbook soft downgrade -----------------------------------
    moltbook_downgraded = False
    if gate.admitted and final_advisory_class == ADVISORY_CANDIDATE:
        downgraded = adjust_admission(
            final_advisory_class, moltbook_penalty,
            threshold=DEFAULT_DOWNGRADE_THRESHOLD,
        )
        if downgraded != final_advisory_class:
            final_advisory_class = downgraded  # -> WATCHLIST
            moltbook_downgraded = True

    # ----- 6. Snapshot persist (additive; the only side effect) ----------
    snapshot_kwargs: dict[str, Any] = dict(
        signal_id=signal_id, axes=axes_map or None, trade_id=trade_id,
        ticker=ticker, country=country, signal_class=signal_class,
        market_regime=market_regime, prediction_horizon_days=prediction_horizon_days,
        chaos_risk=chaos_risk, staleness_penalty=staleness_penalty, mock_penalty=mock_penalty,
    )
    if target_event_definition is not None:
        snapshot_kwargs["target_event_definition"] = target_event_definition
    if db_path is not None:
        snapshot = record_decision_probability(db_path=db_path, **snapshot_kwargs)
        snapshot_persisted = True
    else:
        snapshot = build_decision_snapshot(**snapshot_kwargs)
        snapshot_persisted = False

    # ----- 7. Advisory output --------------------------------------------
    calibration_status = (
        "INSUFFICIENT_EVIDENCE" if p_base is None else "PENDING_OUTCOME_LABELS"
    )
    out: dict[str, Any] = {
        "signal_id": signal_id,
        "ticker": ticker,
        "country": country,
        "final_advisory_class": final_advisory_class,
        "admitted": bool(gate.admitted) and not moltbook_downgraded,
        "candidate_may_be_actionable_for_human_review": bool(
            gate.admitted and final_advisory_class == ADVISORY_CANDIDATE
        ),
        "p_base": p_base,
        "p_base_reason": p_base_reason,
        "p_after_moltbook": p_after_moltbook,
        "model_probability": snapshot.get("model_probability"),
        "model_probability_reason": snapshot.get("model_probability_reason"),
        "model_version": snapshot.get("model_version"),
        "scoring_version": snapshot.get("scoring_version"),
        "prediction_horizon_days": snapshot.get("prediction_horizon_days"),
        "target_event_definition": snapshot.get("target_event_definition"),
        "score_vector": snapshot.get("score_vector"),
        "snapshot_id": snapshot.get("snapshot_id"),
        "snapshot_persisted": snapshot_persisted,
        "source_truth": {
            "api_health_status": source_truth["api_health_status"],
            "canonical_signal_status": source_truth["canonical_signal_status"],
            "rows_added": source_truth["rows_added"],
            "latest_canonical_signal_timestamp": latest_canonical_signal_timestamp,
            "canonical_age_hours": source_truth["age_hours"],
            "is_live_canonical": is_live_canonical,
            "source_truth_score": source_truth_score,
            "freshness_score": fresh_score,
        },
        "source_truth_score": source_truth_score,
        "is_live_canonical": is_live_canonical,
        "moltbook": moltbook,
        "moltbook_downgraded": moltbook_downgraded,
        "capacity_result": capacity,
        "capacity_status": capacity["capacity_status"],
        "capacity_ok": capacity_ok,
        "gate_result": {
            "gate_passed": bool(gate.admitted),
            "advisory_class": gate.advisory_class,
            "blocked_by": list(gate.blocking_reasons),
            "gate_vector": dict(gate.gates),
        },
        "calibration_status": calibration_status,
        "predictive_claim_allowed": False,
        "n_min": N_MIN,
    }
    out.update(stamps)
    out["advisory_only"] = True
    out["human_execution_required"] = True
    return out


__all__ = ["run_live_decision_path", "N_MIN"]
