"""External advisory-evidence enrichment stage for daily synthesis.

EXTERNAL_ADVISORY_EVIDENCE_ENRICHMENT
=====================================

This module is the *runtime invocation point* that finally wires the
canonical external-adapter framework into the daily five-model synthesis.

Before this module, the framework existed but was orphaned::

    config/external_adapters.yaml
        -> scripts.external_adapters.registry.ExternalAdapterRegistry
        -> scripts.external_adapters.base.ExternalAdapter (Kronos, ...)
        -> scripts.core.external_evidence_router.ExternalEvidenceRouter

...yet nothing in the live daily pipeline ever called
``ExternalAdapterRegistry.collect_external_evidence`` or
``ExternalEvidenceRouter.route``.  The adapters were architecturally clean
but runtime-inert.  :func:`build_external_evidence_bundle` is the single
read-only, advisory-only enrichment stage that closes that gap.

It is *evidence-only* by hard contract:

* It NEVER converts evidence into a trade, a BUY/SELL/ENTER/EXIT command,
  or a broker call.
* It NEVER mutates execution permission above ``WATCH_ONLY``.
* It is disabled-and-safe by default (``external_advisory_evidence.enabled``
  defaults to ``false``; Kronos itself also stays ``enabled: false``).
* Any adapter / router / config failure degrades to a zero-decision-impact
  bundle rather than raising.
* External evidence can only nudge an *existing* advisory score within hard,
  asymmetric caps and can never override a DIABLO / CHAOS_VETO / NO_NEW_RISK
  safety class.

Mathematics (see docs/EXTERNAL_ADVISORY_EVIDENCE_PIPELINE.md)
------------------------------------------------------------
For each routed, accepted evidence item ``i``::

    w_i = evidence reliability weight   in [0, 1]   (confidence_proxy)
    a_i = evidence alignment score      in [-1, +1]
    r_i = router safety multiplier      in {0, 0.25, 0.50, 1.00}
    q_i = evidence quality multiplier   in [0, 1]    (evidence_quality_score)

    delta_ext_raw = sum_i ( w_i * a_i * r_i * q_i )
    delta_ext     = clip(delta_ext_raw, -1.00, +0.50)
    S_candidate   = clip(S_base + delta_ext, 0, 10)

External adapters are intentionally stronger as risk reducers (-1.00) than
hype boosters (+0.50).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps, human_only_stamp
    from scripts.core.external_evidence_router import ExternalEvidenceRouter
    from scripts.external_adapters.base import ExternalEvidence
    from scripts.external_adapters.registry import ExternalAdapterRegistry
    from scripts.runtime_common import REPO_ROOT, utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps, human_only_stamp
    from core.external_evidence_router import ExternalEvidenceRouter
    from external_adapters.base import ExternalEvidence
    from external_adapters.registry import ExternalAdapterRegistry
    from runtime_common import REPO_ROOT, utc_timestamp

try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - yaml is a hard dep elsewhere
    yaml = None  # type: ignore

DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "external_adapters.yaml"
EXTERNAL_EVIDENCE_ROUTER_VERSION = "external_evidence_router_v1"

# Hard, asymmetric score-delta caps.  External adapters help by at most +0.50
# and hurt by up to -1.00 — risk reducer first, hype booster never.
MAX_POSITIVE_SCORE_DELTA = 0.50
MAX_NEGATIVE_SCORE_DELTA = -1.00

# Bundle-level status vocabulary.
STATUS_DISABLED = "DISABLED"
STATUS_CONFIG_MISSING = "CONFIG_MISSING"
STATUS_ERROR_SAFE = "ERROR_SAFE"
STATUS_NO_ENABLED_ADAPTERS = "NO_ENABLED_ADAPTERS"
STATUS_ACCEPTED = "ACCEPTED_EVIDENCE_ONLY"
STATUS_ROUTER_REJECTED = "ROUTER_REJECTED"

# Per-item proof status vocabulary.
PROOF_ACCEPTED = "ACCEPTED_EVIDENCE_ONLY"
PROOF_FAILED_SAFE = "FAILED_SAFE_NO_DECISION_IMPACT"
PROOF_ROUTER_REJECTED = "ROUTER_REJECTED_NO_DECISION_IMPACT"
PROOF_PERMISSION_DOWNGRADED = "EXECUTION_PERMISSION_DOWNGRADED_OR_REJECTED"

# Decision-impact vocabulary.
IMPACT_NONE = "NONE"
IMPACT_ADVISORY_CONTEXT_ONLY = "ADVISORY_CONTEXT_ONLY"

# The only execution-permission strings an external adapter item may carry on
# the way *out* of this stage.  Anything else is downgraded to WATCH_ONLY.
_SAFE_OUT_PERMISSIONS = frozenset({"WATCH_ONLY", "REJECT_ONLY"})
_KNOWN_PERMISSIONS = frozenset(
    {"WATCH_ONLY", "REJECT_ONLY", "PAPER_ONLY", "NEVER_REAL_EXECUTION"}
)

# Safety classes external evidence can never upgrade past.
_SAFETY_VETO_CLASSES = frozenset({"DIABLO", "NO_NEW_RISK", "CHAOS_VETO"})
_CLASS_WATCHLIST = "WATCHLIST"


def _clip(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


def _as_payload(evidence: ExternalEvidence | dict[str, Any]) -> dict[str, Any]:
    if isinstance(evidence, ExternalEvidence):
        return evidence.to_dict()
    return dict(evidence)


def _route_safety_multiplier(route: dict[str, Any]) -> float:
    """Map a router decision to ``r_i`` in {0, 0.25, 0.50, 1.00}.

    Real execution is never allowed for an external adapter, so the ``1.00``
    bucket is structurally unreachable — advisory adapters top out at
    ``PAPER_TRADE`` (0.50), most at ``WATCH`` (0.25).
    """
    if bool(route.get("real_execution_allowed")):  # hard guard; never expected
        return 0.0
    action = str(route.get("max_allowed_action") or "").upper()
    if action == "REJECT":
        return 0.0
    if action == "WATCH":
        return 0.25
    if action == "PAPER_TRADE":
        return 0.50
    return 0.0


def _alignment_score(payload: dict[str, Any]) -> float:
    """Derive ``a_i`` in [-1, +1] from a normalized evidence payload.

    Precedence: an explicit numeric ``alignment`` field, then a Kronos status,
    then a coarse forecast direction, else neutral (0.0).
    """
    if "alignment" in payload:
        try:
            return _clip(float(payload["alignment"]), -1.0, 1.0)
        except (TypeError, ValueError):
            return 0.0
    status = str(payload.get("KRONOS_STATUS") or "").upper()
    if status:
        if status == "SUPPORTIVE":
            return 1.0
        if status in {"CONTRADICTORY", "UNSTABLE"}:
            return -1.0
        return 0.0  # NOISY / INSUFFICIENT_DATA / DISABLED / ERROR_SAFE
    direction = str(payload.get("forecast_direction") or "").upper()
    if direction == "UP":
        return 1.0
    if direction == "DOWN":
        return -1.0
    return 0.0


def _safe_bounded(value: Any) -> float:
    try:
        return _clip(float(value), 0.0, 1.0)
    except (TypeError, ValueError):
        return 0.0


def _load_framework_config(
    config_path: Path | None,
    framework_config: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, bool]:
    """Return ``(framework_config_block, config_missing)``.

    ``framework_config`` (an explicit override, used by tests) wins.  Otherwise
    the ``external_advisory_evidence`` block is read from the YAML.  A missing
    *explicitly-requested* config file yields ``config_missing=True``.
    """
    if framework_config is not None:
        return dict(framework_config), False
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return None, True
    if yaml is None:  # pragma: no cover - defensive
        return None, True
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - any parse failure degrades safe
        return None, True
    block = data.get("external_advisory_evidence") if isinstance(data, dict) else None
    return (dict(block) if isinstance(block, dict) else {}), False


def _empty_bundle(
    *,
    status: str,
    enabled: bool,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """A zero-decision-impact bundle (disabled / config-missing / error)."""
    bundle = {
        "stage": "EXTERNAL_ADVISORY_EVIDENCE_ENRICHMENT",
        "external_evidence_enabled": enabled,
        "external_evidence_status": status,
        "external_evidence_count": 0,
        "external_evidence_accepted_count": 0,
        "external_evidence_rejected_count": 0,
        "external_evidence_error_count": 0,
        "external_evidence_score_delta": 0.0,
        "external_evidence_decision_impact": IMPACT_NONE,
        "external_evidence_router_version": EXTERNAL_EVIDENCE_ROUTER_VERSION,
        "external_evidence_items": [],
        "max_positive_score_delta": MAX_POSITIVE_SCORE_DELTA,
        "max_negative_score_delta": MAX_NEGATIVE_SCORE_DELTA,
        "notes": list(notes or []),
        "generated_at_utc": utc_timestamp(),
        "safety": advisory_safety_stamps(),
        "execution": human_only_stamp(),
    }
    return bundle


def _route_one(
    evidence: ExternalEvidence | dict[str, Any],
    router: ExternalEvidenceRouter,
    pipeline_context: dict[str, Any],
) -> dict[str, Any]:
    """Route a single evidence object and build its advisory item dict."""
    payload = _as_payload(evidence)
    normalized = payload.get("normalized_payload")
    if not isinstance(normalized, dict):
        normalized = {}

    source_name = str(payload.get("source") or "unknown")
    evidence_type = str(payload.get("evidence_type") or "UNKNOWN")
    adapter_status = str(payload.get("adapter_status") or "").upper()

    try:
        route = router.route(evidence, pipeline_context=pipeline_context)
    except Exception as exc:  # noqa: BLE001 - a router crash is failed-safe
        return _failed_item(
            source_name=source_name,
            evidence_type=evidence_type,
            reason=f"router error: {type(exc).__name__}",
            normalized=normalized,
        )

    route_decision = str(route.get("max_allowed_action") or "REJECT").upper()
    r_i = _route_safety_multiplier(route)

    # Enforce WATCH_ONLY out-permission regardless of what the adapter claimed.
    raw_permission = str(payload.get("execution_permission") or "").upper()
    permission_downgraded = (
        bool(payload.get("real_execution_allowed"))
        or raw_permission not in _KNOWN_PERMISSIONS
        or raw_permission == "PAPER_ONLY"
    )

    # Item is an error-safe no-op if the adapter itself errored.
    if adapter_status == "ERROR":
        item = _failed_item(
            source_name=source_name,
            evidence_type=evidence_type,
            reason="adapter reported ERROR; failed safe",
            normalized=normalized,
        )
        item["route_decision"] = route_decision
        return item

    # Router rejected the evidence -> zero decision impact.
    if r_i <= 0.0 or route_decision == "REJECT":
        item = _base_item(
            source_name=source_name,
            evidence_type=evidence_type,
            status=STATUS_ROUTER_REJECTED,
            route_decision=route_decision,
            execution_permission="REJECT_ONLY",
            score_delta=0.0,
            reason="; ".join(route.get("notes") or [])
            or "router rejected evidence (max_allowed_action=REJECT)",
            proof_status=PROOF_ROUTER_REJECTED,
            normalized=normalized,
            accepted=False,
            rejected=True,
        )
        return item

    # Accepted, evidence-only.  Compute the per-item contribution.
    w_i = _safe_bounded(payload.get("confidence_proxy"))
    q_i = _safe_bounded(payload.get("evidence_quality_score"))
    a_i = _alignment_score(normalized)
    score_delta = round(w_i * a_i * r_i * q_i, 6)

    proof = PROOF_PERMISSION_DOWNGRADED if permission_downgraded else PROOF_ACCEPTED
    reasons = list(route.get("notes") or [])
    if permission_downgraded:
        reasons.append(
            "execution permission downgraded to WATCH_ONLY (advisory adapters "
            "are watch-only)"
        )
    item = _base_item(
        source_name=source_name,
        evidence_type=evidence_type,
        status=STATUS_ACCEPTED,
        route_decision=route_decision,
        execution_permission="WATCH_ONLY",
        score_delta=score_delta,
        reason="; ".join(reasons) or "accepted as advisory context only",
        proof_status=proof,
        normalized=normalized,
        accepted=True,
        rejected=False,
    )
    item["reliability_weight"] = round(w_i, 6)
    item["alignment_score"] = round(a_i, 6)
    item["router_safety_multiplier"] = r_i
    item["evidence_quality_multiplier"] = round(q_i, 6)
    return item


def _base_item(
    *,
    source_name: str,
    evidence_type: str,
    status: str,
    route_decision: str,
    execution_permission: str,
    score_delta: float,
    reason: str,
    proof_status: str,
    normalized: dict[str, Any],
    accepted: bool,
    rejected: bool,
) -> dict[str, Any]:
    if execution_permission not in _SAFE_OUT_PERMISSIONS:
        execution_permission = "WATCH_ONLY"
    return {
        "source_name": source_name,
        "evidence_type": evidence_type,
        "status": status,
        "route_decision": route_decision,
        "execution_permission": execution_permission,
        "watch_only": True,
        "advisory_only": True,
        "human_execution_required": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "score_delta": score_delta,
        "reason": reason,
        "proof_status": proof_status,
        "payload_summary": dict(normalized),
        "_accepted": accepted,
        "_rejected": rejected,
    }


def _failed_item(
    *,
    source_name: str,
    evidence_type: str,
    reason: str,
    normalized: dict[str, Any],
) -> dict[str, Any]:
    item = _base_item(
        source_name=source_name,
        evidence_type=evidence_type,
        status=STATUS_ERROR_SAFE,
        route_decision="REJECT",
        execution_permission="REJECT_ONLY",
        score_delta=0.0,
        reason=reason,
        proof_status=PROOF_FAILED_SAFE,
        normalized=normalized,
        accepted=False,
        rejected=False,
    )
    item["_errored"] = True
    return item


def build_external_evidence_bundle(
    *,
    config_path: Path | None = None,
    framework_config: dict[str, Any] | None = None,
    pipeline_context: dict[str, Any] | None = None,
    adapter_context: dict[str, Any] | None = None,
    registry: ExternalAdapterRegistry | None = None,
    router: ExternalEvidenceRouter | None = None,
) -> dict[str, Any]:
    """Run the advisory external-evidence enrichment stage.

    Returns a bundle dict that is always safe to attach to the daily payload.
    No exception ever escapes — any failure becomes an ``ERROR_SAFE`` bundle
    with ``decision_impact = NONE``.
    """
    pipeline_context = dict(pipeline_context or {})
    framework, config_missing = _load_framework_config(config_path, framework_config)

    if config_missing:
        return _empty_bundle(
            status=STATUS_CONFIG_MISSING,
            enabled=False,
            notes=["external adapter config file missing; no decision impact"],
        )

    enabled = bool((framework or {}).get("enabled", False))
    if not enabled:
        return _empty_bundle(
            status=STATUS_DISABLED,
            enabled=False,
            notes=["external advisory evidence disabled by default"],
        )

    try:
        active_registry = registry or ExternalAdapterRegistry(
            config_path=config_path or DEFAULT_CONFIG_PATH
        )
        active_router = router or ExternalEvidenceRouter()
        evidence_rows = active_registry.collect_external_evidence(
            context=adapter_context
        )
    except Exception as exc:  # noqa: BLE001 - whole stage fails safe
        bundle = _empty_bundle(
            status=STATUS_ERROR_SAFE,
            enabled=True,
            notes=[f"external evidence stage failed safe: {type(exc).__name__}"],
        )
        return bundle

    items: list[dict[str, Any]] = []
    for evidence in evidence_rows:
        try:
            items.append(_route_one(evidence, active_router, pipeline_context))
        except Exception as exc:  # noqa: BLE001 - one bad row never breaks the rest
            items.append(
                _failed_item(
                    source_name=str(getattr(evidence, "source", "unknown")),
                    evidence_type="UNKNOWN",
                    reason=f"item routing failed safe: {type(exc).__name__}",
                    normalized={},
                )
            )

    accepted = [i for i in items if i.get("_accepted")]
    rejected = [i for i in items if i.get("_rejected")]
    errored = [i for i in items if i.get("_errored")]

    delta_raw = sum(float(i.get("score_delta") or 0.0) for i in accepted)
    delta_ext = round(_clip(delta_raw, MAX_NEGATIVE_SCORE_DELTA, MAX_POSITIVE_SCORE_DELTA), 6)

    if not items:
        status = STATUS_NO_ENABLED_ADAPTERS
        impact = IMPACT_NONE
    elif accepted:
        status = STATUS_ACCEPTED
        impact = IMPACT_ADVISORY_CONTEXT_ONLY
    elif errored and not rejected:
        status = STATUS_ERROR_SAFE
        impact = IMPACT_NONE
    else:
        status = STATUS_ROUTER_REJECTED
        impact = IMPACT_NONE

    if status != STATUS_ACCEPTED:
        delta_ext = 0.0

    bundle = _empty_bundle(status=status, enabled=True)
    bundle["external_evidence_status"] = status
    bundle["external_evidence_count"] = len(items)
    bundle["external_evidence_accepted_count"] = len(accepted)
    bundle["external_evidence_rejected_count"] = len(rejected)
    bundle["external_evidence_error_count"] = len(errored)
    bundle["external_evidence_score_delta"] = delta_ext
    bundle["external_evidence_decision_impact"] = impact
    bundle["external_evidence_score_delta_raw"] = round(delta_raw, 6)
    bundle["external_evidence_items"] = [_public_item(i) for i in items]
    return bundle


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    """Strip the private bookkeeping keys before exposing an item."""
    return {k: v for k, v in item.items() if not k.startswith("_")}


def apply_external_evidence_to_score(
    s_base: float,
    base_class: str,
    bundle: dict[str, Any],
    *,
    safety_veto: bool = False,
    external_is_only_positive_evidence: bool = False,
) -> dict[str, Any]:
    """Apply an external-evidence bundle to a base advisory score, under gates.

    Implements PART B3:

        S_candidate = clip(S_base + delta_ext, 0, 10)
        if safety_veto: S_final = min(S_candidate, S_base), class stays vetoed
        if external is the only positive evidence: class <= WATCHLIST
        if status in {ERROR_SAFE, DISABLED, CONFIG_MISSING, ROUTER_REJECTED,
                      NO_ENABLED_ADAPTERS}: delta = 0, S_final = S_base
    """
    s_base = float(s_base)
    base_class = str(base_class or "")
    base_class_upper = base_class.upper()

    status = str(bundle.get("external_evidence_status") or STATUS_DISABLED)
    delta = float(bundle.get("external_evidence_score_delta") or 0.0)

    zero_impact_states = {
        STATUS_ERROR_SAFE,
        STATUS_DISABLED,
        STATUS_CONFIG_MISSING,
        STATUS_ROUTER_REJECTED,
        STATUS_NO_ENABLED_ADAPTERS,
    }
    if status in zero_impact_states:
        delta = 0.0

    notes: list[str] = []
    s_candidate = _clip(s_base + delta, 0.0, 10.0)

    safety_veto_active = bool(safety_veto) or base_class_upper in _SAFETY_VETO_CLASSES
    final_class = base_class

    if safety_veto_active:
        s_final = min(s_candidate, s_base)
        final_class = base_class  # original veto class is authoritative
        notes.append(
            f"Safety veto ({base_class}) preserved: external evidence cannot "
            "upgrade a veto; score capped at base."
        )
    else:
        s_final = s_candidate

    only_positive_capped = False
    if (
        not safety_veto_active
        and external_is_only_positive_evidence
        and delta > 0
    ):
        final_class = _CLASS_WATCHLIST
        only_positive_capped = True
        notes.append(
            "External evidence is the only positive evidence: capped at "
            "WATCHLIST (never an executable buy)."
        )

    # Contradiction -> human review.
    human_review_required = True
    if delta < 0:
        notes.append("External evidence contradicts/contains the base thesis; "
                     "human review required.")

    result = {
        "base_score": round(s_base, 6),
        "final_score": round(s_final, 6),
        "external_score_delta_applied": round(s_final - s_base, 6),
        "base_signal_class": base_class,
        "final_signal_class": final_class,
        "external_evidence_status": status,
        "safety_veto_preserved": bool(safety_veto_active),
        "external_only_positive_capped": only_positive_capped,
        "decision_impact": bundle.get(
            "external_evidence_decision_impact", IMPACT_NONE
        ),
        "human_review_required": human_review_required,
        "notes": notes,
    }
    result.update(advisory_safety_stamps())
    result["advisory_only"] = True
    result["human_execution_required"] = True
    result["execution_gate"] = "LOCKED"
    result["broker_api_called"] = False
    result["ai_execution_count"] = 0
    return result


def render_external_evidence_markdown(bundle: dict[str, Any]) -> str:
    """Render a safe, advisory-only summary block for the synthesis prompt."""
    lines: list[str] = []
    lines.append("EXTERNAL ADVISORY EVIDENCE (evidence-only; no decision power)")
    lines.append(
        f"  status: {bundle.get('external_evidence_status')} "
        f"(enabled={bundle.get('external_evidence_enabled')})"
    )
    lines.append(
        f"  decision_impact: {bundle.get('external_evidence_decision_impact')} "
        f"score_delta: {bundle.get('external_evidence_score_delta')} "
        f"(caps: +{MAX_POSITIVE_SCORE_DELTA}/{MAX_NEGATIVE_SCORE_DELTA})"
    )
    lines.append(
        f"  evidence: total={bundle.get('external_evidence_count')} "
        f"accepted={bundle.get('external_evidence_accepted_count')} "
        f"rejected={bundle.get('external_evidence_rejected_count')} "
        f"error_safe={bundle.get('external_evidence_error_count')}"
    )
    for item in bundle.get("external_evidence_items", []):
        lines.append(
            f"    - {item.get('source_name')} [{item.get('evidence_type')}] "
            f"{item.get('status')} route={item.get('route_decision')} "
            f"watch_only={item.get('watch_only')} delta={item.get('score_delta')}"
        )
    lines.append(
        "  Note: external evidence is watch-only advisory context. It can never "
        "create a buy/sell, call a broker, or override a chaos/safety veto. "
        "Human review required."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Build the advisory external-evidence bundle (read-only)."
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument(
        "--enable",
        action="store_true",
        help="force-enable the framework for a local advisory dry-run",
    )
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True} if args.enable else None,
    )
    if args.json:
        sys.stdout.write(json.dumps(bundle, indent=2, default=str) + "\n")
    else:
        sys.stdout.write(render_external_evidence_markdown(bundle) + "\n")
    return 0


__all__ = [
    "EXTERNAL_EVIDENCE_ROUTER_VERSION",
    "MAX_POSITIVE_SCORE_DELTA",
    "MAX_NEGATIVE_SCORE_DELTA",
    "STATUS_DISABLED",
    "STATUS_CONFIG_MISSING",
    "STATUS_ERROR_SAFE",
    "STATUS_NO_ENABLED_ADAPTERS",
    "STATUS_ACCEPTED",
    "STATUS_ROUTER_REJECTED",
    "IMPACT_NONE",
    "IMPACT_ADVISORY_CONTEXT_ONLY",
    "build_external_evidence_bundle",
    "apply_external_evidence_to_score",
    "render_external_evidence_markdown",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
