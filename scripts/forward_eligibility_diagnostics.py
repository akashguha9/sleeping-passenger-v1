"""Increase Forward-Eligible Throughput Sprint — Phase 1: forward eligibility
diagnostics (read-only, advisory-only).

Produces the honest *before/after* picture of how many decision candidates can
carry a real forward outcome, and — when they cannot — exactly why.  It is
read-only: it scores nothing new, persists nothing, and never claims calibration
or edge.

For each candidate the eligibility indicator decomposes as
(:mod:`scripts.forward_snapshot_contract`)::

    ForwardOutcomeEligible_i =
        I(ticker_i valid) · I(p_i valid) · I(horizon_i > 0)
      · I(target_i price_based) · I(entry_price_i > 0)
      · I(entry_ts_i <= decision_ts_i)
      · I(advisory_i == ADVISORY_ONLY) · I(gate_i == LOCKED)

The per-candidate ineligibility reason *set* (a candidate may leak on more than
one factor)::

    R_i ⊆ {MISSING_TICKER, MISSING_PROBABILITY, MISSING_HORIZON,
           MISSING_TARGET, MISSING_ENTRY_PRICE, MISSING_SCORE_VECTOR}

Counts::

    Count(reason r)   = Σ_i I(r ∈ R_i)
    N_ineligible      = Σ_i I(ForwardOutcomeEligible_i = 0)
    EligibilityRate   = N_forward_eligible / max(1, N_decisions_recorded)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from typing import Any, Iterable, Mapping, Sequence

try:  # package layout
    from scripts import persistence
    from scripts.forward_snapshot_contract import (
        DEFAULT_FORWARD_HORIZON_DAYS,
        DEFAULT_TARGET_EVENT_DEFINITION,
        is_price_based_target,
    )
    from scripts.score_real_signal_events import (
        SCORE_VECTOR_TABLE,
        complete_axes_from_row,
        ensure_score_vector_schema,
    )
    from scripts.real_signal_score_vector import SCORED
    from scripts.ticker_resolution import resolve_ticker, ticker_valid
    from scripts.real_price_outcome_evidence import (
        load_price_series,
        normalize_symbol,
        resolve_entry_price,
    )
    from scripts.probability_snapshot import compute_model_probability
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    import persistence  # type: ignore[no-redef]
    from forward_snapshot_contract import (  # type: ignore[no-redef]
        DEFAULT_FORWARD_HORIZON_DAYS,
        DEFAULT_TARGET_EVENT_DEFINITION,
        is_price_based_target,
    )
    from score_real_signal_events import (  # type: ignore[no-redef]
        SCORE_VECTOR_TABLE,
        complete_axes_from_row,
        ensure_score_vector_schema,
    )
    from real_signal_score_vector import SCORED  # type: ignore[no-redef]
    from ticker_resolution import resolve_ticker, ticker_valid  # type: ignore[no-redef]
    from real_price_outcome_evidence import (  # type: ignore[no-redef]
        load_price_series,
        normalize_symbol,
        resolve_entry_price,
    )
    from probability_snapshot import compute_model_probability  # type: ignore[no-redef]

# Reason vocabulary (mirrors the contract; MISSING_TARGET kept distinct here).
R_MISSING_TICKER = "MISSING_TICKER"
R_MISSING_ENTRY_PRICE = "MISSING_ENTRY_PRICE"
R_MISSING_PROBABILITY = "MISSING_PROBABILITY"
R_MISSING_HORIZON = "MISSING_HORIZON"
R_MISSING_TARGET = "MISSING_TARGET"
R_MISSING_SCORE_VECTOR = "MISSING_SCORE_VECTOR"
R_UNSUPPORTED_SOURCE = "UNSUPPORTED_SOURCE_TYPE"


def _bump(d: dict[str, int], key: str | None) -> None:
    if key:
        d[key] = d.get(key, 0) + 1


def _valid_p(p: Any) -> bool:
    if p is None:
        return False
    try:
        pf = float(p)
    except (TypeError, ValueError):
        return False
    return 0.0 <= pf <= 1.0


def candidate_reasons(candidate: Mapping[str, Any]) -> set[str]:
    """Return the full ineligibility-reason set ``R_i`` for one candidate.

    Empty set ⇔ forward-outcome-eligible.  A candidate may leak on more than one
    factor (e.g. no ticker *and* no entry price), and every applicable reason is
    reported — nothing is hidden behind a single "first failure".
    """
    reasons: set[str] = set()
    if not ticker_valid(candidate.get("ticker")):
        reasons.add(R_MISSING_TICKER)
    if not candidate.get("has_score_vector", True):
        reasons.add(R_MISSING_SCORE_VECTOR)
    if not _valid_p(candidate.get("model_probability")):
        reasons.add(R_MISSING_PROBABILITY)
    horizon = candidate.get("prediction_horizon_days")
    try:
        if horizon is None or float(horizon) <= 0:
            reasons.add(R_MISSING_HORIZON)
    except (TypeError, ValueError):
        reasons.add(R_MISSING_HORIZON)
    if not is_price_based_target(candidate.get("target_event_definition")):
        reasons.add(R_MISSING_TARGET)
    entry = candidate.get("entry_price")
    try:
        if entry is None or float(entry) <= 0:
            reasons.add(R_MISSING_ENTRY_PRICE)
    except (TypeError, ValueError):
        reasons.add(R_MISSING_ENTRY_PRICE)
    return reasons


def diagnose(candidates: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Compute the full diagnostic table from a list of candidate dicts.

    Each candidate dict carries the resolved fields:
    ``ticker``, ``model_probability``, ``prediction_horizon_days``,
    ``target_event_definition``, ``entry_price``, ``has_score_vector``,
    ``source_name`` and (optional) ``source_type``.  Pure; no I/O.
    """
    cands = list(candidates)
    total = len(cands)

    forward_eligible = 0
    by_source: dict[str, dict[str, int]] = {}
    by_ticker: dict[str, dict[str, int]] = {}
    by_reason: dict[str, int] = {}
    reason_counts = {
        R_MISSING_TICKER: 0, R_MISSING_ENTRY_PRICE: 0, R_MISSING_PROBABILITY: 0,
        R_MISSING_HORIZON: 0, R_MISSING_TARGET: 0, R_MISSING_SCORE_VECTOR: 0,
        R_UNSUPPORTED_SOURCE: 0,
    }
    missing_entry_price_tickers: dict[str, int] = {}
    missing_ticker_sources: dict[str, int] = {}
    missing_probability_sources: dict[str, int] = {}

    for c in cands:
        source = str(c.get("source_name") or "unknown")
        reasons = candidate_reasons(c)
        eligible = not reasons

        src_bucket = by_source.setdefault(source, {"eligible": 0, "ineligible": 0})
        if eligible:
            forward_eligible += 1
            src_bucket["eligible"] += 1
        else:
            src_bucket["ineligible"] += 1

        for r in reasons:
            reason_counts[r] = reason_counts.get(r, 0) + 1
            _bump(by_reason, r)

        # A ticker-bearing candidate missing only its price is the prime target
        # for OHLCV ingestion — track which symbols leak there.
        tkr = c.get("ticker")
        if tkr and R_MISSING_ENTRY_PRICE in reasons and R_MISSING_TICKER not in reasons:
            sym = normalize_symbol(tkr) or str(tkr)
            _bump(missing_entry_price_tickers, sym)
        if R_MISSING_TICKER in reasons:
            _bump(missing_ticker_sources, source)
        if R_MISSING_PROBABILITY in reasons:
            _bump(missing_probability_sources, source)
        if tkr:
            tb = by_ticker.setdefault(normalize_symbol(tkr) or str(tkr),
                                      {"eligible": 0, "ineligible": 0})
            tb["eligible" if eligible else "ineligible"] += 1

    forward_ineligible = total - forward_eligible
    eligibility_rate = round(forward_eligible / max(1, total), 6)

    def _top(d: dict[str, int], n: int = 10) -> list[dict[str, Any]]:
        return [
            {"key": k, "count": v}
            for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
        ]

    return {
        "total_decisions": total,
        "forward_eligible": forward_eligible,
        "forward_ineligible": forward_ineligible,
        "eligibility_rate": eligibility_rate,
        "missing_ticker": reason_counts[R_MISSING_TICKER],
        "missing_entry_price": reason_counts[R_MISSING_ENTRY_PRICE],
        "missing_probability": reason_counts[R_MISSING_PROBABILITY],
        "missing_horizon": reason_counts[R_MISSING_HORIZON],
        "missing_target": reason_counts[R_MISSING_TARGET],
        "missing_score_vector": reason_counts[R_MISSING_SCORE_VECTOR],
        "unsupported_source_type": reason_counts[R_UNSUPPORTED_SOURCE],
        "by_source": by_source,
        "by_ticker": by_ticker,
        "by_reason": by_reason,
        "top_missing_entry_price_tickers": _top(missing_entry_price_tickers),
        "top_missing_ticker_sources": _top(missing_ticker_sources),
        "top_missing_probability_sources": _top(missing_probability_sources),
        # Advisory-only context — never an execution or calibration claim.
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "predictive_claim_allowed": False,
        "edge_claimed": False,
        "calibration_status": "INSUFFICIENT_EVIDENCE",
    }


