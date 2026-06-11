"""Adversarial tests for the advisory-only hard boundary audit.

Forbidden probes are assembled at runtime (this file is exempt from the
repo scan as a test file, but the probes still never appear as literals —
defense in depth against every other scanner in the repo).
"""
from __future__ import annotations

from pathlib import Path

from scripts import audit_advisory_only_boundary as boundary


def _j(*parts: str) -> str:
    """Runtime assembly so forbidden shapes never exist in this source."""
    return "".join(parts)


# ---------------------------------------------------------------------------
# The real repo passes
# ---------------------------------------------------------------------------


def test_real_repo_has_no_execution_shaped_code():
    assert boundary.scan_repo() == []


def test_real_repo_carries_disclaimers():
    assert boundary.audit_disclaimers() == []


def test_guard_file_list_is_small_and_reviewed():
    # The exemption list growing quietly would hollow out the audit.
    assert len(boundary.GUARD_FILES) <= 14
    for entry in boundary.GUARD_FILES:
        assert (Path(boundary._REPO_ROOT) / entry).exists(), entry


# ---------------------------------------------------------------------------
# Real execution-shaped code FAILS
# ---------------------------------------------------------------------------


def test_broker_sdk_import_fails():
    code = _j("import alp", "aca_trade_api as tradeapi\n")
    assert boundary.scan_text(code, "scripts/new_module.py")


def test_order_placement_call_fails():
    code = _j("client.", "submit", "_order", "(symbol, qty, side)\n")
    assert boundary.scan_text(code, "scripts/new_module.py")


def test_market_order_helper_fails():
    code = _j("def ", "create_market", "_order", "(symbol):\n    pass\n")
    assert boundary.scan_text(code, "scripts/helpers.py")


def test_execution_route_fails():
    code = _j('@app.post("', "/orders/", "place", '")\n')
    assert boundary.scan_text(code, "scripts/api_server_ext.py")


def test_buy_sell_routes_fail():
    for path_token in ("buy", "sell"):
        code = _j('@app.post("/', path_token, '")\n')
        assert boundary.scan_text(code, "scripts/api_server_ext.py"), path_token


def test_live_trading_loop_fails():
    code = _j("def run_live_", "trading_loop", "():\n    pass\n")
    assert boundary.scan_text(code, "scripts/loop.py")


def test_auto_execute_flag_fails():
    code = _j("if cfg.auto_", "execute:\n    run()\n")
    assert boundary.scan_text(code, "scripts/runner.py")


def test_rebalancing_executor_fails():
    code = _j("class Rebalancing", "Executor:\n    pass\n")
    assert boundary.scan_text(code, "scripts/rebalance.py")


def test_broker_webhook_fails():
    code = _j('URL = "https://api.alp', 'aca.markets/v2/"\n')
    assert boundary.scan_text(code, "scripts/feed.py")


# ---------------------------------------------------------------------------
# Allowed contexts do NOT fail
# ---------------------------------------------------------------------------


def test_advisory_scoring_code_passes():
    code = (
        "def score_signal(signal):\n"
        "    return 0.6 * signal.calibration + 0.4 * signal.freshness\n"
    )
    assert boundary.scan_text(code, "scripts/scoring.py") == []


def test_manual_trade_journaling_passes():
    code = (
        '@app.post("/manual-trades")\n'
        "def log_manual_trade(entry):\n"
        "    return persistence.insert_manual_trade(entry)\n"
    )
    assert boundary.scan_text(code, "scripts/api_server_ext.py") == []


def test_paper_simulation_is_classified_separately_not_flagged():
    paper = boundary.classify_paper_simulation(
        ["scripts/paper_execution.py", "scripts/scoring.py"]
    )
    assert paper == ["scripts/paper_execution.py"]
    code = "def simulate_paper_fill(signal):\n    return mark_to_market(signal)\n"
    assert boundary.scan_text(code, "scripts/paper_execution.py") == []


def test_denial_comments_in_code_pass():
    code = _j("# This module never calls ", "place_order",
              "( or any broker API\n")
    assert boundary.scan_text(code, "scripts/clean.py") == []


def test_markdown_docs_never_flagged():
    text = _j("The system has no ", "live trading loop",
              " and never calls ", "submit_order", "(.\n")
    assert boundary.scan_text(text, "docs/SAFETY.md") == []


def test_docs_disclaimer_alone_does_not_satisfy_audit(tmp_path):
    """A repo with a perfect disclaimer but execution code must still fail:
    the code scan and the disclaimer check are independent."""
    code = _j("client.", "place", "_order", "(symbol)\n")
    assert boundary.scan_text(code, "scripts/exec.py"), (
        "execution code must fail regardless of any disclaimer"
    )
    # And conversely a clean code line cannot stand in for the disclaimer.
    missing = boundary.audit_disclaimers(tmp_path)
    assert len(missing) == 2  # README + SECURITY both absent


# ---------------------------------------------------------------------------
# Live FastAPI surface: no route exposes execution semantics
# ---------------------------------------------------------------------------


def test_no_fastapi_route_has_execution_semantics():
    import pytest

    try:
        from scripts import api_server
    except Exception:  # pragma: no cover - fastapi missing in minimal envs
        pytest.skip("scripts.api_server not importable here")
    forbidden = ("execute", "/buy", "/sell", "order/place", "orders/place",
                 "place-order", "rebalance/run")
    paths = [getattr(r, "path", "") for r in api_server.app.routes]
    assert paths, "expected routes on the live app"
    for path in paths:
        lowered = path.lower()
        for token in forbidden:
            assert token not in lowered, f"route {path} has execution semantics"
