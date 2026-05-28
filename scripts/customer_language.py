"""Customer-facing translation layer.

Internally, the engine uses operator/diagnostic state labels (MIURA,
MURCIÉLAGO, AVENTADOR, GALLARDO, HURACÁN, ISLERO, DIABLO).  Those names
encode rich operator semantics but are illegible to a normal retail
user.  This module is the single, deterministic translation surface
between *internal engine state* and *customer-facing action labels*
(Watch, Strong Watch, Enter/Add, Hold/Manage, Momentum Alert,
Shock Alert, Avoid/Exit Risk, Review).

Contract — pure module
----------------------
- No DB, no filesystem, no network, no broker calls, no AI execution.
- Importing this module has no side effects.
- Every function returns either a plain string or a fresh dict.
- Unknown / None / empty state degrades gracefully to ``Review``.
- No function may ever return a trading command ("buy now",
  "sell now", "execute", "guaranteed", "copy trade", etc.).

This module is part of the advisory-only product surface.  It does not
issue execution permission, does not call brokers, and cannot be used
to authorise a trade.
"""
from __future__ import annotations

import unicodedata
from typing import Any

CUSTOMER_LABEL_WATCH = "Watch"
CUSTOMER_LABEL_STRONG_WATCH = "Strong Watch"
CUSTOMER_LABEL_ENTER_ADD = "Enter/Add"
CUSTOMER_LABEL_HOLD_MANAGE = "Hold/Manage"
CUSTOMER_LABEL_MOMENTUM_ALERT = "Momentum Alert"
CUSTOMER_LABEL_SHOCK_ALERT = "Shock Alert"
CUSTOMER_LABEL_AVOID_EXIT_RISK = "Avoid/Exit Risk"
CUSTOMER_LABEL_REVIEW = "Review"

KNOWN_CUSTOMER_LABELS: tuple[str, ...] = (
    CUSTOMER_LABEL_WATCH,
    CUSTOMER_LABEL_STRONG_WATCH,
    CUSTOMER_LABEL_ENTER_ADD,
    CUSTOMER_LABEL_HOLD_MANAGE,
    CUSTOMER_LABEL_MOMENTUM_ALERT,
    CUSTOMER_LABEL_SHOCK_ALERT,
    CUSTOMER_LABEL_AVOID_EXIT_RISK,
    CUSTOMER_LABEL_REVIEW,
)

# Phrases that must never appear in any customer-facing translation
# output.  Used by tests and downstream language scans.
FORBIDDEN_CUSTOMER_PHRASES: tuple[str, ...] = (
    "buy now",
    "sell now",
    "guaranteed returns",
    "guaranteed return",
    "copy trade",
    "auto trade",
    "auto execute",
    "ai executes",
    "ai decides",
    "profit guaranteed",
    "risk-free",
    "risk free",
    "sure shot",
    "blame the ai",
    "place order",
    "execute order",
    "automatic trade",
)


