"""Live-surface guard: the repo must know which code can touch the user.

Two consecutive audits misclassified ``src/scoring`` as dead code
because nothing authoritative mapped src/ modules to their entry lanes.
This guard pins that map:

* the API lane must contain the decision engines users actually see;
* the batch lane must contain the documented CLI stack (``src.scoring``
  et al.) — formally resolving the "dead parallel stack" question;
* the unreachable set is pinned EXACTLY: a new module that ships with
  tests but no entry path fails CI (fake coverage cannot regrow), and
  removing a quarantined module forces a conscious update here.
"""

from __future__ import annotations

from pathlib import Path

from scripts.live_surface_census import build_census

REPO = Path(__file__).resolve().parents[1]

# Tested-but-unwired (or wholly unreferenced) modules, pinned at the
# 2026-06-12 census. Each must be either wired into a lane or retired —
# see docs/LIVE_SURFACE.md. Nothing may join this list silently.
# 2026-06-12 resolution sprint: driver_derivation WIRED into the
# pipeline (journal_records section); paper_position_tracker ARCHIVED
# (zero importers, zero tests). The four below are KEPT deliberately —
# see docs/LIVE_SURFACE.md for each disposition.
QUARANTINE: frozenset[str] = frozenset({
    "src.ingestion.kalshi_public_client",   # parked kalshi ingestion lane
    "src.models.kalshi_market",             # model for the above
    "src.simulator.live_adapter",           # wire target: live-refresh lane
    "src.simulator.reality_replay",         # wire target: resolved-eval replay
})

CORE_API_LANE = (
    "src.simulator.pipeline",
    "src.simulator.risk_convergence",
    "src.simulator.signal_refiner",
    "src.strategy.self_feed",
    "src.strategy.edge_lifecycle",
    "src.strategy.lifecycle_attribution",
    "src.games.advisory_router",
    "src.consent.pipeline_bridge",
)


def test_census_is_deterministic() -> None:
    assert build_census() == build_census()


def test_driver_derivation_is_wired_now() -> None:
    # Resolved out of quarantine 2026-06-12: the journal-evidence driver
    # state is reachable from the API lane via the pipeline's
    # journal_records section.
    assert "src.simulator.driver_derivation" in set(
        build_census()["api_lane"]
    )


def test_decision_engines_are_on_the_api_lane() -> None:
    api_lane = set(build_census()["api_lane"])
    for module in CORE_API_LANE:
        assert module in api_lane, (
            f"{module} fell off the API lane — a user-facing engine is "
            "no longer reachable from the API server"
        )


def test_scoring_stack_is_batch_lane_not_dead_and_not_api() -> None:
    census = build_census()
    batch = set(census["batch_lane"])
    api = set(census["api_lane"])
    scoring = {
        module for module in (
            set(census["api_lane"]) | set(census["batch_lane"])
            | set(census["unreachable"])
        )
        if module.startswith("src.scoring.")
        and not module.endswith("__init__")
    }
    assert scoring, "src.scoring modules disappeared from the census"
    for module in scoring:
        assert module in batch, (
            f"{module} is not on the batch lane — either it died "
            "(retire its tests) or it got wired into the API "
            "(update this guard and docs/LIVE_SURFACE.md)"
        )
        assert module not in api


def test_outcome_import_is_wired_not_test_only() -> None:
    # The calibration importer was the census's first catch: a module
    # reachable only from its own tests. scripts/import_outcomes.py is
    # the wire; this pins it.
    census = build_census()
    assert "src.strategy.outcome_import" in census["batch_lane"]


def test_unreachable_set_is_pinned_exactly() -> None:
    unreachable = {
        module for module in build_census()["unreachable"]
        if not module.endswith("__init__")
    }
    new = unreachable - QUARANTINE
    gone = QUARANTINE - unreachable
    assert not new, (
        f"NEW unreachable module(s): {sorted(new)} — tested-but-unwired "
        "code may not land silently. Wire it into a lane, or add it to "
        "QUARANTINE with a rationale and a wire-or-retire entry in "
        "docs/LIVE_SURFACE.md."
    )
    assert not gone, (
        f"Quarantined module(s) no longer unreachable: {sorted(gone)} — "
        "great, but update QUARANTINE and docs/LIVE_SURFACE.md to match."
    )


def test_live_surface_doc_exists_and_names_the_lanes() -> None:
    doc = (REPO / "docs" / "LIVE_SURFACE.md").read_text(encoding="utf-8")
    for needle in ("api_lane", "batch_lane", "quarantine"):
        assert needle in doc
    for module in QUARANTINE:
        assert module in doc, f"{module} missing from docs/LIVE_SURFACE.md"
