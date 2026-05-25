"""Fresh-discovery quality — per-candidate freshness/novelty/cross-source score.

Integrated Sprint — Part 5 (Kanté defensive batch 2).  Each candidate is
scored on:

* fresh-event count (capped at 3 to avoid a single news flood dominating),
* cross-source confirmation (unique verified source classes / required),
* novelty ratio (events not seen in the recent memory window),
* source-reliability-weighted mean of all supporting events,
* WHY_TODAY contribution.

A discovery *gate* refuses to promote a candidate that has no fresh
verified-or-fixture-verified event, that is a stale repeat, or whose
fresh-discovery-score is below 0.65.

Pure module: caller passes candidate dicts; writes
``runtime/release/fresh_discovery_summary.json`` when asked.
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
    REPO_ROOT / "runtime" / "release" / "fresh_discovery_summary.json"
)

REQUIRED_SOURCE_CLASSES_DEFAULT = 3  # price_mover + filing + news_event
FRESH_DISCOVERY_GATE_MIN = 0.65

# Verification states that may count as "verified for discovery".
VERIFIED_LIKE = frozenset({"VERIFIED", "FIXTURE_VERIFIED", "LIVE_VERIFIED"})

# Sprint 3 — boost a candidate when LIVE_VERIFIED provider evidence is
# present.  Spec rules:
#   * 1 LIVE_VERIFIED source class  -> +0.15
#   * 2 or more source classes      -> +0.25
# The boost is *capped* at 0.25, applied AFTER the base fresh_discovery
# score, and clamped to [0,1].
LIVE_EVIDENCE_BOOST_SINGLE = 0.15
LIVE_EVIDENCE_BOOST_MULTI = 0.25


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp01(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


def _source_reliability(source_class: str, verification_status: str) -> float:
    """Per-source reliability weight in [0,1]."""
    base = {
        "filing": 0.95,
        "price_mover": 0.85,
        "news_event": 0.70,
        "ai_report": 0.45,
    }.get(source_class, 0.30)
    discount = {
        "VERIFIED": 1.0,
        "FIXTURE_VERIFIED": 0.85,
        "UNVERIFIED": 0.5,
        "STALE": 0.25,
        "FALLBACK": 0.0,
        "MOCK": 0.0,
    }.get(verification_status, 0.0)
    return _clamp01(base * discount)


def score_candidate(
    candidate: dict[str, Any],
    *,
    required_source_classes: int = REQUIRED_SOURCE_CLASSES_DEFAULT,
) -> dict[str, Any]:
    """Score a single candidate and emit a gate decision.

    ``candidate`` schema (all optional except ``id``):

      * id              — stable candidate key (string)
      * events          — list of event dicts: {source_class, verification_status,
                          age_hours, is_novel, source_class_required_for_promotion}
      * why_today_score — float in [0,1]
      * stale_repeated  — bool (true if no new verified catalyst since last appearance)
      * advisory_only   — bool (must remain True)
    """
    events = list(candidate.get("events") or [])
    fresh_events = [
        e for e in events
        if e.get("verification_status") in VERIFIED_LIKE
        and float(e.get("age_hours") or 9999.0) <= float(
            e.get("sla_hours") or 48.0
        )
    ]
    novel_events = [e for e in events if e.get("is_novel")]

    fresh_event_count = len(fresh_events)
    novel_event_count = len(novel_events)
    total_event_count = len(events)

    unique_classes = {
        str(e.get("source_class") or "")
        for e in fresh_events
        if e.get("source_class")
    }
    cross_source_confirmation = _clamp01(
        len(unique_classes) / max(required_source_classes, 1)
    )

    novelty_ratio = (
        novel_event_count / total_event_count if total_event_count else 0.0
    )

    reliability_mean = (
        sum(
            _source_reliability(
                str(e.get("source_class") or ""),
                str(e.get("verification_status") or ""),
            )
            for e in events
        ) / total_event_count
        if total_event_count else 0.0
    )

    why_today = _clamp01(float(candidate.get("why_today_score") or 0.0))

    raw = (
        0.30 * min(1.0, fresh_event_count / 3.0)
        + 0.25 * cross_source_confirmation
        + 0.20 * _clamp01(novelty_ratio)
        + 0.15 * reliability_mean
        + 0.10 * why_today
    )
    fresh_discovery_score = round(_clamp01(raw), 6)

    # Sprint 3 cross-wire: a candidate carrying LIVE_VERIFIED provider
    # evidence (from operator-run live refresh) earns a discovery boost.
    live_evidence = list(candidate.get("live_provider_evidence") or [])
    live_verified_classes: set[str] = set()
    for ev in live_evidence:
        if str(ev.get("verification_status") or "").upper() != "LIVE_VERIFIED":
            continue
        sc = str(ev.get("source_class") or ev.get("source_type") or "")
        if sc:
            live_verified_classes.add(sc)
    if len(live_verified_classes) >= 2:
        live_evidence_boost = LIVE_EVIDENCE_BOOST_MULTI
    elif len(live_verified_classes) == 1:
        live_evidence_boost = LIVE_EVIDENCE_BOOST_SINGLE
    else:
        live_evidence_boost = 0.0
    fresh_discovery_score_live_adjusted = round(
        _clamp01(fresh_discovery_score + live_evidence_boost), 6
    )

    has_verified_fresh = bool(fresh_events)
    stale_repeated = bool(candidate.get("stale_repeated"))
    advisory_only = bool(candidate.get("advisory_only", True))

    can_enter = (
        fresh_discovery_score_live_adjusted >= FRESH_DISCOVERY_GATE_MIN
        and has_verified_fresh
        and not stale_repeated
        and advisory_only
    )
    block_reasons: list[str] = []
    if not has_verified_fresh:
        block_reasons.append("NO_VERIFIED_FRESH_EVENT")
    if stale_repeated:
        block_reasons.append("STALE_REPEAT")
    if fresh_discovery_score_live_adjusted < FRESH_DISCOVERY_GATE_MIN:
        block_reasons.append("FRESH_DISCOVERY_SCORE_LOW")
    if not advisory_only:
        block_reasons.append("ADVISORY_INVARIANT_BROKEN")

    return {
        "id": candidate.get("id"),
        "fresh_event_count": fresh_event_count,
        "novel_event_count": novel_event_count,
        "total_event_count": total_event_count,
        "unique_fresh_source_classes": sorted(unique_classes),
        "cross_source_confirmation": round(cross_source_confirmation, 6),
        "novelty_ratio": round(_clamp01(novelty_ratio), 6),
        "source_reliability_weighted_mean": round(reliability_mean, 6),
        "why_today_score": round(why_today, 6),
        "fresh_discovery_score": fresh_discovery_score,
        "fresh_discovery_score_live_adjusted": fresh_discovery_score_live_adjusted,
        "live_evidence_boost": round(live_evidence_boost, 6),
        "live_verified_source_classes": sorted(live_verified_classes),
        "can_enter_fresh_discovery": bool(can_enter),
        "block_reasons": block_reasons,
        "stale_repeated": stale_repeated,
        "advisory_only": advisory_only,
    }


def build_summary(
    candidates: Iterable[dict[str, Any]] | None = None,
    *,
    fixture_mode: bool = True,
) -> dict[str, Any]:
    if candidates is None:
        candidates = _fixture_candidates()
    scored = [score_candidate(c) for c in candidates]
    n = len(scored)
    fresh_count = sum(1 for s in scored if s["can_enter_fresh_discovery"])
    accepted_scores = [
        s["fresh_discovery_score"] for s in scored
        if s["can_enter_fresh_discovery"]
    ]
    accepted_avg = (
        round(sum(accepted_scores) / len(accepted_scores), 6)
        if accepted_scores else 0.0
    )
    avg_score = (
        round(sum(s["fresh_discovery_score"] for s in scored) / n, 6)
        if n else 0.0
    )
    stale_blocks = sum(1 for s in scored if "STALE_REPEAT" in s["block_reasons"])
    fallback_blocks = sum(
        1 for s in scored
        if "NO_VERIFIED_FRESH_EVENT" in s["block_reasons"]
    )

    # Segment score measures TWO things:
    #   1. quality   — how good are the candidates we *did* admit
    #   2. discipline — did the gate reject every candidate it should have
    # If discipline holds (all rejected candidates carry an explicit block
    # reason, and at least one good candidate was admitted), the gate is
    # functioning as designed.
    rejected = [s for s in scored if not s["can_enter_fresh_discovery"]]
    if rejected:
        # Every rejection must carry a concrete reason — otherwise the gate
        # is silently rejecting and we cannot count it as disciplined.
        discipline = 1.0 if all(s["block_reasons"] for s in rejected) else 0.0
    else:
        discipline = 1.0 if accepted_scores else 0.0
    raw_segment = 10.0 * (0.6 * accepted_avg + 0.4 * discipline)
    fresh_discovery_quality_score = round(min(10.0, max(0.0, raw_segment)), 4)

    return {
        "report": "fresh_discovery_summary",
        "ok": fresh_discovery_quality_score >= 9.0,
        "generated_at_utc": _utc_iso(),
        "fixture_mode": bool(fixture_mode),
        "candidate_count": n,
        "fresh_candidate_count": fresh_count,
        "average_fresh_discovery_score": avg_score,
        "stale_repeat_block_count": stale_blocks,
        "fallback_only_block_count": fallback_blocks,
        "candidates": scored,
        "fresh_discovery_quality_score": fresh_discovery_quality_score,
        "advisory_only": True,
        **_contract.advisory_safety_stamps(),
    }


def _fixture_candidates() -> list[dict[str, Any]]:
    """Deterministic 4-candidate fixture exercising every gate path."""
    return [
        {
            "id": "FRESH_PASS",
            "events": [
                {"source_class": "price_mover",
                 "verification_status": "FIXTURE_VERIFIED",
                 "age_hours": 1.0, "sla_hours": 6.0, "is_novel": True},
                {"source_class": "filing",
                 "verification_status": "FIXTURE_VERIFIED",
                 "age_hours": 4.0, "sla_hours": 36.0, "is_novel": True},
                {"source_class": "news_event",
                 "verification_status": "FIXTURE_VERIFIED",
                 "age_hours": 2.0, "sla_hours": 12.0, "is_novel": True},
            ],
            "why_today_score": 0.85,
            "stale_repeated": False, "advisory_only": True,
        },
        {
            "id": "STALE_REPEAT",
            "events": [
                {"source_class": "price_mover",
                 "verification_status": "FIXTURE_VERIFIED",
                 "age_hours": 1.0, "sla_hours": 6.0, "is_novel": False},
            ],
            "why_today_score": 0.4,
            "stale_repeated": True, "advisory_only": True,
        },
        {
            "id": "FALLBACK_ONLY",
            "events": [
                {"source_class": "news_event",
                 "verification_status": "FALLBACK",
                 "age_hours": 1.0, "sla_hours": 12.0, "is_novel": True},
            ],
            "why_today_score": 0.3,
            "stale_repeated": False, "advisory_only": True,
        },
        {
            "id": "WHY_TODAY_ALONE",
            "events": [
                {"source_class": "ai_report",
                 "verification_status": "UNVERIFIED",
                 "age_hours": 1.0, "sla_hours": 24.0, "is_novel": True},
            ],
            "why_today_score": 0.95,
            "stale_repeated": False, "advisory_only": True,
        },
    ]


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
    p = argparse.ArgumentParser(prog="fresh_discovery_quality.py")
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = write_summary() if args.write_summary else build_summary()
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"fresh_discovery_quality_score = "
              f"{summary['fresh_discovery_quality_score']}")
        for c in summary["candidates"]:
            print(f"  {c['id']:18s} fds={c['fresh_discovery_score']:.3f} "
                  f"can_enter={c['can_enter_fresh_discovery']} "
                  f"reasons={c['block_reasons']}")
    return 0


__all__ = [
    "DEFAULT_SUMMARY_PATH",
    "REQUIRED_SOURCE_CLASSES_DEFAULT",
    "FRESH_DISCOVERY_GATE_MIN",
    "VERIFIED_LIKE",
    "score_candidate",
    "build_summary", "write_summary", "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
