"""Tests for ``scripts.error_contracts``.

Pin
---
- Envelope shape matches spec.
- Safety stamps are always present and locked.
- Secret-shaped keys in details are redacted.
- Missing operator_action gets a sensible default.
- Severity is restricted to the valid set.
- ``build_check_result`` coerces invalid statuses to INFO.
- No execution permission anywhere.
"""
from __future__ import annotations

import json

from scripts import error_contracts as ec
from tests.helpers import scanner_probes as probes


def test_error_response_shape():
    r = ec.build_error_response(
        error_id="db_open_failed",
        message="could not open DB",
        operator_action="check file permissions and re-run",
    )
    assert r["ok"] is False
    assert r["envelope"] == "error_response"
    assert r["error_id"] == "db_open_failed"
    assert r["severity"] == "error"
    assert r["message"] == "could not open DB"
    assert r["operator_action"] == "check file permissions and re-run"
    assert "generated_at" in r
    assert "details" in r


def test_error_safety_stamps_locked():
    r = ec.build_error_response(
        error_id="x", message="y", operator_action="z",
    )
    assert r["advisory_status"] == "ADVISORY_ONLY"
    assert r["execution_gate"] == "LOCKED"
    assert r["broker_api_called"] is False
    assert r["ai_execution_count"] == 0
    assert r["execution_permission"] is False
    assert r["can_execute"] is False


def test_warning_response_is_ok_true_with_warning_severity():
    r = ec.build_warning_response(
        warning_id="stale_backup",
        message="newest backup older than 7 days",
        operator_action="run scripts/backup_db.py",
    )
    assert r["ok"] is True
    assert r["envelope"] == "warning_response"
    assert r["severity"] == "warning"
    assert r["warning_id"] == "stale_backup"


def test_secrets_redacted_in_details():
    r = ec.build_error_response(
        error_id="x", message="y", operator_action="z",
        details={
            # Values via sentinels: realistic ones beside credential keys
            # are secret-scanner bait (scripts/secret_fixture_lint.py).
            "MVP_API_TOKEN": "DUMMY_VALUE_FOR_TESTS_ONLY",
            "api_key": "SENTINEL_VALUE_FOR_TESTS_ONLY",
            "passphrase": "do-not-leak",
            "bearer_token": "bearer-abc",
            "free_text": "fine to print",
            "count": 42,
        },
    )
    d = r["details"]
    assert d["MVP_API_TOKEN"] == "<redacted>"
    assert d["api_key"] == "<redacted>"
    assert d["passphrase"] == "<redacted>"
    assert d["bearer_token"] == "<redacted>"
    assert d["free_text"] == "fine to print"
    assert d["count"] == 42
    # The serialized payload must not contain the original secret.
    serialized = json.dumps(r)
    assert "super-secret-token-12345" not in serialized
    assert "another-secret-987" not in serialized


def test_redaction_matches_boundary_terms_only():
    """Keys with secret-shaped substrings at word boundaries are redacted; bare 'description' is not."""
    r = ec.build_error_response(
        error_id="x", message="y", operator_action="z",
        details={
            "description": "ok",          # 'auth' is NOT a substring -> not redacted
            "auth_header": "Bearer ...",  # 'auth' at word boundary -> redacted
            "label": "ok",                # plain -> not redacted
        },
    )
    d = r["details"]
    assert d["description"] == "ok"
    assert d["label"] == "ok"
    assert d["auth_header"] == "<redacted>"


def test_missing_operator_action_gets_default():
    r = ec.build_error_response(
        error_id="x", message="y", operator_action="",
    )
    assert r["operator_action"].strip() != ""


def test_invalid_severity_coerced_to_error():
    r = ec.build_error_response(
        error_id="x", message="y", operator_action="z", severity="catastrophic",
    )
    assert r["severity"] == "error"


def test_valid_severity_preserved():
    for sev in ("error", "warning", "info", "fatal"):
        r = ec.build_error_response(
            error_id="x", message="y", operator_action="z", severity=sev,
        )
        assert r["severity"] == sev


def test_empty_error_id_gets_placeholder():
    r = ec.build_error_response(
        error_id="", message="y", operator_action="z",
    )
    assert r["error_id"] == "unspecified_error"


def test_non_string_message_stringified():
    r = ec.build_error_response(
        error_id="x", message=42, operator_action="z",  # type: ignore[arg-type]
    )
    assert isinstance(r["message"], str)


def test_build_check_result_valid():
    cr = ec.build_check_result(name="db_exists", status="PASS", detail="ok")
    assert cr == {"name": "db_exists", "status": "PASS", "detail": "ok"}


def test_build_check_result_invalid_status_coerced():
    cr = ec.build_check_result(name="x", status="GREAT")
    assert cr["status"] == "INFO"


def test_deterministic_shape_no_extra_fields():
    """Envelope must be small and predictable — no surprise debug fields."""
    r = ec.build_error_response(
        error_id="x", message="y", operator_action="z",
    )
    expected_top_level_keys = {
        "ok", "envelope", "error_id", "message", "operator_action",
        "severity", "details", "generated_at",
        "advisory_status", "execution_gate", "broker_api_called",
        "ai_execution_count", "execution_permission", "can_execute",
    }
    assert set(r.keys()) == expected_top_level_keys


def test_non_dict_details_returns_empty_dict():
    r = ec.build_error_response(
        error_id="x", message="y", operator_action="z",
        details=None,
    )
    assert r["details"] == {}
