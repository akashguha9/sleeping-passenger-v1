"""Customer-facing read-only API router.

Customer-Facing Product Transformation sprint.

Exposes the basket registry, customer-language translation layer, and
default model portfolio under ``/api/customer/*``.  Every endpoint is:

- read-only (HTTP GET only)
- advisory-only (carries the centralised safety stamps)
- pure (no DB writes, no broker calls, no network I/O)
- deterministic for a given build (the data sources are pure modules)

These endpoints back the customer-facing frontend at ``/model-portfolio``.
They are the *only* surfaces a normal retail user is expected to see;
they translate raw internal engine states (MIURA, MURCIÉLAGO, DIABLO,
…) into simple customer-facing action labels.
"""
from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter, HTTPException
    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover — env detail
    _FASTAPI_AVAILABLE = False

    class APIRouter:  # type: ignore[no-redef]
        def __init__(self, *_a: Any, **_kw: Any) -> None:
            self._routes: list[tuple[str, str, Any]] = []

        def get(self, path: str, **_kw: Any):
            def decorator(fn):
                self._routes.append(("GET", path, fn))
                return fn

            return decorator

    class HTTPException(Exception):  # type: ignore[no-redef]
        def __init__(self, status_code: int, detail: Any = None) -> None:
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail


try:
    from scripts.basket_registry import (
        explain_ticker_basket_mapping,
        get_basket_by_id,
        list_baskets,
    )
    from scripts.customer_language import (
        get_full_translation_table,
        translate_internal_state_to_customer_label,
    )
    from scripts.model_portfolio import (
        get_default_model_portfolio,
        get_model_portfolio_summary,
    )
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.customer_facing_gate import (
        CUSTOMER_FACING_DEMO_LABEL,
        CUSTOMER_FACING_DISABLED_MESSAGE,
        evaluate_gate,
    )
except ModuleNotFoundError:  # pragma: no cover — flat-layout fallback
    from basket_registry import (  # type: ignore
        explain_ticker_basket_mapping,
        get_basket_by_id,
        list_baskets,
    )
    from customer_language import (  # type: ignore
        get_full_translation_table,
        translate_internal_state_to_customer_label,
    )
    from model_portfolio import (  # type: ignore
        get_default_model_portfolio,
        get_model_portfolio_summary,
    )
    from advisory_contract import advisory_safety_stamps  # type: ignore
    from customer_facing_gate import (  # type: ignore
        CUSTOMER_FACING_DEMO_LABEL,
        CUSTOMER_FACING_DISABLED_MESSAGE,
        evaluate_gate,
    )


# Canonical customer-facing safety stamp.  Kept here (rather than
# imported from ``scripts.advisory_contract``) because the customer
# surface uses a slightly more verbose set of keys — the customer
# wording matters for the regulatory / wording test.
_CUSTOMER_DISCLAIMER = (
    "This is educational research and decision support only. It is "
    "not financial advice, not a promise of returns, and not an "
    "instruction to trade. Human decision-making is required."
)


def _customer_safety_stamp() -> dict[str, Any]:
    return {
        "advisory_only": True,
        "human_execution_required": True,
        "execution_permission": "LOCKED",
        "no_execution": True,
        "disclaimer": _CUSTOMER_DISCLAIMER,
    }


