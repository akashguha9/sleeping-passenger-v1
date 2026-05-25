"""Readiness / back-quality readiness routers.

Identity Collapse + First-Day Operator sprint, Phase 9.

Extracts the 11 GET routes + 1 locked POST route that read structured
release-envelope artifacts written under ``runtime/release/*``.  Each
endpoint is read-only, advisory-only, never calls a broker, never
authorises execution.  The locked POST does NOT actually invoke the
live refresh from the HTTP path — it returns a structured "is live
refresh permitted right now?" response.
"""
from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter, Depends
    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover — env detail
    _FASTAPI_AVAILABLE = False

    class APIRouter:  # type: ignore[no-redef]
        """Stand-in for environments without FastAPI installed (tests only)."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._routes: list[tuple[str, str, Any]] = []

        def get(self, path: str, **_kwargs: Any):
            def decorator(fn):
                self._routes.append(("GET", path, fn))
                return fn

            return decorator

        def post(self, path: str, **_kwargs: Any):
            def decorator(fn):
                self._routes.append(("POST", path, fn))
                return fn

            return decorator

    def Depends(*_args: Any, **_kwargs: Any):  # type: ignore[no-redef]
        return None


try:
    from scripts.backend_api_quality import (
        read_artifact_envelope as _read_artifact_envelope,
        live_refresh_run_locked_response as _live_refresh_run_locked_response,
    )
except ModuleNotFoundError:  # pragma: no cover
    from backend_api_quality import (  # type: ignore[no-redef]
        read_artifact_envelope as _read_artifact_envelope,
        live_refresh_run_locked_response as _live_refresh_run_locked_response,
    )


# ---------------------------------------------------------------------------
# Handler functions — defined at module scope so they can be re-exported
# back to ``scripts.api_server`` and discovered by
# ``hasattr(api_server, "get_release_gate_readiness")`` tests.  The
# router is decorated in ``build_router`` below.
# ---------------------------------------------------------------------------


def get_release_gate_readiness() -> dict:
    return _read_artifact_envelope("release_gate")


def get_daily_signal_readiness() -> dict:
    return _read_artifact_envelope("daily_signal")


def get_source_health_api() -> dict:
    return _read_artifact_envelope("source_health")


def get_live_refresh_summary() -> dict:
    return _read_artifact_envelope("live_refresh")


def get_portfolio_truth_api() -> dict:
    return _read_artifact_envelope("portfolio_truth")


def get_fresh_discovery_api() -> dict:
    return _read_artifact_envelope("fresh_discovery")


def get_why_today_summary() -> dict:
    return _read_artifact_envelope("why_today")


def get_model_disagreement_summary() -> dict:
    return _read_artifact_envelope("model_disagreement")


def get_signal_input_quality_summary() -> dict:
    return _read_artifact_envelope("signal_input_quality")


def get_compliance_readiness() -> dict:
    return _read_artifact_envelope("compliance_readiness")


def get_business_value_summary() -> dict:
    return _read_artifact_envelope("business_value")


def post_live_refresh_run() -> dict:
    """Locked operator endpoint — refuses unless every safety gate holds.

    Does NOT actually run the live refresh from the HTTP path: live calls
    are operator-run via ``scripts/operator_live_provider_refresh.py``.  The
    endpoint exists to give the cockpit a deterministic, structured
    "is live refresh permitted right now?" answer.
    """
    import os as _os

    mvp_ok = _os.environ.get("MVP_LIVE_REFRESH_OK", "").lower() in {
        "1", "true", "yes", "on",
    }
    return _live_refresh_run_locked_response(
        mvp_live_refresh_ok=mvp_ok,
        advisory_only=True,
        human_execution_required=True,
        execution_gate="LOCKED",
    )


def build_router(require_api_token):
    """Build and return the readiness APIRouter.

    Accepts the ``require_api_token`` dependency from the caller so the
    locked POST route shares the same auth gate as the rest of the API.
    Routes simply delegate to the module-level handler functions so the
    same callables can be re-exported by ``scripts.api_server``.
    """
    router = APIRouter()

    router.get("/api/readiness/release-gate")(get_release_gate_readiness)
    router.get("/api/readiness/daily-signal")(get_daily_signal_readiness)
    router.get("/api/source-health")(get_source_health_api)
    router.get("/api/live-refresh/summary")(get_live_refresh_summary)
    router.get("/api/portfolio-truth")(get_portfolio_truth_api)
    router.get("/api/fresh-discovery")(get_fresh_discovery_api)
    router.get("/api/why-today/summary")(get_why_today_summary)
    router.get("/api/model-disagreement/summary")(get_model_disagreement_summary)
    router.get("/api/signal-input-quality/summary")(get_signal_input_quality_summary)
    router.get("/api/compliance/readiness")(get_compliance_readiness)
    router.get("/api/business-value/summary")(get_business_value_summary)

    # POST route — gated by the auth dependency injected at build time.
    @router.post("/api/live-refresh/run")
    def _post_live_refresh_run(_auth: None = Depends(require_api_token)) -> dict:
        return post_live_refresh_run()

    return router
