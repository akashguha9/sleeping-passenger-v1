"""Backhand Defence Engine: do not confirm — attack.

The model's backhand becomes strong by repeatedly receiving the strongest
bear-case attack. A thesis is rewarded only after surviving its hostile
short-seller case; an unresolved existential attack is fatal regardless
of how attractive the bull case looks.

    Backhand_Defence_Score = Bear_Case_Survival + Weak_Side_Improvement
                             + Evidence_Strength − Fragility
                             − Unresolved_Bear_Cases
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01, clip
from src.utils.validation_utils import normalized_score


@dataclass(slots=True)
class BearAttack:
    """One bear-case attack and its defence."""

    attack: str
    severity: float
    existential: bool
    defence_response: str
    defence_strength: float
    resolved: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class BackhandAssessment:
    """Adversarial-survival verdict for one thesis."""

    bull_thesis: str
    strongest_bear_attack: str
    weakest_point: str
    bear_case_survival: float
    unresolved_bear_cases: list[str] = field(default_factory=list)
    existential_bear_unresolved: bool = False
    weak_side_improvement: float = 0.0
    evidence_strength: float = 0.0
    fragility: float = 0.0
    backhand_defence_score: float = 0.0
    attacks: list[BearAttack] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def assess_backhand_defence(
    *,
    bull_thesis: str,
    bear_attacks: list[dict[str, object]] | None = None,
    weak_side_improvement: float = 0.0,
    evidence_strength: float = 0.0,
    fragility: float = 0.0,
) -> BackhandAssessment:
    """Attack the thesis with every supplied bear case.

    Each attack: {"attack", "severity" 0-1, "existential" bool,
    "defence_response" str, "defence_strength" 0-1}. An attack is
    resolved when the defence outweighs the severity. A thesis with no
    attacks supplied scores zero survival — an untested backhand has no
    record (no confirmation credit for never being attacked).
    """
    attacks: list[BearAttack] = []
    for raw in bear_attacks or []:
        severity = normalized_score(raw.get("severity", 0.0))
        defence = normalized_score(raw.get("defence_strength", 0.0))
        attacks.append(
            BearAttack(
                attack=str(raw.get("attack", "unnamed attack")),
                severity=severity,
                existential=bool(raw.get("existential", False)),
                defence_response=str(raw.get("defence_response", "")),
                defence_strength=defence,
                resolved=defence >= severity,
            )
        )

    rationale: list[str] = []
    if not attacks:
        return BackhandAssessment(
            bull_thesis=str(bull_thesis),
            strongest_bear_attack="none supplied",
            weakest_point="untested — the thesis has never been attacked",
            bear_case_survival=0.0,
            weak_side_improvement=normalized_score(weak_side_improvement),
            evidence_strength=normalized_score(evidence_strength),
            fragility=normalized_score(fragility),
            backhand_defence_score=0.0,
            rationale=[
                "no bear attacks supplied — an untested backhand earns no "
                "survival credit; run the hostile short-seller case first"
            ],
        )

    strongest = max(attacks, key=lambda a: a.severity)
    unresolved = [a.attack for a in attacks if not a.resolved]
    existential_unresolved = any(
        a.existential and not a.resolved for a in attacks
    )
    weakest = (
        max(
            (a for a in attacks if not a.resolved),
            key=lambda a: a.severity,
            default=strongest,
        ).attack
        if unresolved
        else f"{strongest.attack} (defended)"
    )

    # Severity-weighted survival.
    total_severity = sum(a.severity for a in attacks) or 1e-9
    survival = clamp01(
        sum(a.severity * min(a.defence_strength / max(a.severity, 1e-9), 1.0)
            for a in attacks)
        / total_severity
    )

    improvement = normalized_score(weak_side_improvement)
    evidence = normalized_score(evidence_strength)
    frag = normalized_score(fragility)
    score = clip(
        (survival + 0.5 * improvement + 0.5 * evidence
         - 0.5 * frag - 0.4 * len(unresolved) / len(attacks))
        / 2.0,
        0.0,
        1.0,
    ) * 10.0
    if existential_unresolved:
        score = min(score, 2.0)
        rationale.append(
            "EXISTENTIAL bear case unresolved — survival capped; no score "
            "can override an unresolved existential attack"
        )

    rationale.append(
        f"{len(attacks) - len(unresolved)}/{len(attacks)} attacks defended; "
        f"severity-weighted survival {survival:.2f}; strongest attack: "
        f"{strongest.attack}"
    )
    if improvement > 0.5:
        rationale.append("weak side is demonstrably improving — pressure absorbed")

    return BackhandAssessment(
        bull_thesis=str(bull_thesis),
        strongest_bear_attack=strongest.attack,
        weakest_point=weakest,
        bear_case_survival=survival,
        unresolved_bear_cases=unresolved,
        existential_bear_unresolved=existential_unresolved,
        weak_side_improvement=improvement,
        evidence_strength=evidence,
        fragility=frag,
        backhand_defence_score=score,
        attacks=attacks,
        rationale=rationale,
    )
