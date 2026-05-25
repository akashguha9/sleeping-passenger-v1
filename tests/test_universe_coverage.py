"""Tests for the universe coverage module (Sprint 3 — Part 6)."""
from __future__ import annotations

import json

import pytest

from scripts import universe_coverage as uc


def test_universe_has_at_least_44_tickers():
    assert len(uc.UNIVERSE) >= 44


def test_all_required_buckets_present():
    buckets = {row["bucket"] for row in uc.UNIVERSE}
    for required in uc.REQUIRED_BUCKETS:
        assert required in buckets, f"missing bucket {required}"


def test_every_ticker_has_yfinance_mapping():
    for row in uc.UNIVERSE:
        assert row["provider_symbol_yfinance"], (
            f"{row['symbol']} missing yfinance mapping"
        )


def test_every_ticker_has_news_terms():
    for row in uc.UNIVERSE:
        assert row["gdelt_query_terms"], (
            f"{row['symbol']} missing gdelt_query_terms"
        )


def test_every_ticker_has_leverage_policy():
    for row in uc.UNIVERSE:
        assert row.get("leverage_policy"), (
            f"{row['symbol']} missing leverage_policy"
        )


def test_non_india_tickers_are_spot_only():
    for row in uc.UNIVERSE:
        if row["country"] != "IN":
            assert row["leverage_policy"] == "spot_only", (
                f"{row['symbol']} ({row['country']}) "
                f"unexpected leverage {row['leverage_policy']!r}"
            )


def test_india_tickers_allow_up_to_4x_leverage():
    india = [r for r in uc.UNIVERSE if r["country"] == "IN"]
    assert india, "expected at least one India ticker"
    for row in india:
        assert row["leverage_policy"] in {"spot_only", "india_max_4x"}


def test_summary_writes(tmp_path):
    target = tmp_path / "uc.json"
    summary = uc.write_summary(target)
    assert target.exists()
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["ticker_count"] >= 44
    assert "universe_coverage_score" in on_disk
    assert on_disk["advisory_only"] is True


def test_jurisdictions_are_honestly_documented():
    # We claim US + IN + GLOBAL; we do NOT claim EU coverage.
    summary = uc.build_summary()
    assert "EU" not in summary["required_jurisdictions"]
    assert set(uc.REQUIRED_JURISDICTIONS) == {"US", "IN", "GLOBAL"}


def test_score_high_when_all_metadata_present():
    summary = uc.build_summary()
    assert summary["universe_coverage_score"] >= 9.5
    assert summary["india_spot_policy_violations"] == []
