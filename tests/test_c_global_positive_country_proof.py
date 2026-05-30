"""Tests — C_global positive country proof (mission P4).

Deterministic, offline. Proves: coverage(Germany)=1 and C_global=1/30 when
exactly one country is covered; C_global cannot be positive with a missing
layer; a real-run-shaped proof honestly reports missing layers; and the proof
separates FIXTURE from REAL_RUN. Advisory-only; no broker, no execution.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.country_coverage_proof import (
    DEFAULT_TARGET_COUNTRIES,
    build_coverage_proof,
    build_proof_from_payload,
    germany_fixture_coverage,
    target_readiness,
    write_country_coverage_proof,
)
from scripts.top30_country_coverage import DEFAULT_TOP30_COUNTRIES


def _germany_row(proof):
    return next(r for r in proof["country_rows"] if r["country"] == "Germany")


# --- fixture proof: coverage(Germany)=1, C_global=1/30 -----------------------

def test_germany_fixture_coverage_is_one():
    proof = germany_fixture_coverage()
    g = _germany_row(proof)
    assert g["coverage"] == 1
    assert g["target_readiness"] == 1.0
    assert g["missing_layers"] == []
    assert proof["first_covered_country"] == "Germany"
    assert proof["covered_country_count"] == 1
    assert proof["proof_kind"] == "FIXTURE"
    assert proof["global_status"] == "C_GLOBAL_POSITIVE"


def test_c_global_equals_one_over_thirty():
    proof = germany_fixture_coverage()
    n = len(DEFAULT_TOP30_COUNTRIES)
    assert n == 30
    assert proof["C_global"] == round(1 / 30, 4)
    assert proof["C_global"] == 0.0333


# --- C_global cannot be positive with a missing layer ------------------------

def test_missing_price_layer_blocks_coverage():
    g = ["Germany"]
    proof = build_coverage_proof(
        universe_countries=g,
        price_countries=[],          # price missing
        news_countries=g,
        filings_countries=g,
        mapping_countries=g,
        synthesis_countries=g,
    )
    row = _germany_row(proof)
    assert row["coverage"] == 0
    assert "price_support" in row["missing_layers"]
    assert proof["C_global"] == 0.0
    assert proof["covered_country_count"] == 0
    assert proof["global_status"] == "ONE_LAYER_MISSING"


def test_missing_mapping_layer_blocks_coverage():
    g = ["Germany"]
    proof = build_coverage_proof(
        universe_countries=g,
        price_countries=g,
        news_countries=g,
        filings_countries=g,
        mapping_countries=[],        # mapping missing
        synthesis_countries=g,
    )
    assert _germany_row(proof)["coverage"] == 0
    assert proof["C_global"] == 0.0


# --- target_readiness math ---------------------------------------------------

def test_target_readiness_weights():
    assert target_readiness(
        {"universe_loaded": 1, "price_support": 1, "news_support": 0,
         "mapping_support": 0, "synthesis_consumed": 0}
    ) == 0.4
    assert target_readiness({}) == 0.0


# --- real-run-shaped proof reports missing layers honestly -------------------

def test_real_run_proof_reports_missing_layers():
    # An empty payload (no live providers) -> no country covered, layers listed.
    proof = build_proof_from_payload(
        {"price_movers": {"movers": []}, "news_events": {"events": []},
         "filings_events": {"events": []}},
        price_rows=[], mapping_rows=[], proof_kind="REAL_RUN",
    )
    assert proof["proof_kind"] == "REAL_RUN"
    assert proof["C_global"] == 0.0
    assert proof["covered_country_count"] == 0
    for row in proof["country_rows"]:
        assert row["coverage"] == 0
        assert row["missing_layers"]  # something is missing for every target
    assert proof["global_status"] in {
        "ONE_LAYER_MISSING", "PARTIAL_TARGET_COUNTRY_COVERAGE", "COVERAGE_THIN"
    }


def test_proof_kinds_are_separated():
    fixture = germany_fixture_coverage()
    real = build_proof_from_payload(
        {"price_movers": {"movers": []}, "news_events": {"events": []},
         "filings_events": {"events": []}},
        price_rows=[], mapping_rows=[],
    )
    assert fixture["proof_kind"] == "FIXTURE"
    assert real["proof_kind"] == "REAL_RUN"


# --- write proof + safety stamps ---------------------------------------------

def test_write_proof_and_safety(tmp_path):
    proof = germany_fixture_coverage()
    out = write_country_coverage_proof(proof, tmp_path / "country_coverage_proof.json")
    assert out.exists()
    data = json.loads(Path(out).read_text(encoding="utf-8"))
    assert data["C_global"] == 0.0333
    assert data["executable_allowed"] is False
    assert data["safety"]["execution_gate"] == "LOCKED"
    assert data["safety"]["broker_api_called"] is False


def test_default_targets_present():
    proof = germany_fixture_coverage()
    countries = {r["country"] for r in proof["country_rows"]}
    assert set(DEFAULT_TARGET_COUNTRIES) <= countries


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
