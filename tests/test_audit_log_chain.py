"""Tamper-evident audit log proofs (Pass 3, Phase 6)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import audit_log as al
from scripts import verify_audit_log as val


@pytest.fixture
def log_path(tmp_path, monkeypatch):
    path = tmp_path / "audit_log.jsonl"
    monkeypatch.setenv("MVP_AUDIT_LOG_PATH", str(path))
    return path


def _append_n(path: Path, n: int) -> None:
    for i in range(n):
        al.append_event(
            "journal_write", actor="owner", action=f"POST /manual-trades#{i}",
            outcome="http_200", path=path,
        )


def test_chain_appends_and_verifies(log_path):
    _append_n(log_path, 5)
    result = val.verify_chain(log_path)
    assert result["valid"] is True
    assert result["events"] == 5
    # Genesis link is pinned.
    first = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert first["previous_hash"] == "0" * 64


def test_hash_formula_is_pinned(log_path):
    event = al.append_event("export", action="GET /exports/x.csv", path=log_path)
    recomputed = al.compute_event_hash(
        {k: v for k, v in event.items() if k != "event_hash"},
        event["previous_hash"],
    )
    assert recomputed == event["event_hash"]


def test_modified_event_detected(log_path):
    _append_n(log_path, 3)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    middle = json.loads(lines[1])
    middle["action"] = "POST /something-else"  # tamper
    lines[1] = al.canonical_json(middle)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = val.verify_chain(log_path)
    assert result["valid"] is False
    assert any("event_hash mismatch" in e for e in result["errors"])


def test_deleted_event_breaks_chain(log_path):
    _append_n(log_path, 4)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    del lines[1]  # remove an interior event
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = val.verify_chain(log_path)
    assert result["valid"] is False
    assert any("broken chain" in e for e in result["errors"])


def test_truncated_head_breaks_genesis(log_path):
    _append_n(log_path, 3)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    log_path.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
    result = val.verify_chain(log_path)
    assert result["valid"] is False


def test_invalid_json_detected(log_path):
    _append_n(log_path, 2)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write("{not valid json\n")
    result = val.verify_chain(log_path)
    assert result["valid"] is False
    assert any("invalid JSON" in e for e in result["errors"])


def test_empty_or_missing_log_is_valid(tmp_path):
    assert val.verify_chain(tmp_path / "nope.jsonl")["valid"] is True


def test_metadata_redaction(log_path):
    event = al.append_event(
        "settings_change",
        metadata={
            "api_token": "raw-token-value",
            "some_secret": "shh",
            "Authorization": "Bearer abc",
            "stored_hash": "a" * 64,
            "note": "x" * 500,
            "count": 3,
        },
        path=log_path,
    )
    meta = event["metadata"]
    assert meta["api_token"] == "<redacted>"
    assert meta["some_secret"] == "<redacted>"
    assert meta["Authorization"] == "<redacted>"
    assert meta["stored_hash"] == "<redacted>"  # 64-hex strings never persist
    assert len(meta["note"]) <= 161
    assert meta["count"] == 3
    raw = log_path.read_text(encoding="utf-8")
    assert "raw-token-value" not in raw
    assert "shh" not in raw
    assert "a" * 64 not in raw


def test_unknown_event_type_and_actor_fail_closed(log_path):
    event = al.append_event("made_up_type", actor="root", path=log_path)
    assert event["event_type"] == "other"
    assert event["actor"] == "unknown"


def test_verifier_cli_exit_codes(log_path, capsys):
    _append_n(log_path, 2)
    assert val.main(["--path", str(log_path)]) == 0
    lines = log_path.read_text(encoding="utf-8").splitlines()
    del lines[0]
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert val.main(["--path", str(log_path)]) == 1


# ---------------------------------------------------------------------------
# Route emission: the API middleware writes chained events
# ---------------------------------------------------------------------------


def test_api_emits_audit_events_for_sensitive_actions(log_path, monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    monkeypatch.delenv("MVP_API_TOKEN", raising=False)
    monkeypatch.setenv("MVP_API_TOKEN", "audit-test-token")
    import scripts.api_server as srv

    client = TestClient(srv.app)
    headers = {"Authorization": "Bearer audit-test-token"}
    client.get("/exports/manual-trades.csv", headers=headers)
    # Five consecutive 401s → one auth_failure_burst event.
    for _ in range(5):
        client.get("/manual-trades", headers={"Authorization": "Bearer wrong"})

    result = val.verify_chain(log_path)
    assert result["valid"] is True
    events = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines()]
    types = [e["event_type"] for e in events]
    assert "export" in types
    assert "auth_failure_burst" in types
    raw = log_path.read_text(encoding="utf-8")
    assert "audit-test-token" not in raw  # tokens never reach the log
