"""Signal Half-Life Estimator (HL) — P3 interpretation-defense module.

Ships the 2026-06-08 reflection's headline new variable: **half-life is the
missing durability dimension** (see docs/INTERPRETATION_DEFENSE_COMPONENT_MAP.md
and docs/reflections/2026-06-08_game_theory_half_life_reflection.md). The four
P2 modules score whether attention runs ahead of substance (DA), whether the
story exceeds the facts (NSG), who profits if you believe it (incentive), and
who might misread it (audience). NONE of them ask the orthogonal question this
reflection foregrounds:

    "Is this edge a snack, a signal, or an asset?" — i.e. how fast does it decay?

A short-half-life catalyst (a one-day price pop, a momentum/meme spike) benefits
the *house* (churn) more than the holder; a long-half-life catalyst (a structural
contract win, durable earnings re-rating) compounds. This module estimates the
decay of a candidate's edge and emits a `short_half_life_risk` (high = decays
fast = snack) plus a `half_life_class` in {DURABLE, SIGNAL, SNACK}.

    durability  = w·structural_evidence + w·fundamental_backing
                  + w·falsifiability − w·attention_decay − w·crowding
    short_half_life_risk = 100 · (1 − durability)
    lambda (per day) = ln(2) / half_life_days     (reported, advisory)

Conceptual lineage: scripts/asset_durability_filter.py (durability classes),
scripts/candidate_memory_decay.py (exp(-lambda·d) candidate decay),
scripts/late_adoption_lockout.py (crowding/late-entry). HL is the candidate-level
"edge durability" scorer on the clean fresh-discovery payload.

Data honesty: real attention / fundamentals feeds are usually absent for fresh
discovery, so HL derives weak proxies from evidence_type, catalyst text, and the
presence of a falsifiable invalidation condition, and marks missing fields. A
non-live candidate is NOT scored as live. The module can only warn / demote; it
never promotes, never invents a candidate, never unlocks execution. Advisory-only.
Pure module.
"""
from __future__ import annotations

import math
from typing import Any

try:
    from scripts.daily_payload import normalize_ticker
    from scripts.fresh_discovery_contract import VERIFIED_LIVE
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from daily_payload import normalize_ticker
    from fresh_discovery_contract import VERIFIED_LIVE


CLASS_DURABLE = "DURABLE"
CLASS_SIGNAL = "SIGNAL"
CLASS_SNACK = "SNACK"  # short half-life — the "snack" end of snack/signal/asset

# Approximate edge half-lives (calendar days) used only to report a decay rate
# lambda = ln(2) / half_life_days. These are honest order-of-magnitude priors,
# not measured constants; they exist so the advisory note can say "this edge
# halves in ~N days", never to authorise sizing.
_HALF_LIFE_DAYS = {CLASS_DURABLE: 90.0, CLASS_SIGNAL: 21.0, CLASS_SNACK: 3.0}

# Evidence-type → structural-durability prior (1.0 = most structural/durable).
_STRUCTURAL_PRIOR = {
    "LIVE_FILING_EVENT": 0.85,   # 8-K/10-Q contract/guidance — structural
    "LIVE_NEWS_EVENT": 0.50,     # news catalyst — medium decay
    "LIVE_PRICE_MOVER": 0.25,    # pure price/volume move — momentum, fast decay
}

# Catalyst-text cues. Structural words extend half-life; momentum/hype words
# shorten it. Substring match, lowercased.
_STRUCTURAL_WORDS = (
    "contract", "award", "guidance", "earnings", "revenue", "margin", "backlog",
    "approval", "fda", "acquisition", "buyback", "dividend", "filing", "10-k",
    "10-q", "8-k", "patent", "regulatory", "order book", "capacity",
)
_MOMENTUM_WORDS = (
    "rally", "surge", "spike", "squeeze", "meme", "viral", "buzz", "momentum",
    "trending", "hype", "soar", "pop", "frenzy", "short interest", "social",
)

_FUNDAMENTAL_FIELDS = ("earnings_growth", "revenue_growth", "margin_improvement", "filing_materiality")
_ATTENTION_FIELDS = ("social_velocity", "news_velocity", "search_spike", "price_move", "volume_move")


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _mean_present(data: dict[str, Any], fields: tuple[str, ...]) -> tuple[float, bool]:
    vals = [_clamp01(float(data[f])) for f in fields if data.get(f) is not None]
    return (sum(vals) / len(vals), True) if vals else (0.0, False)


def _is_live(candidate: dict[str, Any]) -> bool:
    return candidate.get("is_live") is True and candidate.get("source_health") == VERIFIED_LIVE


def _catalyst_bias(catalyst: str) -> tuple[float, list[str]]:
    """Return (-1..+1 durability bias, flags) from catalyst text cues."""
    text = (catalyst or "").lower()
    flags: list[str] = []
    structural = sum(1 for w in _STRUCTURAL_WORDS if w in text)
    momentum = sum(1 for w in _MOMENTUM_WORDS if w in text)
    if structural:
        flags.append("structural_catalyst_language")
    if momentum:
        flags.append("momentum_catalyst_language")
    raw = structural - momentum
    # Squash into a bounded bias so a keyword pile-up can't dominate.
    bias = max(-1.0, min(1.0, raw / 2.0))
    return bias, flags


