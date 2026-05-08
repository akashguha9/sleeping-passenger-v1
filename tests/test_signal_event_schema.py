"""Tests for the canonical SignalEvent schema."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.normalization.signal_event_schema import (  # noqa: E402
    ADVISORY_ONLY,
    NumericSignal,
    SignalEvent,
    assert_advisory_only,
)


def test_signal_event_defaults_advisory_only_and_human_review() -> None:
    e = SignalEvent(source_name="x", source_type="news_event")
    assert e.execution_permission == ADVISORY_ONLY
    assert e.human_review_required is True
    assert e.mvp_state == "MIURA"
    assert e.source_reliability == 0.0
    assert e.freshness_score == 0.0
    assert e.narrative_intensity == 0.0
    assert e.market_confirmation == 0.0
    assert e.contradiction_score == 0.0


def test_signal_event_rejects_non_advisory_permission() -> None:
    with pytest.raises(ValueError):
        SignalEvent(source_name="x", source_type="news_event", execution_permission="EXECUTE")


def test_signal_event_rejects_human_review_false() -> None:
    with pytest.raises(ValueError):
        SignalEvent(source_name="x", source_type="news_event", human_review_required=False)


def test_signal_event_rejects_unknown_state() -> None:
    with pytest.raises(ValueError):
        SignalEvent(source_name="x", source_type="news_event", mvp_state="EXECUTE")


def test_assert_advisory_only_helper() -> None:
    e = SignalEvent(source_name="x", source_type="news_event")
    assert_advisory_only(e)
    e.execution_permission = "EXECUTE"
    with pytest.raises(ValueError):
        assert_advisory_only(e)


def test_numeric_signal_accepts_dict_payload() -> None:
    e = SignalEvent(
        source_name="x",
        source_type="news_event",
        numeric_signal={"probability": 0.7, "filing_materiality_score": 0.8},  # type: ignore[arg-type]
    )
    assert isinstance(e.numeric_signal, NumericSignal)
    assert e.numeric_signal.probability == 0.7
    assert e.numeric_signal.filing_materiality_score == 0.8
