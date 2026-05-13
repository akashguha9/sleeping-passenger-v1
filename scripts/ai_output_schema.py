"""
Canonical AI output validation schema for the sleeping-passenger MVP.

Purpose
-------
This module is the single, source-agnostic validation layer for any AI
interpretation payload the system persists or displays. It runs *in addition*
to use-case-specific validators in ``scripts/grok_xai_adapter.py``; it is
deliberately permissive about field presence and strict about safety stamps.

Why a separate, smaller schema?
- The Grok/xAI adapter validates use-case-specific shapes (Polymarket,
  Blockscout, signal-ranking). Those are good but live inside the adapter.
- Other AI surfaces (signal-detail AI summary, future LLM eval harness,
  manual AI-discussion entries) need a *shared* contract.
- That contract is: "no matter what the AI returned, the persisted payload
  carries a clear validation_status, the safety stamps are locked, and no
  raw secret pattern leaks into the validation_errors list."

Safety contract (must hold for every output)
--------------------------------------------

    ∀ output ∈ AIInterpretationOutputs:
        output.can_execute             = false
        output.execution_permission    = false
        output.advisory_only           = true
        output.execution_gate          = "LOCKED"
        output.broker_api_called       = false
        output.ai_execution_count      = 0
        output.broker_order_id         = "NONE"
        output.human_execution_required = true
        output.validation_status ∈ {"valid", "partial", "invalid", "not_applicable"}

If a payload arrives with ``execution_permission = true``, ``can_execute = true``,
or any other attempted execution bit, this module **overrides** it to the safe
value and records the override in ``validation_errors``.

Public API
----------
- ``validate_ai_interpretation_payload(payload)`` -> dict
- ``normalize_confidence_score(value)`` -> (float|None, list[str])
- ``build_invalid_ai_payload(raw, errors)`` -> dict
- ``get_default_prompt_version()`` -> str
- ``apply_advisory_safety_stamps(payload)`` -> dict
- ``redact_secret_patterns(text)`` -> str
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"
BROKER_ORDER_NONE = "NONE"

VALIDATION_VALID = "valid"
VALIDATION_PARTIAL = "partial"
VALIDATION_INVALID = "invalid"
VALIDATION_NOT_APPLICABLE = "not_applicable"

ALLOWED_VALIDATION_STATUSES = {
    VALIDATION_VALID,
    VALIDATION_PARTIAL,
    VALIDATION_INVALID,
    VALIDATION_NOT_APPLICABLE,
}

DEFAULT_PROMPT_VERSION = "v1.0.0"

# Patterns that look like leaked credentials. We refuse to let these survive
# into validation_errors or persisted payload, even if the upstream AI
# accidentally echoed an env var name.  Conservative on purpose.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(api[_-]?key|token|secret|bearer)\s*[=:\s]\s*\S+"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"xai-[A-Za-z0-9]{16,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-_.]{16,}"),
)


def get_default_prompt_version() -> str:
    """Returns the canonical prompt version string used when callers do not
    specify one of their own. Bump this when prompts materially change.
    """
    return DEFAULT_PROMPT_VERSION


def redact_secret_patterns(text: str) -> str:
    """Trim and redact obvious secret-like tokens. Always returns a string."""
    if text is None:
        return ""
    out = str(text)
    if not out:
        return ""
    if len(out) > 240:
        out = out[:240] + "…"
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("<redacted-secret>", out)
    return out


def _redact_error_list(errors: Iterable[Any]) -> list[str]:
    cleaned: list[str] = []
    for item in errors or ():
        text = redact_secret_patterns(str(item))
        if text:
            cleaned.append(text)
    return cleaned


def normalize_confidence_score(value: Any) -> tuple[float | None, list[str]]:
    """Normalize a confidence value into the [0.0, 1.0] band.

    Rules
    -----
    - ``None`` -> ``(None, [])`` (caller decides if missing is partial/invalid).
    - ``bool`` -> ``(None, ["confidence_score_type_invalid"])`` (booleans
      should never be passed in as confidence).
    - Numbers in [0, 1] pass through.
    - Numbers in (1, 100] are interpreted as percentage, divided by 100, and
      a warning is recorded so the caller can mark the payload ``partial``.
    - Anything else returns ``(None, ["confidence_score_out_of_range"])``.

    The list of warnings is deliberately small and free of secret-like text.
    """
    warnings: list[str] = []
    if value is None:
        return None, warnings
    if isinstance(value, bool):
        return None, ["confidence_score_type_invalid"]
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None, ["confidence_score_not_numeric"]
    if numeric != numeric:  # NaN check
        return None, ["confidence_score_nan"]
    if 0.0 <= numeric <= 1.0:
        return numeric, warnings
    if 1.0 < numeric <= 100.0:
        warnings.append("confidence_score_rescaled_from_percent")
        return numeric / 100.0, warnings
    return None, ["confidence_score_out_of_range"]


def _coerce_string_list(value: Any) -> tuple[list[str], list[str]]:
    """Coerce ``value`` into a list[str].

    Returns ``(list, warnings)``. A bare string is converted to a single-item
    list with a warning so the caller can mark the payload ``partial``. Any
    item that is not a string is dropped and a warning is recorded.
    """
    warnings: list[str] = []
    if value is None:
        return [], warnings
    if isinstance(value, str):
        if not value.strip():
            return [], warnings
        return [value.strip()], ["contradiction_flags_string_coerced_to_list"]
    if isinstance(value, (list, tuple)):
        cleaned: list[str] = []
        had_non_string = False
        for item in value:
            if isinstance(item, str):
                stripped = item.strip()
                if stripped:
                    cleaned.append(stripped)
            else:
                had_non_string = True
        if had_non_string:
            warnings.append("contradiction_flags_non_string_dropped")
        return cleaned, warnings
    return [], ["contradiction_flags_type_invalid"]


def apply_advisory_safety_stamps(payload: dict[str, Any]) -> dict[str, Any]:
    """Force the safety stamps to their locked values.

    Any attempted execution bit is overridden and an audit note is appended to
    ``validation_errors``. The function is idempotent.
    """
    if not isinstance(payload, dict):
        return build_invalid_ai_payload(payload, ["payload_not_dict"])
    overrides: list[str] = list(payload.get("validation_errors") or [])

    def _force(key: str, expected: Any, error_tag: str) -> None:
        actual = payload.get(key)
        if actual != expected and actual is not None:
            overrides.append(error_tag)
        payload[key] = expected

    _force("advisory_status", ADVISORY_STATUS, "override_advisory_status")
    _force("advisory_only", True, "override_advisory_only")
    _force("execution_gate", EXECUTION_GATE_LOCKED, "override_execution_gate")
    _force("broker_api_called", False, "override_broker_api_called")
    _force("ai_execution_count", 0, "override_ai_execution_count")
    _force("broker_order_id", BROKER_ORDER_NONE, "override_broker_order_id")
    _force("human_execution_required", True, "override_human_execution_required")
    _force("execution_permission", False, "override_execution_permission")
    _force("can_execute", False, "override_can_execute")

    if overrides:
        # Promote validation_status: any safety override means we cannot call
        # this "valid". Treat as partial unless already invalid.
        current = payload.get("validation_status")
        if current != VALIDATION_INVALID:
            payload["validation_status"] = VALIDATION_PARTIAL
    payload["validation_errors"] = _redact_error_list(overrides)
    return payload


def build_invalid_ai_payload(raw: Any, errors: list[str]) -> dict[str, Any]:
    """Build a fully-locked invalid payload for unrecoverable cases.

    The raw value is preserved but stringified and length-capped so future
    debugging is possible without dragging arbitrary nested structures into
    persistence.
    """
    raw_repr: Any
    if isinstance(raw, (dict, list)):
        raw_repr = raw  # JSON-serialisable as-is
    elif raw is None:
        raw_repr = None
    else:
        text = str(raw)
        raw_repr = redact_secret_patterns(text)

    payload: dict[str, Any] = {
        "model_name": None,
        "provider": None,
        "prompt_version": get_default_prompt_version(),
        "interpreted_topic": None,
        "narrative_frame": None,
        "contradiction_flags": [],
        "confidence_score": None,
        "summary": None,
        "raw_response": raw_repr,
        "validation_status": VALIDATION_INVALID,
        "validation_errors": _redact_error_list(errors),
    }
    return apply_advisory_safety_stamps(payload)


@dataclass
class _ValidationState:
    """Tiny scratchpad used by :func:`validate_ai_interpretation_payload`."""

    errors: list[str] = field(default_factory=list)
    promote_to_partial: bool = False
    promote_to_invalid: bool = False


def _validate_topic_or_summary(value: Any, state: _ValidationState, key: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            state.promote_to_partial = True
            state.errors.append(f"{key}_empty_string")
            return None
        return stripped[:1024]
    state.promote_to_partial = True
    state.errors.append(f"{key}_type_invalid")
    return None


def _validate_raw_response(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    text = redact_secret_patterns(str(raw))
    return text or None


def validate_ai_interpretation_payload(payload: Any) -> dict[str, Any]:
    """Validate and normalize an AI interpretation payload.

    The output always conforms to the canonical shape:

        {
          "model_name": str | None,
          "provider": str | None,
          "prompt_version": str,
          "interpreted_topic": str | None,
          "narrative_frame": str | None,
          "contradiction_flags": list[str],
          "confidence_score": float | None,
          "summary": str | None,
          "raw_response": str | dict | list | None,
          "validation_status": "valid" | "partial" | "invalid" | "not_applicable",
          "validation_errors": list[str],
          # Safety stamps (locked):
          "advisory_status": "ADVISORY_ONLY",
          "advisory_only": True,
          "execution_gate": "LOCKED",
          "broker_api_called": False,
          "ai_execution_count": 0,
          "broker_order_id": "NONE",
          "human_execution_required": True,
          "execution_permission": False,
          "can_execute": False,
        }

    The function never raises on malformed input; the worst case is
    ``validation_status="invalid"`` with descriptive errors.
    """
    if payload is None:
        return build_invalid_ai_payload(None, ["payload_missing"])

    if not isinstance(payload, dict):
        return build_invalid_ai_payload(payload, ["payload_not_dict"])

    state = _ValidationState()

    # Detect attempted execution/safety overrides on the *input* so we can
    # record them and promote status. apply_advisory_safety_stamps below
    # cannot see the input, only our cleaned output, so we capture here.
    _UNSAFE_CHECKS: tuple[tuple[str, Any, str], ...] = (
        ("execution_permission", False, "override_execution_permission"),
        ("can_execute", False, "override_can_execute"),
        ("broker_api_called", False, "override_broker_api_called"),
        ("ai_execution_count", 0, "override_ai_execution_count"),
        ("broker_order_id", BROKER_ORDER_NONE, "override_broker_order_id"),
        ("execution_gate", EXECUTION_GATE_LOCKED, "override_execution_gate"),
        ("advisory_only", True, "override_advisory_only"),
        ("advisory_status", ADVISORY_STATUS, "override_advisory_status"),
        ("human_execution_required", True, "override_human_execution_required"),
    )
    for key, expected, tag in _UNSAFE_CHECKS:
        if key in payload and payload[key] != expected and payload[key] is not None:
            state.errors.append(tag)
            state.promote_to_partial = True

    # Required-ish strings — all optional, just typed.
    model_name = payload.get("model_name")
    if model_name is not None and not isinstance(model_name, str):
        state.errors.append("model_name_type_invalid")
        model_name = None
        state.promote_to_partial = True

    provider = payload.get("provider")
    if provider is not None and not isinstance(provider, str):
        state.errors.append("provider_type_invalid")
        provider = None
        state.promote_to_partial = True

    prompt_version_raw = payload.get("prompt_version")
    if isinstance(prompt_version_raw, str) and prompt_version_raw.strip():
        prompt_version = prompt_version_raw.strip()[:64]
    else:
        if prompt_version_raw not in (None, ""):
            state.errors.append("prompt_version_type_invalid")
            state.promote_to_partial = True
        prompt_version = get_default_prompt_version()

    interpreted_topic = _validate_topic_or_summary(
        payload.get("interpreted_topic"), state, "interpreted_topic"
    )
    narrative_frame = _validate_topic_or_summary(
        payload.get("narrative_frame"), state, "narrative_frame"
    )
    summary = _validate_topic_or_summary(payload.get("summary"), state, "summary")

    flags, flag_warnings = _coerce_string_list(payload.get("contradiction_flags"))
    if flag_warnings:
        state.errors.extend(flag_warnings)
        # Type-invalid is treated as partial, not invalid.
        state.promote_to_partial = True

    confidence_score, conf_warnings = normalize_confidence_score(
        payload.get("confidence_score")
    )
    if conf_warnings:
        state.errors.extend(conf_warnings)
        # Any range/type problem promotes to partial.
        state.promote_to_partial = True

    raw_response = _validate_raw_response(payload.get("raw_response"))

    requested_status = str(payload.get("validation_status") or "").strip()
    if requested_status and requested_status not in ALLOWED_VALIDATION_STATUSES:
        state.errors.append("validation_status_unrecognized")
        state.promote_to_partial = True
        requested_status = ""

    # Decide validation_status. A caller-supplied "invalid" is always honored.
    if requested_status == VALIDATION_INVALID:
        status = VALIDATION_INVALID
    elif state.promote_to_invalid:
        status = VALIDATION_INVALID
    elif state.promote_to_partial:
        status = VALIDATION_PARTIAL
    elif requested_status in ALLOWED_VALIDATION_STATUSES:
        status = requested_status
    else:
        # Heuristic: if there is *no* interpretive content at all, that's
        # invalid; if there is content and no errors, that's valid.
        if interpreted_topic is None and summary is None and not flags:
            status = VALIDATION_INVALID
            state.errors.append("no_interpretive_content")
        else:
            status = VALIDATION_VALID

    incoming_errors = payload.get("validation_errors") or []
    if isinstance(incoming_errors, list):
        state.errors = list(incoming_errors) + state.errors

    output: dict[str, Any] = {
        "model_name": model_name,
        "provider": provider,
        "prompt_version": prompt_version,
        "interpreted_topic": interpreted_topic,
        "narrative_frame": narrative_frame,
        "contradiction_flags": flags,
        "confidence_score": confidence_score,
        "summary": summary,
        "raw_response": raw_response,
        "validation_status": status,
        "validation_errors": _redact_error_list(state.errors),
    }
    return apply_advisory_safety_stamps(output)


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "BROKER_ORDER_NONE",
    "VALIDATION_VALID",
    "VALIDATION_PARTIAL",
    "VALIDATION_INVALID",
    "VALIDATION_NOT_APPLICABLE",
    "ALLOWED_VALIDATION_STATUSES",
    "DEFAULT_PROMPT_VERSION",
    "apply_advisory_safety_stamps",
    "build_invalid_ai_payload",
    "get_default_prompt_version",
    "normalize_confidence_score",
    "redact_secret_patterns",
    "validate_ai_interpretation_payload",
]
