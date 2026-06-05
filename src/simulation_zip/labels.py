"""Immutable provenance / safety labels for zip-derived simulation data.

Every record, score, and report produced by this subsystem carries these
labels so a reader can never mistake a simulation-derived number for live
trading proof, broker data, or financial advice.
"""
from __future__ import annotations

from enum import Enum

# Subsystem identity + version.  The parser version is part of the provenance
# of every parsed record so re-runs are attributable to a code version.
SUBSYSTEM_NAME = "zip_simulation"
PARSER_VERSION = "1.0.0"


class Label(str, Enum):
    """Mandatory honesty labels attached to all outputs."""

    SIMULATION_ONLY = "SIMULATION_ONLY"
    ZIP_CORPUS_DERIVED = "ZIP_CORPUS_DERIVED"
    NOT_LIVE_TRADING_EVIDENCE = "NOT_LIVE_TRADING_EVIDENCE"
    NOT_BROKER_DATA = "NOT_BROKER_DATA"
    NOT_FINANCIAL_ADVICE = "NOT_FINANCIAL_ADVICE"


# The canonical label set, as plain strings, ready to embed in JSON.
SIMULATION_LABELS: tuple[str, ...] = tuple(label.value for label in Label)


def label_block() -> dict[str, object]:
    """Return the canonical label block embedded at the top of every report."""
    return {
        "labels": list(SIMULATION_LABELS),
        "subsystem": SUBSYSTEM_NAME,
        "parser_version": PARSER_VERSION,
        "disclaimer": (
            "All metrics here are SIMULATION / TRAINING / BENCHMARK derived "
            "from a local zip corpus. They are NOT live trading proof, NOT "
            "broker data, and NOT financial advice. Chess/hackathon/scraped "
            "data are not market data."
        ),
    }


__all__ = [
    "SUBSYSTEM_NAME",
    "PARSER_VERSION",
    "Label",
    "SIMULATION_LABELS",
    "label_block",
]
