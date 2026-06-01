"""Thresholds for the Discovery / Execution / Survival three-lane mode model.

Single accessor so the mode-state gates, why-today tiers, BUY_SCORE
composition, phantom set, and exit-debt logic all read the SAME numbers.
Values come from ``config/thresholds.yaml`` under the ``discovery_execution``
key; if the file or key is missing (or a key is the wrong type) we fall back to
the spec defaults below rather than fabricating or crashing.

These are ADVISORY thresholds only. They gate the discovery-surface labelling
and the *execution permission* flag; they NEVER authorize execution. The
execution gate stays LOCKED and human execution is always required.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.runtime_common import REPO_ROOT
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from runtime_common import REPO_ROOT


DEFAULTS: dict[str, Any] = {
    "min_holdings_price_coverage_for_execution": 0.80,
    "min_candidate_price_coverage_for_execution": 0.80,
    "non_executable_price_sources": [
        "STATIC_FALLBACK",
        "STATIC_UNIVERSE_FALLBACK",
        "UNVERIFIED",
        "MOCK_ONLY",
        "UNKNOWN",
    ],
    "why_today_noise_max": 0.40,
    "why_today_discovery_min": 0.55,
    "why_today_watchlist_min": 0.65,
    "why_today_probe_min": 0.73,
    "why_today_buy_min": 0.80,
    "buy_score_discovery_min": 0.55,
    "buy_score_watchlist_min": 0.65,
    "buy_score_probe_min": 0.73,
    "buy_score_buy_min": 0.80,
    "buy_score_weights": {
        "why_today_score": 0.30,
        "price_confirmation": 0.25,
        "source_quality": 0.20,
        "cross_model_agreement": 0.15,
        "portfolio_fit": 0.10,
    },
    "probe_price_confirmation_min": 0.60,
    "probe_volume_confirmation_min": 0.50,
    "probe_source_quality_min": 0.60,
    "buy_price_confirmation_min": 0.70,
    "buy_volume_confirmation_min": 0.60,
    "buy_source_quality_min": 0.70,
    "buy_portfolio_fit_min": 0.60,
    "exit_debt_d_max": 5,
    "default_phantom_tickers": ["GLD", "UNG", "TIP", "TLT", "FCG", "ZIM"],
    "open_like_states": [
        "OPEN",
        "OPEN_RECONCILED",
        "OPEN_LIKE",
        "EXIT_PENDING",
        "PARTIAL",
        "HOLD",
    ],
    "closed_states": [
        "CLOSED",
        "STOP_CLOSED",
        "CLOSE_TRADE_SYNCED",
        "CLOSED_RECONCILED",
        "SOLD",
        "EXITED",
    ],
}

_THRESHOLDS_PATH = REPO_ROOT / "config" / "thresholds.yaml"


def load_discovery_execution_config() -> dict[str, Any]:
    """Return the discovery_execution config merged over the spec defaults.

    Defaults are canonical. A YAML value overrides a default only when it has a
    compatible type (so a degraded YAML fallback parser that mangles list/dict
    values can never corrupt the phantom set or the BUY_SCORE weights).
    """
    merged: dict[str, Any] = dict(DEFAULTS)
    # Deep-copy the container defaults so callers cannot mutate module state.
    merged["buy_score_weights"] = dict(DEFAULTS["buy_score_weights"])
    merged["default_phantom_tickers"] = list(DEFAULTS["default_phantom_tickers"])
    merged["non_executable_price_sources"] = list(DEFAULTS["non_executable_price_sources"])
    merged["open_like_states"] = list(DEFAULTS["open_like_states"])
    merged["closed_states"] = list(DEFAULTS["closed_states"])

    try:
        from src.utils.config_loader import load_yaml_config

        config = load_yaml_config(_THRESHOLDS_PATH)
    except Exception:
        return merged
    block = config.get("discovery_execution") if isinstance(config, dict) else None
    if not isinstance(block, dict):
        return merged

    for key, value in block.items():
        default = DEFAULTS.get(key)
        if isinstance(default, dict):
            if isinstance(value, dict):
                merged_block = dict(default)
                merged_block.update(value)
                merged[key] = merged_block
        elif isinstance(default, list):
            if isinstance(value, list) and value:
                merged[key] = list(value)
        else:
            merged[key] = value
    return merged


__all__ = ["DEFAULTS", "load_discovery_execution_config"]