# --------------------------------------------------------------------------- #
# Candidate builders from the runtime DB (read-only)
# --------------------------------------------------------------------------- #
def build_scored_candidates(
    db_path: Any,
    *,
    decision_timestamp_utc: str | None = None,
    horizon_days: int = DEFAULT_FORWARD_HORIZON_DAYS,
    target_event_definition: str = DEFAULT_TARGET_EVENT_DEFINITION,
) -> list[dict[str, Any]]:
    """Build candidate dicts from the SCORED side-table vectors (the forward
    universe: only complete score vectors can carry a probability).

    Resolves each ticker deterministically (Phase 2) and each entry price from
    real OHLCV (Phase 3).  Read-only; fabricates nothing.
    """
    ensure_score_vector_schema(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM {SCORE_VECTOR_TABLE} WHERE score_status=?", (SCORED,)
        ).fetchall()]
    finally:
        conn.close()

    decision_ts = decision_timestamp_utc
    if decision_ts is None:
        from datetime import datetime, timezone
        decision_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Preload price series for all resolvable symbols (efficient single scan).
    wanted: set[str] = set()
    resolved_cache: dict[str, str | None] = {}
    for r in rows:
        res = resolve_ticker(score_vector={"ticker": r.get("ticker")})["ticker"]
        resolved_cache[r["score_key"]] = res
        sym = normalize_symbol(res) if res else None
        if sym:
            wanted.add(sym)
    series = load_price_series(db_path, symbols=wanted or None)

    candidates: list[dict[str, Any]] = []
    for r in rows:
        ticker = resolved_cache.get(r["score_key"])
        axes = complete_axes_from_row(r)
        has_vector = axes is not None
        p = None
        if axes is not None:
            raw = sum(axes.values()) / len(axes)
            p = compute_model_probability(raw)
        entry_price = None
        if ticker:
            ev = resolve_entry_price(
                db_path, ticker=ticker, decision_timestamp_utc=decision_ts,
                series_by_symbol=series,
            )
            entry_price = ev["entry_price"] if ev else None
        candidates.append({
            "event_id": r.get("event_id"),
            "source_name": r.get("source_name"),
            "ticker": ticker,
            "model_probability": p,
            "has_score_vector": has_vector,
            "prediction_horizon_days": horizon_days,
            "target_event_definition": target_event_definition,
            "entry_price": entry_price,
            "decision_timestamp_utc": decision_ts,
        })
    return candidates


