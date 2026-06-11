"""Weight sanity (Phase 6) + score-change explainer (Phase 9) proofs."""
from __future__ import annotations

import datetime as dt
import random

import pytest

from scripts import explain_score_change as ex
from scripts import weight_sanity as ws


# ---------------------------------------------------------------------------
# Weight sanity — static checks
# ---------------------------------------------------------------------------


def test_detects_weights_not_summing_to_one():
    findings = ws.static_checks("X", {"a": 0.5, "b": 0.4}, require_sum_1=True)
    assert any(f["check"] == "sum_to_one" and f["severity"] == "severe"
               for f in findings)


def test_detects_negative_weight():
    findings = ws.static_checks("X", {"a": 1.2, "b": -0.2}, require_sum_1=True)
    assert any(f["check"] == "negative_weight" for f in findings)


def test_detects_dominant_feature_and_unused_feature():
    findings = ws.static_checks("X", {"a": 0.8, "b": 0.2, "c": 0.0},
                                require_sum_1=True)
    assert any(f["check"] == "single_feature_dominance" for f in findings)
    assert any(f["check"] == "unused_feature" for f in findings)


def test_detects_threshold_cliff():
    findings = ws.static_checks(
        "X", {"a": 0.5, "b": 0.5}, require_sum_1=True,
        thresholds={"fcs_min": 0.70},
        neutral_features={"a": 0.7, "b": 0.7},  # neutral score 0.70 == cliff
    )
    assert any(f["check"] == "threshold_cliff" for f in findings)


def test_correlated_duplicates_flagged_and_small_sample_skipped():
    rng = random.Random(1)
    samples = []
    for _ in range(50):
        x = rng.random()
        samples.append({"a": x, "b": x * 0.999 + 0.0005, "c": rng.random()})
    findings = ws.correlated_duplicates(samples)
    assert any("a vs b" in f["detail"] for f in findings)
    assert not any("c" in f["detail"] for f in findings if "vs" in f["detail"])
    skipped = ws.correlated_duplicates(samples[:5])
    assert any("skipped" in f["detail"] for f in skipped)


def test_production_inventory_has_no_severe_findings():
    result = ws.run_sanity()
    assert result["severe_count"] == 0, result["findings"]
    assert set(result["weight_sets"]) >= {"FCS_WEIGHTS", "ERS_WEIGHTS"}


# ---------------------------------------------------------------------------
# Constrained fitting — refusals and honesty
# ---------------------------------------------------------------------------


def _fit_samples(n, keys=("a", "b"), good="a"):
    rng = random.Random(7)
    rows = []
    for i in range(n):
        feats = {k: rng.random() for k in keys}
        # outcome correlates with the 'good' feature only
        rows.append({"features": feats,
                     "net_return": (feats[good] - 0.45) * 0.05 + rng.uniform(-0.005, 0.005)})
    return rows


def test_fit_refuses_insufficient_data():
    result = ws.constrained_fit(_fit_samples(30), {"a": 0.5, "b": 0.5})
    assert result["status"] == ws.INSUFFICIENT_DATA_FOR_FIT
    assert "no fit attempted" in result["note"]


def test_constrained_fit_respects_bounds_and_reports_test_split():
    result = ws.constrained_fit(
        _fit_samples(200), {"a": 0.5, "b": 0.5}, w_max=0.7, max_turnover=0.4,
    )
    assert result["status"] in ("candidate", "rejected_oos")
    w = result["w_candidate"]
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert all(0.0 <= v <= 0.7 + 1e-9 for v in w.values())
    assert result["turnover"] <= 0.4 + 1e-9
    # Test-split honesty: utilities for BOTH old and new reported.
    assert "utility_test_old" in result and "utility_test_new" in result
    assert result["splits"]["test"] > 0
    assert "optimized" not in str(result).lower()  # the word is banned
    if result["status"] == "candidate":
        assert result["utility_test_new"] > result["utility_test_old"]


def test_fit_never_labels_without_oos_win():
    # Random outcomes: candidate should usually fail OOS; whatever happens,
    # the label must match the test-split comparison.
    rng = random.Random(3)
    rows = [{"features": {"a": rng.random(), "b": rng.random()},
             "net_return": rng.uniform(-0.01, 0.01)} for _ in range(150)]
    result = ws.constrained_fit(rows, {"a": 0.5, "b": 0.5})
    if result["utility_test_new"] <= result["utility_test_old"]:
        assert result["status"] == "rejected_oos"


