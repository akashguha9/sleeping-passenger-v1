"""Live Payload Quality (LPQ) + freshness SLA arithmetic (Integrated Sprint — Part 3).

Inputs are per-provider source-health rows (produced by adapters / runners).
Outputs are:

* per-provider ``freshness_score``  = exp(-ln(2) * age_hours / SLA_hours)
* per-class ``source_class_health`` = weighted mean over providers of that class
* a single ``LPQ`` (Live Payload Quality) in ``[0, 1]``
* the live multiplier ``M_live`` and the chosen downgrade reasons

The four source classes the sprint requires:

    price       (e.g. yfinance)
    filings     (e.g. SEC EDGAR)
    news_event  (e.g. GDELT / NewsAPI)
    ai_report   (the five-model interpretation lane)

Verification statuses propagate as in the sprint spec:

    VERIFIED                                   → multiplier 1.00
    UNVERIFIED                                 → 0.70
    STALE                                      → 0.50
    FALLBACK                                   → 0.35
    MOCK                                       → 0.20
    DEGRADED (no STALE/FALLBACK/MOCK)          → 0.85

Pure module; no DB, no broker calls, no execution, no AI execution.
"""
from __future__ import annotations

import argparse
import json
import math
from typing import Any, Iterable

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

# Required source classes that participate in LPQ.  ``ai_report`` is optional
# in practice (if no models have spoken today, we mark UNKNOWN, never fake).
SOURCE_CLASSES: tuple[str, ...] = ("price", "filings", "news_event", "ai_report")

CLASS_WEIGHTS: dict[str, float] = {
    "price": 0.30,
    "filings": 0.25,
    "news_event": 0.25,
    "ai_report": 0.20,
}

# SLA defaults (hours).  Caller can override via typed_config.
SLA_DEFAULTS_HOURS: dict[str, float] = {
    "price": 24.0,
    "filings": 72.0,
    "news_event": 24.0,
    "ai_report": 24.0,
}

# Status taxonomy understood by this module.  Anything else is treated as
# UNKNOWN, which never counts as HEALTHY.
STATUS_HEALTHY = "HEALTHY"
STATUS_DEGRADED = "DEGRADED"
STATUS_STALE = "STALE"
STATUS_OFFLINE = "OFFLINE"
STATUS_FALLBACK = "FALLBACK"
STATUS_MOCK = "MOCK"
STATUS_UNKNOWN = "UNKNOWN"

VERIF_VERIFIED = "VERIFIED"
VERIF_UNVERIFIED = "UNVERIFIED"
VERIF_STALE = "STALE"
VERIF_FALLBACK = "FALLBACK"
VERIF_MOCK = "MOCK"

# Downgrade reason vocabulary the cockpit and release gate consume.
DOWNGRADE_REASONS: tuple[str, ...] = (
    "PRICE_SOURCE_STALE",
    "PRICE_SOURCE_UNVERIFIED",
    "PRICE_SOURCE_FALLBACK",
    "FILINGS_SOURCE_STALE",
    "FILINGS_SOURCE_UNVERIFIED",
    "NEWS_SOURCE_STALE",
    "NEWS_SOURCE_FALLBACK",
    "AI_REPORT_SOURCE_MISSING",
    "LPQ_BELOW_THRESHOLD",
    "WHY_TODAY_WEAK",
    "MODEL_DISAGREEMENT_HIGH",
    "DIABLO_MODEL_VETO",
    "ADVISORY_ONLY_LOCK",
)


# --- core arithmetic ------------------------------------------------------


def _clamp01(value: float) -> float:
    if value is None or math.isnan(value):
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def freshness_score(age_hours: float | None, sla_hours: float) -> float:
    """``exp(-ln(2) * age_hours / sla_hours)``; ``None`` ages → 0 (unknown is not fresh)."""
    if age_hours is None or sla_hours <= 0:
        return 0.0
    age = max(0.0, float(age_hours))
    return round(math.exp(-math.log(2.0) * age / float(sla_hours)), 6)


def verification_multiplier(verification_status: str | None) -> float:
    status = (verification_status or "").upper()
    if status == VERIF_VERIFIED:
        return 1.00
    if status == VERIF_UNVERIFIED:
        return 0.70
    if status == VERIF_STALE:
        return 0.50
    if status == VERIF_FALLBACK:
        return 0.35
    if status == VERIF_MOCK:
        return 0.20
    return 0.0


