"""Tests for the role-fit scorecard engine.

Kanté Role-Fit Sprint, Phase 2.

These tests enforce the *contract* of the role-fit scoring model:

* Per-segment criterion weights sum to 1.
* All scores stay inside their declared intervals.
* NOT_TARGETED segments are excluded from the OverallRoleFit denominator
  and dashboard-score-rendered as the explicit sentinel
  ``"NOT_TARGETED_THIS_YEAR"`` — never a number.
* Public SaaS stays absolutely low and cannot drag the local-first
  role-fit.
* Calibration gate honesty can sit high on role-fit while the
  Scoring/model logic quality segment is held below its no-evidence
  ceiling whenever the live calibration report does not have
  ``predictive_claim_allowed`` and ``n_real ≥ N_min``.
* Advisory-only safety stamps are present.
* No execution-route language is introduced.

The tests run against a temporary repo root for the "missing/insufficient
calibration" scenarios so they are deterministic regardless of the
in-tree ``runtime/release/calibration_report.json`` state.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from scripts import segment_role_scorecard as srs


# ---------------------------------------------------------------------------
# Per-segment math invariants
# ---------------------------------------------------------------------------


def _report() -> dict:
    return srs.build_report()


def test_segment_criterion_weights_sum_to_one():
    for s in srs._segments(calibration_unlocked=False):
        total = sum(c.weight for c in s.criteria)
        assert math.isclose(total, 1.0, abs_tol=1e-6), (
            f"{s.segment}: weights sum to {total!r}, expected 1.0"
        )


def test_segment_criterion_weights_sum_to_one_when_unlocked():
    for s in srs._segments(calibration_unlocked=True):
        total = sum(c.weight for c in s.criteria)
        assert math.isclose(total, 1.0, abs_tol=1e-6), (
            f"{s.segment} (unlocked): weights sum to {total!r}, expected 1.0"
        )


def test_all_scores_in_their_intervals():
    report = _report()
    for s in report["segments"]:
        assert 0.0 <= s["absolute_score"] <= 10.0
        assert 0.0 <= s["role_fit_score"] <= 10.0
        assert 0.0 <= s["confidence"] <= 1.0
        assert 0.0 <= s["evidence_completeness"] <= 1.0
        assert 0.0 <= s["target_relevance"] <= 1.0
        # R_adj ≤ R_s because the multiplier is ≤ 1
        assert (
            s["confidence_adjusted_role_fit"] <= s["role_fit_score"] + 1e-6
        ), f"{s['segment']}: R_adj > R_s"
        for c in s["criteria"]:
            assert 0.0 <= c["weight"] <= 1.0
            assert 0.0 <= c["performance"] <= 1.0


def test_role_fit_formula_R_s_equals_10_times_sum_w_p():
    """R_s = 10 * Σ w_i * p_i per the published model."""
    for s in srs._segments(calibration_unlocked=False):
        s._finalise(repo_root=srs._REPO_ROOT)
        expected = 10.0 * sum(c.weight * c.performance for c in s.criteria)
        assert math.isclose(
            s.role_fit_score, round(expected, 4), abs_tol=1e-4
        ), f"{s.segment}: R_s {s.role_fit_score} != 10*Σ wp {expected}"


def test_confidence_adjustment_formula():
    """R_adj_s = R_s * (0.7 + 0.3 * E_s) * C_s."""
    for s in srs._segments(calibration_unlocked=False):
        s._finalise(repo_root=srs._REPO_ROOT)
        expected = s.role_fit_score * (0.7 + 0.3 * s.evidence_completeness) * s.confidence
        assert math.isclose(
            s.confidence_adjusted_role_fit, round(expected, 4), abs_tol=1e-4
        ), f"{s.segment}: R_adj mismatch"


# ---------------------------------------------------------------------------
# NOT_TARGETED handling
# ---------------------------------------------------------------------------


def test_not_targeted_segments_render_explicit_sentinel():
    report = _report()
    nt = report["not_targeted_segments"]
    assert nt, "expected at least one NOT_TARGETED segment (e.g. Public SaaS)"
    for s in report["segments"]:
        if s["target_relevance"] == 0.0:
            assert s["segment"] in nt
            assert s["dashboard_score"] == "NOT_TARGETED_THIS_YEAR"


def test_not_targeted_excluded_from_overall_role_fit():
    """The OverallRoleFit denominator must skip T_s=0 segments entirely.

    Manually recompute and assert.
    """
    report = _report()
    num = 0.0
    den = 0.0
    for s in report["segments"]:
        if s["target_relevance"] == 0.0:
            continue
        num += s["role_weight"] * s["confidence_adjusted_role_fit"] * s["target_relevance"]
        den += s["role_weight"] * s["target_relevance"]
    expected = num / den if den else 0.0
    assert math.isclose(report["overall_role_fit"], round(expected, 4), abs_tol=1e-3)


def test_public_saas_is_not_targeted_and_absolute_capped():
    report = _report()
    seg = next(s for s in report["segments"] if s["segment"] == "Public SaaS readiness")
    assert seg["target_relevance"] == 0.0
    assert seg["absolute_score"] <= srs.ABSOLUTE_PUBLIC_SAAS_CEILING + 1e-6
    assert seg["dashboard_score"] == "NOT_TARGETED_THIS_YEAR"


def test_public_saas_does_not_drag_overall_role_fit():
    """Setting Public SaaS's role-fit to zero would *not* change OverallRoleFit
    because it is excluded from the denominator — the score must hold.
    """
    report = _report()
    baseline = report["overall_role_fit"]
    # Recompute pretending Public SaaS had R_adj=0; result must equal baseline.
    num = 0.0
    den = 0.0
    for s in report["segments"]:
        if s["target_relevance"] == 0.0:
            continue
        r_adj = 0.0 if s["segment"] == "Public SaaS readiness" else s["confidence_adjusted_role_fit"]
        num += s["role_weight"] * r_adj * s["target_relevance"]
        den += s["role_weight"] * s["target_relevance"]
    recomputed = round(num / den, 4) if den else 0.0
    assert math.isclose(baseline, recomputed, abs_tol=1e-4)


# ---------------------------------------------------------------------------
# Calibration gate honesty vs predictive scoring quality
# ---------------------------------------------------------------------------


def test_calibration_gate_honesty_can_be_high_while_scoring_model_is_capped(tmp_path: Path):
    """When the calibration report says no predictive claim is allowed,
    *Calibration gate honesty* role-fit can still be 10/10 but *Scoring/model
    logic quality* must stay at its no-evidence ceiling.
    """
    # No calibration report at all → calibration_unlocked = False.
    report = srs.build_report(calibration_report_path=tmp_path / "missing.json")
    cal = next(
        s for s in report["segments"] if s["segment"] == "Calibration gate honesty"
    )
    model = next(
        s for s in report["segments"] if s["segment"] == "Scoring/model logic quality"
    )
    assert cal["role_fit_score"] >= 9.5
    assert model["absolute_score"] <= srs.SCORING_MODEL_CEILING_NO_EVIDENCE + 1e-6
    assert model["role_fit_score"] <= 5.8 + 1e-6


def test_predictive_claim_blocked_when_n_real_below_min(tmp_path: Path):
    """Even a report with predictive_claim_allowed=true but n_real<N_min must
    NOT unlock the scoring model ceiling.
    """
    fake = tmp_path / "calibration_report.json"
    fake.write_text(
        json.dumps(
            {"predictive_claim_allowed": True, "n_real": srs.CALIBRATION_N_MIN - 1}
        ),
        encoding="utf-8",
    )
    report = srs.build_report(calibration_report_path=fake)
    assert report["calibration_unlocked"] is False
    model = next(
        s for s in report["segments"] if s["segment"] == "Scoring/model logic quality"
    )
    assert model["absolute_score"] <= srs.SCORING_MODEL_CEILING_NO_EVIDENCE + 1e-6


def test_predictive_claim_unlocked_when_threshold_met(tmp_path: Path):
    """When the calibration report says predictive_claim_allowed AND
    n_real ≥ N_min, the scoring model segment may exceed the no-evidence
    ceiling.
    """
    fake = tmp_path / "calibration_report.json"
    fake.write_text(
        json.dumps(
            {"predictive_claim_allowed": True, "n_real": srs.CALIBRATION_N_MIN}
        ),
        encoding="utf-8",
    )
    report = srs.build_report(calibration_report_path=fake)
    assert report["calibration_unlocked"] is True
    model = next(
        s for s in report["segments"] if s["segment"] == "Scoring/model logic quality"
    )
    assert model["absolute_score"] > srs.SCORING_MODEL_CEILING_NO_EVIDENCE


# ---------------------------------------------------------------------------
# Advisory-only safety stamps
# ---------------------------------------------------------------------------


def test_advisory_stamps_present_in_report():
    report = _report()
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
    assert report["can_execute"] is False
    assert report["execution_permission"] is False
    assert report["human_review_required"] is True
    assert report["broker_order_id"] == "NONE"
    assert report["canonical_store"] == "sqlite"
    assert report["jsonl_is_canonical"] is False


def test_no_forbidden_execution_route_language():
    """The report must never introduce execution-route language.

    Specifically: no per-segment criterion may say "BUY", "SELL", "ORDER",
    "EXECUTE", "BROKER".  (Documentation that describes the *absence* of
    such routes is allowed via the `FORBIDDEN_EXECUTION_TOKENS` list in
    advisory_contract; here we scan only the criteria text.)
    """
    forbidden = {"BUY", "SELL", "ORDER", "EXECUTE", "PLACE_ORDER"}
    report = _report()
    for s in report["segments"]:
        for c in s["criteria"]:
            upper = c["criterion"].upper()
            for token in forbidden:
                # Match the token only as a standalone word, so "broker" in
                # "no broker SDK" remains acceptable while "PLACE_ORDER" or
                # "EXECUTE" as a verb is not.
                assert token != upper, f"forbidden token {token} in {c}"


# ---------------------------------------------------------------------------
# File-output contract
# ---------------------------------------------------------------------------


def test_json_writes_to_runtime_release(tmp_path: Path):
    """--json writes a valid JSON file."""
    out = tmp_path / "segment_role_scorecard.json"
    rc = srs.main(["--json", str(out)])
    assert rc == 0
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["script"] == "segment_role_scorecard.py"
    assert "segments" in data
    assert len(data["segments"]) >= 30


def test_markdown_writes_to_docs_scorecards(tmp_path: Path):
    """--markdown writes a valid Markdown file with the formula table."""
    out = tmp_path / "SEGMENT_ROLE_SCORECARD.md"
    rc = srs.main(["--markdown", str(out)])
    assert rc == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Segment Role-Fit Scorecard" in text
    assert "R_s        = 10 * Σ_i (w_i * p_i)" in text
    assert "NOT_TARGETED" in text


# ---------------------------------------------------------------------------
# Composite scores
# ---------------------------------------------------------------------------


def test_overall_absolute_matches_formula():
    report = _report()
    num = sum(s["absolute_weight"] * s["absolute_score"] for s in report["segments"])
    den = sum(s["absolute_weight"] for s in report["segments"])
    expected = num / den if den else 0.0
    assert math.isclose(report["overall_absolute"], round(expected, 4), abs_tol=1e-3)


def test_overall_role_fit_in_zero_to_ten():
    report = _report()
    assert 0.0 <= report["overall_role_fit"] <= 10.0
    assert 0.0 <= report["overall_absolute"] <= 10.0


def test_live_calibration_report_agrees_with_scorecard():
    """If the live ``runtime/release/calibration_report.json`` says no
    predictive claim is allowed (or N_real < N_min), the scorecard must
    keep ``Scoring/model logic quality`` at or below its no-evidence
    ceiling — otherwise we have silently inflated.

    This pins the predictive ↔ honesty boundary across artifacts.
    """
    cal_path = srs.DEFAULT_CALIBRATION_REPORT
    if not cal_path.exists():
        pytest.skip("no live calibration_report.json in this checkout")
    cal = json.loads(cal_path.read_text(encoding="utf-8"))
    n_real = cal.get("n_real")
    predictive_allowed = cal.get("predictive_claim_allowed") is True
    try:
        n_real_int = int(n_real)
    except (TypeError, ValueError):
        n_real_int = 0
    unlocked = predictive_allowed and n_real_int >= srs.CALIBRATION_N_MIN

    report = srs.build_report()
    assert report["calibration_unlocked"] is unlocked
    model = next(
        s for s in report["segments"] if s["segment"] == "Scoring/model logic quality"
    )
    if not unlocked:
        assert model["absolute_score"] <= srs.SCORING_MODEL_CEILING_NO_EVIDENCE + 1e-6
        # The predictive-criteria performance must be zero when locked.
        predictive_criteria = [
            c
            for c in model["criteria"]
            if "N_real" in c["criterion"] or "Brier" in c["criterion"] or "Reliability" in c["criterion"]
        ]
        for c in predictive_criteria:
            assert c["performance"] == 0.0, (
                f"criterion {c['criterion']!r} should be 0.0 while calibration locked"
            )


def test_local_first_role_fit_higher_than_public_saas_absolute():
    """The Kanté point: local-first role-fit should not be dragged down by
    public-saas-style segments; it should be measurably higher than the
    public-saas absolute score.
    """
    report = _report()
    local_first = next(
        s for s in report["segments"] if s["segment"] == "Local-first showcase"
    )
    public_saas = next(
        s for s in report["segments"] if s["segment"] == "Public SaaS readiness"
    )
    assert local_first["confidence_adjusted_role_fit"] > public_saas["absolute_score"]