def test_sanity_report_written(tmp_path):
    md, js = ws.write_report(ws.run_sanity(), out_dir=tmp_path)
    assert md.exists() and js.exists()
    text = md.read_text(encoding="utf-8")
    assert "hand-set priors" in text and "Advisory-only" in text


# ---------------------------------------------------------------------------
# Score-change explainer
# ---------------------------------------------------------------------------


def _snap(weights, features, **kw):
    return {"weights": weights, "features": features, **kw}


def test_linear_decomposition_is_exact():
    s1 = _snap({"a": 0.6, "b": 0.4}, {"a": 0.5, "b": 0.5})
    s2 = _snap({"a": 0.5, "b": 0.5}, {"a": 0.9, "b": 0.4})
    d = ex.linear_decomposition(s1, s2)
    total = (sum(d["feature_contributions"].values())
             + sum(d["weight_contributions"].values())
             + sum(d["interaction_terms"].values()))
    assert total == pytest.approx(d["delta"])
    # Known parts: feature term a: 0.6*(0.9-0.5)=0.24
    assert d["feature_contributions"]["a"] == pytest.approx(0.24)
    assert d["weight_contributions"]["a"] == pytest.approx(0.5 * -0.1)


def test_nonlinear_model_emits_approximation_warning():
    def score_fn(f):
        return f["a"] ** 2 + f["a"] * f["b"]

    s1 = _snap({"a": 1.0, "b": 1.0}, {"a": 0.5, "b": 0.5})
    s2 = _snap({"a": 1.0, "b": 1.0}, {"a": 0.8, "b": 0.9})
    result = ex.explain(s1, s2, score_fn=score_fn)
    d = result["decomposition"]
    assert d["mode"] == "approximate_ablation"
    assert "APPROXIMATION" in d["warning"]
    assert "residual_interaction" in d


def test_manual_edit_highlighted_and_recommendation_change():
    s1 = _snap({"a": 1.0}, {"a": 0.5})
    s2 = _snap({"a": 1.0}, {"a": 0.9}, manual_edits=["a"])
    result = ex.explain(s1, s2)
    assert "manual_edit" in result["flags"]
    assert any("MANUAL EDIT" in c for c in result["causes"])
    assert result["recommendation_changed"] is True
    assert result["recommendation_t2"] == "ACT_CANDIDATE"


def test_stale_evidence_cannot_be_described_as_fresh():
    s1 = _snap({"a": 1.0}, {"a": 0.5},
               evidence=[{"evidence_id": "E1", "freshness_days": 1.0}])
    s2 = _snap({"a": 1.0}, {"a": 0.5},
               evidence=[{"evidence_id": "E1", "freshness_days": 30.0}])
    result = ex.explain(s1, s2)
    assert "staleness_driven" in result["flags"]
    assert result["reliability_direction"] == "less_reliable"


def test_score_movement_without_evidence_is_flagged():
    s1 = _snap({"a": 1.0}, {"a": 0.5}, evidence=[])
    s2 = _snap({"a": 1.0}, {"a": 0.8}, evidence=[])
    result = ex.explain(s1, s2)
    assert "score_moved_without_evidence_change" in result["flags"]
    assert result["reliability_direction"] == "less_reliable"


def test_fresh_evidence_raises_reliability():
    s1 = _snap({"a": 1.0}, {"a": 0.5}, evidence=[])
    s2 = _snap({"a": 1.0}, {"a": 0.7},
               evidence=[{"evidence_id": "E9", "freshness_days": 0.5}])
    result = ex.explain(s1, s2)
    assert result["reliability_direction"] == "more_reliable"


def test_explanation_written(tmp_path):
    s1 = _snap({"a": 1.0}, {"a": 0.5})
    s2 = _snap({"a": 1.0}, {"a": 0.7},
               evidence=[{"evidence_id": "E9", "freshness_days": 0.5}])
    path = ex.write_explanation(ex.explain(s1, s2), "ACME", out_dir=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "Why did ACME move?" in text
    assert "advisory-only" in text and "human review required" in text
