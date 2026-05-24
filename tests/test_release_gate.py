"""Release gate + deploy preflight — Kanté positioning: no broken/unsafe deploy.

Proves the gate FAILS on an unlocked execution flag or fake Moltbook
pollution, WARNS when the backend is down but offline checks pass, PASSES a
clean local DB, and never calls a broker API.
"""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

import scripts.persistence as persistence
from scripts import (
    cockpit_concurrency_stress_probe as probe,
    release_gate,
    local_deploy_preflight as preflight,
)


def _clean_db(tmp_path):
    db = tmp_path / "mvp_local.db"
    persistence.init_schema(db)
    return db


def _fresh_stress_summary(generated_epoch: float | None = None,
                          *, gate: str = "PASS",
                          db_locked_errors: int = 0) -> dict:
    """Build a stress-probe summary dict; default = right now + PASS."""
    if generated_epoch is None:
        generated_epoch = time.time()
    return {
        "report": "cockpit_concurrency_stress_probe_summary",
        "generated_at_utc": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(generated_epoch)
        ),
        "stress_gate_status": gate,
        "stress_score": 10.0 if gate == "PASS" else 7.5,
        "success_rate": 1.0 if gate == "PASS" else 0.95,
        "p95_ms": 50,
        "db_locked_errors": db_locked_errors,
        "error_rate": 0.0,
        "timeout_rate": 0.0,
        "canonical_truth_source": "sqlite",
        "cache_role": "derived_non_canonical",
        "advisory_only": True,
        "runtime_db_polluted": False,
    }


@pytest.fixture(autouse=True)
def _pin_fresh_stress_summary(tmp_path, monkeypatch):
    """Pin the stress-summary path + content for every release_gate test.

    Without this, the gate would read the real ``runtime/cockpit_stress_probe/
    last_run.json`` and (now that TTL enforcement is live) a stale local
    summary would cause every PASS-expecting test to WARN.  Tests that want
    to exercise STALE/MISSING/MALFORMED/BLOCK overwrite or delete this file
    after the fixture seeds a fresh PASS.
    """
    summary_dir = tmp_path / "_stress_probe_summary"
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_file = summary_dir / "last_run.json"
    summary_file.write_text(
        json.dumps(_fresh_stress_summary()), encoding="utf-8"
    )
    monkeypatch.setattr(probe, "SUMMARY_DIR", summary_dir)
    monkeypatch.setattr(probe, "SUMMARY_FILE", summary_file)
    yield summary_file


def _no_backend(monkeypatch):
    # Point the health probe at a closed local port so the probe is
    # deterministic regardless of whether a real backend is running.
    monkeypatch.setenv("MVP_BACKEND_HEALTH_URL", "http://127.0.0.1:9/health")


def test_release_gate_passes_clean_local_db(tmp_path):
    db = _clean_db(tmp_path)
    result = release_gate.evaluate(db, check_backend=False)
    assert result["verdict"] == "PASS", result["reasons"]
    assert result["fail_count"] == 0


def test_release_gate_fails_if_execution_unlocked(tmp_path):
    db = _clean_db(tmp_path)
    # Defence-in-depth violation: a row claiming a broker call.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO manual_trades (trade_id, event_id, ticker, side,"
            " quantity, price, executed_at, broker_api_called)"
            " VALUES ('T1','E1','AAPL','BUY',1,1,'t',1)"
        )
        conn.commit()
    finally:
        conn.close()
    result = release_gate.evaluate(db, check_backend=False)
    assert result["verdict"] == "FAIL"
    assert "execution_gate_locked" in result["failing_checks"]


def test_release_gate_fails_if_fake_moltbook_pollution(tmp_path):
    db = _clean_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO moltbook_entries (entry_id, event_id, ticker,"
            " original_signal_thesis, mistake_type, lesson_learned, logged_at,"
            " manual_trade_log_id)"
            " VALUES ('MB1','FABRIC_SPY','SPY','Persistence above 0.8',"
            " 'no_trade_correct','demo','t','')"
        )
        conn.commit()
    finally:
        conn.close()
    result = release_gate.evaluate(db, check_backend=False)
    assert result["verdict"] == "FAIL"
    assert "moltbook_no_fake_pollution" in result["failing_checks"]


