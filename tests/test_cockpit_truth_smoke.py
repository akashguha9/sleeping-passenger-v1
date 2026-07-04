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


def test_nbi_cockpit_exposes_artifact_age_even_when_missing() -> None:
    """CI regression (2026-07-04): the fail-closed envelope omitted the key,
    so fresh checkouts (CI) failed the smoke while machines with a live
    artifact passed.  The truth key must exist on EVERY branch."""
    client = TestClient(app)
    payload = client.get("/nbi/cockpit").json()
    # hermetic env: NBI_ARTIFACT_DIR is a tmp dir with no artifact
    assert payload["artifact_present"] is False
    assert "artifact_age_minutes" in payload, (
        "missing artifact must not remove the truth key"
    )
    assert payload["artifact_age_minutes"] is None
    assert payload["artifact_age_status"] == "MISSING"
    assert payload["artifact_stale"] is True
    assert payload.get("status") != "HEALTHY"


def _write_cockpit_artifact(generated_at: str) -> None:
    import json as _json
    import os
    from pathlib import Path

    d = Path(os.environ["NBI_ARTIFACT_DIR"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "nbi_live_ops_cockpit.json").write_text(
        _json.dumps({
            "generated_at": generated_at,
            "health": {"status": "HEALTHY", "LiveOpsHealth10": 10},
        }),
        encoding="utf-8",
    )


def test_nbi_cockpit_fresh_artifact_reports_fresh() -> None:
    from datetime import datetime, timedelta, timezone

    recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    _write_cockpit_artifact(recent)
    client = TestClient(app)
    payload = client.get("/nbi/cockpit").json()
    assert payload["artifact_present"] is True
    assert payload["artifact_age_minutes"] == pytest.approx(30, abs=5)
    assert payload["artifact_age_status"] == "FRESH"
    assert payload["artifact_stale"] is False


def test_nbi_cockpit_stale_artifact_keeps_key_and_says_stale() -> None:
    """A dead scheduler's old HEALTHY artifact must read as STALE, with the
    age key present — never an ageless green."""
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(hours=50)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    _write_cockpit_artifact(old)
    client = TestClient(app)
    payload = client.get("/nbi/cockpit").json()
    assert payload["artifact_present"] is True
    assert "artifact_age_minutes" in payload
    assert payload["artifact_age_minutes"] > 26 * 60
    assert payload["artifact_age_status"] == "STALE"
    assert payload["artifact_stale"] is True
