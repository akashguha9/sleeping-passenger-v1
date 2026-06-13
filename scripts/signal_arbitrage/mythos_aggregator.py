"""Multi-Observation Aggregator — corroboration becomes migration.

A single Mythos observation is one source, so Fable's cross-platform-migration
stage stays capped and vitality can never fully transfer.  This aggregator
groups multiple observations of the SAME thesis, merges them across distinct
source ecologies into one richer Fable dossier, and lets cross-platform
migration rise — but ONLY when *independent* sources in *distinct* ecologies
corroborate.  Repeated same-source spam collapses to one ecology and earns no
migration credit; a social-only cluster gains breadth but no economic reality,
so its blind score stays zero and it can never become a Buy.

Governance is preserved: every aggregate is governance-trust-weighted, so an
audited filing outweighs a noisy feed.  Fable's fraud gates are untouched —
this only builds a better dossier and a confidence cap for it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .util import clamp, r3
from .mythos import (
    MythosObservation, run_mythos, source_to_ecology, build_fable5_dossier,
)
from .opportunity import SignalDossier, score_opportunity
from .strategist import strategize_signal
from .mythos_ledger import MythosLedgerStore, claim_id_for


def thesis_key(obs: MythosObservation) -> str:
    return f"{obs.entity}::{obs.resolved_claim()}"


def _event_key(obs: MythosObservation) -> tuple[str, int, str]:
    """Identity for dedup: same source + day + claim is the same evidence."""
    return (obs.source.strip().lower(), obs.day, obs.resolved_claim())


def dedup_observations(obs_list: list[MythosObservation]) -> list[MythosObservation]:
    """Collapse exact same-source/day/claim duplicates (anti-spam)."""
    seen: set[tuple[str, int, str]] = set()
    out: list[MythosObservation] = []
    for o in obs_list:
        k = _event_key(o)
        if k in seen:
            continue
        seen.add(k)
        out.append(o)
    return out


def group_observations(obs_list: list[MythosObservation]) -> dict[str, list[MythosObservation]]:
    """Group observations into thesis clusters by entity + claim."""
    groups: dict[str, list[MythosObservation]] = {}
    for o in obs_list:
        groups.setdefault(thesis_key(o), []).append(o)
    return groups


@dataclass
class AggregationResult:
    entity: str
    claim: str
    n_observations: int
    n_sources: int
    distinct_ecologies: list[str]
    n_distinct_ecologies: int
    corroboration: float
    economic_reality_score: float
    narrative_belief_score: float
    reality_confirmation: float
    blind_score: float
    confidence_cap: float
    claim_status: str
    has_capture_data: bool = False
    capture_power: float = 0.0
    per_source: list[dict[str, Any]] = field(default_factory=list)
    dossier: SignalDossier | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in (
            "entity", "claim", "n_observations", "n_sources", "distinct_ecologies",
            "n_distinct_ecologies", "corroboration", "economic_reality_score",
            "narrative_belief_score", "reality_confirmation", "blind_score",
            "confidence_cap", "claim_status", "per_source")}
        return d


def aggregate_cluster(obs_list: list[MythosObservation]) -> AggregationResult:
    """Merge a thesis cluster into one governance-weighted aggregate + dossier."""
    deduped = dedup_observations(obs_list)
    per: list[dict[str, Any]] = []
    add_shopify = False
    has_capture_data = any(o.capture_rate is not None or o.flow_growth is not None
                           for o in deduped)
    capture_power = 0.0
    for o in deduped:
        m = run_mythos(o)
        eco = source_to_ecology(o.source, m["governance_type"])
        fc = m["food_chain"]
        capture_power = max(capture_power, fc["capture_power"])
        if fc["value_capture_role"] in ("PREDATOR", "HABITAT") or fc["tollbooth_status"] == "TOLLBOOTH":
            add_shopify = True
        per.append({
            "source": o.source, "ecology": eco, "day": o.day,
            "governance": m["governance_type"],
            "governance_trust": m["governance_trust_score"],
            "economic_reality_score": m["economic_reality_score"],
            "narrative_belief_score": m["narrative_belief_score"],
            "layer_integrity": m["layer_integrity_score"],
            "claim_status": m["claim_status"],
            "_obs": o, "_mythos": m,
        })

    # Distinct ECOLOGIES (not sources): two reddit posts = one ecology.
    distinct = sorted({p["ecology"] for p in per})
    n_eco = len(distinct)
    corroboration = clamp((n_eco - 1) / 3.0)

    # Governance-trust-weighted aggregates (audited filing > noisy feed).
    W = sum(p["governance_trust"] for p in per) or 1.0

    def wmean(key: str) -> float:
        return clamp(sum(p["governance_trust"] * p[key] for p in per) / W)

    def wopt(field_name: str, fallback: float) -> float:
        present = [p for p in per if getattr(p["_obs"], field_name) is not None]
        if not present:
            return clamp(fallback)
        w = sum(p["governance_trust"] for p in present) or 1.0
        return clamp(sum(p["governance_trust"] * clamp(getattr(p["_obs"], field_name))
                         for p in present) / w)

    agg_econ = wmean("economic_reality_score")
    agg_narr = wmean("narrative_belief_score")
    agg_integrity = wmean("layer_integrity")

    # Corroboration legitimately raises reality confidence (the whole point) —
    # but it is a merit input, not a fraud gate, so the spine is intact.
    reality_confirmation = clamp(agg_econ * (1.0 + 0.25 * corroboration))
    perception_premium = max(0.0, agg_narr - agg_econ)
    blind = clamp(agg_econ - 0.6 * perception_premium)
    confidence_cap = clamp(agg_integrity * (1.0 + 0.15 * corroboration))

    retention_up = any(p["_obs"].claim_type == "retention_up" for p in per)
    max_amp = max((p["_obs"].amplification for p in per), default=0.0)
    max_consensus = max((p["_obs"].consensus for p in per), default=0.0)
    max_saturation = max((p["_obs"].saturation for p in per), default=0.0)
    max_priced_in = max((p["_mythos"]["casino"]["priced_in_risk"] for p in per), default=0.0)

    adoption = wopt("customer_adoption", agg_econ)
    retention = wopt("retention", agg_econ if retention_up else 0.5 * agg_econ)

    platforms = list(distinct)
    if add_shopify and "shopify" not in platforms:
        platforms.append("shopify")

    # Aggregated claim status.
    if any(p["claim_status"] in ("DISCONFIRMED", "STALE") for p in per):
        claim_status = "STALE"
    elif corroboration >= 0.5 and agg_econ >= 0.5:
        claim_status = "SUPPORTED"
    else:
        claim_status = "PROVISIONAL"

    entity = per[0]["_obs"].entity if per else ""
    claim = per[0]["_obs"].resolved_claim() if per else ""

    dossier = SignalDossier(
        signal_id=f"mythos-agg::{entity}",
        text=" ".join(p["_obs"].raw_text or p["_obs"].resolved_claim() for p in per),
        platforms=platforms,
        # Engagement proxies from ECONOMIC substance, scaled by corroboration.
        views=round(agg_econ * 4000 * (1.0 + corroboration)),
        likes=round(adoption * 150 * (1.0 + corroboration)),
        saves=round(retention * 60 * (1.0 + corroboration)),
        conversions=round(adoption * 80 * (1.0 + corroboration)),
        conversion_strength=adoption,
        retention_strength=retention,
        reproduction_strength=clamp(0.5 * agg_econ + 0.3 * max_amp + 0.1 * corroboration),
        business_confirmation=wopt("demand", agg_econ),
        financial_confirmation=wopt("margin_trend", 0.8 * agg_econ),
        reality_confirmation=reality_confirmation,
        price_recognition=clamp(0.4 * max_consensus + 0.3 * max_saturation + 0.3 * agg_narr),
        crowding=clamp(max(max_saturation, 0.5 * max_priced_in)),
        blind_score=blind,
        age_days=float(max((p["_obs"].catalyst_elapsed_days or 0.0 for p in per),
                           default=0.0)),
    )

    public_per_source = [{k: p[k] for k in (
        "source", "ecology", "day", "governance", "governance_trust",
        "economic_reality_score", "narrative_belief_score", "claim_status")} for p in per]

    return AggregationResult(
        entity=entity, claim=claim, n_observations=len(deduped),
        n_sources=len({p["source"].strip().lower() for p in per}),
        distinct_ecologies=distinct, n_distinct_ecologies=n_eco,
        corroboration=r3(corroboration),
        economic_reality_score=r3(agg_econ), narrative_belief_score=r3(agg_narr),
        reality_confirmation=r3(reality_confirmation), blind_score=r3(blind),
        confidence_cap=r3(confidence_cap), claim_status=claim_status,
        has_capture_data=has_capture_data, capture_power=r3(capture_power),
        per_source=public_per_source, dossier=dossier,
    )


# Routing decisions (mirror the single-obs pipeline vocabulary).
REJECTED_PRE_SCORING = "REJECTED_PRE_SCORING"
ROUTE_TO_FABLE5 = "ROUTE_TO_FABLE5"
ROUTE_TO_FOOD_CHAIN = "ROUTE_TO_FOOD_CHAIN"
ROUTE_TO_REALITY_CHECK = "ROUTE_TO_REALITY_CHECK"
WATCH_ONLY = "WATCH_ONLY"


def _aggregate_route(agg: AggregationResult) -> str:
    narrative_only = agg.economic_reality_score < 0.25 and agg.narrative_belief_score >= 0.5
    # A signal that explicitly carries flow/capture data but captures little
    # value is a food-chain question, not a buy — even if reality looks high.
    weak_capture = agg.has_capture_data and agg.capture_power < 0.35
    if narrative_only:
        return ROUTE_TO_REALITY_CHECK
    if weak_capture:
        return ROUTE_TO_FOOD_CHAIN
    if agg.confidence_cap < 0.30:
        return REJECTED_PRE_SCORING
    if agg.reality_confirmation >= 0.45:
        return ROUTE_TO_FABLE5
    if agg.economic_reality_score >= 0.4:
        return ROUTE_TO_FOOD_CHAIN
    return WATCH_ONLY


def run_aggregated_pipeline(obs_list: list[MythosObservation], *,
                            ledger: MythosLedgerStore | None = None,
                            current_day: int | None = None,
                            run_fable: bool = True) -> dict[str, Any]:
    """Aggregate a cluster -> route -> (maybe) Fable score -> remember."""
    agg = aggregate_cluster(obs_list)
    day = current_day if current_day is not None else max((o.day for o in obs_list), default=0)
    decision = _aggregate_route(agg)

    fable_summary = None
    capped_confidence = None
    if decision == ROUTE_TO_FABLE5 and run_fable and agg.dossier is not None:
        fable = strategize_signal(agg.dossier)            # fraud gates intact
        capped_confidence = r3(min(fable["confidence_score"], agg.confidence_cap))
        fable_summary = {
            "decision": fable["decision"],
            "investable_score": fable["investable_score"],
            "research_ceiling_score": fable["research_ceiling_score"],
            "raw_merit": fable["raw_merit"],
            "fable_confidence_score": fable["confidence_score"],
            "recommended_action": fable["recommended_action"],
        }

    ledger_view = None
    if ledger is not None:
        from .mythos import validation_window_for
        rec = ledger.upsert_claim(
            entity=agg.entity, claim=agg.claim, interpretation="AGGREGATE",
            governance="AGGREGATE", prior_confidence=agg.reality_confirmation,
            day=day, validation_window=30)
        # Apply each deduped observation's evidence once, dedup by event id.
        for o in dedup_observations(obs_list):
            eid = f"{o.source.strip().lower()}:{o.day}"
            ledger.apply_evidence(rec.claim_id, day=o.day, supports=True,
                                  weight=0.5, independent=0.6, event_id=eid)
        ledger_view = {"claim_id": rec.claim_id, "status": rec.status,
                       "confidence": r3(rec.confidence),
                       "survival_count": rec.survival_count,
                       "chain_valid": rec.chain_valid()}

    return {
        "entity": agg.entity,
        "pre_scoring_decision": decision,
        "routed_to_fable": fable_summary is not None,
        "aggregation": agg.to_dict(),
        "n_distinct_ecologies": agg.n_distinct_ecologies,
        "corroboration": agg.corroboration,
        "mythos_confidence_cap": agg.confidence_cap,
        "fable": fable_summary,
        "capped_confidence": capped_confidence,
        "ledger": ledger_view,
        "advisory_status": "ADVISORY_ONLY",
        "real_money_execution": "PROHIBITED",
        "broker_api_called": False,
    }


__all__ = [
    "aggregate_cluster", "run_aggregated_pipeline", "group_observations",
    "dedup_observations", "thesis_key", "AggregationResult",
    "REJECTED_PRE_SCORING", "ROUTE_TO_FABLE5", "ROUTE_TO_FOOD_CHAIN",
    "ROUTE_TO_REALITY_CHECK", "WATCH_ONLY",
]
