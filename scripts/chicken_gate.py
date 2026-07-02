"""Chicken Gate — canonical freshness + asymmetry + node-evidence gate.

Consolidation facade, not a new pile.  This module wires three existing
layers into one four-stage, demote-only scoring pipeline with hard flags:

* ``signal_decay_waste.compute_decay_factor``  — thesis half-life decay
* ``crowding_detector.compute_crowding_context`` — crowding -> IAP derivation
* ``late_adoption_lockout`` thresholds          — parrot-ceiling IAP mapping
* ``advisory_contract``                         — the one true safety stamp

The question it answers, as arithmetic rather than narrative:

    "By the time this trade reached me, how much value was already eaten,
     who extracted it, is the thesis fresh, does it touch the load-bearing
     node, and am I falling for gambler's fallacy?"

Pipeline (every stage multiplier is clamped to <= 1.0 — demote-only, the
``final <= merit`` invariant of scripts/signal_arbitrage carried over):

    RAW_TRADE_SCORE        = weighted(house_edge, input_quality,
                                      process_integrity, node, label, bone)
    FRESHNESS_ADJ_SCORE    = RAW * freshness_multiplier
    ASYMMETRY_ADJ_SCORE    = FRESHNESS_ADJ * iap_mult * channel_mult
    OPERATOR_FIT_ADJ_SCORE = ASYMMETRY_ADJ * fit_mult

Value-extraction ledger: because the stages are multiplicative and ordered,
``raw - final`` decomposes exactly into per-stage points eaten, each with a
named extractor (TIME, EARLIER_PARTICIPANTS, PACKAGING_CHANNEL,
PORTFOLIO_OVERLAP).  The trade card prints who ate what.

Hard flags override all arithmetic (BUY_BLOCKED regardless of score):
spoilage, gambler's-fallacy without node-change evidence, IAP >= 8,
NET_EDGE <= 0, process integrity < 3, SPOILED freshness, fake label
(authenticity < 0.3 with high label premium).

Advisory-only.  No broker calls, no order surface, no execution language.
Missing evidence degrades to INSUFFICIENT_EVIDENCE + neutral demotion,
never to a stronger score.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from typing import Any

from scripts.advisory_contract import (
    advisory_safety_stamps,
    human_only_stamp,
)
from scripts.crowding_detector import compute_crowding_context
from scripts.late_adoption_lockout import LALO_SATURATION_WARNING
from scripts.signal_decay_waste import compute_decay_factor

SCORING_PROFILE_VERSION = "chicken-gate-v1.0"

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

ASSET_LINEAGES: tuple[str, ...] = (
    "COMPOUNDER", "CYCLICAL", "DISTRESSED", "NARRATIVE", "COMMODITY_PROXY",
    "DEFENCE", "DIVIDEND", "PLATFORM", "REGULATORY", "UNKNOWN",
)

# Lineage-based thesis half-life in days (a narrative rots ~13x faster
# than a dividend compounder).  Explicit THESIS_HALF_LIFE_DAYS input wins.
LINEAGE_HALF_LIFE_DAYS: dict[str, float] = {
    "NARRATIVE": 7.0,
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

# Reversal-shaped language that, without causal node-change evidence, is
# gambler's fallacy.  Lowercase substrings matched against the thesis text.
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
    "gone up too much",
    "risen too much",
    "must cool",
    "due for a correction",
    "due a correction",
    "due to fall",
    "due for a fall",
    "mean reversion is due",
    "can't fall further",
    "cannot fall further",
    "can't go lower",
    "owes me",
    "owes a",
)

# Raw-score weights (lineage-agnostic v1.0; recalibrate at N_closed >= 50).
RAW_WEIGHTS: dict[str, float] = {
    "house_edge": 0.30,
    "input_quality": 0.20,
    "process_integrity": 0.15,
    "load_bearing_node": 0.15,
    "label_authenticity": 0.10,
    "residual_bone_value": 0.10,
}

# Neutral fallbacks for missing evidence — mid-band, never generous.
NEUTRAL_COMPONENT_SCORE = 5.0
NEUTRAL_LABEL_AUTHENTICITY = 0.5
NEUTRAL_BONE_VALUE = 0.3
NEUTRAL_IAP = 5.0
NEUTRAL_CHANNEL_PREMIUM = 5.0
NEUTRAL_OPERATOR_FIT = 5.0
NEUTRAL_FRESHNESS_MULTIPLIER = 0.75  # unknown age is mildly stale, never fresh

IAP_HARD_BLOCK_THRESHOLD = 8.0
PROCESS_INTEGRITY_HARD_BLOCK = 3.0
LABEL_AUTHENTICITY_HARD_BLOCK = 0.3
LABEL_PREMIUM_HIGH = 6.0
SPOILED_FRESHNESS_THRESHOLD = 0.3

INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


# ---------------------------------------------------------------------------
# Coercion helpers (same defensive style as signal_decay_waste)
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


# ---------------------------------------------------------------------------
# Component evaluators
# ---------------------------------------------------------------------------


def resolve_lineage(thesis: dict[str, Any]) -> str:
    raw = _text(thesis.get("asset_lineage")).upper()
    return raw if raw in ASSET_LINEAGES else "UNKNOWN"


def evaluate_freshness(
    thesis: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Thesis half-life -> freshness score + state.  Demote-only.

    FROZEN (deliberate long-horizon holding) pauses decay at multiplier 1.0
    — confirming, never inflating.  Missing first-signal evidence degrades
    to INSUFFICIENT_EVIDENCE with a neutral (mildly stale) multiplier.
    """
    lineage = resolve_lineage(thesis)
    half_life_days = _num(thesis.get("thesis_half_life_days"))
    if half_life_days is None or half_life_days <= 0:
        half_life_days = LINEAGE_HALF_LIFE_DAYS[lineage]

    if bool(thesis.get("frozen_long_term")):
        return {
            "FRESHNESS_SCORE": 1.0,
            "FRESHNESS_STATE": "FROZEN",
            "THESIS_HALF_LIFE_DAYS": half_life_days,
            "THESIS_AGE_DAYS": None,
            "freshness_multiplier": 1.0,
            "evidence": "OK",
        }

    age_days = _num(thesis.get("thesis_age_days"))
    if age_days is None:
        first_signal = _parse_date(thesis.get("thesis_first_signal_date"))
        if first_signal is not None:
            reference = now or datetime.now(timezone.utc)
            if reference.tzinfo is None:
                reference = reference.replace(tzinfo=timezone.utc)
            age_days = max((reference - first_signal).total_seconds() / 86400.0, 0.0)

    if age_days is None:
        return {
            "FRESHNESS_SCORE": None,
            "FRESHNESS_STATE": INSUFFICIENT_EVIDENCE,
            "THESIS_HALF_LIFE_DAYS": half_life_days,
            "THESIS_AGE_DAYS": None,
            "freshness_multiplier": NEUTRAL_FRESHNESS_MULTIPLIER,
            "evidence": "missing thesis_first_signal_date / thesis_age_days",
        }

    # Reuse the existing decay engine (hours domain).
    freshness = compute_decay_factor(age_days * 24.0, half_life_days * 24.0)
    if freshness >= 0.8:
        state = "FRESH"
    elif freshness >= 0.5:
        state = "AGING"
    elif freshness >= SPOILED_FRESHNESS_THRESHOLD:
        state = "NEAR_EXPIRY"
    else:
        state = "SPOILED"
    return {
        "FRESHNESS_SCORE": round(freshness, 4),
        "FRESHNESS_STATE": state,
        "THESIS_HALF_LIFE_DAYS": half_life_days,
        "THESIS_AGE_DAYS": round(age_days, 2),
        "freshness_multiplier": _clamp(freshness, 0.0, 1.0),
        "evidence": "OK",
    }


