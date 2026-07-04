"""Tests: the operator alert channel (Feed-the-Loop sprint)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.operator_alert_bridge import (
    SEV_CRITICAL,
    SEV_WARNING,
    build_alerts_from_surface,
    dispatch_alerts,
    latest_alerts,
)

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)


def _surface(**over) -> dict:
    base = {
        "overall_operational_state": "HEALTHY",
        "state_reasons": [],
        "canonical_holding_count": 10,
        "missing_stop_count": 0,
        "unconfirmed_stop_count": 0,
        "leveraged_without_stop_count": 0,
        "holdings_truth_status": "OK",
        "holdings_freshness_age_minutes": 100.0,
        "artifacts": {},
        "producer_scheduled": True,
        "evidence_velocity_7d": 3.5,
        "scheduler_status": "HEALTHY",
        "rows_persisted_status": {"sources": {}},
        "provider_canary_status": "PASS",
        "fresh_discovery_status": "OK",
    }
    base.update(over)
    return base


def test_blocked_state_creates_critical_alert() -> None:
    alerts = build_alerts_from_surface(
        _surface(overall_operational_state="BLOCKED",
                 state_reasons=["missing stops"]),
        now_utc=NOW,
    )
    cats = {a["category"]: a for a in alerts}
    assert "operational_state" in cats
    assert cats["operational_state"]["severity"] == SEV_CRITICAL
    assert cats["operational_state"]["requires_operator_action"] is True


def test_leveraged_missing_stop_is_critical() -> None:
    alerts = build_alerts_from_surface(
        _surface(leveraged_without_stop_count=2, missing_stop_count=2,
                 overall_operational_state="BLOCKED"),
        now_utc=NOW,
    )
    lev = next(a for a in alerts if a["category"] == "leveraged_missing_stop")
    assert lev["severity"] == SEV_CRITICAL


def test_zero_evidence_velocity_alerts_only_when_scheduled() -> None:
    scheduled = build_alerts_from_surface(
        _surface(evidence_velocity_7d=0), now_utc=NOW
    )
    assert any(a["category"] == "evidence_velocity" for a in scheduled)
    unscheduled = build_alerts_from_surface(
        _surface(evidence_velocity_7d=0, producer_scheduled=False), now_utc=NOW
    )
    assert not any(a["category"] == "evidence_velocity" for a in unscheduled)


def test_healthy_surface_produces_no_alerts() -> None:
    assert build_alerts_from_surface(_surface(), now_utc=NOW) == []


def test_dispatch_appends_and_dedupes(tmp_path: Path) -> None:
    q = tmp_path / "alerts.jsonl"
    latest = tmp_path / "latest.json"
    alerts = build_alerts_from_surface(
        _surface(overall_operational_state="BLOCKED",
                 state_reasons=["missing stops: 10"]),
        now_utc=NOW,
    )
    first = dispatch_alerts(alerts, write=True, queue_path=q,
                            latest_path=latest, now_utc=NOW, echo=False)
    assert first["alerts_new"] == len(alerts) > 0
    # Second dispatch same day, same condition (numbers may differ) -> deduped
    alerts2 = build_alerts_from_surface(
        _surface(overall_operational_state="BLOCKED",
                 state_reasons=["missing stops: 9"]),
        now_utc=NOW,
    )
    second = dispatch_alerts(alerts2, write=True, queue_path=q,
                             latest_path=latest, now_utc=NOW, echo=False)
    assert second["alerts_new"] == 0
    assert second["alerts_deduped"] == len(alerts2)
    # queue is append-only JSONL with valid schema
    lines = [json.loads(x) for x in q.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == len(alerts)
    for row in lines:
        for field in ("alert_id", "created_at", "severity", "category",
                      "title", "message", "source", "dedupe_key",
                      "requires_operator_action"):
            assert field in row
        assert row["severity"] in ("INFO", "WARNING", "CRITICAL")
    # snapshot readable via latest_alerts
    assert latest_alerts(latest_path=latest)


def test_rows_persisted_and_canary_triggers() -> None:
    alerts = build_alerts_from_surface(
        _surface(
            rows_persisted_status={"sources": {
                "kalshi": {"status": "DEGRADED_ZERO_PERSISTED"},
                "market_data": {"status": "OK"},
            }},
            provider_canary_status="FAIL",
            fresh_discovery_status="BLOCKED",
        ),
        now_utc=NOW,
    )
    cats = {a["category"] for a in alerts}
    assert {"rows_persisted", "provider_canary", "fresh_discovery"} <= cats
    rows_alert = next(a for a in alerts if a["category"] == "rows_persisted")
    assert "kalshi" in rows_alert["message"]
    assert "market_data" not in rows_alert["message"]
    assert rows_alert["severity"] == SEV_WARNING
