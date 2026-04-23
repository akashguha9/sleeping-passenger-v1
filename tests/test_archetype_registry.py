from scripts.archetype_registry import load_archetype_registry


def test_archetype_registry_loads_required_modules() -> None:
    registry = load_archetype_registry()

    assert registry["schema_version"] == "ARCHETYPE_REGISTRY_V1"
    assert registry["path"].endswith("config/archetype_registry.json")
    assert set(registry["archetypes"]) == {
        "fischer",
        "kasparov",
        "carlsen",
        "messi",
        "cristiano",
        "neuer",
        "neymar",
        "hazard",
    }
    assert set(registry["meta_layers"]) == {
        "archetype_weighting_layer",
        "closure_deficit_monitor",
    }
    assert registry["archetypes"]["fischer"]["module_name"] == "Signal Purity Engine"
    assert registry["archetypes"]["hazard"]["dimension_key"] == "friction_flow_score"
