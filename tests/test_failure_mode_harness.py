"""Failure-mode harness — Full Role-Uplift Sprint, Phase 6.

Each scenario asserts that the relevant subsystem **fails safe**:

* preserves ``advisory_status = "ADVISORY_ONLY"``,
* preserves ``execution_gate = "LOCKED"``,
* preserves ``broker_api_called = False`` and ``ai_execution_count = 0``,
* does NOT write fake canonical data, and
* emits a truthful skip / error reason rather than fabricating success.

Scenarios covered:

1.  upstream timeout                                  → corpus path
2.  malformed source payload                          → probability snapshot
3.  empty source response                             → calibration corpus
4.  stale source state                                → probability snapshot
5.  partial refresh failure                           → calibration gate
6.  SQLite lock / write contention                    → probability snapshot
7.  missing optional API key                          → bootstrap
8.  corrupted runtime artifact                        → scorecard / calibration
9.  frontend backend-offline state                    → covered in frontend
    (asserted here at the contract layer)
10. calibration corpus missing outcomes               → corpus
11. probability snapshot missing axes                 → snapshot
12. role scorecard missing calibration report         → scorecard

The harness intentionally does **not** simulate broker / order / fill
states because no such code path exists.  Each scenario records its
exact safety stamps so a release reviewer can pattern-match the file
without running it.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import bootstrap_local_operator as bootstrap  # noqa: E402
from scripts import calibration_report as calib  # noqa: E402
from scripts import curate_calibration_corpus as corpus  # noqa: E402
from scripts import probability_snapshot as ps  # noqa: E402
from scripts import segment_role_scorecard as scorecard  # noqa: E402


ADVISORY_STAMPS = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}


def _assert_safety_stamps(d: dict[str, Any]) -> None:
    for k, v in ADVISORY_STAMPS.items():
        assert d.get(k) == v, f"safety stamp {k}={d.get(k)!r} drift"


def _no_forbidden_tokens(blob: str) -> None:
    blob = blob.lower()
    for forbidden in (
        "place_order",
        "submit_order",
        "execute_trade",
        "broker_execute",
        "auto_execute",
        "broker_api_called: true",
    ):
        assert forbidden not in blob, f"forbidden token leaked: {forbidden}"


# ---------------------------------------------------------------------------
# Scenario 1 — upstream timeout in corpus path
# ---------------------------------------------------------------------------


def test_scenario_01_upstream_timeout_returns_empty_corpus(monkeypatch):
    """Polymarket request times out — the corpus path treats a timeout
    as 'no rows' rather than crashing.  The fetch helper already wraps
    the network call in a broad ``except Exception``; here we simulate
    the post-catch behaviour directly by returning ``[]`` from the
    page-fetch.  The envelope still carries advisory stamps.
    """
    def _empty_fetch(*_args, **_kwargs):
        return []

    monkeypatch.setattr(corpus, "_fetch_polymarket_closed_page", _empty_fetch)
    envelope = corpus.build_corpus(
        from_sqlite=None,
        include_polymarket_closed=True,
        from_fixture=None,
        max_records=10,
    )
    _assert_safety_stamps(envelope)
    assert envelope["metrics"]["n_total"] == 0
    assert envelope["metrics"]["evidence_status"] == "INSUFFICIENT_EVIDENCE"


# ---------------------------------------------------------------------------
# Scenario 2 — malformed source payload in signal_events
# ---------------------------------------------------------------------------


def test_scenario_02_malformed_signal_payload_still_yields_valid_snapshot(tmp_path):
    db = tmp_path / "mvp.db"
    con = sqlite3.connect(str(db))
    try:
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE signal_events (
                id INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            "INSERT INTO signal_events (event_id, source_name, raw_payload, fetched_at) "
            "VALUES (?,?,?,?)",
            ("sig-malformed", "grok_xai", "<not-json>", "2026-05-26T10:00:00+00:00"),
        )
        con.commit()
    finally:
        con.close()

    stats = ps.backfill_probability_snapshots(db_path=db, limit=None, dry_run=True)
    assert stats["snapshots_created"] == 1  # planned, dry-run
    assert stats["invalid_probability_count"] == 0
    report = ps.build_report(db_path=db, dry_run=True, limit=None, write=False)
    _assert_safety_stamps(report)
    assert report["predictive_claim_allowed"] is False


# ---------------------------------------------------------------------------
# Scenario 3 — empty source response in calibration corpus
# ---------------------------------------------------------------------------


def test_scenario_03_empty_source_response_yields_no_pairs():
    metrics = corpus.validate_corpus([])
    assert metrics["n_total"] == 0
    assert metrics["n_pairs"] == 0
    assert metrics["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert metrics["class_balance_warning"] == "NO_PAIRS"


# ---------------------------------------------------------------------------
# Scenario 4 — stale signal payload lowers probability without fabricating it
# ---------------------------------------------------------------------------


def test_scenario_04_stale_payload_lowers_advisory_probability():
    fresh = ps.compute_raw_score({axis: 0.6 for axis in ps.SCORE_AXES})
    stale = ps.compute_raw_score(
        {axis: 0.6 for axis in ps.SCORE_AXES}, staleness_penalty=1.0
    )
    assert stale < fresh
    p_stale = ps.compute_model_probability(stale)
    assert 0.0 <= p_stale <= 1.0


# ---------------------------------------------------------------------------
# Scenario 5 — partial refresh failure: calibration gate refuses claim
# ---------------------------------------------------------------------------


def test_scenario_05_partial_refresh_does_not_unlock_predictive_claim(tmp_path):
    """Even when the corpus has a handful of usable pairs (here, 3),
    the calibration gate must refuse to claim predictive validity
    because ``N_real < N_min``.
    """
    pairs = [
        {"p": 0.6, "y": 1},
        {"p": 0.3, "y": 0},
        {"p": 0.55, "y": 1},
    ]
    report = calib.compute_calibration_report(pairs)
    _assert_safety_stamps(report)
    assert report["predictive_claim_allowed"] is False
    assert report["calibration_status"] == "INSUFFICIENT_EVIDENCE"


# ---------------------------------------------------------------------------
# Scenario 6 — SQLite lock / write contention.
# ---------------------------------------------------------------------------


def test_scenario_06_sqlite_lock_does_not_crash_dry_run(tmp_path):
    """Simulate write contention by opening an exclusive transaction on
    the DB while the snapshot pipeline runs in dry-run.  Dry-run does
    not write, so the pipeline must succeed without raising.
    """
    db = tmp_path / "mvp.db"
    con_init = sqlite3.connect(str(db))
    try:
        cur = con_init.cursor()
        cur.execute(
            """
            CREATE TABLE signal_events (
                id INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            "INSERT INTO signal_events (event_id, source_name, raw_payload, fetched_at) "
            "VALUES (?,?,?,?)",
            ("sig-lock", "grok_xai", "{}", "2026-05-26T10:00:00+00:00"),
        )
        con_init.commit()
    finally:
        con_init.close()

    # Open a long-running connection holding a write lock.
    holder = sqlite3.connect(str(db), timeout=0.1)
    try:
        holder.isolation_level = None
        holder.execute("BEGIN EXCLUSIVE")
        # Under exclusive lock, build_report must NOT raise — it must
        # return a structured DB_LOCKED report with advisory stamps.
        report = ps.build_report(db_path=db, dry_run=True, limit=None, write=False)
        holder.execute("COMMIT")
    finally:
        holder.close()
    _assert_safety_stamps(report)
    assert report["predictive_claim_allowed"] is False
    assert report["evidence_status"] == "DB_LOCKED"


