"""Section 4 — Memory decay / stale candidate decay."""
from __future__ import annotations

import math

from scripts.governance.daily_gate import decay_factor, memory_decay


def test_decay_12_days_matches_spec():
    md = memory_decay(run_date="2026-06-05", last_seen_date="2026-05-24")
    assert md["delta_days"] == 12
    assert round(md["decay"], 3) == 0.050
    assert math.isclose(md["decay"], math.exp(-0.25 * 12), rel_tol=1e-4)
    assert md["stale_flag"] is True
    assert md["severe_stale_flag"] is True


def test_decay_factor_table():
    assert decay_factor(0) == 1.0
    assert round(decay_factor(5), 3) == 0.287


def test_stale_thresholds():
    assert memory_decay(run_date="2026-06-05", last_seen_date="2026-05-31")["stale_flag"] is True
    assert memory_decay(run_date="2026-06-05", last_seen_date="2026-06-04")["stale_flag"] is False


def test_board_classifications(gov_result):
    by_ticker = {e["ticker"]: e for e in gov_result.stale_memory_decay_board}
    assert by_ticker["GLD"]["classification"] == "PHANTOM QUARANTINE"
    assert by_ticker["ZIM"]["classification"] == "PHANTOM / STALE"
    assert by_ticker["RTX"]["classification"] == "MANAGEMENT_ONLY"
