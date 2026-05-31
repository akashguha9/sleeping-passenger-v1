"""Frontier model resolver — highest-available-model-per-provider selector.

The N'Golo Kanté FIVE-MODEL FRONTIER RESOLVER sprint.  This module is the
*resolver* half: it scores the registry candidates, selects the highest
available model for each of the five providers, falls back HONESTLY (never
silently) when the preferred model is deprecated/unavailable, honours per
-provider env overrides, computes a model-quality-weighted quorum, and renders
the synthesis-evidence block.

Kanté discipline:
    * The selector does not score goals — it wins the midfield battle against
      model drift: stale ids, silent fallback, weak models, fake quorum.
    * Advisory only.  Model outputs are EVIDENCE, never execution authority.

Hard safety contract (mirrors :mod:`scripts.advisory_contract`):
    * No broker calls, no order-placement endpoints, no autonomous execution,
      no account/portfolio execution surface.  Allowed network (LIVE_PROBE only, opt-in,
      injected): a model metadata/list or a tiny harmless text probe.
    * Key *values* are never logged — only ``key_present`` booleans are emitted.
    * OFFLINE_REGISTRY (default) and DRY_RUN make ZERO network calls.
    * LIVE_PROBE is disabled unless an explicit ``prober`` callable is injected
      AND probe mode is requested; with no prober it reports PROBE_DISABLED.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

try:
    from scripts import frontier_model_registry as _reg
    from scripts import advisory_contract as _contract
    from scripts import provider_secret_redaction as _redact
except ModuleNotFoundError:  # pragma: no cover - direct-script import fallback
    import frontier_model_registry as _reg  # type: ignore[no-redef]
    import advisory_contract as _contract  # type: ignore[no-redef]
    import provider_secret_redaction as _redact  # type: ignore[no-redef]

ModelCandidate = _reg.ModelCandidate

# Resolver availability modes.
MODE_OFFLINE_REGISTRY = "OFFLINE_REGISTRY"
MODE_DRY_RUN = "DRY_RUN"
MODE_LIVE_PROBE = "LIVE_PROBE"
RESOLVER_MODES: tuple[str, ...] = (
    MODE_OFFLINE_REGISTRY,
    MODE_DRY_RUN,
    MODE_LIVE_PROBE,
)

# Explicit, never-silent fallback reasons.
FALLBACK_MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
FALLBACK_MODEL_DEPRECATED = "MODEL_DEPRECATED"
FALLBACK_API_KEY_MISSING = "API_KEY_MISSING"
FALLBACK_AUTH_FAILED = "AUTH_FAILED"
FALLBACK_RATE_LIMITED = "RATE_LIMITED"
FALLBACK_PROVIDER_ERROR = "PROVIDER_ERROR"
FALLBACK_MODEL_NOT_FOUND = "MODEL_NOT_FOUND"

# Provider probe statuses (LIVE_PROBE only).
PROBE_MODEL_AVAILABLE = "MODEL_AVAILABLE"
PROBE_MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
PROBE_API_KEY_MISSING = "API_KEY_MISSING"
PROBE_AUTH_FAILED = "AUTH_FAILED"
PROBE_RATE_LIMITED = "RATE_LIMITED"
PROBE_PROVIDER_ERROR = "PROVIDER_ERROR"
PROBE_DISABLED = "PROBE_DISABLED"
PROBE_NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"

# Probe status -> fallback reason mapping for blocked models in LIVE_PROBE.
_PROBE_TO_FALLBACK = {
    PROBE_MODEL_NOT_FOUND: FALLBACK_MODEL_NOT_FOUND,
    PROBE_API_KEY_MISSING: FALLBACK_API_KEY_MISSING,
    PROBE_AUTH_FAILED: FALLBACK_AUTH_FAILED,
    PROBE_RATE_LIMITED: FALLBACK_RATE_LIMITED,
    PROBE_PROVIDER_ERROR: FALLBACK_PROVIDER_ERROR,
    PROBE_NETWORK_UNAVAILABLE: FALLBACK_PROVIDER_ERROR,
}

QUORUM_REQUIRED_COUNT = 3
QUORUM_NORMALIZED_MIN = 0.60
_EPS = 1e-9

# Tokens an override id may never contain — keeps an override from pointing at
# something that smells like an execution/broker surface rather than a model.
_OVERRIDE_FORBIDDEN_SUBSTR: tuple[str, ...] = (
    "order", "broker", "execute", "trade", "account", "/", " ",
)


def _clamp01(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Scoring mathematics                                                          #
# --------------------------------------------------------------------------- #
def capability_score(m: ModelCandidate) -> float:
    """0.25 reasoning + 0.20 coding + 0.20 financial + 0.10 context
    + 0.10 tool + 0.10 structured + 0.05 release_rank."""
    return _clamp01(
        0.25 * m.reasoning_strength
        + 0.20 * m.coding_strength
        + 0.20 * m.financial_analysis_strength
        + 0.10 * m.context_score
        + 0.10 * m.tool_support_score
        + 0.10 * m.structured_output_score
        + 0.05 * m.release_rank
    )


def penalty_score(m: ModelCandidate, *, availability_penalty: float = 0.0) -> float:
    """0.25 deprecation + 0.20 availability + 0.15 rate_limit + 0.15 auth
    + 0.10 latency + 0.10 cost + 0.05 unknown_capability."""
    return _clamp01(
        0.25 * m.deprecation_penalty
        + 0.20 * _clamp01(availability_penalty)
        + 0.15 * m.rate_limit_penalty
        + 0.15 * m.auth_penalty
        + 0.10 * m.latency_penalty
        + 0.10 * m.cost_penalty
        + 0.05 * m.unknown_capability_penalty
    )


def frontier_model_score(m: ModelCandidate, *, availability_penalty: float = 0.0) -> float:
    """clamp(capability_score - penalty_score, 0, 1)."""
    return _clamp01(
        capability_score(m) - penalty_score(m, availability_penalty=availability_penalty)
    )


# --------------------------------------------------------------------------- #
# Availability                                                                 #
# --------------------------------------------------------------------------- #
def provider_key_present(
    provider_reg: "_reg.ProviderRegistry", env: Mapping[str, str] | None = None
) -> bool:
    """True iff any of the provider's key env vars is present (non-empty).

    Never reads or returns the value — uses the secret-safe ``key_present``.
    """
    return any(_redact.key_present(name, env) for name in provider_reg.key_env)


def _availability_penalty_for(
    m: ModelCandidate,
    *,
    key_present: bool,
    probe_status: str | None,
) -> float:
    """availability_penalty(m): 1 if provider key missing or model unavailable."""
    if not key_present:
        return 1.0
    if not m.available_offline():
        return 1.0
    if probe_status is not None and probe_status != PROBE_MODEL_AVAILABLE:
        return 1.0
    return 0.0


def _validate_override(
    override_id: str,
    provider_reg: "_reg.ProviderRegistry",
    *,
    allow_override: bool,
) -> tuple[bool, str]:
    """Return (is_valid, reason).  An override is rejected (OVERRIDE_INVALID)
    when overrides are disabled, the id is empty/malformed, or the id is on the
    provider's deprecated denylist."""
    if not allow_override:
        return False, "OVERRIDE_DISABLED"
    cleaned = (override_id or "").strip()
    if not cleaned:
        return False, "OVERRIDE_EMPTY"
    low = cleaned.lower()
    if any(tok in low for tok in _OVERRIDE_FORBIDDEN_SUBSTR):
        return False, "OVERRIDE_UNSAFE_TOKEN"
    denylist = {d.lower() for d in provider_reg.deprecated_denylist()}
    if low in denylist or any(marker in low for marker in _reg.DEPRECATED_ID_MARKERS):
        return False, "OVERRIDE_DEPRECATED"
    return True, "OVERRIDE_VALID"


