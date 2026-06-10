"""Blind-test differential: measure the story's contribution directly.

The reflection's blind-test principle ("remove labels, narratives, and
observer bias to test intrinsic value") implemented as a *differential*:
score the signal twice — once as labelled, once with the narrative
attention channel neutralized — and report the gap.

    Narrative Contribution = Labelled Score − Blind Score

Only the story's positive channel (``narrative_velocity`` → neutral 50)
is neutralized.  Casino distortion stays: it is a property of the market
environment that does not vanish because the auditor is blindfolded.

A structural finding this module makes testable: the v2 aggregator's
geometric mean bounds any single loud factor, so a well-behaved signal
shows small narrative contribution by construction.  What matters is the
combination of contribution and survival:

    story_carried          story props it up AND it fails blind (≥25 floor)
    narrative_supported    story helps, but the signal survives without it
    narrative_independent  the story barely moves the score
    narrative_understated  blind scores HIGHER — quiet reality, the
                           residual-utility hunting ground
"""

from __future__ import annotations

from src.alpha import ADVISORY_DISCLAIMER
from src.alpha.opportunity import aggregate_opportunity_score_v2
from src.utils.math_utils import clip

BLIND_CLASSES = (
    "story_carried",
    "narrative_supported",
    "narrative_independent",
    "narrative_understated",
)

_NEUTRALIZED = {"narrative_velocity": 50.0}
_SURVIVAL_FLOOR = 25.0
# Relative band: contribution is judged against the blind score, so a
# 2-point story lift on an 18-point signal (~10%) is material while the
# same lift on an 80-point signal (~2.5%) is noise.
_RELATIVE_BAND = 0.05


def blind_test_differential(
    components: dict[str, float] | None = None,
    **v2_kwargs: object,
) -> dict[str, object]:
    """Score labelled vs blind and report the story's measured contribution.

    ``components`` and ``v2_kwargs`` are exactly the inputs of
    ``aggregate_opportunity_score_v2``; the blind pass reuses them with
    the narrative channel neutralized, so the differential is a pure
    function of the same evidence.
    """
    provided = dict(components or {})
    labelled = aggregate_opportunity_score_v2(provided, **v2_kwargs)
    blind_components = {**provided, **_NEUTRALIZED}
    blind = aggregate_opportunity_score_v2(blind_components, **v2_kwargs)

    labelled_score = float(labelled["opportunity_score"])
    blind_score = float(blind["opportunity_score"])
    narrative_contribution = clip(labelled_score - blind_score, -100.0, 100.0)
    relative_contribution = narrative_contribution / max(blind_score, 1.0)
    survives = blind_score >= _SURVIVAL_FLOOR

    if relative_contribution > _RELATIVE_BAND and not survives:
        blind_class = "story_carried"
    elif relative_contribution > _RELATIVE_BAND:
        blind_class = "narrative_supported"
    elif relative_contribution >= -_RELATIVE_BAND:
        blind_class = "narrative_independent"
    else:
        # Blind score HIGHER than labelled: the missing story is a drag on
        # a boring-but-real signal — the residual-utility hunting ground.
        blind_class = "narrative_understated"

    return {
        "labelled_score": labelled_score,
        "blind_score": blind_score,
        "narrative_contribution": narrative_contribution,
        "relative_contribution": relative_contribution,
        # Kept as an alias for the framework vocabulary ("Narrative
        # Inflation = Labelled Value − Blind Value").
        "narrative_inflation": narrative_contribution,
        "blind_class": blind_class,
        "blind_verdict": blind["advisory_verdict"],
        "labelled_verdict": labelled["advisory_verdict"],
        "neutralized_inputs": dict(_NEUTRALIZED),
        "survives_blind_test": survives,
        "explanation": [
            f"Labelled {labelled_score:.1f} vs blind {blind_score:.1f}: "
            f"narrative contribution {narrative_contribution:+.1f}.",
            f"Class: {blind_class}. "
            + (
                "The signal survives with the story removed."
                if survives
                else "The signal collapses without its story."
            ),
        ],
        "disclaimer": ADVISORY_DISCLAIMER,
    }
