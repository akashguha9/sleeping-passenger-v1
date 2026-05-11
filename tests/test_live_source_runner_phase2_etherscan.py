"""
Tests for Phase 2 live source runner — Etherscan.

Principles
----------
- Zero live network calls. All HTTP is intercepted with unittest.mock.patch.
- Missing ETHERSCAN_API_KEY skips cleanly with a meaningful reason string.
- Missing address skips cleanly with a meaningful reason string.
- Advisory contract enforced on all outputs: ADVISORY_ONLY, LOCKED, AI=0, BROKER=false.
- No broker API calls. No trade/execution fields in any report.
- No private-key, wallet, signing, transaction-send, or broadcast logic.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def etherscan_payload() -> dict:
    return {
        "status": "1",
        "message": "OK",
        "result": [
            {
                "hash": "0xabc123def456abc123def456abc123def456abc123def456abc123def456abc1",
                "from": "0xsender1234567890abcdef1234567890abcdef12",
                "to": "0xrecipient1234567890abcdef1234567890abcde",
                "value": "1000000000000000000",
                "blockNumber": "17000000",
                "timeStamp": "1680000000",
                "gasUsed": "21000",
            },
            {
                "hash": "0xdef456abc123def456abc123def456abc123def456abc123def456abc123def4",
                "from": "0xsender1234567890abcdef1234567890abcdef12",
                "to": "0xanotherrecipient1234567890abcdef12345678",
                "value": "500000000000000000",
                "blockNumber": "16999999",
                "timeStamp": "1679999900",
                "gasUsed": "21000",
            },
        ],
    }


_TEST_ADDRESS = "0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae"


def _mock_response(payload: object) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalizationEtherscan:
    def test_normalize_etherscan_fields(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_etherscan_record

        rec = {
            "hash": "0xabc123def456abc123def456abc123def456abc123def456abc123def456abc1",
            "from_address": "0xsender1234567890abcdef1234567890abcdef12",
            "to_address": "0xrecipient1234567890abcdef1234567890abcde",
            "value_wei": "1000000000000000000",
            "block_number": "17000000",
            "timestamp": "1680000000",
            "gas_used": "21000",
            "source": "etherscan",
        }
        out = _normalize_etherscan_record(rec)
        assert out["source_name"] == "etherscan"
        assert out["signal_type"] == "blockchain_transaction"
        assert out["hash"] == rec["hash"]
        assert out["from_address"] == rec["from_address"]
        assert out["to_address"] == rec["to_address"]
        assert out["value_wei"] == "1000000000000000000"
        assert out["block_number"] == "17000000"
        assert out["timestamp"] == "1680000000"
        assert out["gas_used"] == "21000"
        assert out["advisory_status"] == "ADVISORY_ONLY"
        assert out["human_review_required"] is True
        assert out["execution_gate"] == "LOCKED"
        assert out["ai_execution_count"] == 0
        assert out["broker_api_called"] is False

    def test_normalize_etherscan_event_id_format(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_etherscan_record

        rec = {"hash": "0xabc123def456abc123def456abc123def456abc123def456abc123def456abc1"}
        out = _normalize_etherscan_record(rec)
        assert out["event_id"].startswith("etherscan_")
        assert len(out["event_id"]) == len("etherscan_") + 16

    def test_stable_event_id_deterministic(self) -> None:
        from scripts.live_source_runner_phase2 import _stable_event_id

        tx = "0xabc123def456abc123def456abc123def456abc123def456abc123def456abc1"
        assert _stable_event_id("etherscan", tx) == _stable_event_id("etherscan", tx)

    def test_stable_event_id_differs_from_newsapi(self) -> None:
        from scripts.live_source_runner_phase2 import _stable_event_id

        key = "0xabc123"
        assert _stable_event_id("etherscan", key) != _stable_event_id("newsapi", key)

    def test_stable_event_id_differs_from_event_registry(self) -> None:
        from scripts.live_source_runner_phase2 import _stable_event_id

        key = "0xabc123"
        assert _stable_event_id("etherscan", key) != _stable_event_id("event_registry", key)

    def test_normalize_missing_hash_produces_empty_hash(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_etherscan_record

        rec = {"from_address": "0xsender"}
        out = _normalize_etherscan_record(rec)
        assert out["hash"] == ""
        assert out["event_id"].startswith("etherscan_")

    def test_normalize_title_contains_truncated_hash(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_etherscan_record

        tx_hash = "0xabc123def456abc123def456abc123def456abc123def456abc123def456abc1"
        rec = {"hash": tx_hash}
        out = _normalize_etherscan_record(rec)
        assert "Tx" in out["title"]
        assert out["title"].endswith("...")

    def test_normalize_missing_hash_produces_fallback_title(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_etherscan_record

        rec = {}
        out = _normalize_etherscan_record(rec)
        assert out["title"] == "Ethereum Transaction"

    def test_all_normalized_records_advisory_stamped(self, etherscan_payload: dict) -> None:
        from scripts.live_source_runner_phase2 import _normalize_etherscan_record

        for tx in etherscan_payload["result"]:
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
            out = _normalize_etherscan_record(rec)
            assert out["advisory_status"] == "ADVISORY_ONLY"
            assert out["human_review_required"] is True
            assert out["execution_gate"] == "LOCKED"
            assert out["ai_execution_count"] == 0
            assert out["broker_api_called"] is False


# ---------------------------------------------------------------------------
# Etherscan — mocked HTTP (GET)
# ---------------------------------------------------------------------------


class TestEtherscanMocked:
    def test_dry_run_fetches_correct_count(self, etherscan_payload: dict) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(etherscan_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(
                    dry_run=True,
                    etherscan_address=_TEST_ADDRESS,
                    sources=["etherscan"],
                )

            eth = next(s for s in report.sources if s.source_name == "etherscan")
            assert eth.status == "ok"
            assert eth.fetched_count == 2
            assert eth.events_persisted == 0
            assert report.advisory_status == "ADVISORY_ONLY"
            assert report.ai_execution_count == 0
            assert report.broker_api_called is False
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_dry_run_never_calls_persist(self, etherscan_payload: dict) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(etherscan_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                with patch(
                    "scripts.live_source_runner_phase2._persist_events"
                ) as persist_mock:
                    run_phase2(
                        dry_run=True,
                        etherscan_address=_TEST_ADDRESS,
                        sources=["etherscan"],
                    )
                    persist_mock.assert_not_called()
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_network_error_yields_skipped_source(self) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            with patch("requests.get", side_effect=Exception("network down")):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(
                    dry_run=True,
                    etherscan_address=_TEST_ADDRESS,
                    sources=["etherscan"],
                )

            eth = next(s for s in report.sources if s.source_name == "etherscan")
            assert eth.status in ("skipped", "http_error")
            assert eth.fetched_count == 0
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_api_error_status_yields_skipped_source(self) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        error_payload = {"status": "0", "message": "NOTOK", "result": []}
        try:
            with patch("requests.get", return_value=_mock_response(error_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(
                    dry_run=True,
                    etherscan_address=_TEST_ADDRESS,
                    sources=["etherscan"],
                )

            eth = next(s for s in report.sources if s.source_name == "etherscan")
            assert eth.status == "skipped"
            assert eth.fetched_count == 0
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_empty_results_list(self) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        empty_payload = {"status": "1", "message": "OK", "result": []}
        try:
            with patch("requests.get", return_value=_mock_response(empty_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(
                    dry_run=True,
                    etherscan_address=_TEST_ADDRESS,
                    sources=["etherscan"],
                )

            eth = next(s for s in report.sources if s.source_name == "etherscan")
            assert eth.status == "ok"
            assert eth.fetched_count == 0
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_total_fetched_accumulates(self, etherscan_payload: dict) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(etherscan_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(
                    dry_run=True,
                    etherscan_address=_TEST_ADDRESS,
                    sources=["etherscan"],
                )

            assert report.total_fetched == 2
            assert report.total_persisted == 0
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_records_have_no_duplicate_event_ids(self, etherscan_payload: dict) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(etherscan_payload)):
                from scripts.live_source_runner_phase2 import _normalize_etherscan_record
                from scripts.ingestion.etherscan_loader import EtherscanLoader

                loader = EtherscanLoader(address=_TEST_ADDRESS)
                result = loader.fetch()

            event_ids = [_normalize_etherscan_record(r)["event_id"] for r in result.records]
            assert len(event_ids) == len(set(event_ids))
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)


# ---------------------------------------------------------------------------
# Skip without ETHERSCAN_API_KEY
# ---------------------------------------------------------------------------


class TestEtherscanSkipWithoutKey:
    def test_skips_cleanly_without_env_var(self) -> None:
        os.environ.pop("ETHERSCAN_API_KEY", None)
        with patch("requests.get", side_effect=Exception("should not be called")):
            from scripts.live_source_runner_phase2 import run_phase2

            report = run_phase2(
                dry_run=True,
                etherscan_address=_TEST_ADDRESS,
                sources=["etherscan"],
            )

        eth = next(s for s in report.sources if s.source_name == "etherscan")
        assert eth.status == "skipped"
        assert eth.fetched_count == 0
        assert eth.skipped_reason

    def test_skip_reason_mentions_api_key(self) -> None:
        os.environ.pop("ETHERSCAN_API_KEY", None)
        from scripts.live_source_runner_phase2 import run_phase2

        report = run_phase2(
            dry_run=True,
            etherscan_address=_TEST_ADDRESS,
            sources=["etherscan"],
        )
        eth = next(s for s in report.sources if s.source_name == "etherscan")
        assert "ETHERSCAN_API_KEY" in eth.skipped_reason

    def test_skips_cleanly_without_address(self) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            with patch("requests.get", side_effect=Exception("should not be called")):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(
                    dry_run=True,
                    etherscan_address=None,
                    sources=["etherscan"],
                )

            eth = next(s for s in report.sources if s.source_name == "etherscan")
            assert eth.status == "skipped"
            assert eth.fetched_count == 0
            assert eth.skipped_reason
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_skip_reason_mentions_address_when_missing(self) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            from scripts.live_source_runner_phase2 import run_phase2

            report = run_phase2(
                dry_run=True,
                etherscan_address=None,
                sources=["etherscan"],
            )
            eth = next(s for s in report.sources if s.source_name == "etherscan")
            assert eth.skipped_reason
            assert "address" in eth.skipped_reason.lower() or "skip" in eth.skipped_reason.lower()
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_advisory_fields_intact_when_skipped(self) -> None:
        os.environ.pop("ETHERSCAN_API_KEY", None)
        from scripts.live_source_runner_phase2 import run_phase2

        report = run_phase2(dry_run=True, sources=["etherscan"])
        assert report.advisory_status == "ADVISORY_ONLY"
        assert report.execution_gate == "LOCKED"
        assert report.ai_execution_count == 0
        assert report.broker_api_called is False


# ---------------------------------------------------------------------------
# Write-mode persistence
# ---------------------------------------------------------------------------


class TestEtherscanWriteMode:
    def test_write_mode_calls_persist(self, etherscan_payload: dict) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(etherscan_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                with (
                    patch(
                        "scripts.live_source_runner_phase2._persist_events",
                        return_value=2,
                    ) as persist_mock,
                    patch("scripts.live_source_runner_phase2._log_run"),
                ):
                    report = run_phase2(
                        dry_run=False,
                        etherscan_address=_TEST_ADDRESS,
                        sources=["etherscan"],
                    )
                    persist_mock.assert_called_once()

            eth = next(s for s in report.sources if s.source_name == "etherscan")
            assert eth.events_persisted == 2
            assert report.total_persisted == 2
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_write_mode_logs_run(self, etherscan_payload: dict) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(etherscan_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                with (
                    patch(
                        "scripts.live_source_runner_phase2._persist_events",
                        return_value=2,
                    ),
                    patch("scripts.live_source_runner_phase2._log_run") as log_mock,
                ):
                    run_phase2(
                        dry_run=False,
                        etherscan_address=_TEST_ADDRESS,
                        sources=["etherscan"],
                    )
                    assert log_mock.call_count >= 1
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_dry_run_never_logs(self) -> None:
        os.environ.pop("ETHERSCAN_API_KEY", None)
        from scripts.live_source_runner_phase2 import run_phase2

        with patch("scripts.live_source_runner_phase2._log_run") as log_mock:
            run_phase2(dry_run=True, sources=["etherscan"])
            log_mock.assert_not_called()

    def test_persist_events_receives_correct_source_name(self, etherscan_payload: dict) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(etherscan_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                with (
                    patch(
                        "scripts.live_source_runner_phase2._persist_events",
                        return_value=2,
                    ) as persist_mock,
                    patch("scripts.live_source_runner_phase2._log_run"),
                ):
                    run_phase2(
                        dry_run=False,
                        etherscan_address=_TEST_ADDRESS,
                        sources=["etherscan"],
                    )
                    positional = persist_mock.call_args[0]
                    assert positional[1] == "etherscan"
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)


# ---------------------------------------------------------------------------
# No-execution safety
# ---------------------------------------------------------------------------


class TestEtherscanNoExecutionSafety:
    def test_runner_report_never_contains_trade_fields(self, etherscan_payload: dict) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(etherscan_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(
                    dry_run=True,
                    etherscan_address=_TEST_ADDRESS,
                    sources=["etherscan"],
                )

            d = report.to_dict()
            forbidden = {"trade_id", "broker_order_id", "executed", "order_id", "buy", "sell"}
            assert not forbidden & set(d.keys())
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_phase2_runner_no_forbidden_methods(self) -> None:
        runner_path = REPO_ROOT / "scripts" / "live_source_runner_phase2.py"
        source = runner_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {
            "place_order",
            "execute_trade",
            "submit_order",
            "auto_buy",
            "auto_sell",
            "cancel_order",
            "modify_order",
        }
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert not defined & forbidden

    def test_etherscan_loader_no_forbidden_methods(self) -> None:
        loader_path = REPO_ROOT / "scripts" / "ingestion" / "etherscan_loader.py"
        source = loader_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {
            "place_order",
            "execute_trade",
            "submit_order",
            "auto_buy",
            "auto_sell",
            "sign_transaction",
            "send_transaction",
            "broadcast",
            "transfer",
            "approve",
        }
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert not defined & forbidden

    def test_etherscan_loader_no_forbidden_keywords(self) -> None:
        loader_path = REPO_ROOT / "scripts" / "ingestion" / "etherscan_loader.py"
        source = loader_path.read_text(encoding="utf-8")
        forbidden_patterns = ["private_key", "wallet.sign", "send_raw", "eth_sendTransaction"]
        for pattern in forbidden_patterns:
            assert pattern not in source, f"Forbidden pattern found in loader: {pattern}"

    def test_normalized_event_ai_execution_count_is_zero(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_etherscan_record

        rec = {"hash": "0xabc123"}
        out = _normalize_etherscan_record(rec)
        assert out["ai_execution_count"] == 0

    def test_normalized_event_broker_api_called_is_false(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_etherscan_record

        rec = {"hash": "0xabc123"}
        out = _normalize_etherscan_record(rec)
        assert out["broker_api_called"] is False

    def test_normalized_event_execution_gate_is_locked(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_etherscan_record

        rec = {"hash": "0xabc123"}
        out = _normalize_etherscan_record(rec)
        assert out["execution_gate"] == "LOCKED"

    def test_normalized_event_advisory_status(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_etherscan_record

        rec = {"hash": "0xabc123"}
        out = _normalize_etherscan_record(rec)
        assert out["advisory_status"] == "ADVISORY_ONLY"

    def test_normalized_event_human_review_required(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_etherscan_record

        rec = {"hash": "0xabc123"}
        out = _normalize_etherscan_record(rec)
        assert out["human_review_required"] is True


# ---------------------------------------------------------------------------
# Duration tracking
# ---------------------------------------------------------------------------


class TestEtherscanDurationTracking:
    def test_duration_ms_is_non_negative_on_success(self, etherscan_payload: dict) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(etherscan_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(
                    dry_run=True,
                    etherscan_address=_TEST_ADDRESS,
                    sources=["etherscan"],
                )

            for src in report.sources:
                assert src.duration_ms >= 0
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_duration_ms_is_non_negative_on_skip(self) -> None:
        os.environ.pop("ETHERSCAN_API_KEY", None)
        from scripts.live_source_runner_phase2 import run_phase2

        report = run_phase2(dry_run=True, sources=["etherscan"])
        for src in report.sources:
            assert src.duration_ms >= 0


# ---------------------------------------------------------------------------
# EtherscanLoader unit tests
# ---------------------------------------------------------------------------


class TestEtherscanLoader:
    def test_loader_skips_without_api_key(self) -> None:
        os.environ.pop("ETHERSCAN_API_KEY", None)
        from scripts.ingestion.etherscan_loader import EtherscanLoader

        loader = EtherscanLoader(address=_TEST_ADDRESS)
        result = loader.safe_fetch()
        assert result.skipped is True
        assert "ETHERSCAN_API_KEY" in result.skip_reason

    def test_loader_skips_without_address(self) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            from scripts.ingestion.etherscan_loader import EtherscanLoader

            loader = EtherscanLoader(address=None)
            result = loader.safe_fetch()
            assert result.skipped is True
            assert result.skip_reason
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_loader_returns_records_with_key_and_address(self, etherscan_payload: dict) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(etherscan_payload)):
                from scripts.ingestion.etherscan_loader import EtherscanLoader

                loader = EtherscanLoader(address=_TEST_ADDRESS)
                result = loader.fetch()

            assert result.skipped is False
            assert len(result.records) == 2
            assert result.source_name == "etherscan"
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_loader_stamps_advisory_on_records(self, etherscan_payload: dict) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(etherscan_payload)):
                from scripts.ingestion.etherscan_loader import EtherscanLoader

                loader = EtherscanLoader(address=_TEST_ADDRESS)
                result = loader.fetch()

            for rec in result.records:
                assert rec["advisory_status"] == "ADVISORY_ONLY"
                assert rec["human_review_required"] is True
                assert rec["execution_gate"] == "LOCKED"
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_loader_result_advisory_status(self) -> None:
        os.environ.pop("ETHERSCAN_API_KEY", None)
        from scripts.ingestion.etherscan_loader import EtherscanLoader

        loader = EtherscanLoader(address=_TEST_ADDRESS)
        result = loader.safe_fetch()
        assert result.advisory_status == "ADVISORY_ONLY"
        assert result.human_review_required is True
        assert result.execution_gate == "LOCKED"

    def test_loader_records_have_expected_fields(self, etherscan_payload: dict) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(etherscan_payload)):
                from scripts.ingestion.etherscan_loader import EtherscanLoader

                loader = EtherscanLoader(address=_TEST_ADDRESS)
                result = loader.fetch()

            for rec in result.records:
                assert "hash" in rec
                assert "from_address" in rec
                assert "to_address" in rec
                assert "value_wei" in rec
                assert "block_number" in rec
                assert "timestamp" in rec
                assert "gas_used" in rec
                assert rec["source"] == "etherscan"
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_loader_network_error_safe_fetch(self) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            with patch("requests.get", side_effect=Exception("timeout")):
                from scripts.ingestion.etherscan_loader import EtherscanLoader

                loader = EtherscanLoader(address=_TEST_ADDRESS)
                result = loader.safe_fetch()

            assert result.skipped is True
            assert "unreachable" in result.skip_reason.lower()
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_loader_source_name_is_etherscan(self) -> None:
        from scripts.ingestion.etherscan_loader import EtherscanLoader

        loader = EtherscanLoader()
        assert loader.source_name == "etherscan"

    def test_loader_max_records_respected(self, etherscan_payload: dict) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(etherscan_payload)):
                from scripts.ingestion.etherscan_loader import EtherscanLoader

                loader = EtherscanLoader(address=_TEST_ADDRESS, max_records=1)
                result = loader.fetch()

            assert len(result.records) == 1
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_loader_non_dict_results_skipped(self) -> None:
        os.environ["ETHERSCAN_API_KEY"] = "test-etherscan-key-mock"
        payload = {"status": "1", "message": "OK", "result": ["not-a-dict", None, 42]}
        try:
            with patch("requests.get", return_value=_mock_response(payload)):
                from scripts.ingestion.etherscan_loader import EtherscanLoader

                loader = EtherscanLoader(address=_TEST_ADDRESS)
                result = loader.fetch()

            assert result.records == []
        finally:
            os.environ.pop("ETHERSCAN_API_KEY", None)
