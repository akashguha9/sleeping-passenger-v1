"""nbi-v1.1 — seeded randomized property tests over the branch/score math.

Deterministic fuzzing (fixed ``random.Random`` seeds, no hypothesis
dependency, no flakiness): hundreds of randomly generated claim corpora and
exposures are pushed through the engine, asserting the 15 sprint invariants
on every sample.  Every generated value is drawn from a seeded PRNG, so a
failure reproduces exactly.
"""
from __future__ import annotations

import random

from scripts import narrative_branch_engine as nbi
from scripts import nbi_calibration_report as cal
from scripts import nbi_store as store

_LAYERS = list(nbi.NARRATIVE_LAYERS)
_CLASSES = list(nbi.SOURCE_CLASSES)
_BRANCH_CHOICES = list(nbi.BRANCHES) + ["", "nonsense_branch"]
_DIRECTIONS = ["SUPPORTS", "REFUTES", "NEUTRAL", "??"]
_CHANNELS = list(nbi.CATALYST_CHANNELS) + ["BOGUS_CHANNEL"]


def _random_claim(rng: random.Random, i: int) -> dict:
    has_refs = rng.random() > 0.3
    return {
        "claim_id": f"c{i}",
        "layer": rng.choice(_LAYERS + ["MYSTERY_LAYER"]),
        "claim_text": rng.choice([
            "summit expected to proceed", "BREAKING!! chaos panic",
            "venue shifted to capital", "traffic jam near flyover", "",
        ]),
        "source_cluster": rng.choice(["a", "b", "c", "d", ""]),
        "source_class": rng.choice(_CLASSES + ["ALIEN_SOURCE"]),
        "jurisdiction": rng.choice(["JP", "IN", "US", ""]),
        "age_hours": rng.choice([None, rng.uniform(0, 200)]),
        "direction": rng.choice(_DIRECTIONS),
        "branch": rng.choice(_BRANCH_CHOICES),
        "strength": rng.choice([None, rng.uniform(0, 1), rng.uniform(-2, 3)]),
        "claim_magnitude": rng.uniform(0, 12),
        "evidence_strength": rng.uniform(0, 12),
        "mentions_per_hour": rng.choice([None, rng.uniform(0, 100)]),
        "historical_accuracy": rng.choice([None, rng.uniform(0, 1)]),
        "evidence_refs": ["https://e/x"] if has_refs else [],
    }


def _random_exposure(rng: random.Random, i: int) -> dict:
    has_refs = rng.random() > 0.25
    has_price = rng.random() > 0.4
    exposure = {
        "ticker": f"T{i}",
        "channel": rng.choice(_CHANNELS),
        "base_relevance": rng.uniform(0, 12),
        "evidence_confidence": rng.choice([None, rng.uniform(0, 1)]),
        "evidence_refs": ["https://e/f"] if has_refs else [],
        "filing_confirmed": rng.choice([True, False, None]),
        "liquidity_ok": rng.choice([True, False, None]),
        "days_since_last_verified": rng.choice([None, rng.uniform(0, 30)]),
    }
    if has_price:
        exposure.update({
            "model_probability": rng.uniform(0, 1),
            "market_implied_probability": rng.uniform(0, 1),
            "realized_move_zscore": rng.uniform(-6, 6),
        })
    return exposure


def _random_event(rng: random.Random) -> dict:
    return {
        "event_id": f"fuzz-{rng.randint(0, 10**6)}",
        "event_name": "fuzz event",
        "decision_jurisdictions": rng.choice([[], ["JP"], ["JP", "IN"]]),
        "priors": {
            b: rng.uniform(0.02, 0.98) for b in nbi.BRANCHES
        },
        "claims": [
            _random_claim(rng, i) for i in range(rng.randint(0, 10))
        ],
        "exposures": [
            _random_exposure(rng, i) for i in range(rng.randint(0, 6))
        ],
        "days_since_official_confirmation": rng.choice(
            [None, rng.uniform(0, 30)]
        ),
    }


# ---------------------------------------------------------------------------
# Invariants 1-2: branch ordering
# ---------------------------------------------------------------------------