def _resolve_override(
    cleaned_id: str, provider_reg: "_reg.ProviderRegistry"
) -> ModelCandidate:
    """Return the registry candidate matching the override id, or a synthetic
    UNKNOWN-capability candidate (honest: we cannot vouch for an unlisted id)."""
    for c in provider_reg.candidates:
        if c.model_id.lower() == cleaned_id.lower():
            return c
    # Unlisted override id: selectable but flagged with an unknown-capability
    # penalty so it never outranks a vetted frontier model by accident.
    return ModelCandidate(
        provider=provider_reg.provider,
        model_id=cleaned_id,
        display_name=cleaned_id,
        capability_tier="FRONTIER",
        release_rank=0.0,
        reasoning_strength=0.80,
        coding_strength=0.80,
        financial_analysis_strength=0.80,
        context_score=0.80,
        tool_support_score=0.80,
        structured_output_score=0.80,
        unknown_capability_penalty=1.0,
        availability_status=_reg.AVAILABILITY_UNKNOWN,
        requires_key_env=provider_reg.key_env,
        notes="operator override; capability not vetted by registry",
        source_kind="override",
    )


def _block_reason_for(m: ModelCandidate, probe_status: str | None) -> str:
    """Why a candidate is blocked from selection (for explicit fallback reason)."""
    if probe_status is not None and probe_status in _PROBE_TO_FALLBACK:
        return _PROBE_TO_FALLBACK[probe_status]
    if m.is_deprecated:
        return FALLBACK_MODEL_DEPRECATED
    if str(m.availability_status).upper() == _reg.AVAILABILITY_UNAVAILABLE:
        return FALLBACK_MODEL_UNAVAILABLE
    return FALLBACK_MODEL_UNAVAILABLE


