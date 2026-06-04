"""Extract OutcomeEvidence from existing persistence records.

Transforms manual trades + reconciliation results (+ Moltbook) into the
canonical outcome-evidence model. It NEVER fabricates prices or returns: when
the evidence does not determine a return, the outcome is left OPEN/UNKNOWN and
marked ineligible.

Extraction precedence per trade:
  1. Reconciliation result with a closed outcome (actual fill + pnl + status)
  2. Manual trade exit fields (none stored today -> falls through)
  3. Moltbook outcome classification (label only, no invented PnL)
  4. Open / record-only -> not calibration eligible

Read-only. No DB writes, no broker calls. Advisory stamps preserved.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts import outcome_evidence as oe
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import outcome_evidence as oe  # type: ignore[no-redef]

_RESOLVED = {"WIN", "LOSS", "BREAKEVEN"}


def _direction_from_side(side: Any) -> str:
    s = str(side or "").upper()
    if s == "BUY":
        return "LONG"
    if s == "SELL":
        return "SHORT"
    return oe.UNKNOWN


def _score_at_entry(trade: dict[str, Any]) -> float | None:
    """Best available proxy for the score the operator acted on.

    Precedence: explicit score_at_entry > reactor decision-grade energy >
    operator confidence_before. None when no proxy exists (honest).
    """
    for key in ("score_at_entry", "decision_grade_energy_at_decision", "confidence_before"):
        v = trade.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def extract_outcomes(
    manual_trades: list[dict[str, Any]],
    reconciliations: list[dict[str, Any]],
    moltbook_entries: list[dict[str, Any]] | None = None,
    *,
    source_type: str = oe.REAL_MANUAL_TRADE,
) -> list[oe.OutcomeEvidence]:
    """Build a deterministic list of OutcomeEvidence from persistence rows.

    ``source_type`` tags the provenance of these rows (REAL_MANUAL_TRADE for
    the live operator journal; tests pass SYNTHETIC_FIXTURE for seeded DBs).
    """
    recon_by_trade: dict[str, dict[str, Any]] = {}
    for r in reconciliations or []:
        tid = str(r.get("trade_id") or "")
        if tid and tid not in recon_by_trade:
            recon_by_trade[tid] = r  # first (latest_first ordering preserved by caller)

    molt_by_event: dict[str, dict[str, Any]] = {}
    for m in moltbook_entries or []:
        eid = str(m.get("event_id") or "")
        if eid and eid not in molt_by_event:
            molt_by_event[eid] = m

    outcomes: list[oe.OutcomeEvidence] = []
    for t in sorted(manual_trades or [], key=lambda x: str(x.get("trade_id") or "")):
        tid = str(t.get("trade_id") or "")
        eid = str(t.get("event_id") or "")
        ticker = str(t.get("ticker") or "")
        direction = _direction_from_side(t.get("side"))
        entry_price = t.get("price")
        leverage = t.get("leverage", 1.0)
        jurisdiction = t.get("jurisdiction_group", oe.UNKNOWN)
        score = _score_at_entry(t)

        exit_price = None
        realized_pnl = None
        label_override = None
        recon = recon_by_trade.get(tid)
        if recon is not None:
            # 1. Reconciliation closed outcome (authoritative).
            status = str(recon.get("outcome_status") or "").upper()
            if status in _RESOLVED:
                label_override = status
            exit_price = recon.get("actual_fill_price")
            realized_pnl = recon.get("pnl_estimate")
        elif eid in molt_by_event:
            # 3. Moltbook classification — label only, no invented PnL.
            status = str(molt_by_event[eid].get("outcome_status") or "").upper()
            if status in _RESOLVED:
                label_override = status
        # else: 4. open/record-only -> stays OPEN, ineligible.

        outcomes.append(
            oe.build_outcome(
                outcome_id=f"OE_{tid}" if tid else f"OE_{eid}",
                source_type=source_type,
                ticker=ticker,
                direction=direction,
                signal_id=eid or None,
                trade_id=tid or None,
                opened_at=t.get("executed_at"),
                closed_at=(recon.get("reconciled_at") if recon else None),
                entry_price=entry_price,
                exit_price=exit_price,
                realized_pnl=realized_pnl,
                leverage=leverage,
                jurisdiction_group=jurisdiction,
                score_at_entry=score,
                archetype=t.get("signal_state") or t.get("archetype"),
                outcome_label_override=label_override,
            )
        )
    return outcomes


def extract_from_db(
    db_path: Path | None = None,
    *,
    source_type: str = oe.REAL_MANUAL_TRADE,
) -> list[oe.OutcomeEvidence]:
    """Read persistence and extract outcomes. Defensive: any failure -> []."""
    try:
        try:
            from scripts import persistence
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            import persistence  # type: ignore[no-redef]
        path = db_path if db_path is not None else persistence.DB_PATH
        trades = persistence.get_all_manual_trades(path)
        recons = persistence.get_all_reconciliations(path)
        molt = []
        if hasattr(persistence, "get_all_moltbook_entries"):
            try:
                molt = persistence.get_all_moltbook_entries(path)
            except Exception:
                molt = []
    except Exception:  # pragma: no cover - defensive
        return []
    return extract_outcomes(trades, recons, molt, source_type=source_type)


__all__ = ["extract_outcomes", "extract_from_db"]
