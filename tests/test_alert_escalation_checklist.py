"""Tests: alert escalation + operator checklist (Open-the-Gate, Item 7)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.operator_alert_bridge import (
    SEV_CRITICAL,
    compute_escalations,
    dedupe_key,
    generate_operator_checklist,
    write_operator_checklist,
)

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)


def _queue_row(category: str, created_at: str, severity: str = SEV_CRITICAL,
               title: str = "t") -> dict:
    return {
        "alert_id": f"AL_{created_at[:10]}_{category}",
        "created_at": created_at,
        "severity": severity,
        "category": category,
        "title": title,
        "message": "m",
        "source": "truth_surface",
        "dedupe_key": dedupe_key(category, "truth_surface", "m",
                                 created_at[:10]),
        "requires_operator_action": True,
        "run_id": None,
    }


def _queue(tmp_path: Path, rows: list[dict]) -> Path:
    q = tmp_path / "alerts.jsonl"
    q.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                 encoding="utf-8")
    return q


def test_unresolved_critical_escalates_l2_after_24h(tmp_path: Path) -> None:
    first = (NOW - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    q = _queue(tmp_path, [
        _queue_row("leveraged_missing_stop", first),
        _queue_row("leveraged_missing_stop", today),
    ])
    esc = compute_escalations(queue_path=q, now_utc=NOW)
    assert len(esc) == 1
    assert esc[0]["escalation_level"] == 2
    assert esc[0]["severity"] == SEV_CRITICAL
    assert "24" in esc[0]["message"] or "30 hours" in esc[0]["message"]


def test_unresolved_critical_escalates_l3_after_72h(tmp_path: Path) -> None:
    first = (NOW - timedelta(hours=80)).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    q = _queue(tmp_path, [
        _queue_row("operational_state", first),
        _queue_row("operational_state", today),
    ])
    esc = compute_escalations(queue_path=q, now_utc=NOW)
    assert len(esc) == 1
    assert esc[0]["escalation_level"] == 3
    assert "PERSISTENT BLOCKER" in esc[0]["title"]


def test_resolved_alert_does_not_escalate(tmp_path: Path) -> None:
    """A condition raised yesterday but NOT today is resolved — no escalation."""
    yesterday = (NOW - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = _queue(tmp_path, [_queue_row("missing_stops", yesterday)])
    assert compute_escalations(queue_path=q, now_utc=NOW) == []


def test_fresh_critical_does_not_escalate(tmp_path: Path) -> None:
    today = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    q = _queue(tmp_path, [_queue_row("stop_breach", today)])
    assert compute_escalations(queue_path=q, now_utc=NOW) == []


def _surface(**over) -> dict:
    base = {
        "overall_operational_state": "BLOCKED",
        "missing_stop_count": 10,
        "unconfirmed_stop_count": 0,
        "leveraged_without_stop_count": 2,
        "holdings_truth_status": "HOLDINGS_TRUTH_STALE",
        "calibration_status": "MEASURED_NOT_CALIBRATED",
        "matured_real_outcome_count": 56,
        "latest_alerts": [{"a": 1}],
        "next_required_operator_action": "Confirm stops",
    }
    base.update(over)
    return base


def test_checklist_includes_next_action_and_no_real_money(tmp_path: Path) -> None:
    md = generate_operator_checklist(
        _surface(),
        calendar={"next_maturity_date": "2026-07-09",
                  "projected_n_end_of_window": 81},
        now_utc=NOW,
    )
    assert "Confirm stop-losses" in md
    assert "10 missing" in md
    assert "2 LEVERAGED" in md
    assert "2026-07-09" in md and "81" in md
    assert "DO NOT use real money" in md
    assert "Confirm stops" in md  # next_required_operator_action echoed
    # no secrets: nothing token/key-like belongs in the checklist
    for needle in ("sk-", "AIza", "ghp_", "Bearer "):
        assert needle not in md
    path = write_operator_checklist(
        _surface(), path=tmp_path / "check.md", now_utc=NOW,
    )
    assert Path(path).exists()


def test_checklist_marks_done_items(tmp_path: Path) -> None:
    md = generate_operator_checklist(
        _surface(missing_stop_count=0, unconfirmed_stop_count=0,
                 leveraged_without_stop_count=0,
                 holdings_truth_status="OK",
                 overall_operational_state="HEALTHY"),
        now_utc=NOW,
    )
    assert "1. [x] Confirm stop-losses" in md
    assert "[x] Refresh holdings truth" in md
