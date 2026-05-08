"""Tests for the bull-state classifier and its overrides."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.normalization.signal_event_schema import SignalEvent  # noqa: E402
from scripts.state_machine.bull_state_classifier import (  # noqa: E402
    classify,
    meets_validation_floor,
)
from scripts.state_machine.diablo_chaos_veto import apply_diablo_veto  # noqa: E402
from scripts.state_machine.huracan_fast_track import apply_huracan_fast_track  # noqa: E402
from scripts.state_machine.islero_shock_detector import apply_islero_override  # noqa: E402


def _make_event(**overrides) -> SignalEvent:
    base = dict(
        source_name="x",
        source_type="news_event",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        source_reliability=0.7,
        freshness_score=0.7,
        market_confirmation=0.5,
    )
    base.update(overrides)
    return SignalEvent(**base)


def test_diablo_veto_blocks_aventador_promotion() -> None:
    e = _make_event(mvp_state="AVENTADOR")
    apply_diablo_veto(e, chaos_active=True)
    assert e.mvp_state == "DIABLO"


def test_diablo_veto_blocks_gallardo_promotion() -> None:
    e = _make_event(mvp_state="GALLARDO")
    apply_diablo_veto(e, chaos_active=True)
    assert e.mvp_state == "DIABLO"


def test_islero_shock_overrides_state() -> None:
    e = _make_event(mvp_state="MURCIELAGO")
    apply_islero_override(e, shock_active=True)
    assert e.mvp_state == "ISLERO"


def test_huracan_fast_track_blocked_below_floor() -> None:
    e = _make_event(source_reliability=0.1, market_confirmation=0.0)
    assert not meets_validation_floor(e)
    apply_huracan_fast_track(e, requested=True)
    assert e.mvp_state != "HURACAN"


def test_huracan_fast_track_allowed_when_floor_met() -> None:
    e = _make_event(source_reliability=0.9, market_confirmation=0.5)
    apply_huracan_fast_track(e, requested=True)
    assert e.mvp_state == "HURACAN"


def test_classifier_returns_string_states_only() -> None:
    e = _make_event()
    state = classify(e, cross_validated=True)
    assert state in {"MIURA", "MURCIELAGO", "AVENTADOR", "GALLARDO", "ISLERO", "DIABLO", "HURACAN"}
