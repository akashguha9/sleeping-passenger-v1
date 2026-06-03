"""
Phase E.2 — Tests for CORS, proxy, port-pin, and chart OHLCV seed.

Coverage
--------
 1  api_server CORS: http://sleepingpassenger allowed
 2  api_server CORS: http://sleepingpassenger.local allowed
 3  api_server CORS: http://localhost:3000 allowed
 4  api_server CORS: http://127.0.0.1:3000 allowed
 5  api_server CORS: http://sleepingpassenger:80 allowed
 6  api_server CORS: http://sleepingpassenger.local:80 allowed
 7  api_server CORS: wildcard '*' is NOT allowed
 8  Proxy: self.path used (preserves path verbatim)
 9  Proxy: self.path includes query string (no stripping)
10  Proxy: Host header overridden to upstream host:port
11  start_mvp_stack.ps1: uses 'npx next dev -p 3000'
12  start_mvp_stack.ps1: does NOT use 'npm run dev -- -p 3000'
13  seed_chart_ohlcv_history.py exists
14  seed script is valid Python (parses without SyntaxError)
15  seed script generates >= 120 candles for AAPL
16  seed script covers all required symbols (AAPL, GLD, TLT, BTC-USD, SPY)
17  seed script generates >= 120 candles per required symbol
18  seed candles contain all required OHLCV fields
19  seed candles: advisory_status == ADVISORY_ONLY
20  seed candles: execution_gate == LOCKED
21  seed candles: human_review_required is True
22  seed candles: ai_execution_count == 0
23  seed candles: broker_api_called is False
24  seed candles: broker_order_id == NONE
25  seed script has no forbidden execution strings
26  seed script is idempotent: second run inserts 0 new rows
27  After seeding, _candles_from_market_events returns >= 120 candles per symbol
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_SEED_PATH = REPO_ROOT / "scripts" / "seed_chart_ohlcv_history.py"
_API_SERVER = REPO_ROOT / "scripts" / "api_server.py"
_PROXY_SCRIPT = REPO_ROOT / "scripts" / "windows" / "local_frontend_reverse_proxy.py"
_MVP_STACK = REPO_ROOT / "scripts" / "windows" / "start_mvp_stack.ps1"

_REQUIRED_SYMBOLS = ["AAPL", "GLD", "TLT", "BTC-USD", "SPY"]
_MIN_CANDLES = 120

_FORBIDDEN_SEED_STRINGS = [
    "buy(",
    "sell(",
    "place_order",
    "submit_order",
    "execute_trade",
    "broker_api(",
    "private_key",
    "sign(",
    "send_transaction",
    "wallet(",
    "broker_execute",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cors_origins_from_ast() -> list[str]:
    """Legacy AST helper — still used by other tests to assert the literal list
    when one is present.  CORS is now env-driven via scripts.runtime_config,
    so we also offer a runtime-mode lookup below.
    """
    src = _API_SERVER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "add_middleware"):
            continue
        for kw in node.keywords:
            if kw.arg != "allow_origins":
                continue
            if isinstance(kw.value, ast.List):
                return [
                    elt.value
                    for elt in kw.value.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                ]
    return []


def _cors_origins_default() -> list[str]:
    """Resolve the default CORS allowlist from scripts.runtime_config.

    The api_server now reads ``ALLOWED_ORIGINS`` from the environment; with no
    override, it falls back to the project's default localhost +
    sleepingpassenger origins.  This helper mirrors that resolution path so
    the original Phase E.2 origin-allowlist intent is still pinned.
    """
    import os
    saved = os.environ.pop("ALLOWED_ORIGINS", None)
    try:
        from scripts.runtime_config import get_allowed_origins
        return list(get_allowed_origins())
    finally:
        if saved is not None:
            os.environ["ALLOWED_ORIGINS"] = saved


@pytest.fixture(scope="module")
def cors_origins() -> list[str]:
    """Effective CORS allowlist.

    Prefers the inline AST list when present (legacy behaviour); falls back to
    the env-driven default when api_server now resolves origins at startup.
    """
    ast_list = _cors_origins_from_ast()
    return ast_list if ast_list else _cors_origins_default()


@pytest.fixture(scope="module")
def seed_mod():
    spec = importlib.util.spec_from_file_location("seed_chart_ohlcv_history", _SEED_PATH)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# A. CORS origin tests
# ---------------------------------------------------------------------------

# S7: the sleepingpassenger* hostnames were REMOVED from the default CORS
# allowlist (a hosts-file remap could turn them into a trusted scripting
# surface).  They are now opt-in only via ALLOWED_ORIGINS.  These tests are
# inverted to pin the new secure default + the opt-in path.
def _origins_with_env(value: str) -> list[str]:
    import os
    saved = os.environ.get("ALLOWED_ORIGINS")
    os.environ["ALLOWED_ORIGINS"] = value
    try:
        from scripts.runtime_config import get_allowed_origins
        return list(get_allowed_origins())
    finally:
        if saved is None:
            os.environ.pop("ALLOWED_ORIGINS", None)
        else:
            os.environ["ALLOWED_ORIGINS"] = saved


def test_cors_sleepingpassenger(cors_origins):
    # S7: absent from defaults...
    assert "http://sleepingpassenger" not in cors_origins
    # ...but available when the operator explicitly opts in.
    assert "http://sleepingpassenger" in _origins_with_env("http://sleepingpassenger")


def test_cors_sleepingpassenger_local(cors_origins):
    # S7: absent from defaults.
    assert "http://sleepingpassenger.local" not in cors_origins


def test_cors_localhost_3000(cors_origins):
    assert "http://localhost:3000" in cors_origins


def test_cors_127_0_0_1_3000(cors_origins):
    assert "http://127.0.0.1:3000" in cors_origins


def test_cors_sleepingpassenger_port80(cors_origins):
    # S7: absent from defaults.
    assert "http://sleepingpassenger:80" not in cors_origins


def test_cors_sleepingpassenger_local_port80(cors_origins):
    # S7: absent from defaults.
    assert "http://sleepingpassenger.local:80" not in cors_origins


def test_cors_no_wildcard(cors_origins):
    assert "*" not in cors_origins


# ---------------------------------------------------------------------------
# B. Proxy path/query preservation
# ---------------------------------------------------------------------------

def test_proxy_forwards_self_path():
    src = _PROXY_SCRIPT.read_text(encoding="utf-8")
    assert "self.path" in src, "Proxy must forward self.path (includes path + query string)"


def test_proxy_query_string_preserved():
    src = _PROXY_SCRIPT.read_text(encoding="utf-8")
    assert "self.path" in src, "self.path already includes ?query so no extra handling needed"


def test_proxy_host_header_set():
    src = _PROXY_SCRIPT.read_text(encoding="utf-8")
    assert '"Host"' in src or "'Host'" in src, "Proxy must set Host header for upstream"


# ---------------------------------------------------------------------------
# C. start_mvp_stack.ps1 port pinning
# ---------------------------------------------------------------------------

def test_mvp_stack_uses_npx_next_dev():
    src = _MVP_STACK.read_text(encoding="utf-8")
    assert "npx next dev -p 3000" in src, (
        "start_mvp_stack.ps1 must use 'npx next dev -p 3000'"
    )


def test_mvp_stack_not_npm_run_dev_port():
    src = _MVP_STACK.read_text(encoding="utf-8")
    assert "npm run dev -- -p 3000" not in src, (
        "start_mvp_stack.ps1 must not use 'npm run dev -- -p 3000' (may misparse port)"
    )


# ---------------------------------------------------------------------------
# D. Seed script existence and syntax
# ---------------------------------------------------------------------------

def test_seed_script_exists():
    assert _SEED_PATH.exists(), f"Missing: {_SEED_PATH}"


def test_seed_script_parses():
    src = _SEED_PATH.read_text(encoding="utf-8")
    ast.parse(src)


def test_seed_no_forbidden_strings():
    src = _SEED_PATH.read_text(encoding="utf-8").lower()
    for bad in _FORBIDDEN_SEED_STRINGS:
        assert bad.lower() not in src, f"Forbidden string in seed script: {bad!r}"


# ---------------------------------------------------------------------------
# D. Candle generation (pure, no DB)
# ---------------------------------------------------------------------------

def test_seed_aapl_min_candles(seed_mod):
    assert len(seed_mod.generate_candles("AAPL")) >= _MIN_CANDLES


def test_seed_all_symbols_min_candles(seed_mod):
    for sym in _REQUIRED_SYMBOLS:
        count = len(seed_mod.generate_candles(sym))
        assert count >= _MIN_CANDLES, f"{sym}: got {count}, need >= {_MIN_CANDLES}"


def test_seed_candles_have_ohlcv_fields(seed_mod):
    required = {"open", "high", "low", "close", "volume", "timestamp", "symbol"}
    for c in seed_mod.generate_candles("AAPL"):
        missing = required - c.keys()
        assert not missing, f"Candle missing fields: {missing}"


def test_seed_advisory_status(seed_mod):
    for sym in _REQUIRED_SYMBOLS:
        for c in seed_mod.generate_candles(sym):
            assert c["advisory_status"] == "ADVISORY_ONLY"


def test_seed_execution_gate_locked(seed_mod):
    for sym in _REQUIRED_SYMBOLS:
        for c in seed_mod.generate_candles(sym):
            assert c["execution_gate"] == "LOCKED"


def test_seed_human_review_required(seed_mod):
    for sym in _REQUIRED_SYMBOLS:
        for c in seed_mod.generate_candles(sym):
            assert c["human_review_required"] is True


def test_seed_ai_execution_count_zero(seed_mod):
    for sym in _REQUIRED_SYMBOLS:
        for c in seed_mod.generate_candles(sym):
            assert c["ai_execution_count"] == 0


def test_seed_broker_api_called_false(seed_mod):
    for sym in _REQUIRED_SYMBOLS:
        for c in seed_mod.generate_candles(sym):
            assert c["broker_api_called"] is False


def test_seed_broker_order_id_none(seed_mod):
    for sym in _REQUIRED_SYMBOLS:
        for c in seed_mod.generate_candles(sym):
            assert c["broker_order_id"] == "NONE"


# ---------------------------------------------------------------------------
# D. Idempotency (real SQLite in tmp_path)
# ---------------------------------------------------------------------------

def test_seed_idempotent(seed_mod, tmp_path):
    db = tmp_path / "seed_idem.db"
    import scripts.persistence as p

    for sym in _REQUIRED_SYMBOLS:
        candles = seed_mod.generate_candles(sym)
        first_run = 0
        second_run = 0
        for c in candles:
            date_str = c["timestamp"][:10]
            eid = seed_mod._event_id(sym, date_str)
            if p.insert_signal_event(
                event_id=eid,
                source_name="market_data",
                raw_payload=c,
                fetched_at=c["timestamp"],
                db_path=db,
            ):
                first_run += 1
        for c in candles:
            date_str = c["timestamp"][:10]
            eid = seed_mod._event_id(sym, date_str)
            if p.insert_signal_event(
                event_id=eid,
                source_name="market_data",
                raw_payload=c,
                fetched_at=c["timestamp"],
                db_path=db,
            ):
                second_run += 1
        assert first_run >= _MIN_CANDLES, f"{sym}: first run inserted {first_run}"
        assert second_run == 0, f"{sym}: second run should insert 0, got {second_run}"


# ---------------------------------------------------------------------------
# E. End-to-end: seeded DB -> _candles_from_market_events
# ---------------------------------------------------------------------------

def test_candles_from_seeded_events(seed_mod, tmp_path):
    db = tmp_path / "seed_e2e.db"
    import scripts.persistence as p
    from scripts.chart_structure_api_context import _candles_from_market_events

    for sym in _REQUIRED_SYMBOLS:
        for c in seed_mod.generate_candles(sym):
            date_str = c["timestamp"][:10]
            eid = seed_mod._event_id(sym, date_str)
            p.insert_signal_event(
                event_id=eid,
                source_name="market_data",
                raw_payload=c,
                fetched_at=c["timestamp"],
                db_path=db,
            )

    for sym in _REQUIRED_SYMBOLS:
        events = p.get_signal_events(source_name="market_data", limit=1000, db_path=db)
        sym_events = [
            ev for ev in events
            if (ev.get("raw_payload") or {}).get("symbol", "").upper() == sym.upper()
        ]
        parsed = _candles_from_market_events(sym_events)
        assert len(parsed) >= _MIN_CANDLES, (
            f"{sym}: expected >= {_MIN_CANDLES} candles after seeding, got {len(parsed)}"
        )
