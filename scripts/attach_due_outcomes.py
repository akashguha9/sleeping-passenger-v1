"""Phase 5 — attach realized outcomes after horizons close (advisory-only).

This is video review: without reviewing duels after the match, the system can
never improve its positioning.  It finds decision snapshots whose prediction
horizon has *elapsed*, attaches a realized binary outcome ``y_i`` to the
``model_probability`` ``p_i`` that was persisted at decision time, and leaves
everything unresolved as *pending*.

Hard honesty rules (all enforced):

* An outcome is attached ONLY when it is real AND the horizon has elapsed.
* An open / unresolved trade is NEVER labelled.
* A decision with no realized-price evidence is left *pending* (or recorded as
  *excluded* with a reason) — never fabricated.
* Only ``real_forward`` eligible pairs grow ``N_real_forward``; historical proxy
  pairs are tracked separately and can never unlock a predictive claim.
* Advisory-only context is preserved: no broker, no order, no execution.

Outcome math (pure helpers reused from ``outcome_labeling_flow``):

    r_i   = (P_exit - P_entry) / P_entry
    r_b_i = (B_exit - B_entry) / B_entry
    alpha = r_i - r_b_i
    y_i   = I(r_i >= target_return_threshold)        (return mode)
          = I(alpha >= alpha_threshold)              (benchmark mode)
          = 1 if target before stop, 0 if stop before target, NULL otherwise
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

try:  # package layout
    from scripts import persistence
    from scripts.decision_probability_snapshot import TABLE, ensure_schema
    from scripts.outcome_labeling_flow import (
        REAL_FORWARD,
        attach_outcome,
        label_alpha_ge_threshold,
        label_return_ge_threshold,
        label_stop_loss_vs_target,
    )
    from scripts.real_calibration_evidence import extract_datasets
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    import persistence  # type: ignore[no-redef]
    from decision_probability_snapshot import TABLE, ensure_schema  # type: ignore[no-redef]
    from outcome_labeling_flow import (  # type: ignore[no-redef]
        REAL_FORWARD,
        attach_outcome,
        label_alpha_ge_threshold,
        label_return_ge_threshold,
        label_stop_loss_vs_target,
    )
    from real_calibration_evidence import extract_datasets  # type: ignore[no-redef]
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

# Reasons a due decision could not be labelled.
REASON_NO_PRICE_EVIDENCE = "NO_PRICE_EVIDENCE"
REASON_MISSING_EXIT_PRICE = "MISSING_EXIT_PRICE"
REASON_MISSING_ENTRY_PRICE = "MISSING_ENTRY_PRICE"
REASON_AMBIGUOUS_OUTCOME = "AMBIGUOUS_OUTCOME_NOT_RESOLVED"
REASON_OPEN_TRADE = "OPEN_TRADE_NOT_RESOLVED"
REASON_MISSING_TARGET_DEFINITION = "MISSING_TARGET_EVENT_DEFINITION"
REASON_MISSING_PROBABILITY = "MISSING_PROBABILITY"

# An evidence provider maps a decision_id -> realized-evidence mapping, or None.
EvidenceProvider = Callable[[str], Mapping[str, Any] | None]


def _valid_probability(p: Any) -> bool:
    try:
        pf = float(p)
    except (TypeError, ValueError):
        return False
    return 0.0 <= pf <= 1.0


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def horizon_elapsed(
    *,
    decision_ts: str | None,
    horizon_days: Any,
    now_utc: datetime,
) -> bool:
    """True when ``decision_ts + horizon_days`` is at/behind ``now_utc``.

    A NULL/zero horizon is treated as *not yet elapsed* unless the decision
    timestamp itself is in the past by any amount — conservatively, a missing
    horizon means we cannot assert the horizon closed, so it stays pending.
    """
    start = _parse_iso(decision_ts)
    if start is None:
        return False
    try:
        days = float(horizon_days)
    except (TypeError, ValueError):
        return False
    if days <= 0:
        return False
    return now_utc >= (start + timedelta(days=days))


def compute_outcome_label(
    evidence: Mapping[str, Any],
    *,
    target_return_threshold: float = 0.0,
    alpha_threshold: float = 0.0,
) -> tuple[int | None, str | None]:
    """Derive ``y`` from realized evidence.  Returns ``(y, reason_or_None)``.

    Resolution order: explicit stop/target ordering -> benchmark alpha ->
    absolute return threshold.  Ambiguous / insufficient evidence -> (None, why).
    """
    # 1. stop / target ordering (most decisive)
    if "stop_loss_hit" in evidence or "target_hit" in evidence:
        y = label_stop_loss_vs_target(
            stop_loss_hit=bool(evidence.get("stop_loss_hit")),
            target_hit=bool(evidence.get("target_hit")),
        )
        if y is not None:
            return y, None
        # both/neither resolved -> fall through to price evidence if present

    entry = evidence.get("entry_price")
    exit_ = evidence.get("exit_price")
    # Distinguish the honest reason: a present entry with a missing exit means the
    # horizon-close price could not be found (MISSING_EXIT_PRICE); a missing entry
    # means no reference price (MISSING_ENTRY_PRICE).
    if entry is not None and exit_ is None:
        return None, REASON_MISSING_EXIT_PRICE
    if entry is None and exit_ is not None:
        return None, REASON_MISSING_ENTRY_PRICE
    if entry is None or exit_ is None:
        return None, REASON_AMBIGUOUS_OUTCOME

    # 2. benchmark-relative alpha when a benchmark path is present
    b_entry = evidence.get("benchmark_entry")
    b_exit = evidence.get("benchmark_exit")
    if b_entry is not None and b_exit is not None:
        try:
            y = label_alpha_ge_threshold(
                float(entry), float(exit_), float(b_entry), float(b_exit),
                float(evidence.get("alpha_threshold", alpha_threshold)),
            )
            return int(y), None
        except (ValueError, ZeroDivisionError):
            return None, REASON_NO_PRICE_EVIDENCE

    # 3. absolute return threshold
    try:
        y = label_return_ge_threshold(
            float(entry), float(exit_),
            float(evidence.get("target_return_threshold", target_return_threshold)),
        )
        return int(y), None
    except (ValueError, ZeroDivisionError):
        return None, REASON_NO_PRICE_EVIDENCE


def _due_snapshots(db_path: Any, now_utc: datetime) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        # ``target_return_threshold`` is a forward-contract column (added by the
        # additive migration); tolerate its absence on legacy DBs.
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({TABLE})")}
        thr_col = "target_return_threshold" if "target_return_threshold" in cols else "NULL AS target_return_threshold"
        rows = conn.execute(
            f"SELECT snapshot_id, timestamp_utc, prediction_horizon_days,"
            f" model_probability, target_event_definition, outcome_label,"
            f" {thr_col} FROM {TABLE}"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _n_real_forward(db_path: Any) -> int:
    return len(extract_datasets(db_path)["real_forward"])


def _is_blank_target(target_event_definition: Any) -> bool:
    """A decision with no usable target-event definition cannot be labelled."""
    text = str(target_event_definition or "").strip()
    return text == ""


def attach_due_outcomes(
    *,
    db_path: Any = None,
    evidence_provider: EvidenceProvider | None = None,
    evidence_by_id: Mapping[str, Mapping[str, Any]] | None = None,
    now_utc: str | None = None,
    target_return_threshold: float = 0.0,
    alpha_threshold: float = 0.0,
    use_real_price_evidence: bool = False,
    benchmark_symbol: str | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Attach realized outcomes to decisions whose horizon has elapsed.

    ``evidence_provider`` (or ``evidence_by_id``) supplies realized-price
    evidence per decision_id.  When ``use_real_price_evidence`` is set and no
    explicit provider/map is given, a real-OHLCV provider is built from the
    ingested ``market_data`` bars (see ``real_price_outcome_evidence``).

    A decision with no evidence stays *excluded* (``NO_PRICE_EVIDENCE``); an open
    trade stays *pending*; a snapshot with no target-event definition is
    *excluded* (``MISSING_TARGET_EVENT_DEFINITION``); one carrying no usable
    probability is recorded but never counts toward the gate.  Nothing is ever
    fabricated.
    """
    stamps = advisory_safety_stamps()
    target = db_path if db_path is not None else persistence.DB_PATH
    now_dt = _parse_iso(now_utc) or datetime.now(timezone.utc)

    if evidence_by_id is not None and evidence_provider is None:
        def evidence_provider(did: str):  # type: ignore[misc]
            return evidence_by_id.get(did)

    # Default real-price provider: read real OHLCV entry/exit bars.  Opt-in so
    # the deterministic offline tests keep supplying their own evidence map.
    if evidence_provider is None and use_real_price_evidence:
        try:  # local import to avoid a hard dependency cycle
            try:
                from scripts.real_price_outcome_evidence import (
                    make_real_price_evidence_provider,
                )
            except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
                from real_price_outcome_evidence import (  # type: ignore[no-redef]
                    make_real_price_evidence_provider,
                )
            evidence_provider = make_real_price_evidence_provider(
                target, now_utc=now_utc, benchmark_symbol=benchmark_symbol,
            )
        except Exception:  # pragma: no cover - never crash the loop
            evidence_provider = None

    n_before = _n_real_forward(target)

    snapshots = _due_snapshots(target, now_dt)
    snapshots_seen = len(snapshots)
    due_decisions = 0
    outcomes_attached = 0
    pending = 0
    pending_horizon = 0
    excluded = 0
    excluded_missing_price = 0
    excluded_missing_exit_price = 0
    excluded_missing_target_definition = 0
    excluded_missing_probability = 0
    details: list[dict[str, Any]] = []

    for snap in snapshots:
        did = snap["snapshot_id"]
        # Already labelled -> skip (idempotent).
        if snap.get("outcome_label") is not None:
            continue
        elapsed = horizon_elapsed(
            decision_ts=snap.get("timestamp_utc"),
            horizon_days=snap.get("prediction_horizon_days"),
            now_utc=now_dt,
        )
        if not elapsed:
            pending += 1
            pending_horizon += 1
            continue

        due_decisions += 1

        # A due decision with no target-event definition cannot be labelled.
        if _is_blank_target(snap.get("target_event_definition")):
            excluded += 1
            excluded_missing_target_definition += 1
            details.append({"decision_id": did, "status": "EXCLUDED",
                            "reason": REASON_MISSING_TARGET_DEFINITION})
            continue

        evidence = evidence_provider(did) if evidence_provider else None
        if not evidence:
            # Horizon elapsed but no realized-price evidence -> excluded with a
            # reason (it cannot be labelled), never silently pending-forever.
            excluded += 1
            excluded_missing_price += 1
            details.append({"decision_id": did, "status": "EXCLUDED",
                            "reason": REASON_NO_PRICE_EVIDENCE})
            continue

        # Open / unresolved trades are NEVER labelled -> genuinely pending.
        if bool(evidence.get("trade_open")):
            pending += 1
            details.append({"decision_id": did, "status": "PENDING",
                            "reason": REASON_OPEN_TRADE})
            continue

        # No usable probability at decision time -> recorded honestly but it can
        # never count toward the real-forward gate.
        if not _valid_probability(snap.get("model_probability")):
            excluded_missing_probability += 1

        # Prefer the per-snapshot persisted target_return_threshold (the forward
        # contract default is 0.0) over the batch-wide default.
        snap_threshold = snap.get("target_return_threshold")
        eff_threshold = (
            float(snap_threshold) if snap_threshold is not None else target_return_threshold
        )
        y, reason = compute_outcome_label(
            evidence,
            target_return_threshold=eff_threshold,
            alpha_threshold=alpha_threshold,
        )
        if y is None:
            excluded += 1
            if reason == REASON_MISSING_EXIT_PRICE:
                excluded_missing_exit_price += 1
            else:
                excluded_missing_price += 1
            details.append({"decision_id": did, "status": "EXCLUDED",
                            "reason": reason or REASON_NO_PRICE_EVIDENCE})
            continue

        if not write:
            outcomes_attached += 1
            details.append({"decision_id": did, "status": "WOULD_ATTACH", "y": y})
            continue

        res = attach_outcome(
            target,
            did,
            y,
            outcome_timestamp=evidence.get("outcome_timestamp"),
            outcome_source=str(evidence.get("outcome_source", "realized_price_evidence")),
            is_real_outcome=bool(evidence.get("is_real_outcome", True)),
            outcome_kind=str(evidence.get("outcome_kind", REAL_FORWARD)),
            horizon_elapsed=True,
            trade_open=False,
            now_utc=now_utc,
        )
        if res.get("attached"):
            outcomes_attached += 1
            details.append({"decision_id": did, "status": "ATTACHED", "y": y,
                            "calibration_eligible": res.get("calibration_eligible")})
        else:
            excluded += 1
            excluded_missing_price += 1
            details.append({"decision_id": did, "status": "EXCLUDED",
                            "reason": res.get("reason")})

    n_after = _n_real_forward(target) if write else n_before
    out = {
        "snapshots_seen": snapshots_seen,
        "due_decisions": due_decisions,
        "outcomes_attached": outcomes_attached,
        "pending": pending,
        "pending_horizon": pending_horizon,
        "excluded": excluded,
        "excluded_missing_price": excluded_missing_price,
        "excluded_missing_exit_price": excluded_missing_exit_price,
        "excluded_missing_target_definition": excluded_missing_target_definition,
        "excluded_missing_probability": excluded_missing_probability,
        "n_real_forward_before": n_before,
        "n_real_forward_after": n_after,
        "delta_n_real_forward": n_after - n_before,
        "details": details,
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
        description="Attach realized outcomes after horizons close (advisory-only)."
    )
    p.add_argument("--target-return-threshold", type=float, default=0.0)
    p.add_argument("--alpha-threshold", type=float, default=0.0)
    p.add_argument(
        "--evidence-json",
        default=None,
        help="optional path to a JSON map of decision_id -> realized evidence",
    )
    p.add_argument(
        "--real-price-evidence",
        action="store_true",
        help="attach outcomes from real ingested OHLCV bars (market_data) when "
        "no explicit evidence map is supplied",
    )
    p.add_argument("--benchmark-symbol", default=None)
    p.add_argument("--write", action="store_true")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    persistence.init_schema()
    evidence_by_id: dict[str, Any] | None = None
    if args.evidence_json:
        path = Path(args.evidence_json)
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    evidence_by_id = loaded
            except (OSError, json.JSONDecodeError):
                evidence_by_id = None
    summary = attach_due_outcomes(
        evidence_by_id=evidence_by_id,
        target_return_threshold=args.target_return_threshold,
        alpha_threshold=args.alpha_threshold,
        use_real_price_evidence=bool(args.real_price_evidence),
        benchmark_symbol=args.benchmark_symbol,
        write=bool(args.write),
    )
    # Print without the per-decision details (which could be large).
    printable = {k: v for k, v in summary.items() if k != "details"}
    print(json.dumps(printable, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))


__all__ = [
    "REASON_NO_PRICE_EVIDENCE",
    "REASON_MISSING_EXIT_PRICE",
    "REASON_MISSING_ENTRY_PRICE",
    "REASON_AMBIGUOUS_OUTCOME",
    "REASON_OPEN_TRADE",
    "REASON_MISSING_TARGET_DEFINITION",
    "REASON_MISSING_PROBABILITY",
    "horizon_elapsed",
    "compute_outcome_label",
    "attach_due_outcomes",
    "main",
]
