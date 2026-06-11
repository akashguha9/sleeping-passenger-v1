"""Meal-box completeness gate: no fire extinguisher, no trade.

    burger            = core thesis
    fries             = supporting evidence
    coke              = catalyst / timing
    fire_extinguisher = invalidation / risk control

    Meal Box Complete = thesis AND evidence AND catalyst AND invalidation
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# A component must carry at least this many characters of substance.
MIN_COMPONENT_LENGTH = 10

MEAL_BOX_ITEMS: dict[str, str] = {
    "burger": "thesis",
    "fries": "evidence",
    "coke": "catalyst",
    "fire_extinguisher": "invalidation",
}


@dataclass(slots=True)
class MealBoxStatus:
    """Completeness check for one candidate's trade setup."""

    thesis_present: bool
    evidence_present: bool
    catalyst_present: bool
    invalidation_present: bool
    complete: bool
    missing_items: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    text = str(value).strip()
    return len(text) >= MIN_COMPONENT_LENGTH


def check_meal_box(
    *,
    thesis: object = None,
    evidence: object = None,
    catalyst: object = None,
    invalidation: object = None,
) -> MealBoxStatus:
    """Validate the four-item meal box. Strings need >= 10 chars of substance;
    booleans are taken at face value."""
    thesis_ok = _present(thesis)
    evidence_ok = _present(evidence)
    catalyst_ok = _present(catalyst)
    invalidation_ok = _present(invalidation)
    complete = thesis_ok and evidence_ok and catalyst_ok and invalidation_ok

    missing: list[str] = []
    if not thesis_ok:
        missing.append("thesis")
    if not evidence_ok:
        missing.append("evidence")
    if not catalyst_ok:
        missing.append("catalyst")
    if not invalidation_ok:
        missing.append("invalidation")

    reasons: list[str] = []
    if complete:
        reasons.append("MEAL_BOX_COMPLETE")
    else:
        reasons.append("MEAL_BOX_INCOMPLETE")
    if not invalidation_ok:
        reasons.append("NO_FIRE_EXTINGUISHER_NO_TRADE")

    return MealBoxStatus(
        thesis_present=thesis_ok,
        evidence_present=evidence_ok,
        catalyst_present=catalyst_ok,
        invalidation_present=invalidation_ok,
        complete=complete,
        missing_items=missing,
        reason_codes=reasons,
    )