def evaluate_information_access(thesis: dict[str, Any]) -> dict[str, Any]:
    """IAP 0-10: how late/crowded/parrot the entry is.

    Priority: explicit ``information_access_premium`` input; else derive
    from crowding_detector context (crowding_score * 10); else derive from
    a supplied LALO score (parrot ceiling, late_adoption_lockout).  Multiple
    derivations take the worst (max) — asymmetry evidence never averages
    down.  Missing everything -> neutral 5.0 + INSUFFICIENT_EVIDENCE.
    """
    candidates: list[tuple[float, str]] = []
    explicit = _num(thesis.get("information_access_premium"))
    if explicit is not None:
        candidates.append((_clamp(explicit, 0.0, 10.0), "explicit_input"))

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

    lalo = _num(thesis.get("lalo_score"))
    if lalo is not None:
        derived = _clamp(lalo, 0.0, 1.0) * 10.0
        if lalo > LALO_SATURATION_WARNING:  # LOCKED_OUT: parrot ceiling
            derived = max(derived, IAP_HARD_BLOCK_THRESHOLD)
        candidates.append((_clamp(derived, 0.0, 10.0), "late_adoption_lockout"))

    if not candidates:
        return {
            "INFORMATION_ACCESS_PREMIUM": NEUTRAL_IAP,
            "iap_source": INSUFFICIENT_EVIDENCE,
            "evidence": "no explicit IAP, crowding, or LALO inputs",
        }
    worst = max(candidates, key=lambda c: c[0])
    return {
        "INFORMATION_ACCESS_PREMIUM": round(worst[0], 4),
        "iap_source": worst[1],
        "evidence": "OK",
    }


