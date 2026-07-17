"""Common interface + shared helpers for the six domain lenses.

Every lens subclasses :class:`Lens` and implements :meth:`_evaluate`, returning a
:class:`LensResult`.  The base class enforces the shared contract:

* a stable ``domain`` and ``name``
* fail-closed behaviour: if the observation lacks the minimum data a lens
  needs, it returns an ``INSUFFICIENT_DATA`` result with a WAIT/AVOID vote
  rather than inventing a confident answer
* every result is bounded and evidence-labelled (never a bare confidence)
* exceptions inside a lens are trapped and converted into an ``error`` result
  so one broken lens can never take down the council

Lenses are PURE: they read a :class:`MarketObservation` and a seed and return a
result.  No DB, no network, no clock dependence beyond the caller-supplied
timestamps.
"""
from __future__ import annotations

import math
from typing import Any

try:
    from scripts.simulation_intelligence.contracts import (
        LensResult,
        MarketObservation,
        SimulationRequest,
        AdvisoryVote,
        EvidenceLabel,
        FreshnessStatus,
    )
    from scripts.simulation_intelligence import provenance as prov
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.contracts import (  # type: ignore[no-redef]
        LensResult,
        MarketObservation,
        SimulationRequest,
        AdvisoryVote,
        EvidenceLabel,
        FreshnessStatus,
    )
    from simulation_intelligence import provenance as prov  # type: ignore[no-redef]


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return lo
    if f != f:
        return lo
    return max(lo, min(hi, f))


def mean(xs: list[float]) -> float:
    xs = [float(x) for x in xs if x == x]
    return sum(xs) / len(xs) if xs else 0.0


def stdev(xs: list[float]) -> float:
    xs = [float(x) for x in xs if x == x]
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


class Lens:
    """Base class — all six lenses share this interface."""

    domain: str = "BASE"
    name: str = "base"
    #: minimum observation fields this lens needs to say anything at all
    required_fields: tuple[str, ...] = ()

    def evaluate(
        self,
        obs: MarketObservation,
        request: SimulationRequest | None = None,
        seed: int = 0,
    ) -> LensResult:
        """Public entry: fail-closed wrapper around :meth:`_evaluate`."""
        try:
            missing = self._missing(obs)
            if missing:
                return self._insufficient(obs, missing)
            result = self._evaluate(obs, request, seed)
            # Freshness penalty applies uniformly: stale data caps confidence.
            if obs is not None and obs.freshness_status.upper() == "STALE":
                result.confidence = clamp(result.confidence * 0.4)
                result.uncertainty = clamp(result.uncertainty + 0.3)
                result.missing_data_warnings.append("stale data: confidence capped")
                result.freshness_status = FreshnessStatus.STALE.value
            return result
        except Exception as exc:  # never let a lens crash the council
            return LensResult(
                lens=self.domain,
                state_interpretation="lens error — failing closed",
                advisory_vote=AdvisoryVote.WAIT.value,
                confidence=0.0,
                evidence_label=EvidenceLabel.INSUFFICIENT_DATA.value,
                uncertainty=1.0,
                missing_data_warnings=[f"lens raised {type(exc).__name__}"],
                error=type(exc).__name__,
            )

    # -- helpers subclasses use --------------------------------------------
    def _missing(self, obs: MarketObservation | None) -> list[str]:
        if obs is None:
            return list(self.required_fields) or ["observation"]
        out = []
        for f in self.required_fields:
            val = getattr(obs, f, None)
            if val is None or (isinstance(val, (list, str)) and len(val) == 0):
                out.append(f)
        # Explicitly declared missing fields count too.
        out.extend(m for m in obs.missing_fields if m in self.required_fields)
        return sorted(set(out))

    def _insufficient(self, obs: MarketObservation | None, missing: list[str]) -> LensResult:
        return LensResult(
            lens=self.domain,
            state_interpretation="insufficient data — failing closed",
            advisory_vote=AdvisoryVote.WAIT.value,
            confidence=0.0,
            evidence_label=EvidenceLabel.INSUFFICIENT_DATA.value,
            uncertainty=1.0,
            robustness=0.0,
            fragility=1.0,
            missing_data_warnings=[f"missing: {', '.join(missing)}"],
            freshness_status=(obs.freshness_status if obs else FreshnessStatus.UNKNOWN.value),
        )

    def _source_keys(self, obs: MarketObservation) -> list[str]:
        """Back-compat single key set (domain substrate) for a lens.

        Prefer :meth:`_evidence` which distinguishes the price *substrate*
        (unavoidably shared, domain-unique) from *external* narrative/catalyst
        sources (genuinely shared and the real shared-evidence-illusion signal).
        """
        return [f"{self.domain.lower()}-substrate::{obs.ticker}::{obs.data_cutoff}"]

    def narrative_keys(self, obs: MarketObservation) -> list[str]:
        """Shared narrative-source keys (not domain-prefixed)."""
        return [f"narrative::{s}" for s in obs.narrative_sources]

    def catalyst_keys(self, obs: MarketObservation) -> list[str]:
        """Shared catalyst keys (not domain-prefixed)."""
        return [f"catalyst::{c.get('id', c.get('name', 'unknown'))}" for c in obs.catalysts]

    def _evidence(
        self,
        obs: MarketObservation,
        claim: str,
        label: str,
        external_keys: list[str] | None = None,
    ):
        """Build a lens's evidence packets.

        Always emits one domain-*substrate* packet (price-based, domain-unique,
        so price reuse across lenses is NOT counted as corroboration).  For each
        external source the lens *actually leaned on* (passed via
        ``external_keys``), emits a shared packet — two lenses citing the same
        narrative/catalyst then share a fingerprint and are flagged as entangled,
        which is the genuine shared-evidence signal.
        """
        packets = [prov.make_evidence(
            self.domain, claim, label, self._source_keys(obs),
            weight=1.0, freshness_status=obs.freshness_status,
        )]
        for key in (external_keys or []):
            packets.append(prov.make_evidence(
                self.domain, f"{claim} (cites {key})", label, [key],
                weight=0.5, freshness_status=obs.freshness_status,
            ))
        return packets

    def _evaluate(
        self,
        obs: MarketObservation,
        request: SimulationRequest | None,
        seed: int,
    ) -> LensResult:  # pragma: no cover - abstract
        raise NotImplementedError


__all__ = ["Lens", "clamp", "mean", "stdev", "prov"]
