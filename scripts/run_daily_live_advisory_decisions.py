"""Phase 4 — daily live advisory decision batch (advisory-only).

Turns fresh canonical ``signal_events`` into persisted
``decision_probability_snapshots`` by running each one through the single,
already-tested orchestrator :func:`scripts.live_decision_path.run_live_decision_path`.
This is how ``n_valid_p`` actually grows in the runtime DB — one interception is
noise; daily pressure builds the dataset.

It is ADVISORY-ONLY by construction:

* it never calls a broker, never places an order, never executes a trade;
* every decision spreads the advisory safety stamps (``execution_gate=LOCKED``,
  ``broker_api_called=False``, ``ai_execution_count=0``);
* ``predictive_claim_allowed`` stays ``False`` — this batch only persists
  probabilities at decision time, it never claims calibration.

A decision contributes to ``n_valid_p`` only when a model_probability in [0,1]
was actually produced at decision time:

    ValidP_d = I(model_probability_d is not NULL) · I(0 <= model_probability_d <= 1)

A signal event carries a usable score vector from one of two honest sources, in
priority order:

  1. the persisted ``signal_event_score_vectors`` side table (Phase 4) — the
     real-row scorer wrote a CompleteScore vector keyed by ``event_id``; OR
  2. the event's own ``raw_payload`` exposing the six axes (legacy / fixture
     path) under ``axes`` / ``score_vector`` or as top-level keys.

A side-table vector that exists but is *incomplete* (status != SCORED or an axis
out of range) yields ``model_probability = NULL`` with reason
``SCORE_VECTOR_INCOMPLETE`` — it is never overridden by a fabricated value.  An
event with neither a side-table vector nor payload axes yields NULL with reason
``SCORE_VECTOR_MISSING``.  Events with a NULL probability are still *recorded*
(honest audit) but never count toward ``n_valid_p``.

When there are no fresh canonical rows, ``decisions_recorded`` is 0 and the
summary reports ``reason = "NO_FRESH_CANONICAL_ROWS"`` rather than pretending.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterable, Mapping, Sequence

try:  # package layout
    from scripts import persistence
    from scripts.live_decision_path import run_live_decision_path
    from scripts.decision_probability_snapshot import count_valid_p
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.score_real_signal_events import (
        complete_axes_from_row,
        count_score_vectors,
        lookup_score_vector,
    )
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    import persistence  # type: ignore[no-redef]
    from live_decision_path import run_live_decision_path  # type: ignore[no-redef]
    from decision_probability_snapshot import count_valid_p  # type: ignore[no-redef]
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from score_real_signal_events import (  # type: ignore[no-redef]
        complete_axes_from_row,
        count_score_vectors,
        lookup_score_vector,
    )

NO_FRESH_ROWS = "NO_FRESH_CANONICAL_ROWS"

# Honest reasons for a NULL model_probability at decision time.
SCORE_VECTOR_MISSING = "SCORE_VECTOR_MISSING"
SCORE_VECTOR_INCOMPLETE = "SCORE_VECTOR_INCOMPLETE"

# The six advisory score axes the probability snapshot consumes.
_AXES_KEYS = ("EMS", "EQS", "DS", "LS", "EFS", "APS")


def _coerce_axes(blob: Mapping[str, Any]) -> dict[str, float] | None:
    """Return a usable axes dict from a mapping, or None when incomplete."""
    out: dict[str, float] = {}
    for k in _AXES_KEYS:
        if k not in blob:
            return None
        try:
            out[k] = float(blob[k])
        except (TypeError, ValueError):
            return None
    return out


def extract_axes(payload: Any) -> dict[str, float] | None:
    """Extract the advisory score vector from a signal_event raw_payload.

    Looks under ``axes`` / ``score_vector`` first, then top-level keys.  Returns
    ``None`` when no complete six-axis vector is present — the caller then
    records the decision with a NULL model_probability (never fabricated).
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(payload, Mapping):
        return None
    for key in ("axes", "score_vector"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            axes = _coerce_axes(nested)
            if axes is not None:
                return axes
    return _coerce_axes(payload)


def resolve_decision_axes(
    *,
    event_id: str,
    payload: Any,
    lookup_db: Any,
) -> tuple[dict[str, float] | None, str, str]:
    """Resolve the score vector for one event, honestly.

    Returns ``(axes_or_none, score_vector_source, reason)`` where
    ``score_vector_source`` is one of ``"SCORE_VECTOR"`` (complete side-table
    vector), ``"PAYLOAD_AXES"`` (legacy / fixture), ``"INCOMPLETE"`` or
    ``"MISSING"``.  Side-table truth wins; an incomplete side-table vector is
    NEVER overridden by payload axes — it stays NULL with an explicit reason.
    """
    side_row = None
    if event_id and lookup_db is not None:
        try:
            side_row = lookup_score_vector(lookup_db, event_id)
        except Exception:  # pragma: no cover - defensive; never crash the batch
            side_row = None

    if side_row is not None:
        axes = complete_axes_from_row(side_row)
        if axes is not None:
            return axes, "SCORE_VECTOR", "OK"
        # A persisted-but-incomplete vector is honestly NULL, no fallback.
        return None, "INCOMPLETE", SCORE_VECTOR_INCOMPLETE

    # No side-table vector — fall back to payload-embedded axes (legacy path).
    payload_axes = extract_axes(payload)
    if payload_axes is not None:
        return payload_axes, "PAYLOAD_AXES", "OK"
    return None, "MISSING", SCORE_VECTOR_MISSING


def _classify_blocks(decision: Mapping[str, Any]) -> dict[str, bool]:
    """Classify why a single decision did not promote to advisory-candidate."""
    blocked = [str(r).lower() for r in
               (decision.get("gate_result", {}) or {}).get("blocked_by", [])]
    capacity_status = str(decision.get("capacity_status") or "")
    by_freshness = any("freshness" in r or "stale" in r for r in blocked)
    by_capacity = (
        capacity_status not in ("CAPACITY_OK", "")
        or any("capacity" in r for r in blocked)
    )
    by_moltbook = bool(decision.get("moltbook_downgraded")) or any(
        "moltbook" in r for r in blocked
    )
    return {
        "freshness": by_freshness,
        "capacity": by_capacity,
        "moltbook": by_moltbook,
    }


def run_daily_decision_batch(
    *,
    db_path: Any = None,
    events: Iterable[Mapping[str, Any]] | None = None,
    source_names: Sequence[str] | None = None,
    ttl_hours: float = 24.0,
    max_decisions: int = 50,
    now_iso: str | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Run the advisory decision path over fresh canonical signal events.

    ``events`` (when provided) bypass the DB read for deterministic offline
    tests.  ``write=False`` (or ``db_path=None``) makes every decision
    side-effect free (snapshots are built but never persisted).
    """
    stamps = advisory_safety_stamps()
    target = db_path if db_path is not None else persistence.DB_PATH
    persist_db = target if write else None

    n_valid_p_before = count_valid_p(target) if write else 0

    # ----- resolve the fresh canonical rows ------------------------------- #
    if events is None:
        rows = persistence.get_signal_events(limit=max(1, max_decisions), db_path=target)
        # Keep only rows fresh within the TTL window.
        fresh: list[dict[str, Any]] = []
        for r in rows:
            ev_source = r.get("source_name")
            stats = persistence.count_fresh_signal_events_by_source(
                ev_source or "", ttl_hours=ttl_hours, now_iso=now_iso, db_path=target
            ) if ev_source else {"latest_age_hours": None}
            age = stats.get("latest_age_hours")
            if age is not None and age <= ttl_hours:
                fresh.append(r)
        event_rows = fresh[:max_decisions]
    else:
        event_rows = [dict(e) for e in events][:max_decisions]

    # Total CompleteScore vectors available in the side table (honest context).
    try:
        scored_rows_available = count_score_vectors(target, complete_only=True)
    except Exception:  # pragma: no cover - defensive
        scored_rows_available = 0

    decisions_attempted = len(event_rows)
    decisions_recorded = 0
    valid_p_added = 0
    blocked_by_freshness = 0
    blocked_by_capacity = 0
    blocked_by_moltbook = 0
    decisions_with_score_vector = 0
    decisions_missing_score_vector = 0
    decisions_incomplete_score_vector = 0
    probability_unavailable_reasons: dict[str, int] = {}

    if decisions_attempted == 0:
        out = {
            "decisions_attempted": 0,
            "decisions_recorded": 0,
            "n_valid_p_before": n_valid_p_before,
            "n_valid_p_after": n_valid_p_before,
            "delta_n_valid_p": 0,
            "scored_rows_available": scored_rows_available,
            "decisions_with_score_vector": 0,
            "decisions_missing_score_vector": 0,
            "decisions_incomplete_score_vector": 0,
            "probability_unavailable_reasons": {},
            "blocked_by_freshness": 0,
            "blocked_by_capacity": 0,
            "blocked_by_moltbook": 0,
            "reason": NO_FRESH_ROWS,
            "calibration_status": "INSUFFICIENT_EVIDENCE",
            "predictive_claim_allowed": False,
        }
        out.update(stamps)
        out["advisory_only"] = True
        out["human_execution_required"] = True
        return out

    for i, row in enumerate(event_rows):
        payload = row.get("raw_payload", row)
        signal_id = str(row.get("event_id") or row.get("signal_id") or f"DAILY_{i}")
        ticker = row.get("ticker") if isinstance(row, Mapping) else None
        country = row.get("country") if isinstance(row, Mapping) else None

        # Primary: persisted side-table score vector; fallback: payload axes.
        axes, vector_source, axes_reason = resolve_decision_axes(
            event_id=signal_id, payload=payload, lookup_db=target,
        )
        if vector_source == "SCORE_VECTOR":
            decisions_with_score_vector += 1
        elif vector_source == "INCOMPLETE":
            decisions_incomplete_score_vector += 1
        elif vector_source == "MISSING":
            decisions_missing_score_vector += 1
        # PAYLOAD_AXES rows have no side-table vector but still carry axes; they
        # are counted as "missing side-table vector" for honest accounting.
        if vector_source == "PAYLOAD_AXES":
            decisions_missing_score_vector += 1

        if axes is None and axes_reason in (SCORE_VECTOR_MISSING, SCORE_VECTOR_INCOMPLETE):
            probability_unavailable_reasons[axes_reason] = (
                probability_unavailable_reasons.get(axes_reason, 0) + 1
            )

        decision = run_live_decision_path(
            signal_id=signal_id,
            axes=axes,
            ticker=ticker,
            country=country,
            api_health_status="OK",
            rows_added=1,
            canonical_age_hours=0.0,
            ttl_hours=ttl_hours,
            db_path=persist_db,
        )
        decisions_recorded += 1
        mp = decision.get("model_probability")
        if mp is not None and 0.0 <= float(mp) <= 1.0:
            valid_p_added += 1
        blocks = _classify_blocks(decision)
        blocked_by_freshness += int(blocks["freshness"])
        blocked_by_capacity += int(blocks["capacity"])
        blocked_by_moltbook += int(blocks["moltbook"])

    n_valid_p_after = count_valid_p(target) if write else n_valid_p_before + valid_p_added
    out = {
        "decisions_attempted": decisions_attempted,
        "decisions_recorded": decisions_recorded,
        "n_valid_p_before": n_valid_p_before,
        "n_valid_p_after": n_valid_p_after,
        "delta_n_valid_p": n_valid_p_after - n_valid_p_before,
        "valid_p_added_this_batch": valid_p_added,
        "scored_rows_available": scored_rows_available,
        "decisions_with_score_vector": decisions_with_score_vector,
        "decisions_missing_score_vector": decisions_missing_score_vector,
        "decisions_incomplete_score_vector": decisions_incomplete_score_vector,
        "probability_unavailable_reasons": probability_unavailable_reasons,
        "blocked_by_freshness": blocked_by_freshness,
        "blocked_by_capacity": blocked_by_capacity,
        "blocked_by_moltbook": blocked_by_moltbook,
        "reason": "OK",
        # This batch persists decision-time probabilities only; it never claims
        # calibration.  The gate stays locked until N>=200 with Brier/ECE pass.
        "calibration_status": "INSUFFICIENT_EVIDENCE",
        "predictive_claim_allowed": False,
    }
    out.update(stamps)
    out["advisory_only"] = True
    out["human_execution_required"] = True
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Daily live advisory decision batch (advisory-only, read-then-record)."
    )
    p.add_argument("--max-decisions", type=int, default=50)
    p.add_argument("--ttl-hours", type=float, default=24.0)
    p.add_argument("--write", action="store_true", help="persist decision snapshots")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    persistence.init_schema()
    summary = run_daily_decision_batch(
        max_decisions=args.max_decisions,
        ttl_hours=args.ttl_hours,
        write=bool(args.write),
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))


__all__ = [
    "NO_FRESH_ROWS",
    "SCORE_VECTOR_MISSING",
    "SCORE_VECTOR_INCOMPLETE",
    "extract_axes",
    "resolve_decision_axes",
    "run_daily_decision_batch",
    "main",
]
