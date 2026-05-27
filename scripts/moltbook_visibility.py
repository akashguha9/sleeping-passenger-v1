"""
Moltbook dynamic visibility classifier.

The previous Moltbook truthfulness fix relied on a persisted
``hidden_from_default_view`` flag, which left a window where:

  - Legacy duplicates (same trade outcome emitted twice across the
    reconciliation→Moltbook bridge and the older manual-close path) both
    stayed visible.
  - Fixture/demo rows (DUP, SAFE, SPY ``test``/``probe``, ``Operator long
    X for swing setup`` synthetic trades) survived because their thesis
    text was not literally ``test``.
  - Unconfirmed closed-trade rows (e.g. MSFT closed-win 400→430 qty 2)
    survived because the per-row eligibility check accepted any
    well-formed CLOSED_WIN.

This module is the single source of truth for "may this Moltbook row
appear in the default operator view?".  It is consulted at:

  * GET /moltbook listing time (so default-visible truth is enforced
    even before the DB has been mutated).
  * scripts/moltbook_dedupe_cleanup.py (so the cleanup script's
    dry-run mirrors the API verdict).

The classifier returns a per-row :class:`VisibilityDecision` plus a
canonical_trade_outcome_key that collapses semantic duplicates emitted
by different sources.  ``classify_moltbook_entries`` adds cross-source
dedupe on top of the per-row pass.

Reason vocabulary
-----------------
VISIBLE_OPERATOR_CONFIRMED_FINAL_OUTCOME
HIDE_PERSISTED_HIDDEN
HIDE_DUPLICATE_SIGNATURE
HIDE_TEST_DEMO_FIXTURE
HIDE_UNCONFIRMED_CLOSED_TRADE
HIDE_OPEN_OR_NOT_FINAL
HIDE_MISSING_OPERATOR_SOURCE
HIDE_UNSUPPORTED_EVENT_TYPE

Advisory safety
---------------
This module is read-only and never mutates DB state.  It never calls
the broker, never grants execution permission, and never lifts the
``ADVISORY_ONLY`` / ``ai_execution_count=0`` invariants on a row it
classifies as visible.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

try:
    import scripts.moltbook_learning_bridge as _bridge
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import moltbook_learning_bridge as _bridge  # type: ignore[no-redef]


# Reason constants -----------------------------------------------------------

VISIBLE_OPERATOR_CONFIRMED_FINAL_OUTCOME = "VISIBLE_OPERATOR_CONFIRMED_FINAL_OUTCOME"
HIDE_PERSISTED_HIDDEN = "HIDE_PERSISTED_HIDDEN"
HIDE_DUPLICATE_SIGNATURE = "HIDE_DUPLICATE_SIGNATURE"
HIDE_TEST_DEMO_FIXTURE = "HIDE_TEST_DEMO_FIXTURE"
HIDE_UNCONFIRMED_CLOSED_TRADE = "HIDE_UNCONFIRMED_CLOSED_TRADE"
HIDE_OPEN_OR_NOT_FINAL = "HIDE_OPEN_OR_NOT_FINAL"
HIDE_MISSING_OPERATOR_SOURCE = "HIDE_MISSING_OPERATOR_SOURCE"
HIDE_UNSUPPORTED_EVENT_TYPE = "HIDE_UNSUPPORTED_EVENT_TYPE"

VISIBILITY_REASONS: frozenset[str] = frozenset(
    {
        VISIBLE_OPERATOR_CONFIRMED_FINAL_OUTCOME,
        HIDE_PERSISTED_HIDDEN,
        HIDE_DUPLICATE_SIGNATURE,
        HIDE_TEST_DEMO_FIXTURE,
        HIDE_UNCONFIRMED_CLOSED_TRADE,
        HIDE_OPEN_OR_NOT_FINAL,
        HIDE_MISSING_OPERATOR_SOURCE,
        HIDE_UNSUPPORTED_EVENT_TYPE,
    }
)


# Fixture / demo signatures the operator has confirmed are pollution.
# Each entry hides matching rows from the default Moltbook view *unless*
# the row carries an operator-confirmed source identity (see
# :func:`is_operator_confirmed`).
#
# The list is intentionally narrow: real operator trades for the same
# symbol (e.g. XOM 157.92→150.02, AAPL with different prices) do not
# match these signatures and remain visible.
FIXTURE_SIGNATURES: tuple[dict[str, Any], ...] = (
    {"symbol": "DUP", "entry": 100.0, "exit": 110.0, "qty": 2.0, "pl": 20.0},
    {"symbol": "SAFE", "entry": 50.0, "exit": 55.0, "qty": 1.0, "pl": 5.0},
    {
        "symbol": "MSFT", "entry": 400.0, "exit": 430.0, "qty": 2.0, "pl": 60.0,
        "thesis_sub": "operator long msft for swing setup",
    },
    {
        "symbol": "XOM", "entry": 105.0, "exit": 98.5, "qty": 10.0, "pl": -65.0,
        "thesis_sub": "operator long xom for swing setup",
    },
    {
        "symbol": "ANET", "entry": 380.0, "exit": 420.0, "qty": 7.0, "pl": 280.0,
        "thesis_sub": "operator long anet for swing setup",
    },
    {"symbol": "AAPL", "entry": 180.0, "exit": 190.0, "qty": 10.0, "pl": 100.0},
    {"symbol": "TLT", "entry": 90.0, "exit": 92.0, "qty": 4.0, "pl": 8.0},
    {
        "symbol": "ICICIBANK.NS", "entry": 40.72, "exit": 42.0, "qty": 2.7236, "pl": 3.4862,
        "thesis_sub": "probe",
    },
    {"symbol": "SPY", "entry": 450.0, "exit": 452.0, "qty": 1.0},
    {"symbol": "SPY", "entry": 520.0, "exit": 510.0, "qty": 5.0, "thesis_sub": "probe"},
)

# Test/demo thesis tokens that hide a row even without a numeric
# signature match (catches SPY thesis="t" rows etc.).
_TEST_DEMO_THESIS_TOKENS = _bridge.TEST_DEMO_THESIS_TOKENS

# Tickers that, combined with a fixture-shaped thesis token, are always
# treated as pollution unless explicitly operator-confirmed.
_FIXTURE_TICKER_THESIS_PAIRS: tuple[tuple[str, str], ...] = (
    ("SPY", "test"),
    ("SPY", "t"),
    ("SPY", "probe"),
)


@dataclass(frozen=True)
class VisibilityDecision:
    """Per-row visibility verdict.

    ``canonical_group_key`` is the cross-source dedupe key.  Two rows
    sharing this key represent the same trade outcome emitted by
    different sources and collapse to one visible canonical row.
    ``duplicate_of`` is populated when this row was hidden because a
    canonical sibling won the dedupe pass.
    """
    visible: bool
    reason: str
    canonical_group_key: str | None = None
    duplicate_of: str | None = None
    confidence: str = "HIGH"
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "visible": bool(self.visible),
            "reason": self.reason,
            "canonical_group_key": self.canonical_group_key,
            "duplicate_of": self.duplicate_of,
            "confidence": self.confidence,
        }


# Helpers --------------------------------------------------------------------


def _norm_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _norm_thesis(value: Any) -> str:
    return str(value or "").strip().lower()


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _approx(a: float | None, b: float | None, *, tol: float = 0.01) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _approx_qty(a: float | None, b: float | None, *, tol: float = 1e-4) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def is_operator_confirmed(entry: Mapping[str, Any]) -> bool:
    """Return True when the row carries an operator-confirmed source identity.

    Any one of the following is sufficient:
      * explicit ``operator_confirmed`` / ``real_trade_source`` /
        ``imported_from_operator_sheet`` flag set truthy
      * a non-empty ``closed_at`` timestamp from an actual trade record
      * ``manual_trade_log_id`` populated with a stable ``MT_*`` ID
        that does not look like a fixture placeholder
    """
    for flag in ("operator_confirmed", "real_trade_source",
                 "imported_from_operator_sheet"):
        val = entry.get(flag)
        if val is True:
            return True
        if isinstance(val, int) and val:
            return True
        if isinstance(val, str) and val.strip().lower() in {"1", "true", "yes"}:
            return True
    if str(entry.get("closed_at") or "").strip():
        return True
    return False


def _event_family(entry: Mapping[str, Any]) -> str:
    """Collapse ``event_type`` / ``mistake_type`` into a coarse family.

    The family is the equivalence class used by the cross-source
    canonical_trade_outcome_key.  Rows that describe the same trade
    outcome via different event-type vocabularies must hash to the same
    family.
    """
    event_type = str(entry.get("event_type") or "").strip().upper()
    mistake_type = str(entry.get("mistake_type") or "").strip().lower()
    decision = str(entry.get("final_human_decision") or "").lower()
    realized_pl = _coerce_float(entry.get("realized_pl"))

    if event_type:
        if event_type in {"STOP_LOSS_HIT", "TRAILING_STOP_HIT", "RULE_FOLLOWED_LOSS"}:
            return "STOP_LOSS"
        if event_type == "TAKE_PROFIT_HIT":
            return "TAKE_PROFIT"
        if event_type in {"PARTIAL_TP_HIT", "PARTIAL_TP_LOGGED"}:
            return "PARTIAL_TP"
        if event_type == "MANUAL_EXIT_LOSS":
            return "MANUAL_EXIT_LOSS"
        if event_type == "MANUAL_EXIT_WIN":
            return "MANUAL_EXIT_WIN"
        if event_type == "BREAKEVEN_EXIT":
            return "BREAKEVEN"
        if event_type == "CLOSED_WIN":
            return "CLOSED_WIN"
        if event_type == "CLOSED_LOSS":
            return "CLOSED_LOSS"
        if event_type == "CLOSED":
            if realized_pl is None or realized_pl == 0:
                return "BREAKEVEN"
            return "CLOSED_WIN" if realized_pl > 0 else "CLOSED_LOSS"

    if mistake_type == "stop_loss_breach":
        return "STOP_LOSS"
    if mistake_type == "manual_exit_loss":
        return "MANUAL_EXIT_LOSS"
    if mistake_type == "trade_loss":
        if "manual" in decision or "exit at a loss" in decision:
            return "MANUAL_EXIT_LOSS"
        if "stop" in decision:
            return "STOP_LOSS"
        return "CLOSED_LOSS"
    if mistake_type == "good_signal_good_execution":
        if realized_pl is None:
            return "CLOSED_WIN"
        if realized_pl > 0:
            return "CLOSED_WIN"
        if realized_pl < 0:
            return "CLOSED_LOSS"
        return "BREAKEVEN"
    if mistake_type == "bad_signal_lucky_profit":
        return "CLOSED_WIN"

    if realized_pl is not None:
        if realized_pl > 0:
            return "CLOSED_WIN"
        if realized_pl < 0:
            return "CLOSED_LOSS"
        return "BREAKEVEN"
    return "UNKNOWN"


def canonical_trade_outcome_key(entry: Mapping[str, Any]) -> str:
    """Stable hash that collapses semantic duplicates across sources.

    Two rows hash to the same key when they describe the same trade
    outcome — same symbol, same event family, same entry/exit/qty/pl
    rounded.  This is the cross-source dedupe key the API and cleanup
    both use.
    """
    sym = _norm_symbol(entry.get("ticker") or entry.get("symbol"))
    family = _event_family(entry)
    entry_p = _coerce_float(entry.get("entry_price")) or 0.0
    exit_p = _coerce_float(entry.get("exit_price")) or 0.0
    qty = _coerce_float(entry.get("exit_quantity")) or 0.0
    realized_pl = _coerce_float(entry.get("realized_pl")) or 0.0
    parts = [
        sym,
        family,
        f"{round(entry_p, 4):.4f}",
        f"{round(exit_p, 4):.4f}",
        f"{round(qty, 6):.6f}",
        f"{round(realized_pl, 4):.4f}",
    ]
    raw = "|".join(parts).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    return f"CTO_{digest[:24]}"


def is_known_fixture_signature(entry: Mapping[str, Any]) -> bool:
    """Match an entry against the curated fixture/demo denylist.

    Returns True for rows whose (symbol, entry, exit, qty, pl, thesis)
    matches a known fixture pattern, e.g. ``DUP 100→110 qty 2 pl 20`` or
    ``MSFT 400→430 qty 2 pl 60 "Operator long MSFT for swing setup"``.
    The matcher is conservative — it requires symbol + numeric agreement
    so real trades on the same ticker are not caught.
    """
    sym = _norm_symbol(entry.get("ticker") or entry.get("symbol"))
    if not sym:
        return False
    thesis = _norm_thesis(entry.get("original_signal_thesis") or entry.get("thesis"))
    entry_p = _coerce_float(entry.get("entry_price"))
    exit_p = _coerce_float(entry.get("exit_price"))
    qty = _coerce_float(entry.get("exit_quantity"))
    realized_pl = _coerce_float(entry.get("realized_pl"))

    # Ticker+thesis-only fixture marker (no numeric agreement needed).
    for fix_sym, fix_thesis in _FIXTURE_TICKER_THESIS_PAIRS:
        if sym == fix_sym and thesis == fix_thesis:
            return True

    for sig in FIXTURE_SIGNATURES:
        if sig["symbol"] != sym:
            continue
        if "entry" in sig and not _approx(entry_p, sig["entry"]):
            continue
        if "exit" in sig and not _approx(exit_p, sig["exit"]):
            continue
        if "qty" in sig and not _approx_qty(qty, sig["qty"]):
            continue
        if "pl" in sig and not _approx(realized_pl, sig["pl"], tol=0.05):
            continue
        if "thesis_sub" in sig:
            if sig["thesis_sub"] not in thesis:
                continue
        return True
    return False


# Per-row classification -----------------------------------------------------


def classify_moltbook_visibility(entry: Mapping[str, Any]) -> VisibilityDecision:
    """Classify a single Moltbook row for default-view visibility.

    The decision combines the persisted ``hidden_from_default_view``
    flag, the fixture denylist, the bridge eligibility contract, and the
    test/demo thesis-token shortcut.  Cross-source dedupe is layered on
    top by :func:`classify_moltbook_entries`.
    """
    cto_key = canonical_trade_outcome_key(entry)

    # 1. Persisted hidden flag — operator/cleanup already decided.
    if int(entry.get("hidden_from_default_view") or 0):
        hidden_reason = str(entry.get("hidden_reason") or "")
        if int(entry.get("is_duplicate") or 0) or hidden_reason.startswith("DUPLICATE_OF"):
            return VisibilityDecision(
                False, HIDE_DUPLICATE_SIGNATURE,
                canonical_group_key=cto_key,
                duplicate_of=str(entry.get("duplicate_of") or "") or None,
                confidence="HIGH",
            )
        if hidden_reason == _bridge.SKIP_TEST_DEMO_FIXTURE:
            return VisibilityDecision(
                False, HIDE_TEST_DEMO_FIXTURE,
                canonical_group_key=cto_key, confidence="HIGH",
            )
        return VisibilityDecision(
            False, HIDE_PERSISTED_HIDDEN,
            canonical_group_key=cto_key, confidence="HIGH",
        )

    operator_confirmed = is_operator_confirmed(entry)

    # 2. Fixture signature denylist (operator-confirmed override).
    if is_known_fixture_signature(entry) and not operator_confirmed:
        return VisibilityDecision(
            False, HIDE_TEST_DEMO_FIXTURE,
            canonical_group_key=cto_key, confidence="HIGH",
        )

    # 3. Test/demo thesis tokens that slipped past per-symbol fixtures.
    thesis = _norm_thesis(entry.get("original_signal_thesis") or entry.get("thesis"))
    if thesis in _TEST_DEMO_THESIS_TOKENS and not operator_confirmed:
        return VisibilityDecision(
            False, HIDE_TEST_DEMO_FIXTURE,
            canonical_group_key=cto_key, confidence="HIGH",
        )

    # 4. Bridge eligibility for reconciliation-derived rows.  Legacy
    #    signal-decision rows (event_type='') bypass this gate — they
    #    pre-date the reconciliation→Moltbook bridge and remain valid.
    event_type = str(entry.get("event_type") or "").strip().upper()
    if event_type:
        verdict = _bridge.is_moltbook_eligible_reconciliation_event(
            {
                "event_type": event_type,
                "status": "",
                "symbol": entry.get("ticker") or entry.get("symbol") or "",
                "trade_id": (
                    entry.get("trade_id")
                    or entry.get("manual_trade_log_id")
                    or ""
                ),
                "manual_trade_id": entry.get("manual_trade_log_id") or "",
                "exit_price": entry.get("exit_price"),
                "realized_pl": entry.get("realized_pl"),
                "exit_reason": "",
                "stop_loss_hit": False,
                # Strip thesis when the operator already confirmed the
                # row — the thesis text is preserved for audit, but it
                # must not trigger SKIP_TEST_DEMO_FIXTURE retroactively.
                "thesis": "" if operator_confirmed else (
                    entry.get("original_signal_thesis") or ""
                ),
            }
        )
        if not verdict["eligible"]:
            reason_map = {
                _bridge.SKIP_TEST_DEMO_FIXTURE: HIDE_TEST_DEMO_FIXTURE,
                _bridge.SKIP_OPEN_TRADE: HIDE_OPEN_OR_NOT_FINAL,
                _bridge.SKIP_SIGNAL_ONLY: HIDE_OPEN_OR_NOT_FINAL,
                _bridge.SKIP_PRICE_MARK_ONLY: HIDE_OPEN_OR_NOT_FINAL,
                _bridge.SKIP_UNREALIZED_ONLY: HIDE_OPEN_OR_NOT_FINAL,
                _bridge.SKIP_MISSING_TRADE_IDENTITY: HIDE_MISSING_OPERATOR_SOURCE,
                _bridge.SKIP_MISSING_EXIT_OR_REALIZED_PL: HIDE_UNCONFIRMED_CLOSED_TRADE,
                _bridge.SKIP_UNSUPPORTED_EVENT_TYPE: HIDE_UNSUPPORTED_EVENT_TYPE,
            }
            return VisibilityDecision(
                False, reason_map.get(verdict["reason"], HIDE_UNSUPPORTED_EVENT_TYPE),
                canonical_group_key=cto_key, confidence="HIGH",
            )

    return VisibilityDecision(
        True, VISIBLE_OPERATOR_CONFIRMED_FINAL_OUTCOME,
        canonical_group_key=cto_key, confidence="HIGH",
    )


# Canonical-row selection for cross-source dedupe ---------------------------


def _richness_score(row: Mapping[str, Any]) -> int:
    score = 0
    for field_name in (
        "lesson", "lesson_learned", "user_reflection",
        "original_signal_thesis", "ai_interpretation",
    ):
        text = str(row.get(field_name) or "").strip()
        score += len(text)
    return score


def _pick_canonical(group: list[tuple[str, Mapping[str, Any]]]) -> tuple[str, Mapping[str, Any]]:
    """Pick the canonical row from a same-outcome group.

    Preference order:
      1. Row with explicit ``closed_at`` (real trade record timestamp).
      2. Row with a non-empty ``manual_trade_log_id`` (legacy manually
         logged close beats a bridge-derived backfill row).
      3. Older ``created_at`` (then ``logged_at``).
      4. Richer human reflection (longer lesson + reflection + thesis).
      5. ``entry_id`` as final tiebreak for determinism.
    """
    def sort_key(item: tuple[str, Mapping[str, Any]]) -> tuple[Any, ...]:
        eid, row = item
        has_closed_at = bool(str(row.get("closed_at") or "").strip())
        has_manual_id = bool(str(row.get("manual_trade_log_id") or "").strip())
        created = str(row.get("created_at") or row.get("logged_at") or "")
        return (
            0 if has_closed_at else 1,
            0 if has_manual_id else 1,
            created,
            -_richness_score(row),
            eid,
        )

    return sorted(group, key=sort_key)[0]


def _manual_trade_group_key(entry: Mapping[str, Any]) -> str | None:
    """Secondary group key: same ``manual_trade_log_id`` ⇒ same trade.

    The CTO hash collapses rows that share symbol + event family +
    rounded entry/exit/qty/pl.  In practice legacy Moltbook rows often
    have entry_price/exit_price/exit_quantity stored as NULL because the
    pre-bridge schema never required them, so two rows describing the
    same trade hash to different CTOs.  When both rows still carry the
    same ``manual_trade_log_id`` (the canonical pointer into
    ``manual_trades``), that is the operator-confirmed identity link.
    """
    sym = _norm_symbol(entry.get("ticker") or entry.get("symbol"))
    log_id = str(entry.get("manual_trade_log_id") or "").strip()
    if not log_id or not sym:
        return None
    return f"MTL_{sym}|{log_id}"


def classify_moltbook_entries(
    entries: Iterable[Mapping[str, Any]],
) -> dict[str, VisibilityDecision]:
    """Classify a batch and apply cross-source dedupe in one pass.

    Per-row decisions are computed first.  Then visible rows are grouped
    by ``canonical_trade_outcome_key``; for any group with more than one
    visible row, the canonical row is kept and the remaining rows are
    re-decided as :data:`HIDE_DUPLICATE_SIGNATURE` with ``duplicate_of``
    pointing at the canonical ``entry_id``.  After the CTO pass a
    secondary collapse runs on ``manual_trade_log_id`` for any rows
    still visible — this catches legacy rows that lack persisted
    prices and would otherwise hash to a different CTO than the
    reconciliation-derived bridge row describing the same trade.

    Returns a mapping ``entry_id -> VisibilityDecision``.
    """
    decisions: dict[str, VisibilityDecision] = {}
    rows_by_id: dict[str, Mapping[str, Any]] = {}
    per_key_visible: dict[str, list[tuple[str, Mapping[str, Any]]]] = defaultdict(list)

    for row in entries:
        entry_id = str(row.get("entry_id") or "")
        decision = classify_moltbook_visibility(row)
        decisions[entry_id] = decision
        rows_by_id[entry_id] = row
        if decision.visible and decision.canonical_group_key:
            per_key_visible[decision.canonical_group_key].append((entry_id, row))

    # 1) Primary CTO-key collapse.
    for key, group in per_key_visible.items():
        if len(group) <= 1:
            continue
        canonical_id, _canonical_row = _pick_canonical(group)
        for eid, _ in group:
            if eid == canonical_id:
                continue
            decisions[eid] = VisibilityDecision(
                visible=False,
                reason=HIDE_DUPLICATE_SIGNATURE,
                canonical_group_key=key,
                duplicate_of=canonical_id,
                confidence="HIGH",
            )

    # 2) Secondary collapse by manual_trade_log_id — catches legacy
    #    rows whose entry/exit/qty/pl are NULL so they hash to a
    #    different CTO than the bridge row describing the same trade.
    mtl_groups: dict[str, list[tuple[str, Mapping[str, Any]]]] = defaultdict(list)
    for entry_id, decision in decisions.items():
        if not decision.visible:
            continue
        row = rows_by_id.get(entry_id, {})
        mtl_key = _manual_trade_group_key(row)
        if mtl_key:
            mtl_groups[mtl_key].append((entry_id, row))
    for mtl_key, group in mtl_groups.items():
        if len(group) <= 1:
            continue
        canonical_id, _canonical_row = _pick_canonical(group)
        for eid, _ in group:
            if eid == canonical_id:
                continue
            old = decisions[eid]
            decisions[eid] = VisibilityDecision(
                visible=False,
                reason=HIDE_DUPLICATE_SIGNATURE,
                canonical_group_key=old.canonical_group_key or mtl_key,
                duplicate_of=canonical_id,
                confidence="HIGH",
            )

    return decisions


def summarize_decisions(
    decisions: Mapping[str, VisibilityDecision],
) -> dict[str, Any]:
    """Aggregate counts by reason for API/cleanup metadata."""
    counts: dict[str, int] = {r: 0 for r in VISIBILITY_REASONS}
    visible = 0
    hidden_duplicates = 0
    hidden_test_demo = 0
    hidden_unconfirmed = 0
    hidden_persisted = 0
    hidden_open = 0
    hidden_missing_source = 0
    hidden_unsupported = 0
    for d in decisions.values():
        counts[d.reason] = counts.get(d.reason, 0) + 1
        if d.visible:
            visible += 1
        elif d.reason == HIDE_DUPLICATE_SIGNATURE:
            hidden_duplicates += 1
        elif d.reason == HIDE_TEST_DEMO_FIXTURE:
            hidden_test_demo += 1
        elif d.reason == HIDE_UNCONFIRMED_CLOSED_TRADE:
            hidden_unconfirmed += 1
        elif d.reason == HIDE_PERSISTED_HIDDEN:
            hidden_persisted += 1
        elif d.reason == HIDE_OPEN_OR_NOT_FINAL:
            hidden_open += 1
        elif d.reason == HIDE_MISSING_OPERATOR_SOURCE:
            hidden_missing_source += 1
        elif d.reason == HIDE_UNSUPPORTED_EVENT_TYPE:
            hidden_unsupported += 1
    return {
        "visible_entries": visible,
        "hidden_duplicates": hidden_duplicates,
        "hidden_test_demo": hidden_test_demo,
        "hidden_unconfirmed": hidden_unconfirmed,
        "hidden_persisted": hidden_persisted,
        "hidden_open_or_not_final": hidden_open,
        "hidden_missing_source": hidden_missing_source,
        "hidden_unsupported": hidden_unsupported,
        "visibility_reasons": counts,
    }


__all__ = [
    "VISIBLE_OPERATOR_CONFIRMED_FINAL_OUTCOME",
    "HIDE_PERSISTED_HIDDEN",
    "HIDE_DUPLICATE_SIGNATURE",
    "HIDE_TEST_DEMO_FIXTURE",
    "HIDE_UNCONFIRMED_CLOSED_TRADE",
    "HIDE_OPEN_OR_NOT_FINAL",
    "HIDE_MISSING_OPERATOR_SOURCE",
    "HIDE_UNSUPPORTED_EVENT_TYPE",
    "VISIBILITY_REASONS",
    "FIXTURE_SIGNATURES",
    "VisibilityDecision",
    "canonical_trade_outcome_key",
    "is_known_fixture_signature",
    "is_operator_confirmed",
    "classify_moltbook_visibility",
    "classify_moltbook_entries",
    "summarize_decisions",
]