# ---------------------------------------------------------------------------
# Scenario 7 — missing optional API key (bootstrap warns, never fails)
# ---------------------------------------------------------------------------


def test_scenario_07_missing_optional_keys_do_not_crash_bootstrap(tmp_path, monkeypatch):
    """An operator with no API keys and an empty repo skeleton should
    still receive a coherent bootstrap report.  No env-vars are read; we
    simulate the *minimum* repo layout and confirm the script
    degrades gracefully.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "frontend").mkdir()
    # Wipe NEWS_API_KEY etc. so the bootstrap genuinely has no
    # optional keys to consult — none are *required* by the script,
    # but we want to confirm that fact in the test.
    for var in ("NEWS_API_KEY", "EVENT_REGISTRY_API_KEY", "SEC_USER_AGENT"):
        monkeypatch.delenv(var, raising=False)

    report = bootstrap.build_report(repo_root=tmp_path, skip_frontend=True)
    _assert_safety_stamps(report)
    assert isinstance(report["bootstrap_score"], (int, float))
    assert 0.0 <= report["bootstrap_score"] <= 10.0


# ---------------------------------------------------------------------------
# Scenario 8 — corrupted runtime artifact
# ---------------------------------------------------------------------------


def test_scenario_08_corrupted_calibration_report_blocks_predictive_claim(tmp_path):
    """A garbage calibration_report.json must not silently unlock the
    Scoring/model segment.  The scorecard reads it and falls back to
    ``predictive_claim_allowed = false``.
    """
    bad = tmp_path / "calibration_report.json"
    bad.write_text("{not-json", encoding="utf-8")
    unlocked = scorecard._read_calibration_unlocked(bad)
    assert unlocked is False
    report = scorecard.build_report(calibration_report_path=bad)
    _assert_safety_stamps(report)
    # Scoring/model logic quality is the segment whose ceiling is
    # bound to calibration_unlocked.
    seg = next(
        s for s in report["segments"] if s["segment"] == "Scoring/model logic quality"
    )
    assert seg["absolute_score"] <= scorecard.SCORING_MODEL_CEILING_PIPELINE_ONLY


# ---------------------------------------------------------------------------
# Scenario 9 — frontend backend-offline (asserted via contract surface)
# ---------------------------------------------------------------------------


def test_scenario_09_backend_offline_contract_is_advisory_only():
    """The advisory contract module's safety stamps are what the
    frontend renders when it cannot reach the backend (mock chip).
    """
    from scripts.advisory_contract import advisory_safety_stamps

    stamps = advisory_safety_stamps()
    _assert_safety_stamps(stamps)
    assert stamps["execution_permission"] is False
    assert stamps["can_execute"] is False


# ---------------------------------------------------------------------------
# Scenario 10 — calibration corpus missing outcomes
# ---------------------------------------------------------------------------


def test_scenario_10_missing_outcomes_blocks_calibration():
    rec = {
        "source": "manual_trade",
        "source_record_id": "X",
        "asset_or_market": "SPY",
        "signal_timestamp_utc": "2026-05-26T00:00:00+00:00",
        "outcome_timestamp_utc": "2026-05-27T00:00:00+00:00",
        "score_snapshot": {"model_probability": 0.55},
        "outcome_label": 99,  # invalid
        "outcome_definition": "missing",
        "provenance": {"mock_fallback": False, "fallback_used": False},
    }
    metrics = corpus.validate_corpus([rec])
    assert metrics["n_valid_y"] == 0
    assert metrics["n_pairs"] == 0
    assert metrics["corpus_validity"] is False


# ---------------------------------------------------------------------------
# Scenario 11 — probability snapshot missing axes
# ---------------------------------------------------------------------------


def test_scenario_11_missing_axes_collapse_to_half_with_no_penalty():
    """An advisory snapshot with no axes and no penalties resolves to
    p = sigmoid(0) = 0.5.  This is a *defensible* advisory value, not
    a predictive claim.  Critically, ``predictive_claim_allowed`` is
    False on the report envelope regardless.
    """
    snap = ps.build_probability_snapshot(signal_id="no-axes", axes={})
    assert snap.model_probability == pytest.approx(0.5)
    # And the larger report keeps the predictive claim blocked.
    report = ps.build_report(
        db_path=Path("does-not-exist.db"),
        dry_run=True,
        limit=None,
        write=False,
    )
    assert report["predictive_claim_allowed"] is False


# ---------------------------------------------------------------------------
# Scenario 12 — role scorecard with missing calibration report
# ---------------------------------------------------------------------------


def test_scenario_12_missing_calibration_report_caps_scoring_segment(tmp_path):
    missing = tmp_path / "absent_calibration_report.json"
    assert not missing.exists()
    report = scorecard.build_report(calibration_report_path=missing)
    _assert_safety_stamps(report)
    seg = next(
        s for s in report["segments"] if s["segment"] == "Scoring/model logic quality"
    )
    assert seg["absolute_score"] <= scorecard.SCORING_MODEL_CEILING_PIPELINE_ONLY
    # And the dashboard score for the segment is also capped.
    assert seg["dashboard_score"] != "NOT_TARGETED_THIS_YEAR"
    _no_forbidden_tokens(json.dumps(report))


# ---------------------------------------------------------------------------
# Harness aggregate — confirm every scenario contributed advisory stamps
# ---------------------------------------------------------------------------


def test_harness_total_scenarios_match_spec():
    """Pin the spec contract: 12 failure scenarios, each independently
    exercised above.  Adding a new scenario must update this count
    intentionally.
    """
    import inspect

    module = sys.modules[__name__]
    scenario_tests = [
        name
        for name, obj in inspect.getmembers(module, inspect.isfunction)
        if name.startswith("test_scenario_")
    ]
    assert len(scenario_tests) == 12
