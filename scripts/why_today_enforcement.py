"""WHY_TODAY enforcement — component-scored gate per candidate.

Integrated Sprint — Part 7 (Kanté defensive batch 2).  Wraps the existing
:mod:`scripts.why_today` heuristic with the *component* formula the
release gate consumes:

  fresh_catalyst    — verification-conditioned freshness signal
  timing_pressure   — price/narrative/filing/source-diversity blend
  specificity       — asset/event/timestamp/invalidation specificity
  cross_source      — cross-source confirmation factor

Hard gate: a candidate may not advance to ADVISORY_CANDIDATE_HUMAN_REVIEW
with WHY_TODAY_score < 0.65, and a high WHY_TODAY (>= 0.75) requires at
least one populated evidence anchor.

Writes ``runtime/release/why_today_summary.json``.
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
    REPO_ROOT / "runtime" / "release" / "why_today_summary.json"
)

WHY_TODAY_HARD_GATE = 0.65
WHY_TODAY_HIGH_THRESHOLD = 0.75

# Verification -> fresh_catalyst contribution.
FRESH_CATALYST_SCORE: dict[str, float] = {
    "VERIFIED": 1.0,
    "FIXTURE_VERIFIED": 0.7,
    "UNVERIFIED_FRESH": 0.4,
    "STALE": 0.2,
    "FALLBACK": 0.0,
    "MOCK": 0.0,
}

REQUIRED_EVIDENCE_KEYS: tuple[str, ...] = (
    "provider", "timestamp_utc", "claim", "verification_status",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp01(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


def fresh_catalyst_score(
    *, verification_status: str, age_hours: float, sla_hours: float
) -> float:
    """Map verification + freshness to a 0..1 fresh-catalyst score."""
    v = (verification_status or "").upper()
    fresh = age_hours <= sla_hours
    if v in {"VERIFIED", "FIXTURE_VERIFIED"} and fresh:
        return FRESH_CATALYST_SCORE[v]
    if v == "UNVERIFIED" and fresh:
        return FRESH_CATALYST_SCORE["UNVERIFIED_FRESH"]
    if v == "STALE" or (v == "UNVERIFIED" and not fresh):
        return FRESH_CATALYST_SCORE["STALE"]
    if v in {"FALLBACK", "MOCK"}:
        return 0.0
    if not fresh:
        return FRESH_CATALYST_SCORE["STALE"]
    return 0.0


def timing_pressure_score(
    *, price_mover_intensity: float, narrative_velocity: float,
    filing_materiality_score: float, source_diversity: float,
) -> float:
    raw = (
        0.40 * _clamp01(price_mover_intensity)
        + 0.30 * _clamp01(narrative_velocity)
        + 0.20 * _clamp01(filing_materiality_score)
        + 0.10 * _clamp01(source_diversity)
    )
    return _clamp01(raw)


def specificity_score(
    *, asset_specific: bool, event_specific: bool,
    timestamp_specific: bool, invalidation_specific: bool,
) -> float:
    raw = (
        0.40 * (1.0 if asset_specific else 0.0)
        + 0.25 * (1.0 if event_specific else 0.0)
        + 0.20 * (1.0 if timestamp_specific else 0.0)
        + 0.15 * (1.0 if invalidation_specific else 0.0)
    )
    return _clamp01(raw)


def evidence_anchor_valid(anchor: dict[str, Any]) -> bool:
    """An anchor is valid only if every required key is non-empty."""
    if not isinstance(anchor, dict):
        return False
    for key in REQUIRED_EVIDENCE_KEYS:
        if not str(anchor.get(key) or "").strip():
            return False
    return True


def evaluate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Compute the full WHY_TODAY breakdown + gate decision for one candidate."""
    fresh = fresh_catalyst_score(
        verification_status=str(candidate.get("verification_status") or ""),
        age_hours=float(candidate.get("age_hours") or 9999.0),
        sla_hours=float(candidate.get("sla_hours") or 48.0),
    )
    timing = timing_pressure_score(
        price_mover_intensity=float(candidate.get("price_mover_intensity") or 0.0),
        narrative_velocity=float(candidate.get("narrative_velocity") or 0.0),
        filing_materiality_score=float(
            candidate.get("filing_materiality_score") or 0.0
        ),
        source_diversity=float(candidate.get("source_diversity") or 0.0),
    )
    spec = specificity_score(
        asset_specific=bool(candidate.get("asset_specific")),
        event_specific=bool(candidate.get("event_specific")),
        timestamp_specific=bool(candidate.get("timestamp_specific")),
        invalidation_specific=bool(candidate.get("invalidation_specific")),
    )
    cross = _clamp01(float(candidate.get("cross_source_confirmation") or 0.0))
    raw_score = round(
        _clamp01(0.40 * fresh + 0.30 * timing + 0.20 * spec + 0.10 * cross),
        6,
    )

    anchors = list(candidate.get("evidence_anchors") or [])
    valid_anchors = [a for a in anchors if evidence_anchor_valid(a)]

    # Cap WHY_TODAY at 0.74 if the candidate would otherwise reach the
    # high threshold but has no valid evidence anchor.
    score = raw_score
    capped_for_anchor = False
    if score >= WHY_TODAY_HIGH_THRESHOLD and not valid_anchors:
        score = WHY_TODAY_HIGH_THRESHOLD - 0.01
        capped_for_anchor = True

    can_promote = (
        score >= WHY_TODAY_HARD_GATE
        and bool(candidate.get("advisory_only", True))
    )
    downgrade_reasons: list[str] = []
    if score < WHY_TODAY_HARD_GATE:
        downgrade_reasons.append("WHY_TODAY_WEAK")
    if capped_for_anchor:
        downgrade_reasons.append("WHY_TODAY_HIGH_REQUIRES_EVIDENCE")

    return {
        "id": candidate.get("id"),
        "fresh_catalyst_score": round(fresh, 6),
        "timing_pressure_score": round(timing, 6),
        "specificity_score": round(spec, 6),
        "cross_source_confirmation": round(cross, 6),
        "why_today_score": round(score, 6),
        "raw_why_today_score": raw_score,
        "evidence_anchors_count": len(anchors),
        "evidence_anchors_valid_count": len(valid_anchors),
        "evidence_anchors": valid_anchors,
        "can_promote_to_human_review": bool(can_promote),
        "downgrade_reasons": downgrade_reasons,
        "high_score_evidence_anchor_required": capped_for_anchor,
    }


