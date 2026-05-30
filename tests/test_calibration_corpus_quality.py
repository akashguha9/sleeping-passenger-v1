"""Tests — calibration corpus quality (deterministic, pure).

Kanté Ceiling Push II, Workstream B.  Proves the EMPTY/WEAK/DEVELOPING/
USABLE/STRONG label bands, that high validity with low linkage is penalised,
that >=0.90 quality under 100 outcomes is NOT STRONG, and that real-money
sizing stays PROHIBITED even for a STRONG_PAPER_ONLY corpus.
"""
from __future__ import annotations

import pytest

from scripts.calibration_corpus_quality import (
    LABEL_DEVELOPING,
    LABEL_EMPTY,
    LABEL_STRONG_PAPER_ONLY,
    LABEL_USABLE_PAPER_ONLY,
    LABEL_WEAK,
    build_corpus_quality,
)


# --- 1 ----------------------------------------------------------------------
def test_empty_corpus_label():
    r = build_corpus_quality(n_closed=0)
    assert r["corpus_label"] == LABEL_EMPTY
    assert r["top_blocker"] == "no_closed_paper_outcomes"


# --- 2 ----------------------------------------------------------------------
def test_weak_corpus_label():
    r = build_corpus_quality(
        n_closed=10, n_valid=0, n_review=8, n_rejected=2, n_linked=0, n_bucketed=0
    )
    assert r["corpus_label"] == LABEL_WEAK
    assert r["corpus_quality_score"] < 0.40


# --- 3 ----------------------------------------------------------------------
def test_low_linkage_penalized():
    high_link = build_corpus_quality(
        n_closed=50, n_valid=50, n_linked=50, n_bucketed=50
    )
    low_link = build_corpus_quality(
        n_closed=50, n_valid=50, n_linked=0, n_bucketed=0
    )
    assert low_link["corpus_quality_score"] < high_link["corpus_quality_score"]
    assert low_link["corpus_label"] == LABEL_DEVELOPING
    assert low_link["top_blocker"] in {"low_linkage_rate", "low_bucket_coverage"}


# --- 4 ----------------------------------------------------------------------
def test_strong_under_100_not_strong():
    r = build_corpus_quality(n_closed=50, n_valid=50, n_linked=50, n_bucketed=50)
    assert r["corpus_quality_score"] >= 0.90
    assert r["corpus_label"] != LABEL_STRONG_PAPER_ONLY
    assert r["corpus_label"] == LABEL_USABLE_PAPER_ONLY


# --- 5 ----------------------------------------------------------------------
def test_strong_100_label():
    r = build_corpus_quality(n_closed=100, n_valid=100, n_linked=100, n_bucketed=100)
    assert r["corpus_quality_score"] >= 0.90
    assert r["corpus_label"] == LABEL_STRONG_PAPER_ONLY


# --- 6 ----------------------------------------------------------------------
def test_corpus_quality_real_money_prohibited():
    for kwargs in (
        {"n_closed": 0},
        {"n_closed": 100, "n_valid": 100, "n_linked": 100, "n_bucketed": 100},
    ):
        r = build_corpus_quality(**kwargs)
        assert r["real_money_sizing_impact"] == "PROHIBITED"
        assert r["real_money_weight_allowed"] is False
        assert r["execution_gate"] == "LOCKED"
        assert r["broker_api_called"] is False
        assert r["ai_execution_count"] == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
