"""Tests — external-evidence reliability API route (read-only, advisory-only).

Kanté Continuation sprint, Workstream B.  Proves the route:
  * returns an honest DISABLED state when adapters are off (the default),
  * always carries the advisory-only safety stamps,
  * never leaks a secret-looking key,
  * never mutates the filesystem,
  * degrades to NO_PAYLOAD / ERROR_SAFE safely,
  * is registered on the FastAPI app.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.api.routers.external_evidence_router import (
    STATUS_DISABLED,
    STATUS_NO_PAYLOAD,
    STATUS_OK,
    build_external_evidence_reliability_payload,
    build_router,
)


def test_external_evidence_reliability_api_disabled_state():
    # No artifact + real on-demand build (adapters disabled by default).
    payload = build_external_evidence_reliability_payload(
        artifact_path=Path("/nonexistent/__no_artifact__.json")
    )
    assert payload["status"] == STATUS_DISABLED
    assert payload["external_evidence_status"] == "DISABLED"
    assert payload["external_evidence_enabled"] is False
    assert payload["decision_impact"] == "NONE"
    assert payload["mode"] == "PAPER_ONLY"
    assert payload["items"] == []


def test_external_evidence_reliability_api_safety_stamps():
    payload = build_external_evidence_reliability_payload(
        artifact_path=Path("/nonexistent/__no_artifact__.json")
    )
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["human_execution_required"] is True
    assert payload["real_money_sizing_impact"] == "PROHIBITED"
    assert payload["real_money_weight_allowed"] is False
    assert payload["external_adapter_decision_power"] == "EVIDENCE_ONLY"
    assert payload["external_adapter_execution_permission"] == "WATCH_ONLY"


def test_external_evidence_reliability_api_no_secret_leakage(tmp_path):
    # An artifact contaminated with secret-looking keys must be scrubbed.
    artifact = {
        "external_evidence": {
            "external_evidence_status": "ACCEPTED_EVIDENCE_ONLY",
            "external_evidence_enabled": True,
            "external_evidence_accepted_count": 2,
            "external_evidence_decision_impact": "ADVISORY_CONTEXT_ONLY",
            "TWELVE_DATA_API_KEY": "SECRET_abc123",
            "authorization": "Bearer SECRET_TOKEN_xyz",
            "external_evidence_items": [
                {"source_name": "kronos", "api_key": "SECRET_inner_999"},
            ],
        },
        "external_evidence_operator_readiness": {
            "mode": "PAPER_ONLY",
            "polygon_secret": "SECRET_poly",
        },
    }
    path = tmp_path / "external_evidence_reliability.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")

    payload = build_external_evidence_reliability_payload(artifact_path=path)
    blob = json.dumps(payload)
    for secret in ("SECRET_abc123", "SECRET_TOKEN_xyz", "SECRET_inner_999", "SECRET_poly"):
        assert secret not in blob, f"secret leaked: {secret}"
    # Non-secret evidence still surfaced.
    assert payload["status"] == STATUS_OK
    assert payload["external_evidence_accepted_count"] == 2


def test_external_evidence_reliability_api_does_not_mutate(tmp_path):
    # An existing artifact is read, never rewritten.
    path = tmp_path / "external_evidence_reliability.json"
    artifact = {"external_evidence": {"external_evidence_status": "DISABLED"}}
    path.write_text(json.dumps(artifact), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    mtime_before = path.stat().st_mtime_ns

    build_external_evidence_reliability_payload(artifact_path=path)
    build_external_evidence_reliability_payload(artifact_path=path)

    assert path.read_text(encoding="utf-8") == before
    assert path.stat().st_mtime_ns == mtime_before


def test_external_evidence_reliability_api_no_payload_when_build_fails():
    payload = build_external_evidence_reliability_payload(
        artifact_path=Path("/nonexistent/__none__.json"),
        on_demand=lambda: None,
    )
    assert payload["status"] == STATUS_NO_PAYLOAD
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["items"] == []


def test_external_evidence_reliability_route_registered():
    router = build_router()
    paths = {getattr(r, "path", None) for r in getattr(router, "routes", [])}
    assert "/external-evidence/reliability" in paths


def test_external_evidence_reliability_route_on_app():
    import scripts.api_server as srv

    assert hasattr(srv, "_build_external_evidence_reliability_payload")
    app = getattr(srv, "app", None)
    if app is None:  # pragma: no cover - fastapi optional
        return
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/external-evidence/reliability" in paths
