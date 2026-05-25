"""Catalyst-specific candidate memory decay + anti-staleness summaries.

Integrated Sprint — Part 6 (Kanté defensive batch 2).  Layered on top of
the existing :mod:`scripts.candidate_memory_decay` (which carries the
single-lambda decay formula); this module adds:

* per-catalyst-type half-lives (λ_type),
* stale-repeat penalty,
* quarantine after 4+ repeats with no new verified catalyst,
* honest reset rule (only verified or fixture-verified catalysts reset
  decay; fallback/mock/AI-only repeats may not).

Writes two summary artifacts the release gate consumes:

  ``runtime/release/anti_staleness_summary.json``
  ``runtime/release/candidate_memory_decay_summary.json``

Named with a ``_v2`` suffix so the existing single-lambda module remains
the in-pipeline source of truth and the older anti-staleness builder keeps
working unchanged.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover
    import advisory_contract as _contract  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
ANTI_STALENESS_SUMMARY_PATH = (
    REPO_ROOT / "runtime" / "release" / "anti_staleness_summary.json"
)
MEMORY_DECAY_SUMMARY_PATH = (
    REPO_ROOT / "runtime" / "release" / "candidate_memory_decay_summary.json"
)

CATALYST_LAMBDA: dict[str, float] = {
    "earnings": 0.35,
    "guidance": 0.35,
    "filing": 0.20,
    "material_event": 0.20,
    "news": 0.45,
    "narrative": 0.45,
    "macro": 0.15,
    "geopolitical": 0.15,
    "price_momentum": 0.50,
    "ai_report_only": 0.60,
}

# Verifications that reset decay.  Fallback/mock/unverified do NOT.
RESET_VERIFICATIONS: frozenset[str] = frozenset({
    "LIVE_VERIFIED", "VERIFIED", "FIXTURE_VERIFIED",
})

QUARANTINE_REPEAT_THRESHOLD = 4
QUARANTINE_WINDOW_DAYS = 30

# Sprint 3 — reset_strength by verification class.  This drives how much
# of the candidate's accumulated decay age is wiped when a new catalyst
# arrives:
#
#   LIVE_VERIFIED_CATALYST  -> 1.0  (full reset)
#   FIXTURE_VERIFIED        -> 0.7  (fixture reset; lower confidence)
#   UNVERIFIED              -> 0.4  (partial reset only if schema valid + fresh)
#   FALLBACK / MOCK         -> 0.0  (never resets)
#
# Stale-quarantine release additionally requires WHY_TODAY >= 0.65 AND
# reset_strength >= 0.7 (so an UNVERIFIED catalyst alone can NOT lift a
# candidate out of quarantine).
RESET_STRENGTH: dict[str, float] = {
    "LIVE_VERIFIED": 1.0,
    "VERIFIED": 1.0,
    "FIXTURE_VERIFIED": 0.7,
    "UNVERIFIED": 0.4,
    "STALE": 0.0,
    "FALLBACK": 0.0,
    "MOCK": 0.0,
}
STALE_QUARANTINE_RELEASE_MIN_RESET = 0.7
STALE_QUARANTINE_RELEASE_MIN_WHY_TODAY = 0.65


def reset_strength_for(verification_status: str,
                       *, schema_valid: bool = True,
                       fresh_within_sla: bool = True) -> float:
    """Return the per-catalyst reset strength.

    UNVERIFIED only earns partial reset if BOTH schema_valid AND
    fresh_within_sla are true; otherwise it drops to 0.
    """
    key = (verification_status or "").upper()
    base = RESET_STRENGTH.get(key, 0.0)
    if key == "UNVERIFIED" and not (schema_valid and fresh_within_sla):
        return 0.0
    return base


def apply_decay_reset(old_decay_age_days: float,
                      *, reset_strength: float) -> float:
    """``new_age = old_age * (1 - reset_strength)``, clamped to >= 0."""
    rs = max(0.0, min(1.0, float(reset_strength)))
    return max(0.0, float(old_decay_age_days) * (1.0 - rs))


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp01(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


def base_decay(catalyst_type: str, days_since_last_fresh: float) -> float:
    """``exp(-λ_type * d)``."""
    lam = CATALYST_LAMBDA.get(str(catalyst_type).lower(), 0.40)
    d = max(0.0, float(days_since_last_fresh))
    return round(math.exp(-lam * d), 6)


def stale_repeat_penalty(repeat_count_30d: int) -> float:
    """``min(0.50, 0.10 * repeat_count_30d)`` — penalty in [0, 0.5]."""
    n = max(0, int(repeat_count_30d))
    return round(min(0.50, 0.10 * n), 4)


def evaluate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Decay + penalty + quarantine decision for one candidate.

    ``candidate`` schema:
      * id                       — string
      * catalyst_type            — one of CATALYST_LAMBDA keys
      * days_since_last_fresh    — float
      * raw_score                — base score in [0,1]
      * repeat_count_30d         — int
      * last_catalyst_verification — "VERIFIED" | "FIXTURE_VERIFIED" | other
    """
    raw = _clamp01(float(candidate.get("raw_score") or 0.0))
    catalyst = str(candidate.get("catalyst_type") or "narrative")
    days = float(candidate.get("days_since_last_fresh") or 0.0)
    repeats = int(candidate.get("repeat_count_30d") or 0)
    verification = str(candidate.get("last_catalyst_verification") or "")
    decay = base_decay(catalyst, days)
    penalty = stale_repeat_penalty(repeats)
    adjusted = round(raw * decay * (1.0 - penalty), 6)

    has_new_verified = verification.upper() in RESET_VERIFICATIONS
    schema_valid = bool(candidate.get("schema_valid", True))
    fresh_within_sla = bool(candidate.get("fresh_within_sla", True))
    rs = reset_strength_for(
        verification,
        schema_valid=schema_valid,
        fresh_within_sla=fresh_within_sla,
    )
    new_decay_age_days = round(
        apply_decay_reset(days, reset_strength=rs), 6
    )
    why_today_score = float(candidate.get("why_today_score") or 0.0)

    # Sprint 3 quarantine logic: once repeats >= threshold, exit requires
    # BOTH a verified catalyst (reset_strength >= 0.7) AND WHY_TODAY ≥ 0.65.
    # A LIVE_VERIFIED catalyst with weak WHY_TODAY is NOT enough on its own.
    if repeats >= QUARANTINE_REPEAT_THRESHOLD:
        can_exit_quarantine = (
            has_new_verified
            and rs >= STALE_QUARANTINE_RELEASE_MIN_RESET
            and why_today_score >= STALE_QUARANTINE_RELEASE_MIN_WHY_TODAY
        )
        quarantined = not can_exit_quarantine
        release_from_quarantine = can_exit_quarantine
    else:
        quarantined = False
        release_from_quarantine = False

    downgrade_reasons: list[str] = []
    if quarantined:
        downgrade_reasons.append("STALE_REPEAT_QUARANTINE")
    if not has_new_verified and repeats >= 1:
        downgrade_reasons.append("NO_NEW_VERIFIED_CATALYST")
    if rs <= 0 and verification.upper() in {"FALLBACK", "MOCK"}:
        downgrade_reasons.append("FALLBACK_MOCK_CANNOT_RESET")

    state = "STALE_QUARANTINE" if quarantined else "ACTIVE"
    may_promote = not quarantined and has_new_verified

    return {
        "id": candidate.get("id"),
        "catalyst_type": catalyst,
        "days_since_last_fresh": days,
        "repeat_count_30d": repeats,
        "last_catalyst_verification": verification,
        "raw_score": raw,
        "base_decay": decay,
        "stale_repeat_penalty": penalty,
        "memory_adjusted_score": adjusted,
        "state": state,
        "quarantined": quarantined,
        "may_promote": may_promote,
        "downgrade_reasons": downgrade_reasons,
        "reset_strength": round(rs, 6),
        "new_decay_age_days": new_decay_age_days,
        "schema_valid": schema_valid,
        "fresh_within_sla": fresh_within_sla,
        "why_today_score": round(why_today_score, 6),
        "released_from_quarantine": bool(release_from_quarantine),
    }


