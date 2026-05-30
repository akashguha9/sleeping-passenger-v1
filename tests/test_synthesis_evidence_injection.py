"""Tests for synthesis evidence injection (P3 of the Kanté evidence sprint).

Proves that:
* ``compute_synthesis_evidence_score`` implements the documented formula.
* ``render_evidence_readiness_block`` surfaces every required proof metric.
* The hard classification invariants (BUY_CANDIDATE / PRICE_CONFIRMED_WATCH /
  C_global phrasing / advisory-only / new_risk) are present.
* The block is actually wired into the five-model context renderer.

Advisory only; no execution, no broker, no network.
"""
from __future__ import annotations

import importlib

import pytest


def _load():
    return importlib.import_module("scripts.daily_synthesis_pipeline")


def test_evidence_score_full_marks():
    mod = _load()
    ev = mod.compute_synthesis_evidence_score(
        {
            "C_global": 0.0333,
            "L_today_count": 1,
            "H_price_coverage": 1.0,
            "payload_stale": False,
            "sqlite_fresh_rows_count": 1,
            "provider_attempts": {"YAHOO": {"status": "OK"}},
        }
    )
    assert ev["synthesis_evidence_score"] == 1.0
    assert all(v == 1 for v in ev["components"].values())


def test_evidence_score_zero():
    mod = _load()
    ev = mod.compute_synthesis_evidence_score(
        {
            "C_global": 0.0,
            "L_today_count": 0,
            "H_price_coverage": 0.0,
            "payload_stale": True,
            "sqlite_fresh_rows_count": 0,
            "provider_attempts": {},
        }
    )
    assert ev["synthesis_evidence_score"] == 0.0
    assert all(v == 0 for v in ev["components"].values())


def test_evidence_score_partial_weighting():
    mod = _load()
    # C_global positive + payload fresh via sqlite_fresh only -> 0.40.
    ev = mod.compute_synthesis_evidence_score(
        {
            "C_global": 0.0333,
            "L_today_count": 0,
            "H_price_coverage": 0.5,  # below 0.80 threshold
            "payload_stale": True,
            "sqlite_fresh_rows_count": 1,  # forces payload_fresh=1
            "provider_attempts": {},
        }
    )
    assert ev["components"]["C_global_positive"] == 1
    assert ev["components"]["H_price_coverage_ok"] == 0
    assert ev["components"]["payload_fresh"] == 1
    assert ev["synthesis_evidence_score"] == pytest.approx(0.40)


def test_h_price_threshold_is_080():
    mod = _load()
    at = mod.compute_synthesis_evidence_score({"H_price_coverage": 0.80})
    below = mod.compute_synthesis_evidence_score({"H_price_coverage": 0.79})
    assert at["components"]["H_price_coverage_ok"] == 1
    assert below["components"]["H_price_coverage_ok"] == 0


def _germany_covered():
    return {
        "ratios": {"C_global": 0.0333, "C_price": 0.1667},
        "countries": {
            "Germany": {
                "price_support": 1,
                "news_support": 1,
                "mapping_support": 1,
                "coverage": 1,
            }
        },
    }


def test_readiness_block_includes_all_required_metrics():
    mod = _load()
    block = mod.render_evidence_readiness_block(
        {
            "country_coverage": _germany_covered(),
            "candidates": [{"ticker": "RHM.DE"}],
            "H_price_coverage": 1.0,
            "payload_stale": False,
            "sqlite_fresh_rows_count": 1,
            "provider_attempts": {"YAHOO": {"status": "OK"}},
            "new_risk_allowed": False,
        }
    )
    for needle in (
        "synthesis_evidence_score",
        "C_global",
        "L_today_count",
        "H_price_coverage",
        "payload_stale",
        "provider_attempts_observed",
        "new_risk_allowed",
    ):
        assert needle in block, "missing metric in block: %s" % needle


def test_readiness_block_includes_hard_classification_invariants():
    mod = _load()
    block = mod.render_evidence_readiness_block(
        {"country_coverage": _germany_covered(), "candidates": [{"ticker": "RHM.DE"}]}
    )
    assert "BUY_CANDIDATE" in block  # candidate-not-in-L_today rule
    assert "PRICE_CONFIRMED_WATCH" in block  # price-only rule
    assert "end-to-end" in block  # C_global>0 phrasing
    assert "ADVISORY" in block
    assert "RHM.DE" not in block or "COVERAGE-BACKED" in block


def test_readiness_block_c_global_zero_phrasing():
    mod = _load()
    block = mod.render_evidence_readiness_block(
        {"country_coverage": {"ratios": {"C_global": 0.0}, "countries": {}}, "candidates": []}
    )
    assert "not fully live" in block


def test_price_only_country_is_watch_only():
    mod = _load()
    block = mod.render_evidence_readiness_block(
        {
            "country_coverage": {
                "ratios": {"C_global": 0.0},
                "countries": {
                    "Germany": {
                        "price_support": 1,
                        "news_support": 0,
                        "mapping_support": 0,
                        "coverage": 0,
                    }
                },
            },
            "candidates": [],
        }
    )
    assert "Germany: PRICE_CONFIRMED_WATCH only" in block


def test_block_is_wired_into_context_renderer():
    """The five-model context renderer must call the readiness block."""
    import inspect

    mod = _load()
    src = inspect.getsource(mod.render_portfolio_truth_context)
    assert "render_evidence_readiness_block(result)" in src
