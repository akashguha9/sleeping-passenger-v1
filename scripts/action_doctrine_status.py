"""Machine-readable action-authority doctrine status — UNRATIFIED by default.

This module reports whether the human operator has ratified the action-authority
doctrine (see docs/ACTION_AUTHORITY_DOCTRINE.md). It is a STATUS REPORTER, not
a control surface:

    * It is UNRATIFIED by default and ships UNRATIFIED.
    * It unlocks NOTHING. Returning a status never changes governance,
      action_authority, or any lock. Code cannot self-ratify authority.
    * It must never be imported by broker/order/execution code (test-enforced).

Ratification is a HUMAN act performed OUTSIDE code. Even a future "ratified"
state here would only *record* that act; it would not by itself permit any
trade. The five gates below must each be satisfied by a human.
"""

from __future__ import annotations

from typing import Any

DOCTRINE_DOC = "docs/ACTION_AUTHORITY_DOCTRINE.md"

# The five ratification gates. All UNRATIFIED until a human ratifies them
# outside code. Do NOT flip these to "RATIFIED" programmatically.
GATES = (
    "authority",            # who may lift action_authority=REVOKED
    "unit_of_learning",     # what conditions a BUY/entry candidate
    "operator_contract",    # what the system promises / never promises
    "observation_evidence",  # forward-observation evidence requirement
    "safety_rollback",      # how to revoke authority and roll back safely
)

_UNRATIFIED = "UNRATIFIED"


def doctrine_status() -> dict[str, Any]:
    """Return the current (always UNRATIFIED) doctrine status."""
    return {
        "overall": _UNRATIFIED,
        "ratified": False,
        "gates": {gate: _UNRATIFIED for gate in GATES},
        "doc": DOCTRINE_DOC,
        "authorizes_action": False,
        "note": (
            "Doctrine is UNRATIFIED. This module unlocks nothing; ratification "
            "is a human act recorded outside code. action_authority stays "
            "REVOKED regardless of this status."
        ),
    }


def is_ratified() -> bool:
    """Always False. Code cannot self-ratify action authority."""
    return False


def main() -> int:
    import json

    print(json.dumps(doctrine_status(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
