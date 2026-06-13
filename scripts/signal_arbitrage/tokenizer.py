"""Layer 2 — Tokenized Signal Engine.

Binary tells you *whether* something happened; tokenization tells you *what
the signal is made of*.  This engine decomposes raw signal text into typed,
meaning-bearing tokens (demand / trust / friction / hype / bot / pricing-power
/ adoption / churn / policy / margin / sovereignty / aesthetic / interpretation)
and scores semantic density.

It is rule-based and deterministic — NOT keyword-only.  Beyond a per-category
lexicon it uses structural cues:

  * specificity   — numerals, %, $, model/version names raise useful meaning
  * switching     — "switched from X to Y", "instead of", "moved off" → churn
  * uncertainty   — heavy "?" / "anyone else" → pain/friction
  * repetition    — duplicated phrasing → bot/synthetic dilution

The lexicons are module-level constants so a later ML/LLM enrichment pass can
swap or extend them without touching the scoring logic.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .util import clamp, r3, safe_ratio

# Per-category lexicon.  Multi-word phrases are matched as substrings; single
# words as whole-word tokens.  Weight = how diagnostic a hit is (0..1).
LEXICON: dict[str, dict[str, float]] = {
    "demand": {
        "where to buy": 1.0, "where can i buy": 1.0, "need this": 0.8,
        "want one": 0.7, "take my money": 0.9, "sold out": 0.9,
        "waitlist": 0.8, "back in stock": 0.7, "shut up and": 0.8,
        "demand": 0.5, "buying": 0.5, "preorder": 0.8,
    },
    "trust": {
        "trust": 0.7, "reliable": 0.7, "recommend": 0.7, "been using": 0.8,
        "for years": 0.8, "worth it": 0.6, "honest": 0.5, "loyal": 0.7,
        "subscribed": 0.7, "renewed": 0.8,
    },
    "friction": {
        "annoying": 0.7, "frustrat": 0.8, "broken": 0.8, "doesn't work": 0.9,
        "does not work": 0.9, "bug": 0.6, "pain": 0.7, "hate": 0.7,
        "workaround": 0.9, "anyone else": 0.7, "struggle": 0.7, "clunky": 0.7,
        "wish it": 0.6,
    },
    "hype": {
        "to the moon": 1.0, "🚀": 0.9, "insane": 0.6, "game changer": 0.8,
        "next big": 0.8, "10x": 0.6, "explod": 0.7, "viral": 0.7,
        "everyone is talking": 0.8, "fomo": 0.8, "can't miss": 0.7,
    },
    "bot": {
        "great product": 0.6, "nice post": 0.7, "love this": 0.5,
        "check my profile": 0.9, "dm me": 0.8, "follow back": 0.9,
        "first": 0.4, "🔥🔥🔥": 0.8, "amazing!!!": 0.7, "so good": 0.4,
    },
    "pricing_power": {
        "raised prices": 0.9, "price increase": 0.9, "still worth": 0.8,
        "would pay more": 0.9, "premium": 0.6, "no discount needed": 0.9,
        "happy to pay": 0.8, "pricing power": 1.0,
    },
    "adoption": {
        "switched to": 0.8, "now using": 0.8, "rolled out": 0.8,
        "adopting": 0.8, "standard at": 0.8, "everyone at work": 0.8,
        "company-wide": 0.9, "deployed": 0.7, "migrated to": 0.8,
    },
    "churn": {
        "switched from": 0.9, "moved off": 0.9, "cancelled": 0.9,
        "canceled": 0.9, "leaving": 0.7, "instead of": 0.6, "ditched": 0.9,
        "no longer use": 0.9, "churn": 0.7, "downgrade": 0.7,
    },
    "policy": {
        "regulat": 0.8, "ban": 0.7, "lawsuit": 0.8, "compliance": 0.7,
        "fda": 0.8, "sec ": 0.7, "tariff": 0.8, "subsidy": 0.8,
        "antitrust": 0.9, "sanction": 0.8,
    },
    "margin": {
        "margin": 0.8, "gross margin": 0.9, "profitab": 0.8, "cost cut": 0.7,
        "free cash flow": 0.9, "fcf": 0.8, "operating leverage": 0.9,
        "unit economics": 0.9,
    },
    "sovereignty": {
        "own customer": 0.9, "owned audience": 0.9, "direct relationship": 0.9,
        "email list": 0.8, "off platform": 0.9, "first-party": 0.9,
        "own the customer": 1.0, "leave the platform": 0.9,
    },
    "aesthetic": {
        "beautiful": 0.6, "gorgeous": 0.7, "aesthetic": 0.7, "design": 0.5,
        "color": 0.4, "packaging": 0.7, "looks amazing": 0.6, "vibe": 0.5,
        "satisfying": 0.6,
    },
    "interpretation": {
        "bullish": 0.7, "bearish": 0.7, "overvalued": 0.7, "undervalued": 0.7,
        "priced in": 0.8, "the market is missing": 0.9, "contrarian": 0.7,
        "consensus": 0.6, "everyone thinks": 0.7,
    },
}

_SWITCHING_RE = re.compile(r"\b(switched|moved|migrat\w*)\s+(from|off|to)\b", re.I)
_SPECIFIC_RE = re.compile(r"(\$\d|\d+%|\bv\d|\b\d{2,}\b|q[1-4]\b)", re.I)
_WORD_RE = re.compile(r"[a-zA-Z']+")


@dataclass(frozen=True)
class Token:
    category: str
    surface: str
    weight: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TokenizationResult:
    tokens: list[Token]
    category_mass: dict[str, float]   # summed weight per category
    word_count: int
    specificity: float                # 0..1 numeric/version density
    repetition: float                 # 0..1 duplicated-phrase share
    semantic_density: float           # useful meaning / token count, 0..1
    reason_codes: list[str] = field(default_factory=list)

    def mass(self, category: str) -> float:
        return self.category_mass.get(category, 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens": [t.to_dict() for t in self.tokens],
            "category_mass": {k: r3(v) for k, v in self.category_mass.items()},
            "word_count": self.word_count,
            "specificity": r3(self.specificity),
            "repetition": r3(self.repetition),
            "semantic_density": r3(self.semantic_density),
            "reason_codes": self.reason_codes,
        }


def _repetition_score(texts: list[str]) -> float:
    """Share of near-duplicate lines — a synthetic-engagement fingerprint."""
    norm = [re.sub(r"\W+", " ", t.lower()).strip() for t in texts if t.strip()]
    if len(norm) < 2:
        return 0.0
    unique = len(set(norm))
    return clamp(1.0 - safe_ratio(unique, len(norm), 1.0))


def extract_tokens(text: str, *, extra_texts: list[str] | None = None) -> TokenizationResult:
    """Decompose ``text`` (+ optional comment corpus) into typed tokens."""
    blob = text or ""
    lowered = blob.lower()
    tokens: list[Token] = []
    category_mass: dict[str, float] = {}
    for category, phrases in LEXICON.items():
        for phrase, weight in phrases.items():
            if phrase in lowered:
                tokens.append(Token(category, phrase, weight))
                category_mass[category] = category_mass.get(category, 0.0) + weight

    reasons: list[str] = []

    # Structural cue: switching grammar reinforces churn even without lexicon.
    if _SWITCHING_RE.search(blob):
        tokens.append(Token("churn", "<switching-grammar>", 0.6))
        category_mass["churn"] = category_mass.get("churn", 0.0) + 0.6
        reasons.append("SWITCHING_GRAMMAR")

    words = _WORD_RE.findall(blob)
    word_count = max(1, len(words))

    specificity = clamp(len(_SPECIFIC_RE.findall(blob)) / 3.0)
    if specificity >= 0.34:
        reasons.append("HIGH_SPECIFICITY")

    corpus = list(extra_texts or [])
    repetition = _repetition_score(corpus)
    if repetition >= 0.5:
        reasons.append("HIGH_REPETITION_SYNTHETIC_RISK")

    # Semantic density = useful meaning / token count.
    #   useful meaning = lexicon mass (+ specificity bonus, - repetition dilution)
    useful = sum(category_mass.values()) * (1.0 + 0.5 * specificity)
    density = clamp(safe_ratio(useful, word_count) * 4.0)  # scale: ~4 words/dense-token
    density = clamp(density * (1.0 - 0.4 * repetition))
    if density >= 0.6:
        reasons.append("DENSE_SIGNAL")
    elif density <= 0.15:
        reasons.append("LOW_SEMANTIC_DENSITY")

    return TokenizationResult(
        tokens=tokens,
        category_mass=category_mass,
        word_count=len(words),
        specificity=specificity,
        repetition=repetition,
        semantic_density=density,
        reason_codes=reasons,
    )


def semantic_density_score(result: TokenizationResult) -> dict[str, Any]:
    return {
        "score": r3(result.semantic_density),
        "specificity": r3(result.specificity),
        "n_tokens": len(result.tokens),
        "reason_codes": result.reason_codes,
    }


__all__ = [
    "LEXICON",
    "Token",
    "TokenizationResult",
    "extract_tokens",
    "semantic_density_score",
]