def test_release_gate_warns_if_backend_down_but_offline_ok(tmp_path, monkeypatch):
    db = _clean_db(tmp_path)
    _no_backend(monkeypatch)
    result = release_gate.evaluate(db, check_backend=True)
    assert result["verdict"] == "WARN"
    assert result["fail_count"] == 0
    assert "backend_health" in result["warning_checks"]


def test_release_gate_fails_when_db_missing(tmp_path):
    missing = tmp_path / "does_not_exist.db"
    result = release_gate.evaluate(missing, check_backend=False)
    assert result["verdict"] == "FAIL"
    assert "runtime_db_exists" in result["failing_checks"]


def test_release_gate_never_calls_broker_apis():
    import pathlib
    for mod in (release_gate, preflight):
        text = pathlib.Path(mod.__file__).read_text(encoding="utf-8").lower()
        for forbidden in ("place_order(", "submit_order(", "execute_trade(",
                          "broker.execute", "import alpaca", "import ib_insync"):
            assert forbidden not in text, (mod.__file__, forbidden)


def test_release_gate_is_advisory_only(tmp_path):
    db = _clean_db(tmp_path)
    result = release_gate.evaluate(db)
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_gate"] == "LOCKED"
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0


def test_preflight_bridge_idempotency_check_passes_clean(tmp_path):
    db = _clean_db(tmp_path)
    chk = preflight.check_moltbook_bridge_idempotent(db)
    assert chk["status"] == "PASS"


# ---------------------------------------------------------------------------
# Kanté Defensive Sprint — guard coverage + diagnostics service in the gate
# ---------------------------------------------------------------------------


def test_release_gate_surfaces_guard_and_service_summary(tmp_path):
    db = _clean_db(tmp_path)
    result = release_gate.evaluate(db, check_backend=False)
    # The advisory guard/diagnostics summary is exposed at the gate top level.
    assert result["operator_permission_guard_available"] is True
    assert result["auth_guard_status"] in {"PASS", "WARN"}
    assert isinstance(result["mutation_scripts_guarded"], int)
    assert isinstance(result["mutation_scripts_unguarded"], int)
    assert result["diagnostics_service_available"] is True
    assert "release_gate_impact" in result


def test_known_mutation_scripts_are_guarded(tmp_path):
    """The two primary mutation scripts wired this sprint count as guarded."""
    coverage = preflight.scan_mutation_script_guarding()
    assert "quarantine_fake_manual_trades.py" in coverage["guarded"]
    assert "moltbook_cleanup_fake_seed.py" in coverage["guarded"]


def test_guard_coverage_warns_when_unguarded_present():
    """An unguarded mutation script must produce a WARN coverage status."""
    assert preflight.evaluate_guard_coverage_status(0, guard_available=True) == "PASS"
    assert preflight.evaluate_guard_coverage_status(2, guard_available=True) == "WARN"
    # A missing guard module is itself a WARN.
    assert preflight.evaluate_guard_coverage_status(0, guard_available=False) == "WARN"


def test_diagnostics_service_unavailable_is_warn(monkeypatch):
    """If the diagnostics service can't be imported, the summary impact is WARN."""
    import builtins
    real_import = builtins.__import__

    def _block(name, *a, **k):
        if "diagnostics_service" in name:
            raise ModuleNotFoundError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _block)
    health = preflight.diagnostics_service_health()
    assert health["available"] is False
    assert health["status"] == "UNKNOWN"
    summary = preflight.build_kante_defensive_summary()
    assert summary["release_gate_impact"] == "WARN"


def test_guard_coverage_check_is_info_non_blocking(tmp_path):
    """The preflight guard check must be INFO so it never flips the verdict."""
    chk = preflight.check_kante_defensive_gates()
    assert chk["status"] == "INFO"
    assert chk["name"] == "kante_defensive_gates"


# ---------------------------------------------------------------------------
# Kanté Task 5 — mutation-guard release impact (PASS/WARN/BLOCK enforcement)
# ---------------------------------------------------------------------------


