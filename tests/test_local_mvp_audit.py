"""Sprint 9A — local MVP audit summary tests.

Tests the read-only Python helpers in scripts/local_mvp_audit.py and
verifies the PowerShell wrapper script exists with the right safety
posture (advisory-only / no broker / no execution).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import local_mvp_audit
from scripts import persistence
from scripts import signal_inbox_api

REPO_ROOT = Path(__file__).resolve().parents[1]


def _rebind_defaults(fn, new_db: Path) -> None:
    if fn.__defaults__:
        new_defs = tuple(new_db if isinstance(d, Path) else d for d in fn.__defaults__)
        fn.__defaults__ = new_defs
    if fn.__kwdefaults__:
        fn.__kwdefaults__ = {
            k: (new_db if isinstance(v, Path) else v)
            for k, v in fn.__kwdefaults__.items()
        }


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "audit.db"
    persistence.init_schema(db)
    for name in [
        "init_schema", "_get_conn", "insert_manual_trade",
        "get_trades_for_event", "get_event_id_for_trade",
        "get_all_manual_trades", "insert_reconciliation",
        "get_reconciliations_for_trade", "get_all_reconciliations",
    ]:
        fn = getattr(persistence, name, None)
        if fn is None:
            continue
        _rebind_defaults(fn, db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=True)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(signal_inbox_api, "MANUAL_TRADE_LOG", log_dir / "mt.jsonl")
    monkeypatch.setattr(signal_inbox_api, "RECONCILIATIONS_LOG", log_dir / "rec.jsonl")
    monkeypatch.setattr(signal_inbox_api, "REFLECTIONS_LOG", log_dir / "ref.jsonl")
    monkeypatch.setattr(signal_inbox_api, "AI_SUMMARIES_LOG", log_dir / "ai.jsonl")
    monkeypatch.setattr(signal_inbox_api, "INBOX_STATES_LOG", log_dir / "inbox.jsonl")
    yield db


def test_run_audit_returns_complete_envelope(tmp_db: Path) -> None:
    payload = local_mvp_audit.run_audit(tmp_db)
    assert payload["report"] == "local_mvp_audit"
    assert payload["db_exists"] is True
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["execution_permission"] is False
    assert payload["can_execute"] is False
    assert payload["overall"] in {"PASS", "WARN", "FAIL"}
    sections = payload["sections"]
    for required in (
        "safety_invariants",
        "token_status",
        "paper_ledger",
        "calibration",
        "learning_completeness",
        "source_health",
    ):
        assert required in sections


def test_safety_invariants_section_locks_execution() -> None:
    inv = local_mvp_audit._safety_invariants()
    assert inv["advisory_only"] is True
    assert inv["execution_gate"] == "LOCKED"
    assert inv["broker_api_called"] is False
    assert inv["ai_execution_count"] == 0
    assert inv["execution_permission"] is False
    assert inv["can_execute"] is False


def test_paper_ledger_section_counts_modes(tmp_db: Path) -> None:
    signal_inbox_api.log_manual_trade(
        event_id="EV_P1", ticker="X", side="BUY", quantity=1.0, price=1.0,
        thesis="paper", trade_mode="PAPER",
    )
    signal_inbox_api.log_manual_trade(
        event_id="EV_P2", ticker="X", side="BUY", quantity=1.0, price=1.0,
        thesis="paper", trade_mode="PAPER",
    )
    signal_inbox_api.log_manual_trade(
        event_id="EV_R", ticker="Y", side="BUY", quantity=1.0, price=1.0,
        thesis="real", trade_mode="REAL_MANUAL",
    )
    section = local_mvp_audit.paper_ledger_section(tmp_db)
    assert section["db_available"] is True
    assert section["trade_mode_column_present"] is True
    assert section["paper_trade_count"] == 2
    assert section["real_manual_trade_count"] == 1
    assert section["broker_api_called"] is False


def test_token_status_section_does_not_leak_value(monkeypatch) -> None:
    monkeypatch.setenv("MVP_API_TOKEN", "secret-do-not-leak")
    section = local_mvp_audit.token_status_section()
    assert section["mvp_api_token_set"] is True
    # Token value is never present in the output.
    blob = str(section).lower()
    assert "secret-do-not-leak" not in blob
    assert "secret" not in blob


def test_powershell_wrapper_exists_with_safety_doctrine() -> None:
    ps1 = REPO_ROOT / "scripts" / "windows" / "run_local_mvp_audit.ps1"
    assert ps1.exists()
    text = ps1.read_text(encoding="utf-8")
    # Safety doctrine assertions.
    assert "ADVISORY_ONLY" in text
    assert "HUMAN_EXECUTION_REQUIRED" in text
    assert "execution_gate" in text
    assert "LOCKED" in text
    assert "broker_api_called" in text
    # Forbidden phrases (affirmative use only — the wrapper's docstring
    # legitimately uses negated forms like "does NOT auto-trade").  These
    # phrases should never appear UNLESS preceded by a negation in the
    # same line.
    lower = text.lower()
    for bad in (
        "place order",
        "submit order",
        "execute trade",
        "permission granted",
        "ai-approved",
        "broker api call",
    ):
        for line in lower.splitlines():
            if bad in line:
                negators = (" not ", " never ", "no ", "does not", "forbidden", "doesn't")
                assert any(n in line for n in negators), (
                    f"forbidden phrase {bad!r} found without negation: {line!r}"
                )


def test_powershell_wrapper_no_secrets_committed() -> None:
    ps1 = REPO_ROOT / "scripts" / "windows" / "run_local_mvp_audit.ps1"
    text = ps1.read_text(encoding="utf-8")
    # The wrapper must NOT hardcode any token / key / secret.
    lower = text.lower()
    # Tokens of this form should never appear.
    for needle in ("mvp_api_token=", "api_key=", "secret=", "password="):
        assert needle not in lower
