"""
Phase C.10 Final Integration Audit Tests.

Covers:
1. Source registry completeness (all 11 sources registered in both runners)
2. Safety invariant completeness (advisory_status, execution_gate,
   human_review_required, ai_execution_count, broker_api_called, broker_order_id)
3. Normalizer output invariants — every normalizer returns required safety fields
4. Forbidden execution endpoint absence in api_server.py
5. CLI source support (phase1 and phase2 CLI _SUPPORTED_SOURCES lists)
6. Frontend source filter coverage (reads index.ts and live-signals/page.tsx)
7. README Phase C Integrated Source Matrix coverage
8. phase_c_final_audit.py runs and returns 0

No live internet required. All loader calls are mocked.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Repo root on sys.path
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# ---------------------------------------------------------------------------
# Expected source registry
# ---------------------------------------------------------------------------

PHASE1_SOURCES = ["polymarket", "gdelt", "sec_edgar"]
PHASE2_SOURCES = [
    "newsapi",
    "event_registry",
    "etherscan",
    "grok_xai",
    "market_data",
    "india",
    "global_filings",
    "asia_disclosure",
]
ALL_SOURCES = PHASE1_SOURCES + PHASE2_SOURCES

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------

_RUNNER1 = _REPO / "scripts" / "live_source_runner.py"
_RUNNER2 = _REPO / "scripts" / "live_source_runner_phase2.py"
_CLI1 = _REPO / "scripts" / "run_live_sources_phase1.py"
_CLI2 = _REPO / "scripts" / "run_live_sources_phase2.py"
_API = _REPO / "scripts" / "api_server.py"
_TS_TYPES = _REPO / "frontend" / "src" / "types" / "index.ts"
_UI_PAGE = _REPO / "frontend" / "src" / "app" / "live-signals" / "page.tsx"
_README = _REPO / "README.md"
_AUDIT_SCRIPT = _REPO / "scripts" / "phase_c_final_audit.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ===========================================================================
# 1. File existence
# ===========================================================================


class TestFileExistence:
    def test_runner1_exists(self):
        assert _RUNNER1.exists(), f"Missing: {_RUNNER1}"

    def test_runner2_exists(self):
        assert _RUNNER2.exists(), f"Missing: {_RUNNER2}"

    def test_cli1_exists(self):
        assert _CLI1.exists(), f"Missing: {_CLI1}"

    def test_cli2_exists(self):
        assert _CLI2.exists(), f"Missing: {_CLI2}"

    def test_api_server_exists(self):
        assert _API.exists(), f"Missing: {_API}"

    def test_ts_types_exists(self):
        assert _TS_TYPES.exists(), f"Missing: {_TS_TYPES}"

    def test_ui_page_exists(self):
        assert _UI_PAGE.exists(), f"Missing: {_UI_PAGE}"

    def test_readme_exists(self):
        assert _README.exists(), f"Missing: {_README}"

    def test_audit_script_exists(self):
        assert _AUDIT_SCRIPT.exists(), f"Missing: {_AUDIT_SCRIPT}"


# ===========================================================================
# 2. Source registry completeness
# ===========================================================================


class TestSourceRegistryCompleteness:
    """Verify all expected sources appear in every registry location."""

    def test_runner1_contains_all_phase1_sources(self):
        content = _read(_RUNNER1)
        for src in PHASE1_SOURCES:
            assert f'"{src}"' in content or f"'{src}'" in content, \
                f"Phase 1 runner missing source: '{src}'"

    def test_runner1_normalizers_cover_phase1(self):
        content = _read(_RUNNER1)
        assert "_NORMALIZERS" in content, "live_source_runner.py missing _NORMALIZERS dict"
        for src in PHASE1_SOURCES:
            assert src in content, f"_NORMALIZERS in runner1 missing '{src}'"

    def test_runner2_contains_all_phase2_sources(self):
        content = _read(_RUNNER2)
        for src in PHASE2_SOURCES:
            assert f'"{src}"' in content or f"'{src}'" in content, \
                f"Phase 2 runner missing source: '{src}'"

    def test_runner2_normalizers_cover_phase2(self):
        content = _read(_RUNNER2)
        assert "_NORMALIZERS" in content, "live_source_runner_phase2.py missing _NORMALIZERS dict"
        for src in PHASE2_SOURCES:
            assert src in content, f"_NORMALIZERS in runner2 missing '{src}'"

    def test_cli1_supported_sources(self):
        content = _read(_CLI1)
        for src in PHASE1_SOURCES:
            assert src in content, f"CLI1 missing source '{src}' in _SUPPORTED_SOURCES"

    def test_cli2_supported_sources(self):
        content = _read(_CLI2)
        for src in PHASE2_SOURCES:
            assert src in content, f"CLI2 missing source '{src}' in _SUPPORTED_SOURCES"

    def test_typescript_live_signal_source_type(self):
        content = _read(_TS_TYPES)
        assert "LiveSignalSource" in content, "index.ts missing LiveSignalSource type"
        for src in ALL_SOURCES:
            assert f"'{src}'" in content or f'"{src}"' in content, \
                f"LiveSignalSource in index.ts missing '{src}'"

    def test_frontend_page_source_options(self):
        content = _read(_UI_PAGE)
        assert "SOURCE_OPTIONS" in content, "page.tsx missing SOURCE_OPTIONS"
        for src in ALL_SOURCES:
            assert f"'{src}'" in content or f'"{src}"' in content, \
                f"SOURCE_OPTIONS in page.tsx missing '{src}'"

    def test_frontend_page_source_labels(self):
        content = _read(_UI_PAGE)
        expected_labels = [
            "All Sources",
            "Polymarket",
            "GDELT",
            "SEC EDGAR",
            "NewsAPI",
            "Event Registry",
            "Etherscan",
            "Grok/xAI",
            "Market Data",
            "India",
            "Global Filings",
            "Asia Disclosure",
        ]
        for label in expected_labels:
            assert label in content, f"page.tsx missing source label: '{label}'"


# ===========================================================================
# 3. Safety invariant constants in runner modules
# ===========================================================================


class TestSafetyInvariantConstants:
    def test_runner1_advisory_status_constant(self):
        content = _read(_RUNNER1)
        assert '_ADVISORY_STATUS = "ADVISORY_ONLY"' in content or \
               "_ADVISORY_STATUS = 'ADVISORY_ONLY'" in content, \
            "runner1 missing _ADVISORY_STATUS = 'ADVISORY_ONLY'"

    def test_runner1_execution_gate_constant(self):
        content = _read(_RUNNER1)
        assert '_EXECUTION_GATE = "LOCKED"' in content or \
               "_EXECUTION_GATE = 'LOCKED'" in content, \
            "runner1 missing _EXECUTION_GATE = 'LOCKED'"

    def test_runner1_ai_execution_count_zero(self):
        content = _read(_RUNNER1)
        assert "_AI_EXECUTION_COUNT = 0" in content, \
            "runner1 missing _AI_EXECUTION_COUNT = 0"

    def test_runner2_advisory_status_constant(self):
        content = _read(_RUNNER2)
        assert '_ADVISORY_STATUS = "ADVISORY_ONLY"' in content or \
               "_ADVISORY_STATUS = 'ADVISORY_ONLY'" in content, \
            "runner2 missing _ADVISORY_STATUS = 'ADVISORY_ONLY'"

    def test_runner2_execution_gate_constant(self):
        content = _read(_RUNNER2)
        assert '_EXECUTION_GATE = "LOCKED"' in content or \
               "_EXECUTION_GATE = 'LOCKED'" in content, \
            "runner2 missing _EXECUTION_GATE = 'LOCKED'"

    def test_runner2_ai_execution_count_zero(self):
        content = _read(_RUNNER2)
        assert "_AI_EXECUTION_COUNT = 0" in content, \
            "runner2 missing _AI_EXECUTION_COUNT = 0"

    def test_runner2_broker_api_called_false(self):
        content = _read(_RUNNER2)
        assert "_BROKER_API_CALLED = False" in content, \
            "runner2 missing _BROKER_API_CALLED = False"

    def test_runner2_broker_order_id_none(self):
        content = _read(_RUNNER2)
        assert "broker_order_id" in content, \
            "runner2 missing broker_order_id field"
        assert '"NONE"' in content or "'NONE'" in content, \
            "runner2 missing broker_order_id = 'NONE' sentinel"

    def test_all_runner2_normalizers_set_human_review(self):
        content = _read(_RUNNER2)
        assert content.count("human_review_required") >= len(PHASE2_SOURCES), \
            "Not all Phase 2 normalizers set human_review_required"


# ===========================================================================
# 4. Normalizer output invariants (unit-level)
# ===========================================================================


class TestNormalizerOutputInvariants:
    """Import normalizer functions directly and verify safety fields on output."""

    def _assert_invariants(self, record: dict, source: str) -> None:
        assert record.get("advisory_status") == "ADVISORY_ONLY", \
            f"{source}: advisory_status != ADVISORY_ONLY, got {record.get('advisory_status')!r}"
        assert record.get("execution_gate") == "LOCKED", \
            f"{source}: execution_gate != LOCKED, got {record.get('execution_gate')!r}"
        assert record.get("human_review_required") is True, \
            f"{source}: human_review_required != True, got {record.get('human_review_required')!r}"
        assert record.get("ai_execution_count") == 0, \
            f"{source}: ai_execution_count != 0, got {record.get('ai_execution_count')!r}"
        assert "event_id" in record, f"{source}: missing event_id"
        assert record.get("source_name") == source, \
            f"{source}: source_name mismatch, got {record.get('source_name')!r}"

    def test_polymarket_normalizer_invariants(self):
        from scripts.live_source_runner import _normalize_polymarket_record
        rec = _normalize_polymarket_record({
            "market_id": "test-mkt-1",
            "question": "Will the Fed cut rates in 2026?",
            "volume": 1000,
            "liquidity": 500,
            "end_date": "2026-12-31",
            "active": True,
        })
        self._assert_invariants(rec, "polymarket")

    def test_gdelt_normalizer_invariants(self):
        from scripts.live_source_runner import _normalize_gdelt_record
        rec = _normalize_gdelt_record({
            "url": "https://example.com/article",
            "title": "Test GDELT Article",
            "seendate": "2026-05-10",
            "domain": "example.com",
            "language": "en",
            "sourcecountry": "US",
        })
        self._assert_invariants(rec, "gdelt")

    def test_sec_edgar_normalizer_invariants(self):
        from scripts.live_source_runner import _normalize_sec_record
        rec = _normalize_sec_record({
            "cik": "0000320193",
            "form_type": "10-K",
            "filing_date": "2026-01-15",
            "accession_number": "0000320193-26-000001",
        })
        self._assert_invariants(rec, "sec_edgar")

    def test_newsapi_normalizer_invariants(self):
        from scripts.live_source_runner_phase2 import _normalize_newsapi_record
        rec = _normalize_newsapi_record({
            "url": "https://example.com/news",
            "title": "Test NewsAPI Article",
            "description": "A test news article",
            "published_at": "2026-05-10T12:00:00Z",
            "source_name": "ExampleNews",
        })
        self._assert_invariants(rec, "newsapi")
        assert rec.get("broker_api_called") is False, \
            "newsapi: broker_api_called must be False"

    def test_event_registry_normalizer_invariants(self):
        from scripts.live_source_runner_phase2 import _normalize_event_registry_record
        rec = _normalize_event_registry_record({
            "url": "https://example.com/er",
            "title": "Event Registry Article",
            "date_time": "2026-05-10T12:00:00Z",
            "source_name": "ERSource",
            "body": "Article body text",
        })
        self._assert_invariants(rec, "event_registry")
        assert rec.get("broker_api_called") is False

    def test_etherscan_normalizer_invariants(self):
        from scripts.live_source_runner_phase2 import _normalize_etherscan_record
        rec = _normalize_etherscan_record({
            "hash": "0xabc123def456789",
            "from_address": "0xSender",
            "to_address": "0xReceiver",
            "value_wei": "1000000000000000000",
            "block_number": "12345678",
            "timestamp": "1715347200",
            "gas_used": "21000",
        })
        self._assert_invariants(rec, "etherscan")
        assert rec.get("broker_api_called") is False

    def test_grok_xai_normalizer_invariants(self):
        from scripts.live_source_runner_phase2 import _normalize_grok_record
        rec = _normalize_grok_record({
            "source_prompt": "What macro themes dominate?",
            "created_at": "2026-05-10T12:00:00Z",
            "model_name": "grok-beta",
            "interpreted_topic": "Rate policy uncertainty",
            "narrative_frame": "central bank dovish pivot",
            "contradiction_flags": [],
            "confidence_score": 0.72,
            "summary_text": "Test summary",
            "grok_response": "Full grok response text",
        })
        self._assert_invariants(rec, "grok_xai")
        assert rec.get("broker_api_called") is False

    def test_market_data_normalizer_invariants(self):
        from scripts.live_source_runner_phase2 import _normalize_market_data_record
        rec = _normalize_market_data_record({
            "symbol": "SPY",
            "provider": "yahoo",
            "period": "5d",
            "interval": "1d",
            "latest_price": 512.34,
            "previous_close": 510.00,
            "price_change": 2.34,
            "price_change_pct": 0.46,
            "volume": 50000000,
            "average_volume": 55000000,
            "volume_change_ratio": 0.91,
            "high": 514.00,
            "low": 509.50,
            "open": 510.25,
            "close": 512.34,
            "timestamp": "2026-05-10T16:00:00Z",
            "market_confirmation_score": 0.62,
        })
        self._assert_invariants(rec, "market_data")
        assert rec.get("broker_api_called") is False

    def test_india_normalizer_invariants(self):
        from scripts.live_source_runner_phase2 import _normalize_india_record
        rec = _normalize_india_record({
            "index_name": "NIFTY 50",
            "last_price": 22500.0,
            "change": 150.0,
            "percent_change": 0.67,
            "regulatory_source": "NSE",
            "regulatory_url": "https://nse.example.com",
            "regulatory_note": None,
        })
        self._assert_invariants(rec, "india")
        assert rec.get("broker_api_called") is False

    def test_global_filings_normalizer_invariants(self):
        from scripts.live_source_runner_phase2 import _normalize_global_filings_record
        rec = _normalize_global_filings_record({
            "provider": "asx",
            "issuer_name": "BHP Group",
            "ticker_or_identifier": "BHP",
            "exchange_or_regulator": "ASX",
            "jurisdiction": "AU",
            "disclosure_type": "quarterly_report",
            "published_at": "2026-05-10T09:00:00Z",
            "url": "https://asx.example.com/bhp",
            "summary": "Quarterly production report",
        })
        self._assert_invariants(rec, "global_filings")
        assert rec.get("broker_api_called") is False
        assert rec.get("broker_order_id") == "NONE", \
            f"global_filings: broker_order_id must be 'NONE', got {rec.get('broker_order_id')!r}"

    def test_asia_disclosure_normalizer_invariants(self):
        from scripts.live_source_runner_phase2 import _normalize_asia_disclosure_record
        rec = _normalize_asia_disclosure_record({
            "provider": "hkex",
            "issuer_name": "HSBC Holdings",
            "ticker_or_identifier": "0005.HK",
            "exchange_or_regulator": "HKEX",
            "jurisdiction": "HK",
            "disclosure_type": "annual_report",
            "published_at": "2026-05-10T06:00:00Z",
            "url": "https://hkex.example.com/hsbc",
            "summary": "Annual results announcement",
            "language": "en",
        })
        self._assert_invariants(rec, "asia_disclosure")
        assert rec.get("broker_api_called") is False
        assert rec.get("broker_order_id") == "NONE", \
            f"asia_disclosure: broker_order_id must be 'NONE', got {rec.get('broker_order_id')!r}"


# ===========================================================================
# 5. Forbidden execution endpoint absence
# ===========================================================================


class TestForbiddenEndpoints:
    """Verify that no execution/brokerage routes exist in the API server."""

    _forbidden_routes = [
        "/buy",
        "/sell",
        "/trade",
        "/execute",
        "/orders",
        "/place-order",
        "/broker/order",
        "/wallet/sign",
        "/transaction/broadcast",
    ]

    def test_api_server_has_no_forbidden_routes(self):
        content = _read(_API)
        for route in self._forbidden_routes:
            # Check for route definition patterns like @app.get("/buy")
            pattern = rf'@app\.\w+\("{re.escape(route)}[/"]'
            assert not re.search(pattern, content), \
                f"Forbidden route '{route}' found in api_server.py"

    def test_api_server_has_no_buy_endpoint(self):
        content = _read(_API)
        assert '"/buy"' not in content and "'/buy'" not in content, \
            "api_server.py contains /buy route"

    def test_api_server_has_no_sell_endpoint(self):
        content = _read(_API)
        assert '"/sell"' not in content and "'/sell'" not in content, \
            "api_server.py contains /sell route"

    def test_api_server_has_no_execute_endpoint(self):
        content = _read(_API)
        assert '"/execute"' not in content and "'/execute'" not in content, \
            "api_server.py contains /execute route"

    def test_api_server_has_no_broker_order_endpoint(self):
        content = _read(_API)
        assert '"/broker' not in content and "'/broker" not in content, \
            "api_server.py contains /broker route"

    def test_api_server_has_no_wallet_sign_endpoint(self):
        content = _read(_API)
        assert '"/wallet' not in content and "'/wallet" not in content, \
            "api_server.py contains /wallet route"

    def test_api_server_has_no_private_key(self):
        content = _read(_API)
        assert "private_key" not in content.lower(), \
            "api_server.py references private_key"

    def test_runner_files_have_no_wallet_signing(self):
        for path in [_RUNNER1, _RUNNER2]:
            content = _read(path)
            assert "wallet.sign" not in content, \
                f"{path.name} contains wallet.sign"
            assert "send_transaction" not in content, \
                f"{path.name} contains send_transaction"
            assert "private_key" not in content.lower(), \
                f"{path.name} contains private_key"


# ===========================================================================
# 6. Required API routes exist
# ===========================================================================


def _registered_routes():
    """Truthful route surface — uses FastAPI's app.routes instead of
    a literal source-regex on api_server.py.  Several routes have been
    extracted into ``scripts/api/routers/*`` (Calibration Corpus +
    Hosted Canary sprint, Phase 3); the regex form is brittle and
    would falsely fail extraction sprints.
    """
    import scripts.api_server as srv
    return {getattr(r, "path", None) for r in srv.app.routes}


class TestRequiredAPIRoutes:
    def test_live_signals_route_exists(self):
        assert "/live-signals" in _registered_routes(), \
            "FastAPI app missing GET /live-signals route"

    def test_live_signals_supports_source_filter(self):
        import inspect
        from scripts.api.routers.live_signals_router import get_live_signals
        sig = inspect.signature(get_live_signals)
        assert "source" in sig.parameters, \
            "GET /live-signals does not expose a `source` filter parameter"

    def test_source_health_route_exists(self):
        assert "/source-health" in _registered_routes(), \
            "FastAPI app missing GET /source-health route"

    def test_db_status_route_exists(self):
        assert "/db/status" in _registered_routes(), \
            "FastAPI app missing GET /db/status route"

    def test_health_route_exists(self):
        assert "/health" in _registered_routes(), \
            "FastAPI app missing GET /health route"

    def test_source_run_log_in_source_health(self):
        import inspect as _inspect
        import scripts.api.routers.source_health_router as router_mod
        source = _inspect.getsource(router_mod)
        assert "source_run_log" in source, \
            "GET /source-health does not include source_run_log"

    def test_advisory_status_in_api_responses(self):
        content = _read(_API)
        assert "_ADVISORY_STATUS" in content, \
            "api_server.py does not reference _ADVISORY_STATUS"
        assert "_EXECUTION_MODE" in content, \
            "api_server.py does not reference _EXECUTION_MODE"
        assert "_AI_EXECUTION_COUNT" in content, \
            "api_server.py does not reference _AI_EXECUTION_COUNT"


# ===========================================================================
# 7. CLI source support (static inspection)
# ===========================================================================


class TestCLISourceSupport:
    def test_cli1_source_choices_cover_phase1(self):
        content = _read(_CLI1)
        for src in PHASE1_SOURCES:
            assert src in content, f"CLI1 missing '{src}' in source choices"

    def test_cli1_has_dry_run_flag(self):
        content = _read(_CLI1)
        assert "--dry-run" in content, "CLI1 missing --dry-run flag"

    def test_cli1_has_write_flag(self):
        content = _read(_CLI1)
        assert "--write" in content, "CLI1 missing --write flag"

    def test_cli1_has_json_flag(self):
        content = _read(_CLI1)
        assert "--json" in content, "CLI1 missing --json flag"

    def test_cli2_source_choices_cover_phase2(self):
        content = _read(_CLI2)
        for src in PHASE2_SOURCES:
            assert src in content, f"CLI2 missing '{src}' in source choices"

    def test_cli2_has_dry_run_flag(self):
        content = _read(_CLI2)
        assert "--dry-run" in content, "CLI2 missing --dry-run flag"

    def test_cli2_has_write_flag(self):
        content = _read(_CLI2)
        assert "--write" in content, "CLI2 missing --write flag"

    def test_cli2_has_json_flag(self):
        content = _read(_CLI2)
        assert "--json" in content, "CLI2 missing --json flag"


# ===========================================================================
# 8. Persistence layer coverage
# ===========================================================================


class TestPersistenceLayer:
    """Verify insert_signal_event and get_signal_events work for every source."""

    def _make_event(self, source: str) -> dict:
        return {
            "event_id": f"{source}_test_abc123",
            "source_name": source,
            "signal_type": "test",
            "title": f"Test signal for {source}",
            "advisory_status": "ADVISORY_ONLY",
            "human_review_required": True,
            "execution_gate": "LOCKED",
            "ai_execution_count": 0,
        }

    def test_signal_events_table_schema_includes_safety_fields(self):
        from scripts.persistence import _SCHEMA_SQL
        assert "advisory_status" in _SCHEMA_SQL, \
            "signal_events table missing advisory_status column"
        assert "execution_gate" in _SCHEMA_SQL, \
            "signal_events table missing execution_gate column"
        assert "human_review_required" in _SCHEMA_SQL, \
            "signal_events table missing human_review_required column"
        assert "ai_execution_count" in _SCHEMA_SQL, \
            "signal_events table missing ai_execution_count column"

    def test_source_run_log_table_exists_in_schema(self):
        from scripts.persistence import _SCHEMA_SQL
        assert "source_run_log" in _SCHEMA_SQL, \
            "persistence.py schema missing source_run_log table"

    def test_insert_and_get_signal_event_roundtrip(self, tmp_path):
        from scripts.persistence import insert_signal_event, get_signal_events
        db = tmp_path / "test_roundtrip.db"

        payload = self._make_event("polymarket")
        result = insert_signal_event(
            event_id=payload["event_id"],
            source_name="polymarket",
            raw_payload=payload,
            fetched_at="2026-05-10T00:00:00Z",
            db_path=db,
        )
        assert result is True, "insert_signal_event should return True on first insert"

        events = get_signal_events(source_name="polymarket", limit=10, db_path=db)
        assert len(events) == 1
        ev = events[0]
        assert ev["source_name"] == "polymarket"
        assert ev["advisory_status"] == "ADVISORY_ONLY"
        assert ev["execution_gate"] == "LOCKED"
        assert ev["human_review_required"] is True
        assert ev["ai_execution_count"] == 0

    def test_insert_idempotent_on_duplicate_event_id(self, tmp_path):
        from scripts.persistence import insert_signal_event
        db = tmp_path / "test_dedup.db"
        payload = self._make_event("gdelt")
        first = insert_signal_event("gdelt_dedup_001", "gdelt", payload,
                                    "2026-05-10T00:00:00Z", db_path=db)
        second = insert_signal_event("gdelt_dedup_001", "gdelt", payload,
                                     "2026-05-10T01:00:00Z", db_path=db)
        assert first is True
        assert second is False, "Duplicate event_id must not re-insert"

    @pytest.mark.parametrize("source", ALL_SOURCES)
    def test_get_signal_events_by_source(self, source, tmp_path):
        from scripts.persistence import insert_signal_event, get_signal_events
        db = tmp_path / f"test_{source}.db"
        payload = self._make_event(source)
        insert_signal_event(
            event_id=payload["event_id"],
            source_name=source,
            raw_payload=payload,
            fetched_at="2026-05-10T00:00:00Z",
            db_path=db,
        )
        events = get_signal_events(source_name=source, limit=10, db_path=db)
        assert len(events) >= 1
        assert events[0]["source_name"] == source

    def test_log_source_run_and_retrieve(self, tmp_path):
        from scripts.persistence import log_source_run, get_source_run_log
        db = tmp_path / "test_run_log.db"
        log_source_run(
            source_name="newsapi",
            status="ok",
            fetched_count=5,
            skipped_reason="",
            error_message="",
            timestamp_utc="2026-05-10T12:00:00Z",
            duration_ms=250,
            db_path=db,
        )
        rows = get_source_run_log(limit=10, db_path=db)
        assert len(rows) == 1
        assert rows[0]["source_name"] == "newsapi"
        assert rows[0]["status"] == "ok"
        assert rows[0]["fetched_count"] == 5

    @pytest.mark.parametrize("source", ALL_SOURCES)
    def test_log_source_run_for_every_source(self, source, tmp_path):
        from scripts.persistence import log_source_run, get_source_run_log
        db = tmp_path / f"test_run_log_{source}.db"
        log_source_run(
            source_name=source,
            status="skipped",
            fetched_count=0,
            skipped_reason="no api key",
            error_message="",
            timestamp_utc="2026-05-10T12:00:00Z",
            duration_ms=10,
            db_path=db,
        )
        rows = get_source_run_log(limit=5, db_path=db)
        assert len(rows) >= 1
        assert rows[0]["source_name"] == source

    def test_get_db_status_includes_signal_events_table(self, tmp_path):
        from scripts.persistence import get_db_status, init_schema
        db = tmp_path / "test_status.db"
        init_schema(db_path=db)
        status = get_db_status(db_path=db)
        assert "signal_events" in str(status), \
            "get_db_status does not include signal_events table info"
        assert "source_run_log" in str(status), \
            "get_db_status does not include source_run_log table info"


# ===========================================================================
# 9. Frontend source filter completeness
# ===========================================================================


class TestFrontendSourceFilter:
    def test_all_sources_in_source_options(self):
        content = _read(_UI_PAGE)
        for src in ALL_SOURCES:
            assert f"'{src}'" in content or f'"{src}"' in content, \
                f"SOURCE_OPTIONS missing value '{src}'"

    def test_all_source_labels_present(self):
        content = _read(_UI_PAGE)
        labels = {
            "polymarket": "Polymarket",
            "gdelt": "GDELT",
            "sec_edgar": "SEC EDGAR",
            "newsapi": "NewsAPI",
            "event_registry": "Event Registry",
            "etherscan": "Etherscan",
            "grok_xai": "Grok/xAI",
            "market_data": "Market Data",
            "india": "India",
            "global_filings": "Global Filings",
            "asia_disclosure": "Asia Disclosure",
        }
        for src, label in labels.items():
            assert label in content, f"page.tsx missing label '{label}' for source '{src}'"

    def test_no_forbidden_ui_labels(self):
        content = _read(_UI_PAGE)
        forbidden = ["Buy", "Sell", "Execute", "Auto-trade", "Place Order",
                     "Send Transaction", "Sign Transaction"]
        for label in forbidden:
            # Must not appear as standalone button text / aria label
            assert f">{label}<" not in content, \
                f"page.tsx contains forbidden UI label: '{label}'"

    def test_advisory_badge_used(self):
        content = _read(_UI_PAGE)
        assert "AdvisoryOnly" in content or "advisory" in content.lower(), \
            "page.tsx does not reference advisory badge"

    def test_execution_locked_status_displayed(self):
        content = _read(_UI_PAGE)
        assert "EXECUTION_LOCKED" in content or "LOCKED" in content, \
            "page.tsx does not display EXECUTION_LOCKED status"


# ===========================================================================
# 10. README Phase C Integrated Source Matrix
# ===========================================================================


class TestReadmeMatrix:
    def test_phase_c_matrix_section_exists(self):
        content = _read(_README)
        assert "Phase C Integrated Source Matrix" in content, \
            "README missing 'Phase C Integrated Source Matrix' section"

    def test_matrix_mentions_all_sources(self):
        content = _read(_README)
        for src in ALL_SOURCES:
            assert src in content, f"README matrix missing source '{src}'"

    def test_matrix_mentions_advisory_only(self):
        content = _read(_README)
        assert "ADVISORY_ONLY" in content, \
            "README matrix missing ADVISORY_ONLY execution permission column"

    def test_matrix_mentions_execution_locked(self):
        content = _read(_README)
        assert "LOCKED" in content or "execution_gate" in content, \
            "README does not mention LOCKED execution_gate"

    def test_readme_advisory_safety_rules_present(self):
        content = _read(_README)
        assert "advisory safety rules" in content.lower() or \
               "Advisory safety rules" in content, \
            "README missing advisory safety rules section"

    def test_readme_mentions_dry_run(self):
        content = _read(_README)
        assert "--dry-run" in content, "README missing --dry-run CLI examples"


# ===========================================================================
# 11. Run phase_c_final_audit.py and verify it exits 0
# ===========================================================================


class TestAuditScript:
    def test_audit_script_passes(self):
        spec = importlib.util.spec_from_file_location(
            "phase_c_final_audit", _AUDIT_SCRIPT
        )
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        exit_code = module.run_audit(verbose=False)
        assert exit_code == 0, \
            "phase_c_final_audit.py reported audit failures (exit code != 0)"

    def test_audit_script_compiles(self):
        import py_compile
        py_compile.compile(str(_AUDIT_SCRIPT), doraise=True)

    def test_audit_script_has_expected_source_lists(self):
        content = _read(_AUDIT_SCRIPT)
        for src in ALL_SOURCES:
            assert f'"{src}"' in content or f"'{src}'" in content, \
                f"phase_c_final_audit.py missing source '{src}' in expected lists"


# ===========================================================================
# 12. Phase 1 run_phase1 dry-run (mocked)
# ===========================================================================


class TestPhase1DryRun:
    """Verify run_phase1 in dry-run mode returns the correct safety fields."""

    def _make_skipped_result(self, source: str = "test"):
        from scripts.ingestion.base_loader import LoaderResult
        return LoaderResult(source_name=source, records=[], skipped=True, skip_reason="no api key")

    def test_phase1_dry_run_report_safety_fields(self):
        from scripts.live_source_runner import run_phase1

        skipped = self._make_skipped_result("polymarket")

        with patch("scripts.live_source_runner.PolymarketLoader") as p_cls, \
             patch("scripts.live_source_runner.GDELTLoader") as g_cls, \
             patch("scripts.live_source_runner.SECEdgarLoader") as s_cls:

            for cls, src in [(p_cls, "polymarket"), (g_cls, "gdelt"), (s_cls, "sec_edgar")]:
                inst = MagicMock()
                inst.safe_fetch.return_value = self._make_skipped_result(src)
                cls.return_value = inst

            report = run_phase1(dry_run=True)

        assert report.advisory_status == "ADVISORY_ONLY"
        assert report.execution_gate == "LOCKED"
        assert report.ai_execution_count == 0
        assert report.human_review_required is True
        assert report.dry_run is True

    def test_phase1_dry_run_does_not_call_persist(self):
        from scripts.live_source_runner import run_phase1
        from scripts.ingestion.base_loader import LoaderResult

        loaded = LoaderResult(
            source_name="polymarket",
            records=[{"market_id": "m1", "question": "Q1?", "volume": 100}],
            skipped=False,
        )

        with patch("scripts.live_source_runner.PolymarketLoader") as p_cls, \
             patch("scripts.live_source_runner._persist_events") as persist_mock, \
             patch("scripts.live_source_runner._log_run") as log_mock:

            inst = MagicMock()
            inst.safe_fetch.return_value = loaded
            p_cls.return_value = inst

            run_phase1(dry_run=True, sources=["polymarket"])

        persist_mock.assert_not_called()
        log_mock.assert_not_called()


# ===========================================================================
# 13. Phase 2 run_phase2 dry-run (mocked)
# ===========================================================================


class TestPhase2DryRun:
    """Verify run_phase2 in dry-run mode returns the correct safety fields."""

    def _make_skipped_result(self, source: str = "newsapi"):
        from scripts.ingestion.base_loader import LoaderResult
        return LoaderResult(source_name=source, records=[], skipped=True, skip_reason="no api key")

    def test_phase2_dry_run_report_safety_fields(self):
        from scripts.live_source_runner_phase2 import run_phase2

        skipped = self._make_skipped_result("newsapi")
        loader_mock = MagicMock()
        loader_mock.safe_fetch.return_value = skipped

        with patch("scripts.live_source_runner_phase2.NewsAPILoader",
                   return_value=loader_mock):
            report = run_phase2(dry_run=True, sources=["newsapi"])

        assert report.advisory_status == "ADVISORY_ONLY"
        assert report.execution_gate == "LOCKED"
        assert report.ai_execution_count == 0
        assert report.human_review_required is True
        assert report.broker_api_called is False
        assert report.dry_run is True

    @pytest.mark.parametrize("source,loader_path", [
        ("newsapi", "scripts.live_source_runner_phase2.NewsAPILoader"),
        ("event_registry", "scripts.live_source_runner_phase2.EventRegistryLoader"),
        ("etherscan", "scripts.live_source_runner_phase2.EtherscanLoader"),
        ("grok_xai", "scripts.live_source_runner_phase2.GrokInterpreter"),
        ("market_data", "scripts.live_source_runner_phase2.MarketDataLoader"),
        ("india", "scripts.live_source_runner_phase2.IndiaLoader"),
        ("global_filings", "scripts.live_source_runner_phase2.GlobalFilingsLoader"),
        ("asia_disclosure", "scripts.live_source_runner_phase2.AsiaDisclosureLoader"),
    ])
    def test_phase2_dry_run_skipped_source(self, source, loader_path):
        from scripts.live_source_runner_phase2 import run_phase2
        from scripts.ingestion.base_loader import LoaderResult

        skipped = LoaderResult(source_name=source, records=[], skipped=True, skip_reason="no api key")
        loader_mock = MagicMock()
        loader_mock.safe_fetch.return_value = skipped

        with patch(loader_path, return_value=loader_mock):
            report = run_phase2(dry_run=True, sources=[source])

        assert report.advisory_status == "ADVISORY_ONLY"
        assert report.broker_api_called is False
        assert len(report.sources) == 1
        assert report.sources[0].source_name == source
        assert report.sources[0].status == "skipped"

    def test_phase2_dry_run_does_not_call_persist(self):
        from scripts.live_source_runner_phase2 import run_phase2
        from scripts.ingestion.base_loader import LoaderResult

        loaded = LoaderResult(
            source_name="newsapi",
            records=[{"url": "https://example.com", "title": "Test", "published_at": "2026-05-10"}],
            skipped=False,
        )
        loader_mock = MagicMock()
        loader_mock.safe_fetch.return_value = loaded

        with patch("scripts.live_source_runner_phase2.NewsAPILoader",
                   return_value=loader_mock), \
             patch("scripts.live_source_runner_phase2._persist_events") as persist_mock, \
             patch("scripts.live_source_runner_phase2._log_run") as log_mock:
            run_phase2(dry_run=True, sources=["newsapi"])

        persist_mock.assert_not_called()
        log_mock.assert_not_called()
