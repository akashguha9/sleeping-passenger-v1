"""Games layer: classify the decision environment before scoring it.

    The edge is not more data; it is knowing what game the data
    belongs to.

Doctrine:
    Before choosing the move, identify the game.
    Before trusting the game, inspect the dice.
    Before trusting the dice, ask who benefits if it is loaded.
    Prediction market price is not truth; it is tradable belief.
    Do not confuse tradeability with investability.
    A signal without half-life becomes stale poison.
    Power without mobility can be trapped.
    The scoreboard can become more real than the game.

ADVISORY_ONLY — classification and interpretation for journal research;
no orders, no execution, human judgement required.
"""

GAMES_DOCTRINE: tuple[str, ...] = (
    "Before choosing the move, identify the game.",
    "Before trusting the game, inspect the dice.",
    "Before trusting the dice, ask who benefits if it is loaded.",
    "Prediction market price is not truth; it is tradable belief about truth.",
    "Do not confuse tradeability with investability.",
    "Strong reality with weak narrative can be opportunity.",
    "Weak reality with strong narrative can be danger.",
    "Markets are nested games played with uncertain dice.",
    "The edge is not more data; it is knowing what game the data belongs to.",
    "The scoreboard can become more real than the game.",
)

GAMES_ADVISORY_NOTE = (
    "ADVISORY_ONLY — game/dice/reality classification for journal "
    "research. No orders are placed; staged actions are research labels, "
    "not instructions."
)
