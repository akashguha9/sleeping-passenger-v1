"""Tests for ``scripts.operator_live_provider_refresh`` (Sprint 3 — Part 2).

These tests mock provider modules; no real network calls are made.
"""
from __future__ import annotations

import json
import types
from datetime import datetime, timezone

import pytest

from scripts import operator_live_provider_refresh as olpr


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeRequests:
    @staticmethod
    def get(url, params=None, headers=None, timeout=None):
        if "sec.gov" in url:
            return _FakeResponse({
                "filings": {"recent": {
                    "form": ["10-K", "8-K"],
                    "filingDate": ["2026-05-22", "2026-05-20"],
                    "accessionNumber": ["x1", "x2"],
                }}
            })
        if "gdelt" in url:
            return _FakeResponse({"articles": [
                {"url": "https://news.example.com/a",
                 "title": "Markets rally",
                 "seendate": "20260524T120000Z"},
                {"url": "https://news.example.com/b",
                 "title": "Inflation data",
                 "seendate": "20260524T100000Z"},
            ]})
        return _FakeResponse({})


def _fake_yfinance():
    class _DF:
        def __init__(self, rows, idx):
            self._rows = rows
            self.index = idx
            self.shape = (len(rows), 4)

        def __getitem__(self, key):
            class _Col:
                def __init__(self, vals):
                    self._vals = vals

                @property
                def iloc(self):
                    return self
                def __getitem__(self, i):
                    return self._vals[i]
            return _Col([r[key] for r in self._rows])

    class _Ts:
        def __init__(self, dt):
            self._dt = dt

        def to_pydatetime(self):
            return self._dt

    class _Ticker:
        def history(self, period, interval):
            now = datetime.now(timezone.utc)
            return _DF(
                [{"Close": 100.0}, {"Close": 101.5}],
                idx=[_Ts(now), _Ts(now)],
            )

    return types.SimpleNamespace(Ticker=lambda sym: _Ticker())


# ---------------------------------------------------------------------------
# Refusal-by-default
# ---------------------------------------------------------------------------


def test_refuses_live_run_without_mvp_live_refresh_ok(monkeypatch):
    monkeypatch.delenv("MVP_LIVE_REFRESH_OK", raising=False)
    summary = olpr.refresh_providers()
    assert summary["network_allowed"] is False
    # Every requested provider is OFFLINE.
    for ev in summary["providers_evidence"]:
        assert ev["status"] in {"OFFLINE", "SKIPPED"}
        assert ev["verification_status"] != "LIVE_VERIFIED"
    assert summary["live_payload_quality_score"] == 8.2
    assert summary["providers_live_verified"] == []


def test_advisory_safety_stamps_present_in_summary(monkeypatch):
    monkeypatch.delenv("MVP_LIVE_REFRESH_OK", raising=False)
    summary = olpr.refresh_providers()
    assert summary["advisory_status"] == "ADVISORY_ONLY"
    assert summary["execution_gate"] == "LOCKED"
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# Mocked live success: 3 LIVE_VERIFIED -> LPQ 8.6
# ---------------------------------------------------------------------------


def test_mocked_three_providers_lift_lpq_to_8_6(monkeypatch):
    monkeypatch.setenv("MVP_LIVE_REFRESH_OK", "1")
    monkeypatch.setenv("SEC_USER_AGENT", "test test@example.com")
    summary = olpr.refresh_providers(
        yfinance_module=_fake_yfinance(),
        requests_module=_FakeRequests,
    )
    assert summary["ok"] is True
    assert set(summary["providers_live_verified"]) == {
        "yfinance", "sec_edgar", "gdelt"
    }
    assert summary["live_payload_quality_score"] >= 8.6
    # Every LIVE_VERIFIED row carries a timestamp.
    for ev in summary["providers_evidence"]:
        if ev["verification_status"] == "LIVE_VERIFIED":
            assert ev["latest_provider_timestamp_utc"]


