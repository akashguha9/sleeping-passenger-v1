from __future__ import annotations

# SIGNAL_CONVERSION_MONITOR (SCM)
# Module: CAL - Calibration
# Added: April 16 2026
# Source: Railway campus / conversion failure session
#
# Meta-diagnostic: what fraction of the operator's identified edge is
# successfully converting into clean pipeline entries?
#
# SCM_rate = clean_SYSTEM_entries / total_signals_above_CE_threshold
#
# CEE detects overload (too much entering at once - April 4 CHAOS cluster).
# SCM detects conversion failure (too little entering cleanly - T=6 vs 9.57 arch).
# They are opposite failure modes. GSCE manages the balance between them.

import json
from pathlib import Path

from moltbook_loader import load_moltbook_bundle

SCM_HIGH_CONVERSION = 0.60
SCM_PARTIAL_CONVERSION = 0.30
SCM_LOW_CONVERSION = 0.10

DIAGNOSTIC_ROUTING_ORDER = [
    "GSCE_PHASE_LOCK",
    "CEE_OVERLOAD",
    "MTL_TIMING",
    "NAR_ARCHETYPE",
    "TAT_PRESSURE_STATE",
    "REALM_BIS",
]


def compute_scm_rate(clean_system_entries, total_signals_above_threshold):
    if total_signals_above_threshold == 0:
        return 0.0
    return clean_system_entries / total_signals_above_threshold


def classify_scm_state(scm_rate):
    if scm_rate >= SCM_HIGH_CONVERSION:
        return "HIGH_CONVERSION"
    elif scm_rate >= SCM_PARTIAL_CONVERSION:
        return "PARTIAL_CONVERSION"
    elif scm_rate >= SCM_LOW_CONVERSION:
        return "LOW_CONVERSION"
    else:
        return "CONVERSION_FAILURE"


def scm_diagnostic_route(scm_state, gate_states):
    if scm_state in ("HIGH_CONVERSION", "PARTIAL_CONVERSION"):
        return None
    blocking_gates = []
    for gate in DIAGNOSTIC_ROUTING_ORDER:
        if gate_states.get(gate, False):
            blocking_gates.append(gate)
    return blocking_gates if blocking_gates else ["UNKNOWN_BLOCKER"]


def scm_review(clean_entries, total_signals, gate_states):
    rate = compute_scm_rate(clean_entries, total_signals)
    state = classify_scm_state(rate)
    diagnosis = scm_diagnostic_route(state, gate_states)
    return {
        "scm_rate": round(rate, 3),
        "scm_state": state,
        "diagnosis": diagnosis,
        "gap_type": "CONVERSION_FRICTION" if state != "HIGH_CONVERSION" else "NONE",
    }


def derive_clean_entries_from_moltbook(moltbook_dir: Path | None = None) -> dict:
    bundle = load_moltbook_bundle(moltbook_dir)

    clean_entries = sum(
        1
        for item in bundle.trade_closes
        if item.get("classification") in {"GOOD_WIN", "MARGINAL_WIN"}
    )

    chaos_entries = sum(
        1
        for item in bundle.trade_closes
        if item.get("classification") == "CHAOS_LOSS"
    )

    return {
        "trade_close_count": len(bundle.trade_closes),
        "mw_signal_count": len(bundle.mw_signals),
        "clean_entries": clean_entries,
        "chaos_entries": chaos_entries,
        "tickers": sorted({item["ticker"] for item in bundle.trade_closes}),
    }


if __name__ == "__main__":
    moltbook_summary = derive_clean_entries_from_moltbook()

    total_signals_above_threshold = 12

    gate_states = {
        "GSCE_PHASE_LOCK": False,
        "CEE_OVERLOAD": False,
        "MTL_TIMING": False,
        "NAR_ARCHETYPE": False,
        "TAT_PRESSURE_STATE": False,
        "REALM_BIS": False,
    }

    review = scm_review(
        clean_entries=moltbook_summary["clean_entries"],
        total_signals=total_signals_above_threshold,
        gate_states=gate_states,
    )

    output = {
        "moltbook_summary": moltbook_summary,
        "scm_review": review,
        "note": "SCM now consumes live Moltbook close data for numerator; denominator still manual until signal ledger exists."
    }

    print(json.dumps(output, indent=2))