def evaluate_gamblers_fallacy(thesis: dict[str, Any]) -> dict[str, Any]:
    """Reversal-shaped language + no causal node change = fallacy flag.

    Invalid/unknown NODE_CHANGE_EVIDENCE values fail closed to NONE.
    """
    text = _text(thesis.get("thesis_text")).lower()
    matched = [p for p in GAMBLERS_FALLACY_PHRASES if p in text]
    evidence_raw = _text(thesis.get("node_change_evidence")).upper() or "NONE"
    evidence = (
        evidence_raw if evidence_raw in NODE_CHANGE_EVIDENCE_VALUES else "NONE"
    )
    flag = bool(matched)
    return {
        "GAMBLERS_FALLACY_FLAG": flag,
        "NODE_CHANGE_EVIDENCE": evidence,
        "matched_phrases": matched,
        "fallacy_unbacked": flag and evidence == "NONE",
    }


def evaluate_load_bearing_node(thesis: dict[str, Any]) -> dict[str, Any]:
    """Every thesis must name the node doing the heavy lifting.

    Unknown node or unproven touch fails closed: cap at BUY_LIMITED.
    """
    node = _text(thesis.get("load_bearing_node"))
    score = _num(thesis.get("load_bearing_node_score"))
    touches_raw = thesis.get("thesis_touches_node")
    touches: bool | None = touches_raw if isinstance(touches_raw, bool) else None

    notes: list[str] = []
    if not node:
        node = INSUFFICIENT_EVIDENCE
        notes.append("load-bearing node not identified")
    if score is None:
        score = NEUTRAL_COMPONENT_SCORE
        notes.append("node score missing -> neutral 5.0")
    if touches is None:
        notes.append("thesis_touches_node unproven -> fail closed, cap BUY_LIMITED")

    return {
        "LOAD_BEARING_NODE": node,
        "LOAD_BEARING_NODE_SCORE": _clamp(score, 0.0, 10.0),
        "THESIS_TOUCHES_NODE": touches,
        "node_cap_buy_limited": touches is not True,
        "evidence": "; ".join(notes) if notes else "OK",
    }


def evaluate_net_edge(thesis: dict[str, Any]) -> dict[str, Any]:
    """NET_EDGE = model_prob - market_implied_prob - friction.  <= 0 blocks."""
    model_p = _num(thesis.get("model_probability"))
    implied_p = _num(thesis.get("market_implied_probability"))
    friction = _num(thesis.get("friction_leakage_estimate"))
    if model_p is None or implied_p is None:
        return {
            "NET_EDGE": None,
            "FRICTION_LEAKAGE_ESTIMATE": friction,
            "evidence": "model/market probability missing -> NET_EDGE not computable",
        }
    friction_val = friction if friction is not None else 0.0
    net = model_p - implied_p - friction_val
    return {
        "NET_EDGE": round(net, 6),
        "FRICTION_LEAKAGE_ESTIMATE": friction_val,
        "evidence": "OK" if friction is not None else "friction missing -> assumed 0.0",
    }