def test_mocked_yfinance_only_lifts_lpq_to_8_35(monkeypatch):
    monkeypatch.setenv("MVP_LIVE_REFRESH_OK", "1")
    monkeypatch.setenv("SEC_USER_AGENT", "")
    monkeypatch.setenv("YFINANCE_LIVE_ENABLED", "true")
    # SEC will get CONFIG_MISSING (empty UA), GDELT mocked to fail.
    class _GdeltFail:
        @staticmethod
        def get(url, params=None, headers=None, timeout=None):
            if "gdelt" in url:
                return _FakeResponse({}, status_code=503)
            if "sec.gov" in url:
                # Should not reach here because UA missing -> CONFIG_MISSING.
                return _FakeResponse({})
            return _FakeResponse({})
    summary = olpr.refresh_providers(
        yfinance_module=_fake_yfinance(),
        requests_module=_GdeltFail,
    )
    live = summary["providers_live_verified"]
    assert live == ["yfinance"]
    assert summary["live_payload_quality_score"] == 8.35


def test_fixture_mode_cannot_produce_live_verified(monkeypatch):
    monkeypatch.delenv("MVP_LIVE_REFRESH_OK", raising=False)
    summary = olpr.refresh_providers()
    for ev in summary["providers_evidence"]:
        assert ev["verification_status"] != "LIVE_VERIFIED"


# ---------------------------------------------------------------------------
# SEC config missing path (must not crash)
# ---------------------------------------------------------------------------


def test_missing_sec_user_agent_produces_config_missing(monkeypatch):
    monkeypatch.setenv("MVP_LIVE_REFRESH_OK", "1")
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    summary = olpr.refresh_providers(
        providers=["sec_edgar"],
        yfinance_module=_fake_yfinance(),
        requests_module=_FakeRequests,
    )
    [ev] = summary["providers_evidence"]
    assert ev["provider"] == "sec_edgar"
    assert ev["status"] in {"CONFIG_MISSING", "OFFLINE"}
    assert ev["verification_status"] != "LIVE_VERIFIED"


# ---------------------------------------------------------------------------
# Provider failure honesty
# ---------------------------------------------------------------------------


def test_yfinance_network_failure_degrades_to_failed(monkeypatch):
    monkeypatch.setenv("MVP_LIVE_REFRESH_OK", "1")

    class _BrokenTicker:
        def history(self, period, interval):
            raise RuntimeError("network down")

    yf = types.SimpleNamespace(Ticker=lambda sym: _BrokenTicker())
    summary = olpr.refresh_providers(
        providers=["yfinance"],
        yfinance_module=yf,
        requests_module=_FakeRequests,
    )
    [ev] = summary["providers_evidence"]
    assert ev["status"] == "FAILED"
    assert ev["verification_status"] != "LIVE_VERIFIED"
    assert ev["last_error"] is not None


# ---------------------------------------------------------------------------
# Artifact write + safety
# ---------------------------------------------------------------------------


def test_write_summary_persists_evidence_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("MVP_LIVE_REFRESH_OK", "1")
    monkeypatch.setenv("SEC_USER_AGENT", "test t@example.com")
    summary = olpr.refresh_providers(
        yfinance_module=_fake_yfinance(),
        requests_module=_FakeRequests,
    )
    summary_target = tmp_path / "op.json"
    evidence_target = tmp_path / "ev.json"
    out = olpr.write_summary(
        summary, summary_path=summary_target, evidence_path=evidence_target,
    )
    assert summary_target.exists()
    assert evidence_target.exists()
    ev_payload = json.loads(evidence_target.read_text(encoding="utf-8"))
    assert ev_payload["advisory_only"] is True
    assert ev_payload["broker_api_called"] is False
    # Every live row keeps a timestamp.
    for row in ev_payload["evidence"]:
        if row["verification_status"] == "LIVE_VERIFIED":
            assert row["latest_provider_timestamp_utc"]


def test_operator_artifact_valid_handles_missing():
    info = olpr.operator_artifact_valid(None)
    assert info["valid"] is False
    assert info["fresh"] is False
    assert info["providers_live_verified"] == []


def test_operator_artifact_valid_marks_stale(monkeypatch):
    old_summary = {
        "ok": True,
        "operator_run": True,
        "generated_at_utc": "2020-01-01T00:00:00Z",
        "providers_live_verified": ["yfinance"],
        "previous_live_payload_quality_score": 8.2,
        "live_payload_quality_score": 8.35,
        "ttl_hours": 24,
    }
    info = olpr.operator_artifact_valid(old_summary)
    assert info["fresh"] is False
    assert info["valid"] is False


def test_no_broker_api_calls_anywhere():
    # Inspect the module source for forbidden execution tokens.
    import inspect
    src = inspect.getsource(olpr)
    for token in (
        "place_order", "submit_order", "broker_execute",
        "auto_execute", "execute_trade",
    ):
        assert token not in src