def _class_for_risk(risk: float) -> str:
    # Bands are wide on the DURABLE end on purpose: offline fundamental proxies
    # are conservatively capped, so a structural filing with real fundamentals
    # and a falsifiable thesis lands ~40 risk yet IS the durable archetype. SNACK
    # is reserved for genuine momentum/no-substance edges (risk > 70).
    if risk <= 45.0:
        return CLASS_DURABLE
    if risk <= 70.0:
        return CLASS_SIGNAL
    return CLASS_SNACK


def score_signal_half_life(
    candidate: dict[str, Any],
    *,
    fundamentals: dict[str, Any] | None = None,
    attention: dict[str, Any] | None = None,
    crowding: dict[str, Any] | None = None,
    model_outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the half-life / edge-durability record for one clean candidate."""
    ticker = normalize_ticker(candidate.get("ticker"))
    flags: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []

    if not _is_live(candidate):
        return {
            "ticker": ticker,
            "short_half_life_risk": 0.0,
            "half_life_class": CLASS_SNACK,
            "durability": 0.0,
            "estimated_half_life_days": _HALF_LIFE_DAYS[CLASS_SNACK],
            "decay_lambda_per_day": round(math.log(2) / _HALF_LIFE_DAYS[CLASS_SNACK], 6),
            "half_life_flags": ["not_live_not_scored"],
            "missing_fields": ["live_evidence"],
            "warnings": ["candidate is not live; not scored as live durability"],
            "advisory_only": True,
        }

    fundamentals = dict(fundamentals or {})
    attention = dict(attention or {})
    crowding = dict(crowding or {})

    evidence_type = candidate.get("evidence_type")
    structural_prior = _STRUCTURAL_PRIOR.get(evidence_type, 0.30)

    # Fundamental backing — real feed if present, else weak evidence proxy.
    fund, fund_present = _mean_present(fundamentals, _FUNDAMENTAL_FIELDS)
    if not fund_present:
        fund = {"LIVE_FILING_EVENT": 0.45, "LIVE_NEWS_EVENT": 0.3, "LIVE_PRICE_MOVER": 0.1}.get(evidence_type, 0.15)
        missing.append("fundamental_backing")
        warnings.append("no fundamentals feed; durability under-evidenced")
    fundamental_backing = _clamp01(fund)

    # Attention decay risk — high attention with thin substance decays fast.
    att, att_present = _mean_present(attention, _ATTENTION_FIELDS)
    if not att_present:
        att = {"LIVE_PRICE_MOVER": 0.6, "LIVE_NEWS_EVENT": 0.45, "LIVE_FILING_EVENT": 0.3}.get(evidence_type, 0.4)
        missing.append("attention_feed")
        warnings.append("no attention feed; using evidence-type proxy")
    attention_decay = _clamp01(att) * (1.0 - fundamental_backing)

    # Falsifiability — a thesis with a stated invalidation condition is more
    # durable (it can be maintained, not just ridden).
    has_invalidation = bool((candidate.get("invalidation_condition") or "").strip())
    falsifiability = 0.7 if has_invalidation else 0.25
    if not has_invalidation:
        flags.append("no_invalidation_condition")

    # Catalyst language bias.
    catalyst_bias, cat_flags = _catalyst_bias(candidate.get("catalyst", ""))
    flags.extend(cat_flags)

    # Crowding / late adoption shortens the *remaining* half-life.
    crowd = _clamp01(float(crowding.get("crowding", crowding.get("late_adoption", 0.0)) or 0.0))
    if not crowding:
        missing.append("crowding_feed")

    durability = (
        0.30 * structural_prior
        + 0.25 * fundamental_backing
        + 0.15 * falsifiability
        + 0.15 * (0.5 + 0.5 * catalyst_bias)
        - 0.25 * attention_decay
        - 0.15 * crowd
    )
    durability = _clamp01(durability)
    short_half_life_risk = round(100.0 * (1.0 - durability), 4)
    half_life_class = _class_for_risk(short_half_life_risk)

    if half_life_class == CLASS_SNACK:
        flags.append("short_half_life_edge")
    if attention_decay >= 0.5 and fundamental_backing < 0.25:
        flags.append("attention_driven_decay")

    half_life_days = _HALF_LIFE_DAYS[half_life_class]
    return {
        "ticker": ticker,
        "short_half_life_risk": short_half_life_risk,
        "half_life_class": half_life_class,
        "durability": round(durability, 6),
        "structural_prior": round(structural_prior, 6),
        "fundamental_backing": round(fundamental_backing, 6),
        "attention_decay": round(attention_decay, 6),
        "falsifiability": round(falsifiability, 6),
        "catalyst_bias": round(catalyst_bias, 6),
        "crowding": round(crowd, 6),
        "estimated_half_life_days": half_life_days,
        "decay_lambda_per_day": round(math.log(2) / half_life_days, 6),
        "half_life_flags": flags,
        "missing_fields": missing,
        "warnings": warnings,
        "advisory_only": True,
    }


__all__ = [
    "CLASS_DURABLE",
    "CLASS_SIGNAL",
    "CLASS_SNACK",
    "score_signal_half_life",
]
