"""
Etherscan read-only loader — Phase 2 Global Signal Fabric.

Requires ETHERSCAN_API_KEY env var. Skips cleanly if missing.
Fetches public blockchain data only (transactions, token transfers, gas).
No private-key, signing, or transaction-send logic.

Address resolution order
------------------------
1. CLI/constructor `address` argument (explicit override)
2. ETHERSCAN_ADDRESS env var
3. ETHEREUM_ADDRESS env var
4. PUBLIC_ETH_ADDRESS env var
5. SkipLoader if none found or all are placeholder/malformed
"""
from __future__ import annotations

import os
import re

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_ETHERSCAN_BASE = "https://api.etherscan.io/api"
_TIMEOUT = 15

_ETH_ADDRESS_RE = re.compile(r"^0[xX][0-9a-fA-F]{40}$")
_PLACEHOLDER_FRAGMENTS = [
    "YOUR_PUBLIC_ETH_ADDRESS",
    "YOUR_ETH_ADDRESS",
    "INSERT_ADDRESS",
    "WALLET_ADDRESS",
    "0xYOUR",
    "0xINSERT",
    "EXAMPLE",
    "PLACEHOLDER",
]

_ENV_ADDRESS_VARS = [
    "ETHERSCAN_ADDRESS",
    "ETHEREUM_ADDRESS",
    "PUBLIC_ETH_ADDRESS",
]


def _validate_eth_address(address: str) -> str | None:
    """Return None if address is valid, or an error string if invalid."""
    upper = address.upper()
    for frag in _PLACEHOLDER_FRAGMENTS:
        if frag.upper() in upper:
            return f"address appears to be a placeholder: {address!r}"
    if not _ETH_ADDRESS_RE.match(address):
        return (
            f"malformed Ethereum address (expected 0x + 40 hex chars): {address!r}"
        )
    return None


def _resolve_address(explicit: str | None) -> str | None:
    """
    Return a candidate address from CLI arg or env vars.
    Returns None if nothing is configured. Does NOT validate — caller validates.
    """
    if explicit:
        return explicit
    for var in _ENV_ADDRESS_VARS:
        val = os.environ.get(var, "").strip()
        if val:
            return val
    return None


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

        # Resolve address: CLI arg → env var fallback
        address = _resolve_address(self._address)
        if not address:
            raise SkipLoader(
                "No Ethereum address provided — pass --address <0x...> "
                f"or set one of: {', '.join(_ENV_ADDRESS_VARS)}"
            )

        addr_error = _validate_eth_address(address)
        if addr_error:
            raise SkipLoader(f"Invalid Ethereum address: {addr_error}")

        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        params = {
            "module": "account",
            "action": self._action,
            "address": address,
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
            msg = data.get("message", "unknown")
            result = data.get("result", "")
            # "No transactions found" is a valid empty result, not an error
            if "no transactions" in str(msg).lower() or "no transactions" in str(result).lower():
                return LoaderResult(source_name=self.source_name, records=[])
            raise SkipLoader(f"Etherscan API error: {msg}")

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