def _formula_indicator_scores(
    candidates: list[dict[str, Any]]
) -> dict[str, bool]:
    """Compute the booleans both summary formulas score against.

    Each is an actual property of the evaluator (proved by the per-candidate
    results), not a wishlist switch.
    """
    by_id = {c["id"]: c for c in candidates}

    # Decay differs by catalyst — the same days/score combo gives different
    # adjusted scores for different catalyst types.
    decay_differs = (
        base_decay("earnings", 3) != base_decay("ai_report_only", 3)
    )

    # Quarantine — at least one quarantined candidate when 4+ repeats and no
    # new verified catalyst.
    quarantine_works = any(c["quarantined"] for c in candidates)

    # Fallback cannot reset — a candidate with verification "FALLBACK" must
    # not have may_promote=True, even at d=0.
    fallback_cannot_reset = all(
        not c["may_promote"]
        for c in candidates
        if c["last_catalyst_verification"].upper() in {"FALLBACK", "MOCK", "UNVERIFIED"}
    )

    # New verified catalyst resets decay — a candidate with verification
    # "VERIFIED" or "FIXTURE_VERIFIED" must have may_promote=True (unless
    # also quarantined).
    new_verified_resets = any(
        c["may_promote"]
        for c in candidates
        if c["last_catalyst_verification"].upper() in RESET_VERIFICATIONS
        and not c["quarantined"]
    )

    # Downgrade reasons visible — at least one rejected candidate carries an
    # explicit downgrade_reasons entry.
    downgrade_visible = any(
        c["downgrade_reasons"] for c in candidates if not c["may_promote"]
    )

    # Stale repeat penalty engages — at least one candidate with repeats > 0
    # has a non-zero stale_repeat_penalty.
    repeat_penalty_works = any(
        c["stale_repeat_penalty"] > 0 for c in candidates
        if c["repeat_count_30d"] > 0
    )

    return {
        "exp_decay_by_type_works": decay_differs,
        "repeat_penalty_works": repeat_penalty_works,
        "quarantine_works": quarantine_works,
        "reset_rules_safe": (fallback_cannot_reset and new_verified_resets),
        "catalyst_specific_half_life_works": decay_differs,
        "fallback_mock_cannot_reset_decay": fallback_cannot_reset,
        "new_verified_catalyst_resets_decay": new_verified_resets,
        "stale_repeat_quarantine_works": quarantine_works,
        "downgrade_reasons_visible": downgrade_visible,
    }