def resolve_provider(
    provider_reg: "_reg.ProviderRegistry",
    *,
    env: Mapping[str, str] | None = None,
    mode: str = MODE_OFFLINE_REGISTRY,
    allow_override: bool = True,
    prober: Callable[[ModelCandidate, Mapping[str, str] | None], str] | None = None,
) -> dict[str, Any]:
    """Select the highest-scoring AVAILABLE model for one provider.

    Returns a fully-explained resolution dict (selected model, score, tier,
    key presence, availability, fallback used + explicit reason, override
    state, deprecated-blocked, participates-in-quorum).
    """
    key_present = provider_key_present(provider_reg, env)
    live_probe = mode == MODE_LIVE_PROBE

    # Per-candidate probe status (LIVE_PROBE only; otherwise None = offline).
    probe_statuses: dict[str, str | None] = {}
    for c in provider_reg.candidates:
        if not live_probe:
            probe_statuses[c.model_id] = None
        elif prober is None:
            probe_statuses[c.model_id] = PROBE_DISABLED
        elif not key_present:
            probe_statuses[c.model_id] = PROBE_API_KEY_MISSING
        else:
            try:
                probe_statuses[c.model_id] = str(prober(c, env)) or PROBE_PROVIDER_ERROR
            except Exception:  # noqa: BLE001 - a probe failure must degrade honestly
                probe_statuses[c.model_id] = PROBE_PROVIDER_ERROR

    def _blocked(c: ModelCandidate) -> bool:
        if not c.available_offline():
            return True
        if live_probe:
            status = probe_statuses.get(c.model_id)
            # PROBE_DISABLED does not block (offline-equivalent); only a
            # definitive negative probe blocks.
            if status not in (None, PROBE_DISABLED, PROBE_MODEL_AVAILABLE):
                return True
        return False

    def _score(c: ModelCandidate) -> float:
        ap = _availability_penalty_for(
            c,
            key_present=key_present,
            probe_status=(probe_statuses.get(c.model_id) if live_probe else None),
        )
        return frontier_model_score(c, availability_penalty=ap)

    candidates_ranked = sorted(
        provider_reg.candidates, key=lambda c: (_score(c), c.release_rank), reverse=True
    )
    available = [c for c in candidates_ranked if not _blocked(c)]
    deprecated_blocked = sorted(
        c.model_id for c in provider_reg.candidates if c.is_deprecated
    )

    base: dict[str, Any] = {
        "provider": provider_reg.provider,
        "ledger_model_name": provider_reg.ledger_model_name,
        "provider_key_present": key_present,
        "key_env": list(provider_reg.key_env),
        "override_env": provider_reg.override_env,
        "deprecated_model_blocked": deprecated_blocked,
        "candidate_models": [c.model_id for c in provider_reg.candidates],
        "resolver_mode": mode,
    }

    # --- Override path --------------------------------------------------- #
    override_raw = ""
    if provider_reg.override_env and env is not None:
        override_raw = str(env.get(provider_reg.override_env) or "").strip()
    elif provider_reg.override_env and env is None:
        import os
        override_raw = str(os.environ.get(provider_reg.override_env) or "").strip()

    override_used = False
    override_status = "NONE"
    if override_raw:
        ok, reason = _validate_override(
            override_raw, provider_reg, allow_override=allow_override
        )
        if ok:
            selected = _resolve_override(override_raw, provider_reg)
            override_used = True
            override_status = reason  # OVERRIDE_VALID
            return _finalise(
                base, selected, available_first=selected,
                fallback_used=False, fallback_reason=None,
                override_used=True, override_status=override_status,
                key_present=key_present,
                availability_status=_availability_label(
                    selected, mode, key_present, probe_statuses
                ),
                score=_score(selected),
            )
        override_status = reason  # OVERRIDE_INVALID -> fall through to registry

    # --- Registry selection --------------------------------------------- #
    if not available:
        out = dict(base)
        out.update(
            {
                "selected_model": None,
                "selected_model_score": 0.0,
                "capability_tier": None,
                "availability_status": (
                    FALLBACK_API_KEY_MISSING if not key_present else "NO_AVAILABLE_MODEL"
                ),
                "provider_status": "NO_AVAILABLE_MODEL",
                "fallback_used": False,
                "fallback_reason": None,
                "override_used": False,
                "override_status": override_status,
                "participates_in_quorum": False,
                "model_quality_weight": 0.0,
            }
        )
        return out

    selected = available[0]
    primary = provider_reg.primary_preferred()

    # Fallback iff a higher-preference (higher release_rank) candidate than the
    # selected one was blocked.  Reason is the block reason of the highest such
    # blocked candidate — NEVER silent.
    higher_pref_blocked = [
        c for c in provider_reg.candidates
        if c.release_rank > selected.release_rank and _blocked(c)
    ]
    fallback_used = bool(higher_pref_blocked)
    fallback_reason = None
    if fallback_used:
        top_blocked = max(higher_pref_blocked, key=lambda c: c.release_rank)
        fallback_reason = _block_reason_for(
            top_blocked, probe_statuses.get(top_blocked.model_id) if live_probe else None
        )

    return _finalise(
        base, selected, available_first=selected,
        fallback_used=fallback_used, fallback_reason=fallback_reason,
        override_used=False, override_status=override_status,
        key_present=key_present,
        availability_status=_availability_label(selected, mode, key_present, probe_statuses),
        score=_score(selected),
        primary=primary,
    )


