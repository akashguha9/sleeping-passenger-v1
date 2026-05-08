"""
Etherscan read-only loader — Phase 2 Global Signal Fabric.

Requires ETHERSCAN_API_KEY env var. Skips cleanly if missing.
Fetches public blockchain data only (transactions, token transfers, gas).
"""
from __future__ import annotations

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_ETHERSCAN_BASE = "https://api.etherscan.io/api"
_TIMEOUT = 15


class EtherscanLoader(BaseSourceLoader):
    source_name = "etherscan"
    requires_key = True

    def __init__(
        self,
        address: str | None = None,
        action: str = "txlist",
        max_records: int = 25,
        timeout: int = _TIMEOUT,
        base_url: str = _ETHERSCAN_BASE,
    ) -> None:
        self._address = address
        self._action = action
        self._max = max_records
        self._timeout = timeout
        self._base_url = base_url

    def fetch(self) -> LoaderResult:
        """Fetch Ethereum transaction data (read-only). Requires ETHERSCAN_API_KEY."""
        api_key = self._require_env_key("ETHERSCAN_API_KEY")

        if not self._address:
            raise SkipLoader("No Ethereum address provided to EtherscanLoader")

        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        params = {
            "module": "account",
            "action": self._action,
            "address": self._address,
            "startblock": 0,
            "endblock": 99999999,
            "sort": "desc",
            "apikey": api_key,
        }
        try:
            resp = requests.get(self._base_url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise SkipLoader(f"Etherscan API unreachable: {exc}") from exc

        if data.get("status") != "1":
            raise SkipLoader(f"Etherscan API error: {data.get('message', 'unknown')}")

        txs = data.get("result", []) or []
        records = []
        for tx in txs[: self._max]:
            if not isinstance(tx, dict):
                continue
            rec = {
                "hash": tx.get("hash", ""),
                "from_address": tx.get("from", ""),
                "to_address": tx.get("to", ""),
                "value_wei": tx.get("value", "0"),
                "block_number": tx.get("blockNumber", ""),
                "timestamp": tx.get("timeStamp", ""),
                "gas_used": tx.get("gasUsed", ""),
                "source": "etherscan",
            }
            self._stamp_record(rec)
            records.append(rec)

        return LoaderResult(source_name=self.source_name, records=records)
