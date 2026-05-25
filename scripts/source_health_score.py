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

# Per-source *configuration gate* hints.  These are env vars that, when
# unset, cause a source to skip cleanly without raising — e.g. the SEC
# loader needs either a CIK or the watchlist; the Etherscan public-tx
# loader needs an address (the key alone is not enough); GDELT honours
# an optional timeout override.
#
# Surfacing these names verbatim in the actionable_next_step lets the
# operator copy-paste straight into ``.env`` instead of grepping
# ``.env.example``.  These entries never *flip* an unhealthy source to
# healthy — they only enrich the action string.
_CONFIG_GATE_HINTS: dict[str, tuple[str, ...]] = {
    # SEC EDGAR — either a single CIK or the built-in watchlist toggle.
    "sec_edgar": (
        "SEC_USER_AGENT",
        "SEC_DEFAULT_CIK",
        "SEC_DEFAULT_WATCHLIST",
        "SEC_USE_DEFAULT_WATCHLIST",
    ),
    "sec": (
        "SEC_USER_AGENT",
        "SEC_DEFAULT_CIK",
        "SEC_DEFAULT_WATCHLIST",
        "SEC_USE_DEFAULT_WATCHLIST",
    ),
    "global_filings_sec": (
        "SEC_USER_AGENT",
        "SEC_DEFAULT_CIK",
        "SEC_DEFAULT_WATCHLIST",
        "SEC_USE_DEFAULT_WATCHLIST",
    ),
    # Etherscan — address is required for the public-tx pull; API key
    # alone is not enough.  Loader accepts any of the three fallbacks.
    "etherscan": (
        "ETHERSCAN_API_KEY",
        "ETHERSCAN_ADDRESS",
        "ETHEREUM_ADDRESS",
        "PUBLIC_ETH_ADDRESS",
    ),
    # GDELT — optional timeout override for slow upstream responses.
    "gdelt": (
        "GDELT_TIMEOUT_SECONDS",
    ),
    "gdelt_loader": (
        "GDELT_TIMEOUT_SECONDS",
    ),
}


def _config_gate_keys_for(source_key: str) -> tuple[str, ...]:
    """Return the env-var hints for a source_key, case-insensitively."""
    if not source_key:
        return ()
    return _CONFIG_GATE_HINTS.get(source_key.lower(), ())


def _merge_env_keys(
    primary: list[str] | tuple[str, ...],
    hint: tuple[str, ...],
) -> list[str]:
    """Merge two env-key sequences preserving order and dropping dupes.

    ``primary`` entries (typically ``missing_env_keys`` from the freshness
    probe) come first because they reflect what the loader actually
    asked for in this run; the config-gate hint augments with anything
    the operator might also need to set.
    """
    seen: set[str] = set()
    out: list[str] = []
    for key in list(primary) + list(hint):
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out

