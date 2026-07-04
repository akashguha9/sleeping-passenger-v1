"""End-to-end cockpit truth smoke via the REAL FastAPI app (Item 5).

Runs the same checks as scripts/smoke_cockpit_truth.py inside the suite:
the real app serves /truth-surface with every field the cockpit needs, and
the honesty rules hold under the hermetic env (holdings absent -> BROKEN/
BLOCKED family, never HEALTHY; no CALIBRATED claim below the gate).
"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from scripts.api_server import app  # noqa: E402
from scripts.smoke_cockpit_truth import REQUIRED_FIELDS, run_smoke  # noqa: E402


def test_truth_surface_serves_all_cockpit_fields() -> None:
    client = TestClient(app)  # no startup hooks: repo test convention
    surface = client.get("/truth-surface").json()
    for field in REQUIRED_FIELDS:
        assert field in surface, f"cockpit field missing: {field}"
    assert surface["advisory_status"] == "ADVISORY_ONLY"
    assert surface["execution_gate"] == "LOCKED"


def test_hermetic_state_is_never_healthy() -> None:
    """Under test isolation the holdings truth is absent — the app must say
    BROKEN/BLOCKED/DEGRADED, never HEALTHY."""
    client = TestClient(app)
    surface = client.get("/truth-surface").json()
    assert surface["overall_operational_state"] != "HEALTHY"
    assert surface["holdings_truth_status"] == "HOLDINGS_TRUTH_MISSING"


def test_no_calibrated_claim_below_gate() -> None:
    client = TestClient(app)
    surface = client.get("/truth-surface").json()
    n = int(surface.get("matured_real_outcome_count") or 0)
    if n < 200:
        assert surface["calibration_status"] != "CALIBRATED"
        assert "uncalibrated" in surface["calibration_display_note"].lower()


def test_smoke_runner_passes_end_to_end() -> None:
    result = run_smoke()
    assert result["passed"] is True, result["failures"]


def test_nbi_cockpit_exposes_artifact_age() -> None:
    client = TestClient(app)
    payload = client.get("/nbi/cockpit").json()
    assert "artifact_age_minutes" in payload or (
        payload.get("artifact_present") is False
    )
