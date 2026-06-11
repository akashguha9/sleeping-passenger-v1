"""Temporal guard proofs (Pass 4, Phase 4) — no time travel."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from scripts import temporal_guard as tg

UTC = dt.timezone.utc
DEC = dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def test_clean_sample_valid():
    v = tg.validate_sample(
        t_decision=DEC,
        t_published=DEC - dt.timedelta(days=1),
        t_observed=DEC - dt.timedelta(hours=12),
        t_outcome=DEC + dt.timedelta(days=5),
    )
    assert v.status == tg.VALID
    assert v.usable_for_evaluation


def test_future_earnings_included_is_invalid():
    """Earnings published AFTER the decision must not feed the decision."""
    v = tg.validate_sample(
        t_decision=DEC,
        t_published=DEC + dt.timedelta(hours=3),  # earnings later that day
        t_outcome=DEC + dt.timedelta(days=5),
    )
    assert v.status == tg.INVALID
    assert any("lookahead" in r for r in v.reasons)


def test_revised_financials_detected():
    """Restated data: 'published' after the system already observed it."""
    v = tg.validate_sample(
        t_decision=DEC,
        t_published=DEC - dt.timedelta(hours=1),
        t_observed=DEC - dt.timedelta(days=2),  # observed before publication
        t_outcome=DEC + dt.timedelta(days=5),
    )
    assert v.status == tg.INVALID
    assert any("revision" in r or "revised" in r for r in v.reasons)


def test_article_published_after_decision_invalid():
    v = tg.validate_sample(
        t_decision=DEC,
        t_observed=DEC + dt.timedelta(minutes=5),
        t_outcome=DEC + dt.timedelta(days=1),
    )
    assert v.status == tg.INVALID


def test_outcome_leaking_into_features():
    """Outcome at/before the decision = target leakage."""
    v = tg.validate_sample(t_decision=DEC, t_outcome=DEC)
    assert v.status == tg.INVALID
    assert any("target leakage" in r for r in v.reasons)


def test_timezone_conversion_ist_cet_utc():
    """09:00 IST == 03:30 UTC: published-before-decision holds only when
    timezones convert correctly."""
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    cet = dt.timezone(dt.timedelta(hours=1))
    decision_cet = dt.datetime(2026, 6, 1, 13, 0, tzinfo=cet)  # 12:00 UTC
    published_ist = dt.datetime(2026, 6, 1, 9, 0, tzinfo=ist)  # 03:30 UTC
    v = tg.validate_sample(
        t_decision=decision_cet,
        t_published=published_ist,
        t_outcome="2026-06-05T00:00:00+00:00",
    )
    assert v.status == tg.VALID
    # Flip it: published 23:00 IST (17:30 UTC) is AFTER the 12:00 UTC decision.
    v2 = tg.validate_sample(
        t_decision=decision_cet,
        t_published=dt.datetime(2026, 6, 1, 23, 0, tzinfo=ist),
        t_outcome="2026-06-05T00:00:00+00:00",
    )
    assert v2.status == tg.INVALID


def test_naive_timestamps_refused():
    v = tg.validate_sample(
        t_decision=DEC, t_observed="2026-06-01T10:00:00",  # naive
        t_outcome=DEC + dt.timedelta(days=1),
    )
    assert v.status == tg.INVALID
    assert any("naive" in r for r in v.reasons)


def test_missing_decision_timestamp_invalid():
    v = tg.validate_sample(t_decision=None)  # type: ignore[arg-type]
    assert v.status == tg.INVALID


def test_manual_override_requires_reason_and_audits(monkeypatch, tmp_path):
    monkeypatch.setenv("MVP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    bad = tg.validate_sample(t_decision=DEC, t_outcome=DEC)
    with pytest.raises(tg.TemporalError):
        tg.override_sample(bad, reason="   ")
    blessed = tg.override_sample(bad, reason="deliberate research exception X")
    assert blessed.status == tg.OVERRIDDEN
    assert blessed.usable_for_evaluation
    events = [
        json.loads(l)
        for l in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(e["action"] == "temporal_guard_override" for e in events)


def test_filter_partitions_and_reports_rejects():
    samples = [
        {"t_decision": DEC.isoformat(),
         "t_outcome": (DEC + dt.timedelta(days=2)).isoformat()},
        {"t_decision": DEC.isoformat(), "t_outcome": DEC.isoformat()},  # leak
    ]
    result = tg.filter_evaluation_samples(samples)
    assert len(result["usable"]) == 1
    assert len(result["rejected"]) == 1
    _, reasons = result["rejected"][0]
    assert reasons  # silent drops are forbidden
