"""Model-evaluation honesty audit: overclaims fail, honest text passes.

Overclaim probes are assembled at runtime so the phrases never appear in
this source as bare claims (this file is also a declared guard file).
"""
from __future__ import annotations

from scripts import audit_model_evaluation_honesty as honesty


def _j(*parts: str) -> str:
    return "".join(parts)


def test_real_repo_has_no_overclaims():
    assert honesty.scan_repo() == []


def test_unqualified_overclaims_fail():
    for probe in (
        _j("This strategy is guar", "anteed to work."),
        _j("Our signals beat", " the market every year."),
        _j("The system is real-", "money ready today."),
        _j("Fully autono", "mous trading out of the box."),
        _j("This will make", " money in any regime."),
    ):
        assert honesty.scan_text(probe, "docs/PITCH.md"), probe


def test_negated_claims_pass():
    for line in (
        _j("This is not guar", "anteed and never will be."),
        _j("No autono", "mous trading exists anywhere in this repo."),
        _j("We make no claim that this beats", " the market."),
    ):
        assert honesty.scan_text(line, "docs/SAFETY.md") == [], line


def test_not_section_bullets_pass():
    text = _j(
        "## What this MVP is NOT\n\n",
        "- An autono", "mous trading system.\n",
        "- A guar", "anteed edge.\n",
    )
    assert honesty.scan_text(text, "docs/SAFETY.md") == []


def test_quoted_forbidden_vocabulary_passes():
    line = _j('The banned phrase "guar', 'anteed" must never appear.')
    assert honesty.scan_text(line, "docs/POLICY.md") == []


def test_risk_free_rate_term_of_art_passes():
    line = "- Risk-free rate per period: 0.0001"
    assert honesty.scan_text(line, "reports/backtest_template.md") == []


def test_bare_risk_free_claim_fails():
    line = _j("Returns are risk", "-free with our hedging.")
    assert honesty.scan_text(line, "docs/PITCH.md")


def test_code_identifiers_not_scanned():
    code = _j("REAL_MONEY_READY = ", '"gate_state"')
    assert honesty.scan_text(code, "scripts/readiness.py") == []


def test_test_files_exempt():
    probe = _j("banlist = ['guar", "anteed', 'risk-fr", "ee']")
    assert honesty.scan_text(probe, "tests/test_language.py") == []


# ---------------------------------------------------------------------------
# Evidence scorecard honesty
# ---------------------------------------------------------------------------


def test_evidence_scorecard_statuses_are_computed_not_asserted():
    card = honesty.build_evidence_scorecard()
    assert {e["status"] for e in card.values()} <= {
        "capability_present", "missing"
    }
    # Capabilities this repo actually has machinery + tests for:
    for present in ("backtest_availability", "walk_forward_validation",
                    "leakage_controls", "calibration_evidence",
                    "drawdown_reporting", "manual_review_requirement",
                    "advisory_only_disclaimer"):
        assert card[present]["status"] == "capability_present", present


def test_live_results_are_honestly_missing():
    """The line that keeps the repo honest: tooling is not validated alpha."""
    card = honesty.build_evidence_scorecard()
    assert card["live_out_of_sample_results"]["status"] == "missing"
    assert "NOT validated alpha" in card["live_out_of_sample_results"]["note"]


def test_scorecard_flips_to_missing_without_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(honesty, "_REPO_ROOT", tmp_path)
    card = honesty.build_evidence_scorecard()
    assert all(
        e["status"] == "missing" for e in card.values()
    ), "evidence must be probed from the tree, never hardcoded"