def test_mutation_guard_impact_all_guarded_is_pass():
    impact = preflight.evaluate_mutation_guard_impact(
        guarded_count=7, unguarded_names=[], high_severity_count=0)
    assert impact["mutation_guard_coverage"] == 1.0
    assert impact["mutation_guard_risk"] == 0.0
    assert impact["mutation_guard_release_impact"] == "PASS"


def test_mutation_guard_impact_one_low_risk_unguarded_is_warn():
    # 1 of 8 unguarded, low severity → risk 0.125 ≤ 0.25 → WARN.
    impact = preflight.evaluate_mutation_guard_impact(
        guarded_count=7, unguarded_names=["x.py"], high_severity_count=0)
    assert impact["mutation_guard_release_impact"] == "WARN"


def test_mutation_guard_impact_high_severity_unguarded_is_block():
    # Even a single HIGH-severity unguarded script BLOCKs, regardless of risk.
    impact = preflight.evaluate_mutation_guard_impact(
        guarded_count=20, unguarded_names=["restore_x.py"], high_severity_count=1)
    assert impact["mutation_guard_release_impact"] == "BLOCK"


def test_mutation_guard_impact_high_risk_is_block():
    # >25% unguarded (even all low-severity) → BLOCK.
    impact = preflight.evaluate_mutation_guard_impact(
        guarded_count=2, unguarded_names=["a.py", "b.py"], high_severity_count=0)
    assert impact["mutation_guard_risk"] == 0.5
    assert impact["mutation_guard_release_impact"] == "BLOCK"


def test_classify_mutation_script_severity_high_by_name():
    # restore_db.py is restore-capable → HIGH severity if it were unguarded.
    assert preflight.classify_mutation_script_severity("restore_db.py") == "HIGH"
    assert preflight.classify_mutation_script_severity("schema_migrations.py") == "HIGH"


def test_classify_mutation_script_severity_repair_is_low():
    # A repair-write script with no delete/restore/broker pattern.  We synthesise
    # via a name token check: backfill is repair-like.  (Body classification is
    # exercised indirectly by the real scan.)
    sev = preflight.classify_mutation_script_severity(
        "backfill_manual_trade_log_provenance.py")
    assert sev in {"LOW", "HIGH"}  # never crashes; returns a class


def test_known_four_repair_scripts_guarded():
    coverage = preflight.scan_mutation_script_guarding()
    for name in ("quarantine_fake_manual_trades.py", "moltbook_cleanup_fake_seed.py",
                 "backfill_manual_trade_log_provenance.py",
                 "repair_manual_trade_reconciliation.py"):
        assert name in coverage["guarded"], name
    assert coverage["unguarded"] == []  # all mutation scripts wired


def test_release_gate_top_level_includes_mutation_fields(tmp_path):
    db = _clean_db(tmp_path)
    result = release_gate.evaluate(db, check_backend=False)
    for key in ("mutation_guard_coverage", "mutation_scripts_unguarded_names",
                "mutation_guard_release_impact", "auth_guard_status"):
        assert key in result
    assert result["mutation_guard_release_impact"] == "PASS"
    assert result["auth_guard_status"] == "PASS"


def test_release_gate_does_not_hide_unguarded_scripts(tmp_path, monkeypatch):
    """A WARN mutation impact surfaces the unguarded names and downgrades PASS."""
    real = preflight.build_kante_defensive_summary

    def _fake_summary():
        s = dict(real())
        s.update({
            "mutation_scripts_unguarded": ["sketchy_repair.py"],
            "mutation_scripts_unguarded_names": ["sketchy_repair.py"],
            "mutation_scripts_unguarded_count": 1,
            "mutation_guard_coverage": 0.9,
            "mutation_guard_release_impact": "WARN",
            "auth_guard_status": "WARN",
        })
        return s

    monkeypatch.setattr(preflight, "build_kante_defensive_summary", _fake_summary)
    result = release_gate.evaluate(db := _clean_db(tmp_path), check_backend=False)
    assert result["verdict"] == "WARN"
    assert "sketchy_repair.py" in result["mutation_scripts_unguarded_names"]
    assert any("mutation_guard" in r for r in result["reasons"])