def status_multiplier(status: str | None) -> float:
    s = (status or "").upper()
    if s == STATUS_HEALTHY:
        return 1.00
    if s == STATUS_DEGRADED:
        return 0.85
    if s == STATUS_STALE:
        return 0.50
    if s == STATUS_FALLBACK:
        return 0.35
    if s == STATUS_MOCK:
        return 0.20
    if s == STATUS_OFFLINE:
        return 0.0
    return 0.0


def provider_health_score(provider: dict[str, Any]) -> float:
    """Combine freshness + verification + status into a single 0..1 score.

    Required inputs (best-effort; missing fields degrade safely):
      * ``age_hours``           — float (hours since latest verified event)
      * ``sla_hours``           — float
      * ``verification_status`` — VERIFIED|UNVERIFIED|STALE|FALLBACK|MOCK
      * ``status``              — HEALTHY|DEGRADED|STALE|OFFLINE|FALLBACK|MOCK
    """
    age = provider.get("age_hours")
    sla = provider.get("sla_hours") or SLA_DEFAULTS_HOURS.get(
        str(provider.get("source_class") or "").lower(), 24.0)
    fresh = freshness_score(age, sla)
    verif_mult = verification_multiplier(provider.get("verification_status"))
    stat_mult = status_multiplier(provider.get("status"))
    score = 0.50 * fresh + 0.25 * verif_mult + 0.25 * stat_mult
    return round(_clamp01(score), 6)


def aggregate_class_health(
    providers: Iterable[dict[str, Any]],
    source_class: str,
) -> dict[str, Any]:
    """Mean per-provider health within a class plus the worst verification/status."""
    rows = [p for p in providers if str(p.get("source_class") or "").lower()
            == source_class.lower()]
    if not rows:
        return {
            "source_class": source_class,
            "provider_count": 0,
            "class_health": 0.0,
            "worst_verification": None,
            "worst_status": None,
            "any_stale": False,
            "any_fallback": False,
            "any_mock": False,
            "any_unverified": False,
            "any_missing": True,
        }

    per_health = [provider_health_score(p) for p in rows]
    verifications = [str(p.get("verification_status") or "").upper() for p in rows]
    statuses = [str(p.get("status") or "").upper() for p in rows]

    rank = {
        VERIF_VERIFIED: 0, VERIF_UNVERIFIED: 1, VERIF_STALE: 2,
        VERIF_FALLBACK: 3, VERIF_MOCK: 4,
    }
    worst_verif = max(
        verifications,
        key=lambda v: rank.get(v, 5),
    ) if verifications else None
    status_rank = {
        STATUS_HEALTHY: 0, STATUS_DEGRADED: 1, STATUS_STALE: 2,
        STATUS_OFFLINE: 3, STATUS_FALLBACK: 4, STATUS_MOCK: 5,
    }
    worst_status = max(
        statuses,
        key=lambda s: status_rank.get(s, 6),
    ) if statuses else None

    return {
        "source_class": source_class,
        "provider_count": len(rows),
        "class_health": round(sum(per_health) / len(per_health), 6),
        "worst_verification": worst_verif,
        "worst_status": worst_status,
        "any_stale": any(s == STATUS_STALE or v == VERIF_STALE
                         for s, v in zip(statuses, verifications)),
        "any_fallback": any(s == STATUS_FALLBACK or v == VERIF_FALLBACK
                            for s, v in zip(statuses, verifications)),
        "any_mock": any(s == STATUS_MOCK or v == VERIF_MOCK
                        for s, v in zip(statuses, verifications)),
        "any_unverified": any(v == VERIF_UNVERIFIED for v in verifications),
        "any_missing": False,
    }


