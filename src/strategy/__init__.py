"""Strategy layer: narrative-to-stock game-theory engines (advisory-only).

Doctrine:
    The MVP does not pick stocks directly; it traces narrative
    probability into economic payoff nodes.
    No mechanism, no trade.
    The best stock may not be named in the headline; it may be feeding
    the company named in the headline.
    Apex predators are not universally dominant; they are dominant
    within nodes.
    A node is not valuable by itself — odds, hierarchy, edge durability,
    threshold condition, and inflection timing must align.
    A company is not only a piece on the board; it is a possible state
    transition.
    The model's backhand becomes strong by repeatedly receiving the
    strongest bear-case attack.
    Greatness is pressure-adjusted by the monsters you had to beat.
    Underground is not automatically undervalued.
    Attention is not value until it converts.
    Raw numbers are meaningless without distribution context.
    Bell curves locate normality; fat-tail logic detects breakouts.
    A high score cannot override an unresolved existential bear case.

Every verdict here is a RESEARCH CLASSIFICATION for the advisory journal:
no orders, no execution, human judgement required. The final question is
not "is this company good?" but "is this company in the right node, with
the right weapon, at the right inflection, with enough durability to
survive attack?"
"""

STRATEGY_DOCTRINE: tuple[str, ...] = (
    "The MVP does not pick stocks directly; it traces narrative "
    "probability into economic payoff nodes.",
    "No mechanism, no trade.",
    "The best stock may not be named in the headline; it may be feeding "
    "the company named in the headline.",
    "Apex predators are not universally dominant; they are dominant "
    "within nodes.",
    "A node is not valuable by itself.",
    "A company is not only a piece on the board; it is a possible state "
    "transition.",
    "The model's backhand becomes strong by repeatedly receiving the "
    "strongest bear-case attack.",
    "Greatness is pressure-adjusted by the monsters you had to beat.",
    "Underground is not automatically undervalued.",
    "Attention is not value until it converts.",
    "Raw numbers are meaningless without distribution context.",
    "Bell curves locate normality; fat-tail logic detects breakouts.",
    "Expected value beats excitement.",
    "No threshold, no buy.",
    "Every edge has a half-life.",
    "A high score cannot override an unresolved existential bear case.",
)

STRATEGY_ADVISORY_NOTE = (
    "ADVISORY_ONLY — research classification for the journal. Verdict "
    "labels (BUY/WATCHLIST/...) are analytical categories, not "
    "instructions; no order is placed, sized, or routed."
)
