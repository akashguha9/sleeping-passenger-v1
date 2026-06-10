"""Model scorecard — segmented, evidence-gated model quality scoring (Pass 4).

Scores the advisory model stack across ten segments. Scores are CAPPED
by evidence tier, not argued up (test-pinned):

    no tests for the segment        → score ≤ 8
    no out-of-sample validation     → score ≤ 9
    no formal independent validation → score ≤ 10 never granted here

A claimed score above its evidence cap is clamped down and the clamp is
recorded — the scorecard cannot be flattered.

    ModelScore_total = Σ_i W_i × Score_i

Output: reports/model_scorecard_<timestamp>.md (gitignored artifact).
Advisory-only: a scorecard about models that themselves never execute.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

SEGMENT_WEIGHTS: dict[str, float] = {
    "data_provenance": 0.12,
    "temporal_integrity": 0.13,
    "feature_quality": 0.10,
    "backtest_quality": 0.14,
    "calibration": 0.10,
    "robustness": 0.10,
    "explainability": 0.09,
    "risk_control": 0.10,
    "human_review_clarity": 0.07,
    "advisory_only_safety": 0.05,
}

CAP_NO_TESTS = 8.0
CAP_NO_OOS = 9.0
CAP_NO_INDEPENDENT = 10.0  # never reachable without formal external validation


class ScorecardError(ValueError):
    """Raised on malformed scorecard input."""


def apply_evidence_caps(
    claimed: float,
    *,
    has_tests: bool,
    has_out_of_sample: bool,
    has_independent_validation: bool,
) -> tuple[float, str | None]:
    """Clamp a claimed score to its evidence tier; returns (score, clamp_note)."""
    if not (0.0 <= claimed <= 10.0):
        raise ScorecardError(f"score {claimed} outside [0,10]")
    if not has_independent_validation and claimed >= CAP_NO_INDEPENDENT:
        return (
            min(claimed, CAP_NO_INDEPENDENT - 0.5),
            "clamped: 10 requires formal independent validation",
        )
    if not has_out_of_sample and claimed > CAP_NO_OOS:
        return min(claimed, CAP_NO_OOS), "clamped to 9: no out-of-sample validation"
    if not has_tests and claimed > CAP_NO_TESTS:
        return min(claimed, CAP_NO_TESTS), "clamped to 8: no tests for this segment"
    return claimed, None


def build_scorecard(segments: list[dict]) -> dict:
    """Build the scorecard from segment entries.

    Each entry: {"segment", "claimed_score", "evidence", "gap", "next_fix",
                 "has_tests", "has_out_of_sample", "has_independent_validation"}.
    All ten segments are mandatory; evidence text is mandatory — a score
    without evidence is an opinion and is refused.
    """
    by_name = {s.get("segment"): s for s in segments}
    missing = set(SEGMENT_WEIGHTS) - set(by_name)
    if missing:
        raise ScorecardError(f"missing segments: {sorted(missing)}")
    rows = []
    total = 0.0
    for name, weight in SEGMENT_WEIGHTS.items():
        entry = by_name[name]
        if not str(entry.get("evidence", "")).strip():
            raise ScorecardError(f"segment {name!r} has no evidence — refused")
        score, clamp = apply_evidence_caps(
            float(entry["claimed_score"]),
            has_tests=bool(entry.get("has_tests")),
            has_out_of_sample=bool(entry.get("has_out_of_sample")),
            has_independent_validation=bool(entry.get("has_independent_validation")),
        )
        total += weight * score
        rows.append({
            "segment": name,
            "weight": weight,
            "score": score,
            "claimed_score": float(entry["claimed_score"]),
            "clamp_note": clamp,
            "evidence": str(entry["evidence"]).strip(),
            "gap": str(entry.get("gap", "")).strip(),
            "next_fix": str(entry.get("next_fix", "")).strip(),
        })
    return {
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "rows": rows,
        "total": round(total, 3),
        "advisory_only": True,
        "human_review_required": True,
        "note": (
            "Scores are evidence-capped (no tests ≤8, no OOS ≤9, no "
            "independent validation <10). The total describes model "
            "process quality, never expected profit."
        ),
    }


def render_scorecard(card: dict) -> str:
    lines = [
        "# Model scorecard",
        "",
        f"Generated: {card['generated_utc']}",
        f"**ModelScore_total = {card['total']} / 10**",
        "",
        f"> {card['note']}",
        "",
        "| Segment | Weight | Score /10 | Evidence | Gap | Next Fix |",
        "| ------- | -----: | --------: | -------- | --- | -------- |",
    ]
    for r in card["rows"]:
        score = f"{r['score']:.1f}"
        if r["clamp_note"]:
            score += f" ({r['clamp_note']})"
        lines.append(
            f"| {r['segment']} | {r['weight']:.2f} | {score} | "
            f"{r['evidence']} | {r['gap'] or '—'} | {r['next_fix'] or '—'} |"
        )
    lines += ["", "Advisory-only. Human review required for every decision.", ""]
    return "\n".join(lines)


def write_scorecard(segments: list[dict], out_dir: Path | None = None) -> Path:
    card = build_scorecard(segments)
    out_dir = out_dir or (_REPO_ROOT / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"model_scorecard_{stamp}.md"
    path.write_text(render_scorecard(card), encoding="utf-8")
    return path
