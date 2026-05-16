"""Guard: pytest runs must not corrupt logs/live_signal_refresh_summary.json.

Defensive engineering — observability of the live-source refresh cycle
depends on this file being trustworthy.  Before the conftest-level
isolation, tests that called ``refresh_live_signals.run_refresh`` would
overwrite the operator's real summary with pytest artifacts, masking
real refresh failures with stale or empty data.

This module locks in two invariants:

1. The session-wide pytest harness redirects writes elsewhere via the
   ``MVP_LIVE_REFRESH_SUMMARY_PATH`` env var.  Calling ``run_refresh``
   in a test never touches the real ``logs/live_signal_refresh_summary.json``.

2. The orchestrator honours an explicit ``summary_path`` kwarg with the
   highest precedence, and reads the env var as the next fallback.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import scripts.refresh_live_signals as orch
from scripts import persistence


_REPO_ROOT = Path(__file__).resolve().parents[1]
_REAL_SUMMARY = _REPO_ROOT / "logs" / "live_signal_refresh_summary.json"


@pytest.fixture()
def _isolated_db(tmp_path, monkeypatch):
    db = tmp_path / "refresh_isolation.db"
    monkeypatch.setattr(persistence, "DB_PATH", db)
    persistence.init_schema(db)
    return db


def _stub_runners(monkeypatch):
    monkeypatch.setattr(orch, "_invoke_phase1_single",
                        lambda key, dry_run: {"status": "ok"})
    monkeypatch.setattr(orch, "_invoke_phase2_single",
                        lambda key, dry_run: {"status": "ok"})


def test_pytest_session_envvar_redirects_summary_writes() -> None:
    """Conftest must set ``MVP_LIVE_REFRESH_SUMMARY_PATH`` for the whole
    session.  If this assertion ever fails, the session-wide guard has
    regressed and other tests may begin clobbering the operator file."""
    env_val = os.environ.get("MVP_LIVE_REFRESH_SUMMARY_PATH", "")
    assert env_val, (
        "conftest must set MVP_LIVE_REFRESH_SUMMARY_PATH for the pytest session"
    )
    assert str(_REAL_SUMMARY) != env_val, (
        "MVP_LIVE_REFRESH_SUMMARY_PATH must NOT point at the real "
        "operator summary file during tests"
    )


def test_run_refresh_does_not_touch_real_summary(_isolated_db, monkeypatch):
    """The session envvar redirects writes; the real file is untouched."""
    _stub_runners(monkeypatch)

    before_bytes = _REAL_SUMMARY.read_bytes() if _REAL_SUMMARY.exists() else None
    before_mtime = _REAL_SUMMARY.stat().st_mtime if _REAL_SUMMARY.exists() else None

    orch.run_refresh(write_mode=False)

    if before_bytes is None:
        # If the real file did not exist before, it must still not exist.
        assert not _REAL_SUMMARY.exists(), (
            "run_refresh created the real summary file from a test"
        )
    else:
        assert _REAL_SUMMARY.read_bytes() == before_bytes, (
            "run_refresh corrupted the real operator summary file"
        )
        assert _REAL_SUMMARY.stat().st_mtime == before_mtime, (
            "run_refresh modified the real operator summary file mtime"
        )


def test_explicit_summary_path_takes_precedence(
    _isolated_db, monkeypatch, tmp_path
) -> None:
    _stub_runners(monkeypatch)
    explicit = tmp_path / "explicit_summary.json"
    # Even though the session env var is set to another location, the
    # explicit kwarg must win.
    summary = orch.run_refresh(write_mode=False, summary_path=explicit)
    assert explicit.exists()
    payload = json.loads(explicit.read_text(encoding="utf-8"))
    assert payload["run_id"] == summary["run_id"]
    assert payload["broker_api_called"] is False


def test_envvar_fallback_when_no_explicit_path(
    _isolated_db, monkeypatch, tmp_path
) -> None:
    _stub_runners(monkeypatch)
    target = tmp_path / "envvar_summary.json"
    monkeypatch.setenv("MVP_LIVE_REFRESH_SUMMARY_PATH", str(target))
    orch.run_refresh(write_mode=False)
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"


def test_resolve_summary_path_returns_module_default_when_no_overrides(
    monkeypatch,
) -> None:
    monkeypatch.delenv("MVP_LIVE_REFRESH_SUMMARY_PATH", raising=False)
    assert orch._resolve_summary_path() == orch._SUMMARY_PATH


def test_summary_writer_preserves_safety_stamps(
    _isolated_db, monkeypatch, tmp_path
) -> None:
    _stub_runners(monkeypatch)
    target = tmp_path / "safety_summary.json"
    orch.run_refresh(write_mode=False, summary_path=target)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["can_execute"] is False
    assert payload["ai_execution_count"] == 0