def anti_staleness_score(indicators: dict[str, bool]) -> float:
    raw = (
        0.30 * (1.0 if indicators["stale_repeat_quarantine_works"] else 0.0)
        + 0.25 * (1.0 if indicators["fallback_mock_cannot_reset_decay"] else 0.0)
        + 0.20 * (1.0 if indicators["catalyst_specific_half_life_works"] else 0.0)
        + 0.15 * (1.0 if indicators["new_verified_catalyst_resets_decay"] else 0.0)
        + 0.10 * (1.0 if indicators["downgrade_reasons_visible"] else 0.0)
    )
    return round(10.0 * _clamp01(raw), 4)


def candidate_memory_decay_score(indicators: dict[str, bool]) -> float:
    raw = (
        0.35 * (1.0 if indicators["exp_decay_by_type_works"] else 0.0)
        + 0.25 * (1.0 if indicators["repeat_penalty_works"] else 0.0)
        + 0.20 * (1.0 if indicators["quarantine_works"] else 0.0)
        + 0.20 * (1.0 if indicators["reset_rules_safe"] else 0.0)
    )
    return round(10.0 * _clamp01(raw), 4)


def _fixture_candidates() -> list[dict[str, Any]]:
    """Deterministic 5-candidate panel covering every code path."""
    return [
        {"id": "VERIFIED_FRESH", "catalyst_type": "filing",
         "days_since_last_fresh": 0.0, "raw_score": 0.85,
         "repeat_count_30d": 0, "last_catalyst_verification": "VERIFIED"},
        {"id": "FIXTURE_FRESH", "catalyst_type": "earnings",
         "days_since_last_fresh": 0.0, "raw_score": 0.80,
         "repeat_count_30d": 0,
         "last_catalyst_verification": "FIXTURE_VERIFIED"},
        {"id": "STALE_AGING", "catalyst_type": "narrative",
         "days_since_last_fresh": 4.0, "raw_score": 0.70,
         "repeat_count_30d": 2, "last_catalyst_verification": "UNVERIFIED"},
        {"id": "REPEAT_QUARANTINE", "catalyst_type": "news",
         "days_since_last_fresh": 6.0, "raw_score": 0.60,
         "repeat_count_30d": 5, "last_catalyst_verification": "UNVERIFIED"},
        {"id": "AI_ONLY_DECAYS_FAST", "catalyst_type": "ai_report_only",
         "days_since_last_fresh": 3.0, "raw_score": 0.65,
         "repeat_count_30d": 1, "last_catalyst_verification": "FALLBACK"},
    ]


