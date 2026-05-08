"""Etherscan read-only loader.

Supports a small set of read-only modules:
    - account.tokentx       (ERC-20 transfers for an address)
    - account.txlist        (normal txs for an address)
    - account.balance       (ETH balance)

NO signing, NO trading. ETHERSCAN_API_KEY is required; without it the loader
skips cleanly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scripts.ingestion.base_loader import BaseLoader, LoaderResult
from scripts.normalization.signal_event_schema import NumericSignal, SignalEvent
from scripts.normalization.signal_processor import process_signal

ETHERSCAN_BASE = "https://api.etherscan.io/api"


class EtherscanLoader(BaseLoader):
    source_name = "etherscan"
    source_type = "onchain"

    def fetch(self, *, address: str, action: str = "tokentx", limit: int = 25) -> LoaderResult:
        api_key = self.env("ETHERSCAN_API_KEY")
        if not api_key:
            return self.skip("ETHERSCAN_API_KEY not set")
        if action not in {"tokentx", "txlist", "balance"}:
            return self.fail(f"unsupported action {action!r}")
        params = {
            "module": "account",
            "action": action,
            "address": address,
            "page": 1,
            "offset": limit,
            "sort": "desc",
            "apikey": api_key,
        }
        try:
            data = self._http_get(ETHERSCAN_BASE, params=params)
        except Exception as exc:
            return self.fail(f"etherscan fetch failed: {exc}", address=address, action=action)

        result = data.get("result") if isinstance(data, dict) else None
        if action == "balance":
            events = [self._normalize_balance(address, result)]
        elif isinstance(result, list):
            events = [self.normalize(row) for row in result]
        else:
            events = []
        return self.ok(events, address=address, action=action)

    def normalize(self, raw: dict[str, Any]) -> SignalEvent:
        try:
            value_raw = float(raw.get("value") or 0.0)
            decimals = int(raw.get("tokenDecimal") or 18)
            value_token = value_raw / (10 ** decimals)
        except (TypeError, ValueError):
            value_token = 0.0
        ts_raw = raw.get("timeStamp")
        ts = None
        if ts_raw:
            try:
                ts = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc).isoformat()
            except (TypeError, ValueError):
                ts = None
        symbol = raw.get("tokenSymbol") or "ETH"
        tx_hash = raw.get("hash")
        url = f"https://etherscan.io/tx/{tx_hash}" if tx_hash else None
        raw_event: dict[str, Any] = {
            "source_name": self.source_name,
            "source_type": self.source_type,
            "jurisdiction": "GLOBAL",
            "headline_or_label": f"{symbol} transfer {value_token:g}",
            "raw_text_or_summary": (
                f"from {raw.get('from')} to {raw.get('to')} value={value_token:g} {symbol}"
            ),
            "url": url,
            "event_type": "token_transfer",
            "asset_tags": [symbol] if symbol else [],
            "numeric_signal": NumericSignal(transfer_value_usd=None),
            "metadata": {
                "from": raw.get("from"),
                "to": raw.get("to"),
                "tx_hash": tx_hash,
                "token_symbol": symbol,
                "value_token": value_token,
            },
        }
        if ts:
            raw_event["timestamp_utc"] = ts
        return process_signal(raw_event)

    def _normalize_balance(self, address: str, result: Any) -> SignalEvent:
        try:
            wei = float(result or 0)
            eth = wei / 1e18
        except (TypeError, ValueError):
            eth = 0.0
        raw_event: dict[str, Any] = {
            "source_name": self.source_name,
            "source_type": self.source_type,
            "jurisdiction": "GLOBAL",
            "headline_or_label": f"ETH balance {eth:g}",
            "raw_text_or_summary": f"address {address} balance {eth:g} ETH",
            "url": f"https://etherscan.io/address/{address}",
            "event_type": "balance_snapshot",
            "asset_tags": ["ETH"],
            "numeric_signal": NumericSignal(),
            "metadata": {"address": address, "balance_eth": eth},
        }
        return process_signal(raw_event)
