"""Gap 4: advisory-only / action-authority invariants (doctrine-gated).

These tests LOCK the safety posture in place. They must fail loudly if anyone
adds a BUY/ENTER action, a broker/order path, or flips the default authority to
ACTIVE. No new capability is added here — only guards.
"""

from pathlib import Path

from scripts.action_engine import ACTION_ORDER, OPTIONAL_ACTION_ORDER
from scripts.narrative_operator_wisdom_filter import (
    evaluate_narrative_operator_wisdom_filter,
)

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_no_buy_or_enter_action_label() -> None:
    labels = set(ACTION_ORDER) | set(OPTIONAL_ACTION_ORDER)
    for forbidden in ("BUY", "ENTER", "ENTRY", "OPEN", "EXECUTE", "ORDER"):
        assert forbidden not in labels, f"forbidden action label present: {forbidden}"


def test_action_order_is_exactly_the_advisory_set() -> None:
    # Pins the advisory action vocabulary. Adding an action is a deliberate act.
    assert ACTION_ORDER == ["EXIT_NOW", "REDUCE", "HOLD", "MONITOR", "BLOCK_ENTRY"]
    assert OPTIONAL_ACTION_ORDER == ["REVIEW_FOR_ENTRY"]


def test_action_authority_revoked_by_default() -> None:
    # Seeded/empty context -> operator UNKNOWN, stability below threshold.
    result = evaluate_narrative_operator_wisdom_filter(None)
    assert result["action_authority"] == "REVOKED"
    assert result["allowed_to_execute"] is False


def test_action_engine_has_no_broker_or_order_path() -> None:
    src = (SCRIPTS / "action_engine.py").read_text(encoding="utf-8-sig").lower()
    for forbidden in (
        "place_order", "submit_order", "broker", "execute_trade",
        "import requests", "http://", "https://", "api_key",
    ):
        assert forbidden not in src, f"action_engine must stay advisory-only: {forbidden}"
