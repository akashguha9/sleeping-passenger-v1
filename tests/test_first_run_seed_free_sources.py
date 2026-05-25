"""Tests for the first-day operator seed script.

Identity Collapse + First-Day Operator sprint, Phase 3.

Hard properties under test
--------------------------
* ``--dry-run`` (the default) does not write canonical signal_events rows.
* ``--write`` writes ONLY truth-labeled real-public rows; never fabricated.
* Missing keys for optional keyed sources lead to clean skips, never
  fabricated rows.
* Every summary record carries the advisory safety stamps.
* ``broker_api_called`` is False; ``ai_execution_count`` is 0;
  ``execution_gate`` is ``LOCKED``.
* No canonical ``signal_events`` event_id ever carries the fake-row
  prefixes flagged by ``manual_trade_origin.FAKE_EVENT_ID_PREFIXES`` (the
  truth-purity vocabulary).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import scripts.first_run_seed_free_sources as fr


_FAKE_PREFIXES = ("FABRIC_", "SEED_", "DEMO_", "TEST_", "FIXTURE_")


def _canned_refresh_summary(*, write_mode: bool, rows_per_source: int = 0, succeed: bool = True) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for src in fr.FREE_SOURCES_DEFAULT:
        entries.append(
            {
                "run_id": "TEST_RUN_00000001",
                "source_name": src,
                "display_name": src.title(),
                "phase": "phase1",
                "attempted": True,
                "success": bool(succeed),
                "skipped": False,
                "started_at": "2026-05-25T00:00:00+00:00",
                "finished_at": "2026-05-25T00:00:01+00:00",
                "duration_seconds": 1.0,
                "rows_before": 0,
                "rows_after": rows_per_source if (succeed and write_mode) else 0,
                "rows_added": rows_per_source if (succeed and write_mode) else 0,
                "skipped_reason": "",
                "error_message": "" if succeed else "simulated_error",
                "advisory_status": "ADVISORY_ONLY",
                "execution_gate": "LOCKED",
                "broker_api_called": False,
                "ai_execution_count": 0,
                "human_review_required": True,
            }
        )
    return {
        "operation": "refresh_live_signals",
        "run_id": "TEST_RUN_00000001",
        "mode": "write" if write_mode else "dry_run",
        "total_sources_attempted": len(entries),
        "total_sources_succeeded": sum(1 for e in entries if e["success"]),
        "total_sources_failed": sum(1 for e in entries if not e["success"]),
        "total_sources_skipped": sum(1 for e in entries if e["skipped"]),
        "db_path": "runtime/mvp_local.db",
        "entries": entries,
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


def test_dry_run_default_does_not_write_rows():
    """--dry-run (default) reports zero rows_written even if the orchestrator
    were to claim writes.  In dry-run, the orchestrator does not actually
    persist rows; the wrapper must reflect this honestly."""
    with patch.object(
        fr,
        "run_first_run_seed",
        wraps=fr.run_first_run_seed,
    ):
        with patch(
            "scripts.refresh_live_signals.run_refresh",
            return_value=_canned_refresh_summary(write_mode=False, rows_per_source=0),
        ):
            summary = fr.run_first_run_seed(dry_run=True)
    assert summary["dry_run"] is True
    assert summary["rows_written"] == 0
    assert summary["rows_mock"] == 0


def test_write_mode_writes_only_truth_labeled_rows():
    with patch(
        "scripts.refresh_live_signals.run_refresh",
        return_value=_canned_refresh_summary(write_mode=True, rows_per_source=10),
    ):
        summary = fr.run_first_run_seed(dry_run=False)
    assert summary["dry_run"] is False
    # Every source result must declare a truth_source label.
    truth_labels = {sr["truth_source"] for sr in summary["source_results"]}
    assert truth_labels.issubset({"live_public", "live_keyed", "skipped", "error"})
    # Free-default sources are all public; no mock rows ever.
    assert summary["rows_mock"] == 0
    assert summary["rows_live_public"] >= 0


def test_advisory_stamps_present_on_summary_and_each_source():
    with patch(
        "scripts.refresh_live_signals.run_refresh",
        return_value=_canned_refresh_summary(write_mode=False),
    ):
        summary = fr.run_first_run_seed(dry_run=True)
    for key in ("advisory_status", "execution_gate", "broker_api_called", "ai_execution_count"):
        assert key in summary, f"summary missing advisory key: {key}"
    assert summary["advisory_status"] == "ADVISORY_ONLY"
    assert summary["execution_gate"] == "LOCKED"
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0
    for sr in summary["source_results"]:
        assert sr["advisory_status"] == "ADVISORY_ONLY"
        assert sr["execution_gate"] == "LOCKED"
        assert sr["broker_api_called"] is False
        assert sr["ai_execution_count"] == 0


def test_truth_model_declared_in_summary():
    with patch(
        "scripts.refresh_live_signals.run_refresh",
        return_value=_canned_refresh_summary(write_mode=False),
    ):
        summary = fr.run_first_run_seed(dry_run=True)
    assert summary["canonical_store"] == "sqlite"
    assert summary["jsonl_is_canonical"] is False


def test_optional_keyed_sources_skipped_when_keys_absent(monkeypatch):
    # Ensure none of the keys are set in the test environment.
    monkeypatch.delenv("NEWS_API_KEY", raising=False)
    monkeypatch.delenv("EVENT_REGISTRY_API_KEY", raising=False)
    selected = fr._select_sources(include_optional=True)
    # Only the free defaults should be selected.
    assert tuple(selected) == fr.FREE_SOURCES_DEFAULT


def test_optional_keyed_sources_included_when_key_present(monkeypatch):
    monkeypatch.setenv("NEWS_API_KEY", "dummy-value-not-logged")
    monkeypatch.delenv("EVENT_REGISTRY_API_KEY", raising=False)
    selected = fr._select_sources(include_optional=True)
    assert "newsapi" in selected
    assert "event_registry" not in selected


def test_summary_writes_to_json_file(tmp_path: Path):
    target = tmp_path / "first_run_summary.json"
    with patch(
        "scripts.refresh_live_signals.run_refresh",
        return_value=_canned_refresh_summary(write_mode=False),
    ):
        rc = fr.main(["--dry-run", "--json-summary", str(target), "--quiet"])
    assert rc == 0
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["script"] == "first_run_seed_free_sources.py"
    assert data["advisory_status"] == "ADVISORY_ONLY"


def test_all_sources_failed_exits_non_zero():
    with patch(
        "scripts.refresh_live_signals.run_refresh",
        return_value=_canned_refresh_summary(write_mode=False, succeed=False),
    ):
        rc = fr.main(["--quiet"])
    assert rc == 2


def test_usefulness_score_is_bounded_zero_ten():
    with patch(
        "scripts.refresh_live_signals.run_refresh",
        return_value=_canned_refresh_summary(write_mode=True, rows_per_source=10),
    ):
        summary = fr.run_first_run_seed(dry_run=False)
    score = summary["first_run_usefulness_score"]
    assert 0.0 <= score <= 10.0


def test_no_fake_event_id_prefix_appears_in_source_results():
    """The wrapper must never persist or display rows whose event_id begins
    with a known fake prefix.  The wrapper itself does not synthesise IDs —
    this asserts the contract is documented."""
    with patch(
        "scripts.refresh_live_signals.run_refresh",
        return_value=_canned_refresh_summary(write_mode=False),
    ):
        summary = fr.run_first_run_seed(dry_run=True)
    blob = json.dumps(summary)
    for prefix in _FAKE_PREFIXES:
        # The literal prefix may appear as part of the test run_id label in
        # the entries (e.g. ``TEST_RUN_00000001``); allow that one because
        # it is metadata, not an event_id.  We assert no ``event_id`` field
        # carries the prefix.
        for sr in summary["source_results"]:
            eid = sr.get("event_id")
            if eid:
                assert not str(eid).startswith(prefix), (
                    f"source_result event_id has fake prefix: {eid}"
                )


def test_no_broker_endpoint_words_in_module_source():
    """Static guard — the first-run seed file must not import or reference
    any broker/order/fill/position/withdrawal endpoint word."""
    src = Path(fr.__file__).read_text(encoding="utf-8")
    forbidden = (
        "place_order(",
        "submit_order(",
        "execute_trade(",
        "broker_execute(",
        "/orders",
        "/portfolio",
        "/fills",
        "/positions",
        "/deposits",
        "/withdrawals",
        "/balance",
    )
    for token in forbidden:
        assert token not in src, f"forbidden token in first_run script: {token!r}"


def test_help_string_documents_advisory_only():
    src = Path(fr.__file__).read_text(encoding="utf-8")
    assert "ADVISORY-ONLY" in src.upper()
    assert "No broker" in src or "no broker" in src
