"""Layer 3 — Synthetic Liquidity Detector.

Bought followers, fake likes, generic comments and velocity spikes are
*synthetic liquidity*: surface motion without behavioral substance.

    Synthetic Ratio = Fake / Low-Quality Engagement  /  Total Engagement

This detector fuses several independent fingerprints into one contamination
score in [0,1] with reason codes.  It is intentionally additive-on-evidence:
each fingerprint can only *raise* contamination, so a clean signal stays clean.

Fingerprints
------------
  generic_comment_ratio  — share of comments that are bot-pattern boilerplate
  comment_repetition     — duplicated comment text
  velocity_anomaly       — engagement velocity far above the account baseline
  engagement_conversion  — high engagement, ~zero conversion (vanity)
  low_comment_density    — comments carry no semantic mass
  follower_engagement    — follower count wildly disproportionate to interaction
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .util import clamp, r3, safe_ratio

# Boilerplate the synthetic-engagement industry mass-produces.
_GENERIC_COMMENT_RE = re.compile(
    r"^\s*(nice( post| one)?|great|love (it|this)|amazing!*|so good|first|"
    r"🔥+|❤️+|👏+|wow!*|cool!*|awesome!*|follow back|check (my|out my) "
    r"(profile|page)|dm me)\s*!*\s*$",
    re.I,
)

WEIGHTS = {
    "generic_comment_ratio": 0.25,
    "comment_repetition": 0.20,
    "velocity_anomaly": 0.20,
    "engagement_conversion": 0.15,
    "low_comment_density": 0.10,
    "follower_engagement": 0.10,
}


@dataclass(frozen=True)
class ContaminationResult:
    contamination: float                 # 0 clean .. 1 fully synthetic
    fingerprints: dict[str, float]
    reason_codes: list[str] = field(default_factory=list)

    @property
    def authenticity(self) -> float:
        return r3(1.0 - self.contamination)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fingerprints"] = {k: r3(v) for k, v in self.fingerprints.items()}
        d["contamination"] = r3(self.contamination)
        d["authenticity"] = self.authenticity
        return d


def _generic_ratio(comments: list[str]) -> float:
    if not comments:
        return 0.0
    hits = sum(1 for c in comments if _GENERIC_COMMENT_RE.match(c.strip()))
    return safe_ratio(hits, len(comments))


def _repetition(comments: list[str]) -> float:
    norm = [re.sub(r"\W+", " ", c.lower()).strip() for c in comments if c.strip()]
    if len(norm) < 2:
        return 0.0
    return clamp(1.0 - safe_ratio(len(set(norm)), len(norm), 1.0))


def detect_synthetic_liquidity(
    *,
    comments: list[str] | None = None,
    views: float = 0.0,
    likes: float = 0.0,
    saves: float = 0.0,
    conversions: float = 0.0,
    followers: float = 0.0,
    velocity: float = 0.0,
    baseline_velocity: float = 0.0,
    comment_semantic_density: float | None = None,
) -> ContaminationResult:
    """Score synthetic contamination from engagement-shape fingerprints.

    All inputs are optional; missing dimensions simply don't contribute. The
    contamination is the weighted sum of fingerprints present, clamped to 1.
    """
    comments = comments or []
    fp: dict[str, float] = {}
    reasons: list[str] = []

    fp["generic_comment_ratio"] = _generic_ratio(comments)
    if fp["generic_comment_ratio"] >= 0.5:
        reasons.append("GENERIC_COMMENT_FLOOD")

    fp["comment_repetition"] = _repetition(comments)
    if fp["comment_repetition"] >= 0.4:
        reasons.append("DUPLICATED_COMMENTS")

    # Velocity anomaly: how many multiples above baseline (4x+ → maxed).
    if baseline_velocity > 0 and velocity > 0:
        mult = velocity / baseline_velocity
        fp["velocity_anomaly"] = clamp((mult - 1.0) / 3.0)
        if mult >= 4.0:
            reasons.append("VELOCITY_SPIKE")
    else:
        fp["velocity_anomaly"] = 0.0

    # Engagement → conversion mismatch: lots of likes/views, ~no conversion.
    engagement = likes + views * 0.01 + saves
    if engagement > 0:
        conv_rate = safe_ratio(conversions, engagement)
        # Below 0.1% conversion on meaningful engagement reads as vanity.
        fp["engagement_conversion"] = clamp(1.0 - conv_rate * 1000.0)
        if conversions == 0 and engagement >= 100:
            reasons.append("ENGAGEMENT_WITHOUT_CONVERSION")
    else:
        fp["engagement_conversion"] = 0.0

    if comment_semantic_density is not None and comments:
        fp["low_comment_density"] = clamp(1.0 - comment_semantic_density)
        if comment_semantic_density <= 0.15:
            reasons.append("LOW_COMMENT_SEMANTIC_DENSITY")
    else:
        fp["low_comment_density"] = 0.0

    # Follower / engagement disproportion: huge audience, tiny interaction.
    if followers >= 1000:
        engaged = likes + saves + len(comments)
        ratio = safe_ratio(engaged, followers)
        # Healthy organic engagement ~1-5%. Below 0.1% → bought audience.
        fp["follower_engagement"] = clamp(1.0 - ratio * 1000.0)
        if ratio <= 0.001:
            reasons.append("FOLLOWER_ENGAGEMENT_MISMATCH")
    else:
        fp["follower_engagement"] = 0.0

    contamination = clamp(sum(WEIGHTS[k] * fp[k] for k in WEIGHTS))
    if contamination <= 0.15:
        reasons.append("LOW_CONTAMINATION")
    elif contamination >= 0.6:
        reasons.append("HIGH_CONTAMINATION_SYNTHETIC")

    return ContaminationResult(
        contamination=contamination, fingerprints=fp, reason_codes=reasons
    )


__all__ = ["ContaminationResult", "detect_synthetic_liquidity", "WEIGHTS"]
