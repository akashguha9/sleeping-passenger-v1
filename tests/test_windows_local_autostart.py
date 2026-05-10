"""Phase E.1 — Tests for Windows local auto-start scripts."""
import pathlib

REPO_ROOT   = pathlib.Path(__file__).parent.parent
WINDOWS_DIR = REPO_ROOT / "scripts" / "windows"

_SCRIPTS = [
    "start_mvp_stack.ps1",
    "poll_live_sources.ps1",
    "register_mvp_startup_task.ps1",
    "unregister_mvp_startup_task.ps1",
    "add_sleepingpassenger_host_alias.ps1",
    "remove_sleepingpassenger_host_alias.ps1",
    "start_sleepingpassenger_proxy.ps1",
    "local_frontend_reverse_proxy.py",
]

_FORBIDDEN = [
    "buy",
    "sell",
    "execute_trade",
    "place_order",
    "submit_order",
    "broker_order",
    "wallet",
    "private_key",
    "send_transaction",
    "sign_transaction",
]


def test_all_scripts_exist():
    for name in _SCRIPTS:
        assert (WINDOWS_DIR / name).exists(), f"Missing: scripts/windows/{name}"


def test_poll_interval_300_seconds():
    content = (WINDOWS_DIR / "poll_live_sources.ps1").read_text(encoding="utf-8")
    assert "300" in content, "Poll interval 300 not found in poll_live_sources.ps1"


def test_poller_sources_present():
    content = (WINDOWS_DIR / "poll_live_sources.ps1").read_text(encoding="utf-8")
    assert "polymarket" in content
    assert "gdelt" in content
    assert "market_data" in content


def test_no_forbidden_strings_in_windows_scripts():
    for name in _SCRIPTS:
        content = (WINDOWS_DIR / name).read_text(encoding="utf-8", errors="replace").lower()
        for term in _FORBIDDEN:
            assert term not in content, (
                f"Forbidden string '{term}' found in scripts/windows/{name}"
            )


def test_task_name_in_register_script():
    content = (WINDOWS_DIR / "register_mvp_startup_task.ps1").read_text(encoding="utf-8")
    assert "PipelineV57LocalMVP" in content


def test_task_name_in_unregister_script():
    content = (WINDOWS_DIR / "unregister_mvp_startup_task.ps1").read_text(encoding="utf-8")
    assert "PipelineV57LocalMVP" in content


def test_host_aliases_in_add_script():
    content = (WINDOWS_DIR / "add_sleepingpassenger_host_alias.ps1").read_text(encoding="utf-8")
    assert "sleepingpassenger" in content
    assert "sleepingpassenger.local" in content


def test_reverse_proxy_targets():
    content = (WINDOWS_DIR / "local_frontend_reverse_proxy.py").read_text(encoding="utf-8")
    assert "127.0.0.1" in content
    assert "3000" in content
    assert "80" in content


def test_readme_documents_sleepingpassenger():
    content = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "http://sleepingpassenger" in content


def test_no_em_dash_in_ps1_scripts():
    """Em-dash (U+2014) inside double-quoted PowerShell strings causes parse errors."""
    em_dash = "—"
    for name in _SCRIPTS:
        if not name.endswith(".ps1"):
            continue
        content = (WINDOWS_DIR / name).read_text(encoding="utf-8", errors="replace")
        assert em_dash not in content, (
            f"Em-dash found in scripts/windows/{name} -- replace with ' - '"
        )


def test_backend_uses_python_m_uvicorn():
    content = (WINDOWS_DIR / "start_mvp_stack.ps1").read_text(encoding="utf-8")
    assert "python -m uvicorn" in content, (
        "start_mvp_stack.ps1 must launch backend with 'python -m uvicorn', not bare 'uvicorn'"
    )
    assert "uvicorn scripts.api_server:app" in content


def test_frontend_pinned_to_port_3000():
    content = (WINDOWS_DIR / "start_mvp_stack.ps1").read_text(encoding="utf-8")
    assert "-p 3000" in content, (
        "start_mvp_stack.ps1 must pin frontend to port 3000 (proxy expects this port)"
    )


def test_chart_structure_api_context_importable():
    """_candles_from_market_events must be importable without fastapi installed."""
    import importlib
    mod = importlib.import_module("scripts.chart_structure_api_context")
    assert callable(getattr(mod, "_candles_from_market_events", None))
