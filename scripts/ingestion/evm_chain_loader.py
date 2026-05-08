"""Generic EVM-chain placeholder loader (read-only).

Covers BscScan / PolygonScan / Arbiscan / BaseScan endpoints. Each chain has
its own env-var key; the loader skips cleanly when the requested chain has no
key set. No signing, no trading.
"""
from __future__ import annotations

from typing import Any

from scripts.ingestion.base_loader import BaseLoader, LoaderResult
from scripts.ingestion._placeholder import PlaceholderLoader

CHAIN_ENV = {
    "bsc": "BSCSCAN_API_KEY",
    "polygon": "POLYGONSCAN_API_KEY",
    "arbitrum": "ARBISCAN_API_KEY",
    "base": "BASESCAN_API_KEY",
}


class EVMChainLoader(PlaceholderLoader):
    source_name = "evm_chain"
    source_type = "onchain"
    required_env: tuple[str, ...] = ()

    def fetch(self, *, chain: str = "bsc", **_: Any) -> LoaderResult:  # type: ignore[override]
        env_name = CHAIN_ENV.get(chain.lower())
        if env_name is None:
            return self.fail(f"unsupported chain {chain!r}")
        if not BaseLoader.env(env_name):
            return self.skip(f"{env_name} not set; {chain} placeholder")
        return self.ok([], note=f"{chain} placeholder; no upstream wired yet")
