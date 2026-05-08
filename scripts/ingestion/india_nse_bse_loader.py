"""
India NSE/BSE read-only loader — Phase 2 Global Signal Fabric.

Uses NSE India public endpoints. No API key required.
All outputs are advisory only.
"""
from __future__ import annotations

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_NSE_BASE = "https://www.nseindia.com/api"
_TIMEOUT = 15
_DEFAULT_INDICES = ["NIFTY 50", "NIFTY BANK"]


class IndiaNSEBSELoader(BaseSourceLoader):
    source_name = "india_nse_bse"
    requires_key = False

    def __init__(
        self,
        indices: list[str] | None = None,
        timeout: int = _TIMEOUT,
        base_url: str = _NSE_BASE,
    ) -> None:
        self._indices = indices or _DEFAULT_INDICES
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")

    def fetch(self) -> LoaderResult:
        """Fetch NSE index data (read-only, public endpoint)."""
        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; GSF-Phase2/1.0; research-only)",
            "Accept": "application/json",
        }
        records = []
        url = f"{self._base_url}/allIndices"
        try:
            resp = requests.get(url, headers=headers, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise SkipLoader(f"NSE API unreachable: {exc}") from exc

        indices_data = data.get("data", []) if isinstance(data, dict) else []
        wanted = {n.upper() for n in self._indices}
        for idx in indices_data:
            if not isinstance(idx, dict):
                continue
            if idx.get("index", "").upper() in wanted:
                rec = {
                    "index": idx.get("index", ""),
                    "last": idx.get("last"),
                    "change": idx.get("change"),
                    "percent_change": idx.get("percentChange"),
                    "source": "india_nse",
                }
                self._stamp_record(rec)
                records.append(rec)

        return LoaderResult(source_name=self.source_name, records=records)