def test_fuzz_branch_ordering_invariants():
    rng = random.Random(1234)
    for _ in range(300):
        claims = nbi.normalize_claims(
            [_random_claim(rng, i) for i in range(rng.randint(0, 12))]
        )
        priors = {b: rng.uniform(0.02, 0.98) for b in nbi.BRANCHES}
        branches = nbi.evaluate_event_branches(claims, priors, ["JP", "IN"])
        core = branches["core_event"]["p"]
        for b in nbi.CORE_BOUNDED_BRANCHES:
            assert branches[b]["p"] <= core + 1e-9, (b, branches[b], core)
        deals = branches["deals_or_mous"]
        if deals["n_clusters"] == 0:
            assert deals["p"] <= branches["delegation_intact"]["p"] + 1e-9
        for b in nbi.BRANCHES:
            assert 0.0 <= branches[b]["p"] <= 1.0
            assert 0.0 <= branches[b]["independent_confirmation"] <= 1.0


# ---------------------------------------------------------------------------
# Invariants 3-5: social / repetition / citation cannot raise truth
# ---------------------------------------------------------------------------


def test_fuzz_social_only_corpora_never_move_branches():
    rng = random.Random(99)
    for _ in range(100):
        claims = []
        for i in range(rng.randint(1, 8)):
            c = _random_claim(rng, i)
            c["source_class"] = rng.choice(["SOCIAL_MEDIA", "LLM_SUMMARY"])
            c["evidence_refs"] = ["https://social/x"]
            claims.append(c)
        priors = {b: rng.uniform(0.05, 0.95) for b in nbi.BRANCHES}
        branches = nbi.evaluate_event_branches(
            nbi.normalize_claims(claims), priors, []
        )
        core = branches["core_event"]
        # Social can never move a branch above its prior... or below: zero
        # LLR contribution, so posterior == prior (4dp rounding tolerance).
        assert abs(core["p"] - core["prior"]) < 1e-4
        assert core["status"] == "INSUFFICIENT_EVIDENCE"


def test_fuzz_same_cluster_repetition_never_compounds():
    rng = random.Random(7)
    for _ in range(100):
        base = _random_claim(rng, 0)
        base["source_cluster"] = "one-cluster"
        base["source_class"] = "CREDIBLE_MEDIA"
        base["evidence_refs"] = ["https://e/1"]
        base["layer"] = "CORE_FACT"
        base["branch"] = "core_event"
        base["direction"] = "SUPPORTS"
        copies = []
        for i in range(rng.randint(2, 8)):
            c = dict(base)
            c["claim_id"] = f"copy{i}"
            copies.append(c)
        one = nbi.evaluate_event_branches(
            nbi.normalize_claims([base]), None, []
        )["core_event"]["p"]
        many = nbi.evaluate_event_branches(
            nbi.normalize_claims(copies), None, []
        )["core_event"]["p"]
        assert many == one


def test_fuzz_missing_citation_never_raises():
    rng = random.Random(21)
    for _ in range(100):
        c = _random_claim(rng, 0)
        c["evidence_refs"] = []
        claims = nbi.normalize_claims([c])
        assert claims[0]["verification"] == "UNVERIFIED"
        branches = nbi.evaluate_event_branches(claims, None, [])
        for b in nbi.BRANCHES:
            assert branches[b]["p"] == branches[b]["prior"] or \
                branches[b]["status"].startswith("INSUFFICIENT")


# ---------------------------------------------------------------------------
# Invariants 6-8, 13: demote-only score chain
# ---------------------------------------------------------------------------


def test_fuzz_score_chain_demote_only():
    rng = random.Random(4321)
    for _ in range(200):
        report = nbi.build_event_report(_random_event(rng))
        assert report["invariants"]["final_leq_validated_all_tickers"] is True
        for t in report["tickers"]:
            assert t["FINAL_TICKER_SCORE"] <= t["VALIDATED_RELEVANCE"] + 1e-9
            assert t["VALIDATED_RELEVANCE"] <= t["BASE_RELEVANCE"] + 1e-9
            for name, m in t.get("multipliers", {}).items():
                assert 0.0 <= m <= 1.0, (name, m)
            assert t.get("price_bonus_capped", 1.0) <= nbi.PRICE_BONUS_CAP + 1e-9


