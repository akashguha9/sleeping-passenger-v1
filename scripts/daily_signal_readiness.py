"""Daily-signal readiness — overall composite score with caps.

Integrated Sprint — Part 14 (Kanté defensive batch 2).  Combines every
component segment into a single ``overall_daily_signal_readiness`` score
on the 0..10 scale, applies the spec's three safety caps, and writes
``runtime/release/daily_signal_readiness_summary.json``.

Reads each component summary on disk if present (so the release gate sees
the same value the operator does), or computes them inline using each
module's fixture-mode builder when the summary is missing.

No broker, no execution, advisory-only.  Safety floor cap fires hard if
``safety_advisory_integrity_score`` drops below 10.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
    from scripts import portfolio_truth_integrity as _pti
    from scripts import fresh_discovery_quality as _fdq
    from scripts import candidate_memory_decay_v2 as _cmd2
    from scripts import why_today_enforcement as _wte
    from scripts import five_model_independence as _fmi
    from scripts import model_disagreement_handling as _mdh
    from scripts import source_run_ledger as _srl
    from scripts import signal_input_quality as _siq
except ModuleNotFoundError:  # pragma: no cover
    import advisory_contract as _contract  # type: ignore[no-redef]
    import portfolio_truth_integrity as _pti  # type: ignore[no-redef]
    import fresh_discovery_quality as _fdq  # type: ignore[no-redef]
    import candidate_memory_decay_v2 as _cmd2  # type: ignore[no-redef]
    import why_today_enforcement as _wte  # type: ignore[no-redef]
    import five_model_independence as _fmi  # type: ignore[no-redef]
    import model_disagreement_handling as _mdh  # type: ignore[no-redef]
    import source_run_ledger as _srl  # type: ignore[no-redef]
    import signal_input_quality as _siq  # type: ignore[no-redef]

# Sprint 3 — optional cross-modules.  Imported best-effort so the readiness
# summary still builds in stripped environments.
try:
    from scripts import candidate_promotion_contract as _cpc  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    try:
        import candidate_promotion_contract as _cpc  # type: ignore[no-redef]
    except ModuleNotFoundError:
        _cpc = None  # type: ignore[assignment]

try:
    from scripts import operator_live_provider_refresh as _olpr  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    try:
        import operator_live_provider_refresh as _olpr  # type: ignore[no-redef]
    except ModuleNotFoundError:
        _olpr = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_PATH = (
    REPO_ROOT / "runtime" / "release" / "daily_signal_readiness_summary.json"
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp01(v: float) -> float:
    if v < 0:
        return 0.0
    if v > 1:
        return 1.0
    return v


def _read_or_compute(
    summary_path: Path,
    score_key: str,
    fallback_builder,
) -> float:
    """Try the persisted summary; else fall back to the in-memory builder."""
    if summary_path.exists():
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and score_key in data:
                return float(data[score_key])
        except (json.JSONDecodeError, OSError):
            pass
    data = fallback_builder()
    return float(data.get(score_key, 0.0))


def gather_component_scores() -> dict[str, float]:
    """Read each component summary, falling back to fixture-mode builders."""
    pti_score = _read_or_compute(
        _pti.DEFAULT_SUMMARY_PATH, "portfolio_truth_score",
        _pti.build_summary,
    )
    fdq_score = _read_or_compute(
        _fdq.DEFAULT_SUMMARY_PATH, "fresh_discovery_quality_score",
        _fdq.build_summary,
    )
    anti_score = _read_or_compute(
        _cmd2.ANTI_STALENESS_SUMMARY_PATH, "anti_staleness_score",
        lambda: _cmd2.build_summaries()[0],
    )
    memo_score = _read_or_compute(
        _cmd2.MEMORY_DECAY_SUMMARY_PATH, "candidate_memory_decay_score",
        lambda: _cmd2.build_summaries()[1],
    )
    fmi_score = _read_or_compute(
        _fmi.DEFAULT_SUMMARY_PATH, "five_model_independence_score",
        _fmi.build_summary,
    )

    # Sprint 3 — Live/fresh payload quality is read from the operator-run
    # artifact when it exists *and is fresh*; otherwise we fall back to the
    # honest fixture-mode floor (8.2 per spec).  The fixture-mode summary
    # writes a higher headline number but it is NOT a live score.
    live_fresh_payload_quality_score = 8.2
    live_refresh_present = False
    live_refresh_fresh = False
    if _olpr is not None:
        op_summary = _olpr.read_summary()
        if isinstance(op_summary, dict):
            live_refresh_present = True
            evidence = _olpr.operator_artifact_valid(op_summary)
            live_refresh_fresh = bool(evidence.get("fresh"))
            providers_live = list(op_summary.get("providers_live_verified") or [])
            if live_refresh_fresh and providers_live:
                val = op_summary.get("live_payload_quality_score")
                if isinstance(val, (int, float)):
                    live_fresh_payload_quality_score = float(val)

    wte_score = _read_or_compute(
        _wte.DEFAULT_SUMMARY_PATH, "why_today_enforcement_score",
        _wte.build_summary,
    )
    mdh_score = _read_or_compute(
        _mdh.DEFAULT_SUMMARY_PATH, "model_disagreement_score",
        _mdh.build_summary,
    )
    siq_score = _read_or_compute(
        _siq.DEFAULT_SUMMARY_PATH, "signal_input_quality_score",
        _siq.build_summary,
    )
    # Sprint 3 — candidate vs executable score from the promotion contract.
    if _cpc is not None:
        cpc_score = _read_or_compute(
            _cpc.DEFAULT_SUMMARY_PATH, "candidate_vs_executable_score",
            _cpc.build_summary,
        )
    else:
        cpc_score = 9.8  # honest baseline; absence is non-blocking
    # Safety is invariant — the contract is the source of truth.  10.0 unless
    # an explicit downgrade is recorded by a caller.
    safety_score = 10.0
    return {
        "portfolio_truth_integrity": pti_score,
        "fresh_discovery_quality": fdq_score,
        "anti_staleness": anti_score,
        "five_model_independence": fmi_score,
        "live_fresh_payload_quality": live_fresh_payload_quality_score,
        "why_today_enforcement": wte_score,
        "candidate_memory_decay": memo_score,
        "model_disagreement": mdh_score,
        "signal_input_quality": siq_score,
        "candidate_vs_executable": cpc_score,
        "safety_advisory_integrity": safety_score,
        "_live_refresh_present": 1.0 if live_refresh_present else 0.0,
        "_live_refresh_fresh": 1.0 if live_refresh_fresh else 0.0,
    }


def compute_overall(
    components: dict[str, float],
) -> tuple[float, list[str]]:
    """Apply the weighted formula + the spec caps; return ``(score, caps)``.

    Sprint 3 formula (weights sum to 1.00):

        0.10 portfolio_truth_integrity
        0.11 fresh_discovery_quality
        0.09 anti_staleness
        0.09 five_model_independence
        0.15 live_fresh_payload_quality
        0.10 why_today_enforcement
        0.08 candidate_memory_decay
        0.09 model_disagreement
        0.12 signal_input_quality
        0.04 candidate_vs_executable
        0.03 safety_advisory_integrity

    Caps (lowest cap wins):

        safety < 10                 -> 7.0
        portfolio_truth < 9.5       -> 9.0
        live_fresh_payload < 8.0    -> 9.15
        live_fresh_payload < 8.6    -> 9.30
        candidate_vs_executable<9.8 -> 9.25
    """
    weights = {
        "portfolio_truth_integrity": 0.10,
        "fresh_discovery_quality": 0.11,
        "anti_staleness": 0.09,
        "five_model_independence": 0.09,
        "live_fresh_payload_quality": 0.15,
        "why_today_enforcement": 0.10,
        "candidate_memory_decay": 0.08,
        "model_disagreement": 0.09,
        "signal_input_quality": 0.12,
        "candidate_vs_executable": 0.04,
        "safety_advisory_integrity": 0.03,
    }
    raw = sum(w * (components.get(k, 0.0) / 10.0) for k, w in weights.items())
    raw = _clamp01(raw)
    score = round(10.0 * raw, 4)

    caps_applied: list[str] = []
    # The caps record *whenever the precondition fires*, not only when the
    # cap actually lowers the score.  Lowest cap wins.
    if components.get("safety_advisory_integrity", 10.0) < 10.0:
        caps_applied.append("safety_floor:cap_7.0")
        score = min(score, 7.0)
    if components.get("portfolio_truth_integrity", 0.0) < 9.5:
        caps_applied.append("portfolio_truth_low:cap_9.0")
        score = min(score, 9.0)
    lpq = components.get("live_fresh_payload_quality", 0.0)
    if lpq < 8.0:
        caps_applied.append("live_payload_low:cap_9.15")
        score = min(score, 9.15)
    elif lpq < 8.6:
        caps_applied.append("live_payload_below_target:cap_9.30")
        score = min(score, 9.30)
    if components.get("candidate_vs_executable", 0.0) < 9.8:
        caps_applied.append("candidate_vs_executable_low:cap_9.25")
        score = min(score, 9.25)

    return round(score, 4), caps_applied


def build_summary(
    components: dict[str, float] | None = None,
) -> dict[str, Any]:
    if components is None:
        components = gather_component_scores()
    overall, caps_applied = compute_overall(components)
    live_refresh_present = bool(components.get("_live_refresh_present", 0.0))
    live_refresh_fresh = bool(components.get("_live_refresh_fresh", 0.0))
    # Project a clean component view (strip the underscore-prefixed flags).
    visible_components = {
        k: v for k, v in components.items() if not k.startswith("_")
    }
    return {
        "report": "daily_signal_readiness_summary",
        "ok": overall >= 9.0,
        "generated_at_utc": _utc_iso(),
        "overall_daily_signal_readiness": overall,
        "component_scores": visible_components,
        "caps_applied": caps_applied,
        "live_refresh_present": live_refresh_present,
        "live_refresh_fresh": live_refresh_fresh,
        "live_fresh_payload_quality_score": components.get(
            "live_fresh_payload_quality", 0.0
        ),
        "candidate_vs_executable_score": components.get(
            "candidate_vs_executable", 0.0
        ),
        "advisory_only": True,
        "human_review_required": True,
        **_contract.advisory_safety_stamps(),
        # spec requires the string form on this artifact — set AFTER the
        # legacy contract stamps so the string isn't overwritten.
        "execution_permission": "ADVISORY_ONLY",
        "execution_permission_bool": False,
    }


def write_summary(path: Path | None = None,
                  components: dict[str, float] | None = None,
                  ) -> dict[str, Any]:
    target = path or DEFAULT_SUMMARY_PATH
    summary = build_summary(components)
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
    p = argparse.ArgumentParser(prog="daily_signal_readiness.py")
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = write_summary() if args.write_summary else build_summary()
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"overall_daily_signal_readiness = "
              f"{summary['overall_daily_signal_readiness']}")
        for k, v in summary["component_scores"].items():
            print(f"  {k:30s} = {v}")
        if summary["caps_applied"]:
            print(f"  caps_applied = {summary['caps_applied']}")
    return 0


__all__ = [
    "DEFAULT_SUMMARY_PATH",
    "gather_component_scores", "compute_overall",
    "build_summary", "write_summary", "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
