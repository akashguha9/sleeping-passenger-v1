"""MFE / MAE entry-quality analysis (advisory-only, long-only).

Win rate alone hides whether a loss was a bad *discovery* or a bad *exit*.
Maximum Favorable Excursion (MFE) and Maximum Adverse Excursion (MAE) let the
review separate thesis quality from timing/exit quality.

When only a current live price is known, provisional MFE/MAE are derived from
the current return; once intraday high/low history is available, the true
excursions are used.

Diagnoses::

    abs(current_return) < 0.01 and age < 5  -> PENDING_HORIZON  (too young)
    MFE >= 0.08 and final_pl < 0            -> GOOD_DISCOVERY_BAD_EXIT
    MAE <= -0.04 and final_pl > 0           -> GOOD_THESIS_POOR_ENTRY_TIMING
    MFE < 0.02 and MAE <= -0.04             -> BAD_DISCOVERY_OR_BAD_ENTRY
    MFE >= 0.05 and MAE > -0.02             -> GOOD_DISCOVERY_GOOD_ENTRY
    otherwise                               -> INCONCLUSIVE

Contract — pure module: no DB, no network, no broker calls, no AI execution.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import sys

    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

PENDING_HORIZON = "PENDING_HORIZON"
GOOD_DISCOVERY_BAD_EXIT = "GOOD_DISCOVERY_BAD_EXIT"
GOOD_THESIS_POOR_ENTRY_TIMING = "GOOD_THESIS_POOR_ENTRY_TIMING"
BAD_DISCOVERY_OR_BAD_ENTRY = "BAD_DISCOVERY_OR_BAD_ENTRY"
GOOD_DISCOVERY_GOOD_ENTRY = "GOOD_DISCOVERY_GOOD_ENTRY"
INCONCLUSIVE = "INCONCLUSIVE"


def compute_excursions(
    entry: float,
    *,
    live: float | None = None,
    high_since_entry: float | None = None,
    low_since_entry: float | None = None,
) -> dict[str, Any]:
    """Return current return + provisional/true MFE & MAE (long-only)."""
    if not entry:
        return {"current_return": None, "mfe": None, "mae": None, "provisional": True}

    current_return = (live - entry) / entry if live is not None else None

    if high_since_entry is not None and low_since_entry is not None:
        mfe = (high_since_entry - entry) / entry
        mae = (low_since_entry - entry) / entry
        provisional = False
    elif current_return is not None:
        mfe = max(0.0, current_return)
        mae = min(0.0, current_return)
        provisional = True
    else:
        mfe = mae = None
        provisional = True

    return {
        "current_return": round(current_return, 6) if current_return is not None else None,
        "mfe": round(mfe, 6) if mfe is not None else None,
        "mae": round(mae, 6) if mae is not None else None,
        "provisional": provisional,
    }


def diagnose(
    *,
    mfe: float | None,
    mae: float | None,
    final_pl: float | None,
    current_return: float | None,
    age_trading_days: int | None,
) -> str:
    """Entry-quality diagnosis from excursions + final P/L + age."""
    if (
        current_return is not None
        and abs(current_return) < 0.01
        and age_trading_days is not None
        and age_trading_days < 5
    ):
        return PENDING_HORIZON
    if mfe is None or mae is None:
        return PENDING_HORIZON
    if mfe >= 0.08 and final_pl is not None and final_pl < 0:
        return GOOD_DISCOVERY_BAD_EXIT
    if mae <= -0.04 and final_pl is not None and final_pl > 0:
        return GOOD_THESIS_POOR_ENTRY_TIMING
    if mfe < 0.02 and mae <= -0.04:
        return BAD_DISCOVERY_OR_BAD_ENTRY
    if mfe >= 0.05 and mae > -0.02:
        return GOOD_DISCOVERY_GOOD_ENTRY
    return INCONCLUSIVE


def analyze(
    entry: float,
    *,
    live: float | None = None,
    high_since_entry: float | None = None,
    low_since_entry: float | None = None,
    final_pl: float | None = None,
    age_trading_days: int | None = None,
) -> dict[str, Any]:
    """Full advisory MFE/MAE analysis for one long position."""
    ex = compute_excursions(
        entry, live=live, high_since_entry=high_since_entry, low_since_entry=low_since_entry
    )
    diagnosis = diagnose(
        mfe=ex["mfe"],
        mae=ex["mae"],
        final_pl=final_pl,
        current_return=ex["current_return"],
        age_trading_days=age_trading_days,
    )
    out = {**ex, "diagnosis": diagnosis}
    out.update(advisory_safety_stamps())
    out["human_execution_required"] = True
    return out


__all__ = [
    "PENDING_HORIZON",
    "GOOD_DISCOVERY_BAD_EXIT",
    "GOOD_THESIS_POOR_ENTRY_TIMING",
    "BAD_DISCOVERY_OR_BAD_ENTRY",
    "GOOD_DISCOVERY_GOOD_ENTRY",
    "INCONCLUSIVE",
    "compute_excursions",
    "diagnose",
    "analyze",
]
