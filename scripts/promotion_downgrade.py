"""Candidate promotion gate w/ live-payload-aware downgrade (Integrated Sprint — Part 3).

Combines a candidate's raw scores with the Live Payload Quality summary +
optional AI disagreement / DIABLO veto signal to decide the *output state* the
candidate may carry — never an execution permission.

Output state vocabulary (NEVER includes broker-executable):

    ADVISORY_CANDIDATE_HUMAN_REVIEW  — promoted (still requires a human)
    RESEARCH_CANDIDATE               — explanation/research-only
    WATCHLIST                        — surfaced but not promoted
    NO_NEW_RISK                      — operator-overload safety hold
    DIABLO_REVIEW                    — DIABLO veto in effect
    HUMAN_REVIEW_REQUIRED            — generic fallback

Promotion contract::

    actionable_for_human_review =
        CQS_live_adjusted >= executable_threshold
        AND WHY_TODAY_score >= why_today_threshold
        AND LPQ >= 0.80
        AND no required source class in {STALE, FALLBACK, MOCK}
        AND advisory_only == true
        AND human_review_required == true
        AND execution_permission == "ADVISORY_ONLY"

Pure module; no DB, no broker calls, no execution, no AI execution.
"""
from __future__ import annotations

import argparse
import json
import math
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import live_payload_quality as _lpq
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import live_payload_quality as _lpq  # type: ignore[no-redef]


DEFAULT_EXECUTABLE_THRESHOLD = 0.70
DEFAULT_WHY_TODAY_THRESHOLD = 0.60
DEFAULT_MODEL_DISAGREEMENT_VETO = 0.60


def _clamp01(value: float) -> float:
    if value is None or math.isnan(value):
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def decide_promotion(
    *,
    cqs_raw: float,
    why_today_score: float,
    lpq_summary: dict[str, Any],
    model_disagreement: float = 0.0,
    diablo_veto: bool = False,
    executable_threshold: float = DEFAULT_EXECUTABLE_THRESHOLD,
    why_today_threshold: float = DEFAULT_WHY_TODAY_THRESHOLD,
    model_disagreement_veto: float = DEFAULT_MODEL_DISAGREEMENT_VETO,
) -> dict[str, Any]:
    """Decide candidate state from raw CQS + WHY_TODAY + LPQ + AI signals.

    Returns the chosen ``state`` (advisory vocabulary) + the live-adjusted CQS
    + the list of ``downgrade_reasons`` so the cockpit can show *why* a strong
    raw candidate did not promote.  Advisory-only invariants are always set.
    """
    m_live = float(lpq_summary.get("m_live", 1.0) or 1.0)
    lpq_value = float(lpq_summary.get("lpq", 0.0) or 0.0)
    lpq_reasons = list(lpq_summary.get("downgrade_reasons", []) or [])
    cqs_live_adjusted = round(_clamp01(cqs_raw) * _clamp01(m_live), 6)
    why_today_clamped = _clamp01(why_today_score)

    reasons: list[str] = list(lpq_reasons)
    if why_today_clamped < why_today_threshold:
        reasons.append("WHY_TODAY_WEAK")
    if model_disagreement >= model_disagreement_veto:
        reasons.append("MODEL_DISAGREEMENT_HIGH")
    if diablo_veto:
        reasons.append("DIABLO_MODEL_VETO")

    reasons = sorted(set(reasons))

    promoted = (
        cqs_live_adjusted >= executable_threshold
        and why_today_clamped >= why_today_threshold
        and lpq_value >= 0.80
        and "DIABLO_MODEL_VETO" not in reasons
        and "MODEL_DISAGREEMENT_HIGH" not in reasons
        and "LPQ_BELOW_THRESHOLD" not in reasons
        and "PRICE_SOURCE_STALE" not in reasons
        and "PRICE_SOURCE_FALLBACK" not in reasons
        and "FILINGS_SOURCE_STALE" not in reasons
        and "NEWS_SOURCE_STALE" not in reasons
        and "NEWS_SOURCE_FALLBACK" not in reasons
    )

    if diablo_veto:
        state = "DIABLO_REVIEW"
    elif "MODEL_DISAGREEMENT_HIGH" in reasons:
        state = "RESEARCH_CANDIDATE"
    elif not promoted and cqs_live_adjusted < executable_threshold:
        state = "RESEARCH_CANDIDATE"
    elif not promoted:
        state = "WATCHLIST"
    else:
        state = "ADVISORY_CANDIDATE_HUMAN_REVIEW"

    return {
        "report": "promotion_downgrade_decision",
        "state": state,
        "promoted": promoted,
        "cqs_raw": round(_clamp01(cqs_raw), 6),
        "cqs_live_adjusted": cqs_live_adjusted,
        "why_today_score": why_today_clamped,
        "lpq": lpq_value,
        "m_live": m_live,
        "model_disagreement": round(_clamp01(model_disagreement), 6),
        "diablo_veto": bool(diablo_veto),
        "downgrade_reasons": reasons,
        "executable_threshold": executable_threshold,
        "why_today_threshold": why_today_threshold,
        "model_disagreement_veto": model_disagreement_veto,
        # Safety invariants — never any execution permission.
        "advisory_only": True,
        "human_review_required": True,
        # Contract stamps spread first so our string `execution_permission`
        # (advisory vocabulary) wins over the contract's boolean alias.
        **_contract.execution_lock_stamp(),
        "execution_permission": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="promotion_downgrade.py",
        description=(
            "Decide candidate promotion from CQS + WHY_TODAY + LPQ + AI "
            "signals. Read-only; never an execution permission."
        ),
    )
    p.add_argument("--cqs", type=float, required=True)
    p.add_argument("--why-today", type=float, required=True)
    p.add_argument("--lpq-json", type=str, required=True,
                   help="JSON for the LPQ summary (compute_lpq output)")
    p.add_argument("--model-disagreement", type=float, default=0.0)
    p.add_argument("--diablo-veto", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    lpq_summary = json.loads(args.lpq_json)
    result = decide_promotion(
        cqs_raw=args.cqs,
        why_today_score=args.why_today,
        lpq_summary=lpq_summary,
        model_disagreement=args.model_disagreement,
        diablo_veto=args.diablo_veto,
    )
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print("Promotion Decision (advisory)")
        print("=============================")
        print(f"  state                : {result['state']}")
        print(f"  promoted             : {result['promoted']}")
        print(f"  cqs_live_adjusted    : {result['cqs_live_adjusted']}")
        print(f"  downgrade_reasons    : {result['downgrade_reasons']}")
    return 0


__all__ = [
    "DEFAULT_EXECUTABLE_THRESHOLD",
    "DEFAULT_WHY_TODAY_THRESHOLD",
    "DEFAULT_MODEL_DISAGREEMENT_VETO",
    "decide_promotion",
]


if __name__ == "__main__":
    raise SystemExit(main())
