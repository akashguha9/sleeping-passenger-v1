"""Deterministic simulation replay + telemetry timeline.

Given a stored run's request payload, re-run the council and confirm it
reproduces the stored ``run_id`` and aggregate verdict.  This proves
reproducibility-by-seed-and-data-cutoff (the iRacing/rFactor "versioned
telemetry" transplant: a replay must reconstruct the recorded decision path).

Pure: takes dicts in, returns dicts out.  Reading the stored run from SQLite is
the route's job.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.simulation_intelligence.api_surface import run_simulation
    from scripts.simulation_intelligence.contracts import stamp_advisory
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.api_surface import run_simulation  # type: ignore[no-redef]
    from simulation_intelligence.contracts import stamp_advisory  # type: ignore[no-redef]


def build_telemetry_timeline(council_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Reconstruct the decision telemetry: how the verdict was reached.

    Every gate, weight, penalty, warning and override becomes a timeline entry
    (the iRacing high-resolution-telemetry transplant), so an operator can see
    WHY a candidate moved to WATCH / WAIT / AVOID / RISK_BLOCK.
    """
    timeline: list[dict[str, Any]] = []
    seq = 0

    def add(kind: str, label: str, detail: Any = None) -> None:
        nonlocal seq
        timeline.append({"seq": seq, "kind": kind, "label": label, "detail": detail})
        seq += 1

    add("input", "observation freshness", council_result.get("freshness_status"))
    for lr in council_result.get("lens_results", []):
        add("lens", f"{lr.get('lens')} → {lr.get('advisory_vote')}", {
            "state": lr.get("state_interpretation"),
            "confidence": lr.get("confidence"),
            "evidence_label": lr.get("evidence_label"),
            "tail_warning": lr.get("tail_warning") or None,
        })
    for w in council_result.get("lens_weights", []):
        add("weight", f"{w.get('lens')} weight={w.get('final_weight')}", w.get("reasons"))
    for line in council_result.get("aggregation_explanation", []):
        add("aggregation", line)
    for warn in council_result.get("minority_warnings", []):
        add("minority_warning", warn)
    for warn in council_result.get("tail_warnings", []):
        add("tail_warning", warn)
    if council_result.get("risk_block_engaged"):
        add("override", "RISK_BLOCK engaged", council_result.get("risk_block_reason"))
    add("verdict", f"aggregate → {council_result.get('aggregate_vote')}", {
        "disagreement_class": council_result.get("disagreement_class"),
        "evidence_label": council_result.get("evidence_label"),
        "simulation_only": council_result.get("simulation_only"),
    })
    return timeline


def replay_run(stored_run: dict[str, Any]) -> dict[str, Any]:
    """Re-run the council from a stored run's request and compare.

    ``stored_run`` is a persisted row dict containing ``request`` (the parsed
    request payload) and ``result`` (the original council dict).  Returns a
    determinism report.
    """
    request_payload = stored_run.get("request") or {}
    original = stored_run.get("result") or {}
    replayed = run_simulation(request_payload, run_stress=True)

    matches = (
        replayed.get("run_id") == original.get("run_id")
        and replayed.get("aggregate_vote") == original.get("aggregate_vote")
        and replayed.get("disagreement_class") == original.get("disagreement_class")
        and abs(float(replayed.get("aggregate_confidence", 0.0))
                - float(original.get("aggregate_confidence", 0.0))) < 1e-9
    )
    return stamp_advisory({
        "report": "simulation_replay",
        "run_id": original.get("run_id"),
        "deterministic_match": bool(matches),
        "original_vote": original.get("aggregate_vote"),
        "replayed_vote": replayed.get("aggregate_vote"),
        "original_run_id": original.get("run_id"),
        "replayed_run_id": replayed.get("run_id"),
        "telemetry_timeline": build_telemetry_timeline(replayed),
        "replayed_result": replayed,
    })


__all__ = ["build_telemetry_timeline", "replay_run"]
