from __future__ import annotations

from scripts.hedge_trade_entry_common import PositionConflictState


def detect_position_conflict(
    *,
    asset: str,
    spot_notional: float,
    futures_long_notional: float,
    futures_short_notional: float,
    declared_leg_purposes: list[str] | None,
    arbitrage_rationale_present: bool,
    funding_edge_present: bool,
    basis_edge_present: bool,
) -> dict:
    purposes = [p.upper() for p in (declared_leg_purposes or [])]
    has_explicit_edge = arbitrage_rationale_present or funding_edge_present or basis_edge_present
    if spot_notional > 0 and futures_long_notional > 0 and futures_short_notional > 0 and not has_explicit_edge:
        return {
            "state": PositionConflictState.REDUNDANT_COMPLEXITY.value,
            "reason": "same-asset long spot plus opposing futures legs adds complexity without distinct rationale",
            "review_ready": False,
        }
    if abs(futures_long_notional - futures_short_notional) < 1e-9 and futures_long_notional > 0 and not has_explicit_edge:
        return {
            "state": PositionConflictState.INTERNAL_CONFLICT.value,
            "reason": "same-asset opposing futures legs cancel exposure while adding fees/funding/liquidation risk",
            "review_ready": False,
        }
    if spot_notional > 0 and futures_short_notional > 0 and "HEDGE" in purposes:
        return {
            "state": PositionConflictState.VALID_HEDGE.value,
            "reason": "spot long is partially or fully protected by explicit futures hedge",
            "review_ready": True,
        }
    if has_explicit_edge:
        return {
            "state": PositionConflictState.STRUCTURE_REVIEW_READY.value if arbitrage_rationale_present else PositionConflictState.ARBITRAGE_REQUIRES_PROOF.value,
            "reason": f"structure on {asset} has explicit non-directional rationale but still requires proof and review",
            "review_ready": True,
        }
    return {
        "state": PositionConflictState.VALID_STRUCTURE.value,
        "reason": "no internal leg conflict detected",
        "review_ready": True,
    }
