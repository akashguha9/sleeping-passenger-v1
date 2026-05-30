"""Operator-facing external-evidence reliability readiness block.

KANTE_EXTERNAL_EVIDENCE_OPERATOR_READINESS
==========================================

The defensive-midfield summary the operator reads at a glance: how much the
external-evidence engine actually moved, how reliable it is, where the biggest
fake-confidence risk sits, and the unbreakable safety posture.  This is the
"recover the ball and start the transition" block — it turns the raw bundle +
calibration buckets + veto status into one compact, honest readout.

It composes existing layers (it does not re-derive their maths):

* :mod:`scripts.external_advisory_evidence`     — the evidence bundle + deltas
* :mod:`scripts.fake_confidence_audit`          — fake-confidence risk summary
* :mod:`scripts.veto_integrity_proof`           — veto-override-impossible proof

Honesty contract
----------------
When data is unavailable the block says so — no fake live status, no invented
source reliability.  Every output states ``PAPER ONLY``, ``Real-money sizing:
PROHIBITED``, ``Human review: REQUIRED`` and ``Veto override: IMPOSSIBLE``.

Hard safety contract
--------------------
Pure module.  No DB, no network, no broker calls.  No execution-instruction
wording is ever emitted (a positive context never carries place/submit/execute
order language).
"""
from __future__ import annotations

from typing import Any

try:
    from scripts import advisory_contract as _contract
    from scripts import fake_confidence_audit as _fca
    from scripts.external_advisory_evidence import (
        MAX_NEGATIVE_SCORE_DELTA,
        MAX_POSITIVE_SCORE_DELTA,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]
    import fake_confidence_audit as _fca  # type: ignore[no-redef]
    from external_advisory_evidence import (  # type: ignore[no-redef]
        MAX_NEGATIVE_SCORE_DELTA,
        MAX_POSITIVE_SCORE_DELTA,
    )

MODE_PAPER_ONLY = "PAPER_ONLY"
MODE_DISABLED = "DISABLED"
REAL_MONEY_SIZING_IMPACT = "PROHIBITED"
HUMAN_REVIEW = "REQUIRED"
VETO_OVERRIDE = "IMPOSSIBLE"

_DISABLED_STATUSES = {
    "DISABLED",
    "CONFIG_MISSING",
    "NO_ENABLED_ADAPTERS",
    "ERROR_SAFE",
    "ROUTER_REJECTED",
    "",
}

_PROOF = "EXTERNAL_EVIDENCE_OPERATOR_READINESS_PAPER_ONLY"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return default if out != out else out


