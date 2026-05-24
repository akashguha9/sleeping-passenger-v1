"""Tests for the 6-hour live source refresh orchestrator.

These tests are intentionally synthetic: no live adapter is invoked, no
network call is made, and credential state is supplied explicitly via the
``env`` parameter of the registry helpers (the orchestrator reads from the
process environment, which we manage with monkeypatch).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from scripts.live_source_registry import ADVISORY_STATUS, EXECUTION_GATE_LOCKED
from scripts.run_live_refresh import (
    build_orchestrator_report,
    main as orchestrator_main,
)


ALL_KEYS = (
    "polymarket",
    "kalshi",
    "gdelt",
    "sec_edgar",
    "newsapi",
    "event_registry",
    "etherscan",
    "grok_xai",
    "market_data",
    "india",
    "global_filings",
    "asia_disclosure",
)


def _clear_live_keys(monkeypatch) -> None:
    for key in (
        "NEWS_API_KEY",
        "EVENT_REGISTRY_API_KEY",
        "ETHERSCAN_API_KEY",
        "XAI_API_KEY",
        "SEC_USER_AGENT",
    ):
        monkeypatch.delenv(key, raising=False)


def _all_live_keys(monkeypatch) -> None:
    monkeypatch.setenv("NEWS_API_KEY", "fake-news")
    monkeypatch.setenv("EVENT_REGISTRY_API_KEY", "fake-er")
    monkeypatch.setenv("ETHERSCAN_API_KEY", "fake-eth")
    monkeypatch.setenv("XAI_API_KEY", "xai-fake-not-real-1234567890")
    monkeypatch.setenv("SEC_USER_AGENT", "SleepingPassenger contact@example.com")


# ---------------------------------------------------------------------------
# build_orchestrator_report
# ---------------------------------------------------------------------------


def test_default_dry_run_does_not_invoke_any_adapter(monkeypatch) -> None:
    _clear_live_keys(monkeypatch)
    report = build_orchestrator_report(
        list(ALL_KEYS), write_mode=False, plan_only=False, cadence_hours=6
    )
    # We assert that the orchestrator never says "ran" — it only ever says
    # "would_run", "would_write", or "skipped". The presence of "ran" would
    # mean an adapter was actually invoked.
    actions = {e["action"] for e in report["entries"]}
    assert "ran" not in actions
    assert "failed" not in actions


def test_all_eleven_source_families_included(monkeypatch) -> None:
    _clear_live_keys(monkeypatch)
    report = build_orchestrator_report(
        list(ALL_KEYS), write_mode=False, plan_only=False, cadence_hours=6
    )
    keys = tuple(e["source_key"] for e in report["entries"])
    assert keys == ALL_KEYS


def test_missing_credentials_skip_source_not_abort_run(monkeypatch) -> None:
    _clear_live_keys(monkeypatch)
    report = build_orchestrator_report(
        list(ALL_KEYS), write_mode=False, plan_only=False, cadence_hours=6
    )
    by_key = {e["source_key"]: e for e in report["entries"]}
    # Sources requiring API keys must be skipped, not failed:
    for key in ("newsapi", "event_registry", "etherscan", "grok_xai"):
        assert by_key[key]["action"] == "skipped"
        assert by_key[key]["reason"].startswith("missing_credentials")
    # Keyless sources should still be "would_run":
    for key in ("polymarket", "gdelt", "market_data", "india"):
        assert by_key[key]["action"] == "would_run"


def test_source_failure_does_not_abort_whole_run(monkeypatch) -> None:
    # In the orchestrator we treat every source independently. A skipped
    # source for one reason does not affect any other source.
    _clear_live_keys(monkeypatch)
    report = build_orchestrator_report(
        list(ALL_KEYS), write_mode=False, plan_only=False, cadence_hours=6
    )
    assert report["summary"]["total"] == len(ALL_KEYS)
    assert report["summary"]["skipped"] >= 1
    assert report["summary"]["would_run"] >= 1


def test_partial_adapter_asia_disclosure_proceeds_to_would_run(monkeypatch) -> None:
    """Asia Disclosure is no longer ADAPTER_PLANNED — EDINET (Japan) and
    OpenDART (Korea) are wired official-API sub-sources.  The orchestrator
    must therefore route it to would_run (or would_write in write mode),
    not skip it with the legacy ``adapter_planned_not_implemented``
    reason.  Sub-source-level missing-key handling lives in the loader."""
    _all_live_keys(monkeypatch)
    report = build_orchestrator_report(
        list(ALL_KEYS), write_mode=False, plan_only=False, cadence_hours=6
    )
    by_key = {e["source_key"]: e for e in report["entries"]}
    assert by_key["asia_disclosure"]["action"] in {"would_run", "would_write"}
    assert (
        by_key["asia_disclosure"].get("reason", "")
        != "adapter_planned_not_implemented"
    )


def test_write_must_be_explicit(monkeypatch) -> None:
    _all_live_keys(monkeypatch)
    dry = build_orchestrator_report(
        list(ALL_KEYS), write_mode=False, plan_only=False, cadence_hours=6
    )
    wet = build_orchestrator_report(
        list(ALL_KEYS), write_mode=True, plan_only=False, cadence_hours=6
    )
    assert dry["mode"] == "dry_run"
    assert wet["mode"] == "write"
    # In dry-run, no entry should be in "would_write".
    assert all(e["action"] != "would_write" for e in dry["entries"])


def test_plan_only_disables_write_even_when_write_flag_present(monkeypatch) -> None:
    _all_live_keys(monkeypatch)
    report = build_orchestrator_report(
        list(ALL_KEYS), write_mode=True, plan_only=True, cadence_hours=6
    )
    assert report["mode"] == "dry_run"
    assert report["plan_only"] is True
    assert all(e["action"] != "would_write" for e in report["entries"])


def test_safety_stamps_on_every_entry(monkeypatch) -> None:
    _all_live_keys(monkeypatch)
    report = build_orchestrator_report(
        list(ALL_KEYS), write_mode=True, plan_only=False, cadence_hours=6
    )
    for entry in report["entries"]:
        assert entry["advisory_status"] == ADVISORY_STATUS
        assert entry["execution_gate"] == EXECUTION_GATE_LOCKED
        assert entry["broker_api_called"] is False
        assert entry["ai_execution_count"] == 0
        assert entry["human_review_required"] is True


def test_safety_stamps_on_envelope(monkeypatch) -> None:
    _all_live_keys(monkeypatch)
    report = build_orchestrator_report(
        list(ALL_KEYS), write_mode=False, plan_only=False, cadence_hours=6
    )
    assert report["advisory_status"] == ADVISORY_STATUS
    assert report["execution_gate"] == EXECUTION_GATE_LOCKED
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
    assert report["human_review_required"] is True


def test_cadence_default_is_six(monkeypatch) -> None:
    _clear_live_keys(monkeypatch)
    report = build_orchestrator_report(
        list(ALL_KEYS), write_mode=False, plan_only=False, cadence_hours=6
    )
    assert report["cadence_hours"] == 6


def test_unknown_source_returns_safe_failure(capsys, monkeypatch) -> None:
    _all_live_keys(monkeypatch)
    rc = orchestrator_main(["--source", "definitely_made_up", "--dry-run", "--json"])
    assert rc == 2
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["error"] == "unknown_source"
    assert payload["advisory_status"] == ADVISORY_STATUS


def test_orchestrator_does_not_leak_secret_values(monkeypatch, capsys) -> None:
    monkeypatch.setenv("XAI_API_KEY", "xai-supersecretvaluethatshouldneverappear")
    monkeypatch.setenv("NEWS_API_KEY", "news-supersecretvaluethatshouldneverappear")
    monkeypatch.delenv("EVENT_REGISTRY_API_KEY", raising=False)
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    rc = orchestrator_main(["--source", "all", "--dry-run", "--json"])
    assert rc == 0
    text = capsys.readouterr().out
    assert "supersecretvaluethatshouldneverappear" not in text


def test_orchestrator_text_output_includes_cadence(monkeypatch, capsys) -> None:
    _all_live_keys(monkeypatch)
    rc = orchestrator_main(["--source", "all", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "every 6h" in out
    assert "Advisory: ADVISORY_ONLY" in out
    assert "Execution gate: LOCKED" in out


def test_orchestrator_single_source_dry_run(monkeypatch) -> None:
    _all_live_keys(monkeypatch)
    report = build_orchestrator_report(
        ["polymarket"], write_mode=False, plan_only=False, cadence_hours=6
    )
    assert [e["source_key"] for e in report["entries"]] == ["polymarket"]
    assert report["summary"]["total"] == 1
    assert report["entries"][0]["action"] == "would_run"


def test_orchestrator_plan_only_route(monkeypatch, capsys) -> None:
    _clear_live_keys(monkeypatch)
    rc = orchestrator_main(["--source", "all", "--plan-only", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["plan_only"] is True
    assert payload["mode"] == "dry_run"
    assert payload["summary"]["total"] == len(ALL_KEYS)
