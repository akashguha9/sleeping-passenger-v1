"""
Polymarket read-only loader — Phase 2 Global Signal Fabric.

Uses only public read-only endpoints (Gamma API and Data API).
No authenticated trading endpoints. No CLOB order submission.
"""
from __future__ import annotations

from typing import Any

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_GAMMA_BASE = "https://gamma-api.polymarket.com"
_DATA_BASE = "https://data-api.polymarket.com"
_DEFAULT_LIMIT = 20
_TIMEOUT = 10


class PolymarketLoader(BaseSourceLoader):
    source_name = "polymarket"
    requires_key = False  # public endpoints only

    def __init__(
        self,
        limit: int = _DEFAULT_LIMIT,
        gamma_base: str = _GAMMA_BASE,
        data_base: str = _DATA_BASE,
        timeout: int = _TIMEOUT,
    ) -> None:
        self._limit = limit
        self._gamma_base = gamma_base.rstrip("/")
        self._data_base = data_base.rstrip("/")
        self._timeout = timeout

    def fetch(self) -> LoaderResult:
        """Fetch public market summaries from Polymarket Gamma API (read-only)."""
        try:
            import requests  # lazy import — no network on module load
        except ImportError:
            raise SkipLoader("requests library not installed")

        url = f"{self._gamma_base}/markets"
        params: dict[str, Any] = {"limit": self._limit, "active": "true"}
        try:
            resp = requests.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise SkipLoader(f"Polymarket API unreachable: {exc}") from exc

        markets = data if isinstance(data, list) else data.get("markets", [])
        records = []
        for m in markets:
            if not isinstance(m, dict):
                continue
            rec: dict[str, Any] = {
                "market_id": str(m.get("id", "")),
                "question": str(m.get("question", "")),
                "volume": m.get("volume"),
                "liquidity": m.get("liquidity"),
                "end_date": m.get("endDate"),
                "active": m.get("active"),
                "source": "polymarket",
            }
            self._stamp_record(rec)
            records.append(rec)

        return LoaderResult(source_name=self.source_name, records=records)
