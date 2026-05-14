"""Sprint 7D — source configuration hardening.

Pins:
* SEC EDGAR env-driven default CIK / built-in watchlist are detected from
  the environment by the refresh orchestrator and forwarded to run_phase1.
* GDELT_TIMEOUT_SECONDS is forwarded as an int when valid; ignored when
  blank / non-numeric / below 1.
* Each source has a tier (core / secondary / optional / planned) exposed
  on get_source_family / list_live_source_families.
* compute_source_freshness returns the tier alongside the freshness state
  so the UI can grade skip warnings.
* The hardening introduces no broker call, no execution permission.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from scripts import refresh_live_signals as rls
from scripts import live_source_registry as lsr


# ---------------------------------------------------------------------------
# SEC env resolution
# ---------------------------------------------------------------------------


def test_sec_kwargs_empty_when_no_env(monkeypatch):
    monkeypatch.delenv("SEC_DEFAULT_CIK", raising=False)
    monkeypatch.delenv("SEC_DEFAULT_WATCHLIST", raising=False)
    monkeypatch.delenv("SEC_USE_DEFAULT_WATCHLIST", raising=False)
    assert rls._resolve_sec_phase1_kwargs() == {}


def test_sec_kwargs_uses_single_cik(monkeypatch):
    monkeypatch.setenv("SEC_DEFAULT_CIK", "0000320193")
    monkeypatch.delenv("SEC_DEFAULT_WATCHLIST", raising=False)
    out = rls._resolve_sec_phase1_kwargs()
    assert out == {"sec_cik": "0000320193"}


def test_sec_kwargs_enables_watchlist_when_truthy(monkeypatch):
    monkeypatch.delenv("SEC_DEFAULT_CIK", raising=False)
    for truthy in ("1", "true", "yes", "on", "TRUE"):
        monkeypatch.setenv("SEC_DEFAULT_WATCHLIST", truthy)
        assert rls._resolve_sec_phase1_kwargs() == {"sec_default_watchlist": True}


def test_sec_kwargs_alias_use_default_watchlist(monkeypatch):
    monkeypatch.delenv("SEC_DEFAULT_CIK", raising=False)
    monkeypatch.delenv("SEC_DEFAULT_WATCHLIST", raising=False)
    monkeypatch.setenv("SEC_USE_DEFAULT_WATCHLIST", "true")
    assert rls._resolve_sec_phase1_kwargs() == {"sec_default_watchlist": True}


def test_sec_cik_wins_over_watchlist(monkeypatch):
    monkeypatch.setenv("SEC_DEFAULT_CIK", "0001318605")
    monkeypatch.setenv("SEC_DEFAULT_WATCHLIST", "true")
    assert rls._resolve_sec_phase1_kwargs() == {"sec_cik": "0001318605"}


def test_sec_watchlist_false_value_does_not_enable(monkeypatch):
    monkeypatch.delenv("SEC_DEFAULT_CIK", raising=False)
    for falsy in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("SEC_DEFAULT_WATCHLIST", falsy)
        assert rls._resolve_sec_phase1_kwargs() == {}


# ---------------------------------------------------------------------------
# GDELT env resolution
# ---------------------------------------------------------------------------


def test_gdelt_timeout_default_empty(monkeypatch):
    monkeypatch.delenv("GDELT_TIMEOUT_SECONDS", raising=False)
    assert rls._resolve_gdelt_phase1_kwargs() == {}


def test_gdelt_timeout_valid(monkeypatch):
    monkeypatch.setenv("GDELT_TIMEOUT_SECONDS", "10")
    assert rls._resolve_gdelt_phase1_kwargs() == {"gdelt_timeout": 10}


def test_gdelt_timeout_invalid_ignored(monkeypatch):
    for raw in ("abc", "-5", "0", "  "):
        monkeypatch.setenv("GDELT_TIMEOUT_SECONDS", raw)
        assert rls._resolve_gdelt_phase1_kwargs() == {}


# ---------------------------------------------------------------------------
# Orchestrator wiring — env reaches run_phase1
# ---------------------------------------------------------------------------


def test_invoke_phase1_threads_sec_env(monkeypatch):
    monkeypatch.setenv("SEC_DEFAULT_CIK", "0000320193")
    captured: dict = {}

    class _FakeReport:
        sources = []

    def _fake_run_phase1(**kwargs):
        captured.update(kwargs)
        return _FakeReport()

    with patch("scripts.live_source_runner.run_phase1", _fake_run_phase1):
        rls._invoke_phase1_single("sec_edgar", dry_run=True)

    assert captured.get("sec_cik") == "0000320193"
    assert captured.get("sources") == ["sec_edgar"]
    assert captured.get("dry_run") is True


def test_invoke_phase1_threads_gdelt_timeout(monkeypatch):
    monkeypatch.setenv("GDELT_TIMEOUT_SECONDS", "12")
    captured: dict = {}

    class _FakeReport:
        sources = []

    def _fake_run_phase1(**kwargs):
        captured.update(kwargs)
        return _FakeReport()

    with patch("scripts.live_source_runner.run_phase1", _fake_run_phase1):
        rls._invoke_phase1_single("gdelt", dry_run=True)

    assert captured.get("gdelt_timeout") == 12


def test_invoke_phase1_polymarket_unaffected(monkeypatch):
    monkeypatch.setenv("SEC_DEFAULT_CIK", "0000320193")
    monkeypatch.setenv("GDELT_TIMEOUT_SECONDS", "9")
    captured: dict = {}

    class _FakeReport:
        sources = []

    def _fake_run_phase1(**kwargs):
        captured.update(kwargs)
        return _FakeReport()

    with patch("scripts.live_source_runner.run_phase1", _fake_run_phase1):
        rls._invoke_phase1_single("polymarket", dry_run=True)

    assert "sec_cik" not in captured
    assert "gdelt_timeout" not in captured


# ---------------------------------------------------------------------------
# Tier metadata
# ---------------------------------------------------------------------------


def test_tier_core_for_polymarket_and_gdelt():
    assert lsr.get_source_tier("polymarket") == lsr.SOURCE_TIER_CORE
    assert lsr.get_source_tier("gdelt") == lsr.SOURCE_TIER_CORE


def test_tier_planned_for_asia_disclosure():
    assert lsr.get_source_tier("asia_disclosure") == lsr.SOURCE_TIER_PLANNED


def test_tier_secondary_for_sec_edgar():
    assert lsr.get_source_tier("sec_edgar") == lsr.SOURCE_TIER_SECONDARY


def test_tier_optional_for_etherscan_and_unknown():
    assert lsr.get_source_tier("etherscan") == lsr.SOURCE_TIER_OPTIONAL
    # Unknown defaults to optional.
    assert lsr.get_source_tier("totally_unknown_source") == lsr.SOURCE_TIER_OPTIONAL


def test_get_source_family_includes_tier():
    fam = lsr.get_source_family("polymarket")
    assert fam.get("tier") == lsr.SOURCE_TIER_CORE


def test_list_live_source_families_includes_tier_on_every_entry():
    families = lsr.list_live_source_families()
    assert families  # not empty
    for fam in families:
        assert "tier" in fam, f"{fam['source_key']} missing tier"
        assert fam["tier"] in {
            lsr.SOURCE_TIER_CORE,
            lsr.SOURCE_TIER_SECONDARY,
            lsr.SOURCE_TIER_OPTIONAL,
            lsr.SOURCE_TIER_PLANNED,
        }


def test_compute_source_freshness_includes_tier():
    out = lsr.compute_source_freshness([], cadence_hours=6, now_epoch=0.0)
    # asia_disclosure is planned but still gets a tier entry.
    assert out["asia_disclosure"]["tier"] == lsr.SOURCE_TIER_PLANNED
    assert out["polymarket"]["tier"] == lsr.SOURCE_TIER_CORE


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


def test_hardening_does_not_unlock_execution():
    fam = lsr.get_source_family("sec_edgar")
    assert fam["can_execute"] is False
    assert fam["advisory_only"] is True
    fresh = lsr.compute_source_freshness([], cadence_hours=6, now_epoch=0.0)
    for entry in fresh.values():
        assert entry["execution_gate"] == "LOCKED"
        assert entry["broker_api_called"] is False
        assert entry["execution_permission"] is False
        assert entry["can_execute"] is False
        assert entry["may_execute"] is False
        assert entry["may_call_broker"] is False


def test_env_resolvers_never_print_secrets(monkeypatch, capsys):
    monkeypatch.setenv("SEC_DEFAULT_CIK", "very-private-cik")
    monkeypatch.setenv("GDELT_TIMEOUT_SECONDS", "10")
    rls._resolve_sec_phase1_kwargs()
    rls._resolve_gdelt_phase1_kwargs()
    captured = capsys.readouterr()
    assert "very-private-cik" not in captured.out
    assert "very-private-cik" not in captured.err
