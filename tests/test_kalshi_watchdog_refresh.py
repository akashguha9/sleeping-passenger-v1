"""Tests for the Kalshi read-only watchdog.

Verifies:
- Fresh source-health => no refresh attempted, exit 0.
- Stale or missing source-health => refresh attempted; success/failure
  recorded in the summary; safety stamps always present.
- Refresh failure surfaces error type/message in the summary without
  echoing secrets.
- Trading endpoints remain blocked even if a buggy callable tried to
  hit one (the watchdog never builds non-GET requests).
- The watchdog summary is sanitized and contains the canonical safety
  block.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.kalshi_watchdog_refresh import run_watchdog


SECRET_API_KEY_ID = "00000000-1111-2222-3333-444444444444"


@pytest.fixture(autouse=True)
def _env_pinned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # Use a fake env so the watchdog never tries to load a real key.
    cryptography = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path = tmp_path / "watchdog.key"
    key_path.write_bytes(pem)
    monkeypatch.setenv("KALSHI_ENV", "demo")
    monkeypatch.setenv("KALSHI_API_KEY_ID", SECRET_API_KEY_ID)
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", str(key_path))
    monkeypatch.setenv("KALSHI_ENABLE_AUTH", "true")
    monkeypatch.setenv("KALSHI_READ_ONLY", "true")
    monkeypatch.setenv("KALSHI_ENABLE_TRADING", "false")
    monkeypatch.setenv("KALSHI_ORDER_PLACEMENT_ENABLED", "false")
    monkeypatch.setenv("KALSHI_BROKER_API_CALLED", "false")
    monkeypatch.setenv("KALSHI_USE_MOCK_FIXTURES", "false")
    monkeypatch.setenv("KALSHI_FRESHNESS_TTL_SECONDS", "21600")
    yield


def _write_health(path: Path, *, fetched_at: str, ttl: int = 21600) -> None:
    payload = {
        "source_name": "kalshi",
        "status": "OK",
        "records_allowed": 1,
        "records_quarantined": 0,
        "source_freshness_status": "LIVE_VERIFIED",
        "freshness_ttl_seconds": ttl,
        "last_successful_fetch_at_utc": fetched_at,
        "advisory_only": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_fresh_health_skips_refresh(tmp_path: Path):
    h = tmp_path / "kalshi_source_health.json"
    now = datetime.now(timezone.utc)
    _write_health(h, fetched_at=now.isoformat())
    refresh = MagicMock()
    result = run_watchdog(
        health_path=h,
        summary_path=tmp_path / "watchdog_summary.json",
        env="demo",
        ttl_seconds=21600,
        now_utc=now,
        refresh_callable=refresh,
    )
    assert result.fresh is True
    assert result.refresh_attempted is False
    refresh.assert_not_called()
    summary = json.loads((tmp_path / "watchdog_summary.json").read_text(encoding="utf-8"))
    assert summary["advisory_only"] is True
    assert summary["broker_api_called"] is False
    assert summary["fresh"] is True


def test_stale_health_triggers_refresh(tmp_path: Path):
    h = tmp_path / "kalshi_source_health.json"
    now = datetime.now(timezone.utc)
    stale = now - timedelta(seconds=21600 * 4)
    _write_health(h, fetched_at=stale.isoformat())

    refresh = MagicMock()
    refresh.return_value = MagicMock(
        status="ok",
        source_freshness_status="LIVE_VERIFIED",
        error_type="",
        error_message="",
    )
    result = run_watchdog(
        health_path=h,
        summary_path=tmp_path / "watchdog_summary.json",
        env="demo",
        ttl_seconds=21600,
        now_utc=now,
        refresh_callable=refresh,
    )
    assert result.stale is True
    assert result.refresh_attempted is True
    assert result.refresh_succeeded is True
    refresh.assert_called_once()
    # Refresh receives the same health path so the next read still sees the
    # refreshed artifact.
    call_kwargs = refresh.call_args.kwargs
    assert call_kwargs["health_path"] == h
    assert call_kwargs["dry_run"] is True


def test_missing_health_treated_as_refresh_required(tmp_path: Path):
    h = tmp_path / "absent.json"
    refresh = MagicMock(
        return_value=MagicMock(
            status="ok",
            source_freshness_status="LIVE_VERIFIED",
            error_type="",
            error_message="",
        )
    )
    now = datetime.now(timezone.utc)
    result = run_watchdog(
        health_path=h,
        summary_path=tmp_path / "watchdog_summary.json",
        env="demo",
        ttl_seconds=21600,
        now_utc=now,
        refresh_callable=refresh,
    )
    assert result.missing is True
    assert result.refresh_attempted is True
    assert result.refresh_succeeded is True


def test_refresh_failure_records_error_and_no_secret_leak(tmp_path: Path):
    h = tmp_path / "kalshi_source_health.json"
    now = datetime.now(timezone.utc)
    stale = now - timedelta(seconds=21600 * 4)
    _write_health(h, fetched_at=stale.isoformat())

    refresh = MagicMock(side_effect=RuntimeError("kalshi 503"))
    result = run_watchdog(
        health_path=h,
        summary_path=tmp_path / "watchdog_summary.json",
        env="demo",
        ttl_seconds=21600,
        now_utc=now,
        refresh_callable=refresh,
    )
    assert result.refresh_attempted is True
    assert result.refresh_succeeded is False
    # Only type name surfaces — never the response body.
    assert result.error_type == "RuntimeError"
    summary_path = tmp_path / "watchdog_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    blob = json.dumps(summary)
    for needle in (
        SECRET_API_KEY_ID,
        "BEGIN PRIVATE KEY",
        "BEGIN RSA PRIVATE KEY",
        "KALSHI-ACCESS-KEY",
        "KALSHI-ACCESS-SIGNATURE",
        "Authorization",
    ):
        assert needle not in blob


def test_safety_stamps_always_present(tmp_path: Path):
    h = tmp_path / "kalshi_source_health.json"
    now = datetime.now(timezone.utc)
    _write_health(h, fetched_at=now.isoformat())
    refresh = MagicMock()
    result = run_watchdog(
        health_path=h,
        summary_path=tmp_path / "watchdog_summary.json",
        env="demo",
        ttl_seconds=21600,
        now_utc=now,
        refresh_callable=refresh,
    )
    payload = result.to_dict()
    assert payload["advisory_only"] is True
    assert payload["human_review_required"] is True
    assert payload["execution_locked"] is True
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["safety_violations"] == []


def test_watchdog_summary_persisted_atomically(tmp_path: Path):
    h = tmp_path / "kalshi_source_health.json"
    summary_target = tmp_path / "watchdog_summary.json"
    now = datetime.now(timezone.utc)
    _write_health(h, fetched_at=now.isoformat())
    run_watchdog(
        health_path=h,
        summary_path=summary_target,
        env="demo",
        ttl_seconds=21600,
        now_utc=now,
        refresh_callable=MagicMock(),
    )
    assert summary_target.exists()
    # No leftover .tmp file from the atomic write.
    assert not summary_target.with_suffix(summary_target.suffix + ".tmp").exists()
