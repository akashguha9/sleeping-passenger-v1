"""Narrative state engine — deterministic clustering + narrative dynamics.

Groups deduplicated information observations into evolving NARRATIVES and
computes an explainable state per narrative:

    strength    N_t  = sum_i r_i * I_i * 2^(-(t - t_i)/h)
                       (reliability-prior x independence-weighted decayed
                       mass; independence uses cluster weights so 100
                       syndicated copies never count as 100 facts)
    velocity    (N_t - N_{t-step}) / step-normalized
    acceleration second difference over three checkpoints
    novelty     1 - max token-Jaccard vs OTHER narrative clusters
    persistence observation-span vs half-life
    contradiction dispersion of linguistic direction across items
    urgency / certainty / emotional activation: independence-weighted
                linguistic aggregates
    source entropy: Shannon entropy over per-family decayed mass

Regimes (operational subset — honestly reachable from available inputs):

    INSUFFICIENT_DATA, EMERGING, ACCUMULATING, ACCELERATING, CONTESTED,
    BREAKING, DOMINANT, DECAYING

Designed-but-not-operational (documented, never assigned):
DORMANT / COHERING / SATURATED / REVERSING need narrative registries that
persist across runs (cross-run identity) — deferred until narrative
history accumulates.  Exported as ``RESERVED_NARRATIVE_REGIMES``.

Half-lives are CONFIGURED priors per dominant source family (rumour-hours
to regulation-months compressed to the families this repo actually
ingests); the payload stamps ``half_life_source="configured_prior"``.

Also provides ``narrative temperature`` (sigmoid over item velocity,
source velocity, |log-odds impulse|, urgency, emotion, contradiction) and
linguistic inflection between the narrative's early and late halves.

Pure module; deterministic given (observations, now); advisory-only.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from typing import Any

try:
    from scripts.linguistic_state_engine import (
        classify_linguistic_inflection,
        extract_linguistic_features,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from linguistic_state_engine import (  # type: ignore[no-redef]
        classify_linguistic_inflection,
        extract_linguistic_features,
    )

NARRATIVE_ENGINE_VERSION = "narrative_state_v1"

NARRATIVE_REGIMES: tuple[str, ...] = (
    "INSUFFICIENT_DATA", "EMERGING", "ACCUMULATING", "ACCELERATING",
    "CONTESTED", "BREAKING", "DOMINANT", "DECAYING",
)

RESERVED_NARRATIVE_REGIMES: tuple[str, ...] = (
    "DORMANT", "COHERING", "SATURATED", "REVERSING",
)

# Configured half-life priors (hours) by dominant source family.
NARRATIVE_HALF_LIFE_HOURS: dict[str, float] = {
    "prediction_market": 48.0,
    "news": 36.0,
    "regulatory_filing": 168.0,
    "ai_interpretation": 24.0,
    "unknown": 36.0,
}

CLUSTER_JACCARD = 0.22
MIN_OBS_FOR_STATE = 2
CHECKPOINT_HOURS = 24.0

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-']*")
_STOP = frozenset(
    "the a an of to in on for and or as at by with from is are was were be "
    "has have had will would could may might this that these those it its "
    "into over after says said new more most".split()
)


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOP and len(t) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _parse_iso(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    text = ts.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, x))))


def cluster_observations_into_narratives(
    observations: list[dict[str, Any]],
    *,
    jaccard_threshold: float = CLUSTER_JACCARD,
) -> list[dict[str, Any]]:
    """Greedy deterministic topic clustering over cluster-representative
    observations (syndicated duplicates follow their representative)."""
    reps = [
        o for o in observations
        if isinstance(o, dict) and o.get("is_cluster_representative", True)
    ]
    narratives: list[dict[str, Any]] = []
    for obs in sorted(reps, key=lambda o: str(o.get("retrieved_at_utc", ""))):
        toks = _tokens((obs.get("raw_title") or "") + " " + (obs.get("raw_text") or "")[:280])
        best, best_sim = None, 0.0
        for narrative in narratives:
            sim = _jaccard(toks, narrative["tokens"])
            if sim > best_sim:
                best, best_sim = narrative, sim
        if best is not None and best_sim >= jaccard_threshold:
            best["members"].append(obs)
            best["tokens"] |= toks
        else:
            narratives.append({"members": [obs], "tokens": set(toks)})

    # Attach non-representative duplicates to their representative's narrative.
    by_cluster: dict[str, dict[str, Any]] = {}
    for narrative in narratives:
        for member in narrative["members"]:
            cid = member.get("deduplication_cluster_id")
            if cid:
                by_cluster[cid] = narrative
    for obs in observations:
        if isinstance(obs, dict) and not obs.get("is_cluster_representative", True):
            narrative = by_cluster.get(obs.get("deduplication_cluster_id"))
            if narrative is not None:
                narrative["members"].append(obs)

    for narrative in narratives:
        top_tokens = sorted(narrative["tokens"])[:8]
        narrative["narrative_id"] = "NARR_" + hashlib.sha256(
            "|".join(top_tokens).encode()
        ).hexdigest()[:12]
        counts: dict[str, int] = {}
        for member in narrative["members"]:
            for tok in _tokens(member.get("raw_title") or ""):
                counts[tok] = counts.get(tok, 0) + 1
        canonical = sorted(counts, key=lambda t: (-counts[t], t))[:5]
        narrative["canonical_topic"] = " ".join(canonical) or "unlabelled"
    return narratives


def _strength_at(members: list[dict[str, Any]], at: datetime, half_life: float) -> float:
    total = 0.0
    for obs in members:
        ts = _parse_iso(obs.get("retrieved_at_utc"))
        if ts is None or ts > at:
            continue  # as-of: later observations never count backwards
        age_h = (at - ts).total_seconds() / 3600.0
        reliability = float(obs.get("source_reliability_prior", 0.4) or 0.4)
        independence = float(obs.get("independence_weight", 1.0) or 1.0)
        total += reliability * independence * (2.0 ** (-age_h / half_life))
    return total


def build_narrative_state(
    narrative: dict[str, Any],
    *,
    now: datetime,
    all_narratives: list[dict[str, Any]] | None = None,
    market_impulse: float | None = None,
) -> dict[str, Any]:
    """Full NarrativeState payload for one clustered narrative."""
    members = [m for m in narrative.get("members", []) if isinstance(m, dict)]
    timestamps = sorted(
        ts for ts in (_parse_iso(m.get("retrieved_at_utc")) for m in members) if ts
    )
    base: dict[str, Any] = {
        "narrative_id": narrative.get("narrative_id", ""),
        "canonical_topic": narrative.get("canonical_topic", ""),
        "timestamp_utc": now.isoformat(),
        "engine_version": NARRATIVE_ENGINE_VERSION,
        "item_count": len(members),
        "state": "INSUFFICIENT_DATA",
        "operational_regimes": list(NARRATIVE_REGIMES),
        "reserved_regimes_not_operational": list(RESERVED_NARRATIVE_REGIMES),
        "score_semantics": "heuristic_bounded_score_not_probability",
    }
    if len(members) < MIN_OBS_FOR_STATE or not timestamps:
        return base

    families: dict[str, float] = {}
    for m in members:
        fam = str(m.get("source_type", "unknown") or "unknown")
        families[fam] = families.get(fam, 0.0) + float(m.get("independence_weight", 1.0) or 1.0)
    dominant_family = max(families, key=lambda f: families[f])
    half_life = NARRATIVE_HALF_LIFE_HOURS.get(dominant_family, NARRATIVE_HALF_LIFE_HOURS["unknown"])

    from datetime import timedelta
    n_now = _strength_at(members, now, half_life)
    n_prev = _strength_at(members, now - timedelta(hours=CHECKPOINT_HOURS), half_life)
    n_prev2 = _strength_at(members, now - timedelta(hours=2 * CHECKPOINT_HOURS), half_life)
    velocity = n_now - n_prev
    acceleration = (n_now - n_prev) - (n_prev - n_prev2)

    # Novelty vs OTHER narratives (token overlap).
    novelty = None
    if all_narratives:
        best_sim = 0.0
        for other in all_narratives:
            if other.get("narrative_id") == narrative.get("narrative_id"):
                continue
            best_sim = max(best_sim, _jaccard(narrative.get("tokens", set()), other.get("tokens", set())))
        novelty = round(1.0 - best_sim, 6)

    span_hours = (timestamps[-1] - timestamps[0]).total_seconds() / 3600.0
    persistence = round(min(1.0, span_hours / (2.0 * half_life)), 6)

    # Linguistic aggregates (independence-weighted over available features).
    directions: list[float] = []
    certainty_vals: list[float] = []
    urgency_vals: list[float] = []
    emotion_vals: list[float] = []
    weights: list[float] = []
    for m in members:
        feats = m.get("linguistic_features") or {}
        if not feats.get("available"):
            continue
        w = float(m.get("independence_weight", 1.0) or 1.0)
        weights.append(w)
        directions.append(float(feats.get("direction_score", 0.0)) * w)
        certainty_vals.append(float(feats.get("certainty", 0.0)) * w)
        urgency_vals.append(float(feats.get("urgency", 0.0)) * w)
        emotion_vals.append(
            (float(feats.get("escalation", 0.0)) + float((feats.get("framing") or {}).get("threat_frame", 0.0))) * 0.5 * w
        )
    wsum = sum(weights) or 1.0
    mean_direction = sum(directions) / wsum if weights else None
    certainty = sum(certainty_vals) / wsum if weights else None
    urgency = sum(urgency_vals) / wsum if weights else None
    emotion = sum(emotion_vals) / wsum if weights else None

    # Contradiction: weighted dispersion of item direction scores.
    contradiction = None
    if len(weights) >= 2 and mean_direction is not None:
        raw_dirs = [d / w for d, w in zip(directions, weights)]
        var = sum(
            w * (d - mean_direction) ** 2
            for w, d in zip(weights, raw_dirs)
        ) / wsum
        contradiction = round(min(1.0, math.sqrt(max(0.0, var))), 6)
    if contradiction is None:
        contradiction_band = "UNKNOWN"
    elif contradiction < 0.15:
        contradiction_band = "LOW"
    elif contradiction < 0.35:
        contradiction_band = "MODERATE"
    elif contradiction < 0.6:
        contradiction_band = "HIGH"
    else:
        contradiction_band = "EXTREME"

    # Source entropy over per-family independence mass.
    total_mass = sum(families.values())
    entropy = None
    if total_mass > 0 and len(families) >= 2:
        shares = [v / total_mass for v in families.values()]
        entropy = round(
            min(1.0, -sum(p * math.log(p) for p in shares if p > 0) / math.log(len(shares))), 6
        )

    # Linguistic inflection: early-half vs late-half concatenated titles.
    ordered = sorted(members, key=lambda m: str(m.get("retrieved_at_utc", "")))
    half = max(1, len(ordered) // 2)
    early_text = ". ".join((m.get("raw_title") or "") for m in ordered[:half])
    late_text = ". ".join((m.get("raw_title") or "") for m in ordered[half:])
    inflection = classify_linguistic_inflection(
        extract_linguistic_features(early_text),
        extract_linguistic_features(late_text),
    )

    # Narrative temperature (sigmoid; anchored like market temperature).
    recent = [ts for ts in timestamps if (now - ts).total_seconds() / 3600.0 <= 48.0]
    items_per_day = len(recent) / 2.0
    sources_active = len({m.get("source_name") for m in members})
    impulse_term = abs(market_impulse) if isinstance(market_impulse, (int, float)) else 0.0
    temperature = _sigmoid(
        -2.2
        + 2.2 * min(1.0, items_per_day / (items_per_day + 3.0) * 2.0)
        + 0.8 * min(1.0, sources_active / 4.0)
        + 1.0 * min(1.0, impulse_term)
        + 0.8 * (urgency or 0.0)
        + 0.6 * (emotion or 0.0)
        + 0.4 * (contradiction or 0.0)
    )

    independent_count = round(sum(float(m.get("independence_weight", 1.0) or 1.0) for m in members), 3)
    duplicate_count = len(members) - len({m.get("deduplication_cluster_id") for m in members})

    # Regime classification (precedence order, explainable).
    hours_since_last = (now - timestamps[-1]).total_seconds() / 3600.0
    breaking = bool(market_impulse is not None and abs(market_impulse) >= 0.6) or (
        len(recent) >= 4 and (urgency or 0.0) > 0.3
    )
    if breaking:
        state = "BREAKING"
    elif contradiction_band in ("HIGH", "EXTREME"):
        state = "CONTESTED"
    elif n_now >= 2.5 and velocity >= 0:
        state = "DOMINANT"
    elif acceleration > 0.05 and velocity > 0:
        state = "ACCELERATING"
    elif velocity > 0.05:
        state = "ACCUMULATING"
    elif hours_since_last > 2.0 * half_life or velocity < -0.05:
        state = "DECAYING"
    else:
        state = "EMERGING"

    base.update({
        "state": state,
        "active_source_count": sources_active,
        "independent_source_count": independent_count,
        "duplicate_count": max(0, duplicate_count),
        "narrative_strength": round(n_now, 6),
        "narrative_velocity": round(velocity, 6),
        "narrative_acceleration": round(acceleration, 6),
        "novelty": novelty,
        "persistence": persistence,
        "contradiction": contradiction,
        "contradiction_band": contradiction_band,
        "certainty": round(certainty, 6) if certainty is not None else None,
        "urgency": round(urgency, 6) if urgency is not None else None,
        "emotional_activation": round(emotion, 6) if emotion is not None else None,
        "mean_direction": round(mean_direction, 6) if mean_direction is not None else None,
        "prediction_market_impulse": (
            round(float(market_impulse), 6) if isinstance(market_impulse, (int, float)) else None
        ),
        "source_entropy": entropy,
        "dominant_source_family": dominant_family,
        "half_life_hours": half_life,
        "half_life_source": "configured_prior",
        "narrative_temperature": round(temperature, 6),
        "linguistic_inflection": inflection,
        "first_observed_utc": timestamps[0].isoformat(),
        "last_observed_utc": timestamps[-1].isoformat(),
    })
    return base


__all__ = [
    "NARRATIVE_ENGINE_VERSION",
    "NARRATIVE_REGIMES",
    "RESERVED_NARRATIVE_REGIMES",
    "NARRATIVE_HALF_LIFE_HOURS",
    "cluster_observations_into_narratives",
    "build_narrative_state",
]