def _why_today_enforcement_score(candidates: list[dict[str, Any]]) -> float:
    """0..10 segment score; measures the *gate*, not any single candidate."""
    # Indicator-style scoring (per the sprint formula).  We require the
    # evaluator to demonstrate each property across the candidate set.
    fresh_required = all(
        c["downgrade_reasons"]
        for c in candidates
        if c["fresh_catalyst_score"] == 0.0
    )
    evidence_required = any(c["high_score_evidence_anchor_required"]
                            for c in candidates)
    fallback_capped = all(
        c["why_today_score"] < WHY_TODAY_HIGH_THRESHOLD
        for c in candidates
        if c["fresh_catalyst_score"] == 0.0
    )
    weak_blocks = all(
        not c["can_promote_to_human_review"]
        for c in candidates
        if c["why_today_score"] < WHY_TODAY_HARD_GATE
    )
    components_visible = all(
        all(k in c for k in (
            "fresh_catalyst_score", "timing_pressure_score",
            "specificity_score", "cross_source_confirmation",
            "why_today_score",
        ))
        for c in candidates
    )
    raw = (
        0.30 * (1.0 if fresh_required else 0.0)
        + 0.25 * (1.0 if evidence_required else 0.0)
        + 0.20 * (1.0 if fallback_capped else 0.0)
        + 0.15 * (1.0 if weak_blocks else 0.0)
        + 0.10 * (1.0 if components_visible else 0.0)
    )
    return round(10.0 * _clamp01(raw), 4)