def _stamp(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach the customer safety stamp keys + the proof-loop gate state.

    Returns a new dict so callers may mutate freely.  Stacks the
    customer-friendly keys (``advisory_only``, ``human_execution_required``,
    ``execution_permission``, ``no_execution``, ``disclaimer``) on top of
    the legacy advisory-contract safety dict, so customer payloads
    satisfy both the customer-language contract enforced by
    ``tests/test_customer_api.py`` AND the repo-wide advisory-stamp
    property test enforced by ``tests/test_advisory_stamp_property.py``.

    Also attaches ``customer_facing_gate`` from
    :mod:`scripts.customer_facing_gate` so any client can see whether
    the proof loop has closed (``customer_facing_enabled``) or whether
    the response is ``DEMO_ONLY / UNCALIBRATED``.
    """
    out = dict(payload)
    out["safety"] = advisory_safety_stamps()
    out["advisory_status"] = "ADVISORY_ONLY"
    out["execution_gate"] = "LOCKED"
    out["broker_api_called"] = False
    out["ai_execution_count"] = 0
    out["human_review_required"] = True
    for key, value in _customer_safety_stamp().items():
        out[key] = value
    gate = evaluate_gate()
    out["customer_facing_gate"] = gate.to_dict()
    if gate.demo_only_label:
        out["demo_only_label"] = gate.demo_only_label
    return out


def _gate_or_disabled_response() -> dict[str, Any] | None:
    """Return a safe disabled response when the proof loop has not closed
    and the env override is also absent.  Returns ``None`` when callers
    may serve the underlying data (either gate is open, or env override
    is present and the response will be stamped DEMO_ONLY).
    """
    gate = evaluate_gate()
    if gate.customer_facing_enabled or gate.env_flag_true:
        return None
    # Default-off: refuse the underlying data politely.
    return {
        "disabled": True,
        "reason": CUSTOMER_FACING_DISABLED_MESSAGE,
        "customer_facing_gate": gate.to_dict(),
        "safety": advisory_safety_stamps(),
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_review_required": True,
        **_customer_safety_stamp(),
    }


# ---------------------------------------------------------------------------
# Handler functions — defined at module scope so they can be unit-tested
# directly without spinning up a FastAPI app.
# ---------------------------------------------------------------------------


def get_customer_baskets() -> dict:
    """Return every basket with the customer safety stamp attached.

    Default-off behind the customer-facing gate; returns a structured
    disabled response when the proof loop has not closed and no env
    override is set.
    """
    disabled = _gate_or_disabled_response()
    if disabled is not None:
        return disabled
    return _stamp({"baskets": list_baskets()})


def get_customer_basket_by_id(basket_id: str) -> dict:
    """Return one basket by id.  ``HTTPException(404)`` if missing.

    Default-off behind the customer-facing gate.
    """
    disabled = _gate_or_disabled_response()
    if disabled is not None:
        return disabled
    basket = get_basket_by_id(basket_id)
    if basket is None:
        raise HTTPException(status_code=404, detail=f"unknown basket_id: {basket_id}")
    return _stamp({"basket": basket})


def get_customer_model_portfolio() -> dict:
    """Return the full default model portfolio.

    Default-off behind the customer-facing gate.
    """
    disabled = _gate_or_disabled_response()
    if disabled is not None:
        return disabled
    portfolio = get_default_model_portfolio()
    summary = get_model_portfolio_summary()
    return _stamp(
        {
            "model_portfolio": portfolio,
            "summary": summary,
            "translation_table": get_full_translation_table(),
        }
    )


def get_customer_translate_state(state: str) -> dict:
    """Translate an internal engine state into the customer record.

    Default-off behind the customer-facing gate.
    """
    disabled = _gate_or_disabled_response()
    if disabled is not None:
        return disabled
    translation = translate_internal_state_to_customer_label(state)
    return _stamp({"translation": translation, "input_state": state})


def get_customer_ticker_basket(ticker: str) -> dict:
    """Return the customer-facing "why is this ticker here?" record.

    Default-off behind the customer-facing gate.
    """
    disabled = _gate_or_disabled_response()
    if disabled is not None:
        return disabled
    record = explain_ticker_basket_mapping(ticker)
    return _stamp(record)


def build_router() -> APIRouter:
    """Build and return the ``/api/customer`` router."""
    router = APIRouter()

    router.get("/api/customer/baskets")(get_customer_baskets)
    router.get("/api/customer/baskets/{basket_id}")(get_customer_basket_by_id)
    router.get("/api/customer/model-portfolio")(get_customer_model_portfolio)
    router.get("/api/customer/translate-state/{state}")(
        get_customer_translate_state
    )
    router.get("/api/customer/ticker/{ticker}/basket")(
        get_customer_ticker_basket
    )

    return router


__all__ = [
    "get_customer_baskets",
    "get_customer_basket_by_id",
    "get_customer_model_portfolio",
    "get_customer_translate_state",
    "get_customer_ticker_basket",
    "build_router",
]