def _availability_label(
    m: ModelCandidate,
    mode: str,
    key_present: bool,
    probe_statuses: Mapping[str, str | None],
) -> str:
    if mode == MODE_LIVE_PROBE:
        status = probe_statuses.get(m.model_id)
        if status and status not in (PROBE_DISABLED,):
            return status
        if status == PROBE_DISABLED:
            return "LIVE_PROBE_DISABLED_OFFLINE_REGISTRY"
    if not key_present:
        return FALLBACK_API_KEY_MISSING
    return "OFFLINE_REGISTRY_AVAILABLE"


def _finalise(
    base: dict[str, Any],
    selected: ModelCandidate,
    *,
    available_first: ModelCandidate,
    fallback_used: bool,
    fallback_reason: str | None,
    override_used: bool,
    override_status: str,
    key_present: bool,
    availability_status: str,
    score: float,
    primary: ModelCandidate | None = None,
) -> dict[str, Any]:
    out = dict(base)
    # participates in quorum: provider key present AND a model is selected AND
    # (offline) availability is not a hard negative.  Output presence /
    # advisory-safety are folded in later by the quorum function from real runs.
    participates = bool(key_present and selected is not None)
    out.update(
        {
            "selected_model": selected.model_id,
            "selected_model_display": selected.display_name,
            "selected_model_score": round(score, 6),
            "capability_tier": selected.capability_tier,
            "release_rank": selected.release_rank,
            "source_kind": selected.source_kind,
            "availability_status": availability_status,
            "provider_status": "OK" if participates else "DEGRADED",
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "override_used": override_used,
            "override_status": override_status,
            "deprecated_model_blocked_count": len(base.get("deprecated_model_blocked", [])),
            "participates_in_quorum": participates,
            "model_quality_weight": round(score, 6),
            "primary_preferred_model": primary.model_id if primary else selected.model_id,
            "notes": selected.notes,
        }
    )
    return out


