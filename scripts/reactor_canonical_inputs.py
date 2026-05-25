"""Canonical reactor inputs + routing score (Kanté Sprint 2 — Task 2).

The signal reactor / adaptive router decides *where attention should go*, never
*whether to execute*.  Before this module its routing inputs could be
caller-supplied proxies.  Here the routing score is computed from the
**canonical-SQLite-derived** complex-systems state produced by
:mod:`scripts.complex_systems_sqlite_bridge`, so adaptive routing reflects real
operator history (echoes, unrepaired losses, crowding) rather than a proxy.

Routing score (sprint contract)
--------------------------------
    R = w1·F + w2·I + w3·D + w4·M + w5·V
        - w6·C - w7·X - w8·O - w9·U - w10·E

  F = freshness            I = source independence   D = narrative diffusion
  M = Moltbook repair      V = invalidation clarity   C = crowding
  X = contradiction        O = operator load          U = unrepaired-loss debt
  E = echo risk

Missing canonical components contribute their **neutral** weight-zero value and
are reported as ``insufficient`` rather than invented, so an empty DB yields an
honest ``INSUFFICIENT_DATA`` routing readiness — never a confident fake.

Hard rules
----------
* Read-only.  No DB writes, no broker, no execution.
* The reactor consumes this **summary**; it issues no orders.  The output never
  contains BUY / SELL / EXECUTE.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import complex_systems_sqlite_bridge as _bridge
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import complex_systems_sqlite_bridge as _bridge  # type: ignore[no-redef]

INSUFFICIENT = "INSUFFICIENT_DATA"

# Positive contributors (rewarded) and negative contributors (penalised).
_POSITIVE_WEIGHTS: dict[str, float] = {
    "freshness": 0.15,
    "source_independence": 0.25,
    "narrative_diffusion": 0.10,
    "moltbook_repair": 0.30,
    "invalidation_clarity": 0.20,
}
_NEGATIVE_WEIGHTS: dict[str, float] = {
    "crowding": 0.15,
    "contradiction": 0.20,
    "operator_load": 0.15,
    "unrepaired_loss_debt": 0.40,
    "echo_risk": 0.25,
}


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # drop NaN


def _diffusion_unit(value: Any) -> float | None:
    """Squash the unbounded diffusion value into [0,1] for scoring."""
    f = _num(value)
    if f is None:
        return None
    # Diffusion is >= 0 and rarely exceeds ~3 in practice; cap at 1.0.
    return max(0.0, min(1.0, f / 3.0))


def extract_routing_components(state: dict[str, Any]) -> dict[str, Any]:
    """Pull the ten routing components out of the canonical bridge state.

    Each component is either a float in [0,1] or ``None`` (insufficient data).
    """
    comps = state.get("components", {}) if isinstance(state, dict) else {}
    fp = comps.get("fingerprint_independence", {})
    cell = comps.get("signal_cell_diffusion", {})
    repair = comps.get("moltbook_repair", {})
    mismatch = comps.get("reconciliation_mismatch", {})
    exposure = comps.get("manual_trade_exposure", {})
    fresh = comps.get("signal_freshness", {})
    return {
        "freshness": _num(fresh.get("freshness")),
        "source_independence": _num(fp.get("independence_score")),
        "narrative_diffusion": _diffusion_unit(cell.get("diffusion")),
        "moltbook_repair": _num(repair.get("moltbook_repair_score")),
        "invalidation_clarity": _num(exposure.get("invalidation_clarity")),
        "crowding": _num(cell.get("crowding")),
        "contradiction": _num(mismatch.get("contradiction")),
        "operator_load": _num(exposure.get("operator_load")),
        "unrepaired_loss_debt": _num(repair.get("unrepaired_loss_debt")),
        "echo_risk": _num(fp.get("echo_risk")),
    }


def compute_routing_score(components: dict[str, Any]) -> dict[str, Any]:
    """Compute R from the routing components.  Pure; never raises.

    Returns the score plus the per-term contributions and a list of components
    that were insufficient (so the operator sees what was *not* grounded).
    """
    contributions: dict[str, float] = {}
    insufficient: list[str] = []
    score = 0.0
    for name, weight in _POSITIVE_WEIGHTS.items():
        val = components.get(name)
        if val is None:
            insufficient.append(name)
            continue
        contrib = weight * max(0.0, min(1.0, float(val)))
        contributions[name] = round(contrib, 4)
        score += contrib
    for name, weight in _NEGATIVE_WEIGHTS.items():
        val = components.get(name)
        if val is None:
            insufficient.append(name)
            continue
        contrib = -weight * max(0.0, min(1.0, float(val)))
        contributions[name] = round(contrib, 4)
        score += contrib
    grounded = len(_POSITIVE_WEIGHTS) + len(_NEGATIVE_WEIGHTS) - len(insufficient)
    return {
        "routing_score": round(score, 4),
        "contributions": contributions,
        "insufficient_components": insufficient,
        "grounded_component_count": grounded,
    }


def build_reactor_canonical_inputs(
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Build the canonical reactor input payload (routing score + summary)."""
    state = _bridge.build_canonical_complex_systems_state(db_path)
    components = extract_routing_components(state)
    scoring = compute_routing_score(components)

    # Routing readiness is INSUFFICIENT_DATA unless at least the two
    # safety-critical components (independence + repair) are grounded.
    safety_critical = ("source_independence", "moltbook_repair")
    grounded_critical = all(components.get(k) is not None for k in safety_critical)
    readiness = "ROUTABLE" if (state.get("state") == "OK" and grounded_critical) else INSUFFICIENT

    return {
        "report": "reactor_canonical_inputs",
        "db_path": state.get("db_path"),
        "db_available": state.get("db_available", False),
        "data_origin": "canonical_sqlite",
        "routing_readiness": readiness,
        "routing_score": scoring["routing_score"],
        "routing_components": components,
        "routing_contributions": scoring["contributions"],
        "insufficient_components": scoring["insufficient_components"],
        "grounded_component_count": scoring["grounded_component_count"],
        # The full canonical complex-systems summary the reactor may consume.
        "complex_system_summary": state,
        "advisory_status": _contract.ADVISORY_STATUS,
        "execution_gate": _contract.EXECUTION_GATE_LOCKED,
        "human_review_required": True,
        "broker_api_called": False,
        "ai_execution_count": _contract.AI_EXECUTION_COUNT,
        "note": (
            "Adaptive-routing diagnostic only — not an order. Routing reflects "
            "canonical operator history; missing data degrades, never faked."
        ),
    }