def _strip_accents(text: str) -> str:
    """Return ``text`` with combining accents stripped.

    MURCIÉLAGO has an accent; tolerating accented and non-accented input
    is part of the safety story — we never want a typo to silently fall
    through to ``Review`` when the operator meant MURCIÉLAGO.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_internal_state(state: Any) -> str:
    """Normalise ``state`` to an upper-case, accent-stripped, trimmed key.

    Returns an empty string for ``None`` or empty input.  Never raises.
    """
    if state is None:
        return ""
    try:
        s = str(state).strip()
    except Exception:  # pragma: no cover — defensive
        return ""
    if not s:
        return ""
    return _strip_accents(s).upper()


# Single source of truth: internal-state-key -> customer translation
# record.  Keep this map small and deterministic; tests assert the exact
# customer labels.  Records are intentionally plain dicts so the API
# layer can JSON-serialise without an extra adapter.
_STATE_TRANSLATIONS: dict[str, dict[str, str]] = {
    "MIURA": {
        "internal_state": "MIURA",
        "customer_label": CUSTOMER_LABEL_WATCH,
        "meaning": "Early signal. Interesting, but not ready for inclusion.",
        "risk_tone": "Observation only.",
        "customer_guidance": (
            "Monitor the thesis, but do not treat it as ready for model "
            "inclusion."
        ),
    },
    "MURCIELAGO": {
        "internal_state": "MURCIÉLAGO",
        "customer_label": CUSTOMER_LABEL_STRONG_WATCH,
        "meaning": (
            "Signal has durability, but timing or confirmation may still "
            "be incomplete."
        ),
        "risk_tone": "Candidate under review.",
        "customer_guidance": (
            "Suitable for closer research, but still requires confirmation "
            "and risk review."
        ),
    },
    "AVENTADOR": {
        "internal_state": "AVENTADOR",
        "customer_label": CUSTOMER_LABEL_ENTER_ADD,
        "meaning": (
            "Thesis, timing, and risk are aligned enough for advisory "
            "model inclusion."
        ),
        "risk_tone": "Suitable only within model risk limits.",
        "customer_guidance": (
            "Can be considered for model portfolio inclusion within target "
            "weights and risk bands."
        ),
    },
    "GALLARDO": {
        "internal_state": "GALLARDO",
        "customer_label": CUSTOMER_LABEL_HOLD_MANAGE,
        "meaning": (
            "Existing model exposure should be managed with discipline, "
            "rebalance rules, stops, and partial profit logic."
        ),
        "risk_tone": "Manage exposure, do not chase.",
        "customer_guidance": (
            "Maintain or manage existing model exposure; avoid emotional "
            "over-sizing."
        ),
    },
    "HURACAN": {
        "internal_state": "HURACÁN",
        "customer_label": CUSTOMER_LABEL_MOMENTUM_ALERT,
        "meaning": (
            "Fast-moving opportunity with higher urgency and higher risk."
        ),
        "risk_tone": "Volatile, position sizing must be conservative.",
        "customer_guidance": (
            "Review quickly, but avoid oversized exposure because momentum "
            "can reverse."
        ),
    },
    "ISLERO": {
        "internal_state": "ISLERO",
        "customer_label": CUSTOMER_LABEL_SHOCK_ALERT,
        "meaning": "External shock has changed the thesis. Human review required.",
        "risk_tone": "Event-driven review.",
        "customer_guidance": (
            "Pause and reassess because new information may have changed "
            "the thesis."
        ),
    },
    "DIABLO": {
        "internal_state": "DIABLO",
        "customer_label": CUSTOMER_LABEL_AVOID_EXIT_RISK,
        "meaning": "Chaos, contradiction, or risk is too high. No new exposure.",
        "risk_tone": "Defensive posture.",
        "customer_guidance": (
            "Avoid new model exposure and review existing exposure "
            "defensively."
        ),
    },
}

_UNKNOWN_TRANSLATION: dict[str, str] = {
    "internal_state": "UNKNOWN",
    "customer_label": CUSTOMER_LABEL_REVIEW,
    "meaning": "Internal state is unrecognized or not yet mapped.",
    "risk_tone": "Research required.",
    "customer_guidance": (
        "Requires manual review before appearing in a customer-facing "
        "recommendation."
    ),
}


def translate_internal_state_to_customer_label(state: Any) -> dict:
    """Translate an internal engine state into the customer-facing record.

    Returns a fresh dict so callers may safely mutate.  Never raises;
    unknown / None / empty input maps to the ``Review`` record.
    """
    key = normalize_internal_state(state)
    record = _STATE_TRANSLATIONS.get(key)
    if record is None:
        out = dict(_UNKNOWN_TRANSLATION)
        # Preserve the original input for audit/debug, but never echo it
        # as a "live" internal state.
        if key:
            out["internal_state_raw"] = key
        return out
    return dict(record)


def get_customer_action_label(state: Any) -> str:
    """Return only the customer-facing action label (e.g. ``Enter/Add``)."""
    return translate_internal_state_to_customer_label(state)["customer_label"]


def get_customer_risk_tone(state: Any) -> str:
    """Return only the customer-facing risk tone."""
    return translate_internal_state_to_customer_label(state)["risk_tone"]


def explain_state_for_customer(state: Any) -> str:
    """Return a single plain-English sentence the UI can render directly."""
    record = translate_internal_state_to_customer_label(state)
    return f"{record['customer_label']} — {record['meaning']} {record['customer_guidance']}".strip()


def is_customer_safe_action_label(label: Any) -> bool:
    """True iff ``label`` is one of the approved customer-facing labels.

    Used by frontend / API tests to guarantee that customer payloads
    never leak raw internal state strings into the action column.
    """
    if label is None:
        return False
    try:
        return str(label).strip() in KNOWN_CUSTOMER_LABELS
    except Exception:  # pragma: no cover — defensive
        return False


def list_known_internal_states() -> list[str]:
    """Return the canonical display form of every internal state we map.

    The list preserves accents (MURCIÉLAGO, HURACÁN) for UI rendering.
    """
    return [record["internal_state"] for record in _STATE_TRANSLATIONS.values()]


def get_full_translation_table() -> list[dict]:
    """Return the full state -> customer-label table as a list of dicts.

    Convenience for the API and the frontend "internal-to-customer
    translation" educational section.
    """
    return [dict(record) for record in _STATE_TRANSLATIONS.values()]


__all__ = [
    "CUSTOMER_LABEL_WATCH",
    "CUSTOMER_LABEL_STRONG_WATCH",
    "CUSTOMER_LABEL_ENTER_ADD",
    "CUSTOMER_LABEL_HOLD_MANAGE",
    "CUSTOMER_LABEL_MOMENTUM_ALERT",
    "CUSTOMER_LABEL_SHOCK_ALERT",
    "CUSTOMER_LABEL_AVOID_EXIT_RISK",
    "CUSTOMER_LABEL_REVIEW",
    "KNOWN_CUSTOMER_LABELS",
    "FORBIDDEN_CUSTOMER_PHRASES",
    "normalize_internal_state",
    "translate_internal_state_to_customer_label",
    "get_customer_action_label",
    "get_customer_risk_tone",
    "explain_state_for_customer",
    "is_customer_safe_action_label",
    "list_known_internal_states",
    "get_full_translation_table",
]
