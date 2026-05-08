"""
Solscan read-only loader — Phase 2 Global Signal Fabric.

Fetches public Solana blockchain data from Solscan Pro API.
Requires SOLSCAN_API_KEY env var. Skips cleanly if missing.
"""
from __future__ import annotations

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_SOLSCAN_BASE = "https://pro-api.solscan.io/v2.0"
_TIMEOUT = 15
_DEFAULT_MAX = 20


class SolscanLoader(BaseSourceLoader):
    source_name = "solscan"
    requires_key = True

    def __init__(
        self,
        address: str | None = None,
        endpoint: str = "account/transactions",
        max_records: int = _DEFAULT_MAX,
        timeout: int = _TIMEOUT,
        base_url: str = _SOLSCAN_BASE,
    ) -> None:
        self._address = address
        self._endpoint = endpoint.lstrip("/")
        self._max = max_records
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")

    def fetch(self) -> LoaderResult:
        """Fetch Solana account data from Solscan (read-only). Requires SOLSCAN_API_KEY."""
        api_key = self._require_env_key("SOLSCAN_API_KEY")

        if not self._address:
            raise SkipLoader("No Solana address provided to SolscanLoader")

        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        url = f"{self._base_url}/{self._endpoint}"
        headers = {"token": api_key, "Accept": "application/json"}
        params = {"address": self._address, "limit": self._max}
        try:
            resp = requests.get(
                url, headers=headers, params=params, timeout=self._timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise SkipLoader(f"Solscan API unreachable: {exc}") from exc

        items = data.get("data", []) if isinstance(data, dict) else []
        if isinstance(items, dict):
            items = [items]

        records = []
        for item in (items or [])[: self._max]:
            if not isinstance(item, dict):
                continue
            rec = dict(item)
            rec["source"] = "solscan"
            rec["address"] = self._address
            self._stamp_record(rec)
            records.append(rec)

        return LoaderResult(source_name=self.source_name, records=records)
