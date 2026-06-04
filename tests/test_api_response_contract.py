"""Golden tests for the extracted advisory response-contract seam.

Pins the advisory constants + sanitizer and asserts api_server re-exports the
SAME objects (byte-identical behaviour after the god-module extraction).
"""

from scripts import api_response_contract as arc


def test_advisory_constants_are_pinned() -> None:
    assert arc.ADVISORY_STATUS == "ADVISORY_ONLY"
    assert arc.EXECUTION_MODE == "HUMAN_ONLY"
    assert arc.AI_EXECUTION_COUNT == 0
    assert arc.CSV_MEDIA_TYPE == "text/csv; charset=utf-8"
    assert arc.API_VERSION == "1.0.0"


def test_safe_exc_summary_returns_type_name_only() -> None:
    assert arc.safe_exc_summary(ValueError("/secret/path/db.sqlite")) == "ValueError"
    assert arc.safe_exc_summary(KeyError("internal")) == "KeyError"


def test_api_server_reexports_same_objects() -> None:
    # api_server imports fastapi; skip cleanly if unavailable (mirrors suite).
    import importlib

    try:
        api_server = importlib.import_module("scripts.api_server")
    except ModuleNotFoundError:
        import pytest

        pytest.skip("fastapi not installed")
    assert api_server._ADVISORY_STATUS == arc.ADVISORY_STATUS
    assert api_server._EXECUTION_MODE == arc.EXECUTION_MODE
    assert api_server._AI_EXECUTION_COUNT == arc.AI_EXECUTION_COUNT
    assert api_server._VERSION == arc.API_VERSION
    assert api_server._safe_exc_summary is arc.safe_exc_summary