def test_fuzz_adding_rumor_never_raises_any_ticker_score():
    rng = random.Random(555)
    for _ in range(60):
        event = _random_event(rng)
        # Keep the truth corpus fixed; add pure rumor noise on top.
        rumor_noise = []
        for i in range(rng.randint(1, 4)):
            c = _random_claim(rng, 100 + i)
            c["layer"] = "RUMOR"
            c["source_class"] = "SOCIAL_MEDIA"
            c["claim_magnitude"] = rng.uniform(6, 10)
            c["evidence_strength"] = rng.uniform(0, 2)
            c["evidence_refs"] = ["https://social/r"]
            rumor_noise.append(c)
        quiet = nbi.build_event_report(event)
        noisy_event = dict(event)
        noisy_event["claims"] = list(event["claims"]) + rumor_noise
        noisy = nbi.build_event_report(noisy_event)
        quiet_scores = {t["ticker"]: t["FINAL_TICKER_SCORE"]
                        for t in quiet["tickers"]}
        for t in noisy["tickers"]:
            assert t["FINAL_TICKER_SCORE"] <= quiet_scores[t["ticker"]] + 1e-9


# ---------------------------------------------------------------------------
# Invariants 9-12: state machine + price/liquidity fail-closed
# ---------------------------------------------------------------------------


def test_fuzz_dead_only_when_core_collapses():
    rng = random.Random(31337)
    for _ in range(200):
        report = nbi.build_event_report(_random_event(rng))
        core = report["branches"]["core_event"]["p"]
        if report["EVENT_STATE"] == "DEAD":
            assert core < nbi.CORE_DEAD_THRESHOLD
        if core >= nbi.CORE_STRONG_THRESHOLD and \
                report["EVENT_STATE"] == "TRANSFORMED":
            # A transformed narrative with a live core must never FOLD.
            assert report["ACTION"] != "FOLD"


def test_fuzz_no_price_data_is_never_actionable():
    rng = random.Random(777)
    for _ in range(150):
        report = nbi.build_event_report(_random_event(rng))
        for t in report["tickers"]:
            if t["price_validation"]["status"] != "COMPUTED":
                assert t["actionable"] is False
            if t.get("multipliers", {}).get("m_liquidity") == 0.0:
                assert t["FINAL_TICKER_SCORE"] == 0.0
        if report["ACTION"] == "ACT":
            assert report["scores"]["RUMOR_RISK"] < nbi.ACT_MAX_RUMOR
            assert any(t["actionable"] for t in report["tickers"])


# ---------------------------------------------------------------------------
# Invariant 14: persistence round-trip fidelity
# ---------------------------------------------------------------------------


def test_fuzz_store_round_trip_preserves_branch_probabilities(tmp_path):
    rng = random.Random(2026)
    db = tmp_path / "fuzz.db"
    for i in range(10):
        report = nbi.build_event_report(_random_event(rng))
        report["event_id"] = f"rt-{i}"
        store.save_nbi_report(report, db_path=db,
                              now_iso="2026-07-02T12:00:00+00:00")
        loaded = store.load_latest_report(f"rt-{i}", db)
        assert loaded is not None
        for b in nbi.BRANCHES:
            assert abs(loaded["branches"][b]["p"]
                       - report["branches"][b]["p"]) < 1e-9


# ---------------------------------------------------------------------------
# Invariant 15: calibration refuses insufficient evidence
# ---------------------------------------------------------------------------


def test_fuzz_calibration_always_refuses_below_threshold():
    rng = random.Random(808)
    for _ in range(50):
        n = rng.randint(0, 9)
        cases = [
            {
                "case_id": f"z{i}", "event_id": f"e{i}", "is_fixture": False,
                "resolution_timestamp": "2026-07-10T00:00:00+00:00",
                "resolution_labels": {
                    "outcome_label": rng.choice(
                        ["CORE_HELD_INTACT", "CORE_DIED"]
                    )
                },
                "branch_probabilities": {"core_event": rng.uniform(0, 1)},
            }
            for i in range(n)
        ]
        report = cal.build_nbi_calibration_report(cases=cases)
        # v1.4: 1-9 cases land in the CASE_ACCUMULATION band; both bands
        # withhold metrics and refuse fitting.
        assert report["status"] in (cal.STATUS_INSUFFICIENT,
                                    cal.STATUS_ACCUMULATION)
        assert report["metrics"]["brier"] is None
        assert report["fitted_weights"] is None
