"""
Reconciliation-loss → Moltbook bridge.

Turns a *closed losing* manual trade (a row in ``reconciliation_results``
whose outcome is a loss) into exactly ONE advisory-only Moltbook learning
entry.  This is the honest replacement for the fake/demo Moltbook seed rows
that previously polluted the runtime DB: every entry created here is derived
from real, operator-entered reconciliation data — never invented.

Contract
--------
- SQLite (``moltbook_entries``) is canonical.  JSONL is an audit mirror.
- One Moltbook entry per closed losing trade.  Re-running is idempotent
  (dedup by manual_trade_log_id → reconciliation_id → ticker+close+pnl+exit).
- Winning / flat / open / unreconciled trades are NEVER turned into mistake
  entries.
- Missing close / P&L data degrades to "insufficient data" (no entry); P/L
  is never invented.
- Every created entry preserves:
    advisory_status      = ADVISORY_ONLY
    execution_mode       = HUMAN_ONLY
    human_review_required = True
    ai_execution_count   = 0
- This module NEVER places, modifies, or cancels a broker order.

Usage
-----
    python scripts/moltbook_reconciliation_bridge.py            # dry-run
    python scripts/moltbook_reconciliation_bridge.py --write    # create entries
    python scripts/moltbook_reconciliation_bridge.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import utc_timestamp, append_jsonl
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_common import utc_timestamp, append_jsonl  # type: ignore[no-redef]

try:
    import scripts.persistence as _persistence
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import persistence as _persistence  # type: ignore[no-redef]

try:
    import scripts.moltbook_api as _moltbook_api
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import moltbook_api as _moltbook_api  # type: ignore[no-redef]

try:
    from scripts.manual_trade_origin import is_user_manual_trade
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from manual_trade_origin import is_user_manual_trade  # type: ignore[no-redef]


# Outcome labels that explicitly mean "this position closed at a loss".
_LOSS_STATUS = {"LOSS", "CLOSED_LOSS", "STOP_LOSS", "LOSING"}
# Outcome labels that explicitly mean NOT a loss — guards against ever
# turning a win/flat row into a mistake entry.
_NON_LOSS_STATUS = {"WIN", "PROFIT", "FLAT", "BREAKEVEN", "SCRATCH", "GAIN"}

_EXTRAS_RE = re.compile(r"\[reconciliation_extras=(\{.*\})\]", re.DOTALL)

_AI_INTERPRETATION_BASE = (
    "Advisory-only review of a closed losing trade. This entry records the "
    "human's exit for learning; it does not assert the original signal was "
    "correct or incorrect and authorizes no execution."
)

_CONSERVATIVE_REFLECTION = (
    "Closed at a loss. Human review required — no separate reflection was "
    "captured at exit."
)

_CONSERVATIVE_LESSON = (
    "Review why this trade closed at a loss: confirm position sizing, "
    "invalidation discipline, and whether the thesis was invalidated before "
    "exit."
)

_RECALIBRATION_NOTE = (
    "Correction candidate only — not auto-applied. Requires human "
    "confirmation before any rule or threshold change."
)


def _default_db_path() -> Path:
    try:
        return Path(_persistence.DB_PATH)
    except Exception:  # pragma: no cover
        return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


def _parse_extras(outcome_notes: str) -> dict[str, Any]:
    """Extract the structured reconciliation_extras JSON if present."""
    if not outcome_notes:
        return {}
    m = _EXTRAS_RE.search(outcome_notes)
    if not m:
        return {}
    try:
        parsed = json.loads(m.group(1))
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_loss(outcome_status: str, extras: dict[str, Any]) -> bool:
    status = (outcome_status or "").strip().upper()
    if status in _NON_LOSS_STATUS:
        return False
    if status in _LOSS_STATUS:
        return True
    post = str(extras.get("post_trade_outcome") or "").strip().upper()
    if post in _NON_LOSS_STATUS:
        return False
    return "LOSS" in post


def _classify_mistake_type(extras: dict[str, Any], outcome_status: str) -> str:
    """Pick a loss-review mistake_type from available, structured fields only.

    We deliberately do NOT parse free-text ``exit_reason`` to decide stop-loss
    breach: a real exit note can say "...not a stop-loss breach", which a naive
    substring match would invert.  Structured flags are the source of truth:
      - ``stop_loss_hit`` True               → stop_loss_breach
      - ``post_trade_outcome`` contains STOP  → stop_loss_breach
      - ``post_trade_outcome`` CLOSED_LOSS / empty → manual_exit_loss
      - otherwise                             → trade_loss
    """
    if bool(extras.get("stop_loss_hit")):
        return "stop_loss_breach"
    post = str(extras.get("post_trade_outcome") or "").strip().upper()
    if "STOP" in post:
        return "stop_loss_breach"
    if "CLOSED_LOSS" in post or post == "":
        return "manual_exit_loss"
    return "trade_loss"


def _build_outcome_text(
    *,
    realized_pnl: float | None,
    entry_price: float | None,
    exit_price: float | None,
    quantity: float | None,
    side: str,
    reconciled_at: str,
) -> str:
    """Honest realized-outcome string built only from values we actually have."""
    parts: list[str] = []
    if realized_pnl is not None:
        parts.append(f"Realized P/L {realized_pnl:g}")
    if entry_price is not None and exit_price is not None:
        pct: float | None = None
        if entry_price:
            raw = (exit_price - entry_price) / entry_price * 100.0
            pct = -raw if side.upper() in {"SELL", "SHORT"} else raw
        seg = f"entry {entry_price:g} -> exit {exit_price:g}"
        if pct is not None:
            seg += f" ({pct:+.2f}%)"
        parts.append(seg)
    if quantity is not None:
        parts.append(f"qty {quantity:g}")
    if reconciled_at:
        parts.append(f"closed {reconciled_at}")
    return "Closed at a loss. " + "; ".join(parts) if parts else "Closed at a loss."


def build_entry_kwargs(trade: dict[str, Any], rec: dict[str, Any]) -> dict[str, Any] | None:
    """Derive Moltbook entry kwargs from a trade + its loss reconciliation.

    Returns ``None`` when the data is insufficient to honestly describe a
    loss (no realized P/L and no entry/exit prices) — the caller treats
    that as "insufficient data → no entry".
    """
    # Provenance gate: only trades the operator actually entered through the
    # Manual Trade Log become learning entries.  Probe/seed/import rows
    # (e.g. event_id='EV_REC', thesis='t', created_via='') are excluded by
    # the same canonical classifier the Reconciliation queue uses.
    if not is_user_manual_trade(trade):
        return None

    extras = _parse_extras(str(rec.get("outcome_notes") or ""))
    if not _is_loss(str(rec.get("outcome_status") or ""), extras):
        return None

    realized_pnl = _coerce_float(rec.get("pnl_estimate"))
    if realized_pnl is not None and realized_pnl == 0.0:
        # A 0.0 "loss" is contradictory; fall back to extras realized_pnl.
        realized_pnl = _coerce_float(extras.get("realized_pnl"))
    if realized_pnl is None:
        realized_pnl = _coerce_float(extras.get("realized_pnl"))

    entry_price = _coerce_float(extras.get("entry_price")) or _coerce_float(trade.get("price"))
    exit_price = (
        _coerce_float(extras.get("actual_exit_price"))
        or _coerce_float(extras.get("fill_price"))
        or _coerce_float(rec.get("actual_fill_price"))
    )

    # Insufficient-data guard: never invent P/L.  We need either a real
    # realized P/L (non-zero) or a real entry+exit price pair.
    has_pnl = realized_pnl is not None and realized_pnl != 0.0
    has_prices = bool(entry_price and exit_price)
    if not (has_pnl or has_prices):
        return None

    quantity = _coerce_float(extras.get("exit_quantity")) or _coerce_float(trade.get("quantity"))
    side = str(trade.get("side") or "")
    reconciled_at = str(rec.get("reconciled_at") or "")

    mistake_type = _classify_mistake_type(extras, str(rec.get("outcome_status") or ""))

    thesis = str(trade.get("thesis") or "").strip() or "Manual trade loss review"
    exit_reason = str(extras.get("exit_reason") or "").strip()
    ai_interpretation = _AI_INTERPRETATION_BASE
    if exit_reason:
        ai_interpretation += f" Exit reason (operator-entered): {exit_reason}"

    lesson_text = str(extras.get("lesson_takeaway") or rec.get("lesson") or "").strip()
    lesson_learned = lesson_text or _CONSERVATIVE_LESSON
    # user_reflection: no dedicated reflection is captured at reconcile time,
    # so degrade to a conservative placeholder that demands human review.
    user_reflection = _CONSERVATIVE_REFLECTION

    post = str(extras.get("post_trade_outcome") or "").strip()
    if mistake_type == "stop_loss_breach":
        final_decision = "Stop-loss breach — position closed at a loss"
    else:
        final_decision = "Manual exit — closed at a loss"
    if post:
        final_decision += f" ({post})"

    outcome_text = _build_outcome_text(
        realized_pnl=realized_pnl,
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=quantity,
        side=side,
        reconciled_at=reconciled_at,
    )

    return {
        "event_id": str(trade.get("event_id") or rec.get("event_id") or ""),
        "ticker": str(trade.get("ticker") or "").upper(),
        "original_signal_thesis": thesis,
        "ai_interpretation": ai_interpretation,
        "user_reflection": user_reflection,
        "final_human_decision": final_decision,
        "manual_trade_log_id": str(trade.get("trade_id") or ""),
        "outcome": outcome_text,
        "mistake_type": mistake_type,
        "lesson_learned": lesson_learned,
        "bias_detected": "",
        "recalibration_note": _RECALIBRATION_NOTE,
        "future_rule_update": "",
        # carried for dedup, stripped before insert
        "_reconciliation_id": str(rec.get("reconciliation_id") or ""),
        "_close_date": reconciled_at,
        "_realized_pnl": realized_pnl,
    }


def _dedup_keys(existing: list[dict[str, Any]]) -> tuple[set[str], set[str], set[str]]:
    """Build the three dedup index sets from existing Moltbook rows."""
    by_trade: set[str] = set()
    by_event: set[str] = set()
    by_composite: set[str] = set()
    for row in existing:
        mtl = str(row.get("manual_trade_log_id") or "").strip()
        if mtl:
            by_trade.add(mtl)
        ev = str(row.get("event_id") or "").strip()
        if ev:
            by_event.add(ev)
        # composite: ticker|close|pnl|exit — parsed from outcome text is
        # lossy, so we key on event_id+ticker which is stable for our entries.
        tkr = str(row.get("ticker") or "").strip().upper()
        if ev or tkr:
            by_composite.add(f"{tkr}|{ev}")
    return by_trade, by_event, by_composite


def _is_duplicate(
    kwargs: dict[str, Any],
    by_trade: set[str],
    by_event: set[str],
    by_composite: set[str],
) -> bool:
    mtl = str(kwargs.get("manual_trade_log_id") or "").strip()
    if mtl and mtl in by_trade:
        return True
    rec_id = str(kwargs.get("_reconciliation_id") or "").strip()
    if rec_id and rec_id in by_event:  # entries may key event_id to rec id elsewhere
        return True
    ev = str(kwargs.get("event_id") or "").strip()
    if ev and ev in by_event:
        return True
    composite = f"{str(kwargs.get('ticker') or '').upper()}|{ev}"
    if composite in by_composite:
        return True
    return False


def _read_loss_candidates(db_path: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Read (trade, reconciliation) pairs for reconciled trades, read-only."""
    if not db_path.exists():
        return []
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    try:
        rec_rows = conn.execute(
            "SELECT * FROM reconciliation_results ORDER BY reconciled_at ASC"
        ).fetchall()
        for rec in rec_rows:
            rec_d = dict(rec)
            trade = conn.execute(
                "SELECT * FROM manual_trades WHERE trade_id=?",
                (rec_d.get("trade_id"),),
            ).fetchone()
            trade_d = dict(trade) if trade else {"trade_id": rec_d.get("trade_id"),
                                                 "event_id": rec_d.get("event_id")}
            pairs.append((trade_d, rec_d))
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return pairs


