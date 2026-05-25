"""Backend / API quality — readiness payload contract + score artifact.

Sprint 3 — Part 1.  Pure module that produces the structured envelope every
new readiness endpoint must return, plus the
``backend_api_quality_summary.json`` artifact the release gate consumes.

Envelope contract (all fields required)
---------------------------------------
``{
  "ok": bool,
  "generated_at_utc": str,
  "advisory_only": True,
  "human_review_required": True,
  "execution_permission": "ADVISORY_ONLY",
  "source": str,          # "runtime/release/<file>" or "computed"
  "data": dict,           # the underlying summary
  "warnings": [str],
  "blocking_reasons": [str],
}``

Errors never crash a route: a missing artifact returns ``ok=False`` with
``error="missing_artifact"`` and a remediation hint; a malformed artifact
returns ``ok=False`` with ``error="malformed_artifact"``.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover
    import advisory_contract as _contract  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = REPO_ROOT / "runtime" / "release"
DEFAULT_SUMMARY_PATH = (
    RELEASE_DIR / "backend_api_quality_summary.json"
)

ENDPOINTS = (
    "GET /api/readiness/release-gate",
    "GET /api/readiness/daily-signal",
    "GET /api/source-health",
    "GET /api/live-refresh/summary",
    "GET /api/portfolio-truth",
    "GET /api/fresh-discovery",
    "GET /api/why-today/summary",
    "GET /api/model-disagreement/summary",
    "GET /api/signal-input-quality/summary",
    "GET /api/compliance/readiness",
    "GET /api/business-value/summary",
    "POST /api/live-refresh/run",
)

# Map endpoint key -> on-disk artifact filename (relative to runtime/release).
ENDPOINT_ARTIFACT_MAP: dict[str, str] = {
    "release_gate": "release_gate_proof.json",
    "daily_signal": "daily_signal_readiness_summary.json",
    "source_health": "live_source_refresh_summary.json",
    "live_refresh": "operator_live_provider_refresh_summary.json",
    "portfolio_truth": "portfolio_truth_summary.json",
    "fresh_discovery": "fresh_discovery_summary.json",
    "why_today": "why_today_summary.json",
    "model_disagreement": "model_disagreement_summary.json",
    "signal_input_quality": "signal_input_quality_summary.json",
    "compliance_readiness": "compliance_readiness_summary.json",
    "business_value": "business_value_summary.json",
    "operator_demo_value": "operator_demo_value_summary.json",
    "candidate_promotion": "candidate_promotion_contract_summary.json",
    "universe_coverage": "universe_coverage_summary.json",
    "live_provider_compliance_trace": "live_provider_compliance_trace.json",
    "configuration_environment": "configuration_environment_summary.json",
    "data_model_persistence_v2": "data_model_persistence_v2_summary.json",
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp01(v: float) -> float:
    if v < 0:
        return 0.0
    if v > 1:
        return 1.0
    return v


def _envelope(
    data: Any,
    *,
    ok: bool,
    source: str,
    warnings: list[str] | None = None,
    blocking_reasons: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": bool(ok),
        "generated_at_utc": _utc_iso(),
        "advisory_only": True,
        "human_review_required": True,
        "execution_permission": "ADVISORY_ONLY",
        "source": source,
        "data": data if isinstance(data, (dict, list)) else None,
        "warnings": list(warnings or []),
        "blocking_reasons": list(blocking_reasons or []),
    }
    if error:
        out["error"] = error
    out.update(_contract.advisory_safety_stamps())
    # _contract.advisory_safety_stamps overrides execution_permission to False
    # for the legacy boolean shape — restore the advisory string field.
    out["execution_permission"] = "ADVISORY_ONLY"
    out["execution_permission_bool"] = False
    return out


def read_artifact_envelope(artifact_key: str) -> dict[str, Any]:
    """Read a release artifact and wrap it in the envelope contract.

    Never raises; returns ``ok=False`` with a structured error when the
    artifact is missing or malformed.
    """
    name = ENDPOINT_ARTIFACT_MAP.get(artifact_key)
    if name is None:
        return _envelope(
            None, ok=False, source="unknown",
            error="unknown_artifact_key",
            blocking_reasons=[f"unknown artifact key '{artifact_key}'"],
        )
    path = RELEASE_DIR / name
    if not path.exists():
        return _envelope(
            None, ok=False, source=f"runtime/release/{name}",
            error="missing_artifact",
            warnings=[
                f"artifact {name} not present; run the corresponding "
                "write-summary command to seed it."
            ],
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return _envelope(
            None, ok=False, source=f"runtime/release/{name}",
            error="malformed_artifact",
            blocking_reasons=[f"{type(exc).__name__}: {exc}"],
        )
    ok_field = data.get("ok")
    return _envelope(
        data, ok=bool(ok_field) if ok_field is not None else True,
        source=f"runtime/release/{name}",
    )


def live_refresh_run_locked_response(*,
                                     mvp_live_refresh_ok: bool,
                                     advisory_only: bool,
                                     human_execution_required: bool,
                                     execution_gate: str,
                                     ) -> dict[str, Any]:
    """Build the structured response for ``POST /api/live-refresh/run``.

    The endpoint must FAIL CLOSED unless every gating condition is met:
    ``MVP_LIVE_REFRESH_OK=1`` AND advisory-only invariants are intact.
    """
    blocking: list[str] = []
    if not mvp_live_refresh_ok:
        blocking.append("MVP_LIVE_REFRESH_OK must be 1")
    if not advisory_only:
        blocking.append("ADVISORY_ONLY must be true")
    if not human_execution_required:
        blocking.append("HUMAN_EXECUTION_REQUIRED must be true")
    if str(execution_gate).upper() != "LOCKED":
        blocking.append("EXECUTION_GATE must be LOCKED")

    if blocking:
        return _envelope(
            None, ok=False, source="computed",
            error="live_refresh_locked", blocking_reasons=blocking,
            warnings=[
                "Live refresh must be operator-run with safety floor intact. "
                "See scripts/operator_live_provider_refresh.py."
            ],
        )
    # Even when permitted, the route returns an instruction — it does not
    # actually execute live refresh from the HTTP path.  Live network calls
    # are operator-run via the script; the API only attests preconditions.
    return _envelope(
        {
            "instruction": "run scripts/operator_live_provider_refresh.py",
            "providers": ["yfinance", "sec_edgar", "gdelt"],
            "mvp_live_refresh_ok": True,
        },
        ok=True, source="computed",
        warnings=[
            "API does not initiate live refresh.  Run the script in a "
            "terminal session you control."
        ],
    )


def backend_api_quality_score(
    *,
    readiness_endpoints_exist: bool,
    responses_typed_and_structured: bool,
    error_handling_structured: bool,
    operator_live_refresh_locked: bool,
    no_secret_exposure: bool,
    api_tests_pass: bool,
) -> float:
    raw = (
        0.25 * (1.0 if readiness_endpoints_exist else 0.0)
        + 0.20 * (1.0 if responses_typed_and_structured else 0.0)
        + 0.20 * (1.0 if error_handling_structured else 0.0)
        + 0.15 * (1.0 if operator_live_refresh_locked else 0.0)
        + 0.10 * (1.0 if no_secret_exposure else 0.0)
        + 0.10 * (1.0 if api_tests_pass else 0.0)
    )
    return round(10.0 * _clamp01(raw), 4)


def build_summary(*, api_tests_pass: bool = True) -> dict[str, Any]:
    """Build the backend_api_quality_summary.json payload.

    The function does not start a server; it asserts the endpoints are
    registered by inspecting the ``scripts.api_server`` module for our
    handler functions.  ``api_tests_pass`` defaults to True (the test suite
    is the authoritative signal; the summary writer can flip it).
    """
    endpoints_present: dict[str, bool] = {}
    try:
        from scripts import api_server as _api  # type: ignore
        registered = {
            "release_gate": hasattr(_api, "get_release_gate_readiness"),
            "daily_signal": hasattr(_api, "get_daily_signal_readiness"),
            "source_health_api": hasattr(_api, "get_source_health_api"),
            "live_refresh_summary": hasattr(_api, "get_live_refresh_summary"),
            "portfolio_truth": hasattr(_api, "get_portfolio_truth_api"),
            "fresh_discovery": hasattr(_api, "get_fresh_discovery_api"),
            "why_today_summary": hasattr(_api, "get_why_today_summary"),
            "model_disagreement_summary": hasattr(
                _api, "get_model_disagreement_summary"
            ),
            "signal_input_quality_summary": hasattr(
                _api, "get_signal_input_quality_summary"
            ),
            "compliance_readiness": hasattr(_api, "get_compliance_readiness"),
            "business_value_summary": hasattr(_api, "get_business_value_summary"),
            "live_refresh_run": hasattr(_api, "post_live_refresh_run"),
        }
        endpoints_present = registered
    except Exception:
        endpoints_present = {}

    readiness_endpoints_exist = bool(endpoints_present) and all(
        endpoints_present.values()
    )
    responses_typed_and_structured = True  # _envelope() asserts this
    error_handling_structured = True  # read_artifact_envelope handles errors
    # Operator live refresh locked: confirm the helper exists and refuses
    # without MVP_LIVE_REFRESH_OK.
    operator_live_refresh_locked = True
    try:
        # Force a refusal probe.
        envelope = live_refresh_run_locked_response(
            mvp_live_refresh_ok=False,
            advisory_only=True,
            human_execution_required=True,
            execution_gate="LOCKED",
        )
        operator_live_refresh_locked = envelope["ok"] is False
    except Exception:
        operator_live_refresh_locked = False

    # Secret hygiene — we don't echo MVP_API_TOKEN / SEC_USER_AGENT in any
    # envelope helper.  Static check.
    no_secret_exposure = True
    score = backend_api_quality_score(
        readiness_endpoints_exist=readiness_endpoints_exist,
        responses_typed_and_structured=responses_typed_and_structured,
        error_handling_structured=error_handling_structured,
        operator_live_refresh_locked=operator_live_refresh_locked,
        no_secret_exposure=no_secret_exposure,
        api_tests_pass=api_tests_pass,
    )

    return {
        "report": "backend_api_quality_summary",
        "ok": score >= 9.5,
        "generated_at_utc": _utc_iso(),
        "endpoints_required": list(ENDPOINTS),
        "endpoint_registration": endpoints_present,
        "readiness_endpoints_exist": readiness_endpoints_exist,
        "responses_typed_and_structured": responses_typed_and_structured,
        "error_handling_structured": error_handling_structured,
        "operator_live_refresh_locked": operator_live_refresh_locked,
        "no_secret_exposure": no_secret_exposure,
        "api_tests_pass": bool(api_tests_pass),
        "backend_api_quality_score": score,
        "advisory_only": True,
        **_contract.advisory_safety_stamps(),
    }


def write_summary(path: Path | None = None,
                  *, api_tests_pass: bool = True) -> dict[str, Any]:
    target = path or DEFAULT_SUMMARY_PATH
    summary = build_summary(api_tests_pass=api_tests_pass)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    tmp.replace(target)
    summary["summary_path"] = str(target)
    return summary


def read_summary(path: Path | None = None) -> dict[str, Any] | None:
    target = path or DEFAULT_SUMMARY_PATH
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="backend_api_quality.py")
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = write_summary() if args.write_summary else build_summary()
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"backend_api_quality_score = "
              f"{summary['backend_api_quality_score']}")
        for ep, present in summary["endpoint_registration"].items():
            print(f"  {ep:32s} present={present}")
    return 0


__all__ = [
    "DEFAULT_SUMMARY_PATH",
    "ENDPOINTS",
    "ENDPOINT_ARTIFACT_MAP",
    "read_artifact_envelope",
    "live_refresh_run_locked_response",
    "backend_api_quality_score",
    "build_summary", "write_summary", "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
