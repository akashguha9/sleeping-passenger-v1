"""Layer 1 — Portfolio Truth Gate.

The daily five-model synthesis went stale because it treated stale moltbook
rows (UNG/FCG/TLT/TIP) and a sold name (GLD) as if they were live holdings.
That phantom portfolio then blocked all fresh discovery for two days.

This module is the hard gate that fixes that. It computes the *only* valid
current-holdings set from the verified payload and proves, per ticker, whether
the system is allowed to manage it as a position.

Set algebra (verbatim from the operator spec):

    V = OPEN tickers in verified_current_holdings.json
    C = CLOSED/EXITED/SOLD tickers in closed_positions.json
    S = tickers in sold_positions.json
    D = not_owned_do_not_manage ∪ closed_or_sold_positions (do_not_treat_as_open)
    L = tickers in stale ledger artifacts (open_positions/signal_ledger/etc.)

    H = V \\ (C ∪ S ∪ D)        # the only valid current holdings

    OPEN_VERIFIED(t)        = 1[t ∈ H]
    FORBIDDEN_MANAGEMENT(t) = 1[t ∈ C ∪ S ∪ D]  OR  1[t ∉ H]
    management_permission(t)= 1 iff t ∈ H   (and 0 if t ∈ D regardless of L)

Phantom positions (t ∈ L but t ∉ H) are surfaced explicitly and may NEVER set
``global_discovery_permission = 0``. This module is advisory/visibility-only:
it never mutates any file and never authorizes execution.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.daily_payload import load_daily_payload, normalize_ticker
    from scripts.runtime_common import (
        OPEN_POSITIONS_PATH,
        SIGNAL_LEDGER_PATH,
        load_json_file,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from daily_payload import load_daily_payload, normalize_ticker
    from runtime_common import OPEN_POSITIONS_PATH, SIGNAL_LEDGER_PATH, load_json_file


# Treatments that are forbidden for any ticker that is not a verified holding.
FORBIDDEN_TREATMENTS: tuple[str, ...] = (
    "existing_position",
    "exit_candidate",
    "stop_loss_breach",
    "take_profit_hit",
    "portfolio_risk",
    "position_needing_management",
    "runner",
    "partial_tp_candidate",
    "hold_review",
)


def _stale_ledger_tickers(
    open_positions_path: Path | None = None,
    signal_ledger_path: Path | None = None,
) -> list[str]:
    """Collect tickers from stale ledger artifacts (set L).

    These are historical/contaminated rows — they are NOT portfolio truth.
    """
    tickers: list[str] = []

    open_payload = load_json_file(open_positions_path or OPEN_POSITIONS_PATH, default=[])
    if isinstance(open_payload, list):
        for row in open_payload:
            if isinstance(row, dict):
                ticker = normalize_ticker(row.get("ticker") or row.get("symbol"))
                if ticker and ticker not in tickers:
                    tickers.append(ticker)

    ledger_payload = load_json_file(signal_ledger_path or SIGNAL_LEDGER_PATH, default=[])
    if isinstance(ledger_payload, list):
        for row in ledger_payload:
            if isinstance(row, dict):
                ticker = normalize_ticker(row.get("ticker") or row.get("symbol"))
                if ticker and ticker not in tickers:
                    tickers.append(ticker)
    return tickers


def build_portfolio_truth_gate(
    payload: dict[str, Any] | None = None,
    payload_dir: Path | None = None,
    open_positions_path: Path | None = None,
    signal_ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Compute the Portfolio Truth Gate output object.

    ``payload`` may be supplied directly (already-loaded daily payload). When
    omitted it is loaded from ``payload_dir`` (or the committed default).
    """
    if payload is None:
        payload = load_daily_payload(payload_dir)

    V = list(payload["verified_holdings"]["open_tickers"])
    C = list(payload["closed_positions"]["closed_tickers"])
    S = list(payload["sold_positions"]["tickers"])
    D = list(payload["do_not_treat_as_open"]["all_tickers"])
    L = _stale_ledger_tickers(open_positions_path, signal_ledger_path)

    forbidden_union = sorted(set(C) | set(S) | set(D))
    H = [t for t in V if t not in set(forbidden_union)]

    h_set = set(H)
    # Phantom positions: appear in stale ledger context but are NOT verified
    # holdings. These are exactly the rows that hijacked the old synthesis.
    phantom_candidates = sorted(t for t in set(L) if t not in h_set)

    # Truth errors: a ticker that is both flagged do-not-manage AND still
    # present in verified holdings would be a contradiction the operator must
    # resolve. We never silently drop it — we surface it.
    truth_errors: list[str] = []
    for ticker in V:
        if ticker in set(D):
            truth_errors.append(
                f"{ticker} is in verified_current_holdings but also in "
                f"do_not_treat_as_open; do_not_treat_as_open wins — excluded from H."
            )
        if ticker in set(S):
            truth_errors.append(
                f"{ticker} is in verified_current_holdings but also in "
                f"sold_positions; sold wins — excluded from H."
            )

    notes: list[str] = []
    if not H:
        notes.append(
            "No verified open holdings. Position-management actions are disabled; "
            "fresh discovery is still permitted."
        )
    if phantom_candidates:
        notes.append(
            "Phantom position mentions detected in stale ledger context "
            f"({', '.join(phantom_candidates)}). These are historical/forbidden, "
            "must not be managed, and must not block discovery."
        )
    if D:
        notes.append(
            "do_not_treat_as_open override active for "
            f"{', '.join(sorted(set(D)))} — labeled DO_NOT_TREAT_AS_OPEN."
        )
    if C or S:
        notes.append(
            "Closed/sold names "
            f"({', '.join(sorted(set(C) | set(S)))}) are historical context only."
        )

    return {
        "verified_open_holdings": sorted(H),
        "closed_or_sold": sorted(set(C) | set(S)),
        "do_not_treat_as_open": sorted(set(D)),
        "stale_ledger_tickers": sorted(set(L)),
        "phantom_position_candidates": phantom_candidates,
        "portfolio_truth_errors": truth_errors,
        "can_manage_positions": bool(H),
        # Phantom positions can never disable discovery — this is the core fix.
        "global_discovery_permission": True,
        "notes": notes,
        "set_sizes": {"V": len(set(V)), "C": len(set(C)), "S": len(set(S)), "D": len(set(D)), "L": len(set(L)), "H": len(set(H))},
        "safety": advisory_safety_stamps(),
    }


