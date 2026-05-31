"""Frontier model registry — canonical, config-driven candidate inventory.

The N'Golo Kanté FIVE-MODEL FRONTIER RESOLVER sprint.  This module is the
*registry* half: it loads the per-provider candidate models (from
``config/frontier_models.json`` with an embedded fallback) and exposes the
capability/penalty fields the resolver scores over.  It does NOT select a
model, call any provider, or touch the network — that is the resolver's job.

Five providers are represented:

    OPENAI, ANTHROPIC, XAI, GOOGLE_GEMINI, MISTRAL

Each candidate carries the documented capability dimensions (reasoning,
coding, financial-analysis, context, tool-support, structured-output) and
penalty dimensions (latency, cost, deprecation) on a 0..1 scale, plus its
``capability_tier``, ``release_rank`` (seed preference), ``availability_status``
and the env var name that must hold the provider key.

Contract — pure module:
    * No network, no broker calls, no AI execution, no order placement.
    * Importing this module performs no I/O beyond reading the JSON config
      lazily on first :func:`load_registry`.
    * Key *values* are never read here — only env *names* are carried so the
      resolver can report ``key_present`` without ever logging a secret.

The seeds are SEED PREFERENCES ONLY.  They are not a claim that these models
remain the highest-capability forever; the resolver re-selects the highest
*available* model each run and every id is overrideable without a code change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "frontier_models.json"

# Canonical provider ids.
OPENAI = "OPENAI"
ANTHROPIC = "ANTHROPIC"
XAI = "XAI"
GOOGLE_GEMINI = "GOOGLE_GEMINI"
MISTRAL = "MISTRAL"

PROVIDERS: tuple[str, ...] = (OPENAI, ANTHROPIC, XAI, GOOGLE_GEMINI, MISTRAL)

CAPABILITY_TIERS: tuple[str, ...] = (
    "FRONTIER_MAX",
    "FRONTIER",
    "BALANCED",
    "FAST",
    "FALLBACK",
    "DEPRECATED",
)

# Availability states a model may carry in the offline registry.  Only
# DEPRECATED / UNAVAILABLE block selection in OFFLINE_REGISTRY mode; UNKNOWN
# is selectable but the resolver flags that availability was not live-probed.
AVAILABILITY_AVAILABLE = "AVAILABLE"
AVAILABILITY_UNKNOWN = "UNKNOWN"
AVAILABILITY_UNAVAILABLE = "UNAVAILABLE"
AVAILABILITY_DEPRECATED = "DEPRECATED"

# A model id matching one of these (case-insensitive substring) is treated as
# a hard deprecation denylist hit regardless of its declared fields — protects
# against an override pointing at a known-sunset id.
DEPRECATED_ID_MARKERS: tuple[str, ...] = (
    "-legacy",
    "-deprecated",
    "-sunset",
)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ModelCandidate:
    """A single candidate model for one provider.

    All strength/score fields are on a 0..1 scale where 1 is best.  All
    penalty fields are on a 0..1 scale where 1 is the worst (most penalised).
    """

    provider: str
    model_id: str
    display_name: str = ""
    capability_tier: str = "FRONTIER"
    release_rank: float = 0.0
    reasoning_strength: float = 0.0
    coding_strength: float = 0.0
    financial_analysis_strength: float = 0.0
    context_score: float = 0.0
    tool_support_score: float = 0.0
    structured_output_score: float = 0.0
    latency_penalty: float = 0.0
    cost_penalty: float = 0.0
    deprecation_penalty: float = 0.0
    # Penalty inputs that are 0 in offline mode and only populated by an
    # explicit LIVE_PROBE.  Carried here so scoring has a stable shape.
    rate_limit_penalty: float = 0.0
    auth_penalty: float = 0.0
    unknown_capability_penalty: float = 0.0
    availability_status: str = AVAILABILITY_AVAILABLE
    requires_key_env: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""
    source_kind: str = "seed"

    @property
    def is_deprecated(self) -> bool:
        if self.deprecation_penalty >= 1.0:
            return True
        if str(self.availability_status).upper() == AVAILABILITY_DEPRECATED:
            return True
        if str(self.capability_tier).upper() == "DEPRECATED":
            return True
        low = self.model_id.lower()
        return any(marker in low for marker in DEPRECATED_ID_MARKERS)

    def available_offline(self) -> bool:
        """Offline availability: in registry, not deprecated, not UNAVAILABLE."""
        if self.is_deprecated:
            return False
        return str(self.availability_status).upper() != AVAILABILITY_UNAVAILABLE


@dataclass(frozen=True)
class ProviderRegistry:
    provider: str
    ledger_model_name: str
    key_env: tuple[str, ...]
    override_env: str
    candidates: tuple[ModelCandidate, ...]

    def deprecated_denylist(self) -> tuple[str, ...]:
        return tuple(c.model_id for c in self.candidates if c.is_deprecated)

    def primary_preferred(self) -> ModelCandidate | None:
        """The seed-preferred candidate (highest release_rank, non-deprecated)."""
        live = [c for c in self.candidates if not c.is_deprecated]
        if not live:
            return None
        return max(live, key=lambda c: c.release_rank)


@dataclass(frozen=True)
class FrontierRegistry:
    providers: dict[str, ProviderRegistry]
    allow_model_override: bool = True
    silent_model_fallback_allowed: bool = False
    source_path: str = ""

    def provider(self, provider: str) -> ProviderRegistry | None:
        return self.providers.get(provider)

    def provider_ids(self) -> tuple[str, ...]:
        return tuple(p for p in PROVIDERS if p in self.providers)


def _candidate_from_dict(provider: str, key_env: tuple[str, ...], raw: Mapping[str, Any]) -> ModelCandidate:
    return ModelCandidate(
        provider=provider,
        model_id=str(raw.get("model_id") or "").strip(),
        display_name=str(raw.get("display_name") or raw.get("model_id") or ""),
        capability_tier=str(raw.get("capability_tier") or "FRONTIER").upper(),
        release_rank=_f(raw.get("release_rank")),
        reasoning_strength=_f(raw.get("reasoning_strength")),
        coding_strength=_f(raw.get("coding_strength")),
        financial_analysis_strength=_f(raw.get("financial_analysis_strength")),
        context_score=_f(raw.get("context_score")),
        tool_support_score=_f(raw.get("tool_support_score")),
        structured_output_score=_f(raw.get("structured_output_score")),
        latency_penalty=_f(raw.get("latency_penalty")),
        cost_penalty=_f(raw.get("cost_penalty")),
        deprecation_penalty=_f(raw.get("deprecation_penalty")),
        rate_limit_penalty=_f(raw.get("rate_limit_penalty")),
        auth_penalty=_f(raw.get("auth_penalty")),
        unknown_capability_penalty=_f(raw.get("unknown_capability_penalty")),
        availability_status=str(raw.get("availability_status") or AVAILABILITY_AVAILABLE).upper(),
        requires_key_env=key_env,
        notes=str(raw.get("notes") or ""),
        source_kind=str(raw.get("source_kind") or "seed"),
    )


def registry_from_config(config: Mapping[str, Any], source_path: str = "") -> FrontierRegistry:
    """Build a :class:`FrontierRegistry` from a parsed config mapping."""
    providers: dict[str, ProviderRegistry] = {}
    raw_providers = config.get("providers") or {}
    for provider_id in PROVIDERS:
        raw = raw_providers.get(provider_id)
        if not raw:
            continue
        key_env = tuple(str(e) for e in (raw.get("key_env") or []))
        candidates = tuple(
            _candidate_from_dict(provider_id, key_env, c)
            for c in (raw.get("candidates") or [])
            if str(c.get("model_id") or "").strip()
        )
        providers[provider_id] = ProviderRegistry(
            provider=provider_id,
            ledger_model_name=str(raw.get("ledger_model_name") or provider_id.lower()),
            key_env=key_env,
            override_env=str(raw.get("override_env") or ""),
            candidates=candidates,
        )
    return FrontierRegistry(
        providers=providers,
        allow_model_override=bool(config.get("allow_model_override", True)),
        silent_model_fallback_allowed=bool(
            config.get("silent_model_fallback_allowed", False)
        ),
        source_path=source_path,
    )


# Minimal embedded fallback so the registry is never empty even if the JSON
# config is missing/corrupt.  The JSON file is the authoritative seed source;
# this only guarantees five providers and a primary each in degraded mode.
_EMBEDDED_FALLBACK: dict[str, Any] = {
    "allow_model_override": True,
    "silent_model_fallback_allowed": False,
    "providers": {
        "OPENAI": {"ledger_model_name": "codex", "key_env": ["OPENAI_API_KEY"], "override_env": "OPENAI_MODEL_OVERRIDE", "candidates": [
            {"model_id": "gpt-5.5", "capability_tier": "FRONTIER_MAX", "release_rank": 1.0, "reasoning_strength": 0.98, "coding_strength": 0.96, "financial_analysis_strength": 0.95, "context_score": 0.95, "tool_support_score": 0.97, "structured_output_score": 0.96, "latency_penalty": 0.15, "cost_penalty": 0.35, "availability_status": "AVAILABLE", "source_kind": "embedded_fallback"}]},
        "ANTHROPIC": {"ledger_model_name": "claude", "key_env": ["ANTHROPIC_API_KEY"], "override_env": "ANTHROPIC_MODEL_OVERRIDE", "candidates": [
            {"model_id": "claude-opus-4-8", "capability_tier": "FRONTIER_MAX", "release_rank": 1.0, "reasoning_strength": 0.98, "coding_strength": 0.97, "financial_analysis_strength": 0.96, "context_score": 0.95, "tool_support_score": 0.96, "structured_output_score": 0.96, "latency_penalty": 0.20, "cost_penalty": 0.40, "availability_status": "AVAILABLE", "source_kind": "embedded_fallback"}]},
        "XAI": {"ledger_model_name": "grok", "key_env": ["XAI_API_KEY"], "override_env": "XAI_MODEL_OVERRIDE", "candidates": [
            {"model_id": "grok-4.3", "capability_tier": "FRONTIER_MAX", "release_rank": 1.0, "reasoning_strength": 0.95, "coding_strength": 0.90, "financial_analysis_strength": 0.90, "context_score": 0.90, "tool_support_score": 0.90, "structured_output_score": 0.88, "latency_penalty": 0.15, "cost_penalty": 0.30, "availability_status": "AVAILABLE", "source_kind": "embedded_fallback"}]},
        "GOOGLE_GEMINI": {"ledger_model_name": "gemini", "key_env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"], "override_env": "GEMINI_MODEL_OVERRIDE", "candidates": [
            {"model_id": "gemini-3.1-pro-preview", "capability_tier": "FRONTIER", "release_rank": 1.0, "reasoning_strength": 0.95, "coding_strength": 0.92, "financial_analysis_strength": 0.91, "context_score": 0.97, "tool_support_score": 0.92, "structured_output_score": 0.91, "latency_penalty": 0.15, "cost_penalty": 0.28, "availability_status": "AVAILABLE", "source_kind": "embedded_fallback"}]},
        "MISTRAL": {"ledger_model_name": "mistral", "key_env": ["MISTRAL_API_KEY"], "override_env": "MISTRAL_MODEL_OVERRIDE", "candidates": [
            {"model_id": "mistral-medium-3.5", "capability_tier": "FRONTIER", "release_rank": 1.0, "reasoning_strength": 0.90, "coding_strength": 0.90, "financial_analysis_strength": 0.88, "context_score": 0.88, "tool_support_score": 0.88, "structured_output_score": 0.90, "latency_penalty": 0.10, "cost_penalty": 0.20, "availability_status": "AVAILABLE", "source_kind": "embedded_fallback"}]},
    },
}


def load_registry(config_path: Path | str | None = None) -> FrontierRegistry:
    """Load the frontier registry from JSON config, falling back to embedded seeds.

    Never raises on a missing/corrupt file — degrades honestly to the embedded
    fallback (which still provides five providers + a primary each).
    """
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    if path.exists():
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
            reg = registry_from_config(config, source_path=str(path))
            if reg.providers:
                return reg
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return registry_from_config(_EMBEDDED_FALLBACK, source_path="embedded_fallback")


__all__ = [
    "PROVIDERS",
    "OPENAI",
    "ANTHROPIC",
    "XAI",
    "GOOGLE_GEMINI",
    "MISTRAL",
    "CAPABILITY_TIERS",
    "AVAILABILITY_AVAILABLE",
    "AVAILABILITY_UNKNOWN",
    "AVAILABILITY_UNAVAILABLE",
    "AVAILABILITY_DEPRECATED",
    "ModelCandidate",
    "ProviderRegistry",
    "FrontierRegistry",
    "registry_from_config",
    "load_registry",
    "DEFAULT_CONFIG_PATH",
]
