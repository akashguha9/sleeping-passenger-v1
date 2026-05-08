"""Lightweight entity-name resolution placeholder.

This is intentionally minimal: the MVP only needs deterministic, side-effect
free hooks that downstream modules can call. Real resolution (Wikidata /
OpenCorporates / SEC CIK) can plug in later.
"""
from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_name(name: str) -> str:
    if not name:
        return ""
    return _NON_ALNUM.sub("-", name.lower()).strip("-")


def resolve_entity(name: str) -> dict[str, str]:
    return {"raw": name, "normalized": normalize_name(name), "resolver": "placeholder"}