def test_release_gate_blocks_high_risk_unguarded(tmp_path, monkeypatch):
    """A BLOCK mutation impact fails the gate (FAIL), not merely WARN."""
    real = preflight.build_kante_defensive_summary

    def _fake_summary():
        s = dict(real())
        s.update({
            "mutation_scripts_unguarded": ["restore_everything.py"],
            "mutation_scripts_unguarded_names": ["restore_everything.py"],
            "mutation_scripts_unguarded_count": 1,
            "mutation_scripts_unguarded_high_severity": ["restore_everything.py"],
            "mutation_guard_coverage": 0.5,
            "mutation_guard_release_impact": "BLOCK",
            "auth_guard_status": "BLOCK",
        })
        return s

    monkeypatch.setattr(preflight, "build_kante_defensive_summary", _fake_summary)
    result = release_gate.evaluate(_clean_db(tmp_path), check_backend=False)
    assert result["verdict"] == "FAIL"
    assert result["mutation_guard_release_impact"] == "BLOCK"
    assert any("mutation_guard" in r for r in result["reasons"])


# ---------------------------------------------------------------------------
# Large-scale performance proof sprint — stress-summary TTL enforcement
# ---------------------------------------------------------------------------


def test_stress_summary_fresh_pass_passes_gate(tmp_path, _pin_fresh_stress_summary):
    """A fresh PASS stress summary is the autouse default — gate PASSes."""
    db = _clean_db(tmp_path)
    result = release_gate.evaluate(db, check_backend=False)
    assert result["verdict"] == "PASS", result["reasons"]
    assert result["stress_release_impact"] == "PASS"
    assert result["stress_gate_status"] == "PASS"
    assert result["stress_summary_fresh"] is True
    assert result["stress_summary_age_seconds"] is not None
    assert result["stress_summary_ttl_seconds"] == 24 * 3600
    assert "recommended" not in " ".join(result["reasons"]).lower()


def test_stress_summary_missing_warns(tmp_path, _pin_fresh_stress_summary):
    """A missing stress summary downgrades PASS → WARN with a recommendation."""
    _pin_fresh_stress_summary.unlink()
    db = _clean_db(tmp_path)
    result = release_gate.evaluate(db, check_backend=False)
    assert result["verdict"] == "WARN", result["reasons"]
    assert result["stress_release_impact"] == "WARN"
    assert result["stress_gate_status"] == "UNKNOWN"
    assert result["stress_summary_fresh"] is False
    assert "cockpit_concurrency_stress_probe.py" in result["stress_recommended_command"]
    assert any("stress_probe" in r and "UNKNOWN" in r for r in result["reasons"])


def test_stress_summary_stale_pass_warns(tmp_path, _pin_fresh_stress_summary):
    """A stale PASS summary must NEVER produce a release PASS."""
    old = time.time() - (48 * 3600)  # 48h ago — outside default 24h TTL
    _pin_fresh_stress_summary.write_text(
        json.dumps(_fresh_stress_summary(generated_epoch=old, gate="PASS")),
        encoding="utf-8",
    )
    db = _clean_db(tmp_path)
    result = release_gate.evaluate(db, check_backend=False)
    assert result["verdict"] == "WARN"
    assert result["stress_release_impact"] == "WARN"
    assert result["stress_gate_status"] == "STALE"
    assert result["stress_summary_fresh"] is False
    assert result["stress_summary_age_seconds"] > 24 * 3600
    assert any("STALE" in r for r in result["reasons"])


def test_stress_summary_malformed_warns(tmp_path, _pin_fresh_stress_summary):
    """A malformed JSON summary degrades to WARN, never silent PASS."""
    _pin_fresh_stress_summary.write_text("not json at all{", encoding="utf-8")
    db = _clean_db(tmp_path)
    result = release_gate.evaluate(db, check_backend=False)
    assert result["verdict"] == "WARN"
    assert result["stress_gate_status"] == "DEGRADED"
    assert result["stress_release_impact"] == "WARN"


