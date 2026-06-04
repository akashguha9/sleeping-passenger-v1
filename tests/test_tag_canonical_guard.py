"""Canonical-tag drift guard + catalog versioning (Tagging-v1 hardening).

Enforces a single canonical definition site for tags, that the genuine decision
consumers import tag_engine, and that catalog content is versioned/fingerprinted.

The remaining modules that still compare against raw distinctive tag literals
WITHOUT importing tag_engine are captured in an explicit, frozen ALLOWLIST.
This is the deliberate 9/10 posture (explicit exceptions), NOT 10/10 (no
exceptions). A NEW module introducing a raw distinctive tag literal will fail
this test until it either imports tag_engine or is consciously allowlisted.
"""

import re
from pathlib import Path

from scripts import tag_engine as tags

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

# Distinctive canonical tags — unambiguous tag strings (not generic words like
# NONE/STANDARD/HOLD that appear in many unrelated contexts).
DISTINCTIVE = (
    "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
    "CLEAN_READY_PENDING_TRIGGER",
    "CLEAN_ENTRY_ELIGIBLE",
    "CLEAN_READY_PENDING",
    "PROMOTABLE_WATCHLIST",
    "REVIEW_FOR_ENTRY",
)

# Genuine decision/classification consumers that MUST route through tag_engine.
MIGRATED_CONSUMERS = (
    "signal_conversion_monitor",  # producer (emit_tag)
    "action_engine",
    "snapshot_logger",
    "trend_engine",
)

# Explicit, frozen exceptions: modules that still reference a distinctive tag
# literal as a read-only comparison without importing tag_engine. Each is a
# known consumer (god modules / read-only layers) not yet migrated. Shrinking
# this set is always allowed; growing it requires a conscious edit here.
TAG_LITERAL_ALLOWLIST = frozenset({
    "archetype_profile",
    "closure_deficit_monitor",
    "execution_governance",
    "false_negative_casino_monopoly_layer",
    "operator_control",
    "paper_execution",
    "perception_control",
    "pipeline_health_report",
    "runtime_common",
    "signal_refinery",
    "temporal_position_engine",
    "visibility_engine",
})

_LITERAL_RE = re.compile(r'["\'](' + "|".join(DISTINCTIVE) + r')["\']')


def test_constants_match_catalog_lockstep() -> None:
    catalog_ids = set(tags.tag_ids())
    const_values = {
        getattr(tags, name)
        for name in catalog_ids  # every id is also a module constant name
    }
    assert const_values == catalog_ids
    # And no constant points at a non-canonical value.
    for tag_id in catalog_ids:
        assert getattr(tags, tag_id) == tag_id


def test_catalog_version_and_fingerprint_pinned() -> None:
    assert tags.TAG_CATALOG_VERSION == "1.0.0"
    # Fingerprint changes ONLY when the catalog content changes. If you changed
    # the catalog on purpose, bump TAG_CATALOG_VERSION and update this hash.
    assert tags.TAG_CATALOG_FINGERPRINT == "32f4e17ecafec2ab"
    assert tags.catalog_fingerprint() == tags.TAG_CATALOG_FINGERPRINT


def test_decision_consumers_import_tag_engine() -> None:
    for stem in MIGRATED_CONSUMERS:
        src = (SCRIPTS / f"{stem}.py").read_text(encoding="utf-8-sig")
        assert "tag_engine" in src, f"{stem} must import tag_engine"


def test_migrated_consumers_have_no_raw_distinctive_literals() -> None:
    # The producer routes literals through emit_tag(...) intentionally; the
    # other three must contain no raw distinctive tag literal at all.
    for stem in ("action_engine", "snapshot_logger", "trend_engine"):
        src = (SCRIPTS / f"{stem}.py").read_text(encoding="utf-8-sig")
        found = _LITERAL_RE.findall(src)
        assert not found, f"{stem} still has raw tag literals: {found}"


def test_no_new_unallowlisted_raw_tag_literal_modules() -> None:
    offenders = []
    for path in SCRIPTS.glob("*.py"):
        src = path.read_text(encoding="utf-8-sig")
        if not _LITERAL_RE.search(src):
            continue
        if "tag_engine" in src:
            continue  # routes through the canonical module
        if path.stem in TAG_LITERAL_ALLOWLIST:
            continue  # explicit, acknowledged exception
        offenders.append(path.stem)
    assert offenders == [], (
        "New module(s) define raw distinctive tag literals without importing "
        f"tag_engine: {offenders}. Import tag_engine or add to "
        "TAG_LITERAL_ALLOWLIST with rationale."
    )
