"""Dice Profile Classifier: inspect the dice before trusting the odds.

Every signal source is an uncertainty engine with a shape:

    precision  — audited, low-bias evidence (filings, verified data)
    d4         — low-variance operational signals
    d6         — balanced uncertainty
    d10        — catalyst volatility
    d20        — high-drama binary events (biotech, lawsuits, memes)
    d100       — fine-grained probability engines (prediction markets)
    rounded    — noisy social/news chatter
    loaded_possible — manipulation / asymmetric information suspected
    non_transitive  — regime-dependent matchup logic (no absolute best)

Plus a deterministic loaded-die detector over observed outcome counts:
    bias = Σ|observed_i − expected_i| / 2   (total variation distance)
and a non-transitive matchup table for regime-dependent comparison.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01
from src.utils.validation_utils import normalized_score

DICE_PROFILES: tuple[str, ...] = (
    "precision", "d4", "d6", "d10", "d20", "d100",
    "rounded", "loaded_possible", "non_transitive",
)

# Total-variation distance at or above this flags a loaded die.
LOADED_BIAS_THRESHOLD = 0.20
# Minimum observations before a bias verdict means anything.
MIN_OBSERVATIONS = 30


@dataclass(slots=True)
class DiceProfile:
    """Uncertainty classification of one signal source."""

    source: str
    profile: str
    variance_class: str
    reliability: float
    manipulation_risk: float
    confidence_multiplier: float
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class LoadedDieReport:
    """Distribution-bias verdict over observed outcomes."""

    bias_score: float
    loaded: bool
    observations: int
    sufficient_sample: bool
    worst_face: str = ""
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def classify_dice_profile(
    *,
    source: str,
    reliability: float = 0.5,
    variance: float = 0.5,
    manipulation_risk: float = 0.0,
    is_probability_market: bool = False,
    regime_dependent: bool = False,
) -> DiceProfile:
    """Classify one signal source's uncertainty engine (inputs 0–1).

    The confidence multiplier scales how much weight downstream scoring
    may put on this source: precision ≈ 1.0, rounded ≈ 0.5,
    loaded_possible ≈ 0.25 — a suspect die discounts everything rolled
    with it.
    """
    rel = normalized_score(reliability, 0.5)
    var = normalized_score(variance, 0.5)
    manipulation = normalized_score(manipulation_risk)

    rationale: list[str] = []
    if manipulation >= 0.5:
        profile = "loaded_possible"
        rationale.append(
            f"manipulation risk {manipulation:.2f} — ask who benefits if "
            "this die is loaded"
        )
    elif regime_dependent:
        profile = "non_transitive"
        rationale.append("regime-dependent matchup source — no absolute "
                         "ranking exists")
    elif is_probability_market:
        profile = "d100"
        rationale.append("crowd-implied probability engine — tradable "
                         "belief, not truth")
    elif rel >= 0.8 and var <= 0.3:
        profile = "precision"
    elif rel <= 0.45:
        profile = "rounded"
        rationale.append("noisy source — treated as a rounded home die")
    elif var >= 0.8:
        profile = "d20"
        rationale.append("high-drama variance — threshold-success logic "
                         "applies")
    elif var >= 0.6:
        profile = "d10"
    elif var <= 0.25:
        profile = "d4"
    else:
        profile = "d6"

    variance_class = (
        "low" if var <= 0.3 else ("high" if var >= 0.7 else "medium")
    )
    confidence = clamp01(
        rel * (1.0 - 0.5 * manipulation) * (1.0 - 0.25 * var)
    )
    if profile == "loaded_possible":
        confidence = min(confidence, 0.25)
    rationale.append(
        f"profile '{profile}' (reliability {rel:.2f}, variance {var:.2f}) "
        f"-> confidence multiplier {confidence:.2f}"
    )

    return DiceProfile(
        source=str(source),
        profile=profile,
        variance_class=variance_class,
        reliability=rel,
        manipulation_risk=manipulation,
        confidence_multiplier=confidence,
        rationale=rationale,
    )


def detect_loaded_die(
    observed_counts: dict[str, int],
    expected_probabilities: dict[str, float] | None = None,
) -> LoadedDieReport:
    """Total-variation bias test of observed outcomes vs expectation.

    With no expectation supplied, a fair (uniform) die is assumed. Small
    samples never produce a loaded verdict — an unfair-looking handful of
    rolls is an anecdote, not a bias finding.
    """
    counts = {str(k): max(int(v), 0) for k, v in (observed_counts or {}).items()}
    total = sum(counts.values())
    if total == 0 or not counts:
        return LoadedDieReport(
            bias_score=0.0, loaded=False, observations=0,
            sufficient_sample=False,
            rationale=["no observations supplied"],
        )

    faces = sorted(counts)
    if expected_probabilities:
        expected = {
            face: max(float(expected_probabilities.get(face, 0.0)), 0.0)
            for face in faces
        }
        norm = sum(expected.values()) or 1.0
        expected = {face: p / norm for face, p in expected.items()}
    else:
        expected = {face: 1.0 / len(faces) for face in faces}

    observed = {face: counts[face] / total for face in faces}
    bias = sum(abs(observed[f] - expected[f]) for f in faces) / 2.0
    sufficient = total >= MIN_OBSERVATIONS
    loaded = sufficient and bias >= LOADED_BIAS_THRESHOLD
    worst = max(faces, key=lambda f: observed[f] - expected[f])

    rationale = [
        f"total-variation bias {bias:.3f} over {total} observation(s)"
    ]
    if not sufficient:
        rationale.append(
            f"sample below {MIN_OBSERVATIONS} — bias verdict withheld; "
            "an odd handful of rolls is an anecdote"
        )
    elif loaded:
        rationale.append(
            f"LOADED: face '{worst}' over-represented by "
            f"{observed[worst] - expected[worst]:+.3f} — inspect who "
            "benefits before optimizing any move"
        )

    return LoadedDieReport(
        bias_score=bias,
        loaded=loaded,
        observations=total,
        sufficient_sample=sufficient,
        worst_face=worst,
        rationale=rationale,
    )


@dataclass(slots=True)
class MatchupVerdict:
    """Non-transitive, regime-conditional comparison of two candidates."""

    regime: str
    winner: str
    edge: float
    non_transitive_warning: bool
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def regime_matchup(
    *,
    candidate_a: str,
    candidate_b: str,
    regime: str,
    scores_by_regime: dict[str, dict[str, float]],
) -> MatchupVerdict:
    """Who beats whom IN THIS REGIME — never absolutely.

    ``scores_by_regime`` maps regime -> {candidate: score 0–1}. The
    non-transitive warning fires when the winner flips across the
    supplied regimes: A > B here and B > A elsewhere means absolute
    ranking talk is a category error.
    """
    current = scores_by_regime.get(regime, {})
    a_score = normalized_score(current.get(candidate_a, 0.0))
    b_score = normalized_score(current.get(candidate_b, 0.0))
    winner = candidate_a if a_score >= b_score else candidate_b
    edge = abs(a_score - b_score)

    flips = False
    for other_regime, scores in scores_by_regime.items():
        if other_regime == regime:
            continue
        other_a = normalized_score(scores.get(candidate_a, 0.0))
        other_b = normalized_score(scores.get(candidate_b, 0.0))
        other_winner = candidate_a if other_a >= other_b else candidate_b
        if other_winner != winner:
            flips = True
            break

    rationale = [
        f"in regime '{regime}': {winner} leads by {edge:.2f}",
    ]
    if flips:
        rationale.append(
            "NON-TRANSITIVE: the winner flips in another supplied regime — "
            "matchup matters more than absolute ranking"
        )

    return MatchupVerdict(
        regime=str(regime),
        winner=winner,
        edge=edge,
        non_transitive_warning=flips,
        rationale=rationale,
    )
