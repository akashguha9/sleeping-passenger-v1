"""
Singapore ACRA/SGX read-only loader — Phase 2 Global Signal Fabric.

Fetches public SGX securities and announcements data.
No API key required for public endpoints.
"""
from __future__ import annotations

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_SGX_BASE = "https://api.sgx.com"
_TIMEOUT = 15
_DEFAULT_MAX = 20


class SingaporeACRASGXLoader(BaseSourceLoader):
    source_name = "singapore_acra_sgx"
    requires_key = False

    def __init__(
        self,
        max_items: int = _DEFAULT_MAX,
        timeout: int = _TIMEOUT,
        base_url: str = _SGX_BASE,
    ) -> None:
        self._max = max_items
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")

    def fetch(self) -> LoaderResult:
        """Fetch SGX securities index data (read-only, public endpoint)."""
        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        url = f"{self._base_url}/securities/3.0/securities/index"
        headers = {"Accept": "application/json"}
        try:
            resp = requests.get(url, headers=headers, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise SkipLoader(f"SGX API unreachable: {exc}") from exc

        items = data if isinstance(data, list) else data.get("items", [])
        records = []
        for item in items[: self._max]:
            if not isinstance(item, dict):
                continue
            rec = {
                "name": item.get("n", item.get("name", "")),
                "ticker": item.get("s", item.get("ticker", "")),
                "price": item.get("lt", item.get("price")),
                "change": item.get("c", item.get("change")),
                "source": "singapore_sgx",
            }
            self._stamp_record(rec)
            records.append(rec)

        return LoaderResult(source_name=self.source_name, records=records)
