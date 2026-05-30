"""Phase 3 — Moltbook read-back penalty is wired into the live scoring path.

Proves prior bad-process / loss patterns actually down-weight a NEW candidate's
advisory probability inside ``run_live_decision_path`` (not just in the
moltbook_adjustment unit tests), can downgrade CANDIDATE -> WATCHLIST, run
before the admission gate, and can never unlock execution.
"""
from __future__ import annotations

from scripts.live_decision_path import run_live_decision_path
from scripts.moltbook_adjustment import compute_pattern_signature

# Strong axes so the base probability is comfortably above 0.5; the Moltbook
# penalty is what we want to observe pulling it down.
_AXES = {"EMS": 0.9, "EQS": 0.9, "DS": 0.9, "LS": 0.9, "EFS": 0.9, "APS": 0.9}

_PATTERN = dict(
    country="India",
    signal_class="momentum",
    sector="energy",
    market_regime="risk_on",
    source_mix=["yfinance"],
)


def _bad_entries(n: int):
    """n Moltbook entries matching the candidate pattern, all bad outcomes."""
    rows = []
    for i in range(n):
        rows.append(
            {
                "country": "India",
                "signal_class": "momentum",
                "sector": "energy",
                "market_regime": "risk_on",
                "source_mix": ["yfinance"],
                "outcome_quality": "STOP_LOSS_HIT",
                "entry_id": f"MB{i}",
            }
        )
    return rows


def _kwargs(**overrides):
    base = dict(
        signal_id="SIG_MB",
        axes=_AXES,
        ticker="RELIANCE.NS",
        prediction_horizon_days=3.0,
        api_health_status="OK",
        rows_added=5,
        canonical_age_hours=1.0,
        state="HURACAN",
        chaos_risk=0.1,
        capital=1_000_000.0,
        cash_available=900_000.0,
        entry_price=100.0,
        hard_stop_price=98.0,
        db_path=None,
    )
    base.update(_PATTERN)
    base.update(overrides)
    return base


def test_prior_bad_moltbook_pattern_reduces_live_candidate_probability():
    clean = run_live_decision_path(**_kwargs(moltbook_entries=[]))
    penalised = run_live_decision_path(**_kwargs(moltbook_entries=_bad_entries(5)))
    assert penalised["moltbook"]["moltbook_adjustment_applied"] is True
    assert penalised["p_after_moltbook"] < clean["p_after_moltbook"]
    # p_after_moltbook never exceeds p_base — penalty only lowers.
    assert penalised["p_after_moltbook"] <= penalised["p_base"]


def test_prior_bad_pattern_can_downgrade_candidate_to_watchlist():
    out = run_live_decision_path(**_kwargs(moltbook_entries=_bad_entries(8)))
    # Penalty exceeds the downgrade threshold -> WATCHLIST, not CANDIDATE.
    assert out["moltbook"]["moltbook_penalty"] >= 0.05
    assert out["final_advisory_class"] == "WATCHLIST"
    assert out["moltbook_downgraded"] is True


def test_no_matching_moltbook_history_penalty_zero_in_live_path():
    out = run_live_decision_path(**_kwargs(moltbook_entries=[]))
    assert out["moltbook"]["moltbook_penalty"] == 0.0
    assert out["moltbook"]["reason"] == "NO_MATCHING_MOLTBOOK_HISTORY"
    assert out["moltbook"]["moltbook_adjustment_applied"] is False


def test_moltbook_metadata_present_in_live_advisory_output():
    out = run_live_decision_path(**_kwargs(moltbook_entries=_bad_entries(5)))
    mb = out["moltbook"]
    for key in (
        "p_base", "p_adj", "moltbook_penalty", "moltbook_pattern_n",
        "moltbook_bad_rate", "moltbook_adjustment_applied",
    ):
        assert key in mb


def test_moltbook_penalty_cannot_unlock_execution():
    out = run_live_decision_path(**_kwargs(moltbook_entries=_bad_entries(20)))
    assert out["moltbook"]["moltbook_can_unlock_execution"] is False
    assert out["execution_gate"] == "LOCKED"
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0


def test_moltbook_adjustment_runs_before_admission_gates():
    # The downgrade only happens if Moltbook is applied BEFORE the final
    # class is resolved; a WATCHLIST result on a candidate that otherwise
    # clears every gate proves ordering.
    out = run_live_decision_path(**_kwargs(moltbook_entries=_bad_entries(8)))
    assert out["gate_result"]["gate_passed"] is True  # gates themselves pass
    assert out["final_advisory_class"] == "WATCHLIST"  # but moltbook downgraded


def test_logged_stop_loss_affects_future_same_pattern_candidate():
    # Same pattern signature -> the loss history bites; a different pattern is
    # immune (signature mismatch).
    sig_same = compute_pattern_signature(**{
        "country": "India", "signal_class": "momentum", "sector": "energy",
        "market_regime": "risk_on", "source_mix": ["yfinance"],
    })
    same = run_live_decision_path(**_kwargs(moltbook_entries=_bad_entries(5)))
    other = run_live_decision_path(
        **_kwargs(country="USA", moltbook_entries=_bad_entries(5))
    )
    assert same["moltbook"]["moltbook_penalty"] > 0.0
    assert other["moltbook"]["moltbook_penalty"] == 0.0
    assert sig_same  # signature is deterministic/non-empty
