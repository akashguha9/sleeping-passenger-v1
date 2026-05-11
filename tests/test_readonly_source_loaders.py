"""
Tests for Phase 2 Global Signal Fabric — read-only source loaders.

Goals
-----
1. All loaders are importable without network calls or API keys.
2. Missing API keys produce a clean SkipLoader, never a test failure.
3. No loader defines forbidden execution methods.
4. LoaderResult always carries advisory_status / human_review_required / execution_gate.
5. BrokerCSVLoader parses a real in-memory CSV without any network call.
6. safe_fetch() never raises — always returns a LoaderResult.
7. AST inspection: no forbidden callable definitions in any loader source file.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import os
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INGESTION_DIR = REPO_ROOT / "scripts" / "ingestion"

FORBIDDEN_METHODS = {
    "place_order",
    "modify_order",
    "cancel_order",
    "submit_order",
    "execute_trade",
    "auto_buy",
    "auto_sell",
}


def _loader_module_names() -> list[str]:
    if not INGESTION_DIR.exists():
        return []
    modules = []
    for path in sorted(INGESTION_DIR.glob("*.py")):
        if path.stem.startswith("_") and path.stem != "__init__":
            continue
        modules.append(f"scripts.ingestion.{path.stem}")
    return modules


def _all_loader_paths() -> list[Path]:
    if not INGESTION_DIR.exists():
        return []
    return sorted(
        p for p in INGESTION_DIR.glob("*.py")
        if not p.name.startswith("_") or p.name == "__init__.py"
    )


# ---------------------------------------------------------------------------
# Import safety — no network calls at import time
# ---------------------------------------------------------------------------


class TestImportSafety:
    @pytest.mark.parametrize("module_name", _loader_module_names())
    def test_importable_without_network(self, module_name: str) -> None:
        mod = importlib.import_module(module_name)
        assert mod is not None

    def test_base_loader_importable(self) -> None:
        from scripts.ingestion.base_loader import (
            BaseSourceLoader,
            LoaderResult,
            SkipLoader,
        )
        assert BaseSourceLoader is not None
        assert LoaderResult is not None
        assert SkipLoader is not None

    def test_ingestion_package_exports(self) -> None:
        import scripts.ingestion as pkg
        assert hasattr(pkg, "BaseSourceLoader")
        assert hasattr(pkg, "LoaderResult")
        assert hasattr(pkg, "SkipLoader")


# ---------------------------------------------------------------------------
# Advisory contract
# ---------------------------------------------------------------------------


class TestAdvisoryContract:
    def test_loader_result_defaults(self) -> None:
        from scripts.ingestion.base_loader import LoaderResult
        result = LoaderResult(source_name="test")
        assert result.advisory_status == "ADVISORY_ONLY"
        assert result.human_review_required is True
        assert result.execution_gate == "LOCKED"

    def test_loader_result_to_dict_carries_advisory_fields(self) -> None:
        from scripts.ingestion.base_loader import LoaderResult
        d = LoaderResult(source_name="src", records=[{"x": 1}]).to_dict()
        assert d["advisory_status"] == "ADVISORY_ONLY"
        assert d["human_review_required"] is True
        assert d["execution_gate"] == "LOCKED"
        assert d["record_count"] == 1

    def test_stamp_record_adds_advisory_fields(self) -> None:
        from scripts.ingestion.base_loader import BaseSourceLoader

        class _L(BaseSourceLoader):
            source_name = "test"
            def fetch(self) -> Any:
                return None  # type: ignore[return-value]

        rec: dict[str, Any] = {"ticker": "SPY"}
        stamped = _L._stamp_record(rec)
        assert stamped["advisory_status"] == "ADVISORY_ONLY"
        assert stamped["human_review_required"] is True
        assert stamped["execution_gate"] == "LOCKED"

    def test_stamp_record_does_not_overwrite_existing(self) -> None:
        from scripts.ingestion.base_loader import BaseSourceLoader

        class _L(BaseSourceLoader):
            source_name = "test"
            def fetch(self) -> Any:
                return None  # type: ignore[return-value]

        rec = {"advisory_status": "ADVISORY_ONLY", "human_review_required": True}
        stamped = _L._stamp_record(rec)
        assert stamped["advisory_status"] == "ADVISORY_ONLY"


# ---------------------------------------------------------------------------
# SkipLoader behaviour
# ---------------------------------------------------------------------------


class TestSkipLoader:
    def test_require_env_key_raises_when_missing(self) -> None:
        from scripts.ingestion.base_loader import BaseSourceLoader, SkipLoader

        class _L(BaseSourceLoader):
            source_name = "test"
            def fetch(self) -> Any:
                return None  # type: ignore[return-value]

        key = "__GSF_TEST_MISSING_KEY_XYZ__"
        os.environ.pop(key, None)
        with pytest.raises(SkipLoader):
            _L._require_env_key(key)

    def test_require_env_key_returns_value_when_set(self) -> None:
        from scripts.ingestion.base_loader import BaseSourceLoader

        class _L(BaseSourceLoader):
            source_name = "test"
            def fetch(self) -> Any:
                return None  # type: ignore[return-value]

        key = "__GSF_TEST_PRESENT_KEY_XYZ__"
        os.environ[key] = "test_value_123"
        try:
            val = _L._require_env_key(key)
            assert val == "test_value_123"
        finally:
            os.environ.pop(key, None)

    def test_safe_fetch_returns_loader_result_on_skip(self) -> None:
        from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

        class _Skip(BaseSourceLoader):
            source_name = "always_skip"
            def fetch(self) -> LoaderResult:
                raise SkipLoader("no key")

        result = _Skip().safe_fetch()
        assert isinstance(result, LoaderResult)
        assert result.skipped is True
        assert result.advisory_status == "ADVISORY_ONLY"
        assert result.human_review_required is True
        assert result.execution_gate == "LOCKED"

    def test_safe_fetch_returns_loader_result_on_unexpected_exception(self) -> None:
        from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult

        class _Fail(BaseSourceLoader):
            source_name = "always_fail"
            def fetch(self) -> LoaderResult:
                raise RuntimeError("unexpected error")

        result = _Fail().safe_fetch()
        assert isinstance(result, LoaderResult)
        assert result.skipped is True
        assert "RuntimeError" in result.skip_reason

    def test_skip_loader_is_exception_subclass(self) -> None:
        from scripts.ingestion.base_loader import SkipLoader
        assert issubclass(SkipLoader, Exception)


# ---------------------------------------------------------------------------
# No-execution source inspection
# ---------------------------------------------------------------------------


class TestNoExecutionInLoaders:
    @pytest.mark.parametrize("loader_path", _all_loader_paths())
    def test_no_forbidden_method_definitions(self, loader_path: Path) -> None:
        source = loader_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            pytest.fail(f"{loader_path.name}: SyntaxError: {exc}")

        defined: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(node.name)

        violations = defined & FORBIDDEN_METHODS
        assert not violations, (
            f"{loader_path.name} defines forbidden execution methods: {violations}"
        )

    def test_no_execution_call_literals_in_loaders(self) -> None:
        for path in _all_loader_paths():
            source = path.read_text(encoding="utf-8")
            for forbidden in ("place_order(", "execute_trade(", "submit_order("):
                assert forbidden not in source, (
                    f"{path.name} contains forbidden call: {forbidden!r}"
                )

    def test_no_paper_execution_imports(self) -> None:
        for path in _all_loader_paths():
            source = path.read_text(encoding="utf-8")
            for forbidden in (
                "import paper_execution",
                "from paper_execution",
                "import live_execution",
                "from live_execution",
            ):
                assert forbidden not in source, (
                    f"{path.name} contains forbidden import: {forbidden!r}"
                )


# ---------------------------------------------------------------------------
# Missing key → SkipLoader for key-requiring loaders
# ---------------------------------------------------------------------------


class TestMissingKeySkips:
    def _clear(self, *keys: str) -> None:
        for k in keys:
            os.environ.pop(k, None)

    def test_sec_edgar_skips_without_key(self) -> None:
        self._clear("SEC_USER_AGENT")
        from scripts.ingestion.sec_edgar_loader import SECEdgarLoader
        from scripts.ingestion.base_loader import SkipLoader
        with pytest.raises(SkipLoader):
            SECEdgarLoader().fetch()

    def test_etherscan_skips_without_key(self) -> None:
        self._clear("ETHERSCAN_API_KEY")
        from scripts.ingestion.etherscan_loader import EtherscanLoader
        from scripts.ingestion.base_loader import SkipLoader
        with pytest.raises(SkipLoader):
            EtherscanLoader(address="0xtest").fetch()

    def test_newsapi_skips_without_key(self) -> None:
        self._clear("NEWS_API_KEY", "NEWSAPI_KEY")
        from scripts.ingestion.newsapi_loader import NewsAPILoader
        from scripts.ingestion.base_loader import SkipLoader
        with pytest.raises(SkipLoader):
            NewsAPILoader().fetch()

    def test_event_registry_skips_without_key(self) -> None:
        self._clear("EVENT_REGISTRY_API_KEY")
        from scripts.ingestion.event_registry_loader import EventRegistryLoader
        from scripts.ingestion.base_loader import SkipLoader
        with pytest.raises(SkipLoader):
            EventRegistryLoader().fetch()

    def test_grok_skips_without_key(self) -> None:
        self._clear("XAI_API_KEY", "GROK_API_KEY")
        from scripts.ingestion.grok_interpreter import GrokInterpreter
        from scripts.ingestion.base_loader import SkipLoader
        with pytest.raises(SkipLoader):
            GrokInterpreter().fetch()

    def test_uk_companies_house_skips_without_key(self) -> None:
        self._clear("UK_COMPANIES_HOUSE_API_KEY")
        from scripts.ingestion.uk_companies_house_loader import UKCompaniesHouseLoader
        from scripts.ingestion.base_loader import SkipLoader
        with pytest.raises(SkipLoader):
            UKCompaniesHouseLoader(company_number="12345678").fetch()

    def test_japan_edinet_skips_without_key(self) -> None:
        self._clear("EDINET_API_KEY")
        from scripts.ingestion.japan_edinet_loader import JapanEDINETLoader
        from scripts.ingestion.base_loader import SkipLoader
        with pytest.raises(SkipLoader):
            JapanEDINETLoader().fetch()

    def test_solscan_skips_without_key(self) -> None:
        self._clear("SOLSCAN_API_KEY")
        from scripts.ingestion.solscan_loader import SolscanLoader
        from scripts.ingestion.base_loader import SkipLoader
        with pytest.raises(SkipLoader):
            SolscanLoader(address="test_address").fetch()

    def test_evm_chain_skips_without_key(self) -> None:
        self._clear("EVM_RPC_URL")
        from scripts.ingestion.evm_chain_loader import EVMChainLoader
        from scripts.ingestion.base_loader import SkipLoader
        with pytest.raises(SkipLoader):
            EVMChainLoader().fetch()

    def test_safe_fetch_never_raises_for_missing_key_loaders(self) -> None:
        from scripts.ingestion.base_loader import LoaderResult
        self._clear(
            "SEC_USER_AGENT", "ETHERSCAN_API_KEY", "NEWS_API_KEY", "NEWSAPI_KEY",
            "EVENT_REGISTRY_API_KEY", "XAI_API_KEY", "GROK_API_KEY",
        )
        from scripts.ingestion.sec_edgar_loader import SECEdgarLoader
        from scripts.ingestion.etherscan_loader import EtherscanLoader
        from scripts.ingestion.newsapi_loader import NewsAPILoader

        for loader in [SECEdgarLoader(), EtherscanLoader(), NewsAPILoader()]:
            result = loader.safe_fetch()
            assert isinstance(result, LoaderResult)
            assert result.skipped is True
            assert result.advisory_status == "ADVISORY_ONLY"


# ---------------------------------------------------------------------------
# Loader-specific: no-key loaders
# ---------------------------------------------------------------------------


class TestNoKeyLoaders:
    def test_broker_csv_skips_without_path(self) -> None:
        from scripts.ingestion.broker_csv_loader import BrokerCSVLoader
        from scripts.ingestion.base_loader import SkipLoader
        with pytest.raises(SkipLoader):
            BrokerCSVLoader(csv_path=None).fetch()

    def test_broker_csv_skips_nonexistent_file(self, scratch_path: Path) -> None:
        from scripts.ingestion.broker_csv_loader import BrokerCSVLoader
        from scripts.ingestion.base_loader import SkipLoader
        with pytest.raises(SkipLoader):
            BrokerCSVLoader(csv_path=scratch_path / "nonexistent.csv").fetch()

    def test_broker_csv_parses_valid_csv(self, scratch_path: Path) -> None:
        from scripts.ingestion.broker_csv_loader import BrokerCSVLoader
        csv_file = scratch_path / "portfolio.csv"
        csv_file.write_text(
            "ticker,date,close,volume\n"
            "SPY,2026-05-01,520.5,12345678\n"
            "QQQ,2026-05-01,440.2,9876543\n",
            encoding="utf-8",
        )
        result = BrokerCSVLoader(csv_path=csv_file).fetch()
        assert not result.skipped
        assert len(result.records) == 2
        assert result.records[0]["ticker"] == "SPY"
        assert result.advisory_status == "ADVISORY_ONLY"
        assert result.human_review_required is True

    def test_broker_csv_records_stamped(self, scratch_path: Path) -> None:
        from scripts.ingestion.broker_csv_loader import BrokerCSVLoader
        csv_file = scratch_path / "data.csv"
        csv_file.write_text("ticker,close\nGLD,180.0\n", encoding="utf-8")
        result = BrokerCSVLoader(csv_path=csv_file).fetch()
        for rec in result.records:
            assert rec.get("advisory_status") == "ADVISORY_ONLY"
            assert rec.get("human_review_required") is True
            assert rec.get("execution_gate") == "LOCKED"

    def test_broker_csv_empty_file(self, scratch_path: Path) -> None:
        from scripts.ingestion.broker_csv_loader import BrokerCSVLoader
        csv_file = scratch_path / "empty.csv"
        csv_file.write_text("ticker,close\n", encoding="utf-8")
        result = BrokerCSVLoader(csv_path=csv_file).fetch()
        assert not result.skipped
        assert result.records == []

    def test_polymarket_no_key_required(self) -> None:
        from scripts.ingestion.polymarket_loader import PolymarketLoader
        loader = PolymarketLoader()
        assert loader.requires_key is False
        assert loader.source_name == "polymarket"

    def test_gdelt_no_key_required(self) -> None:
        from scripts.ingestion.gdelt_loader import GDELTLoader
        loader = GDELTLoader()
        assert loader.requires_key is False
        assert loader.source_name == "gdelt"

    def test_market_data_loader_init(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader
        loader = MarketDataLoader(tickers=["SPY", "GLD"])
        assert loader.requires_key is False
        assert loader._tickers == ["SPY", "GLD"]

    def test_market_data_skips_without_yfinance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys
        from scripts.ingestion.base_loader import SkipLoader
        # Temporarily hide yfinance if present
        yf_backup = sys.modules.pop("yfinance", None)
        monkeypatch.setitem(sys.modules, "yfinance", None)  # type: ignore[arg-type]
        try:
            from scripts.ingestion.market_data_loader import MarketDataLoader
            with pytest.raises((SkipLoader, ImportError, TypeError)):
                MarketDataLoader().fetch()
        finally:
            if yf_backup is not None:
                sys.modules["yfinance"] = yf_backup
            else:
                sys.modules.pop("yfinance", None)


# ---------------------------------------------------------------------------
# Source name uniqueness
# ---------------------------------------------------------------------------


class TestSourceNames:
    def test_all_concrete_loaders_have_source_name(self) -> None:
        from scripts.ingestion.base_loader import BaseSourceLoader
        found = []
        for mod_name in _loader_module_names():
            if mod_name.endswith(".__init__") or mod_name.endswith(".base_loader"):
                continue
            mod = importlib.import_module(mod_name)
            for _name, obj in inspect.getmembers(mod, inspect.isclass):
                if (
                    issubclass(obj, BaseSourceLoader)
                    and obj is not BaseSourceLoader
                    and obj.__module__ == mod.__name__
                ):
                    assert obj.source_name, f"{obj.__name__} has empty source_name"
                    found.append(obj.source_name)
        assert len(found) > 0, "No concrete loaders found in scripts/ingestion/"

    def test_source_names_are_unique(self) -> None:
        from scripts.ingestion.base_loader import BaseSourceLoader
        seen: dict[str, str] = {}
        for mod_name in _loader_module_names():
            if mod_name.endswith(".__init__") or mod_name.endswith(".base_loader"):
                continue
            mod = importlib.import_module(mod_name)
            for _name, obj in inspect.getmembers(mod, inspect.isclass):
                if (
                    issubclass(obj, BaseSourceLoader)
                    and obj is not BaseSourceLoader
                    and obj.__module__ == mod.__name__
                ):
                    sn = obj.source_name
                    assert sn not in seen, (
                        f"Duplicate source_name {sn!r}: "
                        f"{obj.__name__} and {seen[sn]}"
                    )
                    seen[sn] = obj.__name__


# ---------------------------------------------------------------------------
# Config files exist and are parseable
# ---------------------------------------------------------------------------


class TestConfigFiles:
    def test_sources_yaml_exists(self) -> None:
        assert (REPO_ROOT / "configs" / "sources.yaml").exists()

    def test_source_rate_limits_yaml_exists(self) -> None:
        assert (REPO_ROOT / "configs" / "source_rate_limits.yaml").exists()

    def test_jurisdictions_yaml_exists(self) -> None:
        assert (REPO_ROOT / "configs" / "jurisdictions.yaml").exists()

    def test_api_keys_example_env_exists(self) -> None:
        assert (REPO_ROOT / "configs" / "api_keys.example.env").exists()

    def test_no_execution_policy_yaml_exists(self) -> None:
        assert (REPO_ROOT / "configs" / "no_execution_policy.yaml").exists()

    def test_sources_yaml_parseable(self) -> None:
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        path = REPO_ROOT / "configs" / "sources.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "advisory_contract" in data
        assert data["advisory_contract"]["advisory_status"] == "ADVISORY_ONLY"

    def test_no_execution_policy_parseable(self) -> None:
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        path = REPO_ROOT / "configs" / "no_execution_policy.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["advisory_status"] == "ADVISORY_ONLY"
        assert data["execution_gate"] == "LOCKED"
        assert data["human_review_required"] is True

    def test_jurisdictions_yaml_parseable(self) -> None:
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        path = REPO_ROOT / "configs" / "jurisdictions.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "jurisdictions" in data
        assert "US" in data["jurisdictions"]

    def test_api_keys_example_env_no_real_secrets(self) -> None:
        content = (REPO_ROOT / "configs" / "api_keys.example.env").read_text(
            encoding="utf-8"
        )
        # example file must contain placeholder patterns, not real keys
        for placeholder in ("your_", "_here", "example.com"):
            assert placeholder in content, (
                f"api_keys.example.env should contain placeholder {placeholder!r}"
            )
