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

Endpoint
--------
Default base URL is the v1 endpoint (`/api`). The loader also sends
`chainid=1` in params so the same request works against the v2 endpoint
(`/v2/api`) if the caller overrides `base_url`. v1 ignores unknown params.

Error reporting
---------------
A `NOTOK` response carries the real reason in `result` (e.g. "Missing/Invalid
API Key", "Max calls per sec rate limit reached", "Invalid address format").
We surface a sanitized version of `message` + `result` so the operator can
distinguish auth / rate-limit / endpoint / chain issues.  The API key is
stripped from any error string before it is reported.
"""
from __future__ import annotations

import os
import re

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_ETHERSCAN_BASE = "https://api.etherscan.io/v2/api"
_ETHERSCAN_BASE_V1 = "https://api.etherscan.io/api"  # kept for reference / explicit caller override
_TIMEOUT = 15
_DEFAULT_CHAIN_ID = 1  # mainnet

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


def _sanitize(text: str, api_key: str | None) -> str:
    """Strip the API key from any error string before reporting."""
    if not text:
        return ""
    cleaned = str(text)
    if api_key:
        cleaned = cleaned.replace(api_key, "<redacted>")
    return cleaned.strip()


def _classify_notok(msg: str, result: str) -> str:
    """
    Map a NOTOK ``message`` + ``result`` pair to a status tag.

    Returns one of: AUTH, RATE_LIMITED, INVALID_REQUEST, DEPRECATED, EMPTY, GENERIC.
    """
    blob = (msg + " " + result).lower()
    if "no transactions" in blob or "no records found" in blob:
        return "EMPTY"
    if (
        "invalid api key" in blob
        or "missing/invalid api key" in blob
        or "invalid api" in blob
    ):
        return "AUTH"
    if "rate limit" in blob or "max calls per sec" in blob or "too many" in blob:
        return "RATE_LIMITED"
    if "invalid address" in blob or "invalid parameter" in blob or "missing parameter" in blob:
        return "INVALID_REQUEST"
    if (
        "deprecated" in blob
        or "endpoint not found" in blob
        or "moved" in blob
        or "use v2" in blob
        or "chainid" in blob
    ):
        return "DEPRECATED"
    return "GENERIC"


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
        chain_id: int = _DEFAULT_CHAIN_ID,
    ) -> None:
        self._address = address
        self._action = action
        self._max = max_records
        self._timeout = timeout
        self._base_url = base_url
        self._chain_id = chain_id

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
            "chainid": self._chain_id,
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
            sanitized = _sanitize(f"{type(exc).__name__}: {exc}", api_key)
            raise SkipLoader(f"Etherscan API unreachable: {sanitized}") from exc

        if not isinstance(data, dict):
            raise SkipLoader("Etherscan API error: non-dict response")

        status_val = str(data.get("status", "")).strip()
        if status_val != "1":
            msg = str(data.get("message", "unknown"))
            result_val = data.get("result", "")
            # Etherscan sometimes returns result as list even for errors
            if isinstance(result_val, (list, dict)):
                result_str = ""
            else:
                result_str = str(result_val)

            tag = _classify_notok(msg, result_str)
            detail = _sanitize(
                f"{msg}" + (f" — {result_str}" if result_str else ""),
                api_key,
            )

            if tag == "EMPTY":
                # Valid empty result — not an error.
                return LoaderResult(source_name=self.source_name, records=[])
            if tag == "AUTH":
                raise SkipLoader(f"[ETHERSCAN_AUTH] {detail}")
            if tag == "RATE_LIMITED":
                raise SkipLoader(f"[RATE_LIMITED] Etherscan: {detail}")
            if tag == "INVALID_REQUEST":
                raise SkipLoader(f"[ETHERSCAN_INVALID] {detail}")
            if tag == "DEPRECATED":
                raise SkipLoader(
                    f"[ETHERSCAN_DEPRECATED] {detail} "
                    f"(try v2 endpoint: https://api.etherscan.io/v2/api with chainid)"
                )
            raise SkipLoader(f"Etherscan API error: {detail}")

        txs = data.get("result", []) or []
        if not isinstance(txs, list):
            raise SkipLoader("Etherscan API error: result is not a list")

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
