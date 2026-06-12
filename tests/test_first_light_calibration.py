"""Empirical first-light proofs: the calibration ledger's first
non-synthetic rows — operator-attested journal records, imported as
recorded, with no fabricated prices, no invented benchmark, and no
verdict beyond what n=4 can support."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.import_outcomes import import_grouped, read_rows
from src.strategy.outcome_import import (
    audit_streak,
    streak_inputs_from_outcomes,
    summarize_gate_outcomes,
)

REPO = Path(__file__).resolve().parents[1]
FIRST_LIGHT = REPO / "examples" / "outcomes" / "first_light_empirical.jsonl"


@pytest.fixture(scope="module")
def first_light():
    return import_grouped(read_rows(FIRST_LIGHT))


def test_first_light_imports_at_empirical_tier(first_light) -> None:
    assert first_light["tiers_present"] == ["empirical"]
    summary = first_light["by_tier"]["empirical"]["summary"]
    assert summary["count"] == 4
    assert summary["rejected"] == 0
    assert summary["data_tier"] == "empirical"
    assert summary["status"] == "require_more_data"  # 4 < floor of 10
    assert summary["win_rate"] == pytest.approx(0.5)


def test_no_alpha_is_claimed_without_a_benchmark(first_light) -> None:
    report = first_light["_reports"]["empirical"]
    summary = first_light["by_tier"]["empirical"]["summary"]
    assert summary["mean_realized_alpha"] is None
    assert summary["rows_without_benchmark"] == 4
    # (1.23 + 4.19 - 4.49 - 8.67) / 4 = -1.935% mean absolute return.
    assert summary["mean_absolute_return"] == pytest.approx(-0.019350,
                                                            abs=1e-6)
    for outcome in report.imported:
        assert outcome.realized_alpha is None
        assert outcome.alpha_basis == "absolute_return_no_benchmark"
        assert outcome.return_basis == "recorded_return"
        assert any("no raw prices fabricated" in r
                   for r in outcome.rationale)
        assert outcome.source_record.startswith("moltbook/")


def test_gate_utility_is_honest_at_n_2(first_light) -> None:
    report = first_light["_reports"]["empirical"]
    gates = summarize_gate_outcomes(report.imported)["gates"]
    veto = gates["ce_threshold_veto"]
    # Both CHAOS overrides (UNG, FCG) lost: the veto would have avoided
    # both losses. Two counterfactuals are an anecdote, not a verdict.
    assert veto["helpful"] == 2
    assert veto["harmful"] == 0
    assert veto["pass_through"] == 2
    assert veto["verdict"] == "insufficient_data"
    assert veto["leaning"] == "helpful"
    assert "below the floor" in veto["note"]


def test_streak_audit_on_real_rows(first_light) -> None:
    report = first_light["_reports"]["empirical"]
    audit = audit_streak(
        streak_inputs_from_outcomes(report.imported),
        data_tier="empirical",
    )
    # Both wins carry the named CE-discipline mechanism; both losses
    # were tagless chaos overrides — reliability 1.0, but the sample
    # is tiny and the audit says so.
    assert audit.win_rate == pytest.approx(0.5)
    assert audit.streak_reliability == pytest.approx(1.0)
    assert "SMALL_SAMPLE" in audit.warnings
    assert audit.causal_confidence <= 0.5  # capped by the record itself


def test_unresolved_open_positions_cannot_enter_the_ledger() -> None:
    # The shape of moltbook/open_positions.json rows: an OPEN position
    # has a current_price, not a resolution. It must be rejected, never
    # silently treated as resolved.
    open_row = {
        "id": "ung_open", "ticker": "UNG", "entry_price": 16.0,
        "current_price": 12.5, "state": "OPEN",
        "data_tier": "empirical",
    }
    result = import_grouped([open_row])
    assert result["by_tier"] == {} or all(
        r["summary"]["count"] == 0 for r in result["by_tier"].values()
    )
    errors = (
        result["by_tier"].get("empirical", {}).get("errors")
        if result["by_tier"] else None
    )
    if errors is None:
        # Row grouped but rejected inside the tier report.
        assert True
    else:
        assert errors


def test_gate_summary_verdicts_at_and_above_the_floor() -> None:
    from src.strategy.outcome_import import ImportedOutcome

    def row(win: bool, fired=True, overridden=True):
        return ImportedOutcome(
            case_id="x", ticker="X", data_tier="empirical",
            holding_days=None, asset_return=0.01 if win else -0.01,
            benchmark_return=None, realized_alpha=None, win=win,
            predicted_edge=None, prediction_error=None,
            predicted_expiry_days=None, actual_resolution_days=None,
            expiry_accuracy=None, expired_before_resolution=None,
            gate_interaction={"gate": "g", "fired": fired,
                              "overridden": overridden},
        )

    helpful = summarize_gate_outcomes(
        [row(win=False)] * 3
    )["gates"]["g"]
    assert helpful["verdict"] == "helpful"

    harmful = summarize_gate_outcomes(
        [row(win=True)] * 3
    )["gates"]["g"]
    assert harmful["verdict"] == "harmful"

    neutral = summarize_gate_outcomes(
        [row(win=True), row(win=True), row(win=False), row(win=False)]
    )["gates"]["g"]
    assert neutral["verdict"] == "neutral"

    unobservable = summarize_gate_outcomes(
        [row(win=False, overridden=False)] * 5
    )["gates"]["g"]
    assert unobservable["observed_counterfactuals"] == 0
    assert unobservable["verdict"] == "insufficient_data"
