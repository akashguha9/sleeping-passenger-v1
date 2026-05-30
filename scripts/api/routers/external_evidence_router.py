"""External-evidence reliability router — read-only, advisory-only.

Kanté Continuation sprint, Workstream B.

Exposes ``GET /external-evidence/reliability`` so the frontend
``ExternalEvidenceReliabilityCard`` can finally be mounted.  The route is
strictly read-only: it serves the latest daily external-evidence reliability
artifact (written by ``scripts/daily_synthesis_pipeline.py``) when present,
and otherwise builds a zero-decision-impact bundle on demand from the pure
advisory-evidence layer.  External adapters are disabled by default, so the
honest default rendered by the card is the DISABLED state.

Hard safety contract
--------------------
* No file/DB mutation, no network, no broker calls.
* Secrets are stripped defensively before serialisation.
* Every response carries the advisory-only safety stamps and states
  ``real_money_sizing_impact = PROHIBITED`` / ``execution_gate = LOCKED``.
* External evidence is EVIDENCE_ONLY; it can never grant execution.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

try:
    from fastapi import APIRouter
    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    _FASTAPI_AVAILABLE = False

    class APIRouter:  # type: ignore[no-redef]
        def __init__(self, *_a: Any, **_kw: Any) -> None:
            pass

        def get(self, *_a: Any, **_kw: Any):
            def decorator(fn):
                return fn

            return decorator


# Envelope status vocabulary.
STATUS_OK = "OK"
STATUS_DISABLED = "DISABLED"
STATUS_NO_PAYLOAD = "NO_PAYLOAD"
STATUS_ERROR_SAFE = "ERROR_SAFE"

MODE_PAPER_ONLY = "PAPER_ONLY"
REAL_MONEY_SIZING_IMPACT = "PROHIBITED"

# Bundle statuses that mean "no decision impact / not active".
_DISABLED_STATUSES = {
    "DISABLED",
    "CONFIG_MISSING",
    "NO_ENABLED_ADAPTERS",
    "ERROR_SAFE",
    "ROUTER_REJECTED",
    "",
}

# Defensive secret-key denylist (substring match, case-insensitive).
_SECRET_KEY_MARKERS = (
    "api_key",
    "apikey",
    "secret",
    "authorization",
    "private_key",
    "access_key",
    "access-signature",
    "bearer",
    "password",
    "token",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _reliability_artifact_path() -> Path:
    return _repo_root() / "runtime" / "release" / "external_evidence_reliability.json"


def _safety_stamps() -> dict[str, Any]:
    """Advisory-only safety stamps shared by every response shape."""
    try:
        from scripts.advisory_contract import advisory_safety_stamps
    except ModuleNotFoundError:  # pragma: no cover - script-style env
        from advisory_contract import advisory_safety_stamps  # type: ignore
    out = dict(advisory_safety_stamps())
    out["advisory_only"] = True
    out["human_execution_required"] = True
    out["execution_gate"] = "LOCKED"
    out["broker_api_called"] = False
    out["ai_execution_count"] = 0
    out["real_money_sizing_impact"] = REAL_MONEY_SIZING_IMPACT
    out["real_money_weight_allowed"] = False
    out["external_adapter_execution_permission"] = "WATCH_ONLY"
    out["external_adapter_decision_power"] = "EVIDENCE_ONLY"
    return out


def _strip_secrets(value: Any) -> Any:
    """Recursively drop any key whose name looks secret-bearing.

    Defence in depth — the advisory-evidence bundle carries no secrets, but a
    read-only HTTP surface must never become a key-exfiltration path.
    """
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for k, v in value.items():
            kl = str(k).lower()
            if any(marker in kl for marker in _SECRET_KEY_MARKERS):
                continue
            cleaned[k] = _strip_secrets(v)
        return cleaned
    if isinstance(value, list):
        return [_strip_secrets(v) for v in value]
    return value


def _load_artifact(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _build_bundle_on_demand() -> dict[str, Any] | None:
    """Build the advisory-evidence bundle + operator readiness on demand.

    Pure / read-only: with adapters disabled by default this returns a
    zero-decision-impact DISABLED bundle.  Returns ``None`` on any failure so
    the caller can degrade to ERROR_SAFE.
    """
    try:
        try:
            from scripts.external_advisory_evidence import (
                build_external_evidence_bundle,
            )
            from scripts.external_evidence_operator_readiness import (
                build_external_evidence_operator_readiness,
            )
        except ModuleNotFoundError:  # pragma: no cover - script-style env
            from external_advisory_evidence import (  # type: ignore
                build_external_evidence_bundle,
            )
            from external_evidence_operator_readiness import (  # type: ignore
                build_external_evidence_operator_readiness,
            )
        bundle = build_external_evidence_bundle(pipeline_context={})
        readiness = build_external_evidence_operator_readiness(bundle)
        return {"bundle": bundle, "operator_readiness": readiness}
    except Exception:  # noqa: BLE001 - never crash the route
        return None


REAL_MONEY_READINESS_CEILING = "LOW BY DESIGN"


def _paper_readiness_fields(artifact: dict[str, Any] | None) -> dict[str, Any]:
    """Read-only paper-outcome readiness + corpus-quality clarity fields.

    Prefers values already embedded in the daily artifact; otherwise computes
    them on demand from the read-only loaders.  Never raises, never mutates,
    never enables sizing.  Real-money readiness is reported as LOW BY DESIGN.
    """
    readiness: dict[str, Any] | None = None
    corpus: dict[str, Any] | None = None
    blockers: list[str] = []

    if isinstance(artifact, dict):
        readiness = (
            artifact.get("paper_outcome_collection_readiness")
            or artifact.get("paper_outcome_readiness")
        )
        corpus = artifact.get("calibration_corpus_quality")
        blockers = list(artifact.get("live_verified_blockers") or [])

    if readiness is None or corpus is None:
        try:
            try:
                from scripts.paper_outcome_collection_readiness import (
                    build_from_db as _readiness_from_db,
                )
                from scripts.calibration_corpus_quality import (
                    build_from_db as _corpus_from_db,
                )
            except ModuleNotFoundError:  # pragma: no cover - script-style env
                from paper_outcome_collection_readiness import (  # type: ignore
                    build_from_db as _readiness_from_db,
                )
                from calibration_corpus_quality import (  # type: ignore
                    build_from_db as _corpus_from_db,
                )
            if readiness is None:
                readiness = _readiness_from_db()
            if corpus is None:
                corpus = _corpus_from_db()
        except Exception:  # noqa: BLE001 - degrade honestly, never crash the route
            readiness = readiness or None
            corpus = corpus or None

    closed_count = 0
    readiness_view = None
    if isinstance(readiness, dict):
        closed_count = int(readiness.get("closed_paper_outcomes_count") or 0)
        target_min = readiness.get("target_minimum", 50) or 50
        target_pref = readiness.get("target_preferred", 100) or 100
        readiness_view = {
            "readiness_label": readiness.get("readiness_label"),
            "closed_paper_outcomes_count": closed_count,
            "target_minimum": target_min,
            "target_preferred": target_pref,
            "calibration_readiness_score": readiness.get("calibration_readiness_score"),
            "next_required_action": readiness.get("next_required_action"),
            # Kanté Closed-Outcome Corpus sprint — 50/100 progress + stage.
            "closed_outcome_progress_50": readiness.get(
                "closed_outcome_progress_50",
                min(closed_count / float(target_min), 1.0),
            ),
            "closed_outcome_progress_100": readiness.get(
                "closed_outcome_progress_100",
                min(closed_count / float(target_pref), 1.0),
            ),
            "calibration_stage": readiness.get(
                "calibration_stage", readiness.get("readiness_label")
            ),
        }
    corpus_view = None
    top_missing_fields: list[str] = []
    if isinstance(corpus, dict):
        corpus_view = {
            "corpus_quality_score": corpus.get("corpus_quality_score"),
            "corpus_label": corpus.get("corpus_label"),
            "top_blocker": corpus.get("top_blocker"),
            "operator_next_action": corpus.get("operator_next_action"),
            "n_closed": corpus.get("n_closed"),
        }
        missing_summary = corpus.get("missing_fields_summary")
        if isinstance(missing_summary, dict):
            top_missing_fields = [
                k
                for k, _ in sorted(
                    missing_summary.items(), key=lambda kv: kv[1], reverse=True
                )
            ][:5]

    return {
        "paper_outcome_readiness": readiness_view,
        "calibration_corpus_quality": corpus_view,
        "live_verified_blockers": blockers,
        "real_money_readiness_ceiling": REAL_MONEY_READINESS_CEILING,
        "top_missing_fields": top_missing_fields,
        "next_operator_actions": _next_operator_actions(readiness, corpus, closed_count),
    }


def _next_operator_actions(
    readiness: dict[str, Any] | None,
    corpus: dict[str, Any] | None,
    closed_count: int,
) -> list[str]:
    """The next (up to 5) operator actions for the 50/100 outcome push.

    Read-only, advisory wording only — never an execution / trade CTA.  Derived
    from the read-only readiness + corpus reports, deduped, capped at five.
    """
    actions: list[str] = []
    if isinstance(readiness, dict) and readiness.get("next_required_action"):
        actions.append(str(readiness["next_required_action"]))
    if isinstance(corpus, dict) and corpus.get("operator_next_action"):
        actions.append(str(corpus["operator_next_action"]))
    remaining_50 = max(0, 50 - closed_count)
    remaining_100 = max(0, 100 - closed_count)
    if remaining_50 > 0:
        actions.append(
            f"Collect {remaining_50} more closed paper outcomes to reach the "
            "50-outcome minimum."
        )
    if remaining_100 > 0:
        actions.append(
            f"Collect {remaining_100} more to reach the 100-outcome preferred target."
        )
    actions.append(
        "Link closed outcomes to external-evidence snapshots via "
        "calibration_corpus_builder (dry-run first)."
    )
    actions.append("Real-money readiness remains low by design — keep sizing prohibited.")
    deduped: list[str] = []
    for a in actions:
        if a and a not in deduped:
            deduped.append(a)
    return deduped[:5]


def build_external_evidence_reliability_payload(
    *,
    artifact_path: Path | None = None,
    on_demand: Callable[[], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Pure builder for ``GET /external-evidence/reliability``.

    Resolution order:
      1. the persisted daily reliability artifact (if present + valid)
      2. an on-demand build from the pure advisory-evidence layer
      3. an honest NO_PAYLOAD / ERROR_SAFE envelope

    Never raises, never mutates, never leaks secrets.
    """
    safety = _safety_stamps()
    path = artifact_path or _reliability_artifact_path()
    on_demand = on_demand or _build_bundle_on_demand

    artifact = _load_artifact(path)
    source = "artifact" if artifact is not None else None
    bundle: dict[str, Any] | None = None
    readiness: dict[str, Any] | None = None

    if artifact is not None:
        bundle = artifact.get("external_evidence") or artifact.get("bundle") or artifact
        readiness = artifact.get("external_evidence_operator_readiness") or artifact.get(
            "operator_readiness"
        )

    paper_fields = _paper_readiness_fields(artifact)

    if bundle is None:
        built = on_demand()
        if built is None:
            # Could not build at all → honest error-safe / no-payload envelope.
            env = _envelope(
                status=STATUS_NO_PAYLOAD,
                bundle=None,
                readiness=None,
                safety=safety,
                source="none",
            )
            env.update(paper_fields)
            return env
        bundle = built.get("bundle")
        readiness = built.get("operator_readiness")
        source = "on_demand"

    env = _envelope(
        status=None,
        bundle=bundle,
        readiness=readiness,
        safety=safety,
        source=source or "unknown",
    )
    env.update(paper_fields)
    return env