def attach_canonical_diagnostics(
    reactor_payload: dict[str, Any],
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Merge the canonical reactor inputs into an existing reactor payload.

    Non-destructive: the reactor's own keys are preserved; the canonical
    summary is attached under ``canonical_inputs``.  The advisory stamps are
    re-asserted so the merged payload cannot lose them.
    """
    out = dict(reactor_payload) if isinstance(reactor_payload, dict) else {}
    out["canonical_inputs"] = build_reactor_canonical_inputs(db_path)
    out.setdefault("advisory_status", _contract.ADVISORY_STATUS)
    out["execution_gate"] = _contract.EXECUTION_GATE_LOCKED
    out["broker_api_called"] = False
    out["ai_execution_count"] = _contract.AI_EXECUTION_COUNT
    out["human_review_required"] = True
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="reactor_canonical_inputs.py",
        description=(
            "Compute the canonical-SQLite-derived reactor routing score. "
            "Read-only; advisory-only; never an order."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = Path(args.db_path) if args.db_path else None
    report = build_reactor_canonical_inputs(db)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Reactor canonical inputs: {report['routing_readiness']}")
        print(f"  routing_score        : {report['routing_score']}")
        print(f"  grounded components  : {report['grounded_component_count']}/10")
        print(f"  insufficient         : {report['insufficient_components']}")
    return 0


__all__ = [
    "extract_routing_components",
    "compute_routing_score",
    "build_reactor_canonical_inputs",
    "attach_canonical_diagnostics",
]


if __name__ == "__main__":
    raise SystemExit(main())