def resolve_all(
    registry: "_reg.FrontierRegistry | None" = None,
    *,
    env: Mapping[str, str] | None = None,
    mode: str = MODE_OFFLINE_REGISTRY,
    prober: Callable[[ModelCandidate, Mapping[str, str] | None], str] | None = None,
    config_path: Any = None,
) -> dict[str, Any]:
    """Resolve the best available model for ALL five providers."""
    if mode not in RESOLVER_MODES:
        mode = MODE_OFFLINE_REGISTRY
    reg = registry or _reg.load_registry(config_path)
    allow_override = reg.allow_model_override
    resolutions: dict[str, dict[str, Any]] = {}
    for provider_id in _reg.PROVIDERS:
        provider_reg = reg.provider(provider_id)
        if provider_reg is None:
            resolutions[provider_id] = {
                "provider": provider_id,
                "selected_model": None,
                "selected_model_score": 0.0,
                "provider_status": "PROVIDER_NOT_REGISTERED",
                "participates_in_quorum": False,
                "model_quality_weight": 0.0,
                "fallback_used": False,
                "fallback_reason": None,
            }
            continue
        resolutions[provider_id] = resolve_provider(
            provider_reg, env=env, mode=mode, allow_override=allow_override, prober=prober
        )
    return {
        "report": "frontier_model_resolution",
        "model_resolver_mode": mode,
        "model_availability_live_probed": mode == MODE_LIVE_PROBE and prober is not None,
        "model_resolver_generated_at_utc": _utc_iso(),
        "registry_source": reg.source_path,
        "silent_model_fallback_allowed": reg.silent_model_fallback_allowed,
        "allow_model_override": allow_override,
        "providers": resolutions,
        "advisory_only": True,
        "model_output_authority": "ADVISORY_ONLY",
        **_contract.advisory_safety_stamps(),
    }


# --------------------------------------------------------------------------- #
# Model-quality-weighted quorum                                               #
# --------------------------------------------------------------------------- #
def _vote_for(provider_id: str, resolution: dict[str, Any], votes: Mapping[str, Any] | None) -> dict[str, Any]:
    """Resolve a provider's vote inputs.

    ``votes`` may map provider -> bool (output present & safe) OR provider ->
    dict with keys model_output_present / output_advisory_safe /
    no_invented_executable_candidate.  When omitted, the offline default is the
    provider's ``participates_in_quorum`` (key present + model selected).
    """
    selected = resolution.get("selected_model")
    if votes is None:
        present = bool(resolution.get("participates_in_quorum"))
        safe = present
        no_invent = present
    else:
        raw = votes.get(provider_id)
        if isinstance(raw, dict):
            present = bool(raw.get("model_output_present"))
            safe = bool(raw.get("output_advisory_safe", present))
            no_invent = bool(raw.get("no_invented_executable_candidate", present))
        else:
            present = bool(raw)
            safe = present
            no_invent = present
    valid = bool(selected is not None and present and safe and no_invent)
    return {
        "selected": selected,
        "model_output_present": present,
        "output_advisory_safe": safe,
        "no_invented_executable_candidate": no_invent,
        "valid_provider_vote": valid,
        "model_quality_weight": float(resolution.get("model_quality_weight") or 0.0),
    }


