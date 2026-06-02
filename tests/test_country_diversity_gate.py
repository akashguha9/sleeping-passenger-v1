"""Tests for scripts/country_diversity_gate.py — diversity without forced trades."""
from __future__ import annotations

from scripts.country_diversity_gate import (
    COUNTRY_CONCENTRATION_WARNING,
    COUNTRY_OVERCONCENTRATION_BLOCK,
    DISCOVERY_TOO_CONCENTRATED,
    TRADE_CANDIDATE,
    WATCH_CAP_LIMITED,
    apply_trade_candidate_cap,
    build_diversity_report,
    check_quota,
    compute_diversity,
    load_quotas,
)

QUOTAS = load_quotas()


def _c(country, score=80.0, status=None):
    return {"ticker": f"{country[:2]}{int(score)}", "country": country,
            "discovery_score": score, "promotion_status": status}


# 1. Four South Korea names -> concentration warning.
def test_four_south_korea_names_trigger_concentration_warning():
    cands = [_c("South Korea", s) for s in (90, 85, 80, 75)]
    div = compute_diversity(cands, QUOTAS)
    assert div["max_country_share"] == 1.0
    assert COUNTRY_CONCENTRATION_WARNING in div["concentration_warnings"]
    assert COUNTRY_OVERCONCENTRATION_BLOCK in div["concentration_warnings"]
    assert DISCOVERY_TOO_CONCENTRATED in div["concentration_warnings"]


# 2. UK + Japan is more diverse than SK-only, but below the global target.
def test_uk_japan_more_diverse_but_below_global_target():
    sk_only = [_c("South Korea", s) for s in (90, 85, 80, 75)]
    uk_jp = [_c("United Kingdom", 88), _c("Japan", 84), _c("Japan", 80)]

    div_sk = compute_diversity(sk_only, QUOTAS)
    div_ukjp = compute_diversity(uk_jp, QUOTAS)
    assert div_ukjp["diversity_score"] > div_sk["diversity_score"]

    quota = check_quota(uk_jp, QUOTAS)
    assert quota["global_discovery_target_met"] is False


# 3. The gate never fabricates missing countries.
def test_gate_does_not_fabricate_countries():
    cands = [_c("Japan", 80), _c("Japan", 70)]
    quota = check_quota(cands, QUOTAS)
    # Regions with no discovered names report shortfall, not invented names.
    assert quota["per_region"]["US"]["discovered"] == 0
    assert quota["per_region"]["US"]["shortfall"] == 5
    assert quota["fabrication"].startswith("NONE")
    # The cap pass returns exactly the input names — nothing added.
    capped = apply_trade_candidate_cap(cands, QUOTAS)
    assert len(capped) == len(cands)
    assert {r["ticker"] for r in capped} == {c["ticker"] for c in cands}


# 4. The gate can say quota not met.
def test_gate_reports_quota_not_met():
    cands = [_c("United States", 80)]  # 1 US name, needs 5
    quota = check_quota(cands, QUOTAS)
    assert quota["per_region"]["US"]["quota_met"] is False
    assert quota["per_region"]["US"]["shortfall"] == 4
    assert quota["global_discovery_target_met"] is False


# 5. The trade-candidate cap prevents one country from dominating.
def test_trade_candidate_cap_limits_one_country():
    cands = [_c("United States", s, status=TRADE_CANDIDATE) for s in (95, 90, 85, 80, 75)]
    capped = apply_trade_candidate_cap(cands, QUOTAS)
    promoted = [r for r in capped if r["promotion_status"] == TRADE_CANDIDATE]
    cap_limited = [r for r in capped if r["promotion_status"] == WATCH_CAP_LIMITED]
    assert len(promoted) == 2  # US max_trade_candidates
    assert len(cap_limited) == 3
    # The two kept are the highest-scoring (95, 90).
    assert {r["ticker"] for r in promoted} == {"Un95", "Un90"}


def test_build_report_is_advisory_and_does_not_force_trades():
    report = build_diversity_report([_c("Japan", 80)], QUOTAS)
    assert report["diversity_forces_trades"] is False
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["human_execution_required"] is True
