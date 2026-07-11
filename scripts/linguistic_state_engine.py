"""Linguistic state engine — deterministic, versioned, honest text features.

Extracts explainable linguistic-state features from headline/summary text
for the Narrative Cascade layer.  Two feature families, kept distinct:

1. **Natural-language state features** — direction, certainty, modality,
   urgency, escalation/de-escalation, agency, causal assertiveness,
   temporal framing.  Deterministic lexicon scoring (stdlib only; no
   model dependency), versioned so scores are reproducible.

2. **NLP-INSPIRED LINGUISTIC FRAMING HEURISTICS** — presupposition,
   inevitability, scarcity/threat/opportunity frames, authority/consensus
   invocation, future pacing.  These are *text descriptors inspired by
   Neuro-Linguistic Programming vocabulary*, NOT established neuroscience
   and NOT evidence of psychological influence.  Every payload stamps:

       feature_type       = "LINGUISTIC_HEURISTIC"
       validation_status  = "UNVALIDATED"

   The research question they exist for is whether observable framing
   changes precede attention/recognition/response changes — nothing more.

Honesty contract
----------------
* Empty/short/non-English-looking text degrades to ``available=False``
  with a reason, never fabricated zeros.
* Scores are bounded [0,1] lexicon-hit densities — not probabilities,
  not psychological measurements.
* ``linguistic_inflection`` compares two feature snapshots and labels the
  *change*, with a configurable materiality threshold.

Safety: pure module; no network, no execution surface.
"""

from __future__ import annotations

import math
import re
from typing import Any

LINGUISTIC_ENGINE_VERSION = "lexical_v1"
FEATURE_TYPE = "LINGUISTIC_HEURISTIC"
VALIDATION_STATUS = "UNVALIDATED"

MIN_TOKENS = 4

# ---------------------------------------------------------------------------
# Versioned lexicons (lowercase). Deliberately small, auditable, and
# documented — these are the entire model.
# ---------------------------------------------------------------------------

_LEX: dict[str, tuple[str, ...]] = {
    "certainty_high": (
        "will", "confirmed", "certain", "definitely", "inevitable",
        "guaranteed", "official", "announced", "approved", "signed",
        "finalized", "finalised", "must",
    ),
    "certainty_low": (
        "may", "might", "could", "possibly", "rumored", "rumoured",
        "unverified", "unclear", "uncertain", "speculation", "reportedly",
        "alleged", "considering", "potential", "perhaps",
    ),
    "urgency": (
        "immediately", "urgent", "now", "emergency", "imminent", "breaking",
        "deadline", "rush", "critical", "overnight", "today", "tonight",
    ),
    "escalation": (
        "escalate", "escalates", "escalating", "escalation", "worsen",
        "worsening", "intensify", "intensifies", "intensifying", "surge",
        "surges", "spiral", "crisis", "collapse", "war", "strike",
        "retaliate", "retaliation", "sanction", "sanctions", "shortage",
        "systemic",
    ),
    "de_escalation": (
        "resolve", "resolved", "resolution", "ceasefire", "de-escalate",
        "normalize", "normalise", "stabilize", "stabilise", "ease", "eases",
        "easing", "truce", "agreement", "settle", "settled", "recovery",
        "restored", "calm",
    ),
    "positive_direction": (
        "beat", "beats", "growth", "record", "surge", "gain", "gains",
        "upgrade", "upgraded", "profit", "expansion", "wins", "win",
        "approval", "breakthrough", "boost", "boosts", "raises",
    ),
    "negative_direction": (
        "miss", "misses", "loss", "losses", "decline", "declines", "cut",
        "cuts", "downgrade", "downgraded", "bankruptcy", "default", "fraud",
        "recall", "lawsuit", "halt", "halted", "plunge", "plunges", "warn",
        "warns", "warning", "layoff", "layoffs", "shutdown",
    ),
    "causal_assertive": (
        "because", "due to", "caused", "causes", "leads to", "led to",
        "results in", "resulted in", "drives", "driven by", "forces",
        "forced", "triggers", "triggered",
    ),
    "future_orientation": (
        "will", "expect", "expects", "expected", "forecast", "forecasts",
        "outlook", "guidance", "plans", "planned", "upcoming", "next year",
        "next quarter", "by 2026", "by 2027", "roadmap",
    ),
    # --- NLP-inspired framing heuristics (labelled UNVALIDATED) ---
    "presupposition": (
        "continues to", "still", "again", "further", "remains", "resumed",
        "yet another", "as expected", "once more",
    ),
    "inevitability": (
        "inevitable", "unstoppable", "irreversible", "only a matter of time",
        "bound to", "certain to", "cannot be avoided", "no way back",
    ),
    "scarcity_frame": (
        "shortage", "scarce", "scarcity", "limited supply", "running out",
        "tight supply", "constraint", "constrained", "rationing", "depleted",
    ),
    "threat_frame": (
        "threat", "threatens", "risk", "risks", "danger", "dangerous",
        "warning", "vulnerable", "exposure", "crisis", "fear", "fears",
    ),
    "opportunity_frame": (
        "opportunity", "opportunities", "boom", "winner", "winners",
        "beneficiary", "beneficiaries", "upside", "tailwind", "tailwinds",
        "gold rush", "opening",
    ),
    "authority_invocation": (
        "officials", "regulator", "regulators", "government", "minister",
        "fed", "central bank", "white house", "supreme court", "according to",
        "experts", "analysts",
    ),
    "consensus_invocation": (
        "everyone", "widely expected", "consensus", "most analysts",
        "broad agreement", "unanimous", "markets agree", "widely believed",
    ),
    "future_pacing": (
        "imagine", "soon", "prepare for", "get ready", "brace for",
        "coming months", "coming weeks", "on the horizon", "ahead",
    ),
}

