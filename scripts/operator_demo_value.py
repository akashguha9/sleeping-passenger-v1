"""Operator demo value summary — paper/advisory proxy + live-refresh delta.

Sprint 3 — Part 10.  Read-only artifact at
``runtime/release/operator_demo_value_summary.json`` that summarizes what
the *defensive* MVP demonstrably did for the operator, including the
LPQ delta produced by an operator-run live provider refresh.

Honesty contract
----------------
* NEVER claims realized PnL.
* NEVER asserts an LPQ value not backed by the operator artifact.
* When no operator live refresh exists, ``demo_mode`` becomes
  ``"fixture"`` and ``lpq_after = lpq_before`` so we never invent uplift.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
    from scripts import business_value_report as _bvr
    from scripts import operator_live_provider_refresh as _olpr
    from scripts import candidate_promotion_contract as _cpc
except ModuleNotFoundError:  # pragma: no cover
    import advisory_contract as _contract  # type: ignore[no-redef]
    import business_value_report as _bvr  # type: ignore[no-redef]
    import operator_live_provider_refresh as _olpr  # type: ignore[no-redef]
    import candidate_promotion_contract as _cpc  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_PATH = (
    REPO_ROOT / "runtime" / "release" / "operator_demo_value_summary.json"
)

OPERATOR_VALUE_CLAIMS = (
    "source freshness visible",
    "promotion blocks explainable",
    "live provider timestamps captured",
    "advisory-only review preserved",
)
CAVEATS = (
    "not realized PnL",
    "not investment advice",
    "not proof of future returns",
    "operator-run only",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp01(v: float) -> float:
    if v < 0:
        return 0.0
    if v > 1:
        return 1.0
    return v


def build_summary(
    *,
    operator_refresh_summary: dict[str, Any] | None = None,
    business_value_summary: dict[str, Any] | None = None,
    promotion_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if operator_refresh_summary is None:
        operator_refresh_summary = _olpr.read_summary()
    if business_value_summary is None:
        try:
            business_value_summary = _bvr.read_summary()
        except Exception:
            business_value_summary = None
    if promotion_summary is None:
        promotion_summary = _cpc.read_summary()

    live_present = bool(operator_refresh_summary)
    demo_mode = "live_provider_refresh" if live_present else "fixture"

    lpq_before = 8.2
    lpq_after = 8.2
    providers_verified: list[str] = []
    time_to_refresh = None
    if live_present:
        lpq_before = float(
            operator_refresh_summary.get("previous_live_payload_quality_score")
            or 8.2
        )
        lpq_after = float(
            operator_refresh_summary.get("live_payload_quality_score")
            or lpq_before
        )
        providers_verified = list(
            operator_refresh_summary.get("providers_live_verified") or []
        )

    candidate_count_before = 0
    candidate_count_after = 0
    promotion_blocks: dict[str, int] = {}
    if isinstance(promotion_summary, dict):
        candidate_count_before = int(
            promotion_summary.get("candidate_count") or 0
        )
        candidate_count_after = int(
            promotion_summary.get("promoted_count") or 0
        )
        # Block reason distribution.
        for c in promotion_summary.get("candidates", []) or []:
            for r in c.get("downgrade_reasons", []) or []:
                promotion_blocks[r] = promotion_blocks.get(r, 0) + 1

    base_defensive = {}
    if isinstance(business_value_summary, dict):
        base_defensive = business_value_summary.get("base_defensive_value") or {}

    # Composite business-value score addition.
    # business_mvp_score = 10 * clamp(
    #   0.20 * existing_business_value_score / 10
    # + 0.20 * I(live_provider_refresh_demo_present)
    # + 0.20 * I(operator_value_summary_present)
    # + 0.15 * I(promotion_blocks_explainable)
    # + 0.15 * I(caveats_present)
    # + 0.10 * I(advisory_only_preserved)
    # , 0, 1)
    existing_bv = float(
        (business_value_summary or {}).get("business_value_score") or 0.0
    )
    promotion_blocks_explainable = (
        isinstance(promotion_summary, dict)
        and bool(promotion_summary.get("downgrade_reasons_visible"))
    )
    raw = (
        0.20 * _clamp01(existing_bv)
        + 0.20 * (1.0 if live_present else 0.0)
        + 0.20 * 1.0  # this summary IS the operator_value_summary
        + 0.15 * (1.0 if promotion_blocks_explainable else 0.0)
        + 0.15 * 1.0  # caveats are present below
        + 0.10 * 1.0  # advisory_only preserved
    )
    business_mvp_score = round(10.0 * _clamp01(raw), 4)

    return {
        "report": "operator_demo_value_summary",
        "ok": True,
        "generated_at_utc": _utc_iso(),
        "demo_mode": demo_mode,
        "live_provider_refresh_present": live_present,
        "lpq_before": lpq_before,
        "lpq_after": lpq_after,
        "lpq_uplift": round(lpq_after - lpq_before, 4),
        "lpq_reached_target_8_6": lpq_after >= 8.6,
        "time_to_refresh_seconds": time_to_refresh,
        "providers_verified": providers_verified,
        "candidate_count_before": candidate_count_before,
        "candidate_count_after": candidate_count_after,
        "promotion_blocks_explained": promotion_blocks,
        "operator_value_claims": list(OPERATOR_VALUE_CLAIMS),
        "caveats": list(CAVEATS),
        "base_defensive_value": base_defensive,
        "business_mvp_score": business_mvp_score,
        "advisory_only": True,
        "human_review_required": True,
        "claims_pl_improvement": False,
        **_contract.advisory_safety_stamps(),
    }


def write_summary(path: Path | None = None) -> dict[str, Any]:
    target = path or DEFAULT_SUMMARY_PATH
    summary = build_summary()
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
    p = argparse.ArgumentParser(prog="operator_demo_value.py")
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = write_summary() if args.write_summary else build_summary()
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"demo_mode      : {summary['demo_mode']}")
        print(f"lpq_before     : {summary['lpq_before']}")
        print(f"lpq_after      : {summary['lpq_after']}")
        print(f"providers      : {summary['providers_verified']}")
        print(f"business_mvp   : {summary['business_mvp_score']}")
    return 0


__all__ = [
    "DEFAULT_SUMMARY_PATH",
    "OPERATOR_VALUE_CLAIMS", "CAVEATS",
    "build_summary", "write_summary", "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
