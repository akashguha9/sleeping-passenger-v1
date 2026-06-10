"""Module F — classic benchmark layer.

Classics are control samples, not boring defaults: vanilla for ice
cream, Margherita for pizza, cash/card/UPI for payments, free cash flow
for stocks, boring plumbing for infrastructure.  Novelty that cannot
beat the sector classic is likely decoration.

    benchmark_edge = candidate_score - classic_benchmark_score
"""

from __future__ import annotations

from src.utils.math_utils import clip

# Sector -> apex classic control sample.
CLASSIC_BENCHMARKS: dict[str, str] = {
    "ice_cream": "vanilla",
    "pizza": "margherita",
    "payments": "cash_card_upi",
    "stocks": "free_cash_flow",
    "infrastructure": "boring_plumbing",
}

VERDICTS = ("beats_classic", "fails_classic", "inconclusive")

# Edges inside this band are noise, not signal.
_INCONCLUSIVE_MARGIN = 5.0


def compare_to_classic(
    classic_benchmark: str,
    candidate_score: float,
    benchmark_score: float,
    *,
    inconclusive_margin: float = _INCONCLUSIVE_MARGIN,
) -> dict[str, object]:
    """Compare a candidate (0-100) against its classic benchmark (0-100)."""
    candidate = clip(candidate_score, 0.0, 100.0)
    benchmark = clip(benchmark_score, 0.0, 100.0)
    edge = candidate - benchmark
    if edge > inconclusive_margin:
        verdict = "beats_classic"
    elif edge < -inconclusive_margin:
        verdict = "fails_classic"
    else:
        verdict = "inconclusive"
    return {
        "classic_benchmark": classic_benchmark,
        "candidate_score": candidate,
        "benchmark_score": benchmark,
        "benchmark_edge": edge,
        "verdict": verdict,
        "explanation": [
            f"Candidate {candidate:.1f} vs classic '{classic_benchmark}' "
            f"{benchmark:.1f}: edge {edge:+.1f}.",
            f"Verdict: {verdict} (margin +/-{inconclusive_margin:.1f} is "
            "treated as inconclusive).",
            "If novelty does not beat the classic, it is likely decoration.",
        ],
    }


def classic_for_sector(sector: str) -> str | None:
    """Look up the registered apex classic for a sector, if any."""
    return CLASSIC_BENCHMARKS.get(sector)