def forward_eligibility_diagnostics(
    *,
    db_path: Any = None,
    candidates: Sequence[Mapping[str, Any]] | None = None,
    decision_timestamp_utc: str | None = None,
) -> dict[str, Any]:
    """Top-level diagnostic.  Uses an explicit ``candidates`` list (tests) or
    builds the scored-vector universe from ``db_path``."""
    if candidates is None:
        target = db_path if db_path is not None else persistence.DB_PATH
        candidates = build_scored_candidates(
            target, decision_timestamp_utc=decision_timestamp_utc
        )
    out = diagnose(candidates)
    out["universe"] = "scored_vectors"
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Forward eligibility diagnostics over scored decision candidates (read-only)."
    )
    p.add_argument("--now", default=None, help="decision timestamp (ISO) for entry-price anchoring")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    persistence.init_schema()
    out = forward_eligibility_diagnostics(decision_timestamp_utc=args.now)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))


def forward_throughput_summary(
    *,
    forward_eligible_before: int,
    forward_eligible_after: int,
    decisions_before: int,
    decisions_after: int,
    reasons_before: Mapping[str, int] | None = None,
    reasons_after: Mapping[str, int] | None = None,
    n_pending_horizon: int = 0,
    n_due_forward: int = 0,
    n_real_forward_pairs: int = 0,
    top_missing_entry_price_tickers: Any = None,
    top_missing_ticker_sources: Any = None,
) -> dict[str, Any]:
    """Compute the honest before/after throughput block for the evidence layer.

    Includes the eligibility gain, per-reason reductions, eligibility rates, and
    how many *real forward pairs* remain before the calibration gate (N>=200)
    could even be considered.  This block can NEVER unlock a predictive claim.
    """
    reasons_before = dict(reasons_before or {})
    reasons_after = dict(reasons_after or {})
    reductions = {
        r: reasons_before.get(r, 0) - reasons_after.get(r, 0)
        for r in set(reasons_before) | set(reasons_after)
    }
    return {
        "forward_eligible_before": forward_eligible_before,
        "forward_eligible_after": forward_eligible_after,
        "eligibility_gain": forward_eligible_after - forward_eligible_before,
        "eligibility_rate_before": round(forward_eligible_before / max(1, decisions_before), 6),
        "eligibility_rate_after": round(forward_eligible_after / max(1, decisions_after), 6),
        "decisions_before": decisions_before,
        "decisions_after": decisions_after,
        "reason_reductions": reductions,
        "n_pending_horizon": n_pending_horizon,
        "n_due_forward": n_due_forward,
        "n_real_forward_pairs": n_real_forward_pairs,
        "n_needed_to_200": max(0, 200 - n_real_forward_pairs),
        "top_missing_entry_price_tickers": top_missing_entry_price_tickers or [],
        "top_missing_ticker_sources": top_missing_ticker_sources or [],
        # Throughput improvement NEVER implies calibration / edge / readiness.
        "predictive_claim_allowed": False,
        "edge_claimed": False,
        "real_money_ready": False,
        "calibration_status": "INSUFFICIENT_EVIDENCE",
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
    }


__all__ = [
    "candidate_reasons",
    "diagnose",
    "build_scored_candidates",
    "forward_eligibility_diagnostics",
    "forward_throughput_summary",
    "main",
]
