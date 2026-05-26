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


def _last_refresh_truth() -> dict:
    """Read the operator's last-run refresh artifact and convert it to
    the structured "operator refresh truth" envelope documented in the
    Calibration Corpus + Hosted Canary sprint, Phase 4.

    Pure file read.  No network.  No broker.  Missing file yields a
    truthful ``MOCK_UNAVAILABLE`` status rather than a fabricated one.
    """
    from pathlib import Path as _Path
    import json as _json

    artifact = (
        _Path(__file__).resolve().parents[3]
        / "runtime"
        / "release"
        / "operator_live_provider_refresh_summary.json"
    )
    base = {
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "refresh_status": "MOCK_UNAVAILABLE",
        "sources_attempted": 0,
        "sources_succeeded": 0,
        "sources_skipped": 0,
        "sources_failed": 0,
        "rows_written": 0,
        "started_at_utc": None,
        "finished_at_utc": None,
        "source_results": [],
        "last_run_present": False,
        "last_run_path": str(artifact),
    }
    if not artifact.exists():
        return base
    try:
        raw = _json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        base["refresh_status"] = "FAILED"
        base["error"] = f"failed_to_parse_summary: {type(exc).__name__}"
        return base

    requested = list(raw.get("providers_requested") or [])
    verified = list(raw.get("providers_live_verified") or [])
    evidence = raw.get("providers_evidence") or {}
    attempted = max(len(requested), len(evidence))

    skipped_keys: list[str] = []
    failed_keys: list[str] = []
    succeeded_keys: list[str] = list(verified)
    rows_written = 0
    source_results: list[dict] = []
    if isinstance(evidence, dict):
        for name, info in evidence.items():
            if not isinstance(info, dict):
                continue
            in_verified = name in succeeded_keys
            ok = bool(info.get("ok") or info.get("verified") or in_verified)
            skipped = bool(info.get("skipped"))
            rows = int(info.get("rows_written") or info.get("rows") or 0)
            rows_written += max(0, rows)
            err = info.get("error") or info.get("reason") or ""
            if skipped and not in_verified:
                skipped_keys.append(name)
                status = "SKIPPED"
            elif not ok:
                failed_keys.append(name)
                status = "FAILED"
            else:
                if not in_verified:
                    succeeded_keys.append(name)
                status = "SUCCESS"
            source_results.append({
                "source": str(name),
                "status": status,
                "rows_written": int(rows),
                "skipped": bool(skipped),
                "error_redacted": str(err)[:200] if err else "",
            })
    # Any requested provider not in evidence is treated as skipped.
    seen_names = {r["source"] for r in source_results}
    for name in requested:
        if name not in seen_names:
            skipped_keys.append(name)
            source_results.append({
                "source": str(name),
                "status": "SKIPPED",
                "rows_written": 0,
                "skipped": True,
                "error_redacted": "",
            })

    succeeded_n = len(set(succeeded_keys))
    skipped_n = len(set(skipped_keys) - set(succeeded_keys))
    failed_n = len(set(failed_keys) - set(succeeded_keys))
    attempted = max(attempted, succeeded_n + skipped_n + failed_n)

    if failed_n == 0 and skipped_n == 0 and succeeded_n > 0:
        refresh_status = "SUCCESS"
    elif succeeded_n == 0 and (failed_n > 0 or attempted > 0):
        refresh_status = "FAILED"
    elif succeeded_n > 0 and (failed_n > 0 or skipped_n > 0):
        refresh_status = "PARTIAL"
    elif attempted == 0:
        refresh_status = "MOCK_UNAVAILABLE"
    else:
        refresh_status = "SKIPPED"

    finished = raw.get("generated_at_utc")
    started = raw.get("started_at_utc") or finished

    return {
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "refresh_status": refresh_status,
        "sources_attempted": int(attempted),
        "sources_succeeded": int(succeeded_n),
        "sources_skipped": int(skipped_n),
        "sources_failed": int(failed_n),
        "rows_written": int(rows_written),
        "started_at_utc": started,
        "finished_at_utc": finished,
        "source_results": source_results,
        "last_run_present": True,
        "last_run_path": str(artifact),
    }


def post_live_refresh_run() -> dict:
    """Operator-facing live-refresh status endpoint.

    Returns the structured "is live refresh permitted right now AND what
    happened on the last operator run?" envelope.  Does NOT actually run
    the refresh from the HTTP path: live calls are operator-run via
    ``scripts/operator_live_provider_refresh.py``.  The HTTP route surfaces
    the artifact that script writes so the cockpit can render a truthful
    summary without firing network requests.

    Response shape merges:
    * the legacy ``live_refresh_run_locked_response`` envelope (so
      existing tests + UI banners keep working), AND
    * the Calibration Corpus + Hosted Canary sprint, Phase 4 contract
      (``refresh_status``, ``sources_*``, ``rows_written``,
      ``started_at_utc``, ``finished_at_utc``, ``source_results``).
    """
    import os as _os

    mvp_ok = _os.environ.get("MVP_LIVE_REFRESH_OK", "").lower() in {
        "1", "true", "yes", "on",
    }
    locked = _live_refresh_run_locked_response(
        mvp_live_refresh_ok=mvp_ok,
        advisory_only=True,
        human_execution_required=True,
        execution_gate="LOCKED",
    )
    truth = _last_refresh_truth()
    # Merge: truth fields take precedence; locked envelope provides the
    # backwards-compatible ok/error/warnings/blocking_reasons banner.
    merged = {**locked, **truth}
    return merged


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
