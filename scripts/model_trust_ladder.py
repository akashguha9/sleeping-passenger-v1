"""Model trust ladder — the model stops itself from overclaiming (Pass 6).

Trust levels::

    L0_RESEARCH_ONLY          nothing validated
    L1_SYNTHETIC_VALIDATED    known-answer tests green
    L2_PAPER_TRACKING_STARTED shadow/paper observations accumulating
    L3_MINIMUM_OOS_SAMPLE     ≥30 real out-of-sample outcomes
    L4_CALIBRATED_OOS         ≥100 real OOS outcomes AND acceptable ECE
    L5_INDEPENDENTLY_REVIEWED L4 + formal independent review

Hard caps (test-pinned; arguing with them is not implemented):

    real_oos < 30                  → max L2
    real_oos < 100                 → max L3
    ECE missing or > 0.10          → max L3
    unresolved temporal violations → max L3
    red-team failure               → max L2
    no independent review          → max L4
    execution_ready                → ALWAYS False, at every level

The ladder is wired into the readiness gate and writes
``reports/model_trust_ladder_<timestamp>.md``.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

LEVELS = (
    "L0_RESEARCH_ONLY",
    "L1_SYNTHETIC_VALIDATED",
    "L2_PAPER_TRACKING_STARTED",
    "L3_MINIMUM_OOS_SAMPLE",
    "L4_CALIBRATED_OOS",
    "L5_INDEPENDENTLY_REVIEWED",
)
ECE_ACCEPTABLE = 0.10
MIN_OOS_L3 = 30
MIN_OOS_L4 = 100


@dataclasses.dataclass(frozen=True)
class TrustInputs:
    synthetic_tests_green: bool
    paper_tracking_started: bool
    real_oos_outcomes: int
    ece: float | None  # None = unavailable
    unresolved_temporal_violations: int
    redteam_all_safe: bool
    independent_review: bool


def evaluate(inputs: TrustInputs) -> dict:
    """Compute the trust level + every cap that bound it."""
    caps: list[str] = []
    level = 0
    if inputs.synthetic_tests_green:
        level = 1
    if inputs.paper_tracking_started and level >= 1:
        level = 2
    if inputs.real_oos_outcomes >= MIN_OOS_L3 and level >= 2:
        level = 3
    if (inputs.real_oos_outcomes >= MIN_OOS_L4
            and inputs.ece is not None and inputs.ece <= ECE_ACCEPTABLE
            and level >= 3):
        level = 4
    if inputs.independent_review and level >= 4:
        level = 5

    # Hard caps — applied AFTER aspiration, so the binding cap is recorded.
    if inputs.real_oos_outcomes < MIN_OOS_L3 and level > 2:
        level = 2
        caps.append(f"real OOS outcomes {inputs.real_oos_outcomes} < {MIN_OOS_L3} → max L2")
    if inputs.real_oos_outcomes < MIN_OOS_L4 and level > 3:
        level = 3
        caps.append(f"real OOS outcomes {inputs.real_oos_outcomes} < {MIN_OOS_L4} → max L3")
    if (inputs.ece is None or inputs.ece > ECE_ACCEPTABLE) and level > 3:
        level = 3
        caps.append(f"ECE {'unavailable' if inputs.ece is None else inputs.ece} → max L3")
    if inputs.unresolved_temporal_violations > 0 and level > 3:
        level = 3
        caps.append(f"{inputs.unresolved_temporal_violations} unresolved temporal "
                    "violation(s) → max L3")
    if not inputs.redteam_all_safe and level > 2:
        level = 2
        caps.append("red-team failure → max L2")
    if not inputs.independent_review and level > 4:
        level = 4
        caps.append("no independent review → max L4")

    return {
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "level": LEVELS[level],
        "level_index": level,
        "binding_caps": caps,
        "inputs": dataclasses.asdict(inputs),
        "execution_ready": False,  # permanently, at every level
        "advisory_only": True,
        "human_review_required": True,
        "note": ("Trust describes process maturity, never expected profit. "
                 "Execution readiness is structurally False: this system has "
                 "no execution capability at any trust level."),
    }


def current_inputs() -> TrustInputs:
    """Best-effort live inputs from the repo's own artifacts."""
    redteam_safe = True
    try:
        from scripts.redteam_model import run_cases

        redteam_safe = all(c["ok"] for c in run_cases())
    except Exception:
        redteam_safe = False
    paper_started = False
    try:
        from scripts.signal_tournament import shadow_ledger_path

        paper_started = shadow_ledger_path().exists()
    except Exception:
        pass
    real_oos = 0
    try:
        from scripts.persistence import DB_PATH
        from scripts.outcome_evidence_extractor import extract_from_db

        outcomes = extract_from_db(DB_PATH)  # type: ignore[arg-type]
        real_oos = sum(
            1 for o in outcomes
            if getattr(o, "source_type", "") in ("REAL_MANUAL_TRADE", "PAPER_TRADE")
            and getattr(o, "outcome_label", "") in ("WIN", "LOSS", "BREAKEVEN")
        )
    except Exception:
        real_oos = 0
    return TrustInputs(
        synthetic_tests_green=True,   # asserted by the suite that runs this
        paper_tracking_started=paper_started,
        real_oos_outcomes=real_oos,
        ece=None,                     # honest: no real-OOS ECE exists yet
        unresolved_temporal_violations=0,
        redteam_all_safe=redteam_safe,
        independent_review=False,
    )


def write_report(result: dict, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (_REPO_ROOT / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"model_trust_ladder_{stamp}.md"
    lines = [
        "# Model trust ladder", "",
        f"Generated: {result['generated_utc']}",
        f"**Current level: {result['level']}**",
        f"Execution ready: **{result['execution_ready']}** (permanently)", "",
        "## Binding caps",
    ]
    lines += [f"- {c}" for c in result["binding_caps"]] or ["- none (level earned, not capped)"]
    lines += ["", "## Inputs"]
    for k, v in result["inputs"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", f"> {result['note']}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


if __name__ == "__main__":
    result = evaluate(current_inputs())
    path = write_report(result)
    print(f"trust level: {result['level']} → {path}")
    for cap in result["binding_caps"]:
        print(f"  cap: {cap}")