def build_external_evidence_operator_readiness(
    bundle: dict[str, Any] | None,
    *,
    calibration_buckets: list[dict[str, Any]] | None = None,
    veto_proof: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the compact operator-readiness block from an evidence bundle.

    ``bundle`` is the output of
    :func:`scripts.external_advisory_evidence.build_external_evidence_bundle`.
    ``calibration_buckets`` (optional) drives the fake-confidence summary.
    ``veto_proof`` (optional) is a
    :func:`scripts.veto_integrity_proof.build_veto_integrity_proof` result.
    Never raises.
    """
    bundle = dict(bundle or {})
    status = str(bundle.get("external_evidence_status") or MODE_DISABLED).upper()
    enabled = bool(bundle.get("external_evidence_enabled"))
    cal = bundle.get("external_evidence_calibration") or {}
    cal_applied = bool(cal.get("enabled") and cal.get("applied_to_score_delta"))

    fc_summary = _fca.build_fake_confidence_summary(calibration_buckets)

    available = enabled and status not in _DISABLED_STATUSES
    mode = MODE_PAPER_ONLY if available else MODE_DISABLED

    raw_delta = _num(bundle.get("external_evidence_score_delta_raw_uncalibrated"))
    paper_delta = _num(bundle.get("external_evidence_score_delta_paper_calibrated"))

    # Biggest reliability risk: stale / cold-start dominated evidence.
    cold = int(cal.get("cold_start_items_count") or 0)
    mature = int(cal.get("mature_items_count") or 0)
    accepted = int(bundle.get("external_evidence_accepted_count") or 0)
    if not available:
        reliability_risk = "Evidence disabled/unavailable — no decision impact."
    elif accepted == 0:
        reliability_risk = "No accepted evidence items this run."
    elif cold >= max(mature, 1):
        reliability_risk = (
            "Cold-start dominated: most items lack mature closed-outcome history."
        )
    else:
        reliability_risk = "Sample maturity uneven; weights still capped paper-only."

    fc_risk_label = fc_summary.get("overall_fake_confidence_label")
    worst = fc_summary.get("worst_source_bucket")
    best = fc_summary.get("best_source_bucket")

    # Missing next evidence: always honest about the 50-100 paper-outcome gap.
    missing_next = _missing_next_evidence(fc_summary, mature)

    block: dict[str, Any] = {
        "report": "external_evidence_operator_readiness",
        "data_available": available,
        "mode": mode,
        "runtime_status": status,
        "evidence_items": accepted,
        "calibrated_items": int(cal.get("calibrated_items_count") or 0),
        "cold_start_items": cold,
        "mature_paper_only_items": mature,
        "raw_score_delta": round(raw_delta, 6),
        "calibrated_paper_delta": round(paper_delta, 6),
        "max_boost": MAX_POSITIVE_SCORE_DELTA,
        "max_penalty": MAX_NEGATIVE_SCORE_DELTA,
        "real_money_sizing": REAL_MONEY_SIZING_IMPACT,
        "human_review": HUMAN_REVIEW,
        "veto_override": VETO_OVERRIDE,
        "biggest_reliability_risk": reliability_risk,
        "biggest_false_confidence_risk": fc_risk_label,
        "fake_confidence_summary": fc_summary,
        "best_source_bucket_by_sample": best,
        "worst_source_bucket_by_harm": worst,
        "missing_next_evidence_needed": missing_next,
        "calibration_applied": cal_applied,
        "veto_integrity_proof": veto_proof,
    }
    block.update(_contract.advisory_safety_stamps())
    block.update(_contract.human_only_stamp())
    block["advisory_only"] = True
    block["human_execution_required"] = True
    block["execution_gate"] = "LOCKED"
    block["broker_api_called"] = False
    block["ai_execution_count"] = 0
    block["real_money_sizing_impact"] = REAL_MONEY_SIZING_IMPACT
    block["real_money_weight_allowed"] = False
    block["proof_status"] = _PROOF
    return block


def _missing_next_evidence(fc_summary: dict[str, Any], mature: int) -> str:
    if not fc_summary.get("data_available"):
        return (
            "No closed paper outcomes yet. Need 50-100 paper outcomes before any "
            "bucket can leave cold-start."
        )
    if mature == 0:
        return "No mature (n>=50) buckets yet. More closed paper outcomes needed."
    if fc_summary.get("high_risk_count"):
        return (
            "Refute high fake-confidence buckets with more closed outcomes before "
            "trusting their weight."
        )
    return "Continue accumulating closed paper outcomes to raise sample maturity."


def render_external_evidence_operator_readiness_block(
    block: dict[str, Any],
) -> str:
    """Render the operator-readiness block as a safe, advisory-only text block.

    Always states PAPER ONLY, real-money PROHIBITED, human review REQUIRED, and
    veto override IMPOSSIBLE.  Emits no execution-instruction wording.
    """
    b = dict(block or {})
    lines: list[str] = ["EXTERNAL EVIDENCE RELIABILITY - PAPER ONLY"]
    if not b.get("data_available"):
        lines.append(f"- Runtime status: {b.get('runtime_status', MODE_DISABLED)}")
        lines.append("- Evidence unavailable / disabled by default - no decision impact.")
        lines.append(f"- Real-money sizing: {REAL_MONEY_SIZING_IMPACT}")
        lines.append(f"- Human review: {HUMAN_REVIEW}")
        lines.append(f"- Veto override: {VETO_OVERRIDE}")
        lines.append(
            "- Missing next evidence: "
            f"{b.get('missing_next_evidence_needed', 'paper outcomes needed')}"
        )
        return "\n".join(lines)

    lines.append(f"- Runtime status: {b.get('runtime_status')}")
    lines.append(f"- Evidence items: {b.get('evidence_items', 0)}")
    lines.append(f"- Calibrated items: {b.get('calibrated_items', 0)}")
    lines.append(f"- Cold-start items: {b.get('cold_start_items', 0)}")
    lines.append(f"- Mature paper-only items: {b.get('mature_paper_only_items', 0)}")
    lines.append(f"- Raw score delta: {b.get('raw_score_delta', 0.0)}")
    lines.append(f"- Calibrated paper delta: {b.get('calibrated_paper_delta', 0.0)}")
    lines.append(
        f"- Max boost / penalty: +{b.get('max_boost')} / {b.get('max_penalty')}"
    )
    lines.append(f"- Real-money sizing: {REAL_MONEY_SIZING_IMPACT}")
    lines.append(f"- Human review: {HUMAN_REVIEW}")
    lines.append(f"- Veto override: {VETO_OVERRIDE}")
    lines.append(f"- Biggest reliability risk: {b.get('biggest_reliability_risk')}")
    lines.append(
        f"- Biggest false-confidence risk: {b.get('biggest_false_confidence_risk')}"
    )
    best = b.get("best_source_bucket_by_sample")
    worst = b.get("worst_source_bucket_by_harm")
    lines.append(
        "- Best source bucket by sample size: "
        + (f"{best.get('bucket_id')} (n={best.get('sample_count')})" if best else "none yet")
    )
    lines.append(
        "- Worst source bucket by harm/false-confidence: "
        + (
            f"{worst.get('bucket_id')} (OCR={worst.get('overconfidence_score')})"
            if worst
            else "none rated yet"
        )
    )
    lines.append(
        f"- Missing next evidence needed: {b.get('missing_next_evidence_needed')}"
    )
    return "\n".join(lines)


__all__ = [
    "MODE_PAPER_ONLY",
    "MODE_DISABLED",
    "REAL_MONEY_SIZING_IMPACT",
    "build_external_evidence_operator_readiness",
    "render_external_evidence_operator_readiness_block",
]
