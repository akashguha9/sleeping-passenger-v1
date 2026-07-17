"""The six domain lenses, each behind one common :class:`Lens` interface."""
from __future__ import annotations

try:
    from scripts.simulation_intelligence.lenses.base import Lens
    from scripts.simulation_intelligence.lenses.physics import PhysicsLens
    from scripts.simulation_intelligence.lenses.chemistry import ChemistryLens
    from scripts.simulation_intelligence.lenses.biology import BiologyLens
    from scripts.simulation_intelligence.lenses.racing import RacingLens
    from scripts.simulation_intelligence.lenses.chess import ChessLens
    from scripts.simulation_intelligence.lenses.poker import PokerLens
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.lenses.base import Lens  # type: ignore[no-redef]
    from simulation_intelligence.lenses.physics import PhysicsLens  # type: ignore[no-redef]
    from simulation_intelligence.lenses.chemistry import ChemistryLens  # type: ignore[no-redef]
    from simulation_intelligence.lenses.biology import BiologyLens  # type: ignore[no-redef]
    from simulation_intelligence.lenses.racing import RacingLens  # type: ignore[no-redef]
    from simulation_intelligence.lenses.chess import ChessLens  # type: ignore[no-redef]
    from simulation_intelligence.lenses.poker import PokerLens  # type: ignore[no-redef]


def all_lenses() -> list[Lens]:
    """Fresh instances of all six lenses (stateful lenses reset per call)."""
    return [
        PhysicsLens(), ChemistryLens(), BiologyLens(),
        RacingLens(), ChessLens(), PokerLens(),
    ]


LENS_DOMAINS = ("PHYSICS", "CHEMISTRY", "BIOLOGY", "RACING", "CHESS", "POKER")

__all__ = [
    "Lens", "PhysicsLens", "ChemistryLens", "BiologyLens",
    "RacingLens", "ChessLens", "PokerLens", "all_lenses", "LENS_DOMAINS",
]
