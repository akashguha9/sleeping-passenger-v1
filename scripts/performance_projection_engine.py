from __future__ import annotations


def calculate_period_return(*, profit: float, starting_capital: float) -> float:
    if starting_capital <= 0:
        raise ValueError("starting_capital must be > 0")
    return float(profit) / float(starting_capital)


def calculate_annualized_return(*, period_return: float, period_weeks: float) -> dict:
    if period_weeks <= 0:
        raise ValueError("period_weeks must be > 0")
    annualized = (1.0 + float(period_return)) ** (52.0 / float(period_weeks)) - 1.0
    return {
        "annualized_return": annualized,
        "assumption_flags": [
            "projection_only",
            "requires_repeatability",
            "requires_no_blowups",
            "requires_stable_execution",
            "requires_comparable_regimes",
        ],
    }
