"""Kalshi market-snapshot model.

Mirrors ``src/models/market.py`` but covers only the fields that the
public Kalshi read-only market-data endpoints expose and that the
canonical Kalshi signal object needs.  No trading / portfolio / account
fields are modelled here on purpose — the MVP is advisory-only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class KalshiMarketSnapshot:
    """Public read-only snapshot of a Kalshi market.

    Every snapshot carries the canonical advisory-safety fields so the
    downstream signal inbox can render them without further enrichment.
    """

    source_market_id: str            # Kalshi ticker (e.g. "BTCMAY-2026")
    event_ticker: str
    title: str
    description: str
    rules: str
    category: str                    # canonical display label after allowlist
    category_raw: str                # the raw upstream value (lowercased)
    outcomes: list[str]
    yes_price: float | None
    no_price: float | None
    implied_probability: float | None
    volume: float | None
    open_interest: int | None
    liquidity: float | None
    close_time_utc: str
    market_url: str
    fetched_at_utc: str
    asset_tags: list[str] = field(default_factory=list)
    event_tags: list[str] = field(default_factory=list)
    semantic_text: str = ""

    # Safety stamps — frozen for the MVP, never overridden.
    source: str = "kalshi"
    source_label: str = "Kalshi"
    advisory_status: str = "ADVISORY_ONLY"
    execution_permission: str = "ADVISORY_ONLY"
    execution_gate: str = "LOCKED"
    advisory_only: bool = True
    human_review_required: bool = True
    broker_api_called: bool = False
    ai_execution_count: int = 0
    is_mock_fixture: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
