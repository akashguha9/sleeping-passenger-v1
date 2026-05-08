"""
EVM chain read-only loader — Phase 2 Global Signal Fabric.

Fetches recent block headers from any EVM-compatible chain via JSON-RPC.
Requires EVM_RPC_URL env var (or per-chain env var). Skips cleanly if missing.
All outputs are advisory only.
"""
from __future__ import annotations

from typing import Any

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_TIMEOUT = 15
_DEFAULT_BLOCK_COUNT = 5


class EVMChainLoader(BaseSourceLoader):
    source_name = "evm_chain"
    requires_key = True

    def __init__(
        self,
        chain_name: str = "ethereum",
        rpc_env_var: str = "EVM_RPC_URL",
        block_count: int = _DEFAULT_BLOCK_COUNT,
        timeout: int = _TIMEOUT,
    ) -> None:
        self._chain_name = chain_name
        self._rpc_env_var = rpc_env_var
        self._block_count = block_count
        self._timeout = timeout

    def _rpc_call(self, session: Any, rpc_url: str, method: str, params: list) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        }
        resp = session.post(rpc_url, json=payload, timeout=self._timeout)
        resp.raise_for_status()
        result = resp.json()
        if "error" in result:
            raise SkipLoader(f"RPC error: {result['error']}")
        return result.get("result")

    def fetch(self) -> LoaderResult:
        """Fetch recent block headers from an EVM chain (read-only). Requires EVM_RPC_URL."""
        rpc_url = self._require_env_key(self._rpc_env_var)

        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        session = requests.Session()
        try:
            latest_hex = self._rpc_call(session, rpc_url, "eth_blockNumber", [])
            if not latest_hex:
                raise SkipLoader("Could not fetch latest block number")
            latest_block = int(latest_hex, 16)
        except SkipLoader:
            raise
        except Exception as exc:
            raise SkipLoader(f"EVM RPC unreachable: {exc}") from exc

        records = []
        for i in range(self._block_count):
            block_num = latest_block - i
            block_hex = hex(block_num)
            try:
                block = self._rpc_call(
                    session, rpc_url, "eth_getBlockByNumber", [block_hex, False]
                )
                if not isinstance(block, dict):
                    continue
                rec: dict[str, Any] = {
                    "chain": self._chain_name,
                    "block_number": block_num,
                    "block_hash": block.get("hash", ""),
                    "timestamp": int(block.get("timestamp", "0x0"), 16),
                    "transaction_count": len(block.get("transactions", [])),
                    "gas_used": block.get("gasUsed", ""),
                    "base_fee_per_gas": block.get("baseFeePerGas", ""),
                    "source": "evm_chain",
                }
                self._stamp_record(rec)
                records.append(rec)
            except Exception:
                continue

        return LoaderResult(source_name=self.source_name, records=records)