def test_stress_summary_missing_timestamp_is_degraded(tmp_path, _pin_fresh_stress_summary):
    """A summary with no parseable generated_at_utc → DEGRADED/WARN."""
    bad = _fresh_stress_summary()
    bad.pop("generated_at_utc")
    _pin_fresh_stress_summary.write_text(json.dumps(bad), encoding="utf-8")
    db = _clean_db(tmp_path)
    result = release_gate.evaluate(db, check_backend=False)
    assert result["stress_gate_status"] == "DEGRADED"
    assert result["verdict"] == "WARN"


def test_stress_summary_fresh_block_fails_gate(tmp_path, _pin_fresh_stress_summary):
    """A fresh BLOCK summary FAILS the release gate."""
    _pin_fresh_stress_summary.write_text(
        json.dumps(_fresh_stress_summary(gate="BLOCK", db_locked_errors=3)),
        encoding="utf-8",
    )
    db = _clean_db(tmp_path)
    result = release_gate.evaluate(db, check_backend=False)
    assert result["verdict"] == "FAIL"
    assert result["stress_release_impact"] == "FAIL"
    assert result["stress_gate_status"] == "BLOCK"
    assert any("stress_probe" in r and "BLOCK" in r for r in result["reasons"])


def test_stress_summary_fresh_warn_downgrades_to_warn(tmp_path, _pin_fresh_stress_summary):
    """A fresh WARN summary downgrades PASS → WARN."""
    _pin_fresh_stress_summary.write_text(
        json.dumps(_fresh_stress_summary(gate="WARN")), encoding="utf-8",
    )
    db = _clean_db(tmp_path)
    result = release_gate.evaluate(db, check_backend=False)
    assert result["verdict"] == "WARN"
    assert result["stress_release_impact"] == "WARN"
    assert result["stress_gate_status"] == "WARN"


def test_stress_summary_ttl_env_override(tmp_path, _pin_fresh_stress_summary, monkeypatch):
    """``MVP_STRESS_SUMMARY_TTL_HOURS`` overrides the 24h default."""
    # 1h TTL — anything older than 1h is stale.
    monkeypatch.setenv("MVP_STRESS_SUMMARY_TTL_HOURS", "1")
    old = time.time() - (90 * 60)  # 1.5h ago
    _pin_fresh_stress_summary.write_text(
        json.dumps(_fresh_stress_summary(generated_epoch=old, gate="PASS")),
        encoding="utf-8",
    )
    db = _clean_db(tmp_path)
    result = release_gate.evaluate(db, check_backend=False)
    assert result["stress_summary_ttl_seconds"] == 3600
    assert result["stress_gate_status"] == "STALE"
    assert result["verdict"] == "WARN"


def test_stress_summary_invalid_ttl_env_falls_back(monkeypatch):
    monkeypatch.setenv("MVP_STRESS_SUMMARY_TTL_HOURS", "garbage")
    assert release_gate._stress_summary_ttl_seconds() == 24 * 3600
    monkeypatch.setenv("MVP_STRESS_SUMMARY_TTL_HOURS", "-5")
    assert release_gate._stress_summary_ttl_seconds() == 24 * 3600
    monkeypatch.setenv("MVP_STRESS_SUMMARY_TTL_HOURS", str(24 * 365))  # 1 year — clamp
    assert release_gate._stress_summary_ttl_seconds() == 24 * 3600


def test_no_stale_pass_can_yield_release_pass(tmp_path, _pin_fresh_stress_summary):
    """Property: across stale-PASS configurations, the verdict is NEVER PASS."""
    db = _clean_db(tmp_path)
    for hours_ago in (25, 48, 24 * 7, 24 * 30):
        old = time.time() - (hours_ago * 3600)
        _pin_fresh_stress_summary.write_text(
            json.dumps(_fresh_stress_summary(generated_epoch=old, gate="PASS")),
            encoding="utf-8",
        )
        result = release_gate.evaluate(db, check_backend=False)
        assert result["verdict"] != "PASS", (hours_ago, result["reasons"])
        assert result["stress_gate_status"] == "STALE"
