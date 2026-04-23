from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import CONFIG_DIR, load_json_file, repo_relative
except ModuleNotFoundError:
    from runtime_common import CONFIG_DIR, load_json_file, repo_relative


ARCHETYPE_REGISTRY_PATH = CONFIG_DIR / "archetype_registry.json"

REQUIRED_ARCHETYPES = (
    "fischer",
    "kasparov",
    "carlsen",
    "messi",
    "cristiano",
    "neuer",
    "neymar",
    "hazard",
)
REQUIRED_META_LAYERS = (
    "archetype_weighting_layer",
    "closure_deficit_monitor",
)


def _copy_registry(payload: dict[str, Any]) -> dict[str, Any]:
    copied = dict(payload)
    archetypes = payload.get("archetypes", {})
    meta_layers = payload.get("meta_layers", {})
    copied["archetypes"] = {
        key: dict(value) for key, value in archetypes.items() if isinstance(value, dict)
    }
    copied["meta_layers"] = {
        key: dict(value) for key, value in meta_layers.items() if isinstance(value, dict)
    }
    return copied


def validate_archetype_registry(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["registry payload must be a JSON object"]

    errors: list[str] = []
    archetypes = payload.get("archetypes", {})
    meta_layers = payload.get("meta_layers", {})
    if not isinstance(archetypes, dict):
        errors.append("archetypes must be an object")
        archetypes = {}
    if not isinstance(meta_layers, dict):
        errors.append("meta_layers must be an object")
        meta_layers = {}

    for name in REQUIRED_ARCHETYPES:
        entry = archetypes.get(name)
        if not isinstance(entry, dict):
            errors.append(f"missing archetype entry: {name}")
            continue
        for field in (
            "label",
            "module_name",
            "dimension_key",
            "default_weight",
            "pipeline_stage",
            "criticality",
            "paper_mode_role",
            "metrics",
            "regime_multipliers",
        ):
            if field not in entry:
                errors.append(f"archetype {name} missing field: {field}")
        if not isinstance(entry.get("metrics"), list):
            errors.append(f"archetype {name} metrics must be a list")
        if not isinstance(entry.get("regime_multipliers"), dict):
            errors.append(f"archetype {name} regime_multipliers must be an object")

    for name in REQUIRED_META_LAYERS:
        entry = meta_layers.get(name)
        if not isinstance(entry, dict):
            errors.append(f"missing meta layer entry: {name}")
            continue
        for field in ("module_name", "criticality", "paper_mode_role"):
            if field not in entry:
                errors.append(f"meta layer {name} missing field: {field}")

    return errors


def load_archetype_registry(path: Path | None = None) -> dict[str, Any]:
    target = path or ARCHETYPE_REGISTRY_PATH
    payload = load_json_file(target, default={}) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"archetype registry must be a JSON object: {repo_relative(target)}")
    errors = validate_archetype_registry(payload)
    if errors:
        joined = "; ".join(errors)
        raise ValueError(f"invalid archetype registry {repo_relative(target)}: {joined}")
    registry = _copy_registry(payload)
    registry["path"] = repo_relative(target)
    return registry


def list_archetype_ids(path: Path | None = None) -> list[str]:
    registry = load_archetype_registry(path)
    return list(registry.get("archetypes", {}).keys())
