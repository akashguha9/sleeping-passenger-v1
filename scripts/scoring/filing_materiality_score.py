"""Filing materiality score skeleton.

Returns a value in [0, 1] given a filing form/type. Heuristic only.
"""
from __future__ import annotations

# Higher = more material on average. These are conservative priors.
FORM_PRIORS: dict[str, float] = {
    "8-K": 0.85,
    "10-K": 0.80,
    "10-Q": 0.65,
    "S-1": 0.70,
    "13F": 0.40,
    "13D": 0.75,
    "13G": 0.55,
    "4": 0.45,
    "144": 0.30,
}


def filing_materiality_score(form_type: str | None) -> float:
    if not form_type:
        return 0.0
    return FORM_PRIORS.get(form_type.upper(), 0.25)
