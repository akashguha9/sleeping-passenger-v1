"""Candidate promotion contract — advisory-only composite gate.

Sprint 3 — Part 5.  Computes the final promotion decision for a candidate
across every quality / safety / freshness gate the sprint defines.

This is an *advisory MVP*: no candidate state grants broker execution.
The terminal state is named ``ADVISORY_CANDIDATE_HUMAN_REVIEW`` —
explicitly NOT ``executable_for_trade``.  The release gate FAILs if any
advisory invariant is breached.

States
------
DISCOVERY, WATCHLIST, RESEARCH_CANDIDATE, WATCHLIST_UNCERTAIN,
STALE_QUARANTINE, DIABLO_REVIEW, ADVISORY_CANDIDATE_HUMAN_REVIEW, NO_NEW_RISK
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
    REPO_ROOT / "runtime" / "release" / "candidate_promotion_contract_summary.json"
)

CANDIDATE_STATES: tuple[str, ...] = (
    "DISCOVERY",
    "WATCHLIST",
    "RESEARCH_CANDIDATE",
    "WATCHLIST_UNCERTAIN",
    "STALE_QUARANTINE",
    "DIABLO_REVIEW",
    "ADVISORY_CANDIDATE_HUMAN_REVIEW",
    "NO_NEW_RISK",
)

THRESHOLDS = {
    "CQS_final": 0.70,
    "EQS": 0.65,
    "FCS": 0.70,
    "ERS": 0.40,  # max
    "WHY_TODAY": 0.65,
    "LPQ": 0.80,
    "MODEL_DISAGREEMENT_RISK": 0.65,  # max
}

# Tokens that must not appear anywhere in user-visible promotion output.
FORBIDDEN_EXECUTION_LANGUAGE: tuple[str, ...] = (
    "executable_for_trade",
    "executable for trade",
    "execute_trade",
    "auto-trade",
    "buy now",
    "sell now",
    "place_order",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def evaluate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a candidate against the composite gate.

    Required keys (best-effort; missing values default to a safe-blocked
    outcome): ``id``, ``CQS_final``, ``EQS``, ``FCS``, ``ERS``,
    ``WHY_TODAY``, ``LPQ``, ``portfolio_truth_ok``, ``stale_quarantine``,
    ``any_DIABLO``, ``model_disagreement_risk``, ``live_source_block``,
    ``advisory_only``, ``human_review_required``, ``execution_permission``,
    ``broker_api_called``, ``ai_execution_count``.
    """
    def _f(key: str, default: float = 0.0) -> float:
        v = candidate.get(key)
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    cqs = _f("CQS_final")
    eqs = _f("EQS")
    fcs = _f("FCS")
    ers = _f("ERS", default=1.0)
    why_today = _f("WHY_TODAY")
    lpq = _f("LPQ")
    disagreement = _f("model_disagreement_risk", default=0.0)

    portfolio_truth_ok = _bool(candidate.get("portfolio_truth_ok"), default=False)
    stale_quarantine = _bool(candidate.get("stale_quarantine"), default=False)
    any_diablo = _bool(candidate.get("any_DIABLO"), default=False)
    live_source_block = _bool(candidate.get("live_source_block"), default=False)
    advisory_only = _bool(candidate.get("advisory_only"), default=True)
    human_review = _bool(candidate.get("human_review_required"), default=True)
    exec_perm = str(candidate.get("execution_permission") or "ADVISORY_ONLY")
    broker_api_called = _bool(candidate.get("broker_api_called"), default=False)
    ai_exec_count = int(candidate.get("ai_execution_count") or 0)

    gates: dict[str, bool] = {
        "CQS_final_ge_threshold": cqs >= THRESHOLDS["CQS_final"],
        "EQS_ge_threshold": eqs >= THRESHOLDS["EQS"],
        "FCS_ge_threshold": fcs >= THRESHOLDS["FCS"],
        "ERS_le_max": ers <= THRESHOLDS["ERS"],
        "WHY_TODAY_ge_threshold": why_today >= THRESHOLDS["WHY_TODAY"],
        "LPQ_ge_threshold": lpq >= THRESHOLDS["LPQ"],
        "portfolio_truth_ok": portfolio_truth_ok,
        "no_stale_quarantine": not stale_quarantine,
        "no_DIABLO_veto": not any_diablo,
        "model_disagreement_under_hard_threshold":
            disagreement < THRESHOLDS["MODEL_DISAGREEMENT_RISK"],
        "no_live_source_block": not live_source_block,
        "advisory_only": advisory_only,
        "human_review_required": human_review,
        "execution_permission_advisory":
            exec_perm == "ADVISORY_ONLY",
        "broker_api_not_called": not broker_api_called,
        "ai_execution_count_zero": ai_exec_count == 0,
    }
    downgrade_reasons: list[str] = []
    if not gates["CQS_final_ge_threshold"]:
        downgrade_reasons.append("CQS_FINAL_LOW")
    if not gates["EQS_ge_threshold"]:
        downgrade_reasons.append("EQS_LOW")
    if not gates["FCS_ge_threshold"]:
        downgrade_reasons.append("FCS_LOW")
    if not gates["ERS_le_max"]:
        downgrade_reasons.append("ERS_HIGH")
    if not gates["WHY_TODAY_ge_threshold"]:
        downgrade_reasons.append("WHY_TODAY_WEAK")
    if not gates["LPQ_ge_threshold"]:
        downgrade_reasons.append("LPQ_BELOW_THRESHOLD")
    if not gates["portfolio_truth_ok"]:
        downgrade_reasons.append("PORTFOLIO_TRUTH_FAIL")
    if not gates["no_stale_quarantine"]:
        downgrade_reasons.append("STALE_QUARANTINE")
    if not gates["no_DIABLO_veto"]:
        downgrade_reasons.append("DIABLO_MODEL_VETO")
    if not gates["model_disagreement_under_hard_threshold"]:
        downgrade_reasons.append("MODEL_DISAGREEMENT_HIGH")
    if not gates["no_live_source_block"]:
        downgrade_reasons.append("LIVE_SOURCE_BLOCK")
    if not (gates["advisory_only"] and gates["human_review_required"]
            and gates["execution_permission_advisory"]
            and gates["broker_api_not_called"]
            and gates["ai_execution_count_zero"]):
        downgrade_reasons.append("ADVISORY_INVARIANT_BROKEN")

    can_promote = all(gates.values())

    if can_promote:
        state = "ADVISORY_CANDIDATE_HUMAN_REVIEW"
    elif any_diablo:
        state = "DIABLO_REVIEW"
    elif stale_quarantine:
        state = "STALE_QUARANTINE"
    elif disagreement >= THRESHOLDS["MODEL_DISAGREEMENT_RISK"]:
        state = "RESEARCH_CANDIDATE"
    elif disagreement >= 0.40:
        state = "WATCHLIST_UNCERTAIN"
    elif live_source_block or not gates["LPQ_ge_threshold"]:
        state = "WATCHLIST"
    elif not gates["WHY_TODAY_ge_threshold"]:
        state = "DISCOVERY"
    else:
        state = "RESEARCH_CANDIDATE"

    return {
        "id": candidate.get("id"),
        "candidate_state": state,
        "candidate_may_be_actionable_for_human_review": bool(can_promote),
        "gates": gates,
        "downgrade_reasons": downgrade_reasons,
        "formula_components": {
            "CQS_final": cqs, "EQS": eqs, "FCS": fcs, "ERS": ers,
            "WHY_TODAY": why_today, "LPQ": lpq,
            "model_disagreement_risk": disagreement,
            "portfolio_truth_ok": portfolio_truth_ok,
            "stale_quarantine": stale_quarantine,
            "any_DIABLO": any_diablo,
            "live_source_block": live_source_block,
            "advisory_only": advisory_only,
            "human_review_required": human_review,
            "execution_permission": exec_perm,
            "broker_api_called": broker_api_called,
            "ai_execution_count": ai_exec_count,
        },
        "advisory_only": True,
        "human_review_required": True,
        "execution_permission": "ADVISORY_ONLY",
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


def candidate_vs_executable_score(
    *,
    promoted_only_via_full_gate: bool,
    forbidden_language_absent: bool,
    advisory_invariants_in_every_output: bool,
    downgrade_reasons_visible: bool,
    states_use_advisory_vocabulary: bool,
) -> float:
    raw = (
        0.30 * (1.0 if promoted_only_via_full_gate else 0.0)
        + 0.25 * (1.0 if forbidden_language_absent else 0.0)
        + 0.20 * (1.0 if advisory_invariants_in_every_output else 0.0)
        + 0.15 * (1.0 if downgrade_reasons_visible else 0.0)
        + 0.10 * (1.0 if states_use_advisory_vocabulary else 0.0)
    )
    return round(10.0 * max(0.0, min(1.0, raw)), 4)


def _fixture_candidates() -> list[dict[str, Any]]:
    return [
        {
            "id": "ALL_GREEN",
            "CQS_final": 0.78, "EQS": 0.72, "FCS": 0.82, "ERS": 0.28,
            "WHY_TODAY": 0.78, "LPQ": 0.86,
            "model_disagreement_risk": 0.20,
            "portfolio_truth_ok": True,
            "stale_quarantine": False,
            "any_DIABLO": False,
            "live_source_block": False,
            "advisory_only": True, "human_review_required": True,
            "execution_permission": "ADVISORY_ONLY",
            "broker_api_called": False, "ai_execution_count": 0,
        },
        {
            "id": "HIGH_CQS_WEAK_WHY_TODAY",
            "CQS_final": 0.85, "EQS": 0.75, "FCS": 0.80, "ERS": 0.30,
            "WHY_TODAY": 0.50, "LPQ": 0.86,
            "model_disagreement_risk": 0.10,
            "portfolio_truth_ok": True,
            "stale_quarantine": False,
            "any_DIABLO": False,
            "live_source_block": False,
            "advisory_only": True, "human_review_required": True,
            "execution_permission": "ADVISORY_ONLY",
            "broker_api_called": False, "ai_execution_count": 0,
        },
        {
            "id": "HIGH_CQS_STALE_LPQ",
            "CQS_final": 0.85, "EQS": 0.75, "FCS": 0.80, "ERS": 0.30,
            "WHY_TODAY": 0.70, "LPQ": 0.50,
            "model_disagreement_risk": 0.10,
            "portfolio_truth_ok": True,
            "stale_quarantine": False,
            "any_DIABLO": False,
            "live_source_block": True,
            "advisory_only": True, "human_review_required": True,
            "execution_permission": "ADVISORY_ONLY",
            "broker_api_called": False, "ai_execution_count": 0,
        },
        {
            "id": "DIABLO_BLOCKED",
            "CQS_final": 0.90, "EQS": 0.90, "FCS": 0.90, "ERS": 0.20,
            "WHY_TODAY": 0.90, "LPQ": 0.90,
            "model_disagreement_risk": 0.55,
            "portfolio_truth_ok": True,
            "stale_quarantine": False,
            "any_DIABLO": True,
            "live_source_block": False,
            "advisory_only": True, "human_review_required": True,
            "execution_permission": "ADVISORY_ONLY",
            "broker_api_called": False, "ai_execution_count": 0,
        },
        {
            "id": "PORTFOLIO_TRUTH_BROKEN",
            "CQS_final": 0.80, "EQS": 0.75, "FCS": 0.80, "ERS": 0.30,
            "WHY_TODAY": 0.75, "LPQ": 0.86,
            "model_disagreement_risk": 0.10,
            "portfolio_truth_ok": False,
            "stale_quarantine": False,
            "any_DIABLO": False,
            "live_source_block": False,
            "advisory_only": True, "human_review_required": True,
            "execution_permission": "ADVISORY_ONLY",
            "broker_api_called": False, "ai_execution_count": 0,
        },
    ]


def build_summary(
    candidates: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if candidates is None:
        candidates = _fixture_candidates()
    evaluated = [evaluate_candidate(c) for c in candidates]
    promoted_only_via_full_gate = all(
        (c["candidate_may_be_actionable_for_human_review"]
         and c["candidate_state"] == "ADVISORY_CANDIDATE_HUMAN_REVIEW")
        or not c["candidate_may_be_actionable_for_human_review"]
        for c in evaluated
    )
    # forbidden language must not appear in any candidate state or formula.
    full_text = json.dumps(evaluated, default=str)
    forbidden_absent = not any(t in full_text for t in FORBIDDEN_EXECUTION_LANGUAGE)
    advisory_invariants_in_every_output = all(
        c.get("advisory_only") is True
        and c.get("human_review_required") is True
        and c.get("execution_permission") == "ADVISORY_ONLY"
        and c.get("broker_api_called") is False
        and c.get("ai_execution_count") == 0
        for c in evaluated
    )
    downgrade_visible = all(
        bool(c["downgrade_reasons"])
        for c in evaluated
        if not c["candidate_may_be_actionable_for_human_review"]
    )
    states_use_advisory_vocab = all(
        c["candidate_state"] in CANDIDATE_STATES for c in evaluated
    )

    score = candidate_vs_executable_score(
        promoted_only_via_full_gate=promoted_only_via_full_gate,
        forbidden_language_absent=forbidden_absent,
        advisory_invariants_in_every_output=advisory_invariants_in_every_output,
        downgrade_reasons_visible=downgrade_visible,
        states_use_advisory_vocabulary=states_use_advisory_vocab,
    )
    return {
        "report": "candidate_promotion_contract_summary",
        "ok": score >= 9.5,
        "generated_at_utc": _utc_iso(),
        "candidate_count": len(evaluated),
        "promoted_count": sum(
            1 for c in evaluated
            if c["candidate_may_be_actionable_for_human_review"]
        ),
        "blocked_count": sum(
            1 for c in evaluated
            if not c["candidate_may_be_actionable_for_human_review"]
        ),
        "states_distribution": {
            s: sum(1 for c in evaluated if c["candidate_state"] == s)
            for s in CANDIDATE_STATES
        },
        "candidates": evaluated,
        "thresholds": THRESHOLDS,
        "candidate_vs_executable_score": score,
        "promoted_only_via_full_gate": bool(promoted_only_via_full_gate),
        "forbidden_execution_language_absent": bool(forbidden_absent),
        "advisory_invariants_in_every_output":
            bool(advisory_invariants_in_every_output),
        "downgrade_reasons_visible": bool(downgrade_visible),
        "states_use_advisory_vocabulary": bool(states_use_advisory_vocab),
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
    p = argparse.ArgumentParser(prog="candidate_promotion_contract.py")
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = write_summary() if args.write_summary else build_summary()
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"candidate_vs_executable_score = "
              f"{summary['candidate_vs_executable_score']}")
        for c in summary["candidates"]:
            print(f"  {c['id']:28s} state={c['candidate_state']:32s} "
                  f"promote={c['candidate_may_be_actionable_for_human_review']} "
                  f"reasons={c['downgrade_reasons']}")
    return 0


__all__ = [
    "DEFAULT_SUMMARY_PATH",
    "CANDIDATE_STATES", "THRESHOLDS", "FORBIDDEN_EXECUTION_LANGUAGE",
    "evaluate_candidate", "candidate_vs_executable_score",
    "build_summary", "write_summary", "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
