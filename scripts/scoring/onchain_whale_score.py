"""On-chain whale-transfer score skeleton."""
from __future__ import annotations

WHALE_USD_FLOOR = 1_000_000.0
WHALE_USD_CEIL = 100_000_000.0


def onchain_whale_score(transfer_value_usd: float | None) -> float:
    if not transfer_value_usd or transfer_value_usd <= WHALE_USD_FLOOR:
        return 0.0
    span = WHALE_USD_CEIL - WHALE_USD_FLOOR
    return max(0.0, min(1.0, (transfer_value_usd - WHALE_USD_FLOOR) / span))
