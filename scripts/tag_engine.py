"""Canonical tag catalog for the candidate pre-entry classification path.

HONESTY NOTE (read before trusting this module):
    This catalog is a *single source of truth* for tag strings the active
    pipeline **already emits** — it is not a new capability and it invents no
    new tags. Every id below is a literal currently produced by the active
    path (``signal_conversion_monitor`` -> ``action_engine`` ->
    ``snapshot_logger`` -> ``trend_engine``). A drift test
    (``tests/test_tag_engine.py``) pins these ids against the live consumers.

    The original MVP audit hypothesised "16 tags across 4 families". That was
    an estimate, never a real artifact. The *verified* canonical count is
    defined here (see ``CANONICAL_TAG_COUNT``) and asserted by tests. Do not
    pad the catalog to hit a target number.

Scope (deliberately bounded):
    Candidate pre-entry classification + recommended next-action tags. These
    are the four runtime dimensions:
        * pre_entry_state           (signal_conversion_monitor)
        * watchlist_tier            (signal_conversion_monitor)
        * candidate_conversion_state(signal_conversion_monitor)
        * recommended action label  (action_engine ACTION_ORDER)
    Signal *status* values (WATCHLIST / EXECUTED_CLEAN / EXECUTED_CHAOS) are an
    upstream input dimension and are intentionally NOT catalogued here.

This module is pure: no I/O, no runtime imports, single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TagFamily(str, Enum):
    """Descriptive grouping of a tag by its semantic role.

    Families are an aid to humans reading the catalog; they are not a control
    surface. They mirror the audit's BLOCKING / PROMOTION / PRESSURE /
    TRANSITION vocabulary.
    """

    PROMOTION = "PROMOTION"      # candidate is advancing toward entry eligibility
    BLOCKING = "BLOCKING"        # candidate is held back / entry refused
    PRESSURE = "PRESSURE"        # steady-state / non-advancing / neutral hold
    TRANSITION = "TRANSITION"    # position movement (exit / reduce)


@dataclass(frozen=True)
class Tag:
    """One canonical classification tag.

    Attributes
    ----------
    id:
        The exact string the active pipeline emits. Stable; do not rename.
    family:
        Descriptive grouping (see :class:`TagFamily`).
    dimensions:
        The runtime field(s) this tag can appear in. A tag may legitimately
        appear in more than one dimension (e.g. ``CLEAN_ENTRY_ELIGIBLE``).
    description:
        One-line human description.
    """

    id: str
    family: TagFamily
    dimensions: tuple[str, ...]
    description: str


# Dimension name constants (the runtime fields that carry these tags).
DIM_PRE_ENTRY_STATE = "pre_entry_state"
DIM_WATCHLIST_TIER = "watchlist_tier"
DIM_CANDIDATE_CONVERSION_STATE = "candidate_conversion_state"
DIM_ACTION = "action"


_CATALOG: tuple[Tag, ...] = (
    # --- PROMOTION ---------------------------------------------------------
    Tag("PROMOTABLE", TagFamily.PROMOTION, (DIM_WATCHLIST_TIER,),
        "Watchlist signal at or above the promotion CE threshold."),
    Tag("PROMOTABLE_WATCHLIST", TagFamily.PROMOTION, (DIM_CANDIDATE_CONVERSION_STATE,),
        "Promotable candidate still on the watchlist (not yet clean-ready)."),
    Tag("CLEAN_READY_PENDING", TagFamily.PROMOTION, (DIM_CANDIDATE_CONVERSION_STATE,),
        "Clean candidate ready but a higher-order trigger (REALM_BIS) is still pending."),
    Tag("CLEAN_READY_PENDING_TRIGGER", TagFamily.PROMOTION,
        (DIM_PRE_ENTRY_STATE,),
        "Promotable clean candidate advanced after GSCE cleared; awaits trigger. Policy still forbids new risk."),
    Tag("CLEAN_ENTRY_ELIGIBLE", TagFamily.PROMOTION,
        (DIM_PRE_ENTRY_STATE, DIM_CANDIDATE_CONVERSION_STATE),
        "Clean candidate with no active blockers (advisory eligibility only — NOT an execution authorization)."),
    Tag("REVIEW_FOR_ENTRY", TagFamily.PROMOTION, (DIM_ACTION,),
        "Optional advisory action: surface candidate for human review. Never an order."),
    # --- BLOCKING ----------------------------------------------------------
    Tag("BLOCKED_PROMOTABLE_CLEAN_CANDIDATE", TagFamily.BLOCKING,
        (DIM_PRE_ENTRY_STATE,),
        "Promotable clean candidate blocked while GSCE_PHASE_LOCK (or another blocker) is active."),
    Tag("BLOCK_ENTRY", TagFamily.BLOCKING, (DIM_ACTION,),
        "Advisory action: entry is blocked. Default posture under any active lock."),
    # --- PRESSURE / steady-state ------------------------------------------
    Tag("STANDARD", TagFamily.PRESSURE, (DIM_WATCHLIST_TIER,),
        "Watchlist signal below the promotion CE threshold."),
    Tag("NOT_EXECUTED", TagFamily.PRESSURE, (DIM_CANDIDATE_CONVERSION_STATE,),
        "Candidate not executed (default conversion state)."),
    Tag("NONE", TagFamily.PRESSURE, (DIM_PRE_ENTRY_STATE,),
        "No pre-entry state (non-promotable or no candidate)."),
    Tag("HOLD", TagFamily.PRESSURE, (DIM_ACTION,),
        "Advisory action: hold current posture; take no new action."),
    Tag("MONITOR", TagFamily.PRESSURE, (DIM_ACTION,),
        "Advisory action: keep watching; no entry/exit recommended."),
    # --- TRANSITION (position movement) -----------------------------------
    Tag("EXIT_NOW", TagFamily.TRANSITION, (DIM_ACTION,),
        "Advisory action: exit the position now."),
    Tag("REDUCE", TagFamily.TRANSITION, (DIM_ACTION,),
        "Advisory action: reduce position size."),
)

# Verified canonical count (the audit's "16" was an estimate; this is real).
CANONICAL_TAG_COUNT = len(_CATALOG)

_BY_ID: dict[str, Tag] = {t.id: t for t in _CATALOG}

# --------------------------------------------------------------------------
# Canonical id constants. Import these instead of raw string literals so the
# catalog is the single definition site. Value == id (by design).
# A test asserts this block stays in lock-step with _CATALOG.
# --------------------------------------------------------------------------
PROMOTABLE = "PROMOTABLE"
PROMOTABLE_WATCHLIST = "PROMOTABLE_WATCHLIST"
CLEAN_READY_PENDING = "CLEAN_READY_PENDING"
CLEAN_READY_PENDING_TRIGGER = "CLEAN_READY_PENDING_TRIGGER"
CLEAN_ENTRY_ELIGIBLE = "CLEAN_ENTRY_ELIGIBLE"
REVIEW_FOR_ENTRY = "REVIEW_FOR_ENTRY"
BLOCKED_PROMOTABLE_CLEAN_CANDIDATE = "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE"
BLOCK_ENTRY = "BLOCK_ENTRY"
STANDARD = "STANDARD"
NOT_EXECUTED = "NOT_EXECUTED"
NONE = "NONE"
HOLD = "HOLD"
MONITOR = "MONITOR"
EXIT_NOW = "EXIT_NOW"
REDUCE = "REDUCE"

# Catalog versioning + fingerprint. The fingerprint changes ONLY when the
# catalog content (id/family/dimensions) changes; a test pins it so accidental
# drift is caught and intentional changes are explicit.
TAG_CATALOG_VERSION = "1.0.0"


def catalog_fingerprint() -> str:
    """Stable 16-hex-char fingerprint over (id, family, dimensions)."""
    import hashlib

    payload = "|".join(
        f"{t.id}:{t.family.value}:{','.join(t.dimensions)}" for t in _CATALOG
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


TAG_CATALOG_FINGERPRINT = catalog_fingerprint()


def get_tag_catalog() -> tuple[Tag, ...]:
    """Return the full immutable canonical catalog."""
    return _CATALOG


def tag_ids() -> tuple[str, ...]:
    """Return all canonical tag ids in catalog order."""
    return tuple(t.id for t in _CATALOG)


def validate_tag_id(tag_id: str) -> bool:
    """Return True iff ``tag_id`` is a known canonical tag (exact, case-sensitive)."""
    return tag_id in _BY_ID


def normalize_tag(value: str | None) -> str:
    """Upper/strip a raw value and return it if canonical, else ``"NONE"``.

    Fail-safe: an unknown value normalizes to the neutral ``NONE`` tag rather
    than raising, so this can sit on the hot path without crashing it.
    """
    candidate = str(value or "").strip().upper()
    return candidate if candidate in _BY_ID else "NONE"


def get_tag(tag_id: str) -> Tag:
    """Return the :class:`Tag` for ``tag_id`` or raise KeyError."""
    return _BY_ID[tag_id]


def tags_in_family(family: TagFamily) -> tuple[Tag, ...]:
    """Return all tags in a given family."""
    return tuple(t for t in _CATALOG if t.family is family)


def emit_tag(tag_id: str) -> str:
    """Canonical emit helper: validate and return the tag id unchanged.

    Producers call this when writing a tag so any drift from the catalog
    fails loudly at the source rather than silently persisting an unknown tag.
    """
    if tag_id not in _BY_ID:
        raise ValueError(f"unknown canonical tag id: {tag_id!r}")
    return tag_id
