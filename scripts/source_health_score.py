"""
Source-health reliability scoring (Sprint 7D.1).

Turns ``compute_source_freshness`` + refresh metadata into a per-source
reliability score and human-readable label.  Pure functions, no I/O —
``scripts.api_server._build_live_sources_status`` calls these helpers
when assembling ``/live-sources/status`` responses.

Formula
-------
``Source_Health = Freshness × Success_Rate × Config_Completeness ×
Error_Severity_Adjustment × Tier_Weight × Operator_Visibility``

The score lives in ``[0.0, 1.0]``.  Label bands:

  0.85 – 1.00 → ``healthy``
  0.65 – 0.84 → ``watch``
  0.40 – 0.64 → ``degraded``
  0.00 – 0.39 → ``unhealthy``

Two terminal categories sidestep scoring entirely:

  ``planned``             → ``planned_not_scored``  (not a failure)
  optional missing key    → ``optional_config_missing`` (soft, not failure)

Importantly:
  * a stale ``core`` source is loud (full impact)
  * a stale ``secondary`` is moderate (half impact)
  * a stale ``optional`` is soft (quarter impact)
  * a ``planned`` adapter is informational, not scored
  * advisory-only — health_label NEVER implies trade authority
"""
from __future__ import annotations

from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

# Special non-numeric labels.
LABEL_HEALTHY = "healthy"
LABEL_WATCH = "watch"
LABEL_DEGRADED = "degraded"
LABEL_UNHEALTHY = "unhealthy"
LABEL_PLANNED_NOT_SCORED = "planned_not_scored"
LABEL_OPTIONAL_MISSING_CONFIG = "optional_config_missing"

_TIER_WEIGHT: dict[str, float] = {
    "core": 1.0,
    "secondary": 0.5,
    "optional": 0.25,
    "planned": 0.0,
}

# Per-freshness-state base subtraction (before tier weighting).
_FRESHNESS_PENALTY: dict[str, float] = {
    "fresh": 0.0,
    "stale": 0.30,
    "overdue": 0.55,
    "never_run": 0.55,
    "failed": 0.60,
    "skipped": 0.40,  # contextual; reduced for optional-missing-config below
}


def _band_for_score(score: float) -> str:
    if score >= 0.85:
        return LABEL_HEALTHY
    if score >= 0.65:
        return LABEL_WATCH
    if score >= 0.40:
        return LABEL_DEGRADED
    return LABEL_UNHEALTHY


