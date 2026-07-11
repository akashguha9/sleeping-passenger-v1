"""Defensive-integrity sprint — tests for the system integrity probe.

The probe's contract: READ-ONLY (never creates or writes the DB),
NEVER RAISES (every check is exception-walled into a FAIL result),
DETERMINISTIC (pinned ``now`` + unchanged state → identical payload
modulo latency), and ADVISORY-ONLY (stamped payloads).
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts import system_integrity_probe as probe  # noqa: E402

_NOW = _dt.datetime(2026, 7, 1, 12, 0, 0, tzinfo=_dt.timezone.utc)


def _strip_latency(payload: dict) -> dict:
    out = json.loads(json.dumps(payload, sort_keys=True, default=str))
    out.pop("total_latency_ms", None)
    for c in out.get("checks", []):
        c.pop("latency_ms", None)
    return out


# ---------------------------------------------------------------------------
# Green path on the real repository
# ---------------------------------------------------------------------------


def test_probe_all_checks_pass_on_this_repo():
    result = probe.run_system_integrity_probe(now=_NOW)
    failing = [c for c in result["checks"] if c["status"] == probe.FAIL]
    assert not failing, f"probe FAILs on clean repo: {failing}"
    assert result["overall_status"] in {probe.PASS, "DEGRADED"}
    assert result["counts"]["total"] == len(result["checks"]) == 12


def test_probe_payload_is_advisory_stamped():
    result = probe.run_system_integrity_probe(now=_NOW)
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_gate"] == "LOCKED"
    assert result["human_review_required"] is True
    assert result["ai_execution_count"] == 0
    assert result["broker_api_called"] is False
    assert result["broker_order_id"] == "NONE"
    assert result["non_claims"]


def test_probe_deterministic_given_pinned_now():
    a = probe.run_system_integrity_probe(now=_NOW)
    b = probe.run_system_integrity_probe(now=_NOW)
    assert _strip_latency(a) == _strip_latency(b)


def test_probe_generated_at_uses_injected_clock():
    result = probe.run_system_integrity_probe(now=_NOW)
    assert result["generated_at"] == "2026-07-01T12:00:00Z"


def test_every_check_has_contract_fields():
    result = probe.run_system_integrity_probe(now=_NOW)
    for c in result["checks"]:
        assert c["check_id"]
        assert c["status"] in {probe.PASS, probe.WARN, probe.FAIL}
        assert isinstance(c["reason"], str) and c["reason"]
        assert isinstance(c["detail"], dict)
        assert isinstance(c["latency_ms"], float)


# ---------------------------------------------------------------------------
# Read-only contract — the probe must never create the database
# ---------------------------------------------------------------------------


def test_probe_never_creates_missing_db(tmp_path):
    missing = tmp_path / "does_not_exist.db"
    result = probe.run_system_integrity_probe(now=_NOW, db_path=missing)
    assert not missing.exists(), "probe must NEVER create the database"
    assert result["db_file_present"] is False
    by_id = {c["check_id"]: c for c in result["checks"]}
    assert by_id["schema_tables"]["status"] == probe.WARN
    assert by_id["additive_migrations"]["status"] == probe.WARN
    assert by_id["cascade_honest_degradation"]["status"] == probe.WARN
    # Honest degradation, not failure: WARNs make it DEGRADED, never FAIL.
    assert result["overall_status"] == "DEGRADED"


def test_probe_does_not_modify_existing_db(tmp_path):
    from scripts import persistence
    db = tmp_path / "ro.db"
    persistence.init_schema(db_path=db)
    before = db.read_bytes()
    probe.run_system_integrity_probe(now=_NOW, db_path=db)
    assert db.read_bytes() == before, "probe wrote to the database"


def test_probe_passes_on_freshly_initialized_empty_db(tmp_path):
    from scripts import persistence
    db = tmp_path / "fresh.db"
    persistence.init_schema(db_path=db)
    result = probe.run_system_integrity_probe(now=_NOW, db_path=db)
    by_id = {c["check_id"]: c for c in result["checks"]}
    assert by_id["schema_tables"]["status"] == probe.PASS
    assert by_id["additive_migrations"]["status"] == probe.PASS
    assert by_id["cascade_honest_degradation"]["status"] == probe.PASS


# ---------------------------------------------------------------------------
# Exception wall — a broken subsystem becomes a FAIL result, never a raise
# ---------------------------------------------------------------------------


def test_broken_config_becomes_fail_not_raise(monkeypatch):
    import scripts.causal_event_graph as ceg

    def _boom(path=None):
        raise ValueError("corrupt causal graph on disk")

    monkeypatch.setattr(ceg, "load_causal_graph", _boom)
    result = probe.run_system_integrity_probe(now=_NOW)
    by_id = {c["check_id"]: c for c in result["checks"]}
    assert by_id["config_causal_graph"]["status"] == probe.FAIL
    assert "ValueError" in by_id["config_causal_graph"]["reason"]
    assert result["overall_status"] == probe.FAIL


def test_clock_discipline_detects_wallclock_leak(monkeypatch):
    # Simulate a new evaluator that forgot the injectable clock.
    bad_registry = probe.CLOCK_INJECTED_EVALUATORS + (
        ("scripts.market_titration_engine", "compact_titration_fields", "now"),
    )
    monkeypatch.setattr(probe, "CLOCK_INJECTED_EVALUATORS", bad_registry)
    result = probe.run_system_integrity_probe(now=_NOW)
    by_id = {c["check_id"]: c for c in result["checks"]}
    assert by_id["clock_injection_discipline"]["status"] == probe.FAIL
    assert "compact_titration_fields" in str(
        by_id["clock_injection_discipline"]["detail"]["violations"]
    )


def test_db_path_ratchet_detects_new_violation(tmp_path, monkeypatch):
    planted = tmp_path / "scripts"
    planted.mkdir()
    (planted / "new_module.py").write_text(
        "from pathlib import Path\nDB_PATH = Path('x')\n"
        "def f(db_path: Path = DB_PATH):\n    return db_path\n",
        encoding="utf-8",
    )
    counts = probe.scan_eager_db_path_defaults(planted)
    assert counts == {"new_module.py": 1}


def test_db_path_scan_ignores_comment_lines(tmp_path):
    planted = tmp_path / "scripts"
    planted.mkdir()
    (planted / "documented.py").write_text(
        "# never write db_path: Path = DB_PATH in new code\nX = 1\n",
        encoding="utf-8",
    )
    assert probe.scan_eager_db_path_defaults(planted) == {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_exit_zero_and_json(capsys):
    rc = probe.main(["--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["probe_version"] == probe.PROBE_VERSION
    assert payload["overall_status"] in {probe.PASS, "DEGRADED"}


def test_cli_human_output(capsys):
    rc = probe.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "System Integrity Probe" in out
    assert "overall:" in out


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover
        pytest.skip("fastapi test client unavailable")
    import scripts.api_server as srv
    return TestClient(srv.app)


def test_api_system_integrity_contract(client):
    resp = client.get("/api/system/integrity")
    assert resp.status_code == 200
    body = resp.json()
    assert body["probe_version"] == probe.PROBE_VERSION
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False
    assert body["overall_status"] in {"PASS", "DEGRADED", "FAIL"}
    assert len(body["checks"]) == 12
    ids = {c["check_id"] for c in body["checks"]}
    assert {"schema_tables", "engine_titration_determinism",
            "clock_injection_discipline", "db_path_discipline",
            "scope_guards"} <= ids
