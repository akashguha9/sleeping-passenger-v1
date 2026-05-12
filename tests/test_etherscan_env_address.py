"""
Tests for Etherscan loader — env address fallback, CLI override,
placeholder rejection, malformed rejection, mocked success.

All HTTP is mocked. No live network calls.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from scripts.ingestion.etherscan_loader import (
    EtherscanLoader,
    _validate_eth_address,
    _resolve_address,
    _ENV_ADDRESS_VARS,
)
from scripts.ingestion.base_loader import SkipLoader, LoaderResult

_VALID_ADDR = "0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae"
_VALID_ADDR_2 = "0xab5801a7d398351b8be11c439e05c5b3259aec9b"


def _mock_etherscan_response(txs: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "status": "1",
        "message": "OK",
        "result": txs,
    }
    return resp


_SAMPLE_TXS = [
    {
        "hash": "0xabc123def456abc123def456abc123def456abc123def456abc123def456abc1",
        "from": "0xsender1234567890abcdef1234567890abcdef12",
        "to": _VALID_ADDR,
        "value": "1000000000000000000",
        "blockNumber": "17000000",
        "timeStamp": "1680000000",
        "gasUsed": "21000",
    },
]


class TestEthAddressValidation:
    def test_valid_address(self) -> None:
        assert _validate_eth_address(_VALID_ADDR) is None

    def test_valid_address_uppercase(self) -> None:
        assert _validate_eth_address(_VALID_ADDR.upper()) is None

    def test_empty_is_invalid(self) -> None:
        assert _validate_eth_address("") is not None

    def test_too_short_is_invalid(self) -> None:
        assert _validate_eth_address("0xabcd") is not None

    def test_no_0x_prefix_is_invalid(self) -> None:
        assert _validate_eth_address("de0b295669a9fd93d5f28d9ec85e40f4cb697bae") is not None

    def test_placeholder_0xYOUR_rejected(self) -> None:
        err = _validate_eth_address("0xYOUR_PUBLIC_ETH_ADDRESS")
        assert err is not None
        assert "placeholder" in err.lower()

    def test_placeholder_wallet_address_rejected(self) -> None:
        err = _validate_eth_address("WALLET_ADDRESS")
        assert err is not None

    def test_placeholder_insert_rejected(self) -> None:
        err = _validate_eth_address("0xINSERT_HERE_1234567890abcdef1234567890a")
        assert err is not None

    def test_placeholder_example_rejected(self) -> None:
        err = _validate_eth_address("0xEXAMPLE1234567890abcdef1234567890abcdef")
        assert err is not None

    def test_non_hex_chars_invalid(self) -> None:
        assert _validate_eth_address("0x" + "g" * 40) is not None


class TestResolveAddress:
    def test_explicit_overrides_env(self) -> None:
        with patch.dict(os.environ, {"ETHERSCAN_ADDRESS": _VALID_ADDR_2}):
            addr = _resolve_address(_VALID_ADDR)
        assert addr == _VALID_ADDR

    def test_env_etherscan_address_used_when_no_explicit(self) -> None:
        env = {k: "" for k in _ENV_ADDRESS_VARS}
        env["ETHERSCAN_ADDRESS"] = _VALID_ADDR
        with patch.dict(os.environ, env):
            addr = _resolve_address(None)
        assert addr == _VALID_ADDR

    def test_env_ethereum_address_fallback(self) -> None:
        env = {k: "" for k in _ENV_ADDRESS_VARS}
        env["ETHEREUM_ADDRESS"] = _VALID_ADDR
        with patch.dict(os.environ, env):
            addr = _resolve_address(None)
        assert addr == _VALID_ADDR

    def test_env_public_eth_address_fallback(self) -> None:
        env = {k: "" for k in _ENV_ADDRESS_VARS}
        env["PUBLIC_ETH_ADDRESS"] = _VALID_ADDR
        with patch.dict(os.environ, env):
            addr = _resolve_address(None)
        assert addr == _VALID_ADDR

    def test_none_when_no_explicit_no_env(self) -> None:
        env = {k: "" for k in _ENV_ADDRESS_VARS}
        with patch.dict(os.environ, env):
            addr = _resolve_address(None)
        assert addr is None

    def test_empty_explicit_falls_to_env(self) -> None:
        with patch.dict(os.environ, {"ETHERSCAN_ADDRESS": _VALID_ADDR}):
            addr = _resolve_address("")
        # Empty string is falsy — falls through to env
        assert addr == _VALID_ADDR


class TestEtherscanLoaderMissingKey:
    def test_skip_when_no_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ETHERSCAN_API_KEY", None)
            loader = EtherscanLoader(address=_VALID_ADDR)
            with pytest.raises(SkipLoader) as exc_info:
                loader.fetch()
        assert "ETHERSCAN_API_KEY" in str(exc_info.value)


class TestEtherscanLoaderNoAddress:
    def test_skip_when_no_address_no_env(self) -> None:
        env = {k: "" for k in _ENV_ADDRESS_VARS}
        env["ETHERSCAN_API_KEY"] = "testkey"
        with patch.dict(os.environ, env):
            loader = EtherscanLoader(address=None)
            with pytest.raises(SkipLoader) as exc_info:
                loader.fetch()
        assert "address" in str(exc_info.value).lower()

    def test_skip_reason_mentions_env_vars(self) -> None:
        env = {k: "" for k in _ENV_ADDRESS_VARS}
        env["ETHERSCAN_API_KEY"] = "testkey"
        with patch.dict(os.environ, env):
            loader = EtherscanLoader(address=None)
            result = loader.safe_fetch()
        assert result.skipped
        assert any(v in result.skip_reason for v in _ENV_ADDRESS_VARS)


class TestEtherscanEnvAddressFallback:
    def test_env_address_used_when_no_cli_address(self) -> None:
        env = {k: "" for k in _ENV_ADDRESS_VARS}
        env["ETHERSCAN_API_KEY"] = "testkey"
        env["ETHERSCAN_ADDRESS"] = _VALID_ADDR
        with patch.dict(os.environ, env):
            with patch("requests.get", return_value=_mock_etherscan_response(_SAMPLE_TXS)) as mg:
                loader = EtherscanLoader(address=None)
                result = loader.fetch()
        assert not result.skipped
        # Verify the address was used in the request
        params = mg.call_args[1].get("params", mg.call_args[0][1] if len(mg.call_args[0]) > 1 else {})
        if isinstance(params, dict):
            assert params.get("address") == _VALID_ADDR

    def test_placeholder_env_address_rejected(self) -> None:
        env = {k: "" for k in _ENV_ADDRESS_VARS}
        env["ETHERSCAN_API_KEY"] = "testkey"
        env["ETHERSCAN_ADDRESS"] = "0xYOUR_PUBLIC_ETH_ADDRESS_HERE_12345678901"
        with patch.dict(os.environ, env):
            loader = EtherscanLoader(address=None)
            result = loader.safe_fetch()
        assert result.skipped
        assert "placeholder" in result.skip_reason.lower()

    def test_malformed_env_address_rejected(self) -> None:
        env = {k: "" for k in _ENV_ADDRESS_VARS}
        env["ETHERSCAN_API_KEY"] = "testkey"
        env["ETHERSCAN_ADDRESS"] = "not-a-valid-address"
        with patch.dict(os.environ, env):
            loader = EtherscanLoader(address=None)
            result = loader.safe_fetch()
        assert result.skipped


class TestEtherscanLoaderMockedSuccess:
    def test_fetch_returns_loader_result(self) -> None:
        with patch.dict(os.environ, {"ETHERSCAN_API_KEY": "testkey"}):
            with patch("requests.get", return_value=_mock_etherscan_response(_SAMPLE_TXS)):
                loader = EtherscanLoader(address=_VALID_ADDR)
                result = loader.fetch()
        assert isinstance(result, LoaderResult)
        assert not result.skipped
        assert len(result.records) == 1

    def test_fetch_records_have_advisory_stamps(self) -> None:
        with patch.dict(os.environ, {"ETHERSCAN_API_KEY": "testkey"}):
            with patch("requests.get", return_value=_mock_etherscan_response(_SAMPLE_TXS)):
                loader = EtherscanLoader(address=_VALID_ADDR)
                result = loader.fetch()
        for rec in result.records:
            assert rec["advisory_status"] == "ADVISORY_ONLY"
            assert rec["human_review_required"] is True
            assert rec["execution_gate"] == "LOCKED"

    def test_fetch_records_have_tx_fields(self) -> None:
        with patch.dict(os.environ, {"ETHERSCAN_API_KEY": "testkey"}):
            with patch("requests.get", return_value=_mock_etherscan_response(_SAMPLE_TXS)):
                loader = EtherscanLoader(address=_VALID_ADDR)
                result = loader.fetch()
        rec = result.records[0]
        assert "hash" in rec
        assert "from_address" in rec
        assert "to_address" in rec
        assert "value_wei" in rec

    def test_no_transactions_returns_empty(self) -> None:
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"status": "0", "message": "No transactions found", "result": []}
        with patch.dict(os.environ, {"ETHERSCAN_API_KEY": "testkey"}):
            with patch("requests.get", return_value=resp):
                loader = EtherscanLoader(address=_VALID_ADDR)
                result = loader.fetch()
        assert not result.skipped
        assert result.records == []

    def test_cli_address_overrides_env(self) -> None:
        env = {k: "" for k in _ENV_ADDRESS_VARS}
        env["ETHERSCAN_API_KEY"] = "testkey"
        env["ETHERSCAN_ADDRESS"] = _VALID_ADDR_2
        with patch.dict(os.environ, env):
            with patch("requests.get", return_value=_mock_etherscan_response(_SAMPLE_TXS)) as mg:
                loader = EtherscanLoader(address=_VALID_ADDR)
                loader.fetch()
        call_params = mg.call_args[1].get("params", {})
        if isinstance(call_params, dict):
            assert call_params.get("address") == _VALID_ADDR


class TestEtherscanSafety:
    def test_no_private_key_logic(self) -> None:
        import ast
        from pathlib import Path
        src = (Path(__file__).parents[1] / "scripts" / "ingestion" / "etherscan_loader.py").read_text()
        assert "private_key" not in src.lower()
        assert "sign_transaction" not in src.lower()
        assert "send_transaction" not in src.lower()
        assert "broadcast" not in src.lower()

    def test_source_name(self) -> None:
        assert EtherscanLoader.source_name == "etherscan"

    def test_requires_key(self) -> None:
        assert EtherscanLoader.requires_key is True
