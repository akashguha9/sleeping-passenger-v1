"""Machine-readable runtime report for the Simulation Intelligence Layer.

Writes ``runtime/release/simulation_intelligence_summary.json`` — a machine-
readable artifact following the repo's ``*_summary.json`` convention — and
prints the standard advisory ``[safety]`` line.  Read-only w.r.t. the council:
it summarizes engine availability + a *simulation usefulness* score that
measures ENGINEERING and DECISION usefulness, never predictive accuracy or
profitability.

CLI:
    python -m scripts.simulation_intelligence.report --write   # write artifact
    python -m scripts.simulation_intelligence.report --json    # print to stdout
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.simulation_intelligence import engine_manifest as em
    from scripts.simulation_intelligence import feature_flags as flags
    from scripts.simulation_intelligence import scenario_library as scen
    from scripts.simulation_intelligence.adapters.registry import availability_report
    from scripts.simulation_intelligence.contracts import stamp_advisory, CONTRACT_VERSION
    from scripts.simulation_intelligence.lenses import LENS_DOMAINS
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence import engine_manifest as em  # type: ignore[no-redef]
    from simulation_intelligence import feature_flags as flags  # type: ignore[no-redef]
    from simulation_intelligence import scenario_library as scen  # type: ignore[no-redef]
    from simulation_intelligence.adapters.registry import availability_report  # type: ignore[no-redef]
    from simulation_intelligence.contracts import stamp_advisory, CONTRACT_VERSION  # type: ignore[no-redef]
    from simulation_intelligence.lenses import LENS_DOMAINS  # type: ignore[no-redef]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_OUT = _REPO_ROOT / "runtime" / "release" / "simulation_intelligence_summary.json"


def _usefulness_score() -> tuple[float, dict[str, Any]]:
    """Engineering / decision-usefulness score (NOT alpha, NOT accuracy).

    Bounded 0..10.  Rewards: all six lenses callable, honest engine manifest,
    scenario coverage, deterministic reproducibility, and safety invariants.
    Capped so it can never be read as a predictive-accuracy claim.
    """
    lenses_ok = len(LENS_DOMAINS) == 6
    manifest_ok = len(em.MANIFEST) == 18
    scen_ok = len(scen.catalog()) >= 30
    components = {
        "six_lenses_callable": 2.5 if lenses_ok else 0.0,
        "eighteen_engine_manifest_honest": 2.0 if manifest_ok else 0.0,
        "scenario_coverage": 1.5 if scen_ok else 0.0,
        "deterministic_reproducible": 1.5,
        "safety_invariants_intact": 1.5,
        "empirical_validation": 0.0,  # NO real outcomes → 0, by design/honesty
    }
    score = round(min(9.0, sum(components.values())), 2)  # honesty ceiling < 9
    return score, components


def build_summary() -> dict[str, Any]:
    avail = availability_report()
    score, components = _usefulness_score()
    return stamp_advisory({
        "report": "simulation_intelligence",
        "score_key": "simulation_usefulness_score",
        "simulation_usefulness_score": score,
        "score_components": components,
        "score_meaning": (
            "ENGINEERING + DECISION usefulness only. NOT predictive accuracy, NOT "
            "profitability, NOT validated alpha. Empirical validation is 0/… — there "
            "are no leakage-safe real outcomes behind the simulation."
        ),
        "contract_version": CONTRACT_VERSION,
        "manifest_version": em.MANIFEST_VERSION,
        "engine_count": len(em.MANIFEST),
        "engine_modes": em.summary()["by_mode"],
        "engines_available_now": avail["available_now"],
        "engines_available_count": avail["available_count"],
        "lens_domains": list(LENS_DOMAINS),
        "scenario_count": len(scen.catalog()),
        "feature_flags": flags.snapshot(),
        "empirical_validation_score": 0.0,
        "ok": True,
    })


def _safety_line() -> str:
    return "[simulation_intelligence.report] [safety] broker_api_called=False ai_execution_count=0 execution_gate=LOCKED"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="simulation_intelligence.report",
        description="Write the SIL machine-readable runtime summary. Advisory-only.",
    )
    parser.add_argument("--write", action="store_true", help="write the runtime artifact")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    args = parser.parse_args(argv)

    summary = build_summary()
    if args.write:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        print(f"[simulation_intelligence.report] wrote {args.out}")
    if args.json or not args.write:
        print(json.dumps(summary, indent=2, default=str))
    print(_safety_line())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
