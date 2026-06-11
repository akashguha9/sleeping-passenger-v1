"""Dark-pattern chain detector — the eureka move.

The reflection's deepest claim: fraud-like harm is sometimes a SYSTEM
DESIGN, not one illegal act. Every step is individually defensible —
easy signup, recurring billing, written-form cancellation, weekly
processing, continued billing, a small fee, interest, collections — but
the unbroken journey is extraction.

So the detector does what no single-layer scorer can: it reconstructs
the customer journey as an ordered chain and scores the LONGEST
CONSECUTIVE RUN superlinearly. Three scattered frictions are noise;
three CONSECUTIVE stages are a pipeline. A complete chain is a machine.

    Chain Score =
        (longest_consecutive_run / total_stages)²   -- superlinear --
        × mean stage severity
        × evidence reliability factor
        × vulnerable-user multiplier

Each stage cites its evidence. No stage, no link — the chain cannot be
asserted, only observed. ADVISORY_ONLY; patterns, not intent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.consent.evidence import (
    EvidenceHit,
    evidence_intensity,
    extract_evidence,
)
from src.utils.math_utils import clamp01, clip

# The canonical extraction journey, in order. Each stage maps to the
# evidence categories that prove it, plus an optional structural check
# on the candidate's capability matrix.
CHAIN_STAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("easy_signup_recurring_billing", ("enforcement_speed", "lock_in")),
    ("hard_pause_or_cancel", ("cannot_cancel", "pause_friction",
                              "email_only_relief")),
    ("slow_processing", ("processing_delay", "bot_only_support")),
    ("continued_billing_during_relief", ("charged_after_cancellation",
                                          "processing_delay")),
    ("fees_and_interest", ("hidden_fees",)),
    ("collections_escalation", ("hidden_fees", "enforcement_speed")),
)

# Stage detection threshold on evidence intensity.
STAGE_PRESENT_THRESHOLD = 0.25
VULNERABLE_MULTIPLIER = 1.25

CHAIN_SEVERE_THRESHOLD = 6.0


@dataclass(slots=True)
class ChainStage:
    """One observed (or absent) stage of the extraction journey."""

    stage: str
    present: bool
    intensity: float
    evidence_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class DarkPatternChainReport:
    """The reconstructed journey and its superlinear verdict."""

    score: float
    label: str
    stages_present: int
    total_stages: int
    longest_consecutive_run: int
    chain_complete: bool
    mean_stage_severity: float
    reliability_factor: float
    vulnerable_multiplier: float
    stages: list[ChainStage] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _stage_evidence(
    categories: tuple[str, ...],
    hits: dict[str, EvidenceHit],
    text_count: int,
) -> tuple[float, list[str]]:
    intensity = 0.0
    terms: list[str] = []
    for category in categories:
        hit = hits[category]
        value = evidence_intensity(hit, text_count)
        if value > intensity:
            intensity = value
        for term in hit.matched_terms:
            if term not in terms:
                terms.append(term)
    return intensity, terms


def detect_dark_pattern_chain(
    *,
    complaint_texts: list[str],
    reliability_factor: float = 1.0,
    vulnerable_segment: bool = False,
    collection_capabilities: dict[str, bool] | None = None,
    hits: dict[str, EvidenceHit] | None = None,
) -> DarkPatternChainReport:
    """Reconstruct the extraction journey from evidence (0–10 score).

    ``reliability_factor`` in [0, 1] comes from the evidence-reliability
    model: an unreliable chain reads as a hypothesis, not a finding.
    """
    texts = list(complaint_texts or [])
    evidence = hits if hits is not None else extract_evidence(texts)

    stages: list[ChainStage] = []
    for stage_name, categories in CHAIN_STAGES:
        intensity, terms = _stage_evidence(categories, evidence, len(texts))
        # Stage 1 can also be established structurally: a full digital
        # collection surface IS the easy-signup/recurring-billing stage.
        if stage_name == "easy_signup_recurring_billing" and collection_capabilities:
            structural = sum(
                1 for v in collection_capabilities.values() if v
            ) / max(len(collection_capabilities), 1)
            if structural > intensity:
                intensity = clamp01(structural)
                terms = sorted(
                    k for k, v in collection_capabilities.items() if v
                )
        stages.append(
            ChainStage(
                stage=stage_name,
                present=intensity >= STAGE_PRESENT_THRESHOLD,
                intensity=intensity,
                evidence_terms=terms,
            )
        )

    present_flags = [s.present for s in stages]
    stages_present = sum(present_flags)
    longest_run = 0
    current = 0
    for flag in present_flags:
        current = current + 1 if flag else 0
        longest_run = max(longest_run, current)

    total = len(stages)
    chain_complete = stages_present == total
    present_intensities = [s.intensity for s in stages if s.present]
    mean_severity = (
        sum(present_intensities) / len(present_intensities)
        if present_intensities
        else 0.0
    )

    # Superlinear in consecutive run length: the run fraction is squared
    # so 3 consecutive stages of 6 (0.25) score far below 6 of 6 (1.0),
    # while scattered single frictions barely register.
    run_fraction = longest_run / total
    chain01 = clamp01(
        (run_fraction ** 2)
        * mean_severity
        * clamp01(reliability_factor)
        * (VULNERABLE_MULTIPLIER if vulnerable_segment else 1.0)
        * 1.6  # scale so a complete, severe, reliable chain reaches ~10
    )
    score = clip(chain01 * 10.0, 0.0, 10.0)
    label = (
        "complete_chain" if chain_complete and score >= CHAIN_SEVERE_THRESHOLD
        else ("partial_chain" if longest_run >= 3 else
              ("fragments" if stages_present > 0 else "none"))
    )

    rationale = [
        f"{stages_present}/{total} journey stages evidenced; longest "
        f"consecutive run {longest_run} (superlinear: run² × severity)",
    ]
    if chain_complete:
        rationale.append(
            "COMPLETE extraction journey observed: every stage from easy "
            "signup to collections has evidence — each step individually "
            "defensible, the unbroken chain is the system design"
        )
    elif longest_run >= 3:
        rationale.append(
            "consecutive partial chain — frictions are connected, not "
            "scattered"
        )
    if reliability_factor < 0.5 and stages_present >= 3:
        rationale.append(
            f"reliability factor {reliability_factor:.2f} caps the chain at "
            "a hypothesis, not a finding"
        )
    if vulnerable_segment and score > 0:
        rationale.append(
            f"vulnerable-user multiplier ×{VULNERABLE_MULTIPLIER} applied"
        )
    rationale.append("pattern detection only — no inference of intent")

    return DarkPatternChainReport(
        score=score,
        label=label,
        stages_present=stages_present,
        total_stages=total,
        longest_consecutive_run=longest_run,
        chain_complete=chain_complete,
        mean_stage_severity=mean_severity,
        reliability_factor=clamp01(reliability_factor),
        vulnerable_multiplier=(
            VULNERABLE_MULTIPLIER if vulnerable_segment else 1.0
        ),
        stages=stages,
        rationale=rationale,
    )