def build_summaries(
    candidates: Iterable[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compute both summaries from the same per-candidate evaluation."""
    if candidates is None:
        candidates = _fixture_candidates()
    evaluated = [evaluate_candidate(c) for c in candidates]
    indicators = _formula_indicator_scores(evaluated)
    anti = anti_staleness_score(indicators)
    memo = candidate_memory_decay_score(indicators)
    now = _utc_iso()

    anti_summary = {
        "report": "anti_staleness_summary",
        "ok": anti >= 9.5,
        "generated_at_utc": now,
        "candidate_count": len(evaluated),
        "quarantined_count": sum(1 for c in evaluated if c["quarantined"]),
        "candidates": evaluated,
        "indicators": indicators,
        "anti_staleness_score": anti,
        "advisory_only": True,
        **_contract.advisory_safety_stamps(),
    }
    memo_summary = {
        "report": "candidate_memory_decay_summary",
        "ok": memo >= 9.5,
        "generated_at_utc": now,
        "candidate_count": len(evaluated),
        "quarantined_count": sum(1 for c in evaluated if c["quarantined"]),
        "candidates": evaluated,
        "indicators": indicators,
        "candidate_memory_decay_score": memo,
        "advisory_only": True,
        **_contract.advisory_safety_stamps(),
    }
    return anti_summary, memo_summary


def write_summaries(
    *,
    anti_path: Path | None = None,
    memo_path: Path | None = None,
    candidates: Iterable[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    anti, memo = build_summaries(candidates)
    anti_target = anti_path or ANTI_STALENESS_SUMMARY_PATH
    memo_target = memo_path or MEMORY_DECAY_SUMMARY_PATH
    for target, payload in ((anti_target, anti), (memo_target, memo)):
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str),
                       encoding="utf-8")
        tmp.replace(target)
        payload["summary_path"] = str(target)
    return anti, memo


def read_summary(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="candidate_memory_decay_v2.py")
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.write_summary:
        anti, memo = write_summaries()
    else:
        anti, memo = build_summaries()
    if args.json:
        print(json.dumps({"anti_staleness": anti, "candidate_memory_decay": memo},
                         indent=2, default=str))
    else:
        print(f"anti_staleness_score           = {anti['anti_staleness_score']}")
        print(f"candidate_memory_decay_score   = "
              f"{memo['candidate_memory_decay_score']}")
        for c in memo["candidates"]:
            print(f"  {c['id']:22s} state={c['state']} "
                  f"decay={c['base_decay']:.3f} "
                  f"penalty={c['stale_repeat_penalty']:.2f} "
                  f"adjusted={c['memory_adjusted_score']:.3f}")
    return 0


__all__ = [
    "CATALYST_LAMBDA", "RESET_VERIFICATIONS",
    "QUARANTINE_REPEAT_THRESHOLD",
    "ANTI_STALENESS_SUMMARY_PATH", "MEMORY_DECAY_SUMMARY_PATH",
    "base_decay", "stale_repeat_penalty",
    "evaluate_candidate",
    "anti_staleness_score", "candidate_memory_decay_score",
    "build_summaries", "write_summaries", "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
