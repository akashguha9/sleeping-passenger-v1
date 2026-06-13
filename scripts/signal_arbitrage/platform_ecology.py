"""Layer 1 — Platform Ecology Classifier.

A like on Instagram, an upvote on Reddit, and a repost on X do not mean the
same thing.  This module refuses to ingest "social sentiment" as one flat
variable: it maps each platform to a *signal ecology* with its own meaning,
expected distortion, half-life profile, and the token categories it is
trustworthy for.

    Signal Meaning = Platform x Audience x Format x Incentive x Moderation

Pure functions only.  ``classify_platform`` is the public entry point.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .util import clamp, r3

# Each platform profile carries:
#   role            — what stage of the food chain it sits at
#   meaning         — the dominant signal it produces
#   distortion      — how it lies / what to discount
#   half_life_days  — how fast a signal here decays (timing layer reads this)
#   trust           — base confidence that engagement here reflects real intent
#   strengths       — token categories this platform is a *reliable* source for
#   sovereignty     — owned-customer / owned-audience character (0 rented .. 1 owned)
PLATFORM_PROFILES: dict[str, dict[str, Any]] = {
    "reddit": {
        "role": "pre-market language formation",
        "meaning": "niche pain / future demand before brands can sell to it",
        "distortion": "niche may stay niche; contrarian over-representation",
        "half_life_days": 90.0,
        "trust": 0.80,
        "strengths": ("friction", "churn", "demand", "adoption"),
        "sovereignty": 0.25,
    },
    "x": {
        "role": "narrative combat / velocity",
        "meaning": "what people will fight about publicly; elite participation",
        "distortion": "outrage amplification; velocity != truth",
        "half_life_days": 7.0,
        "trust": 0.55,
        "strengths": ("hype", "policy", "demand"),
        "sovereignty": 0.20,
    },
    "twitter": {  # alias
        "role": "narrative combat / velocity",
        "meaning": "what people will fight about publicly; elite participation",
        "distortion": "outrage amplification; velocity != truth",
        "half_life_days": 7.0,
        "trust": 0.55,
        "strengths": ("hype", "policy", "demand"),
        "sovereignty": 0.20,
    },
    "tiktok": {
        "role": "discovery velocity / format mutation",
        "meaning": "what can spread before people know why they want it",
        "distortion": "shortest half-life; bot-prone; vanity views",
        "half_life_days": 3.0,
        "trust": 0.45,
        "strengths": ("hype", "aesthetic", "demand"),
        "sovereignty": 0.10,
    },
    "instagram": {
        "role": "aesthetic legitimacy / desirability",
        "meaning": "what looks desirable; brand aura",
        "distortion": "curation bias; bought followers common",
        "half_life_days": 14.0,
        "trust": 0.50,
        "strengths": ("aesthetic", "hype", "trust"),
        "sovereignty": 0.15,
    },
    "youtube": {
        "role": "durable authority / long-form conviction",
        "meaning": "what people will spend real time understanding",
        "distortion": "production polish mistaken for substance",
        "half_life_days": 120.0,
        "trust": 0.70,
        "strengths": ("adoption", "trust", "margin"),
        "sovereignty": 0.30,
    },
    "linkedin": {
        "role": "institutional legitimacy / B2B adoption",
        "meaning": "what professionals want to be seen believing",
        "distortion": "performative optimism; signaling > substance",
        "half_life_days": 60.0,
        "trust": 0.65,
        "strengths": ("adoption", "margin", "policy", "pricing_power"),
        "sovereignty": 0.35,
    },
    "substack": {
        "role": "creator-owned trust rail",
        "meaning": "recurring paid intellectual relationship",
        "distortion": "echo-chamber selection; small-N",
        "half_life_days": 45.0,
        "trust": 0.75,
        "strengths": ("trust", "sovereignty", "adoption"),
        "sovereignty": 0.80,
    },
    "discord": {
        "role": "private trust / closed-loop community",
        "meaning": "what people privately trust enough to organize around",
        "distortion": "unobservable; survivorship of insiders",
        "half_life_days": 30.0,
        "trust": 0.72,
        "strengths": ("trust", "adoption", "friction"),
        "sovereignty": 0.55,
    },
    "whatsapp": {
        "role": "private trust / closed-loop community",
        "meaning": "private word-of-mouth trust loop",
        "distortion": "unobservable; near-zero public signal",
        "half_life_days": 30.0,
        "trust": 0.72,
        "strengths": ("trust", "adoption"),
        "sovereignty": 0.55,
    },
    "telegram": {
        "role": "private trust / closed-loop community",
        "meaning": "private coordination + alpha leakage",
        "distortion": "pump-group manipulation risk",
        "half_life_days": 21.0,
        "trust": 0.50,
        "strengths": ("hype", "trust"),
        "sovereignty": 0.45,
    },
    "shopify": {
        "role": "merchant sovereignty / owned conversion",
        "meaning": "rented attention converted into owned customer equity",
        "distortion": "GMV without retention can mask churn",
        "half_life_days": 180.0,
        "trust": 0.85,
        "strengths": ("sovereignty", "demand", "pricing_power", "margin"),
        "sovereignty": 0.90,
    },
    "etsy": {
        "role": "curated niche marketplace / platform-mediated intent",
        "meaning": "niche discovery + buyer trust, but platform owns the buyer",
        "distortion": "revenue mistaken for sovereignty (platform owns ranking)",
        "half_life_days": 120.0,
        "trust": 0.70,
        "strengths": ("demand", "adoption"),
        "sovereignty": 0.40,
    },
}

# Token categories where a platform is NOT a trustworthy source get their
# contribution discounted downstream.  Generic fallback for unknown platforms.
_GENERIC = {
    "role": "unclassified ecology",
    "meaning": "unknown; treat engagement as flat/low-trust",
    "distortion": "unknown ecology — cannot weight; discount heavily",
    "half_life_days": 30.0,
    "trust": 0.30,
    "strengths": (),
    "sovereignty": 0.20,
}


@dataclass(frozen=True)
class PlatformEcology:
    platform: str
    role: str
    signal_meaning: str
    expected_distortion: str
    half_life_days: float
    sovereignty: float
    trust_weight: float          # base confidence in this ecology
    strength_categories: tuple[str, ...]
    confidence: float
    reason_codes: list[str] = field(default_factory=list)

    def category_weight(self, category: str) -> float:
        """Platform-specific trust weight for a token category in [0,1].

        A category the platform is a known-reliable source for keeps full
        trust; everything else is discounted to 60% of base trust.
        """
        base = self.trust_weight
        if category in self.strength_categories:
            return r3(base)
        return r3(base * 0.6)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["strength_categories"] = list(self.strength_categories)
        return d


def classify_platform(platform: str | None) -> PlatformEcology:
    """Classify a raw platform name into its signal ecology."""
    key = (platform or "").strip().lower()
    profile = PLATFORM_PROFILES.get(key)
    reasons: list[str] = []
    if profile is None:
        profile = _GENERIC
        confidence = 0.30
        reasons.append(f"UNKNOWN_PLATFORM:{key or '<empty>'}")
    else:
        confidence = clamp(profile["trust"])
        reasons.append(f"ECOLOGY:{profile['role']}")
        if profile["half_life_days"] <= 7.0:
            reasons.append("SHORT_HALF_LIFE_REQUIRES_FAST_TRANSFER")
        if profile["sovereignty"] >= 0.8:
            reasons.append("HIGH_SOVEREIGNTY_OWNED_DEMAND")
        elif profile["sovereignty"] <= 0.25:
            reasons.append("LOW_SOVEREIGNTY_RENTED_ATTENTION")
    return PlatformEcology(
        platform=key or "<empty>",
        role=profile["role"],
        signal_meaning=profile["meaning"],
        expected_distortion=profile["distortion"],
        half_life_days=float(profile["half_life_days"]),
        sovereignty=clamp(profile["sovereignty"]),
        trust_weight=clamp(profile["trust"]),
        strength_categories=tuple(profile["strengths"]),
        confidence=r3(confidence),
        reason_codes=reasons,
    )


def platform_ecology_score(ecologies: list[PlatformEcology]) -> dict[str, Any]:
    """Aggregate ecology quality across the platforms a signal appears on.

    Rewards *cross-ecology* presence (Reddit pain + LinkedIn adoption beats
    one loud platform) and trustworthy ecologies; penalizes signals that live
    only on short-half-life / low-trust surfaces.
    """
    if not ecologies:
        return {"score": 0.0, "n_platforms": 0, "reason_codes": ["NO_PLATFORM"]}
    trust = sum(e.trust_weight for e in ecologies) / len(ecologies)
    # Diversity bonus: distinct roles seen (capped at 4 → full bonus).
    distinct_roles = len({e.role for e in ecologies})
    diversity = clamp((distinct_roles - 1) / 3.0)
    score = clamp(0.7 * trust + 0.3 * diversity)
    reasons = [f"N_PLATFORMS:{len(ecologies)}", f"DISTINCT_ROLES:{distinct_roles}"]
    if distinct_roles >= 3:
        reasons.append("CROSS_ECOLOGY_PRESENCE")
    if all(e.half_life_days <= 7.0 for e in ecologies):
        reasons.append("ALL_SHORT_HALF_LIFE_FRAGILE")
        score = clamp(score - 0.15)
    return {
        "score": r3(score),
        "n_platforms": len(ecologies),
        "distinct_roles": distinct_roles,
        "mean_trust": r3(trust),
        "diversity": r3(diversity),
        "reason_codes": reasons,
    }


__all__ = [
    "PLATFORM_PROFILES",
    "PlatformEcology",
    "classify_platform",
    "platform_ecology_score",
]
