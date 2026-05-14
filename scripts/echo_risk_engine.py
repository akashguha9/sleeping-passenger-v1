"""Echo risk + source independence engine — pure, deterministic, advisory-only.

Engineering translation of the reflection's "echo is not confirmation"
doctrine. The module separates *repetition* from *independent
confirmation* and stamps a structured score plus a safety contract.

Safety contract (every public output)

    output["safety"]["advisory_status"]     == "ADVISORY_ONLY"
    output["safety"]["execution_gate"]      == "LOCKED"
    output["safety"]["broker_api_called"]   is False
    output["safety"]["ai_execution_count"]  == 0
    output["safety"]["execution_permission"] is False
    output["safety"]["can_execute"]         is False

Public API

    compute_source_independence(items)        -> dict
    compute_echo_risk(items)                  -> dict
    classify_confirmation_quality(items)      -> dict

No DB writes, no live API calls, no broker hooks.
"""

from __future__ import annotations

from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}

CONFIRMATION_QUALITIES: tuple[str, ...] = (
    "independent_confirmation",
    "weak_confirmation",
    "echo_amplification",
    "missing_primary_source",
    "insufficient_data",
)


def _stamp(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["safety"] = dict(SAFETY_STAMPS)
    out.setdefault("advisory_status", ADVISORY_STATUS)
    out.setdefault("execution_gate", EXECUTION_GATE_LOCKED)
    return out


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return lo
    if x != x:
        return lo
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _rows(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [r for r in items if isinstance(r, dict)]


def _dedupe_key(row: dict[str, Any]) -> str:
    claim_hash = _text(row.get("claim_hash"))
    if claim_hash:
        return f"claim:{claim_hash}"
    event_id = _text(row.get("event_id"))
    canonical = _text(row.get("canonical_url"))
    if canonical:
        return f"url:{canonical}|event:{event_id}"
    url = _text(row.get("url"))
    if url:
        return f"url:{url}|event:{event_id}"
    title = _text(row.get("title"))
    return f"title:{title}|event:{event_id}"


def _source_key(row: dict[str, Any]) -> str:
    explicit_original = _text(row.get("original_source"))
    if explicit_original:
        return f"origin:{explicit_original}"
    name = _text(row.get("source_name"))
    family = _text(row.get("source_type"))
    if name:
        return f"source:{name}|family:{family}"
    return f"family:{family}"


def compute_source_independence(items: Any) -> dict[str, Any]:
    rows = _rows(items)
    if not rows:
        return _stamp({
            "total_mention_count": 0,
            "unique_dedupe_keys": 0,
            "independent_source_count": 0,
            "duplicate_or_echo_count": 0,
            "primary_source_present": False,
            "source_independence_score": 0.0,
            "reasons": ["no_items"],
        })

    seen_dedupe: dict[str, int] = {}
    unique_sources: set[str] = set()
    primary_source_present = False
    for row in rows:
        key = _dedupe_key(row)
        seen_dedupe[key] = seen_dedupe.get(key, 0) + 1
        unique_sources.add(_source_key(row))
        if _text(row.get("source_type")) in {"primary", "official", "filing", "regulatory"}:
            primary_source_present = True
        if row.get("primary_source_present") is True:
            primary_source_present = True

    total_mentions = len(rows)
    unique_dedupe = len(seen_dedupe)
    duplicate_or_echo_count = total_mentions - unique_dedupe
    independent_sources = len(unique_sources)
    independence = _clamp(independent_sources / max(total_mentions, 1))

    reasons: list[str] = []
    if duplicate_or_echo_count > 0:
        reasons.append("duplicate_dedupe_keys_detected")
    if independent_sources <= 1 and total_mentions >= 2:
        reasons.append("only_one_unique_source")
    if not primary_source_present:
        reasons.append("no_primary_or_official_source")

    return _stamp({
        "total_mention_count": total_mentions,
        "unique_dedupe_keys": unique_dedupe,
        "independent_source_count": independent_sources,
        "duplicate_or_echo_count": duplicate_or_echo_count,
        "primary_source_present": bool(primary_source_present),
        "source_independence_score": round(independence, 4),
        "reasons": reasons,
    })


def compute_echo_risk(items: Any) -> dict[str, Any]:
    rows = _rows(items)
    independence_payload = compute_source_independence(rows)
    total_mentions = independence_payload["total_mention_count"]
    if total_mentions == 0:
        return _stamp({
            "echo_risk_score": 0.0,
            "ai_echo_risk_score": 0.0,
            "promotion_penalty": 0.0,
            "true_confirmation_ratio": 0.0,
            "total_mention_count": 0,
            "independent_source_count": 0,
            "primary_source_present": False,
            "duplicate_or_echo_count": 0,
            "reasons": ["no_items"],
        })

    repetition = _clamp(
        independence_payload["duplicate_or_echo_count"] / max(total_mentions, 1)
    )
    independent_sources = independence_payload["independent_source_count"]
    source_dependency = _clamp(1.0 - (independent_sources / max(total_mentions, 1)))
    primary_present = independence_payload["primary_source_present"]
    lack_of_primary = 0.0 if primary_present else 1.0

    echo_risk = _clamp(
        0.5 * source_dependency
        + 0.3 * repetition
        + 0.2 * lack_of_primary
    )

    ai_agreement = _coerce_int(
        sum(_coerce_int(r.get("ai_agreement_count")) for r in rows)
    )
    external_anchors = _coerce_int(
        sum(_coerce_int(r.get("external_anchor_count")) for r in rows)
    )
    ai_echo_risk = 0.0
    if ai_agreement > 0:
        anchor_strength = _clamp(external_anchors / max(ai_agreement, 1))
        ai_echo_risk = _clamp(1.0 - anchor_strength)

    true_confirmation_ratio = round(
        independent_sources / max(total_mentions, 1), 4
    )

    promotion_penalty = _clamp(0.5 * echo_risk + 0.3 * ai_echo_risk + 0.2 * lack_of_primary)

    reasons: list[str] = []
    if echo_risk >= 0.6:
        reasons.append("echo_dominated_inputs")
    if ai_echo_risk >= 0.5:
        reasons.append("ai_agreement_without_external_anchors")
    if not primary_present and total_mentions >= 3:
        reasons.append("missing_primary_source")
    if independent_sources <= 1 and total_mentions >= 2:
        reasons.append("single_dependent_source_chain")

    return _stamp({
        "echo_risk_score": round(echo_risk, 4),
        "ai_echo_risk_score": round(ai_echo_risk, 4),
        "promotion_penalty": round(promotion_penalty, 4),
        "true_confirmation_ratio": true_confirmation_ratio,
        "total_mention_count": total_mentions,
        "independent_source_count": independent_sources,
        "primary_source_present": bool(primary_present),
        "duplicate_or_echo_count": independence_payload["duplicate_or_echo_count"],
        "reasons": reasons,
    })


def classify_confirmation_quality(items: Any) -> dict[str, Any]:
    rows = _rows(items)
    independence_payload = compute_source_independence(rows)
    echo_payload = compute_echo_risk(rows)

    total_mentions = independence_payload["total_mention_count"]
    independent_sources = independence_payload["independent_source_count"]
    primary_present = independence_payload["primary_source_present"]
    echo_risk = echo_payload["echo_risk_score"]

    if total_mentions == 0:
        quality = "insufficient_data"
    elif independent_sources >= 3 and primary_present:
        quality = "independent_confirmation"
    elif independent_sources >= 2 and echo_risk < 0.5:
        quality = "independent_confirmation"
    elif independent_sources >= 2:
        quality = "weak_confirmation"
    elif not primary_present and total_mentions >= 3:
        quality = "echo_amplification" if echo_risk >= 0.5 else "missing_primary_source"
    else:
        quality = "echo_amplification" if echo_risk >= 0.5 else "weak_confirmation"

    operator_action_map = {
        "independent_confirmation": "review_candidate",
        "weak_confirmation": "watch",
        "echo_amplification": "decay_archive",
        "missing_primary_source": "review_later",
        "insufficient_data": "observe",
    }

    return _stamp({
        "confirmation_quality": quality,
        "echo_risk_score": echo_payload["echo_risk_score"],
        "ai_echo_risk_score": echo_payload["ai_echo_risk_score"],
        "promotion_penalty": echo_payload["promotion_penalty"],
        "true_confirmation_ratio": echo_payload["true_confirmation_ratio"],
        "independent_source_count": independent_sources,
        "total_mention_count": total_mentions,
        "primary_source_present": bool(primary_present),
        "source_independence_score": independence_payload["source_independence_score"],
        "operator_action": operator_action_map[quality],
        "reasons": echo_payload["reasons"],
    })


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "SAFETY_STAMPS",
    "CONFIRMATION_QUALITIES",
    "compute_source_independence",
    "compute_echo_risk",
    "classify_confirmation_quality",
]