_TOKEN_RE = re.compile(r"[a-z][a-z\-']*")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _hit_density(text_lower: str, tokens: list[str], lexicon: tuple[str, ...]) -> float:
    """Bounded phrase/token hit density: hits per 20 tokens, clipped to 1."""
    if not tokens:
        return 0.0
    hits = 0
    token_set = set(tokens)
    for entry in lexicon:
        if " " in entry or "-" in entry:
            if entry in text_lower:
                hits += 1
        elif entry in token_set:
            hits += 1
    return min(1.0, hits / max(1.0, len(tokens) / 20.0) / 3.0)


def _looks_english(tokens: list[str], raw: str) -> bool:
    if not raw:
        return False
    ascii_ratio = sum(1 for c in raw if ord(c) < 128) / max(1, len(raw))
    return ascii_ratio > 0.8 and bool(tokens)


def extract_linguistic_features(text: str | None) -> dict[str, Any]:
    """Extract the full linguistic-state feature payload for one text."""
    base: dict[str, Any] = {
        "available": False,
        "reason": None,
        "engine_version": LINGUISTIC_ENGINE_VERSION,
        "feature_type": FEATURE_TYPE,
        "validation_status": VALIDATION_STATUS,
        "token_count": 0,
    }
    if not isinstance(text, str) or not text.strip():
        base["reason"] = "empty_text"
        return base
    raw = text.strip()
    tokens = _tokens(raw)
    base["token_count"] = len(tokens)
    if len(tokens) < MIN_TOKENS:
        base["reason"] = "too_short"
        return base
    if not _looks_english(tokens, raw):
        base["reason"] = "non_english_or_non_text"
        return base

    lower = raw.lower()
    scores = {
        name: round(_hit_density(lower, tokens, lex), 6)
        for name, lex in _LEX.items()
    }

    certainty = scores["certainty_high"] - scores["certainty_low"]
    direction_raw = scores["positive_direction"] - scores["negative_direction"]
    if scores["positive_direction"] > 0 and scores["negative_direction"] > 0:
        direction_label = "MIXED"
    elif direction_raw > 0:
        direction_label = "POSITIVE"
    elif direction_raw < 0:
        direction_label = "NEGATIVE"
    else:
        direction_label = "NEUTRAL"
    escalation_net = scores["escalation"] - scores["de_escalation"]

    # Agency: crude active-voice proxy — share of sentences whose first
    # token is a plausible actor (capitalized non-stopword) followed by a
    # verb-ish token. Deterministic and honest about being a heuristic.
    sentences = [s.strip() for s in re.split(r"[.!?]", raw) if s.strip()]
    active_hits = 0
    for s in sentences:
        words = s.split()
        if len(words) >= 2 and words[0][:1].isupper() and words[1].lower().endswith(("s", "ed", "es")):
            active_hits += 1
    agency_strength = round(active_hits / len(sentences), 6) if sentences else 0.0

    return {
        **base,
        "available": True,
        "direction_label": direction_label,
        "direction_score": round(max(-1.0, min(1.0, direction_raw * 3.0)), 6),
        "certainty": round(max(-1.0, min(1.0, certainty * 3.0)), 6),
        "certainty_high": scores["certainty_high"],
        "certainty_low": scores["certainty_low"],
        "urgency": scores["urgency"],
        "escalation": scores["escalation"],
        "de_escalation": scores["de_escalation"],
        "escalation_net": round(max(-1.0, min(1.0, escalation_net * 3.0)), 6),
        "causal_assertiveness": scores["causal_assertive"],
        "future_orientation": scores["future_orientation"],
        "agency_strength": agency_strength,
        "framing": {
            "presupposition": scores["presupposition"],
            "inevitability": scores["inevitability"],
            "scarcity_frame": scores["scarcity_frame"],
            "threat_frame": scores["threat_frame"],
            "opportunity_frame": scores["opportunity_frame"],
            "authority_invocation": scores["authority_invocation"],
            "consensus_invocation": scores["consensus_invocation"],
            "future_pacing": scores["future_pacing"],
            "feature_type": FEATURE_TYPE,
            "validation_status": VALIDATION_STATUS,
            "limitations": [
                "lexicon hit-densities on short text",
                "not evidence of psychological influence",
                "English-only heuristics",
            ],
        },
    }


