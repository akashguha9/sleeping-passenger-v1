"""Intelligence Budget allocator — prevent compute theatre.

Not every candidate deserves the full council + ablation + optional engines. This
allocates analysis depth so a weak candidate is rejected cheaply, a high-potential
uncertain candidate gets deep analysis, and a strong well-evidenced candidate is
not over-analysed. Deterministic, bounded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.simulation_intelligence.contracts import MarketObservation
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from simulation_intelligence.contracts import MarketObservation  # type: ignore[no-redef]


def _clip(v: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, f)) if f == f else lo


@dataclass(slots=True)
class IntelligenceBudget:
    candidate_id: str
    analysis_depth: str            # REJECT_CHEAP | SHALLOW | STANDARD | DEEP
    run_full_council: bool
    scenario_count: int
    run_pairwise_ablation: bool
    justify_optional_engines: bool
    justify_evidence_acquisition: bool
    stop_researching: bool
    priority_score: float          # 0..1 for ranking candidates
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__slots__}
        d.update(advisory_safety_stamps())
        return d


def allocate(
    obs: MarketObservation,
    *,
    prescreen_confidence: float | None = None,
    uncertainty: float = 0.5,
    tail_risk: float = 0.0,
    value_of_information: float = 0.0,
    redundancy: float = 0.0,
    time_sensitive: bool = False,
) -> IntelligenceBudget:
    """Allocate analysis depth BEFORE running the expensive council when possible.

    ``prescreen_confidence`` is a cheap pre-council quality proxy (e.g. from the
    discovery score); when absent, liquidity + data completeness stand in.
    """
    reasons: list[str] = []
    # Cheap quality prescreen from liquidity + data completeness. Completeness is
    # computed from ACTUAL field presence (build_observation's missing_fields is
    # not exhaustive), so a genuinely data-poor candidate scores near zero.
    liq = _clip((obs.adv_usd or 0.0) / 5e7)
    n_ret = len(obs.returns or [])
    present = sum([
        obs.price is not None,
        n_ret >= 2,
        obs.volatility is not None,
        obs.adv_usd is not None,
        obs.spread_bps is not None,
        int(obs.source_count or 0) > 0,
    ])
    completeness = _clip(present / 6.0)
    quality = prescreen_confidence if prescreen_confidence is not None else \
        round(0.4 * liq + 0.4 * completeness + 0.2 * _clip(n_ret / 10.0), 4)

    tail = _clip(tail_risk)
    voi = _clip(value_of_information, hi=2.0)
    unc = _clip(uncertainty)

    # Priority: high tail risk or high VoI on a plausible candidate ranks up.
    priority = round(_clip(0.35 * quality + 0.30 * voi + 0.25 * tail + 0.10 * unc), 4)

    # --- decide depth ----------------------------------------------------
    if quality < 0.2 and tail < 0.3 and voi < 0.05:
        depth = "REJECT_CHEAP"
        reasons.append("low quality, no tail risk, no research value → reject without deep analysis")
        return IntelligenceBudget(
            candidate_id=obs.ticker, analysis_depth=depth, run_full_council=False,
            scenario_count=0, run_pairwise_ablation=False,
            justify_optional_engines=False, justify_evidence_acquisition=False,
            stop_researching=True, priority_score=priority, reasons=reasons)

    if n_ret < 2 or obs.price is None:
        depth = "SHALLOW"
        reasons.append("insufficient price history → shallow (fail-closed) analysis only")
        return IntelligenceBudget(
            candidate_id=obs.ticker, analysis_depth=depth, run_full_council=True,
            scenario_count=3, run_pairwise_ablation=False,
            justify_optional_engines=False, justify_evidence_acquisition=voi > 0.1,
            stop_researching=voi <= 0.05, priority_score=priority, reasons=reasons)

    # High-potential uncertainty (tail risk OR high VoI OR high uncertainty on a
    # plausible candidate) → DEEP.
    if tail >= 0.4 or voi >= 0.15 or (unc >= 0.6 and quality >= 0.4):
        depth = "DEEP"
        reasons.append("high tail risk / research value / uncertainty on a plausible candidate")
        return IntelligenceBudget(
            candidate_id=obs.ticker, analysis_depth=depth, run_full_council=True,
            scenario_count=12, run_pairwise_ablation=True,
            justify_optional_engines=tail >= 0.5,
            justify_evidence_acquisition=voi >= 0.1 and redundancy < 0.7,
            stop_researching=False, priority_score=priority, reasons=reasons)

    # Strong, robust, well-evidenced → STANDARD; do not over-analyse.
    depth = "STANDARD"
    stop = quality >= 0.6 and unc < 0.4 and voi < 0.1
    if stop:
        reasons.append("strong, low-uncertainty candidate with sufficient evidence → stop researching")
    else:
        reasons.append("standard depth: adequate quality, moderate uncertainty")
    return IntelligenceBudget(
        candidate_id=obs.ticker, analysis_depth=depth, run_full_council=True,
        scenario_count=6, run_pairwise_ablation=False,
        justify_optional_engines=False,
        justify_evidence_acquisition=voi >= 0.1 and redundancy < 0.6,
        stop_researching=stop, priority_score=priority, reasons=reasons)


__all__ = ["IntelligenceBudget", "allocate"]
