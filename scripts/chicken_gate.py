"""Chicken Gate v1.1 — hardened freshness + asymmetry + node-evidence gate.

Consolidation facade, not a new pile.  Wires existing layers into one
demote-only scoring pipeline with hard flags, evidence-confidence haircuts,
and an exact value-extraction ledger:

* ``signal_decay_waste.compute_decay_factor``   — thesis half-life decay
* ``crowding_detector.compute_crowding_context`` — crowding -> IAP derivation
* ``late_adoption_lockout`` thresholds           — parrot-ceiling IAP mapping
* ``advisory_contract``                          — the one true safety stamp
* catalyst-text durability word lists ported from
  ``feature/p2-interpretation-defense-expansion:scripts/signal_half_life_estimator.py``
  (SNACK 3d / SIGNAL 21d / DURABLE 90d half-life priors)
* ``data/daily_payload/verified_current_holdings.json`` — operator-fit truth

v1.1 doctrine changes over v1.0 (all demote-only):

1.  Raw inputs are no longer trusted: every component carries an evidence
    confidence C_i in [0,1] and is validated as ``score * (0.5 + 0.5*C_i)``.
    Downstream stages consume RAW_VALIDATED_SCORE; the difference is
    reported as RAW_INFLATION_LEAKAGE.
2.  Silence is suspicious, not safe: with incomplete IAP evidence the
    effective IAP is floored at ``5 + 3*(1 - confidence)`` — total silence
    lands exactly on the >=8 hard block.  Complete evidence earns the right
    to a low IAP.
3.  The gambler's-fallacy guard is negation-aware: explicitly negated or
    rejected reversal language does not flag; unbacked reversal language
    hard-blocks; backed reversal language warns
    (REVERSAL_REQUIRES_NODE_CONFIRMATION).
4.  Freshness gains catalyst-date hard expiry (past catalyst + grace with
    unknown outcome = SPOILED = hard block), an 0.85 confidence haircut for
    unknown first-signal date, and FROZEN requires explicit justification.
5.  Operator fit is computed from verified holdings when available
    (ticker/sector/lineage overlap + concentration); manual score still
    wins; absence degrades to fit 5 with a 0.90 confidence multiplier.

Invariants (tested):  every stage multiplier m_i satisfies 0 <= m_i <= 1;
FINAL_SCORE <= RAW_VALIDATED_SCORE <= RAW_TRADE_SCORE;
sum(ledger points eaten) == RAW_VALIDATED_SCORE - FINAL_SCORE within 0.01.

Advisory-only.  No broker calls, no order surface, no execution language.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.advisory_contract import (
    advisory_safety_stamps,
    human_only_stamp,
)
from scripts.crowding_detector import compute_crowding_context
from scripts.late_adoption_lockout import LALO_SATURATION_WARNING
from scripts.signal_decay_waste import compute_decay_factor

SCORING_PROFILE_VERSION = "chicken-gate-v1.1"

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

ASSET_LINEAGES: tuple[str, ...] = (
    "COMPOUNDER", "CYCLICAL", "DISTRESSED", "NARRATIVE", "MOMENTUM",
    "EVENT_DRIVEN", "COMMODITY_PROXY", "DEFENCE", "DIVIDEND", "PLATFORM",
    "REGULATORY", "UNKNOWN",
)

LINEAGE_HALF_LIFE_DAYS: dict[str, float] = {
    "NARRATIVE": 7.0,
    "MOMENTUM": 7.0,
    "EVENT_DRIVEN": 14.0,      # catalyst-date driven; expiry logic dominates
    "COMMODITY_PROXY": 14.0,
    "DISTRESSED": 21.0,
    "CYCLICAL": 30.0,
    "REGULATORY": 30.0,
    "DEFENCE": 45.0,
    "PLATFORM": 60.0,
    "COMPOUNDER": 90.0,
    "DIVIDEND": 120.0,
    "UNKNOWN": 21.0,
}

FRESHNESS_STATES: tuple[str, ...] = (
    "FRESH", "AGING", "NEAR_EXPIRY", "SPOILED", "FROZEN", "INSUFFICIENT_EVIDENCE",
)

NODE_CHANGE_EVIDENCE_VALUES: tuple[str, ...] = (
    "SUPPLY_CHANGE", "DEMAND_CHANGE", "MANAGEMENT_CHANGE",
    "REGULATORY_CHANGE", "FLOW_CHANGE", "FUNDAMENTAL_CHANGE", "NONE",
)

GATE_BUY_ALLOWED = "BUY_ALLOWED"
GATE_BUY_LIMITED = "BUY_LIMITED"
GATE_WATCHLIST = "WATCHLIST"
GATE_BUY_BLOCKED = "BUY_BLOCKED"

_GATE_RANK = {
    GATE_BUY_BLOCKED: 0,
    GATE_WATCHLIST: 1,
    GATE_BUY_LIMITED: 2,
    GATE_BUY_ALLOWED: 3,
}

# Raw-score weights (v1.1 spec).  Recalibrate only at N_closed >= 50.
RAW_WEIGHTS: dict[str, float] = {
    "house_edge": 0.25,
    "input_quality": 0.20,
    "process_integrity": 0.15,
    "load_bearing_node": 0.20,
    "label_authenticity": 0.10,
    "residual_bone_value": 0.10,
}

NEUTRAL_COMPONENT_SCORE = 5.0
NEUTRAL_LABEL_AUTHENTICITY = 0.5
NEUTRAL_BONE_VALUE = 0.3          # stored 0-1, scaled x10 into the raw score
NEUTRAL_CHANNEL_PREMIUM = 5.0
NEUTRAL_OPERATOR_FIT = 5.0
MISSING_CONFIDENCE_DEFAULT = 0.5  # confidence not stated -> half-trust
MISSING_SCORE_CONFIDENCE = 0.0    # score itself absent -> zero-trust neutral

FIRST_SIGNAL_UNKNOWN_MULTIPLIER = 0.85
OPERATOR_FIT_MISSING_CONFIDENCE = 0.90
CATALYST_GRACE_DAYS_DEFAULT = 5.0

IAP_HARD_BLOCK_THRESHOLD = 8.0
PROCESS_INTEGRITY_HARD_BLOCK = 3.0
LABEL_AUTHENTICITY_HARD_BLOCK = 0.3
LABEL_PREMIUM_HIGH = 6.0
SPOILED_FRESHNESS_THRESHOLD = 0.3
CHANNEL_UNVERIFIED_CAP_THRESHOLD = 8.0
OPERATOR_FIT_CAP_THRESHOLD = 4.0

INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

# ---------------------------------------------------------------------------
# Gambler's-fallacy guard: phrases + negation awareness
# ---------------------------------------------------------------------------

GAMBLERS_FALLACY_PHRASES: tuple[str, ...] = (
    "fallen too much",
    "fallen too far",
    "due to bounce",
    "due for a bounce",
    "due a bounce",
    "oversold",
    "overbought",
    "has to recover",
    "must recover",
    "has to bounce",
    "must bounce",
    "should recover",
    "gone up too much",
    "risen too much",
    "must cool",
    "mean reversion",
    "due for correction",
    "due for a correction",
    "due a correction",
    "due to fall",
    "due for a fall",
    "due to rise",
    "due for a rise",
    "cannot go lower",
    "can't go lower",
    "cannot go higher",
    "can't go higher",
    "cannot fall further",
    "can't fall further",
    "this streak cannot continue",
    "streak cannot continue",
    "owes me",
    "owes a",
)

# Streak-superstition shapes that need a regex ("after three losses the next
# one should win").
GAMBLERS_FALLACY_REGEXES: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"after\s+\S+\s+loss(?:es)?\b.{0,60}?\b(?:should|must|will)\s+win",
        re.IGNORECASE,
    ),
    re.compile(
        r"after\s+\S+\s+(?:red|down)\s+days?\b.{0,60}?\b(?:should|must|will)\s+"
        r"(?:bounce|recover|rise)",
        re.IGNORECASE,
    ),
)

# Tokens that negate/reject a reversal phrase when they appear in the same
# sentence segment shortly before it.  "cannot" is deliberately absent — it
# is part of fallacy phrases ("cannot go lower"), not a rejection of one.
_NEGATION_TOKENS: frozenset[str] = frozenset({
    "not", "no", "never", "without", "nor",
    "avoid", "avoids", "avoiding", "avoided",
    "reject", "rejects", "rejecting", "rejected",
    "isn't", "aren't", "wasn't", "weren't",
    "don't", "doesn't", "didn't", "won't",
})
_NEGATION_WINDOW_CHARS = 60
_SENTENCE_SPLIT = re.compile(r"[.;:!?\n]")


def _is_negated(text_lower: str, phrase_start: int) -> bool:
    """True when the phrase at ``phrase_start`` is negated/rejected.

    Looks at the last sentence segment of the window immediately before the
    phrase, token-wise, so "cannot" (fallacy) never masquerades as "not"
    (negation) and negations in a previous sentence do not leak across.
    """
    window = text_lower[max(0, phrase_start - _NEGATION_WINDOW_CHARS):phrase_start]
    segment = _SENTENCE_SPLIT.split(window)[-1]
    tokens = re.findall(r"[a-z']+", segment)
    return any(tok in _NEGATION_TOKENS for tok in tokens)


def detect_reversal_language(text: Any) -> dict[str, Any]:
    """Negation-aware reversal-language detector.

    Returns matched (non-negated) phrases and the phrases that were present
    but negated (reported for audit, never flagged).
    """
    lowered = _text(text).lower()
    matched: list[str] = []
    negated: list[str] = []
    for phrase in GAMBLERS_FALLACY_PHRASES:
        start = 0
        while True:
            idx = lowered.find(phrase, start)
            if idx < 0:
                break
            (negated if _is_negated(lowered, idx) else matched).append(phrase)
            start = idx + len(phrase)
    for pattern in GAMBLERS_FALLACY_REGEXES:
        match = pattern.search(lowered)
        if match is not None:
            if _is_negated(lowered, match.start()):
                negated.append(match.group(0))
            else:
                matched.append(match.group(0))
    return {
        "reversal_detected": bool(matched),
        "matched_phrases": sorted(set(matched)),
        "negated_phrases": sorted(set(negated)),
    }


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _num(value: Any, default: float | None = None) -> float | None:
    if value is None or isinstance(value, bool):
        return default
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if x != x or x in (float("inf"), float("-inf")):
        return default
    return x


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _parse_date(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _now(now: datetime | None) -> datetime:
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return reference


# ---------------------------------------------------------------------------
# Catalyst-text durability (ported word lists: signal_half_life_estimator on
# feature/p2-interpretation-defense-expansion — SNACK/SIGNAL/DURABLE priors)
# ---------------------------------------------------------------------------

_DURABILITY_HALF_LIFE_DAYS = {"DURABLE": 90.0, "SIGNAL": 21.0, "SNACK": 3.0}

_STRUCTURAL_WORDS: tuple[str, ...] = (
    "contract", "award", "guidance", "earnings", "revenue", "margin", "backlog",
    "approval", "fda", "acquisition", "buyback", "dividend", "filing", "10-k",
    "10-q", "8-k", "patent", "regulatory", "order book", "capacity",
)
_MOMENTUM_WORDS: tuple[str, ...] = (
    "rally", "surge", "spike", "squeeze", "meme", "viral", "buzz", "momentum",
    "trending", "hype", "soar", "pop", "frenzy", "short interest", "social",
)


def derive_half_life_from_catalyst_text(catalyst_text: Any) -> dict[str, Any] | None:
    """Classify catalyst durability (snack/signal/asset) -> half-life prior.

    Used only when neither an explicit half-life nor a known lineage is
    supplied.  Structural words extend half-life; momentum/hype words
    shorten it.  Ties or no cues -> None (caller keeps its default).
    """
    text = _text(catalyst_text).lower()
    if not text:
        return None
    structural = sum(1 for w in _STRUCTURAL_WORDS if w in text)
    momentum = sum(1 for w in _MOMENTUM_WORDS if w in text)
    if structural == momentum:
        return None
    if momentum > structural:
        klass = "SNACK"
    elif structural >= 2:
        klass = "DURABLE"
    else:
        klass = "SIGNAL"
    return {
        "half_life_class": klass,
        "half_life_days": _DURABILITY_HALF_LIFE_DAYS[klass],
        "structural_cues": structural,
        "momentum_cues": momentum,
    }


# ---------------------------------------------------------------------------
# Freshness v1.1
# ---------------------------------------------------------------------------


def resolve_lineage(thesis: dict[str, Any]) -> str:
    raw = _text(thesis.get("asset_lineage")).upper()
    return raw if raw in ASSET_LINEAGES else "UNKNOWN"


def evaluate_freshness(
    thesis: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """FreshnessMultiplier = 2^(-days_since_first_signal / half_life_days).

    Demote-only.  FROZEN requires explicit justification and never inflates
    (multiplier capped at 1.0).  Unknown first-signal date is a confidence
    haircut (x0.85), never assumed fresh.  A past catalyst with unknown
    outcome degrades to NEAR_EXPIRY inside the grace period and SPOILED
    (hard block) beyond it.
    """
    lineage = resolve_lineage(thesis)
    notes: list[str] = []

    half_life_days = _num(thesis.get("thesis_half_life_days"))
    half_life_source = "explicit"
    if half_life_days is None or half_life_days <= 0:
        derived = None
        if lineage == "UNKNOWN":
            derived = derive_half_life_from_catalyst_text(thesis.get("catalyst_text"))
        if derived is not None:
            half_life_days = derived["half_life_days"]
            half_life_source = f"catalyst_text:{derived['half_life_class']}"
        else:
            half_life_days = LINEAGE_HALF_LIFE_DAYS[lineage]
            half_life_source = f"lineage:{lineage}"

    reference = _now(now)

    # FROZEN: deliberate long-horizon holding pauses decay but must be
    # justified, and can only confirm (x1.0), never inflate.
    if bool(thesis.get("frozen_long_term")):
        if _text(thesis.get("frozen_justification")):
            return {
                "FRESHNESS_SCORE": 1.0,
                "FRESHNESS_STATE": "FROZEN",
                "FRESHNESS_MULTIPLIER": 1.0,
                "THESIS_HALF_LIFE_DAYS": half_life_days,
                "THESIS_AGE_DAYS": None,
                "half_life_source": half_life_source,
                "notes": [],
            }
        notes.append("frozen_long_term ignored: no frozen_justification supplied")

    age_days = _num(thesis.get("thesis_age_days"))
    if age_days is None:
        first_signal = _parse_date(thesis.get("thesis_first_signal_date"))
        if first_signal is not None:
            age_days = max((reference - first_signal).total_seconds() / 86400.0, 0.0)

    if age_days is None:
        notes.append("INSUFFICIENT_EVIDENCE_FIRST_SIGNAL_DATE")
        multiplier = FIRST_SIGNAL_UNKNOWN_MULTIPLIER
        state = INSUFFICIENT_EVIDENCE
        score: float | None = None
    else:
        multiplier = _clamp(
            compute_decay_factor(age_days * 24.0, half_life_days * 24.0), 0.0, 1.0
        )
        score = round(multiplier, 4)
        if multiplier >= 0.8:
            state = "FRESH"
        elif multiplier >= 0.5:
            state = "AGING"
        elif multiplier >= SPOILED_FRESHNESS_THRESHOLD:
            state = "NEAR_EXPIRY"
        else:
            state = "SPOILED"

    # Catalyst-date hard expiry (only while the outcome is unknown).
    catalyst_date = _parse_date(thesis.get("catalyst_date"))
    if catalyst_date is not None and not bool(thesis.get("catalyst_outcome_known")):
        days_past = (reference - catalyst_date).total_seconds() / 86400.0
        grace = _num(thesis.get("catalyst_grace_days"), CATALYST_GRACE_DAYS_DEFAULT)
        if days_past > (grace or CATALYST_GRACE_DAYS_DEFAULT):
            state = "SPOILED"
            multiplier = min(multiplier, 0.25)
            notes.append(
                f"catalyst expired {days_past:.1f}d ago (> grace) with unknown outcome"
            )
        elif days_past > 0:
            if state not in ("SPOILED",):
                state = "NEAR_EXPIRY"
            multiplier = min(multiplier, 0.45)
            notes.append(
                f"catalyst passed {days_past:.1f}d ago, outcome unknown (grace window)"
            )

    return {
        "FRESHNESS_SCORE": score,
        "FRESHNESS_STATE": state,
        "FRESHNESS_MULTIPLIER": round(_clamp(multiplier, 0.0, 1.0), 6),
        "THESIS_HALF_LIFE_DAYS": half_life_days,
        "THESIS_AGE_DAYS": None if age_days is None else round(age_days, 2),
        "half_life_source": half_life_source,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Information Access Premium v1.1 — silence is suspicious, not safe
# ---------------------------------------------------------------------------

# The four required evidence slots and the note emitted when each is absent.
_IAP_SLOT_NOTES = {
    "crowding": "INSUFFICIENT_EVIDENCE_CROWDING",
    "late_adoption": "INSUFFICIENT_EVIDENCE_LATE_ADOPTION",
    "price_move": "INSUFFICIENT_EVIDENCE_PRICE_MOVE_SINCE_SIGNAL",
    "source_channel": "INSUFFICIENT_EVIDENCE_SOURCE_CHANNEL",
}


def _price_move_iap_score(pct: float) -> float:
    """Move already captured by earlier participants: 0% -> 0, >=50% -> 10."""
    return _clamp(abs(pct) / 5.0, 0.0, 10.0)


def evaluate_information_access(thesis: dict[str, Any]) -> dict[str, Any]:
    """IAP_raw = worst available lateness signal; confidence = slot coverage.

    IAP_effective = IAP_raw when all four evidence slots are covered;
    otherwise ``max(IAP_raw, 5 + 3*(1 - confidence))`` — so total silence
    lands exactly on the 8.0 hard block and partial silence is demoted,
    while complete evidence earns the right to a low IAP.
    """
    candidates: list[tuple[float, str]] = []
    notes: list[str] = []

    explicit = _num(thesis.get("information_access_premium"))
    if explicit is not None:
        candidates.append((_clamp(explicit, 0.0, 10.0), "explicit_input"))

    crowding_available = explicit is not None
    crowding_inputs = thesis.get("crowding")
    if isinstance(crowding_inputs, dict):
        context = compute_crowding_context(
            light_score=_num(crowding_inputs.get("light_score"), 0.0) or 0.0,
            temporal_position=_num(crowding_inputs.get("temporal_position"), 0.0) or 0.0,
            crowding_state=_text(crowding_inputs.get("crowding_state")) or "OPEN",
            cross_source_confirmation_score=_num(
                crowding_inputs.get("cross_source_confirmation_score")
            ),
            novelty_score=_num(crowding_inputs.get("novelty_score")),
        )
        derived = context["crowding_score"] * 10.0
        if context["full_moon_trap_flag"]:
            derived = max(derived, IAP_HARD_BLOCK_THRESHOLD)
        candidates.append((_clamp(derived, 0.0, 10.0), "crowding_detector"))
        crowding_available = True

    late_adoption_available = explicit is not None
    lalo = _num(thesis.get("lalo_score"))
    if lalo is not None:
        derived = _clamp(lalo, 0.0, 1.0) * 10.0
        if lalo > LALO_SATURATION_WARNING:  # LOCKED_OUT: parrot ceiling
            derived = max(derived, IAP_HARD_BLOCK_THRESHOLD)
        candidates.append((_clamp(derived, 0.0, 10.0), "late_adoption_lockout"))
        late_adoption_available = True

    publicity = _num(thesis.get("publicity_saturation_score"))
    if publicity is not None:
        candidates.append((_clamp(publicity, 0.0, 10.0), "publicity_saturation"))

    price_move = _num(thesis.get("price_move_since_signal_pct"))
    if price_move is not None:
        candidates.append((_price_move_iap_score(price_move), "price_move_since_signal"))

    slots = {
        "crowding": crowding_available,
        "late_adoption": late_adoption_available,
        "price_move": price_move is not None,
        "source_channel": _num(thesis.get("channel_premium_score")) is not None,
    }
    for slot, available in slots.items():
        if not available:
            notes.append(_IAP_SLOT_NOTES[slot])
    confidence = sum(1 for v in slots.values() if v) / len(slots)

    iap_raw = max((c[0] for c in candidates), default=0.0)
    source = max(candidates, key=lambda c: c[0])[1] if candidates else INSUFFICIENT_EVIDENCE

    if confidence >= 1.0:
        iap_effective = iap_raw
    else:
        iap_effective = max(iap_raw, 5.0 + 3.0 * (1.0 - confidence))

    m_iap = _clamp(1.0 - iap_effective / 10.0, 0.0, 1.0)
    m_iap_confidence = _clamp(0.85 + 0.15 * confidence, 0.0, 1.0)

    return {
        "INFORMATION_ACCESS_PREMIUM": round(iap_raw, 4),
        "IAP_EFFECTIVE": round(iap_effective, 4),
        "IAP_CONFIDENCE": round(confidence, 4),
        "iap_source": source,
        "m_iap": m_iap,
        "m_iap_confidence": m_iap_confidence,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Gambler's fallacy + node evidence
# ---------------------------------------------------------------------------


def evaluate_gamblers_fallacy(thesis: dict[str, Any]) -> dict[str, Any]:
    detection = detect_reversal_language(thesis.get("thesis_text"))
    evidence_raw = _text(thesis.get("node_change_evidence")).upper() or "NONE"
    evidence = (
        evidence_raw if evidence_raw in NODE_CHANGE_EVIDENCE_VALUES else "NONE"
    )
    flag = detection["reversal_detected"]
    return {
        "GAMBLERS_FALLACY_FLAG": flag,
        "NODE_CHANGE_EVIDENCE": evidence,
        "matched_phrases": detection["matched_phrases"],
        "negated_phrases": detection["negated_phrases"],
        "fallacy_unbacked": flag and evidence == "NONE",
        "reversal_warning": flag and evidence != "NONE",
    }


def evaluate_load_bearing_node(thesis: dict[str, Any]) -> dict[str, Any]:
    """Node must be named, scored with evidence confidence, and touched."""
    node = _text(thesis.get("load_bearing_node"))
    score = _num(thesis.get("load_bearing_node_score"))
    confidence = _num(thesis.get("load_bearing_node_evidence_confidence"))
    touches_raw = thesis.get("thesis_touches_node")
    touches: bool | None = touches_raw if isinstance(touches_raw, bool) else None

    notes: list[str] = []
    if not node:
        node = INSUFFICIENT_EVIDENCE
        notes.append("INSUFFICIENT_EVIDENCE_LOAD_BEARING_NODE")
    if score is None:
        score = NEUTRAL_COMPONENT_SCORE
        confidence = MISSING_SCORE_CONFIDENCE
        notes.append("load_bearing_node_score missing -> neutral 5.0, confidence 0")
    elif confidence is None:
        confidence = MISSING_CONFIDENCE_DEFAULT
        notes.append("load_bearing_node_evidence_confidence missing -> 0.5")
    if touches is None:
        notes.append("thesis_touches_node unproven -> fail closed, cap BUY_LIMITED")

    confidence = _clamp(confidence, 0.0, 1.0)
    validated = _clamp(score, 0.0, 10.0) * (0.5 + 0.5 * confidence)
    return {
        "LOAD_BEARING_NODE": node,
        "LOAD_BEARING_NODE_SCORE": _clamp(score, 0.0, 10.0),
        "LOAD_BEARING_NODE_VALIDATED_SCORE": round(validated, 4),
        "LOAD_BEARING_NODE_EVIDENCE_CONFIDENCE": confidence,
        "THESIS_TOUCHES_NODE": touches,
        "node_cap_buy_limited": touches is not True or node == INSUFFICIENT_EVIDENCE,
        "notes": notes,
    }


def evaluate_net_edge(thesis: dict[str, Any]) -> dict[str, Any]:
    """NET_EDGE = model_p - implied_p - friction.  <= 0 hard-blocks;
    missing components -> INSUFFICIENT_EVIDENCE status -> cap BUY_LIMITED."""
    model_p = _num(thesis.get("model_probability"))
    implied_p = _num(thesis.get("market_implied_probability"))
    friction = _num(thesis.get("friction_leakage_estimate"))
    notes: list[str] = []

    if model_p is None or implied_p is None:
        return {
            "NET_EDGE": None,
            "NET_EDGE_STATUS": INSUFFICIENT_EVIDENCE,
            "FRICTION_LEAKAGE_ESTIMATE": friction,
            "notes": ["net edge not computable: model/market probability missing"],
        }

    status = "COMPUTED"
    friction_val = friction
    if friction_val is None:
        friction_val = 0.0
        status = INSUFFICIENT_EVIDENCE
        notes.append("friction_leakage_estimate missing -> provisional 0.0")
    net = model_p - implied_p - friction_val
    return {
        "NET_EDGE": round(net, 6),
        "NET_EDGE_STATUS": status,
        "FRICTION_LEAKAGE_ESTIMATE": friction_val,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Operator fit v1.1 — computed from verified holdings when available
# ---------------------------------------------------------------------------

DEFAULT_HOLDINGS_PATH = (
    Path(__file__).resolve().parents[1]
    / "data" / "daily_payload" / "verified_current_holdings.json"
)


def _normalize_holding_ticker(value: Any) -> str:
    text = _text(value).upper()
    return text.split(":", 1)[1] if ":" in text else text


def load_verified_holdings(path: Path | str | None = None) -> list[dict[str, Any]] | None:
    """Read the canonical holdings file.  Returns None on any failure."""
    target = Path(path) if path is not None else DEFAULT_HOLDINGS_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    positions = payload.get("positions") if isinstance(payload, dict) else payload
    if not isinstance(positions, list):
        return None
    return [p for p in positions if isinstance(p, dict)]


def compute_operator_fit_from_holdings(
    holdings: list[dict[str, Any]],
    *,
    candidate_ticker: str = "",
    candidate_sector: str = "",
    candidate_lineage: str = "",
) -> dict[str, Any]:
    """OperatorFitScore = 10 - min(10, sum of overlap penalties).

    Weights use position notionals (quantity x entry_price) when present,
    else equal weight.  Only OPEN positions count.  Penalties:
      same-ticker 6.0 x held; sector 5.0 x sector weight fraction;
      lineage 3.0 x lineage weight fraction; concentration 2.0 x max weight;
      attention 1.0 x crowded-book fraction beyond 8 positions.
    """
    open_positions = [
        p for p in holdings
        if _text(p.get("status") or "OPEN").upper() == "OPEN"
    ]
    n = len(open_positions)
    if n == 0:
        return {
            "OPERATOR_FIT_SCORE": 10.0,
            "penalties": {},
            "positions_count": 0,
        }

    weights: list[float] = []
    for p in open_positions:
        qty = _num(p.get("quantity"))
        price = _num(p.get("entry_price"))
        weights.append(qty * price if qty and price and qty * price > 0 else 0.0)
    total = sum(weights)
    if total <= 0:
        weights = [1.0] * n
        total = float(n)
    weights = [w / total for w in weights]

    ticker = _normalize_holding_ticker(candidate_ticker)
    sector = _text(candidate_sector).upper()
    lineage = _text(candidate_lineage).upper()

    same_ticker_w = sum(
        w for p, w in zip(open_positions, weights)
        if ticker and _normalize_holding_ticker(
            p.get("normalized_ticker") or p.get("ticker")
        ) == ticker
    )
    sector_w = sum(
        w for p, w in zip(open_positions, weights)
        if sector and _text(p.get("sector")).upper() == sector
    )
    lineage_w = sum(
        w for p, w in zip(open_positions, weights)
        if lineage and _text(p.get("asset_lineage")).upper() == lineage
    )

    penalties = {
        "same_ticker_penalty": 6.0 if same_ticker_w > 0 else 0.0,
        "sector_overlap_penalty": round(5.0 * sector_w, 4),
        "lineage_overlap_penalty": round(3.0 * lineage_w, 4),
        "concentration_penalty": round(2.0 * max(weights), 4),
        "attention_penalty": round(_clamp((n - 8) / 8.0, 0.0, 1.0), 4),
    }
    fit = 10.0 - min(10.0, sum(penalties.values()))
    return {
        "OPERATOR_FIT_SCORE": round(_clamp(fit, 0.0, 10.0), 4),
        "penalties": penalties,
        "positions_count": n,
    }


def evaluate_operator_fit(
    thesis: dict[str, Any],
    *,
    holdings: list[dict[str, Any]] | None = None,
    holdings_path: Path | str | None = None,
) -> dict[str, Any]:
    """Resolution order: explicit score > supplied/loaded holdings > neutral.

    Holdings auto-load from the canonical file only when the thesis opts in
    (``use_verified_holdings: true``) so evaluations stay deterministic.
    Neutral degradation: fit 5.0 with a 0.90 confidence multiplier and an
    INSUFFICIENT_EVIDENCE_HOLDINGS note — transparent, never a crash.
    """
    notes: list[str] = []
    explicit = _num(thesis.get("operator_fit_score"))
    if explicit is not None:
        fit = _clamp(explicit, 0.0, 10.0)
        return {
            "OPERATOR_FIT_SCORE": fit,
            "OPERATOR_FIT_CONFIDENCE": 1.0,
            "fit_source": "explicit_input",
            "penalties": {},
            "notes": notes,
        }

    resolved = holdings
    if resolved is None and isinstance(thesis.get("holdings"), list):
        resolved = [p for p in thesis["holdings"] if isinstance(p, dict)]
    if resolved is None and (holdings_path is not None or thesis.get("use_verified_holdings")):
        resolved = load_verified_holdings(holdings_path)
        if resolved is None:
            notes.append("verified holdings file unreadable/absent")

    if resolved is not None:
        computed = compute_operator_fit_from_holdings(
            resolved,
            candidate_ticker=_text(thesis.get("ticker")),
            candidate_sector=_text(thesis.get("sector")),
            candidate_lineage=_text(thesis.get("asset_lineage")),
        )
        return {
            "OPERATOR_FIT_SCORE": computed["OPERATOR_FIT_SCORE"],
            "OPERATOR_FIT_CONFIDENCE": 1.0,
            "fit_source": f"holdings({computed['positions_count']} open)",
            "penalties": computed["penalties"],
            "notes": notes,
        }

    notes.append("INSUFFICIENT_EVIDENCE_HOLDINGS")
    return {
        "OPERATOR_FIT_SCORE": NEUTRAL_OPERATOR_FIT,
        "OPERATOR_FIT_CONFIDENCE": OPERATOR_FIT_MISSING_CONFIDENCE,
        "fit_source": INSUFFICIENT_EVIDENCE,
        "penalties": {},
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Stage multipliers (every one clamped to [0, 1]: demote-only by construction)
# ---------------------------------------------------------------------------


def _channel_multiplier(channel_premium: float) -> float:
    """0 -> 1.00 (farm-gate), 5 -> 0.75 (public screen), 10 -> 0.50 (packaged)."""
    return _clamp(1.0 - channel_premium / 20.0, 0.0, 1.0)


def _operator_fit_multiplier(fit: float) -> float:
    """fit 0 -> x0.5, fit 10 -> x1.0."""
    return _clamp(0.5 + 0.05 * _clamp(fit, 0.0, 10.0), 0.0, 1.0)


def _gate_for_score(score: float) -> str:
    if score >= 8.0:
        return GATE_BUY_ALLOWED
    if score >= 6.5:
        return GATE_BUY_LIMITED
    if score >= 5.0:
        return GATE_WATCHLIST
    return GATE_BUY_BLOCKED


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def evaluate_chicken_gate(
    thesis: dict[str, Any],
    *,
    now: datetime | None = None,
    holdings: list[dict[str, Any]] | None = None,
    holdings_path: Path | str | None = None,
) -> dict[str, Any]:
    """Run the full v1.1 demote-only gate over one thesis dict.

    Never raises on missing optional evidence — every gap becomes an
    evidence note plus a conservative haircut, never a reward.
    """
    data = thesis if isinstance(thesis, dict) else {}
    evidence_notes: list[str] = []
    warnings: list[str] = []

    lineage = resolve_lineage(data)

    # ---- Raw components with evidence-confidence validation --------------
    def validated_component(
        score_key: str, confidence_key: str, neutral: float, lo: float, hi: float
    ) -> tuple[float, float, float]:
        """Returns (reported, confidence, validated)."""
        score = _num(data.get(score_key))
        confidence = _num(data.get(confidence_key))
        if score is None:
            evidence_notes.append(
                f"{score_key}: {INSUFFICIENT_EVIDENCE} -> neutral {neutral}, confidence 0"
            )
            score, confidence = neutral, MISSING_SCORE_CONFIDENCE
        elif confidence is None:
            evidence_notes.append(f"{confidence_key}: missing -> 0.5")
            confidence = MISSING_CONFIDENCE_DEFAULT
        score = _clamp(score, lo, hi)
        confidence = _clamp(confidence, 0.0, 1.0)
        return score, confidence, score * (0.5 + 0.5 * confidence)

    house_edge, _, house_edge_v = validated_component(
        "house_edge_score", "house_edge_confidence", NEUTRAL_COMPONENT_SCORE, 0.0, 10.0
    )
    input_quality, _, input_quality_v = validated_component(
        "input_quality_score", "input_quality_confidence",
        NEUTRAL_COMPONENT_SCORE, 0.0, 10.0,
    )
    process_integrity, _, process_integrity_v = validated_component(
        "process_integrity_score", "process_integrity_confidence",
        NEUTRAL_COMPONENT_SCORE, 0.0, 10.0,
    )
    label_authenticity, _, label_authenticity_v = validated_component(
        "label_authenticity_score", "label_authenticity_confidence",
        NEUTRAL_LABEL_AUTHENTICITY, 0.0, 1.0,
    )
    bone_value, _, bone_value_v = validated_component(
        "residual_bone_value_score", "residual_bone_value_confidence",
        NEUTRAL_BONE_VALUE, 0.0, 1.0,
    )
    label_premium = _num(data.get("label_premium"), 0.0) or 0.0

    node = evaluate_load_bearing_node(data)
    evidence_notes.extend(node["notes"])

    def _raw_sum(node_score: float, label: float, bone: float,
                 he: float, iq: float, pi: float) -> float:
        return (
            RAW_WEIGHTS["house_edge"] * he
            + RAW_WEIGHTS["input_quality"] * iq
            + RAW_WEIGHTS["process_integrity"] * pi
            + RAW_WEIGHTS["load_bearing_node"] * node_score
            + RAW_WEIGHTS["label_authenticity"] * (label * 10.0)
            + RAW_WEIGHTS["residual_bone_value"] * (bone * 10.0)
        )

    raw_score = _clamp(
        _raw_sum(node["LOAD_BEARING_NODE_SCORE"], label_authenticity, bone_value,
                 house_edge, input_quality, process_integrity),
        0.0, 10.0,
    )
    raw_validated = _clamp(
        _raw_sum(node["LOAD_BEARING_NODE_VALIDATED_SCORE"], label_authenticity_v,
                 bone_value_v, house_edge_v, input_quality_v, process_integrity_v),
        0.0, raw_score,
    )
    raw_inflation_leakage = round(raw_score - raw_validated, 4)

    # ---- Component evaluations -------------------------------------------
    freshness = evaluate_freshness(data, now=now)
    evidence_notes.extend(freshness["notes"])

    iap = evaluate_information_access(data)
    evidence_notes.extend(iap["notes"])

    channel_premium_input = _num(data.get("channel_premium_score"))
    if channel_premium_input is None:
        evidence_notes.append(
            f"channel_premium_score: {INSUFFICIENT_EVIDENCE} -> neutral "
            f"{NEUTRAL_CHANNEL_PREMIUM}"
        )
        channel_premium = NEUTRAL_CHANNEL_PREMIUM
    else:
        channel_premium = _clamp(channel_premium_input, 0.0, 10.0)

    fit = evaluate_operator_fit(data, holdings=holdings, holdings_path=holdings_path)
    evidence_notes.extend(fit["notes"])

    fallacy = evaluate_gamblers_fallacy(data)
    if fallacy["reversal_warning"]:
        warnings.append("REVERSAL_REQUIRES_NODE_CONFIRMATION")

    net_edge = evaluate_net_edge(data)
    evidence_notes.extend(net_edge["notes"])

    spoilage_risk = bool(data.get("spoilage_risk"))

    # ---- Multiplicative demote-only pipeline ------------------------------
    m_freshness = freshness["FRESHNESS_MULTIPLIER"]
    m_iap = iap["m_iap"]
    m_iap_confidence = iap["m_iap_confidence"]
    m_channel = _channel_multiplier(channel_premium)
    m_fit = _operator_fit_multiplier(fit["OPERATOR_FIT_SCORE"])
    m_fit_confidence = _clamp(fit["OPERATOR_FIT_CONFIDENCE"], 0.0, 1.0)

    freshness_adj = raw_validated * m_freshness
    iap_adj = freshness_adj * m_iap
    iap_conf_adj = iap_adj * m_iap_confidence
    channel_adj = iap_conf_adj * m_channel
    fit_adj = channel_adj * m_fit
    final_score = fit_adj * m_fit_confidence

    # ---- Value-extraction ledger: RAW_VALIDATED - FINAL, itemised ---------
    def _ledger_row(stage: str, extractor: str, before: float, after: float,
                    reason: str) -> dict[str, Any]:
        eaten = round(before - after, 4)
        return {
            "stage": stage,
            "extractor": extractor,
            "points_eaten": eaten,
            "percent_of_raw_merit": (
                round(100.0 * eaten / raw_validated, 2) if raw_validated > 0 else 0.0
            ),
            "reason": reason,
        }

    ledger = [
        _ledger_row(
            "FRESHNESS", "TIME_AND_EARLIER_HOLDERS", raw_validated, freshness_adj,
            f"freshness x{m_freshness:.4f} ({freshness['FRESHNESS_STATE']}, "
            f"half-life {freshness['THESIS_HALF_LIFE_DAYS']}d)",
        ),
        _ledger_row(
            "INFORMATION_ACCESS", "EARLIER_INFORMED_PARTICIPANTS",
            freshness_adj, iap_adj,
            f"IAP_effective {iap['IAP_EFFECTIVE']:.2f} "
            f"({iap['iap_source']}) x{m_iap:.4f}",
        ),
        _ledger_row(
            "IAP_EVIDENCE_CONFIDENCE", "MISSING_EVIDENCE_HAIRCUT",
            iap_adj, iap_conf_adj,
            f"IAP confidence {iap['IAP_CONFIDENCE']:.2f} x{m_iap_confidence:.4f}",
        ),
        _ledger_row(
            "CHANNEL_PACKAGING", "PACKAGING_CHANNEL_MARKUP",
            iap_conf_adj, channel_adj,
            f"channel premium {channel_premium:.1f} x{m_channel:.4f}",
        ),
        _ledger_row(
            "OPERATOR_FIT", "PORTFOLIO_OVERLAP", channel_adj, fit_adj,
            f"fit {fit['OPERATOR_FIT_SCORE']:.1f} ({fit['fit_source']}) x{m_fit:.4f}",
        ),
        _ledger_row(
            "OPERATOR_FIT_CONFIDENCE", "MISSING_EVIDENCE_HAIRCUT",
            fit_adj, final_score,
            f"fit confidence x{m_fit_confidence:.4f}",
        ),
    ]
    total_eaten = round(raw_validated - final_score, 4)

    # ---- Hard flags (override all arithmetic) -----------------------------
    hard_flags: list[str] = []
    if spoilage_risk:
        hard_flags.append("SPOILAGE_RISK")
    if fallacy["fallacy_unbacked"]:
        hard_flags.append("GAMBLERS_FALLACY_NO_NODE_CHANGE_EVIDENCE")
    if iap["IAP_EFFECTIVE"] >= IAP_HARD_BLOCK_THRESHOLD:
        hard_flags.append("INFORMATION_ACCESS_PREMIUM_GTE_8")
    if net_edge["NET_EDGE"] is not None and net_edge["NET_EDGE"] <= 0.0:
        hard_flags.append("NET_EDGE_NON_POSITIVE")
    if process_integrity < PROCESS_INTEGRITY_HARD_BLOCK:
        hard_flags.append("PROCESS_INTEGRITY_BELOW_3")
    if freshness["FRESHNESS_STATE"] == "SPOILED":
        hard_flags.append("FRESHNESS_SPOILED")
    if (
        label_authenticity < LABEL_AUTHENTICITY_HARD_BLOCK
        and label_premium >= LABEL_PREMIUM_HIGH
    ):
        hard_flags.append("FAKE_LABEL_HIGH_PREMIUM_LOW_AUTHENTICITY")

    # ---- Cap rules (recorded whenever the condition holds) ----------------
    cap_rules: list[dict[str, str]] = []
    if node["node_cap_buy_limited"]:
        cap_rules.append({
            "rule": "THESIS_DOES_NOT_PROVABLY_TOUCH_LOAD_BEARING_NODE",
            "cap": GATE_BUY_LIMITED,
        })
    if fit["OPERATOR_FIT_SCORE"] < OPERATOR_FIT_CAP_THRESHOLD:
        cap_rules.append({"rule": "OPERATOR_FIT_BELOW_4", "cap": GATE_BUY_LIMITED})
    if net_edge["NET_EDGE_STATUS"] == INSUFFICIENT_EVIDENCE:
        cap_rules.append({
            "rule": "NET_EDGE_INSUFFICIENT_EVIDENCE", "cap": GATE_BUY_LIMITED,
        })
    if (
        channel_premium >= CHANNEL_UNVERIFIED_CAP_THRESHOLD
        and not bool(data.get("raw_evidence_independently_verified"))
    ):
        cap_rules.append({
            "rule": "CHANNEL_PREMIUM_GTE_8_UNVERIFIED", "cap": GATE_WATCHLIST,
        })

    # ---- Final gate --------------------------------------------------------
    gate = _gate_for_score(final_score)
    for cap in cap_rules:
        if _GATE_RANK[gate] > _GATE_RANK[cap["cap"]]:
            gate = cap["cap"]
    final_gate = GATE_BUY_BLOCKED if hard_flags else gate

    if final_gate == GATE_BUY_BLOCKED:
        blocked_reason = (
            "; ".join(hard_flags)
            if hard_flags
            else f"score {final_score:.2f} below 5.0"
        )
        allowed_reason = ""
    else:
        blocked_reason = ""
        allowed_reason = f"score {final_score:.2f} ({final_gate})"
        if cap_rules:
            allowed_reason += (
                "; caps: " + "; ".join(c["rule"] for c in cap_rules)
            )

    one_line = (
        f"{final_gate}: "
        + (
            blocked_reason
            if blocked_reason
            else (
                f"validated merit {raw_validated:.2f}, "
                f"{total_eaten:.2f} pts eaten before it reached you"
            )
        )
    )

    result: dict[str, Any] = {
        "TICKER": _text(data.get("ticker")) or "UNKNOWN",
        "ASSET_LINEAGE": lineage,
        "SCORING_PROFILE_VERSION": SCORING_PROFILE_VERSION,
        # Freshness
        "THESIS_FIRST_SIGNAL_DATE": _text(data.get("thesis_first_signal_date")) or None,
        "THESIS_HALF_LIFE_DAYS": freshness["THESIS_HALF_LIFE_DAYS"],
        "THESIS_AGE_DAYS": freshness["THESIS_AGE_DAYS"],
        "FRESHNESS_SCORE": freshness["FRESHNESS_SCORE"],
        "FRESHNESS_STATE": freshness["FRESHNESS_STATE"],
        "FRESHNESS_MULTIPLIER": m_freshness,
        "HALF_LIFE_SOURCE": freshness["half_life_source"],
        # Information access
        "INFORMATION_ACCESS_PREMIUM": iap["INFORMATION_ACCESS_PREMIUM"],
        "IAP_EFFECTIVE": iap["IAP_EFFECTIVE"],
        "IAP_CONFIDENCE": iap["IAP_CONFIDENCE"],
        # Channel
        "CHANNEL_PREMIUM_SCORE": channel_premium,
        "CHANNEL_MULTIPLIER": round(m_channel, 6),
        # Node
        "LOAD_BEARING_NODE": node["LOAD_BEARING_NODE"],
        "LOAD_BEARING_NODE_SCORE": node["LOAD_BEARING_NODE_SCORE"],
        "LOAD_BEARING_NODE_VALIDATED_SCORE": node["LOAD_BEARING_NODE_VALIDATED_SCORE"],
        "THESIS_TOUCHES_NODE": node["THESIS_TOUCHES_NODE"],
        # Gambler
        "GAMBLERS_FALLACY_FLAG": fallacy["GAMBLERS_FALLACY_FLAG"],
        "NODE_CHANGE_EVIDENCE": fallacy["NODE_CHANGE_EVIDENCE"],
        "GAMBLERS_FALLACY_MATCHED_PHRASES": fallacy["matched_phrases"],
        "GAMBLERS_FALLACY_NEGATED_PHRASES": fallacy["negated_phrases"],
        # Risk / edge
        "SPOILAGE_RISK": spoilage_risk,
        "FRICTION_LEAKAGE_ESTIMATE": net_edge["FRICTION_LEAKAGE_ESTIMATE"],
        "NET_EDGE": net_edge["NET_EDGE"],
        "NET_EDGE_STATUS": net_edge["NET_EDGE_STATUS"],
        # Operator fit
        "OPERATOR_FIT_SCORE": fit["OPERATOR_FIT_SCORE"],
        "OPERATOR_FIT_CONFIDENCE": fit["OPERATOR_FIT_CONFIDENCE"],
        "OPERATOR_FIT_SOURCE": fit["fit_source"],
        "OPERATOR_FIT_PENALTIES": fit["penalties"],
        # Scores
        "RAW_TRADE_SCORE": round(raw_score, 4),
        "RAW_VALIDATED_SCORE": round(raw_validated, 4),
        "RAW_INFLATION_LEAKAGE": raw_inflation_leakage,
        "FRESHNESS_ADJ_SCORE": round(freshness_adj, 4),
        "ASYMMETRY_ADJ_SCORE": round(channel_adj, 4),
        "OPERATOR_FIT_ADJ_SCORE": round(final_score, 4),
        "FINAL_SCORE": round(final_score, 4),
        # Gate
        "FINAL_ACTION_GATE": final_gate,
        "HARD_FLAG_TRIGGERED": "; ".join(hard_flags) if hard_flags else "NONE",
        "CAP_RULES_TRIGGERED": cap_rules,
        "WARNINGS": warnings,
        "BUY_ALLOWED_REASON": allowed_reason,
        "BUY_BLOCKED_REASON": blocked_reason,
        "ONE_LINE_REASON": one_line,
        # Ledger + evidence
        "VALUE_EXTRACTION_LEDGER": ledger,
        "VALUE_EATEN_TOTAL_POINTS": total_eaten,
        "VALUE_EATEN_PCT_OF_RAW": (
            round(100.0 * total_eaten / raw_validated, 2) if raw_validated > 0 else 0.0
        ),
        "EVIDENCE_NOTES": evidence_notes,
        # Demote-only invariant: every multiplier clamped <= 1.0.
        "invariant_final_leq_raw": final_score <= raw_validated + 1e-9,
    }
    result["ADVISORY_ONLY_STAMP"] = advisory_safety_stamps()
    result["safety"] = advisory_safety_stamps()
    result["human"] = human_only_stamp()
    return result


# ---------------------------------------------------------------------------
# Trade card
# ---------------------------------------------------------------------------


def render_trade_card(result: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("=== SLEEPING PASSENGER - CHICKEN GATE TRADE CARD (v1.1) ===")
    add(f"TICKER: {result['TICKER']}    LINEAGE: {result['ASSET_LINEAGE']}")
    add(
        f"FRESHNESS: {result['FRESHNESS_STATE']}"
        f" (mult={result['FRESHNESS_MULTIPLIER']},"
        f" half-life={result['THESIS_HALF_LIFE_DAYS']}d,"
        f" source={result['HALF_LIFE_SOURCE']})"
    )
    add(
        f"LOAD-BEARING NODE: {result['LOAD_BEARING_NODE']}"
        f" (score={result['LOAD_BEARING_NODE_SCORE']},"
        f" validated={result['LOAD_BEARING_NODE_VALIDATED_SCORE']},"
        f" touches={result['THESIS_TOUCHES_NODE']})"
    )
    add(
        f"IAP: raw={result['INFORMATION_ACCESS_PREMIUM']}"
        f" effective={result['IAP_EFFECTIVE']}"
        f" confidence={result['IAP_CONFIDENCE']}"
    )
    add(
        f"NET_EDGE: {result['NET_EDGE']} ({result['NET_EDGE_STATUS']})"
        f"    SPOILAGE: {result['SPOILAGE_RISK']}"
    )
    add(
        f"GAMBLER CHECK: flag={result['GAMBLERS_FALLACY_FLAG']}"
        f" evidence={result['NODE_CHANGE_EVIDENCE']}"
        + (f" negated={result['GAMBLERS_FALLACY_NEGATED_PHRASES']}"
           if result["GAMBLERS_FALLACY_NEGATED_PHRASES"] else "")
    )
    add(
        f"OPERATOR FIT: {result['OPERATOR_FIT_SCORE']}"
        f" (conf={result['OPERATOR_FIT_CONFIDENCE']},"
        f" source={result['OPERATOR_FIT_SOURCE']})"
    )
    add("--- score pipeline (demote-only) ---")
    add(f"  RAW_TRADE_SCORE        {result['RAW_TRADE_SCORE']:>7.3f}")
    add(
        f"  RAW_VALIDATED_SCORE    {result['RAW_VALIDATED_SCORE']:>7.3f}"
        f"   (inflation leakage {result['RAW_INFLATION_LEAKAGE']})"
    )
    add(f"  FRESHNESS_ADJ_SCORE    {result['FRESHNESS_ADJ_SCORE']:>7.3f}")
    add(f"  ASYMMETRY_ADJ_SCORE    {result['ASYMMETRY_ADJ_SCORE']:>7.3f}")
    add(f"  FINAL_SCORE            {result['FINAL_SCORE']:>7.3f}")
    add("--- who ate the value before it reached you ---")
    for row in result["VALUE_EXTRACTION_LEDGER"]:
        add(
            f"  {row['stage']:<24} -{row['points_eaten']:<7.3f}"
            f" ({row['percent_of_raw_merit']:>5.1f}%)"
            f" {row['extractor']}  [{row['reason']}]"
        )
    add(
        f"  TOTAL EATEN: {result['VALUE_EATEN_TOTAL_POINTS']} points"
        f" ({result['VALUE_EATEN_PCT_OF_RAW']}% of validated merit)"
    )
    add(f"FINAL ACTION: {result['FINAL_ACTION_GATE']}")
    add(f"REASON: {result['ONE_LINE_REASON']}")
    if result["HARD_FLAG_TRIGGERED"] != "NONE":
        add(f"HARD FLAGS: {result['HARD_FLAG_TRIGGERED']}")
    if result["CAP_RULES_TRIGGERED"]:
        add(
            "CAP RULES: "
            + "; ".join(
                f"{c['rule']} -> {c['cap']}" for c in result["CAP_RULES_TRIGGERED"]
            )
        )
    if result["WARNINGS"]:
        add(f"WARNINGS: {'; '.join(result['WARNINGS'])}")
    if result["EVIDENCE_NOTES"]:
        add("MISSING/DEGRADED EVIDENCE:")
        for note in result["EVIDENCE_NOTES"]:
            add(f"  - {note}")
    add("ADVISORY_ONLY | execution gate LOCKED | human decides")
    return "\n".join(lines)


DEMO_THESIS: dict[str, Any] = {
    "ticker": "DEMO",
    "asset_lineage": "DEFENCE",
    "thesis_text": (
        "Backlog conversion accelerates ahead of consensus on framework-"
        "contract demand; not a mean reversion bet."
    ),
    "thesis_age_days": 1.0,
    "house_edge_score": 9.5, "house_edge_confidence": 1.0,
    "input_quality_score": 9.0, "input_quality_confidence": 1.0,
    "process_integrity_score": 9.0, "process_integrity_confidence": 1.0,
    "load_bearing_node": "Ammunition segment margin",
    "load_bearing_node_score": 9.5,
    "load_bearing_node_evidence_confidence": 1.0,
    "thesis_touches_node": True,
    "label_authenticity_score": 0.95, "label_authenticity_confidence": 1.0,
    "label_premium": 5.0,
    "residual_bone_value_score": 0.8, "residual_bone_value_confidence": 1.0,
    "information_access_premium": 1.0,
    "publicity_saturation_score": 1.0,
    "price_move_since_signal_pct": 2.0,
    "channel_premium_score": 0.0,
    "raw_evidence_independently_verified": True,
    "operator_fit_score": 10.0,
    "node_change_evidence": "DEMAND_CHANGE",
    "model_probability": 0.62,
    "market_implied_probability": 0.50,
    "friction_leakage_estimate": 0.02,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Chicken Gate v1.1: advisory-only freshness+asymmetry+node gate. "
            "Scores a thesis JSON and prints the trade card."
        )
    )
    parser.add_argument("--thesis-json", help="Path to a thesis JSON file")
    parser.add_argument("--demo", action="store_true", help="Score the demo thesis")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON result")
    parser.add_argument(
        "--holdings", action="store_true",
        help="Compute operator fit from data/daily_payload/verified_current_holdings.json",
    )
    args = parser.parse_args(argv)

    if args.demo:
        thesis = dict(DEMO_THESIS)
    elif args.thesis_json:
        with open(args.thesis_json, "r", encoding="utf-8") as fh:
            thesis = json.load(fh)
    else:
        parser.print_help()
        return 2

    if args.holdings:
        thesis.pop("operator_fit_score", None)
        thesis["use_verified_holdings"] = True

    result = evaluate_chicken_gate(thesis)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(render_trade_card(result))
    return 0


__all__ = [
    "SCORING_PROFILE_VERSION",
    "ASSET_LINEAGES",
    "LINEAGE_HALF_LIFE_DAYS",
    "FRESHNESS_STATES",
    "NODE_CHANGE_EVIDENCE_VALUES",
    "GAMBLERS_FALLACY_PHRASES",
    "RAW_WEIGHTS",
    "GATE_BUY_ALLOWED",
    "GATE_BUY_LIMITED",
    "GATE_WATCHLIST",
    "GATE_BUY_BLOCKED",
    "DEFAULT_HOLDINGS_PATH",
    "detect_reversal_language",
    "derive_half_life_from_catalyst_text",
    "evaluate_freshness",
    "evaluate_information_access",
    "evaluate_gamblers_fallacy",
    "evaluate_load_bearing_node",
    "evaluate_net_edge",
    "load_verified_holdings",
    "compute_operator_fit_from_holdings",
    "evaluate_operator_fit",
    "evaluate_chicken_gate",
    "render_trade_card",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