def sync_reconciliation_losses_to_moltbook(
    db_path: Path | None = None,
    *,
    write: bool = False,
    jsonl_path: Path | None = None,
) -> dict[str, Any]:
    """Create one advisory Moltbook entry per closed losing trade.

    Read-only unless ``write=True``.  Idempotent.
    """
    path = Path(db_path) if db_path is not None else _default_db_path()
    report: dict[str, Any] = {
        "operation": "moltbook_reconciliation_bridge",
        "db_path": str(path),
        "db_exists": path.exists(),
        "applied": bool(write),
        "loss_candidates": 0,
        "created": 0,
        "skipped_duplicate": 0,
        "skipped_insufficient_data": 0,
        "created_entries": [],
        "advisory_status": "ADVISORY_ONLY",
        "execution_mode": "HUMAN_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_review_required": True,
        "generated_at": utc_timestamp(),
    }
    if not path.exists():
        report["warning"] = "db_missing"
        return report

    pairs = _read_loss_candidates(path)
    try:
        existing = _persistence.get_moltbook_entries(db_path=path)
    except Exception:
        existing = []
    by_trade, by_event, by_composite = _dedup_keys(existing)

    for trade, rec in pairs:
        kwargs = build_entry_kwargs(trade, rec)
        if kwargs is None:
            # None means one of: not a loss, excluded provenance, or
            # insufficient data.  Only count insufficient-data for real
            # user-manual losses so the operator sees genuinely degraded rows
            # (not seed/probe rows, which are simply out of scope).
            extras = _parse_extras(str(rec.get("outcome_notes") or ""))
            if is_user_manual_trade(trade) and _is_loss(
                str(rec.get("outcome_status") or ""), extras
            ):
                report["skipped_insufficient_data"] += 1
            continue
        report["loss_candidates"] += 1
        if _is_duplicate(kwargs, by_trade, by_event, by_composite):
            report["skipped_duplicate"] += 1
            continue

        if write:
            entry = _moltbook_api.MoltbookEntry(
                entry_id=f"MB_{uuid.uuid4().hex[:12]}",
                event_id=kwargs["event_id"],
                ticker=kwargs["ticker"],
                original_signal_thesis=kwargs["original_signal_thesis"],
                ai_interpretation=kwargs["ai_interpretation"],
                user_reflection=kwargs["user_reflection"],
                final_human_decision=kwargs["final_human_decision"],
                manual_trade_log_id=kwargs["manual_trade_log_id"],
                outcome=kwargs["outcome"],
                mistake_type=kwargs["mistake_type"],
                lesson_learned=kwargs["lesson_learned"],
                bias_detected=kwargs["bias_detected"],
                recalibration_note=kwargs["recalibration_note"],
                future_rule_update=kwargs["future_rule_update"],
                logged_at=utc_timestamp(),
            )
            # Canonical SQLite write (explicit db_path → fully test-isolated).
            _persistence.insert_moltbook_entry(
                entry.entry_id, entry.event_id, entry.ticker,
                entry.original_signal_thesis, entry.ai_interpretation,
                entry.user_reflection, entry.final_human_decision,
                entry.manual_trade_log_id, entry.outcome,
                entry.mistake_type, entry.lesson_learned,
                entry.bias_detected, entry.recalibration_note,
                entry.future_rule_update, entry.logged_at,
                db_path=path,
            )
            # Audit-only JSONL mirror (best-effort; never canonical).
            try:
                target_jsonl = jsonl_path if jsonl_path is not None else _moltbook_api.MOLTBOOK_LOG
                append_jsonl(target_jsonl, entry.to_dict(), stamp=False)
            except Exception:
                pass
            report["created_entries"].append(
                {"entry_id": entry.entry_id, "ticker": entry.ticker,
                 "manual_trade_log_id": entry.manual_trade_log_id,
                 "mistake_type": entry.mistake_type}
            )
        else:
            report["created_entries"].append(
                {"entry_id": "(dry-run)", "ticker": kwargs["ticker"],
                 "manual_trade_log_id": kwargs["manual_trade_log_id"],
                 "mistake_type": kwargs["mistake_type"]}
            )
        report["created"] += 1
        # Update in-memory dedup sets so a second loss in the same run that
        # maps to the same trade/event cannot create a duplicate.
        by_trade.add(str(kwargs.get("manual_trade_log_id") or ""))
        by_event.add(str(kwargs.get("event_id") or ""))
        by_composite.add(f"{kwargs['ticker']}|{kwargs.get('event_id') or ''}")

    return report


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="moltbook_reconciliation_bridge.py",
        description=(
            "Create one advisory-only Moltbook entry per closed losing trade. "
            "Read-only unless --write. Never places or cancels broker orders."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument("--write", action="store_true",
                   help="Actually create entries (default: dry-run).")
    p.add_argument("--json", action="store_true", help="Emit JSON.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    report = sync_reconciliation_losses_to_moltbook(db_path, write=args.write)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        mode = "WRITE" if report["applied"] else "DRY-RUN"
        print(f"Moltbook reconciliation bridge [{mode}]")
        print(f"  db_path             : {report['db_path']}")
        print(f"  loss candidates     : {report['loss_candidates']}")
        print(f"  created             : {report['created']}")
        print(f"  skipped duplicate   : {report['skipped_duplicate']}")
        print(f"  skipped insufficient: {report['skipped_insufficient_data']}")
        for e in report["created_entries"]:
            print(f"    - {e['ticker']:>6} {e['mistake_type']:<18} "
                  f"trade={e['manual_trade_log_id']} {e['entry_id']}")
    return 0


__all__ = [
    "sync_reconciliation_losses_to_moltbook",
    "build_entry_kwargs",
]


if __name__ == "__main__":
    raise SystemExit(main())