def _clamp(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def score_source(entry: dict[str, Any]) -> dict[str, Any]:
    """Score a single source entry.

    Parameters
    ----------
    entry: dict
        The per-source dict produced by
        ``scripts.api_server._build_live_sources_status`` (which has the
        compute_source_freshness output merged with refresh metadata).
        Must contain at minimum ``tier``, ``adapter_status``,
        ``freshness_state``, ``credential_configured``,
        ``hours_since_last_success`` (may be None) and optionally
        ``refresh_age_hours``, ``last_refresh_error``,
        ``last_refresh_skipped``, ``last_refresh_skipped_reason``.

    Returns
    -------
    dict with: ``health_score`` (float in [0,1] or None for non-scored),
    ``health_label`` (one of the LABEL_* constants),
    ``health_reasons`` (list[str] — short phrases for the UI),
    ``stale_severity`` (none/soft/moderate/loud),
    ``config_state`` (configured/optional_missing/required_missing),
    ``last_success_age_hours`` (passthrough),
    ``operator_message`` (single human sentence),
    plus safety stamps.
    """
    tier = str(entry.get("tier") or "optional").lower()
    adapter_status = str(entry.get("adapter_status") or "").lower()
    freshness_state = str(entry.get("freshness_state") or "unknown").lower()
    credential_configured = bool(entry.get("credential_configured", False))
    requires_api_key = bool(entry.get("requires_api_key", False)) or freshness_state == "skipped"
    hours_since_success = entry.get("hours_since_last_success")
    refresh_age_hours = entry.get("refresh_age_hours")
    last_refresh_error = str(entry.get("last_refresh_error") or "")
    last_refresh_skipped = bool(entry.get("last_refresh_skipped", False))
    skip_reason = str(entry.get("last_refresh_skipped_reason") or "")
    last_refresh_success = bool(entry.get("last_refresh_success", False))

    reasons: list[str] = []

    # ---- Terminal: planned adapter -----------------------------------
    if adapter_status == "planned" or tier == "planned":
        return _terminal(
            label=LABEL_PLANNED_NOT_SCORED,
            score=None,
            reasons=["adapter_status=planned — not counted as failure"],
            stale_severity="none",
            config_state="planned",
            operator_message=(
                "Planned source adapter — not counted as a failure. "
                "No action required."
            ),
            entry=entry,
        )

    # ---- Terminal: optional + credential missing ---------------------
    if tier == "optional" and not credential_configured:
        return _terminal(
            label=LABEL_OPTIONAL_MISSING_CONFIG,
            score=None,
            reasons=["optional source missing credential — not a core failure"],
            stale_severity="soft",
            config_state="optional_missing",
            operator_message=(
                "Optional source not configured. This is not a core-source "
                "failure; configure the API key to activate."
            ),
            entry=entry,
        )

    # ---- Scored path -------------------------------------------------
    score = 1.0
    config_state = "configured"
    stale_severity = "none"

    if not credential_configured and tier in {"core", "secondary"}:
        config_state = "required_missing"
        score -= 0.4
        reasons.append("required credential missing")

    base_penalty = _FRESHNESS_PENALTY.get(freshness_state, 0.0)
    if freshness_state == "skipped" and tier == "secondary" and not credential_configured:
        base_penalty = 0.30  # secondary missing credential — moderate, not loud

    tier_weight = _TIER_WEIGHT.get(tier, 0.25)
    weighted_penalty = base_penalty * (0.4 + 0.6 * tier_weight)
    score -= weighted_penalty

    if freshness_state in {"stale", "overdue", "failed", "never_run"}:
        if tier == "core":
            stale_severity = "loud"
        elif tier == "secondary":
            stale_severity = "moderate"
        else:
            stale_severity = "soft"
        reasons.append(f"freshness_state={freshness_state} (tier={tier})")

    if last_refresh_error:
        score -= 0.10 if tier == "core" else 0.05
        # Surface the first line of the error (clipped) — but never log
        # secrets, which compute_source_freshness already strips.
        first_line = last_refresh_error.split("\n", 1)[0][:120]
        reasons.append(f"recent error: {first_line}")

    if last_refresh_skipped and skip_reason:
        reasons.append(f"recent skip: {skip_reason[:80]}")

    if (
        isinstance(hours_since_success, (int, float))
        and hours_since_success is not None
        and hours_since_success > 24
        and tier == "core"
    ):
        score -= 0.10
        reasons.append("last_success_age > 24h on core source")

    if (
        isinstance(refresh_age_hours, (int, float))
        and refresh_age_hours is not None
        and refresh_age_hours > 12
        and freshness_state != "fresh"
        and tier in {"core", "secondary"}
    ):
        score -= 0.05
        reasons.append("last refresh attempt > 12h ago")

    if freshness_state == "fresh" and last_refresh_success:
        if not reasons:
            reasons.append("recent successful refresh")

    score = _clamp(score)
    label = _band_for_score(score)

    operator_message = _build_operator_message(
        label=label,
        tier=tier,
        freshness_state=freshness_state,
        config_state=config_state,
        stale_severity=stale_severity,
        has_error=bool(last_refresh_error),
    )

    return {
        "health_score": round(score, 4),
        "health_label": label,
        "health_reasons": reasons,
        "tier": tier,
        "stale_severity": stale_severity,
        "config_state": config_state,
        "last_success_age_hours": (
            round(hours_since_success, 4)
            if isinstance(hours_since_success, (int, float))
            else None
        ),
        "operator_message": operator_message,
        "advisory_status": ADVISORY_STATUS,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_permission": False,
        "can_execute": False,
    }


def _terminal(
    *,
    label: str,
    score: float | None,
    reasons: list[str],
    stale_severity: str,
    config_state: str,
    operator_message: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    return {
        "health_score": score,
        "health_label": label,
        "health_reasons": reasons,
        "tier": str(entry.get("tier") or "optional"),
        "stale_severity": stale_severity,
        "config_state": config_state,
        "last_success_age_hours": entry.get("hours_since_last_success"),
        "operator_message": operator_message,
        "advisory_status": ADVISORY_STATUS,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_permission": False,
        "can_execute": False,
    }


def _build_operator_message(
    *,
    label: str,
    tier: str,
    freshness_state: str,
    config_state: str,
    stale_severity: str,
    has_error: bool,
) -> str:
    if label == LABEL_HEALTHY:
        return "Source is healthy — recent successful refresh."
    if label == LABEL_WATCH:
        if has_error:
            return (
                f"Source is on watch (tier={tier}). A recent refresh error "
                "is recorded; check the source_errors field."
            )
        return f"Source is on watch (tier={tier}); freshness {freshness_state}."
    if label == LABEL_DEGRADED:
        if stale_severity == "loud":
            return (
                "Core source is degraded. Run the refresh script or check "
                "the scheduled task."
            )
        return (
            f"Source is degraded (tier={tier}). Operator review recommended."
        )
    if label == LABEL_UNHEALTHY:
        if tier == "core":
            return (
                "Core source unhealthy. Local advisory data may be stale — "
                "run refresh and investigate the error."
            )
        return (
            f"Source unhealthy (tier={tier}). Not blocking core advisory, "
            "but operator should investigate."
        )
    return "No operator message."


def aggregate_health(per_source: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build the top-level health summary across all scored sources.

    Returns:
      - health_label_distribution: counts per label
      - core_health_label: worst label among core sources, else 'healthy'
      - average_scored_health: mean of numeric health_scores
      - scored_count, planned_count, optional_missing_config_count
    """
    label_dist: dict[str, int] = {}
    scored: list[float] = []
    core_scores: list[float] = []
    core_labels: list[str] = []

    for entry in per_source.values():
        label = entry.get("health_label", LABEL_WATCH)
        label_dist[label] = label_dist.get(label, 0) + 1
        score = entry.get("health_score")
        if isinstance(score, (int, float)):
            scored.append(float(score))
            if entry.get("tier") == "core":
                core_scores.append(float(score))
                core_labels.append(label)

    average = sum(scored) / len(scored) if scored else None

    # Worst core label = lowest band among core sources.
    band_rank = {
        LABEL_HEALTHY: 4,
        LABEL_WATCH: 3,
        LABEL_DEGRADED: 2,
        LABEL_UNHEALTHY: 1,
    }
    if core_labels:
        worst_core_label = min(
            core_labels,
            key=lambda lab: band_rank.get(lab, 0),
        )
    else:
        worst_core_label = LABEL_HEALTHY

    return {
        "health_label_distribution": label_dist,
        "core_health_label": worst_core_label,
        "average_scored_health": (
            round(average, 4) if average is not None else None
        ),
        "scored_count": len(scored),
        "planned_count": label_dist.get(LABEL_PLANNED_NOT_SCORED, 0),
        "optional_missing_config_count": label_dist.get(
            LABEL_OPTIONAL_MISSING_CONFIG, 0
        ),
        "advisory_status": ADVISORY_STATUS,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_permission": False,
        "can_execute": False,
    }


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "LABEL_HEALTHY",
    "LABEL_WATCH",
    "LABEL_DEGRADED",
    "LABEL_UNHEALTHY",
    "LABEL_PLANNED_NOT_SCORED",
    "LABEL_OPTIONAL_MISSING_CONFIG",
    "score_source",
    "aggregate_health",
]