def compute_lpq(
    providers: Iterable[dict[str, Any]],
    *,
    class_weights: dict[str, float] | None = None,
    ai_required: bool = False,
) -> dict[str, Any]:
    """Compute LPQ + per-class breakdown + downgrade reasons + M_live.

    ``ai_required=False`` (default) lets the AI report class be marked
    ``UNKNOWN`` without forcing a downgrade; the LPQ then redistributes its
    weight across the remaining classes.  This matches the sprint rule:
    *do not fake AI source presence*.
    """
    weights = dict(class_weights or CLASS_WEIGHTS)
    providers_list = list(providers)

    per_class: dict[str, dict[str, Any]] = {}
    for cls in SOURCE_CLASSES:
        per_class[cls] = aggregate_class_health(providers_list, cls)

    # Redistribute AI weight if AI not required AND not present.
    effective_weights = dict(weights)
    if not ai_required and per_class["ai_report"]["any_missing"]:
        ai_weight = effective_weights.pop("ai_report", 0.0)
        # Spread proportionally across remaining classes.
        remaining = sum(effective_weights.values())
        if remaining > 0 and ai_weight > 0:
            for k in list(effective_weights):
                effective_weights[k] += effective_weights[k] / remaining * ai_weight

    weighted_sum = 0.0
    weight_total = 0.0
    for cls, info in per_class.items():
        w = effective_weights.get(cls, 0.0)
        if w <= 0:
            continue
        weighted_sum += w * info["class_health"]
        weight_total += w
    lpq = _clamp01(weighted_sum / weight_total) if weight_total > 0 else 0.0

    # Downgrade reasons + M_live (most punitive of the rules wins).
    reasons: list[str] = []
    if per_class["price"]["any_stale"]:
        reasons.append("PRICE_SOURCE_STALE")
    if per_class["price"]["any_unverified"]:
        reasons.append("PRICE_SOURCE_UNVERIFIED")
    if per_class["price"]["any_fallback"]:
        reasons.append("PRICE_SOURCE_FALLBACK")
    if per_class["filings"]["any_stale"]:
        reasons.append("FILINGS_SOURCE_STALE")
    if per_class["filings"]["any_unverified"]:
        reasons.append("FILINGS_SOURCE_UNVERIFIED")
    if per_class["news_event"]["any_stale"]:
        reasons.append("NEWS_SOURCE_STALE")
    if per_class["news_event"]["any_fallback"]:
        reasons.append("NEWS_SOURCE_FALLBACK")
    if ai_required and per_class["ai_report"]["any_missing"]:
        reasons.append("AI_REPORT_SOURCE_MISSING")
    if lpq < 0.80:
        reasons.append("LPQ_BELOW_THRESHOLD")

    # M_live picks the most punitive matching rule.
    if any(per_class[c]["any_mock"] for c in SOURCE_CLASSES):
        m_live = 0.20
    elif any(per_class[c]["any_fallback"] for c in SOURCE_CLASSES):
        m_live = 0.35
    elif any(per_class[c]["any_stale"] for c in SOURCE_CLASSES):
        m_live = 0.50
    elif any(per_class[c]["any_unverified"] for c in SOURCE_CLASSES):
        m_live = 0.70
    elif any(per_class[c]["worst_status"] == STATUS_DEGRADED
             for c in SOURCE_CLASSES if not per_class[c]["any_missing"]):
        m_live = 0.85
    else:
        m_live = 1.00

    return {
        "report": "live_payload_quality",
        "lpq": round(lpq, 6),
        "lpq_threshold": 0.80,
        "lpq_above_threshold": lpq >= 0.80,
        "m_live": m_live,
        "downgrade_reasons": sorted(set(reasons)),
        "per_class": per_class,
        "class_weights_used": effective_weights,
        "ai_required": bool(ai_required),
        **_contract.advisory_safety_stamps(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="live_payload_quality.py",
        description=(
            "Compute LPQ + M_live + downgrade reasons from a JSON list of "
            "provider rows. Read-only; no broker calls; no execution."
        ),
    )
    p.add_argument("--providers-file", type=str, default=None,
                   help="path to a JSON file with the provider rows")
    p.add_argument("--providers-json", type=str, default=None,
                   help="inline JSON for the provider rows")
    p.add_argument("--ai-required", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    providers: list[dict[str, Any]] = []
    if args.providers_file:
        from pathlib import Path
        providers = list(json.loads(
            Path(args.providers_file).read_text(encoding="utf-8")))
    if args.providers_json:
        providers = list(json.loads(args.providers_json))
    out = compute_lpq(providers, ai_required=args.ai_required)
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print("Live Payload Quality (advisory)")
        print("===============================")
        for key in ("lpq", "m_live", "lpq_above_threshold", "downgrade_reasons"):
            print(f"  {key:<24} : {out.get(key)}")
    return 0 if out["lpq_above_threshold"] else 1


__all__ = [
    "SOURCE_CLASSES",
    "CLASS_WEIGHTS",
    "SLA_DEFAULTS_HOURS",
    "DOWNGRADE_REASONS",
    "freshness_score",
    "verification_multiplier",
    "status_multiplier",
    "provider_health_score",
    "aggregate_class_health",
    "compute_lpq",
]


if __name__ == "__main__":
    raise SystemExit(main())
