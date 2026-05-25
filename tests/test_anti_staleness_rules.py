"""Layer 4 — anti-staleness tests."""
from __future__ import annotations

from pathlib import Path

from daily_payload_factory import write_daily_payload

from scripts.anti_staleness import (
    adjusted_cqs,
    build_anti_staleness,
    freshness_label,
    staleness_penalty,
)
from scripts.daily_payload import load_daily_payload
from scripts.portfolio_truth_gate import build_portfolio_truth_gate


def _payload_and_gate(tmp_path: Path, **kwargs):
    payload_dir = write_daily_payload(tmp_path / "payload", **kwargs)
    payload = load_daily_payload(payload_dir)
    gate = build_portfolio_truth_gate(payload=payload)
    return payload, gate


def test_repeated_ticker_without_change_flags_warning(tmp_path: Path) -> None:
    payload, gate = _payload_and_gate(
        tmp_path, yesterday_final=["RTX", "GLD", "ZIM"], closed_or_sold=["GLD"], sold=["GLD"],
    )
    result = build_anti_staleness(payload, ["RTX"], gate)  # repeats RTX, no change note
    assert "RTX" in result["repeats_missing_change_explanation"]
    assert result["stale_discovery_warning"] is True


def test_change_explanation_clears_repeat(tmp_path: Path) -> None:
    payload, gate = _payload_and_gate(tmp_path, yesterday_final=["RTX", "ZIM"])
    result = build_anti_staleness(
        payload, ["RTX"], gate, change_explanations={"RTX": "fresh order backlog beat today"},
    )
    assert result["repeats_missing_change_explanation"] == []
    assert result["freshness_labels"]["RTX"] == "UPDATED_TODAY"


def test_novelty_ratio_below_threshold_warns(tmp_path: Path) -> None:
    payload, gate = _payload_and_gate(tmp_path, yesterday_final=["RTX", "ZIM"])
    # today = RTX, ZIM (both repeats) -> novelty 0.0
    result = build_anti_staleness(
        payload, ["RTX", "ZIM"], gate,
        change_explanations={"RTX": "x", "ZIM": "y"},
    )
    assert result["novelty_ratio"] == 0.0
    assert result["stale_discovery_warning"] is True


def test_novelty_ratio_high_no_warning(tmp_path: Path) -> None:
    payload, gate = _payload_and_gate(tmp_path, yesterday_final=["RTX"])
    result = build_anti_staleness(payload, ["AAA", "BBB", "CCC", "DDD"], gate)
    assert result["novelty_ratio"] == 1.0
    assert result["stale_discovery_warning"] is False


def test_staleness_penalty_and_adjusted_cqs() -> None:
    assert staleness_penalty("STALE_24H") == 0.20
    assert staleness_penalty("HISTORICAL_ONLY") == 0.50
    assert adjusted_cqs(0.80, "STALE_48H") == 0.45


def test_phantom_never_blocks_discovery(tmp_path: Path) -> None:
    payload, gate = _payload_and_gate(
        tmp_path, not_owned=["UNG", "TIP", "TLT", "FCG"], yesterday_final=["UNG"],
    )
    result = build_anti_staleness(payload, ["RTX"], gate)
    assert result["global_discovery_permission"] is True
    assert result["phantom_position_risk_blocks_discovery"] is False


def test_freshness_labels_for_overrides() -> None:
    assert freshness_label("UNG", fresh_evidence=False, in_yesterday=True,
                           has_change_explanation=False,
                           truth_label="DO_NOT_TREAT_AS_OPEN") == "DO_NOT_TREAT_AS_OPEN"
    assert freshness_label("GLD", fresh_evidence=True, in_yesterday=True,
                           has_change_explanation=True,
                           truth_label="CLOSED_OR_SOLD") == "CLOSED_OR_SOLD"
    assert freshness_label("AAA", fresh_evidence=True, in_yesterday=False,
                           has_change_explanation=False) == "FRESH_TODAY"