def _envelope(
    *,
    status: str | None,
    bundle: dict[str, Any] | None,
    readiness: dict[str, Any] | None,
    safety: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    bundle = _strip_secrets(dict(bundle)) if isinstance(bundle, dict) else None
    readiness = _strip_secrets(dict(readiness)) if isinstance(readiness, dict) else None

    if bundle is None:
        resolved_status = status or STATUS_ERROR_SAFE
        ev_status = resolved_status
        enabled = False
        decision_impact = "NONE"
        calibration: dict[str, Any] = {}
        items: list[Any] = []
        accepted = 0
        raw_delta = 0.0
        paper_delta = 0.0
        final_delta = 0.0
    else:
        ev_status = str(bundle.get("external_evidence_status") or STATUS_DISABLED).upper()
        enabled = bool(bundle.get("external_evidence_enabled"))
        decision_impact = str(
            bundle.get("external_evidence_decision_impact") or "NONE"
        )
        calibration = bundle.get("external_evidence_calibration") or {}
        items = bundle.get("external_evidence_items") or []
        accepted = int(bundle.get("external_evidence_accepted_count") or 0)
        raw_delta = bundle.get("external_evidence_score_delta_raw_uncalibrated")
        paper_delta = bundle.get("external_evidence_score_delta_paper_calibrated")
        final_delta = bundle.get("external_evidence_score_delta_final")
        if status is not None:
            resolved_status = status
        elif not enabled or ev_status in _DISABLED_STATUSES:
            resolved_status = STATUS_DISABLED
        else:
            resolved_status = STATUS_OK

    payload: dict[str, Any] = {
        "status": resolved_status,
        "mode": MODE_PAPER_ONLY,
        "decision_impact": decision_impact,
        "source": source,
        "artifact_present": source == "artifact",
        # --- bundle fields the card consumes (ExternalEvidenceReliabilityView)
        "external_evidence_status": ev_status,
        "external_evidence_enabled": enabled,
        "external_evidence_decision_impact": decision_impact,
        "external_evidence_accepted_count": accepted,
        "external_evidence_score_delta_raw_uncalibrated": raw_delta,
        "external_evidence_score_delta_paper_calibrated": paper_delta,
        "external_evidence_score_delta_final": final_delta,
        "external_evidence_calibration": calibration,
        "external_evidence_items": items,
        # --- envelope extras
        "items": items,
        "external_evidence_operator_readiness": readiness,
    }
    payload.update(safety)
    return payload


# ---------------------------------------------------------------------------
# Route handler — resolves the builder via scripts.api_server at request time
# so test patches on that symbol apply.
# ---------------------------------------------------------------------------


def get_external_evidence_reliability() -> dict[str, Any]:
    import scripts.api_server as _srv

    fn = getattr(
        _srv,
        "_build_external_evidence_reliability_payload",
        build_external_evidence_reliability_payload,
    )
    return fn()


def build_router():
    router = APIRouter()
    router.get("/external-evidence/reliability")(get_external_evidence_reliability)
    return router


__all__ = [
    "STATUS_OK",
    "STATUS_DISABLED",
    "STATUS_NO_PAYLOAD",
    "STATUS_ERROR_SAFE",
    "build_external_evidence_reliability_payload",
    "get_external_evidence_reliability",
    "build_router",
]
