"""Section 8 — Concentration & diversity (HHI)."""
from __future__ import annotations

from scripts.governance.daily_gate import concentration_diversity


def _c(country):
    return {"ticker": country[:3], "country": country}


def test_balanced():
    res = concentration_diversity([_c("US"), _c("GERMANY"), _c("FRANCE"), _c("JAPAN"), _c("INDIA")])
    assert res["classification"] == "BALANCED"
    assert res["warnings"] == []


def test_mild_concentration_warning():
    cands = [{"ticker": f"U{i}", "country": "US"} for i in range(6)] + \
            [{"ticker": f"G{i}", "country": "GERMANY"} for i in range(4)]
    res = concentration_diversity(cands)
    # 6/10 = 0.6 exactly is not > 0.60 => MILD
    assert res["classification"] == "MILD_CONCENTRATION"
    assert "COUNTRY_CONCENTRATION_WARNING" in res["warnings"]


def test_heavy_and_extreme():
    heavy = [{"ticker": f"U{i}", "country": "US"} for i in range(7)] + [{"ticker": "G", "country": "DE"}, {"ticker": "F", "country": "FR"}, {"ticker": "J", "country": "JP"}]
    res = concentration_diversity(heavy)
    assert res["classification"] == "HEAVY_CONCENTRATION"
    assert "COUNTRY_OVERCONCENTRATION_BLOCK" in res["warnings"]

    extreme = [{"ticker": f"U{i}", "country": "US"} for i in range(8)] + [{"ticker": "G", "country": "DE"}, {"ticker": "F", "country": "FR"}]
    res2 = concentration_diversity(extreme)
    assert res2["classification"] == "EXTREME_CONCENTRATION"
    assert "DISCOVERY_TOO_CONCENTRATED" in res2["warnings"]


def test_hhi_value():
    res = concentration_diversity([_c("US"), _c("US"), _c("DE"), _c("FR")])
    # shares: US .5, DE .25, FR .25 => HHI = .25 + .0625 + .0625 = .375
    assert res["hhi"] == 0.375


def test_fixture_is_mild(gov_result):
    cd = gov_result.concentration_and_diversity
    assert cd["classification"] == "MILD_CONCENTRATION"
    assert "COUNTRY_CONCENTRATION_WARNING" in cd["warnings"]
    assert cd["max_country_share"] <= 0.60