# ---------------------------------------------------------------------------
# Linguistic inflection: change between two snapshots
# ---------------------------------------------------------------------------

INFLECTION_LABELS: tuple[str, ...] = (
    "CERTAINTY_RISING", "UNCERTAINTY_RISING", "ESCALATING", "DE_ESCALATING",
    "SCOPE_EXPANDING", "SCOPE_CONTRACTING", "NO_MATERIAL_CHANGE",
    "INSUFFICIENT_DATA",
)

DEFAULT_INFLECTION_THRESHOLD = 0.10


def classify_linguistic_inflection(
    earlier: dict[str, Any] | None,
    later: dict[str, Any] | None,
    *,
    threshold: float = DEFAULT_INFLECTION_THRESHOLD,
) -> dict[str, Any]:
    """Label the CHANGE in linguistic state between two feature payloads.

    Returns every label whose delta exceeds the materiality threshold
    (a narrative can be simultaneously ESCALATING and CERTAINTY_RISING),
    or NO_MATERIAL_CHANGE / INSUFFICIENT_DATA.
    """
    if (
        not isinstance(earlier, dict) or not earlier.get("available")
        or not isinstance(later, dict) or not later.get("available")
    ):
        return {
            "labels": ["INSUFFICIENT_DATA"],
            "deltas": {},
            "threshold": threshold,
            "engine_version": LINGUISTIC_ENGINE_VERSION,
        }
    deltas = {
        "certainty": round(float(later["certainty"]) - float(earlier["certainty"]), 6),
        "urgency": round(float(later["urgency"]) - float(earlier["urgency"]), 6),
        "escalation_net": round(
            float(later["escalation_net"]) - float(earlier["escalation_net"]), 6
        ),
        "causal_assertiveness": round(
            float(later["causal_assertiveness"]) - float(earlier["causal_assertiveness"]), 6
        ),
        "scope": round(
            float(later["framing"]["threat_frame"])
            + float(later["framing"]["scarcity_frame"])
            - float(earlier["framing"]["threat_frame"])
            - float(earlier["framing"]["scarcity_frame"]),
            6,
        ),
    }
    labels: list[str] = []
    if deltas["certainty"] >= threshold:
        labels.append("CERTAINTY_RISING")
    elif deltas["certainty"] <= -threshold:
        labels.append("UNCERTAINTY_RISING")
    if deltas["escalation_net"] >= threshold or deltas["urgency"] >= threshold:
        labels.append("ESCALATING")
    elif deltas["escalation_net"] <= -threshold:
        labels.append("DE_ESCALATING")
    if deltas["scope"] >= threshold:
        labels.append("SCOPE_EXPANDING")
    elif deltas["scope"] <= -threshold:
        labels.append("SCOPE_CONTRACTING")
    if not labels:
        labels = ["NO_MATERIAL_CHANGE"]
    return {
        "labels": labels,
        "deltas": deltas,
        "threshold": threshold,
        "engine_version": LINGUISTIC_ENGINE_VERSION,
    }


__all__ = [
    "LINGUISTIC_ENGINE_VERSION",
    "FEATURE_TYPE",
    "VALIDATION_STATUS",
    "INFLECTION_LABELS",
    "extract_linguistic_features",
    "classify_linguistic_inflection",
]
