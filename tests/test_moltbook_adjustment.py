"""Objective 6 — Moltbook read-back penalty hook tests."""
from __future__ import annotations

from scripts.moltbook_adjustment import (
    DEFAULT_DOWNGRADE_THRESHOLD,
    NO_MATCH_REASON,
    adjust_admission,
    apply_moltbook_adjustment,
    compute_pattern_signature,
    moltbook_penalty_for_pattern,
    signature_from_dict,
)

_PATTERN = dict(
    country="India",
    signal_class="momentum",
    source_mix=["polymarket", "gdelt"],
)


def _entry(outcome_quality, **extra):
    base = dict(_PATTERN)
    base.update(extra)
    base["outcome_quality"] = outcome_quality
    return base


def _sig():
    return signature_from_dict(_PATTERN)


def test_no_moltbook_history_penalty_zero():
    block = moltbook_penalty_for_pattern(_sig(), [])
    assert block["moltbook_penalty"] == 0.0
    assert block["reason"] == NO_MATCH_REASON

    adj = apply_moltbook_adjustment(0.7, _sig(), [])
    assert adj["p_adj"] == adj["p_base"] == 0.7
    assert adj["moltbook_adjustment_applied"] is False


def test_bad_moltbook_pattern_reduces_probability():
    entries = [_entry("LOSS") for _ in range(5)]
    adj = apply_moltbook_adjustment(0.7, _sig(), entries)
    assert adj["moltbook_penalty"] > 0.0
    assert adj["p_adj"] < adj["p_base"]
    assert adj["moltbook_adjustment_applied"] is True
    assert adj["moltbook_pattern_n"] == 5


def test_good_or_empty_pattern_does_not_increase_beyond_base_unless_explicitly_supported():
    # All-good history still must NOT push probability above base (penalty is
    # one-directional: it can only lower or hold).
    entries = [_entry("WIN") for _ in range(5)]
    adj = apply_moltbook_adjustment(0.6, _sig(), entries)
    assert adj["p_adj"] <= adj["p_base"]

    # Non-matching pattern -> no change at all.
    other_sig = compute_pattern_signature(country="USA", signal_class="value", source_mix="sec_edgar")
    adj2 = apply_moltbook_adjustment(0.6, other_sig, entries)
    assert adj2["p_adj"] == adj2["p_base"] == 0.6


def test_moltbook_penalty_cannot_unlock_execution():
    entries = [_entry("STOP_LOSS_HIT") for _ in range(8)]
    adj = apply_moltbook_adjustment(0.9, _sig(), entries)
    assert adj["moltbook_can_unlock_execution"] is False
    assert adj["execution_gate"] == "LOCKED"
    assert adj["broker_api_called"] is False
    assert adj["ai_execution_count"] == 0


def test_moltbook_penalty_metadata_present():
    entries = [_entry("LOSS"), _entry("WIN"), _entry("LOSS")]
    adj = apply_moltbook_adjustment(0.55, _sig(), entries)
    for key in (
        "moltbook_penalty",
        "moltbook_pattern_n",
        "moltbook_bad_rate",
        "moltbook_adjustment_applied",
        "p_base",
        "p_adj",
        "reason",
    ):
        assert key in adj


def test_bad_pattern_can_change_admission_from_candidate_to_watchlist_if_threshold_crossed():
    entries = [_entry("LOSS") for _ in range(5)]
    block = moltbook_penalty_for_pattern(_sig(), entries)
    penalty = block["moltbook_penalty"]
    assert penalty >= DEFAULT_DOWNGRADE_THRESHOLD  # strong bad history

    downgraded = adjust_admission("ADVISORY_CANDIDATE_FOR_HUMAN_REVIEW", penalty)
    assert downgraded == "WATCHLIST"

    # A tiny penalty leaves the admission unchanged.
    unchanged = adjust_admission("ADVISORY_CANDIDATE_FOR_HUMAN_REVIEW", 0.001)
    assert unchanged == "ADVISORY_CANDIDATE_FOR_HUMAN_REVIEW"