# Per-freshness-state base subtraction (before tier weighting).
_FRESHNESS_PENALTY: dict[str, float] = {
    "fresh": 0.0,
    "stale": 0.30,
    "overdue": 0.55,
    "never_run": 0.55,
    "failed": 0.60,
    "skipped": 0.40,  # contextual; reduced for optional-missing-config below
    # Derived sources whose required parent is stale.  Penalty is
    # equivalent to stale; the operator sees a clear "DEGRADED — parent
    # stale" line in source_health_summary.py so they fix the parent.
    "degraded_parent_stale": 0.30,
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
    missing_env_keys = list(entry.get("missing_env_keys") or [])
    source_key = str(entry.get("source_key") or "").lower()

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
            actionable_next_step=(
                f"planned_not_scored: adapter for '{source_key}' not yet "
                "implemented — no operator action required"
            ),
            entry=entry,
        )

    # ---- Terminal: optional + credential missing ---------------------
    if tier == "optional" and not credential_configured:
        # Merge explicit missing_env_keys with any config-gate hints for
        # this source so the operator sees every env var that matters,
        # not just the one the freshness probe happened to flag.
        merged_keys = _merge_env_keys(missing_env_keys, _config_gate_keys_for(source_key))
        env_hint = (
            f"set env var(s): {', '.join(merged_keys)}"
            if merged_keys
            else "configure the source credentials in .env"
        )
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
            actionable_next_step=(
                f"optional_config_missing: to activate '{source_key}', {env_hint}"
            ),
            entry=entry,
            extra_missing_env_keys=merged_keys,
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

    if freshness_state in {"stale", "overdue", "failed", "never_run", "degraded_parent_stale"}:
        if tier == "core":
            stale_severity = "loud"
        elif tier == "secondary":
            stale_severity = "moderate"
        else:
            stale_severity = "soft"
        reasons.append(f"freshness_state={freshness_state} (tier={tier})")

    # Dependency-critical override: a stale dependency_critical parent
    # (e.g. Kalshi) cascades into a derived signal becoming unusable.
    # Promote its stale_severity above its tier weighting so the operator
    # sees the cascade clearly even though the registry tier remains
    # ``optional`` for scoring continuity.
    if (
        bool(entry.get("dependency_critical"))
        and freshness_state in {"stale", "overdue", "failed", "never_run", "degraded_parent_stale"}
    ):
        stale_severity = "dependency_blocking"
        used_by = list(entry.get("used_by_derived") or [])
        if used_by:
            reasons.append(
                f"dependency_critical — parent for: {', '.join(used_by)}"
            )

    # Derived source whose parent is stale: surface which parent so the
    # operator can prioritise the fix without re-reading freshness rows.
    if freshness_state == "degraded_parent_stale":
        offending = list(entry.get("degraded_parent_stale_parents") or [])
        if offending:
            reasons.append(
                f"degraded_parent_stale parents: {', '.join(offending)}"
            )
        # Extra small penalty on the derived source itself so the
        # aggregate score reflects the dependency breakage.
        score -= 0.05

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

    actionable_next_step = _build_actionable_next_step(
        label=label,
        tier=tier,
        source_key=source_key,
        config_state=config_state,
        missing_env_keys=missing_env_keys,
        freshness_state=freshness_state,
        last_refresh_error=last_refresh_error,
        skip_reason=skip_reason,
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
        "actionable_next_step": actionable_next_step,
        "missing_env_keys": list(missing_env_keys),
        "source_key": source_key,
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
    actionable_next_step: str = "",
    extra_missing_env_keys: list[str] | None = None,
) -> dict[str, Any]:
    missing_env_keys = (
        list(extra_missing_env_keys)
        if extra_missing_env_keys is not None
        else list(entry.get("missing_env_keys") or [])
    )
    return {
        "health_score": score,
        "health_label": label,
        "health_reasons": reasons,
        "tier": str(entry.get("tier") or "optional"),
        "stale_severity": stale_severity,
        "config_state": config_state,
        "last_success_age_hours": entry.get("hours_since_last_success"),
        "operator_message": operator_message,
        "actionable_next_step": actionable_next_step,
        "missing_env_keys": missing_env_keys,
        "source_key": str(entry.get("source_key") or ""),
        "advisory_status": ADVISORY_STATUS,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_permission": False,
        "can_execute": False,
    }