def _fixture_candidates() -> list[dict[str, Any]]:
    return [
        {
            "id": "STRONG_VERIFIED",
            "verification_status": "FIXTURE_VERIFIED",
            "age_hours": 1.0, "sla_hours": 12.0,
            "price_mover_intensity": 0.8, "narrative_velocity": 0.7,
            "filing_materiality_score": 0.6, "source_diversity": 0.7,
            "asset_specific": True, "event_specific": True,
            "timestamp_specific": True, "invalidation_specific": True,
            "cross_source_confirmation": 0.8,
            "evidence_anchors": [
                {"provider": "yfinance",
                 "timestamp_utc": "2026-05-24T10:00:00Z",
                 "claim": "Stock gapped +5% on volume",
                 "verification_status": "FIXTURE_VERIFIED",
                 "source": "yfinance", "source_url": "https://fixture/x"},
                {"provider": "sec_edgar",
                 "timestamp_utc": "2026-05-24T09:30:00Z",
                 "claim": "8-K filed re: contract win",
                 "verification_status": "FIXTURE_VERIFIED"},
            ],
            "advisory_only": True,
        },
        {
            "id": "WEAK_NO_FRESH_CATALYST",
            "verification_status": "FALLBACK",
            "age_hours": 1.0, "sla_hours": 12.0,
            "price_mover_intensity": 0.1, "narrative_velocity": 0.1,
            "filing_materiality_score": 0.0, "source_diversity": 0.0,
            "asset_specific": False, "event_specific": False,
            "timestamp_specific": False, "invalidation_specific": False,
            "cross_source_confirmation": 0.0,
            "evidence_anchors": [],
            "advisory_only": True,
        },
        {
            "id": "HIGH_NO_ANCHOR_CAPPED",
            "verification_status": "FIXTURE_VERIFIED",
            "age_hours": 1.0, "sla_hours": 12.0,
            "price_mover_intensity": 0.9, "narrative_velocity": 0.9,
            "filing_materiality_score": 0.9, "source_diversity": 0.9,
            "asset_specific": True, "event_specific": True,
            "timestamp_specific": True, "invalidation_specific": True,
            "cross_source_confirmation": 0.9,
            "evidence_anchors": [],  # missing — must cap
            "advisory_only": True,
        },
        {
            "id": "PRICE_ONLY_NO_EVIDENCE",
            "verification_status": "UNVERIFIED",
            "age_hours": 1.0, "sla_hours": 6.0,
            "price_mover_intensity": 0.8, "narrative_velocity": 0.0,
            "filing_materiality_score": 0.0, "source_diversity": 0.1,
            "asset_specific": True, "event_specific": False,
            "timestamp_specific": True, "invalidation_specific": False,
            "cross_source_confirmation": 0.1,
            "evidence_anchors": [],
            "advisory_only": True,
        },
    ]


def build_summary(
    candidates: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if candidates is None:
        candidates = _fixture_candidates()
    evaluated = [evaluate_candidate(c) for c in candidates]
    enforcement_score = _why_today_enforcement_score(evaluated)
    return {
        "report": "why_today_summary",
        "ok": enforcement_score >= 9.0,
        "generated_at_utc": _utc_iso(),
        "candidate_count": len(evaluated),
        "promotable_count": sum(
            1 for c in evaluated if c["can_promote_to_human_review"]
        ),
        "weak_blocked_count": sum(
            1 for c in evaluated
            if "WHY_TODAY_WEAK" in c["downgrade_reasons"]
        ),
        "high_score_capped_count": sum(
            1 for c in evaluated if c["high_score_evidence_anchor_required"]
        ),
        "candidates": evaluated,
        "why_today_enforcement_score": enforcement_score,
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
    p = argparse.ArgumentParser(prog="why_today_enforcement.py")
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = write_summary() if args.write_summary else build_summary()
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"why_today_enforcement_score = "
              f"{summary['why_today_enforcement_score']}")
        for c in summary["candidates"]:
            print(f"  {c['id']:30s} score={c['why_today_score']:.3f} "
                  f"promote={c['can_promote_to_human_review']} "
                  f"reasons={c['downgrade_reasons']}")
    return 0


__all__ = [
    "DEFAULT_SUMMARY_PATH",
    "WHY_TODAY_HARD_GATE", "WHY_TODAY_HIGH_THRESHOLD",
    "FRESH_CATALYST_SCORE", "REQUIRED_EVIDENCE_KEYS",
    "fresh_catalyst_score", "timing_pressure_score", "specificity_score",
    "evidence_anchor_valid", "evaluate_candidate",
    "build_summary", "write_summary", "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
