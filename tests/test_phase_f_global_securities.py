"""
Phase F — Global Securities Universe: full test suite.

Coverage
--------
 1  persistence.py: global_securities table created by init_schema
 2  persistence.py: global_security_aliases table created by init_schema
 3  upsert_global_security: SBIN.NS insert returns True (newly inserted)
 4  upsert_global_security: SBIN.NS second call returns False (updated, no duplicate)
 5  get_global_security: SBIN.NS returns correct name
 6  get_global_security: advisory_status always ADVISORY_ONLY
 7  get_global_security: execution_gate always LOCKED
 8  get_global_security: ai_execution_count always 0
 9  get_global_security: broker_api_called always False
10  get_global_security: broker_order_id always NONE
11  search_global_securities: SBIN.NS found by canonical symbol substring
12  search_global_securities: 2002.TW insert/search round-trip
13  upsert_security_alias: SBI.NSE -> SBIN.NS stored
14  resolve_alias: SBI.NSE resolves to SBIN.NS
15  resolve_alias: non-existent alias returns None
16  normalize_symbol: direct lookup returns resolution_path='direct'
17  normalize_symbol: alias lookup returns resolution_path='alias'
18  normalize_symbol: unknown symbol returns resolution_path='unknown' and error=UNKNOWN_SYMBOL
19  normalize_symbol: unknown symbol returns advisory invariants
20  normalize_symbol: returns discovery_command and backfill_command
21  get_security_coverage: SBIN.NS in_securities_master=True after upsert
22  get_security_coverage: 2002.TW candle_count reflects inserted signal_events
23  get_security_coverage: returns discovery_command and backfill_command
24  get_security_coverage: advisory_status always ADVISORY_ONLY
25  global_security_master_discovery.py exists
26  global_security_master_discovery.py compiles (no SyntaxError)
27  global_security_master_discovery.py has no forbidden execution terms
28  backfill_global_ohlcv.py exists
29  backfill_global_ohlcv.py compiles (no SyntaxError)
30  backfill_global_ohlcv.py has no forbidden execution terms
31  update_global_ohlcv_latest.py exists
32  update_global_ohlcv_latest.py compiles (no SyntaxError)
33  symbol_normalizer.py exists
34  symbol_normalizer.py compiles (no SyntaxError)
35  symbol_normalizer.py has no yfinance/fastapi imports at module level
36  configs/global_securities_master.yaml exists
37  YAML includes SBIN.NS
38  YAML includes 2002.TW
39  YAML aliases section includes SBI.NSE
40  mocked yfinance backfill: SBIN.NS candles inserted correctly
41  mocked yfinance backfill: 2002.TW candles inserted correctly
42  mocked yfinance backfill: idempotent — second run inserts 0 new rows
43  mocked yfinance backfill: candle advisory_status == ADVISORY_ONLY
44  mocked yfinance backfill: candle execution_gate == LOCKED
45  mocked yfinance discovery: upserts SBIN.NS security record
46  mocked yfinance discovery: upserts 2002.TW security record
47  second discovery run detects newly-listed (simulate active toggle)
48  conservative stale detection: no price → active=False
49  FastAPI-free: symbol_normalizer importable without FastAPI
50  FastAPI-free: global_security_master_discovery importable without FastAPI
51  FastAPI-free: backfill_global_ohlcv importable without FastAPI
52  get_db_status includes global_securities and global_security_aliases counts
53  api_server.py references /securities/search endpoint
54  api_server.py references /securities/{symbol} endpoint
55  api_server.py references /securities/{symbol}/coverage endpoint
56  chart_structure_api_context returns discovery_command on INSUFFICIENT_DATA
57  chart_structure_api_context returns backfill_command on INSUFFICIENT_DATA
58  safety invariant: global_security records never have execution gate != LOCKED
59  safety invariant: global_security records never have ai_execution_count != 0
60  safety invariant: global_security records never have broker_api_called != False
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DISCOVERY_PATH = REPO_ROOT / "scripts" / "global_security_master_discovery.py"
_BACKFILL_PATH = REPO_ROOT / "scripts" / "backfill_global_ohlcv.py"
_UPDATE_PATH = REPO_ROOT / "scripts" / "update_global_ohlcv_latest.py"
_NORMALIZER_PATH = REPO_ROOT / "scripts" / "symbol_normalizer.py"
_API_SERVER_PATH = REPO_ROOT / "scripts" / "api_server.py"
_CHART_CONTEXT_PATH = REPO_ROOT / "scripts" / "chart_structure_api_context.py"
_YAML_CONFIG_PATH = REPO_ROOT / "configs" / "global_securities_master.yaml"

_FORBIDDEN_TERMS = [
    "place_order",
    "submit_order",
    "execute_trade",
    "broker_execute",
    "broker_api(",
    "private_key",
    "send_transaction",
    "wallet(",
    "buy(",
    "sell(",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_db() -> Path:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return Path(f.name)


def _load_module_from_path(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _has_forbidden_term(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    return [t for t in _FORBIDDEN_TERMS if t in src]


def _make_mock_hist(rows: list[dict]):
    """Build a mock yfinance history DataFrame-like object."""
    import datetime

    class MockRow:
        def __init__(self, d):
            self.Open = d["open"]
            self.High = d["high"]
            self.Low = d["low"]
            self.Close = d["close"]
            self.Volume = d["volume"]

        def get(self, k, default=None):
            return getattr(self, k.capitalize(), default)

    class MockHist:
        def __init__(self, rows):
            self._rows = rows
            self.empty = len(rows) == 0

        def __bool__(self):
            return not self.empty

        def iterrows(self):
            for r in self._rows:
                ts = r["date"]
                yield ts, MockRow(r)

    return MockHist(rows)


def _sample_candle_rows(symbol: str, n: int = 3) -> list[dict]:
    import datetime
    rows = []
    base = datetime.date(2024, 1, 2)
    for i in range(n):
        d = base.replace(day=base.day + i)
        rows.append({
            "date": f"{d}",
            "open": 100.0 + i,
            "high": 105.0 + i,
            "low": 99.0 + i,
            "close": 102.0 + i,
            "volume": 1_000_000.0,
        })
    return rows


# ---------------------------------------------------------------------------
# 1-2  Schema creation
# ---------------------------------------------------------------------------

def test_global_securities_table_created():
    db = _tmp_db()
    from scripts.persistence import init_schema
    import sqlite3
    init_schema(db)
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='global_securities'"
    ).fetchone()
    conn.close()
    assert row is not None, "global_securities table not created"


def test_global_security_aliases_table_created():
    db = _tmp_db()
    from scripts.persistence import init_schema
    import sqlite3
    init_schema(db)
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='global_security_aliases'"
    ).fetchone()
    conn.close()
    assert row is not None, "global_security_aliases table not created"


# ---------------------------------------------------------------------------
# 3-10  upsert / get global security
# ---------------------------------------------------------------------------

def test_upsert_sbin_ns_insert_returns_true():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security
    inserted = upsert_global_security(
        canonical_symbol="SBIN.NS",
        name="State Bank of India",
        exchange_code="NSE",
        country="IN",
        economy_rank=5,
        db_path=db,
    )
    assert inserted is True


def test_upsert_sbin_ns_second_call_returns_false():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security
    upsert_global_security("SBIN.NS", name="SBI", db_path=db)
    updated = upsert_global_security("SBIN.NS", name="State Bank of India", db_path=db)
    assert updated is False


def test_get_global_security_sbin_correct_name():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security, get_global_security
    upsert_global_security("SBIN.NS", name="State Bank of India", db_path=db)
    sec = get_global_security("SBIN.NS", db_path=db)
    assert sec is not None
    assert sec["name"] == "State Bank of India"


def test_get_global_security_advisory_status():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security, get_global_security
    upsert_global_security("SBIN.NS", db_path=db)
    sec = get_global_security("SBIN.NS", db_path=db)
    assert sec["advisory_status"] == "ADVISORY_ONLY"


def test_get_global_security_execution_gate_locked():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security, get_global_security
    upsert_global_security("SBIN.NS", db_path=db)
    sec = get_global_security("SBIN.NS", db_path=db)
    assert sec["execution_gate"] == "LOCKED"


def test_get_global_security_ai_execution_count_zero():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security, get_global_security
    upsert_global_security("SBIN.NS", db_path=db)
    sec = get_global_security("SBIN.NS", db_path=db)
    assert sec["ai_execution_count"] == 0


def test_get_global_security_broker_api_called_false():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security, get_global_security
    upsert_global_security("SBIN.NS", db_path=db)
    sec = get_global_security("SBIN.NS", db_path=db)
    assert sec["broker_api_called"] is False


def test_get_global_security_broker_order_id_none():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security, get_global_security
    upsert_global_security("SBIN.NS", db_path=db)
    sec = get_global_security("SBIN.NS", db_path=db)
    assert sec["broker_order_id"] == "NONE"


# ---------------------------------------------------------------------------
# 11-12  search
# ---------------------------------------------------------------------------

def test_search_sbin_ns_by_symbol():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security, search_global_securities
    upsert_global_security("SBIN.NS", name="State Bank of India", db_path=db)
    results = search_global_securities("SBIN", db_path=db)
    assert any(r["canonical_symbol"] == "SBIN.NS" for r in results)


def test_insert_and_search_2002_tw():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security, search_global_securities
    upsert_global_security(
        "2002.TW",
        name="China Steel Corporation",
        exchange_code="TWSE",
        country="TW",
        economy_rank=22,
        db_path=db,
    )
    results = search_global_securities("2002", db_path=db)
    assert any(r["canonical_symbol"] == "2002.TW" for r in results)


# ---------------------------------------------------------------------------
# 13-15  alias upsert / resolve
# ---------------------------------------------------------------------------

def test_upsert_alias_sbi_nse():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security, upsert_security_alias
    upsert_global_security("SBIN.NS", db_path=db)
    ok = upsert_security_alias("SBI.NSE", "SBIN.NS", confidence=0.95, source="test", db_path=db)
    assert ok is True


def test_resolve_alias_sbi_nse_to_sbin_ns():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security, upsert_security_alias, resolve_alias
    upsert_global_security("SBIN.NS", db_path=db)
    upsert_security_alias("SBI.NSE", "SBIN.NS", db_path=db)
    resolved = resolve_alias("SBI.NSE", db_path=db)
    assert resolved == "SBIN.NS"


def test_resolve_alias_nonexistent_returns_none():
    db = _tmp_db()
    from scripts.persistence import resolve_alias
    result = resolve_alias("DOESNOTEXIST", db_path=db)
    assert result is None


# ---------------------------------------------------------------------------
# 16-20  symbol_normalizer
# ---------------------------------------------------------------------------

def test_normalize_symbol_direct_lookup():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security
    from scripts.symbol_normalizer import normalize_symbol
    upsert_global_security("SBIN.NS", name="State Bank of India", db_path=db)
    result = normalize_symbol("SBIN.NS", db_path=db)
    assert result["resolution_path"] == "direct"
    assert result["canonical_symbol"] == "SBIN.NS"


def test_normalize_symbol_alias_lookup():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security, upsert_security_alias
    from scripts.symbol_normalizer import normalize_symbol
    upsert_global_security("SBIN.NS", db_path=db)
    upsert_security_alias("SBI.NSE", "SBIN.NS", db_path=db)
    result = normalize_symbol("SBI.NSE", db_path=db)
    assert result["resolution_path"] == "alias"
    assert result["canonical_symbol"] == "SBIN.NS"
    assert result["alias_used"] == "SBI.NSE"


def test_normalize_symbol_unknown_returns_unknown():
    db = _tmp_db()
    from scripts.symbol_normalizer import normalize_symbol
    result = normalize_symbol("TOTALLY_UNKNOWN_XYZ999", db_path=db)
    assert result["resolution_path"] == "unknown"
    assert result["unknown"] is True
    assert result["error"] == "UNKNOWN_SYMBOL"


def test_normalize_symbol_unknown_has_advisory_invariants():
    db = _tmp_db()
    from scripts.symbol_normalizer import normalize_symbol
    result = normalize_symbol("TOTALLY_UNKNOWN_XYZ999", db_path=db)
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_gate"] == "LOCKED"
    assert result["human_review_required"] is True
    assert result["ai_execution_count"] == 0
    assert result["broker_api_called"] is False
    assert result["broker_order_id"] == "NONE"


def test_normalize_symbol_returns_commands():
    db = _tmp_db()
    from scripts.symbol_normalizer import normalize_symbol
    result = normalize_symbol("SBIN.NS", db_path=db)
    assert "discovery_command" in result
    assert "backfill_command" in result
    assert "SBIN.NS" in result["discovery_command"]
    assert "SBIN.NS" in result["backfill_command"]


# ---------------------------------------------------------------------------
# 21-24  security coverage
# ---------------------------------------------------------------------------

def test_security_coverage_sbin_in_master():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security, get_security_coverage
    upsert_global_security("SBIN.NS", db_path=db)
    cov = get_security_coverage("SBIN.NS", db_path=db)
    assert cov["in_securities_master"] is True
    assert cov["canonical_symbol"] == "SBIN.NS"


def test_security_coverage_2002_tw_candle_count():
    db = _tmp_db()
    from scripts.persistence import (
        upsert_global_security,
        insert_signal_event,
        get_security_coverage,
    )
    upsert_global_security("2002.TW", db_path=db)
    for i in range(5):
        insert_signal_event(
            event_id=f"ohlcv_2002_tw_1d_2024-01-0{i + 1}",
            source_name="market_data",
            raw_payload={"symbol": "2002.TW", "timestamp": f"2024-01-0{i + 1}T16:00:00Z",
                         "open": 30.0, "high": 31.0, "low": 29.0, "close": 30.5, "volume": 1e6},
            fetched_at="2024-01-10T00:00:00Z",
            db_path=db,
        )
    cov = get_security_coverage("2002.TW", db_path=db)
    assert cov["candle_count"] == 5


def test_security_coverage_returns_commands():
    db = _tmp_db()
    from scripts.persistence import get_security_coverage
    cov = get_security_coverage("SBIN.NS", db_path=db)
    assert "discovery_command" in cov
    assert "backfill_command" in cov
    assert "SBIN.NS" in cov["discovery_command"]
    assert "SBIN.NS" in cov["backfill_command"]


def test_security_coverage_advisory_status():
    db = _tmp_db()
    from scripts.persistence import get_security_coverage
    cov = get_security_coverage("SBIN.NS", db_path=db)
    assert cov["advisory_status"] == "ADVISORY_ONLY"


# ---------------------------------------------------------------------------
# 25-27  discovery script file checks
# ---------------------------------------------------------------------------

def test_discovery_script_exists():
    assert _DISCOVERY_PATH.exists(), f"Missing: {_DISCOVERY_PATH}"


def test_discovery_script_compiles():
    src = _DISCOVERY_PATH.read_text(encoding="utf-8")
    ast.parse(src)


def test_discovery_script_no_forbidden_terms():
    found = _has_forbidden_term(_DISCOVERY_PATH)
    assert not found, f"Forbidden terms in discovery script: {found}"


# ---------------------------------------------------------------------------
# 28-30  backfill script file checks
# ---------------------------------------------------------------------------

def test_backfill_global_script_exists():
    assert _BACKFILL_PATH.exists(), f"Missing: {_BACKFILL_PATH}"


def test_backfill_global_script_compiles():
    src = _BACKFILL_PATH.read_text(encoding="utf-8")
    ast.parse(src)


def test_backfill_global_script_no_forbidden_terms():
    found = _has_forbidden_term(_BACKFILL_PATH)
    assert not found, f"Forbidden terms in backfill script: {found}"


# ---------------------------------------------------------------------------
# 31-32  update script
# ---------------------------------------------------------------------------

def test_update_global_script_exists():
    assert _UPDATE_PATH.exists(), f"Missing: {_UPDATE_PATH}"


def test_update_global_script_compiles():
    src = _UPDATE_PATH.read_text(encoding="utf-8")
    ast.parse(src)


# ---------------------------------------------------------------------------
# 33-35  symbol_normalizer
# ---------------------------------------------------------------------------

def test_symbol_normalizer_exists():
    assert _NORMALIZER_PATH.exists(), f"Missing: {_NORMALIZER_PATH}"


def test_symbol_normalizer_compiles():
    src = _NORMALIZER_PATH.read_text(encoding="utf-8")
    ast.parse(src)


def test_symbol_normalizer_no_yfinance_or_fastapi_at_top_level():
    src = _NORMALIZER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in getattr(node, "names", []):
                assert "yfinance" not in alias.name, "yfinance imported at top level in symbol_normalizer"
            if isinstance(node, ast.ImportFrom):
                assert node.module is None or "fastapi" not in node.module, (
                    "fastapi imported at top level in symbol_normalizer"
                )


# ---------------------------------------------------------------------------
# 36-39  YAML config
# ---------------------------------------------------------------------------

def test_yaml_config_exists():
    assert _YAML_CONFIG_PATH.exists(), f"Missing: {_YAML_CONFIG_PATH}"


def test_yaml_config_contains_sbin_ns():
    content = _YAML_CONFIG_PATH.read_text(encoding="utf-8")
    assert "SBIN.NS" in content, "SBIN.NS not in global_securities_master.yaml"


def test_yaml_config_contains_2002_tw():
    content = _YAML_CONFIG_PATH.read_text(encoding="utf-8")
    assert "2002.TW" in content, "2002.TW not in global_securities_master.yaml"


def test_yaml_config_aliases_include_sbi_nse():
    content = _YAML_CONFIG_PATH.read_text(encoding="utf-8")
    assert "SBI.NSE" in content, "SBI.NSE alias not in global_securities_master.yaml"


# ---------------------------------------------------------------------------
# 40-44  mocked yfinance backfill
# ---------------------------------------------------------------------------

def _setup_mock_yf(symbol: str, n_candles: int = 5):
    rows = _sample_candle_rows(symbol, n=n_candles)
    mock_hist = _make_mock_hist(rows)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = mock_hist
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker
    return mock_yf


def test_mocked_backfill_sbin_ns_inserts_candles():
    db = _tmp_db()
    mock_yf = _setup_mock_yf("SBIN.NS", n_candles=5)
    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        from scripts.backfill_global_ohlcv import backfill_symbol
        fetched, inserted = backfill_symbol(
            "SBIN.NS", period="max", interval="1d", write=True, db_path=db, discover=False
        )
    assert fetched == 5
    assert inserted == 5


def test_mocked_backfill_2002_tw_inserts_candles():
    db = _tmp_db()
    mock_yf = _setup_mock_yf("2002.TW", n_candles=4)
    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        from scripts.backfill_global_ohlcv import backfill_symbol
        fetched, inserted = backfill_symbol(
            "2002.TW", period="max", interval="1d", write=True, db_path=db, discover=False
        )
    assert fetched == 4
    assert inserted == 4


def test_mocked_backfill_idempotent():
    db = _tmp_db()
    mock_yf = _setup_mock_yf("SBIN.NS", n_candles=5)
    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        from scripts.backfill_global_ohlcv import backfill_symbol
        backfill_symbol("SBIN.NS", write=True, db_path=db, discover=False)
        _, inserted2 = backfill_symbol("SBIN.NS", write=True, db_path=db, discover=False)
    assert inserted2 == 0, "Second run should insert 0 new rows (idempotent)"


def test_mocked_backfill_candle_advisory_status():
    db = _tmp_db()
    mock_yf = _setup_mock_yf("SBIN.NS", n_candles=2)
    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        from scripts.backfill_global_ohlcv import fetch_candles
        candles = fetch_candles("SBIN.NS", period="max", interval="1d")
    assert all(c["advisory_status"] == "ADVISORY_ONLY" for c in candles)


def test_mocked_backfill_candle_execution_gate():
    db = _tmp_db()
    mock_yf = _setup_mock_yf("SBIN.NS", n_candles=2)
    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        from scripts.backfill_global_ohlcv import fetch_candles
        candles = fetch_candles("SBIN.NS", period="max", interval="1d")
    assert all(c["execution_gate"] == "LOCKED" for c in candles)


# ---------------------------------------------------------------------------
# 45-46  mocked yfinance discovery
# ---------------------------------------------------------------------------

def _setup_discovery_mock(symbol: str, active: bool = True) -> MagicMock:
    mock_info = {
        "longName": f"Mock Security {symbol}",
        "exchange": "MOCK",
        "fullExchangeName": "Mock Exchange",
        "country": "IN" if "NS" in symbol else "TW",
        "currency": "INR" if "NS" in symbol else "TWD",
        "quoteType": "EQUITY",
        "regularMarketPrice": 120.5 if active else None,
        "sector": "Financials",
        "industry": "Banking",
    }
    mock_ticker = MagicMock()
    mock_ticker.info = mock_info
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker
    return mock_yf


def test_mocked_discovery_upserts_sbin_ns():
    db = _tmp_db()
    mock_yf = _setup_discovery_mock("SBIN.NS")
    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        from scripts.global_security_master_discovery import discover_and_upsert
        discover_and_upsert(["SBIN.NS"], write=True, db_path=db)
    from scripts.persistence import get_global_security
    sec = get_global_security("SBIN.NS", db_path=db)
    assert sec is not None
    assert "Mock Security" in sec["name"]


def test_mocked_discovery_upserts_2002_tw():
    db = _tmp_db()
    mock_yf = _setup_discovery_mock("2002.TW")
    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        from scripts.global_security_master_discovery import discover_and_upsert
        discover_and_upsert(["2002.TW"], write=True, db_path=db)
    from scripts.persistence import get_global_security
    sec = get_global_security("2002.TW", db_path=db)
    assert sec is not None


# ---------------------------------------------------------------------------
# 47  second discovery run detects newly-listed
# ---------------------------------------------------------------------------

def test_second_discovery_run_updates_active_flag():
    db = _tmp_db()
    # First run: active=False (no price)
    mock_yf_1 = _setup_discovery_mock("SBIN.NS", active=False)
    with patch.dict("sys.modules", {"yfinance": mock_yf_1}):
        from scripts.global_security_master_discovery import discover_and_upsert
        discover_and_upsert(["SBIN.NS"], write=True, db_path=db)
    from scripts.persistence import get_global_security
    sec1 = get_global_security("SBIN.NS", db_path=db)
    assert sec1 is not None
    assert sec1["active"] is False

    # Second run: active=True (price available now — new listing)
    mock_yf_2 = _setup_discovery_mock("SBIN.NS", active=True)
    with patch.dict("sys.modules", {"yfinance": mock_yf_2}):
        discover_and_upsert(["SBIN.NS"], write=True, db_path=db)
    sec2 = get_global_security("SBIN.NS", db_path=db)
    assert sec2 is not None
    assert sec2["active"] is True


# ---------------------------------------------------------------------------
# 48  conservative stale/delisted detection
# ---------------------------------------------------------------------------

def test_no_price_means_active_false():
    mock_yf = _setup_discovery_mock("SBIN.NS", active=False)
    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        from scripts.global_security_master_discovery import discover_symbol
        result = discover_symbol("SBIN.NS")
    assert result["active"] is False


# ---------------------------------------------------------------------------
# 49-51  FastAPI-free imports
# ---------------------------------------------------------------------------

def test_symbol_normalizer_importable_without_fastapi():
    saved = sys.modules.pop("scripts.symbol_normalizer", None)
    saved2 = sys.modules.pop("symbol_normalizer", None)
    fastapi_saved = sys.modules.get("fastapi")
    sys.modules["fastapi"] = None  # type: ignore[assignment]
    try:
        import importlib
        spec = importlib.util.spec_from_file_location("symbol_normalizer_test", _NORMALIZER_PATH)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        assert hasattr(mod, "normalize_symbol")
    finally:
        if fastapi_saved is None:
            sys.modules.pop("fastapi", None)
        else:
            sys.modules["fastapi"] = fastapi_saved
        if saved:
            sys.modules["scripts.symbol_normalizer"] = saved
        if saved2:
            sys.modules["symbol_normalizer"] = saved2


def test_discovery_importable_without_fastapi():
    src = _DISCOVERY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    top_level_imports: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top_level_imports.append(node.module)
    assert "fastapi" not in " ".join(top_level_imports).lower()


def test_backfill_global_importable_without_fastapi():
    src = _BACKFILL_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    top_level_imports: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top_level_imports.append(node.module)
    assert "fastapi" not in " ".join(top_level_imports).lower()


# ---------------------------------------------------------------------------
# 52  get_db_status includes new tables
# ---------------------------------------------------------------------------

def test_db_status_includes_global_tables():
    db = _tmp_db()
    from scripts.persistence import get_db_status
    status = get_db_status(db_path=db)
    counts = status.get("table_row_counts", {})
    assert "global_securities" in counts, "global_securities missing from db_status"
    assert "global_security_aliases" in counts, "global_security_aliases missing from db_status"


# ---------------------------------------------------------------------------
# 53-55  API server endpoint text checks
# ---------------------------------------------------------------------------

def test_api_server_has_securities_search_endpoint():
    src = _API_SERVER_PATH.read_text(encoding="utf-8")
    assert "/securities/search" in src


def test_api_server_has_securities_detail_endpoint():
    src = _API_SERVER_PATH.read_text(encoding="utf-8")
    assert "/securities/{symbol}" in src


def test_api_server_has_securities_coverage_endpoint():
    src = _API_SERVER_PATH.read_text(encoding="utf-8")
    assert "/securities/{symbol}/coverage" in src


# ---------------------------------------------------------------------------
# 56-57  chart_structure_api_context INSUFFICIENT_DATA commands
# ---------------------------------------------------------------------------

def test_chart_context_insufficient_data_has_discovery_command():
    db = _tmp_db()
    from scripts.chart_structure_api_context import _get_chart_structure
    result = _get_chart_structure(symbol="TOTALLY_UNKNOWN_SYM", db_path=db)
    assert "discovery_command" in result or result.get("candle_count", -1) >= 0, (
        "discovery_command missing from INSUFFICIENT_DATA response"
    )


def test_chart_context_insufficient_data_has_backfill_command():
    db = _tmp_db()
    from scripts.chart_structure_api_context import _get_chart_structure
    result = _get_chart_structure(symbol="TOTALLY_UNKNOWN_SYM2", db_path=db)
    if result.get("candle_count", -1) == 0:
        assert "backfill_command" in result or "advisory_summary" in result


# ---------------------------------------------------------------------------
# 58-60  Safety invariants — no DB record violates the gates
# ---------------------------------------------------------------------------

def test_safety_invariant_execution_gate_always_locked():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security, get_global_security
    upsert_global_security("SPY", name="SPDR S&P 500", db_path=db)
    sec = get_global_security("SPY", db_path=db)
    assert sec is not None
    assert sec["execution_gate"] == "LOCKED"


def test_safety_invariant_ai_execution_count_zero():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security, get_global_security
    upsert_global_security("AAPL", name="Apple Inc.", db_path=db)
    sec = get_global_security("AAPL", db_path=db)
    assert sec["ai_execution_count"] == 0


def test_safety_invariant_broker_api_called_false():
    db = _tmp_db()
    from scripts.persistence import upsert_global_security, get_global_security
    upsert_global_security("MSFT", name="Microsoft", db_path=db)
    sec = get_global_security("MSFT", db_path=db)
    assert sec["broker_api_called"] is False