def _build_actionable_next_step(
    *,
    label: str,
    tier: str,
    source_key: str,
    config_state: str,
    missing_env_keys: list[str],
    freshness_state: str,
    last_refresh_error: str,
    skip_reason: str,
) -> str:
    """Return one short, action-oriented sentence the operator can run.

    Pure string assembly — surfaces env-var names verbatim so the
    operator does not have to grep ``.env.example``.  Never claims a
    fix; never implies execution permission.  Config-gated sources
    (SEC, Etherscan public-tx, GDELT timeout) get their full env-key
    list appended even when only one key was probed.
    """
    gate_keys = _config_gate_keys_for(source_key)

    if config_state == "required_missing":
        merged = _merge_env_keys(missing_env_keys, gate_keys)
        keys = ", ".join(merged) if merged else "credentials"
        return (
            f"core_or_secondary_config_missing: set env var(s) {keys} "
            f"for '{source_key}' and re-run the refresh"
        )
    if last_refresh_error:
        first_line = last_refresh_error.split("\n", 1)[0][:120]
        return (
            f"refresh_error: investigate '{source_key}' — {first_line}"
        )
    if freshness_state in {"stale", "overdue", "never_run", "failed"}:
        if tier == "core":
            return (
                f"core_stale: run `python scripts/refresh_live_signals.py "
                f"--sources {source_key} --write`"
            )
        return (
            f"secondary_stale: schedule refresh for '{source_key}' or "
            "check upstream availability"
        )
    if freshness_state == "skipped" and skip_reason:
        if gate_keys:
            keys_hint = ", ".join(gate_keys)
            return (
                f"skipped: '{source_key}' skipped — {skip_reason[:120]} "
                f"(config gate env vars: {keys_hint})"
            )
        return f"skipped: '{source_key}' skipped — {skip_reason[:120]}"
    if label == LABEL_HEALTHY:
        return f"healthy: no action needed for '{source_key}'"
    return f"watch: monitor '{source_key}' — freshness {freshness_state}"


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
      - actionable_next_steps: deduplicated list of next-step strings,
        sorted so core actions appear before optional/planned ones.
      - issue_classification: counts of {core_stale, core_config_missing,
        secondary_stale, optional_config_missing, planned_not_scored,
        refresh_error} so callers can render a one-line health header
        without re-parsing per-source dicts.
    """
    label_dist: dict[str, int] = {}
    scored: list[float] = []
    core_scores: list[float] = []
    core_labels: list[str] = []
    actionable: list[tuple[int, str]] = []
    classification = {
        "core_stale": 0,
        "core_config_missing": 0,
        "secondary_stale": 0,
        "secondary_config_missing": 0,
        "optional_config_missing": 0,
        "planned_not_scored": 0,
        "refresh_error": 0,
    }

    # Priority ranks: lower number = higher priority (sorted first).
    _ACTION_PRIORITY = {
        "core_or_secondary_config_missing": 0,
        "refresh_error": 1,
        "core_stale": 2,
        "secondary_stale": 3,
        "skipped": 4,
        "optional_config_missing": 5,
        "planned_not_scored": 6,
        "watch": 7,
        "healthy": 8,
    }

    for entry in per_source.values():
        label = entry.get("health_label", LABEL_WATCH)
        label_dist[label] = label_dist.get(label, 0) + 1
        score = entry.get("health_score")
        tier = str(entry.get("tier") or "").lower()
        config_state = str(entry.get("config_state") or "").lower()
        if isinstance(score, (int, float)):
            scored.append(float(score))
            if tier == "core":
                core_scores.append(float(score))
                core_labels.append(label)

        # Classify this source's issue type (for the operator's at-a-glance
        # header).  A single source can hit more than one bucket — e.g.
        # core_stale AND refresh_error — and we count each independently.
        if label == LABEL_PLANNED_NOT_SCORED:
            classification["planned_not_scored"] += 1
        if label == LABEL_OPTIONAL_MISSING_CONFIG:
            classification["optional_config_missing"] += 1
        if config_state == "required_missing":
            if tier == "core":
                classification["core_config_missing"] += 1
            elif tier == "secondary":
                classification["secondary_config_missing"] += 1
        stale_sev = str(entry.get("stale_severity") or "").lower()
        if stale_sev == "loud":
            classification["core_stale"] += 1
        elif stale_sev == "moderate":
            classification["secondary_stale"] += 1
        for reason in entry.get("health_reasons") or []:
            if "recent error" in str(reason).lower():
                classification["refresh_error"] += 1
                break

        step = str(entry.get("actionable_next_step") or "").strip()
        if step:
            prefix = step.split(":", 1)[0].strip()
            actionable.append((_ACTION_PRIORITY.get(prefix, 9), step))

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

    # Deduplicate by step text while preserving priority order.
    seen: set[str] = set()
    ordered_steps: list[str] = []
    for _, step in sorted(actionable, key=lambda kv: kv[0]):
        if step in seen:
            continue
        seen.add(step)
        ordered_steps.append(step)

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
        "actionable_next_steps": ordered_steps,
        "issue_classification": classification,
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


# ---------------------------------------------------------------------------
# Operator-visible CLI
# ---------------------------------------------------------------------------
#
# Without this CLI block ``python scripts/source_health_score.py`` exits
# silently from PowerShell because the module is purely a library.  The CLI
# below loads the same per-source state the API uses, runs ``score_source``
# + ``aggregate_health`` against it, and prints an operator-readable
# scorecard.  Read-only — no DB writes, no broker code.


def _gather_per_source_entries() -> dict[str, dict[str, Any]]:
    """Build the per-source dicts ``score_source`` expects.

    Mirrors the shape produced by ``api_server._build_live_sources_status``
    but without the FastAPI dependency: we merge freshness + refresh-run
    metadata directly from persistence and the registry.
    """
    try:
        try:
            from scripts.live_source_registry import (
                compute_source_freshness,
                detect_source_credential_state,
                get_source_family,
                list_live_source_families,
            )
            from scripts.persistence import (
                get_latest_refresh_run_per_source,
                get_latest_source_run_per_source,
            )
        except ModuleNotFoundError:  # pragma: no cover
            from live_source_registry import (  # type: ignore[no-redef]
                compute_source_freshness,
                detect_source_credential_state,
                get_source_family,
                list_live_source_families,
            )
            from persistence import (  # type: ignore[no-redef]
                get_latest_refresh_run_per_source,
                get_latest_source_run_per_source,
            )
        latest_runs = get_latest_source_run_per_source()
        freshness = compute_source_freshness(latest_runs)
        try:
            refresh_runs = get_latest_refresh_run_per_source()
        except Exception:
            refresh_runs = {}
        cred = detect_source_credential_state()
    except Exception:
        return {}

    try:
        try:
            from scripts.live_source_registry import (
                DEPENDENCY_CRITICAL_SOURCES as _DEP_CRIT,
            )
        except ModuleNotFoundError:  # pragma: no cover
            from live_source_registry import (  # type: ignore[no-redef]
                DEPENDENCY_CRITICAL_SOURCES as _DEP_CRIT,
            )
    except Exception:
        _DEP_CRIT = {}

    entries: dict[str, dict[str, Any]] = {}
    for fam in list_live_source_families():
        key = fam["source_key"]
        fresh = freshness.get(key, {}) or {}
        rrow = refresh_runs.get(key, {}) or {}
        c = cred.get(key, {}) or {}
        entry = dict(fresh)
        entry.setdefault("source_key", key)
        entry["tier"] = fam.get("tier") or fresh.get("tier") or "optional"
        entry["adapter_status"] = fam.get("adapter_status")
        entry["requires_api_key"] = bool(fam.get("requires_api_key"))
        entry["credential_configured"] = bool(c.get("configured"))
        entry["missing_env_keys"] = list(c.get("missing_env_keys") or [])
        entry["last_refresh_success"] = bool(int(rrow.get("success", 0) or 0))
        entry["last_refresh_skipped"] = bool(int(rrow.get("skipped", 0) or 0))
        entry["last_refresh_error"] = str(rrow.get("error_message") or "")
        entry["last_refresh_skipped_reason"] = str(rrow.get("skipped_reason") or "")
        # Dependency-critical / derived-source metadata threaded through
        # so score_source can surface "dependency_blocking" stale_severity.
        dep_info = _DEP_CRIT.get(key, {})
        entry["dependency_critical"] = bool(dep_info.get("dependency_critical"))
        entry["used_by_derived"] = list(dep_info.get("used_by") or ())
        entry["degraded_parent_stale_parents"] = list(
            fresh.get("degraded_parent_stale_parents") or ()
        )
        entries[key] = entry
    return entries


def _format_scorecard(per_source: dict[str, dict[str, Any]], rolled: dict[str, Any]) -> str:
    import datetime as _dt

    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("Sleeping Passenger — Source Health Scorecard")
    lines.append("=" * 72)
    lines.append(f"generated_at_utc: {_dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds')}")
    lines.append(
        f"advisory_status={rolled.get('advisory_status')}  "
        f"execution_gate={rolled.get('execution_gate')}  "
        f"broker_api_called={rolled.get('broker_api_called')}  "
        f"ai_execution_count={rolled.get('ai_execution_count')}"
    )
    avg = rolled.get("average_scored_health")
    lines.append(
        f"core_health_label={rolled.get('core_health_label')}  "
        f"average_scored_health={avg if avg is not None else '-'}  "
        f"scored={rolled.get('scored_count', 0)}  "
        f"planned={rolled.get('planned_count', 0)}  "
        f"optional_missing_config={rolled.get('optional_missing_config_count', 0)}"
    )
    dist = rolled.get("health_label_distribution") or {}
    if dist:
        lines.append("label_distribution: " + ", ".join(f"{k}={v}" for k, v in dist.items()))
    cls = rolled.get("issue_classification") or {}
    if cls:
        lines.append(
            "issue_classification: "
            + ", ".join(f"{k}={v}" for k, v in cls.items())
        )

    lines.append("")
    lines.append("Per-source scores:")
    for key, entry in per_source.items():
        score = entry.get("health_score")
        label = entry.get("health_label") or "-"
        tier = entry.get("tier") or "-"
        fs = entry.get("freshness_state") or "-"
        cfg = entry.get("config_state") or "-"
        stale = entry.get("stale_severity") or "-"
        lines.append(
            f"  - {str(key):<32} "
            f"score={(round(float(score), 3) if isinstance(score, (int, float)) else 'n/a'):<6} "
            f"label={str(label):<22} "
            f"tier={str(tier):<10} "
            f"freshness={str(fs):<10} "
            f"config={str(cfg):<18} "
            f"stale_severity={str(stale)}"
        )
        action = entry.get("actionable_next_step") or entry.get("operator_message")
        if action:
            lines.append(f"      action: {action}")

    steps = rolled.get("actionable_next_steps") or []
    if steps:
        lines.append("")
        lines.append("Top operator actions:")
        for s in steps[:10]:
            lines.append(f"  - {s}")
    return "\n".join(lines)


def _cli(argv: list[str] | None = None) -> int:
    import argparse
    import json as _json
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "Print live-source reliability scores derived from source_run_log "
            "plus refresh metadata. Read-only. ADVISORY_ONLY."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON to stdout instead of the human text view.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-source rows; only print the top-level aggregate.",
    )
    args = parser.parse_args(argv)

    entries = _gather_per_source_entries()
    scored: dict[str, dict[str, Any]] = {}
    for key, raw in entries.items():
        try:
            scored[key] = score_source(raw)
        except Exception:
            continue
    rolled = aggregate_health(scored)

    if args.json:
        payload = {
            "per_source": scored,
            "aggregate": rolled,
            "advisory_status": ADVISORY_STATUS,
            "execution_gate": EXECUTION_GATE_LOCKED,
            "broker_api_called": False,
            "ai_execution_count": 0,
            "can_execute": False,
        }
        sys.stdout.write(_json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")
        return 0
    if args.quiet:
        avg = rolled.get("average_scored_health")
        sys.stdout.write(
            f"core_health_label={rolled.get('core_health_label')} "
            f"average={avg if avg is not None else '-'} "
            f"scored={rolled.get('scored_count', 0)} "
            f"planned={rolled.get('planned_count', 0)} "
            f"optional_missing_config={rolled.get('optional_missing_config_count', 0)}\n"
        )
        return 0
    sys.stdout.write(_format_scorecard(scored, rolled) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via test_source_health_cli
    raise SystemExit(_cli())