def weighted_quorum(
    resolution_result: dict[str, Any],
    votes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the model-quality-weighted quorum over the resolution result."""
    resolutions = resolution_result.get("providers", {})
    per_provider: dict[str, dict[str, Any]] = {}
    weighted = 0.0
    max_possible = 0.0
    valid_count = 0
    for provider_id, resolution in resolutions.items():
        v = _vote_for(provider_id, resolution, votes)
        per_provider[provider_id] = v
        max_possible += v["model_quality_weight"]
        if v["valid_provider_vote"]:
            weighted += v["model_quality_weight"]
            valid_count += 1
    normalized = weighted / max(_EPS, max_possible)
    quorum_satisfied = (
        valid_count >= QUORUM_REQUIRED_COUNT and normalized >= QUORUM_NORMALIZED_MIN
    )
    return {
        "valid_provider_count": valid_count,
        "quorum_required_count": QUORUM_REQUIRED_COUNT,
        "weighted_quorum_score": round(weighted, 6),
        "max_possible_quorum_score": round(max_possible, 6),
        "normalized_quorum": round(normalized, 6),
        "normalized_quorum_min": QUORUM_NORMALIZED_MIN,
        "quorum_satisfied": quorum_satisfied,
        "classification_downgraded_for_quorum": not quorum_satisfied,
        "allowed_classifications_when_degraded": [
            "WATCHLIST", "DATA_INSUFFICIENT", "NO_NEW_RISK", "MODEL_PRIOR_ONLY",
        ],
        "per_provider_vote": per_provider,
    }


# --------------------------------------------------------------------------- #
# Synthesis evidence injection                                                #
# --------------------------------------------------------------------------- #
def render_model_selection_markdown(
    resolution_result: dict[str, Any],
    quorum: dict[str, Any] | None = None,
) -> str:
    """Render the '# Model Selection / Frontier Resolver' synthesis block.

    Advisory-only.  Surfaces selected model + score + tier + key presence +
    availability + fallback (with explicit reason) + override state per
    provider, then the weighted-quorum summary and the hard synthesis
    instruction (no new BUY_CANDIDATE when quorum is not satisfied).
    """
    if quorum is None:
        quorum = weighted_quorum(resolution_result)
    mode = resolution_result.get("model_resolver_mode", MODE_OFFLINE_REGISTRY)
    live_probed = bool(resolution_result.get("model_availability_live_probed"))
    lines: list[str] = []
    lines.append("# Model Selection / Frontier Resolver (ADVISORY)")
    lines.append(
        "Highest available model selected per provider. Outputs are advisory "
        "evidence ONLY — never execution authority. Human final decision required."
    )
    lines.append(f"model_resolver_mode: {mode}")
    if not live_probed:
        lines.append(
            "model availability not live-probed (offline registry / probe disabled)."
        )
    lines.append(
        f"model_resolver_generated_at_utc: "
        f"{resolution_result.get('model_resolver_generated_at_utc', '?')}"
    )
    lines.append("")
    for provider_id in _reg.PROVIDERS:
        r = resolution_result.get("providers", {}).get(provider_id, {})
        lines.append(f"## {provider_id}")
        lines.append(f"- selected_model: {r.get('selected_model')}")
        lines.append(f"- selected_model_score: {r.get('selected_model_score')}")
        lines.append(f"- capability_tier: {r.get('capability_tier')}")
        lines.append(f"- provider_key_present: {r.get('provider_key_present', False)}")
        lines.append(f"- availability_status: {r.get('availability_status')}")
        lines.append(f"- fallback_used: {r.get('fallback_used', False)}")
        lines.append(f"- fallback_reason: {r.get('fallback_reason')}")
        lines.append(f"- override_used: {r.get('override_used', False)}")
        lines.append(
            f"- deprecated_model_blocked: {r.get('deprecated_model_blocked') or 'NONE'}"
        )
        lines.append(
            f"- participates_in_quorum: {r.get('participates_in_quorum', False)}"
        )
        if r.get("selected_model") is None:
            lines.append(
                "  * provider MISSING from quorum (no available model / key absent)."
            )
        elif r.get("fallback_used"):
            lines.append(
                f"  * FALLBACK in effect — preferred model unavailable: "
                f"{r.get('fallback_reason')} (not a silent downgrade)."
            )
        lines.append("")
    lines.append("## Quorum Summary (model-quality-weighted)")
    lines.append(f"- valid_provider_count: {quorum['valid_provider_count']}")
    lines.append(f"- quorum_required_count: {quorum['quorum_required_count']}")
    lines.append(f"- weighted_quorum_score: {quorum['weighted_quorum_score']}")
    lines.append(f"- max_possible_quorum_score: {quorum['max_possible_quorum_score']}")
    lines.append(
        f"- normalized_quorum: {quorum['normalized_quorum']} "
        f"(min {quorum['normalized_quorum_min']})"
    )
    lines.append(f"- quorum_satisfied: {quorum['quorum_satisfied']}")
    lines.append("")
    if not quorum["quorum_satisfied"]:
        lines.append(
            "HARD SYNTHESIS INSTRUCTION: quorum NOT satisfied — do NOT classify any "
            "new BUY_CANDIDATE. Use only WATCHLIST / DATA_INSUFFICIENT / NO_NEW_RISK "
            "/ MODEL_PRIOR_ONLY. At least 3 valid provider votes AND normalized_quorum "
            ">= 0.60 are required; a single frontier model cannot carry the panel."
        )
    else:
        lines.append(
            "Quorum satisfied: >=3 valid independent provider votes and weighted "
            "evidence threshold met. Still advisory-only; human execution required."
        )
    return "\n".join(lines)


def build_model_selection_evidence(
    *,
    env: Mapping[str, str] | None = None,
    mode: str = MODE_OFFLINE_REGISTRY,
    votes: Mapping[str, Any] | None = None,
    prober: Callable[[ModelCandidate, Mapping[str, str] | None], str] | None = None,
    config_path: Any = None,
) -> dict[str, Any]:
    """One-call helper: resolve all providers + compute quorum + render block."""
    resolution = resolve_all(
        env=env, mode=mode, prober=prober, config_path=config_path
    )
    quorum = weighted_quorum(resolution, votes)
    return {
        "resolution": resolution,
        "quorum": quorum,
        "markdown": render_model_selection_markdown(resolution, quorum),
    }


def _emit_lines(resolution_result: dict[str, Any]) -> list[str]:
    """Emit ``<PROVIDER>_RESOLVED_MODEL=<id>`` lines for shell consumption.

    Only the selected model id (never a secret) is emitted.  A provider with no
    available model emits an empty value so the caller keeps its own default.
    """
    out: list[str] = []
    providers = resolution_result.get("providers", {})
    for provider_id in _reg.PROVIDERS:
        r = providers.get(provider_id, {})
        out.append(f"{provider_id}_RESOLVED_MODEL={r.get('selected_model') or ''}")
        out.append(f"{provider_id}_FALLBACK_USED={str(bool(r.get('fallback_used'))).lower()}")
        out.append(
            f"{provider_id}_FALLBACK_REASON={r.get('fallback_reason') or ''}"
        )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="frontier_model_resolver.py")
    parser.add_argument(
        "--mode", default=MODE_OFFLINE_REGISTRY, choices=list(RESOLVER_MODES)
    )
    parser.add_argument("--json", action="store_true", help="print full JSON evidence")
    parser.add_argument(
        "--emit-shell-env",
        action="store_true",
        help="print <PROVIDER>_RESOLVED_MODEL=<id> lines (no secrets)",
    )
    parser.add_argument(
        "--markdown", action="store_true", help="print the synthesis selection block"
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    # LIVE_PROBE from the CLI never gets a prober here — it stays offline-safe
    # (PROBE_DISABLED). A real prober must be wired in code, not via the CLI.
    evidence = build_model_selection_evidence(mode=args.mode)
    if args.emit_shell_env:
        for line in _emit_lines(evidence["resolution"]):
            print(line)
    elif args.json:
        print(_json.dumps(evidence, indent=2, default=str))
    else:
        print(evidence["markdown"])
        if args.markdown:
            pass
    return 0


__all__ = [
    "MODE_OFFLINE_REGISTRY",
    "MODE_DRY_RUN",
    "MODE_LIVE_PROBE",
    "RESOLVER_MODES",
    "QUORUM_REQUIRED_COUNT",
    "QUORUM_NORMALIZED_MIN",
    "capability_score",
    "penalty_score",
    "frontier_model_score",
    "provider_key_present",
    "resolve_provider",
    "resolve_all",
    "weighted_quorum",
    "render_model_selection_markdown",
    "build_model_selection_evidence",
    "FALLBACK_MODEL_UNAVAILABLE",
    "FALLBACK_MODEL_DEPRECATED",
    "FALLBACK_API_KEY_MISSING",
    "PROBE_DISABLED",
    "PROBE_MODEL_AVAILABLE",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
