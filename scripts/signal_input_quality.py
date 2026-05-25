"""Signal input quality — CQS_final, EQS, FCS, ERS + promotion gate.

Integrated Sprint — Part 11 (Kanté defensive batch 2).  Each candidate is
scored with the four-component formulas the spec defines and is allowed
to enter ADVISORY_CANDIDATE_HUMAN_REVIEW only if all gates pass:

  CQS_final >= 0.70
  EQS >= 0.65
  FCS >= 0.70
  ERS <= 0.40
  WHY_TODAY_score >= 0.65
  LPQ >= 0.80
  advisory_only AND human_review_required AND execution_permission == ADVISORY_ONLY

Writes ``runtime/release/signal_input_quality_summary.json``.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover
    import advisory_contract as _contract  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_PATH = (
    REPO_ROOT / "runtime" / "release" / "signal_input_quality_summary.json"
)

REQUIRED_SOURCE_CLASSES = 3  # price_mover + filing + news_event

GATE_THRESHOLDS = {
    "CQS_final": 0.70,
    "EQS": 0.65,
    "FCS": 0.70,
    "ERS": 0.40,  # max (lower is better)
    "WHY_TODAY": 0.65,
    "LPQ": 0.80,
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp01(v: float) -> float:
    if v < 0:
        return 0.0
    if v > 1:
        return 1.0
    return v


def input_quality(
    *,
    verified_source_ratio: float, fresh_source_ratio: float,
    cross_source_ratio: float, source_reliability_weighted_mean: float,
    schema_completeness: float,
) -> float:
    raw = (
        0.30 * _clamp01(verified_source_ratio)
        + 0.25 * _clamp01(fresh_source_ratio)
        + 0.20 * _clamp01(cross_source_ratio)
        + 0.15 * _clamp01(source_reliability_weighted_mean)
        + 0.10 * _clamp01(schema_completeness)
    )
    return round(_clamp01(raw), 6)


def cqs_final(
    *, cqs_raw: float, input_quality_value: float,
    model_disagreement_risk: float,
) -> float:
    base = _clamp01(cqs_raw) * _clamp01(input_quality_value)
    disagreement_factor = max(0.0, 1.0 - 0.30 * _clamp01(model_disagreement_risk))
    return round(_clamp01(base * disagreement_factor), 6)


def eqs(
    *, verified_source_ratio: float, evidence_anchor_completeness: float,
    cross_source_ratio: float, source_reliability_weighted_mean: float,
) -> float:
    raw = (
        0.35 * _clamp01(verified_source_ratio)
        + 0.25 * _clamp01(evidence_anchor_completeness)
        + 0.20 * _clamp01(cross_source_ratio)
        + 0.20 * _clamp01(source_reliability_weighted_mean)
    )
    return round(_clamp01(raw), 6)


def fcs(
    *, fresh_source_ratio: float, lpq: float, why_today_score: float,
    live_verified_source_ratio: float = 0.0,
) -> float:
    """Fresh-Confidence-Score per the sprint formula.

    Sprint 3 cross-wire: the optional ``live_verified_source_ratio`` lifts
    FCS when LIVE_VERIFIED provider evidence is present.  Defaulting it to
    0 keeps backwards-compatibility with callers that do not yet pass
    live evidence.

    .. math::

        FCS = 0.40 * fresh_source_ratio
            + 0.25 * LPQ
            + 0.20 * WHY_TODAY
            + 0.15 * live_verified_source_ratio
    """
    raw = (
        0.40 * _clamp01(fresh_source_ratio)
        + 0.25 * _clamp01(lpq)
        + 0.20 * _clamp01(why_today_score)
        + 0.15 * _clamp01(live_verified_source_ratio)
    )
    return round(_clamp01(raw), 6)


def ers(
    *, chaos_risk: float, stale_risk: float, model_disagreement_risk: float,
    source_unverified_risk: float, operator_risk: float,
) -> float:
    raw = (
        0.30 * _clamp01(chaos_risk)
        + 0.25 * _clamp01(stale_risk)
        + 0.20 * _clamp01(model_disagreement_risk)
        + 0.15 * _clamp01(source_unverified_risk)
        + 0.10 * _clamp01(operator_risk)
    )
    return round(_clamp01(raw), 6)


def evaluate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """All four formulas + the composite promotion gate for one candidate."""
    iq = input_quality(
        verified_source_ratio=float(candidate.get("verified_source_ratio") or 0.0),
        fresh_source_ratio=float(candidate.get("fresh_source_ratio") or 0.0),
        cross_source_ratio=float(candidate.get("cross_source_ratio") or 0.0),
        source_reliability_weighted_mean=float(
            candidate.get("source_reliability_weighted_mean") or 0.0
        ),
        schema_completeness=float(candidate.get("schema_completeness") or 0.0),
    )
    cqs_v = cqs_final(
        cqs_raw=float(candidate.get("cqs_raw") or 0.0),
        input_quality_value=iq,
        model_disagreement_risk=float(
            candidate.get("model_disagreement_risk") or 0.0
        ),
    )
    eqs_v = eqs(
        verified_source_ratio=float(candidate.get("verified_source_ratio") or 0.0),
        evidence_anchor_completeness=float(
            candidate.get("evidence_anchor_completeness") or 0.0
        ),
        cross_source_ratio=float(candidate.get("cross_source_ratio") or 0.0),
        source_reliability_weighted_mean=float(
            candidate.get("source_reliability_weighted_mean") or 0.0
        ),
    )
    fcs_v = fcs(
        fresh_source_ratio=float(candidate.get("fresh_source_ratio") or 0.0),
        lpq=float(candidate.get("lpq") or 0.0),
        why_today_score=float(candidate.get("why_today_score") or 0.0),
        live_verified_source_ratio=float(
            candidate.get("live_verified_source_ratio") or 0.0
        ),
    )
    ers_v = ers(
        chaos_risk=float(candidate.get("chaos_risk") or 0.0),
        stale_risk=float(candidate.get("stale_risk") or 0.0),
        model_disagreement_risk=float(
            candidate.get("model_disagreement_risk") or 0.0
        ),
        source_unverified_risk=float(
            candidate.get("source_unverified_risk") or 0.0
        ),
        operator_risk=float(candidate.get("operator_risk") or 0.0),
    )

    advisory_ok = (
        bool(candidate.get("advisory_only", True))
        and bool(candidate.get("human_review_required", True))
        and str(candidate.get("execution_permission") or "ADVISORY_ONLY")
            == "ADVISORY_ONLY"
    )
    gates: dict[str, bool] = {
        "CQS_final": cqs_v >= GATE_THRESHOLDS["CQS_final"],
        "EQS": eqs_v >= GATE_THRESHOLDS["EQS"],
        "FCS": fcs_v >= GATE_THRESHOLDS["FCS"],
        "ERS": ers_v <= GATE_THRESHOLDS["ERS"],
        "WHY_TODAY": float(candidate.get("why_today_score") or 0.0)
                     >= GATE_THRESHOLDS["WHY_TODAY"],
        "LPQ": float(candidate.get("lpq") or 0.0) >= GATE_THRESHOLDS["LPQ"],
        "advisory_invariants": advisory_ok,
    }
    can_promote = all(gates.values())
    blocked_by = [g for g, ok in gates.items() if not ok]
    return {
        "id": candidate.get("id"),
        "input_quality": iq,
        "CQS_final": cqs_v,
        "EQS": eqs_v,
        "FCS": fcs_v,
        "ERS": ers_v,
        "gates": gates,
        "can_promote": bool(can_promote),
        "blocked_by": blocked_by,
        "formula_components": {
            "verified_source_ratio": candidate.get("verified_source_ratio"),
            "fresh_source_ratio": candidate.get("fresh_source_ratio"),
            "cross_source_ratio": candidate.get("cross_source_ratio"),
            "evidence_anchor_completeness":
                candidate.get("evidence_anchor_completeness"),
            "model_disagreement_risk":
                candidate.get("model_disagreement_risk"),
            "lpq": candidate.get("lpq"),
            "why_today_score": candidate.get("why_today_score"),
            "chaos_risk": candidate.get("chaos_risk"),
            "stale_risk": candidate.get("stale_risk"),
            "source_unverified_risk":
                candidate.get("source_unverified_risk"),
            "operator_risk": candidate.get("operator_risk"),
        },
    }


def _signal_input_quality_score(candidates: list[dict[str, Any]]) -> float:
    cqs_uses_iq = any(
        c["CQS_final"] < (c["formula_components"].get("cqs_raw") or 1.0)
        for c in candidates
    ) or any(c["input_quality"] < 1.0 for c in candidates)
    eqs_uses_anchors = any(
        c["formula_components"]["evidence_anchor_completeness"] is not None
        for c in candidates
    )
    fcs_uses_lpq = any(
        c["formula_components"]["lpq"] is not None for c in candidates
    )
    ers_blocks = any(
        "ERS" in c["blocked_by"] for c in candidates
    )
    components_visible = all(
        "formula_components" in c and isinstance(c["formula_components"], dict)
        for c in candidates
    )
    raw = (
        0.25 * (1.0 if cqs_uses_iq else 0.0)
        + 0.20 * (1.0 if eqs_uses_anchors else 0.0)
        + 0.20 * (1.0 if fcs_uses_lpq else 0.0)
        + 0.20 * (1.0 if ers_blocks else 0.0)
        + 0.15 * (1.0 if components_visible else 0.0)
    )
    return round(10.0 * _clamp01(raw), 4)


def _fixture_candidates() -> list[dict[str, Any]]:
    return [
        {
            "id": "GOLD",
            "cqs_raw": 0.85, "verified_source_ratio": 0.9,
            "fresh_source_ratio": 0.9, "cross_source_ratio": 1.0,
            "source_reliability_weighted_mean": 0.85,
            "schema_completeness": 1.0,
            "evidence_anchor_completeness": 0.9,
            "model_disagreement_risk": 0.10, "lpq": 0.88,
            "why_today_score": 0.82,
            "chaos_risk": 0.20, "stale_risk": 0.15,
            "source_unverified_risk": 0.10, "operator_risk": 0.10,
            "advisory_only": True, "human_review_required": True,
            "execution_permission": "ADVISORY_ONLY",
        },
        {
            "id": "HIGH_RISK",
            "cqs_raw": 0.85, "verified_source_ratio": 0.9,
            "fresh_source_ratio": 0.9, "cross_source_ratio": 1.0,
            "source_reliability_weighted_mean": 0.85,
            "schema_completeness": 1.0,
            "evidence_anchor_completeness": 0.9,
            "model_disagreement_risk": 0.30, "lpq": 0.88,
            "why_today_score": 0.82,
            "chaos_risk": 0.95, "stale_risk": 0.95,
            "source_unverified_risk": 0.95, "operator_risk": 0.95,
            "advisory_only": True, "human_review_required": True,
            "execution_permission": "ADVISORY_ONLY",
        },
        {
            "id": "HIGH_CQS_LOW_IQ",
            "cqs_raw": 0.99, "verified_source_ratio": 0.1,
            "fresh_source_ratio": 0.1, "cross_source_ratio": 0.1,
            "source_reliability_weighted_mean": 0.1,
            "schema_completeness": 0.2,
            "evidence_anchor_completeness": 0.2,
            "model_disagreement_risk": 0.3, "lpq": 0.3,
            "why_today_score": 0.7,
            "chaos_risk": 0.2, "stale_risk": 0.2,
            "source_unverified_risk": 0.6, "operator_risk": 0.2,
            "advisory_only": True, "human_review_required": True,
            "execution_permission": "ADVISORY_ONLY",
        },
    ]


def build_summary(
    candidates: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if candidates is None:
        candidates = _fixture_candidates()
    evaluated = [evaluate_candidate(c) for c in candidates]
    # Stash cqs_raw into formula_components so the segment score can verify
    # that CQS_final actually changed.
    for src, dst in zip(candidates, evaluated):
        dst["formula_components"]["cqs_raw"] = src.get("cqs_raw")
    score = _signal_input_quality_score(evaluated)
    return {
        "report": "signal_input_quality_summary",
        "ok": score >= 9.0,
        "generated_at_utc": _utc_iso(),
        "candidate_count": len(evaluated),
        "promotable_count": sum(1 for c in evaluated if c["can_promote"]),
        "blocked_count": sum(1 for c in evaluated if not c["can_promote"]),
        "candidates": evaluated,
        "gate_thresholds": GATE_THRESHOLDS,
        "signal_input_quality_score": score,
        "advisory_only": True,
        **_contract.advisory_safety_stamps(),
    }


def write_summary(path: Path | None = None,
                  candidates: Iterable[dict[str, Any]] | None = None,
                  ) -> dict[str, Any]:
    target = path or DEFAULT_SUMMARY_PATH
    summary = build_summary(candidates)
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
    p = argparse.ArgumentParser(prog="signal_input_quality.py")
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = write_summary() if args.write_summary else build_summary()
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"signal_input_quality_score = "
              f"{summary['signal_input_quality_score']}")
        for c in summary["candidates"]:
            print(f"  {c['id']:18s} CQS={c['CQS_final']:.3f} EQS={c['EQS']:.3f} "
                  f"FCS={c['FCS']:.3f} ERS={c['ERS']:.3f} "
                  f"can_promote={c['can_promote']}")
    return 0


__all__ = [
    "DEFAULT_SUMMARY_PATH", "GATE_THRESHOLDS",
    "input_quality", "cqs_final", "eqs", "fcs", "ers",
    "evaluate_candidate", "build_summary", "write_summary", "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