# ---------------------------------------------------------------------------
# Stage multipliers (each clamped <= 1.0: demote-only by construction)
# ---------------------------------------------------------------------------


def _iap_multiplier(iap: float) -> float:
    """1.0 up to IAP 2 (early mover), then linear demotion."""
    return _clamp(1.0 - max(0.0, iap - 2.0) / 10.0, 0.0, 1.0)


def _channel_multiplier(channel_premium: float) -> float:
    """Packaged channels demote gently; farm-gate sourcing keeps 1.0."""
    return _clamp(1.0 - max(0.0, channel_premium - 2.0) / 20.0, 0.0, 1.0)


def _operator_fit_multiplier(fit: float) -> float:
    """fit 0 -> x0.5, fit 10 -> x1.0.  Never above 1.0."""
    return _clamp(0.5 + 0.05 * _clamp(fit, 0.0, 10.0), 0.0, 1.0)


def _gate_for_score(score: float) -> str:
    if score >= 8.0:
        return GATE_BUY_ALLOWED
    if score >= 6.5:
        return GATE_BUY_LIMITED
    if score >= 5.0:
        return GATE_WATCHLIST
    return GATE_BUY_BLOCKED


_GATE_RANK = {
    GATE_BUY_BLOCKED: 0,
    GATE_WATCHLIST: 1,
    GATE_BUY_LIMITED: 2,
    GATE_BUY_ALLOWED: 3,
}


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def evaluate_chicken_gate(
    thesis: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Run the full four-stage demote-only gate over one thesis dict.

    Never raises on missing optional evidence — degrades to neutral
    demotion + evidence notes.  Returns UPPERCASE canonical schema fields
    plus the value-extraction ledger and advisory safety stamps.
    """
    data = thesis if isinstance(thesis, dict) else {}
    evidence_notes: list[str] = []

    lineage = resolve_lineage(data)

    def component(key: str, neutral: float, lo: float, hi: float) -> float:
        val = _num(data.get(key))
        if val is None:
            evidence_notes.append(f"{key}: {INSUFFICIENT_EVIDENCE} -> neutral {neutral}")
            return neutral
        return _clamp(val, lo, hi)

    house_edge = component("house_edge_score", NEUTRAL_COMPONENT_SCORE, 0.0, 10.0)
    input_quality = component("input_quality_score", NEUTRAL_COMPONENT_SCORE, 0.0, 10.0)
    process_integrity = component(
        "process_integrity_score", NEUTRAL_COMPONENT_SCORE, 0.0, 10.0
    )
    label_authenticity = component(
        "label_authenticity_score", NEUTRAL_LABEL_AUTHENTICITY, 0.0, 1.0
    )
    label_premium = component("label_premium", 0.0, 0.0, 10.0)
    bone_value = component("residual_bone_value_score", NEUTRAL_BONE_VALUE, 0.0, 1.0)
    channel_premium = component(
        "channel_premium_score", NEUTRAL_CHANNEL_PREMIUM, 0.0, 10.0
    )
    operator_fit = component("operator_fit_score", NEUTRAL_OPERATOR_FIT, 0.0, 10.0)

    node = evaluate_load_bearing_node(data)
    if node["evidence"] != "OK":
        evidence_notes.append(f"load_bearing_node: {node['evidence']}")

    freshness = evaluate_freshness(data, now=now)
    if freshness["evidence"] != "OK":
        evidence_notes.append(f"freshness: {freshness['evidence']}")

    iap = evaluate_information_access(data)
    if iap["evidence"] != "OK":
        evidence_notes.append(f"information_access: {iap['evidence']}")

    fallacy = evaluate_gamblers_fallacy(data)
    net_edge = evaluate_net_edge(data)
    if net_edge["evidence"] not in ("OK",):
        evidence_notes.append(f"net_edge: {net_edge['evidence']}")

    spoilage_risk = bool(data.get("spoilage_risk"))

    # ---- Stage 1: RAW_TRADE_SCORE ---------------------------------------
    raw_score = (
        RAW_WEIGHTS["house_edge"] * house_edge
        + RAW_WEIGHTS["input_quality"] * input_quality
        + RAW_WEIGHTS["process_integrity"] * process_integrity
        + RAW_WEIGHTS["load_bearing_node"] * node["LOAD_BEARING_NODE_SCORE"]
        + RAW_WEIGHTS["label_authenticity"] * (label_authenticity * 10.0)
        + RAW_WEIGHTS["residual_bone_value"] * (bone_value * 10.0)
    )
    raw_score = _clamp(raw_score, 0.0, 10.0)

    # ---- Stages 2-4: multiplicative, demote-only ------------------------
    freshness_mult = _clamp(freshness["freshness_multiplier"], 0.0, 1.0)
    iap_value = iap["INFORMATION_ACCESS_PREMIUM"]
    iap_mult = _iap_multiplier(iap_value)
    channel_mult = _channel_multiplier(channel_premium)
    fit_mult = _operator_fit_multiplier(operator_fit)

    freshness_adj = raw_score * freshness_mult
    asymmetry_adj = freshness_adj * iap_mult * channel_mult
    operator_fit_adj = asymmetry_adj * fit_mult

    # ---- Value-extraction ledger: raw - final, itemised, named ----------
    after_iap = freshness_adj * iap_mult
    ledger = [
        {
            "stage": "FRESHNESS",
            "extractor": "TIME_AND_EARLIER_HOLDERS",
            "points_eaten": round(raw_score - freshness_adj, 4),
            "detail": (
                f"freshness x{freshness_mult:.3f} "
                f"({freshness['FRESHNESS_STATE']})"
            ),
        },
        {
            "stage": "INFORMATION_ACCESS",
            "extractor": "EARLIER_INFORMED_PARTICIPANTS",
            "points_eaten": round(freshness_adj - after_iap, 4),
            "detail": f"IAP {iap_value:.1f} ({iap['iap_source']}) x{iap_mult:.3f}",
        },
        {
            "stage": "CHANNEL_PACKAGING",
            "extractor": "PACKAGING_CHANNEL_MARKUP",
            "points_eaten": round(after_iap - asymmetry_adj, 4),
            "detail": f"channel premium {channel_premium:.1f} x{channel_mult:.3f}",
        },
        {
            "stage": "OPERATOR_FIT",
            "extractor": "PORTFOLIO_OVERLAP",
            "points_eaten": round(asymmetry_adj - operator_fit_adj, 4),
            "detail": f"operator fit {operator_fit:.1f} x{fit_mult:.3f}",
        },
    ]
    value_eaten_total = round(raw_score - operator_fit_adj, 4)

    # ---- Hard flags (override all arithmetic) ---------------------------
    hard_flags: list[str] = []
    if spoilage_risk:
        hard_flags.append("SPOILAGE_RISK")
    if fallacy["fallacy_unbacked"]:
        hard_flags.append("GAMBLERS_FALLACY_NO_NODE_CHANGE_EVIDENCE")
    if iap_value >= IAP_HARD_BLOCK_THRESHOLD:
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

    # ---- Final gate ------------------------------------------------------
    score_gate = _gate_for_score(operator_fit_adj)
    gate_caps: list[str] = []
    if node["node_cap_buy_limited"] and _GATE_RANK[score_gate] > _GATE_RANK[GATE_BUY_LIMITED]:
        score_gate = GATE_BUY_LIMITED
        gate_caps.append("THESIS_DOES_NOT_PROVABLY_TOUCH_LOAD_BEARING_NODE")

    final_gate = GATE_BUY_BLOCKED if hard_flags else score_gate

    if final_gate == GATE_BUY_BLOCKED:
        blocked_reason = (
            "; ".join(hard_flags)
            if hard_flags
            else f"score {operator_fit_adj:.2f} below 5.0"
        )
        allowed_reason = ""
    else:
        blocked_reason = ""
        allowed_reason = (
            f"score {operator_fit_adj:.2f} ({final_gate})"
            + (f"; capped: {'; '.join(gate_caps)}" if gate_caps else "")
        )

    result: dict[str, Any] = {
        "TICKER": _text(data.get("ticker")) or "UNKNOWN",
        "ASSET_LINEAGE": lineage,
        "THESIS_FIRST_SIGNAL_DATE": _text(data.get("thesis_first_signal_date")) or None,
        "THESIS_HALF_LIFE_DAYS": freshness["THESIS_HALF_LIFE_DAYS"],
        "FRESHNESS_SCORE": freshness["FRESHNESS_SCORE"],
        "FRESHNESS_STATE": freshness["FRESHNESS_STATE"],
        "INFORMATION_ACCESS_PREMIUM": iap_value,
        "CHANNEL_PREMIUM_SCORE": channel_premium,
        "LOAD_BEARING_NODE": node["LOAD_BEARING_NODE"],
        "LOAD_BEARING_NODE_SCORE": node["LOAD_BEARING_NODE_SCORE"],
        "THESIS_TOUCHES_NODE": node["THESIS_TOUCHES_NODE"],
        "GAMBLERS_FALLACY_FLAG": fallacy["GAMBLERS_FALLACY_FLAG"],
        "NODE_CHANGE_EVIDENCE": fallacy["NODE_CHANGE_EVIDENCE"],
        "SPOILAGE_RISK": spoilage_risk,
        "FRICTION_LEAKAGE_ESTIMATE": net_edge["FRICTION_LEAKAGE_ESTIMATE"],
        "NET_EDGE": net_edge["NET_EDGE"],
        "RAW_TRADE_SCORE": round(raw_score, 4),
        "FRESHNESS_ADJ_SCORE": round(freshness_adj, 4),
        "ASYMMETRY_ADJ_SCORE": round(asymmetry_adj, 4),
        "OPERATOR_FIT_ADJ_SCORE": round(operator_fit_adj, 4),
        "FINAL_ACTION_GATE": final_gate,
        "HARD_FLAG_TRIGGERED": "; ".join(hard_flags) if hard_flags else "NONE",
        "GATE_CAPS_APPLIED": gate_caps,
        "BUY_ALLOWED_REASON": allowed_reason,
        "BUY_BLOCKED_REASON": blocked_reason,
        "SCORING_PROFILE_VERSION": SCORING_PROFILE_VERSION,
        "value_extraction_ledger": ledger,
        "value_eaten_total_points": value_eaten_total,
        "value_eaten_pct_of_raw": (
            round(100.0 * value_eaten_total / raw_score, 2) if raw_score > 0 else 0.0
        ),
        "gamblers_fallacy_matched_phrases": fallacy["matched_phrases"],
        "evidence_notes": evidence_notes,
        # Demote-only invariant, asserted structurally: every stage
        # multiplier is clamped to <= 1.0, so final <= raw always.
        "invariant_final_leq_raw": operator_fit_adj <= raw_score + 1e-9,
    }
    result["safety"] = advisory_safety_stamps()
    result["human"] = human_only_stamp()
    return result


# ---------------------------------------------------------------------------
# Trade card (the audit artifact: WHO ate the value, stage by stage)
# ---------------------------------------------------------------------------


def render_trade_card(result: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("=== SLEEPING PASSENGER - CHICKEN GATE TRADE CARD ===")
    add(f"TICKER: {result['TICKER']}    LINEAGE: {result['ASSET_LINEAGE']}")
    add(
        f"FRESHNESS: {result['FRESHNESS_STATE']}"
        f" (score={result['FRESHNESS_SCORE']},"
        f" half-life={result['THESIS_HALF_LIFE_DAYS']}d)"
    )
    add(
        f"LOAD-BEARING NODE: {result['LOAD_BEARING_NODE']}"
        f" (score={result['LOAD_BEARING_NODE_SCORE']},"
        f" thesis touches: {result['THESIS_TOUCHES_NODE']})"
    )
    add(
        f"IAP: {result['INFORMATION_ACCESS_PREMIUM']}"
        f"    NET_EDGE: {result['NET_EDGE']}"
        f"    SPOILAGE: {result['SPOILAGE_RISK']}"
    )
    add(
        f"GAMBLER CHECK: flag={result['GAMBLERS_FALLACY_FLAG']}"
        f" evidence={result['NODE_CHANGE_EVIDENCE']}"
    )
    add("--- score pipeline (demote-only) ---")
    add(f"  RAW_TRADE_SCORE        {result['RAW_TRADE_SCORE']:>7.3f}")
    add(f"  FRESHNESS_ADJ_SCORE    {result['FRESHNESS_ADJ_SCORE']:>7.3f}")
    add(f"  ASYMMETRY_ADJ_SCORE    {result['ASYMMETRY_ADJ_SCORE']:>7.3f}")
    add(f"  OPERATOR_FIT_ADJ_SCORE {result['OPERATOR_FIT_ADJ_SCORE']:>7.3f}")
    add("--- who ate the value before it reached you ---")
    for row in result["value_extraction_ledger"]:
        add(
            f"  {row['stage']:<19} -{row['points_eaten']:<7.3f}"
            f" {row['extractor']}  [{row['detail']}]"
        )
    add(
        f"  TOTAL EATEN: {result['value_eaten_total_points']} points"
        f" ({result['value_eaten_pct_of_raw']}% of raw merit)"
    )
    add(f"FINAL ACTION: {result['FINAL_ACTION_GATE']}")
    if result["HARD_FLAG_TRIGGERED"] != "NONE":
        add(f"HARD FLAGS: {result['HARD_FLAG_TRIGGERED']}")
    if result["GATE_CAPS_APPLIED"]:
        add(f"CAPS: {'; '.join(result['GATE_CAPS_APPLIED'])}")
    if result["evidence_notes"]:
        add("EVIDENCE NOTES:")
        for note in result["evidence_notes"]:
            add(f"  - {note}")
    add("ADVISORY_ONLY | execution gate LOCKED | human decides")
    return "\n".join(lines)


DEMO_THESIS: dict[str, Any] = {
    "ticker": "DEMO",
    "asset_lineage": "DEFENCE",
    "thesis_text": "Backlog conversion accelerates ahead of consensus.",
    "thesis_age_days": 2.0,
    "house_edge_score": 9.5,
    "input_quality_score": 9.0,
    "process_integrity_score": 9.0,
    "load_bearing_node": "Ammunition segment margin",
    "load_bearing_node_score": 9.5,
    "thesis_touches_node": True,
    "label_authenticity_score": 0.95,
    "label_premium": 5.0,
    "residual_bone_value_score": 0.8,
    "information_access_premium": 1.5,
    "channel_premium_score": 1.0,
    "operator_fit_score": 9.0,
    "node_change_evidence": "DEMAND_CHANGE",
    "model_probability": 0.62,
    "market_implied_probability": 0.50,
    "friction_leakage_estimate": 0.02,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Chicken Gate: advisory-only freshness+asymmetry+node gate. "
            "Scores a thesis JSON and prints the trade card."
        )
    )
    parser.add_argument("--thesis-json", help="Path to a thesis JSON file")
    parser.add_argument("--demo", action="store_true", help="Score the demo thesis")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON result")
    args = parser.parse_args(argv)

    if args.demo:
        thesis = dict(DEMO_THESIS)
    elif args.thesis_json:
        with open(args.thesis_json, "r", encoding="utf-8") as fh:
            thesis = json.load(fh)
    else:
        parser.print_help()
        return 2

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
    "evaluate_freshness",
    "evaluate_information_access",
    "evaluate_gamblers_fallacy",
    "evaluate_load_bearing_node",
    "evaluate_net_edge",
    "evaluate_chicken_gate",
    "render_trade_card",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
