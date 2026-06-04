"""Tag-engine catalog integrity + drift guard against the live consumers.

These tests prove the canonical catalog is real (no duplicates, stable ids)
AND that it stays in sync with the strings the active pipeline actually emits
(``signal_conversion_monitor`` producer + ``action_engine`` action labels).
If a consumer starts emitting a tag the catalog does not know about — or the
catalog drifts from the consumers — these tests fail.
"""

from scripts import tag_engine
from scripts.action_engine import ACTION_ORDER, OPTIONAL_ACTION_ORDER
from scripts.tag_engine import TagFamily


def test_catalog_count_is_explicit_and_stable() -> None:
    catalog = tag_engine.get_tag_catalog()
    # The verified canonical count. NOT the audit's hypothesised 16 — this is
    # the real emitted set. Changing it is a deliberate act.
    assert len(catalog) == 15
    assert tag_engine.CANONICAL_TAG_COUNT == 15


def test_no_duplicate_tag_ids() -> None:
    ids = [t.id for t in tag_engine.get_tag_catalog()]
    assert len(ids) == len(set(ids))


def test_tag_ids_are_stable_set() -> None:
    # Pin the exact id set so a rename/removal is caught.
    assert set(tag_engine.tag_ids()) == {
        "PROMOTABLE", "PROMOTABLE_WATCHLIST", "CLEAN_READY_PENDING",
        "CLEAN_READY_PENDING_TRIGGER", "CLEAN_ENTRY_ELIGIBLE", "REVIEW_FOR_ENTRY",
        "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE", "BLOCK_ENTRY",
        "STANDARD", "NOT_EXECUTED", "NONE", "HOLD", "MONITOR",
        "EXIT_NOW", "REDUCE",
    }


def test_every_tag_has_a_family_and_dimension() -> None:
    for t in tag_engine.get_tag_catalog():
        assert isinstance(t.family, TagFamily)
        assert t.dimensions, f"{t.id} has no dimension"
        assert t.description.strip()


def test_validate_and_normalize() -> None:
    assert tag_engine.validate_tag_id("CLEAN_ENTRY_ELIGIBLE") is True
    assert tag_engine.validate_tag_id("NOT_A_TAG") is False
    assert tag_engine.normalize_tag(" clean_entry_eligible ") == "CLEAN_ENTRY_ELIGIBLE"
    # Fail-safe: unknown values normalize to the neutral NONE, never raise.
    assert tag_engine.normalize_tag("garbage") == "NONE"
    assert tag_engine.normalize_tag(None) == "NONE"


def test_emit_tag_rejects_unknown() -> None:
    assert tag_engine.emit_tag("EXIT_NOW") == "EXIT_NOW"
    try:
        tag_engine.emit_tag("ENTER")  # there is intentionally no BUY/ENTER tag
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_no_buy_or_enter_tag_exists() -> None:
    # Advisory-only posture: the catalog must not contain an entry/execution tag.
    ids = set(tag_engine.tag_ids())
    for forbidden in ("BUY", "ENTER", "ENTRY", "OPEN_POSITION", "EXECUTE"):
        assert forbidden not in ids


def test_action_labels_are_all_catalogued() -> None:
    # DRIFT GUARD: every action label the action engine can emit must be a
    # known canonical tag. Catches a new action label added without cataloguing.
    for label in list(ACTION_ORDER) + list(OPTIONAL_ACTION_ORDER):
        assert tag_engine.validate_tag_id(label), f"action label {label} not in catalog"


def test_pre_entry_states_emitted_by_producer_are_catalogued() -> None:
    # DRIFT GUARD against signal_conversion_monitor's produced pre_entry_state
    # vocabulary (the producer now emits these via tag_engine.emit_tag).
    for state in (
        "NONE", "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
        "CLEAN_READY_PENDING_TRIGGER", "CLEAN_ENTRY_ELIGIBLE",
    ):
        assert tag_engine.validate_tag_id(state)
