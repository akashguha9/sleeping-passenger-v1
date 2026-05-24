"""Thresholds for the daily discovery / executable gates.

Single accessor so the Fresh Market Discovery Gate, Candidate/Executable
split, Anti-staleness layer, and final synthesis all read the SAME numbers.
Values come from ``config/thresholds.yaml`` under the ``daily_discovery``
key; if the file or key is missing we fall back to the spec defaults rather
than fabricating or crashing.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.runtime_common import REPO_ROOT
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from runtime_common import REPO_ROOT


DEFAULTS: dict[str, Any] = {
    "cqs_min": 0.70,
    "acqs_min": 0.60,
    "eqs_min": 0.75,
    "fcs_min": 0.70,
    "ers_min": 0.75,
    "watchlist_fcs_min": 0.55,
    "source_health_min": 0.70,
    "why_today_min_for_executable": 0.70,
    "novelty_ratio_min": 0.30,
    "minimum_novelty_ratio": 0.30,
    "min_new_ticker_count": 10,
    "minimum_new_tickers": 10,
    "memory_decay_lambda": 0.25,
    "disagreement_low_max": 0.15,
    "disagreement_high_min": 0.35,
    "staleness_penalty": {
        "STALE_24H": 0.20,
        "STALE_48H": 0.35,
        "HISTORICAL_ONLY": 0.50,
    },
}

_THRESHOLDS_PATH = REPO_ROOT / "config" / "thresholds.yaml"


def load_discovery_thresholds() -> dict[str, Any]:
    """Return the daily_discovery thresholds merged over the spec defaults."""
    merged: dict[str, Any] = dict(DEFAULTS)
    merged["staleness_penalty"] = dict(DEFAULTS["staleness_penalty"])
    try:
        from src.utils.config_loader import load_yaml_config

        config = load_yaml_config(_THRESHOLDS_PATH)
    except Exception:
        return merged
    block = config.get("daily_discovery") if isinstance(config, dict) else None
    if not isinstance(block, dict):
        return merged
    for key, value in block.items():
        if key == "staleness_penalty" and isinstance(value, dict):
            merged["staleness_penalty"].update(value)
        else:
            merged[key] = value
    return merged


__all__ = ["DEFAULTS", "load_discovery_thresholds"]