def open_verified(ticker: str, gate: dict[str, Any]) -> int:
    """OPEN_VERIFIED(t) = 1[t ∈ H]."""
    return 1 if normalize_ticker(ticker) in set(gate["verified_open_holdings"]) else 0


def management_permission(ticker: str, gate: dict[str, Any]) -> int:
    """management_permission(t) = 1 iff t ∈ H.

    A ticker in D returns 0 regardless of stale ledger content, because D
    tickers are excluded from H by construction.
    """
    return open_verified(ticker, gate)


def forbidden_management(ticker: str, gate: dict[str, Any]) -> int:
    """FORBIDDEN_MANAGEMENT(t) = 1[t ∈ C ∪ S ∪ D] OR 1[t ∉ H]."""
    norm = normalize_ticker(ticker)
    if norm in (set(gate["closed_or_sold"]) | set(gate["do_not_treat_as_open"])):
        return 1
    return 0 if norm in set(gate["verified_open_holdings"]) else 1


def classify_ticker(ticker: str, gate: dict[str, Any]) -> str:
    """Return the portfolio-truth label for a ticker.

    One of:
        VERIFIED_OPEN_HOLDING
        DO_NOT_TREAT_AS_OPEN
        CLOSED_OR_SOLD
        NOT_A_HOLDING        (phantom / unverified — discovery-eligible only)
    """
    norm = normalize_ticker(ticker)
    if norm in set(gate["verified_open_holdings"]):
        return "VERIFIED_OPEN_HOLDING"
    if norm in set(gate["do_not_treat_as_open"]):
        return "DO_NOT_TREAT_AS_OPEN"
    if norm in set(gate["closed_or_sold"]):
        return "CLOSED_OR_SOLD"
    return "NOT_A_HOLDING"


def may_generate_management_action(ticker: str, gate: dict[str, Any]) -> bool:
    """True only if exit/TP/stop/hold/runner actions are allowed for ``ticker``.

    This is the single guard the synthesis layer must consult before emitting
    any position-management language about a ticker.
    """
    return management_permission(ticker, gate) == 1


__all__ = [
    "FORBIDDEN_TREATMENTS",
    "build_portfolio_truth_gate",
    "open_verified",
    "management_permission",
    "forbidden_management",
    "classify_ticker",
    "may_generate_management_action",
]
