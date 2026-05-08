"""Tests for the canonical signal processor."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.normalization.signal_event_schema import (  # noqa: E402
    ADVISORY_ONLY,
    NumericSignal,
    SignalEvent,
)
from scripts.normalization.signal_processor import process_signal  # noqa: E402


def _fresh_ts() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def test_process_signal_stamps_advisory_and_assigns_reliability() -> None:
    raw = {
        "source_name": "polymarket",
        "source_type": "prediction_market",
        "headline_or_label": "Will X happen?",
        "timestamp_utc": _fresh_ts(),
        "numeric_signal": NumericSignal(probability=0.7),
    }
    event = process_signal(raw)
    assert event.execution_permission == ADVISORY_ONLY
    assert event.human_review_required is True
    assert event.source_reliability > 0.0
    assert event.freshness_score > 0.0


def test_process_signal_strips_caller_supplied_execute_flag() -> None:
    raw = {
        "source_name": "x",
        "source_type": "news_event",
        "execution_permission": "AUTO_EXECUTE",  # must be ignored / overridden
        "timestamp_utc": _fresh_ts(),
    }
    event = process_signal(raw)
    assert event.execution_permission == ADVISORY_ONLY


def test_process_signal_diablo_blocks_promotion() -> None:
    raw = {
        "source_name": "x",
        "source_type": "official_filing",
        "headline_or_label": "8-K filing",
        "timestamp_utc": _fresh_ts(),
        "numeric_signal": NumericSignal(filing_materiality_score=0.85),
    }
    # Even with cross-validation + materiality, chaos veto must dominate.
    event = process_signal(raw, chaos_active=True, cross_validated=True)
    assert event.mvp_state == "DIABLO"


def test_process_signal_islero_overrides_when_shock_detected() -> None:
    raw = {
        "source_name": "x",
        "source_type": "prediction_market",
        "headline_or_label": "Huge swing",
        "timestamp_utc": _fresh_ts(),
        "numeric_signal": NumericSignal(probability=0.97),  # |0.97-0.5|=0.47 -> shock
    }
    event = process_signal(raw)
    assert event.mvp_state == "ISLERO"


def test_process_signal_huracan_requires_validation_floor() -> None:
    # Stale timestamp -> low freshness; should NOT promote to HURACAN.
    stale = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    raw = {
        "source_name": "x",
        "source_type": "news_event",  # reliability 0.55
        "headline_or_label": "old story",
        "timestamp_utc": stale,
        "numeric_signal": NumericSignal(),
    }
    event = process_signal(raw, fast_track_requested=True)
    assert event.mvp_state != "HURACAN"


def test_process_signal_huracan_promotes_when_floor_met() -> None:
    raw = {
        "source_name": "x",
        "source_type": "official_filing",  # reliability 0.95
        "headline_or_label": "fresh filing",
        "timestamp_utc": _fresh_ts(),
        "market_confirmation": 0.5,
        "numeric_signal": NumericSignal(filing_materiality_score=0.6),
    }
    event = process_signal(raw, fast_track_requested=True)
    assert event.mvp_state == "HURACAN"


def test_process_signal_accepts_pre_built_signal_event() -> None:
    e = SignalEvent(source_name="x", source_type="news_event", timestamp_utc=_fresh_ts())
    out = process_signal(e)
    assert out.execution_permission == ADVISORY_ONLY
