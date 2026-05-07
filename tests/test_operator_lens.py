from scripts.contextual_interpretation.operator_lens import default_operator_lenses


def test_default_operator_lenses_cover_required_views() -> None:
    lenses = default_operator_lenses()
    names = {lens.lens_name for lens in lenses}
    assert names == {"Retail", "Institution", "Momentum", "MarketMaker", "Contrarian", "Whale"}
