"""Tests — Real Evidence Sprint Phase 4: reproducible evidence bundle.

Proves the bundle is written, carries a commit hash, separates real vs fixture
sources and real-forward vs proxy outcomes, keeps the predictive claim locked
when the gate is locked, defines a reproducibility score, and that the markdown
states limitations and makes NO real-money claim.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import real_evidence_bundle as bundle_mod
from scripts import outcome_labeling_flow as flow
from scripts.decision_probability_snapshot import record_decision_probability


_AXES = {"EMS": 0.6, "EQS": 0.55, "DS": 0.5, "LS": 0.45, "EFS": 0.5, "APS": 0.5}


def _db(tmp_path: Path) -> Path:
    return tmp_path / "snap.db"


def _seed(db: Path, n: int, kind: str, prefix: str) -> None:
    for i in range(n):
        snap = record_decision_probability(
            db_path=db, signal_id=f"{prefix}-{i}", axes=_AXES, prediction_horizon_days=5
        )
        flow.attach_outcome(db, snap["snapshot_id"], i % 2, is_real_outcome=True, outcome_kind=kind)


def _canary_report() -> dict:
    return {
        "per_source": [
            {"source_name": "yfinance", "activated": True, "canary_real": False},
            {"source_name": "gdelt", "activated": True, "canary_real": False},
            {"source_name": "polymarket", "activated": True, "canary_real": True},
            {"source_name": "newsapi", "activated": False, "canary_real": False},
        ],
        "C_global": 0.5,
        "live_canonical_count": 3,
    }


# --- 1. bundle JSON written -----------------------------------------------
def test_evidence_bundle_json_written(tmp_path):
    db = _db(tmp_path)
    b = bundle_mod.build_evidence_bundle(db, canary_report=_canary_report(), repo_commit="deadbeef")
    paths = bundle_mod.write_bundle(
        b, json_path=tmp_path / "bundle.json", md_path=tmp_path / "BUNDLE.md"
    )
    assert Path(paths["json_path"]).exists()
    assert Path(paths["markdown_path"]).exists()


# --- 2. commit hash present -----------------------------------------------
def test_evidence_bundle_contains_commit_hash(tmp_path):
    b = bundle_mod.build_evidence_bundle(_db(tmp_path), canary_report=_canary_report())
    assert "repo_commit" in b
    assert isinstance(b["repo_commit"], str) and b["repo_commit"]


# --- 3. separates real and fixture sources --------------------------------
def test_evidence_bundle_separates_real_and_fixture_sources(tmp_path):
    b = bundle_mod.build_evidence_bundle(_db(tmp_path), canary_report=_canary_report())
    assert b["real_source_activation"]["source_count"] == 1
    assert b["real_source_activation"]["sources"] == ["polymarket"]
    assert b["fixture_source_activation"]["source_count"] == 2
    assert set(b["fixture_source_activation"]["sources"]) == {"yfinance", "gdelt"}


# --- 4. separates real-forward and proxy outcomes -------------------------
def test_evidence_bundle_separates_real_forward_and_proxy_outcomes(tmp_path):
    db = _db(tmp_path)
    _seed(db, 4, flow.REAL_FORWARD, "rf")
    _seed(db, 6, flow.HISTORICAL_PROXY, "px")
    b = bundle_mod.build_evidence_bundle(db, canary_report=_canary_report())
    assert b["outcomes"]["n_real_forward_pairs"] == 4
    assert b["outcomes"]["n_historical_proxy_pairs"] == 6


# --- 5. predictive claim false when gate locked ---------------------------
def test_evidence_bundle_predictive_claim_false_when_gate_locked(tmp_path):
    db = _db(tmp_path)
    _seed(db, 10, flow.REAL_FORWARD, "rf")  # well below N=200
    b = bundle_mod.build_evidence_bundle(db, canary_report=_canary_report())
    assert b["predictive_claim_allowed"] is False
    assert b["calibration"]["predictive_claim_allowed"] is False
    assert b["s_evidence"]["components"]["calibration_gate_score"] == 0.0
    assert b["real_money_ready"] is False


# --- 6. markdown contains limitations -------------------------------------
def test_markdown_bundle_contains_limitations(tmp_path):
    b = bundle_mod.build_evidence_bundle(_db(tmp_path), canary_report=_canary_report())
    md = bundle_mod.render_markdown(b)
    assert "## Limitations" in md
    assert "ADVISORY ONLY" in md


# --- 7. markdown contains no real-money claim -----------------------------
def test_markdown_bundle_contains_no_real_money_claim(tmp_path):
    b = bundle_mod.build_evidence_bundle(_db(tmp_path), canary_report=_canary_report())
    md = bundle_mod.render_markdown(b).lower()
    for forbidden in [
        "real-money ready: true", "real money ready", "guaranteed",
        "place order", "execute trade", "auto-trade", "broker connected",
    ]:
        assert forbidden not in md, f"forbidden phrase present: {forbidden}"
    assert "not real-money ready" in md


# --- 8. reproducibility score defined -------------------------------------
def test_bundle_reproducibility_score_defined(tmp_path):
    db = _db(tmp_path)
    # Without tests_green/commit, repro score is 0.
    b0 = bundle_mod.build_evidence_bundle(db, canary_report=_canary_report(), repo_commit="UNKNOWN")
    assert b0["s_evidence"]["components"]["reproducibility_score"] == 0.0
    # With commit + tests_green it can be 1.0.
    b1 = bundle_mod.build_evidence_bundle(
        db, canary_report=_canary_report(), repo_commit="abc123", tests_green=True
    )
    assert b1["s_evidence"]["components"]["reproducibility_score"] == 1.0
    assert 0.0 <= b1["s_evidence"]["score"] <= 1.0


# --- bonus: advisory invariants on the bundle -----------------------------
def test_bundle_advisory_invariants(tmp_path):
    b = bundle_mod.build_evidence_bundle(_db(tmp_path), canary_report=_canary_report())
    assert b["execution_gate"] == "LOCKED"
    assert b["broker_api_called"] is False
    assert b["ai_execution_count"] == 0
    assert b["advisory_only"] is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
