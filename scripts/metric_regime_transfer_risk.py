"""Metric Regime Transfer Risk (MTR) — P1 interpretation-defense module.

Ships the reflection thesis "a metric is only valid inside the environment that
produced it" (see docs/INTERPRETATION_DEFENSE_COMPONENT_MAP.md). Conceptual
lineage: scripts/regime_translation_tester.py (RTT) tests whether a *thesis*
survives a regime change on CE scores; MTR is the lighter, payload-level analog
that operates on the clean fresh-discovery candidate contract (which has no CE
score) and asks whether the candidate's evidence/metric is anchored to a clear
current regime, or is being transferred across geography / sector / currency /
liquidity / thesis-type without support.

    MTR = 100 * (1 - environment_similarity)

Two modes:
  * comparison mode — a ``reference_regime`` (the environment the metric is being
    applied to) is supplied; similarity is per-dimension match between the
    candidate's own regime and the reference.
  * self-anchor mode — no reference; similarity = how completely the candidate is
    anchored to a single, current, catalysed regime.

Never invents or promotes candidates. Advisory-only. Pure module.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.daily_payload import normalize_ticker
    from scripts.fresh_discovery_contract import LIVE_EVIDENCE_TYPES, VERIFIED_LIVE
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from daily_payload import normalize_ticker
    from fresh_discovery_contract import LIVE_EVIDENCE_TYPES, VERIFIED_LIVE


GRADE_LOW = "LOW"
GRADE_MEDIUM = "MEDIUM"
GRADE_HIGH = "HIGH"
GRADE_UNRELIABLE = "UNRELIABLE_TRANSFER"

_CORE_REGIME_FIELDS = ("country", "sector", "evidence_type")
_INDIA_MARKERS = ("INDIA", ".NS", "IN")


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _known(value: Any) -> bool:
    text = str(value or "").strip().upper()
    return bool(text) and text not in {"UNKNOWN", "NONE", "MISSING"}


def _catalyst(candidate: dict[str, Any]) -> Any:
    return candidate.get("catalyst") or candidate.get("why_today")


def _is_india(candidate_or_regime: dict[str, Any]) -> bool:
    ticker = str(candidate_or_regime.get("ticker") or "").upper()
    country = str(candidate_or_regime.get("country") or "").upper()
    region = str(candidate_or_regime.get("region") or "").upper()
    if ticker.endswith(".NS"):
        return True
    return any(m == country or m == region for m in ("INDIA",))


def _source_regime(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "geography": str(candidate.get("country") or candidate.get("region") or "").upper() or None,
        "sector": str(candidate.get("sector") or "").upper() or None,
        "currency": str(candidate.get("currency") or "").upper() or ("INR" if str(candidate.get("ticker") or "").upper().endswith(".NS") else None),
        "thesis_type": candidate.get("evidence_type"),
        "leverage": candidate.get("leverage"),
        "has_catalyst": _known(_catalyst(candidate)),
    }


def _self_anchor_similarity(candidate: dict[str, Any]) -> tuple[float, list[str], list[str]]:
    """Similarity = how completely anchored to one current, catalysed regime."""
    dims: dict[str, float] = {}
    flags: list[str] = []
    dims["geography"] = 1.0 if _known(candidate.get("country") or candidate.get("region")) else 0.0
    dims["sector"] = 1.0 if _known(candidate.get("sector")) else 0.0
    dims["thesis_type"] = (
        1.0 if candidate.get("evidence_type") in ("LIVE_NEWS_EVENT", "LIVE_FILING_EVENT")
        else 0.6 if candidate.get("evidence_type") == "LIVE_PRICE_MOVER" else 0.0
    )
    dims["catalyst_currency"] = 1.0 if _known(_catalyst(candidate)) else 0.0
    dims["theme"] = 1.0 if _known(candidate.get("theme")) else 0.4
    if dims["catalyst_currency"] == 0.0:
        flags.append("structural_or_famous_without_current_catalyst")
    missing = [d for d, v in dims.items() if v == 0.0 and d in ("geography", "sector")]
    similarity = sum(dims.values()) / len(dims)
    return similarity, flags, missing


def _comparison_similarity(
    source: dict[str, Any], reference: dict[str, Any]
) -> tuple[float, list[str]]:
    flags: list[str] = []
    dims: list[float] = []

    def match(a: Any, b: Any) -> float:
        if not _known(a) or not _known(b):
            return 0.5  # unknown — neither confirmed match nor mismatch
        return 1.0 if str(a).upper() == str(b).upper() else 0.0

    geo = match(source.get("geography"), reference.get("geography"))
    sec = match(source.get("sector"), reference.get("sector"))
    cur = match(source.get("currency"), reference.get("currency"))
    dims += [geo, sec, cur]
    if geo == 0.0:
        flags.append("geography_mismatch")
    if sec == 0.0:
        flags.append("sector_mismatch")
    if cur == 0.0:
        flags.append("currency_mismatch")

    # Leverage compatibility: applying a spot/global thesis into a leveraged
    # (e.g. India 4x) context is a transfer hazard.
    ref_lev = reference.get("leverage")
    if ref_lev and float(ref_lev) > 1.0:
        dims.append(0.0)
        flags.append("leverage_context_mismatch")
    return (sum(dims) / len(dims) if dims else 0.5), flags


def score_metric_regime_transfer_risk(
    candidate: dict[str, Any],
    *,
    reference_regime: dict[str, Any] | None = None,
    model_outputs: list[dict[str, Any]] | None = None,
    run_date: str | None = None,
) -> dict[str, Any]:
    """Return the MTR record for one clean fresh-discovery candidate."""
    ticker = normalize_ticker(candidate.get("ticker"))
    source = _source_regime(candidate)
    warnings: list[str] = []
    missing_fields = [f for f in _CORE_REGIME_FIELDS if not _known(
        candidate.get("country") if f == "country" else
        candidate.get("sector") if f == "sector" else
        (candidate.get("evidence_type") if candidate.get("evidence_type") in LIVE_EVIDENCE_TYPES else None)
    )]

    if reference_regime:
        similarity, regime_flags = _comparison_similarity(source, reference_regime)
        target = dict(reference_regime)
    else:
        similarity, regime_flags, anchor_missing = _self_anchor_similarity(candidate)
        for f in anchor_missing:
            if f not in missing_fields:
                missing_fields.append(f)
        target = {"mode": "self_anchor"}

    risk = round(100.0 * (1.0 - _clamp01(similarity)), 4)

    # ----- Hard warnings / overrides -----
    revalidated = (
        candidate.get("source_health") == VERIFIED_LIVE
        and candidate.get("is_live") is True
        and bool(run_date)
        and str(candidate.get("last_live_seen_date")) == str(run_date)
    )
    # Genuine stale reuse = a non-live provenance flag that was NOT revalidated
    # by today's live evidence. A live price mover is itself fresh evidence, so a
    # merely missing catalyst *string* is handled by the softer HIGH cap below,
    # not treated as stale reuse.
    reused_without_fresh = (
        any(candidate.get(f) is True for f in ("from_cache", "from_moltbook", "from_trade_log"))
        and not revalidated
    )

    if missing_fields:
        risk = max(risk, 76.0)
        warnings.append(f"missing_regime_fields:{missing_fields}")
    if reused_without_fresh:
        risk = max(risk, 76.0)
        warnings.append("reused_thesis_without_fresh_evidence")
    if reference_regime and float(reference_regime.get("leverage") or 1.0) > 1.0 and not _is_india(candidate):
        # global thesis pushed into a leveraged context
        risk = max(risk, 51.0)
        warnings.append("global_thesis_into_leveraged_context")
    if "sector_mismatch" in regime_flags:
        risk = max(risk, 51.0)
    if not _known(_catalyst(candidate)):
        risk = max(risk, 51.0)
        warnings.append("structural_without_current_catalyst")

    grade = _grade(risk)
    return {
        "ticker": ticker,
        "metric_regime_transfer_risk": round(risk, 4),
        "grade": grade,
        "environment_similarity": round(_clamp01(similarity), 6),
        "regime_shift_flags": regime_flags,
        "metric_transfer_warnings": warnings,
        "source_regime": source,
        "target_regime": target,
        "missing_regime_fields": missing_fields,
        "advisory_only": True,
    }


def _grade(risk: float) -> str:
    if risk <= 25:
        return GRADE_LOW
    if risk <= 50:
        return GRADE_MEDIUM
    if risk <= 75:
        return GRADE_HIGH
    return GRADE_UNRELIABLE


__all__ = [
    "GRADE_LOW",
    "GRADE_MEDIUM",
    "GRADE_HIGH",
    "GRADE_UNRELIABLE",
    "score_metric_regime_transfer_risk",
]
