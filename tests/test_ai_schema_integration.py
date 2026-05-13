"""
Integration tests for the AI output schema wiring into the signal inbox.

Coverage
--------
- ``scripts.signal_inbox_api.add_ai_discussion_summary`` routes every
  caller-supplied AI summary through ``validate_ai_interpretation_payload``.
- ``validation_status`` is returned to the caller and persisted to the
  JSONL log.
- Malformed AI payloads do not crash; they are recorded as ``partial`` or
  ``invalid`` with descriptive errors.
- An attempt to set ``execution_permission=True`` or ``broker_api_called=True``
  in the optional structured payload is silently overridden to safe values
  on both the response and the persisted entry.
- Secret-looking patterns in the summary text or raw_response are redacted
  before they touch disk.
- The advisory-only invariants are preserved end-to-end.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _import_api():
    import scripts.signal_inbox_api as api
    return api


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# Happy path: structured AI payload flows through validator
# ---------------------------------------------------------------------------


def test_add_ai_summary_runs_through_validator(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "AI_SUMMARIES_LOG", tmp_path / "ai_summaries.jsonl")
    # Force JSONL-only persistence so the DB path is irrelevant to assertions
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    result = api.add_ai_discussion_summary(
        "FABRIC_QQQ",
        "Price persistence is elevated. No execution implied.",
        ai_payload={
            "model_name": "grok-3-mini",
            "provider": "xai",
            "prompt_version": "test-v1",
            "summary": "Price persistence is elevated. No execution implied.",
            "confidence_score": 0.62,
            "contradiction_flags": ["narrative_thin"],
        },
    )

    assert result["status"] == "logged"
    assert result["validation_status"] == "valid"
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["ai_execution_count"] == 0
    assert result["execution_gate"] == "LOCKED"
    assert result["execution_permission"] is False
    assert result["can_execute"] is False
    assert result["broker_api_called"] is False

    rows = _read_jsonl(tmp_path / "ai_summaries.jsonl")
    assert len(rows) == 1
    persisted = rows[0]
    assert persisted["validation_status"] == "valid"
    assert persisted["advisory_status"] == "ADVISORY_ONLY"
    assert persisted["ai_execution_count"] == 0
    assert persisted["broker_api_called"] is False
    assert persisted["execution_permission"] is False
    assert persisted["can_execute"] is False
    assert persisted["prompt_version"] == "test-v1"


def test_add_ai_summary_backwards_compatible_without_payload(tmp_path, monkeypatch):
    """Calling with only summary_text must still work (no structured payload)."""
    api = _import_api()
    monkeypatch.setattr(api, "AI_SUMMARIES_LOG", tmp_path / "ai_summaries.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    result = api.add_ai_discussion_summary("FABRIC_SPY", "Plain text summary only.")
    assert result["status"] == "logged"
    assert result["validation_status"] in {"valid", "partial"}
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["ai_execution_count"] == 0

    rows = _read_jsonl(tmp_path / "ai_summaries.jsonl")
    assert len(rows) == 1
    assert "validation_status" in rows[0]
    assert rows[0]["broker_api_called"] is False


# ---------------------------------------------------------------------------
# Malformed payloads: partial or invalid, never crash
# ---------------------------------------------------------------------------


def test_malformed_ai_payload_does_not_crash(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "AI_SUMMARIES_LOG", tmp_path / "ai_summaries.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    result = api.add_ai_discussion_summary(
        "FABRIC_QQQ",
        "Fallback summary text",
        ai_payload="this is not a dict",  # type: ignore[arg-type]
    )
    assert result["status"] == "logged"
    assert result["validation_status"] in {"partial", "invalid"}
    assert result["advisory_status"] == "ADVISORY_ONLY"

    rows = _read_jsonl(tmp_path / "ai_summaries.jsonl")
    assert len(rows) == 1
    assert rows[0]["broker_api_called"] is False


def test_ai_payload_with_confidence_out_of_range_marks_partial(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "AI_SUMMARIES_LOG", tmp_path / "ai_summaries.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    result = api.add_ai_discussion_summary(
        "FABRIC_QQQ",
        "Confidence rescale test",
        ai_payload={
            "summary": "Confidence rescale test",
            "confidence_score": 75,  # treated as percent -> partial
        },
    )
    assert result["validation_status"] == "partial"
    assert any("confidence" in err for err in result["validation_errors"])


# ---------------------------------------------------------------------------
# Safety override: caller cannot smuggle execution permission through
# ---------------------------------------------------------------------------


def test_attempted_execution_permission_is_overridden(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "AI_SUMMARIES_LOG", tmp_path / "ai_summaries.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    result = api.add_ai_discussion_summary(
        "FABRIC_QQQ",
        "Smuggling attempt",
        ai_payload={
            "summary": "Smuggling attempt",
            "execution_permission": True,
            "can_execute": True,
            "broker_api_called": True,
            "ai_execution_count": 9000,
            "advisory_status": "GO_AHEAD_AND_TRADE",
        },
    )
    assert result["validation_status"] in {"partial", "invalid"}
    assert result["execution_permission"] is False
    assert result["can_execute"] is False
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0
    assert result["advisory_status"] == "ADVISORY_ONLY"

    rows = _read_jsonl(tmp_path / "ai_summaries.jsonl")
    assert rows[0]["broker_api_called"] is False
    assert rows[0]["execution_permission"] is False
    assert rows[0]["can_execute"] is False
    assert rows[0]["ai_execution_count"] == 0


def test_broker_order_id_attempt_is_silently_dropped(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "AI_SUMMARIES_LOG", tmp_path / "ai_summaries.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    result = api.add_ai_discussion_summary(
        "FABRIC_QQQ",
        "Order id smuggle",
        ai_payload={
            "summary": "Order id smuggle",
            "broker_order_id": "BROKER_ORDER_12345",
        },
    )
    rows = _read_jsonl(tmp_path / "ai_summaries.jsonl")
    # The persisted entry must NOT contain a non-NONE broker_order_id field;
    # the validator strips this attempt and the response stays advisory.
    persisted_blob = json.dumps(rows[0])
    assert "BROKER_ORDER_12345" not in persisted_blob
    assert result["advisory_status"] == "ADVISORY_ONLY"


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------


def test_secret_pattern_in_summary_is_redacted(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "AI_SUMMARIES_LOG", tmp_path / "ai_summaries.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    leaky_text = "Here is my api_key=sk-ABCDEFGHIJKL1234567890 stop using it"
    api.add_ai_discussion_summary("FABRIC_QQQ", leaky_text)

    rows = _read_jsonl(tmp_path / "ai_summaries.jsonl")
    persisted_blob = json.dumps(rows[0])
    assert "sk-ABCDEFGHIJKL1234567890" not in persisted_blob
    assert "api_key=" not in persisted_blob


def test_secret_pattern_in_raw_response_is_redacted(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "AI_SUMMARIES_LOG", tmp_path / "ai_summaries.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    api.add_ai_discussion_summary(
        "FABRIC_QQQ",
        "Clean summary",
        ai_payload={
            "summary": "Clean summary",
            "raw_response": "token=xai-AAAABBBBCCCCDDDDEEEEFFFF",
        },
    )
    rows = _read_jsonl(tmp_path / "ai_summaries.jsonl")
    persisted_blob = json.dumps(rows[0])
    assert "xai-AAAABBBBCCCCDDDDEEEEFFFF" not in persisted_blob


# ---------------------------------------------------------------------------
# No execution permission introduced anywhere in the response graph
# ---------------------------------------------------------------------------


def test_no_execution_permission_in_response_graph(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "AI_SUMMARIES_LOG", tmp_path / "ai_summaries.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    result = api.add_ai_discussion_summary(
        "FABRIC_QQQ",
        "Routine summary",
        ai_payload={"summary": "Routine summary", "confidence_score": 0.5},
    )

    def _walk(obj):
        if isinstance(obj, dict):
            assert obj.get("execution_permission", False) is False
            assert obj.get("can_execute", False) is False
            assert obj.get("broker_api_called", False) is False
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(result)


def test_existing_caller_only_summary_text_still_returns_advisory(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "AI_SUMMARIES_LOG", tmp_path / "ai_summaries.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)

    result = api.add_ai_discussion_summary("FABRIC_QQQ", "Plain text")
    assert result["status"] == "logged"
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["ai_execution_count"] == 0
    assert result["broker_api_called"] is False
    assert result["execution_permission"] is False
    assert result["can_execute"] is False
    assert result["execution_gate"] == "LOCKED"
