"""Syndication detector (surprise upgrade) + signal tournament proofs (Pass 5)."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from scripts import llm_grounding_guard as gg
from scripts import signal_tournament as st
from scripts import syndication_detector as syn

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 1, 1, tzinfo=UTC)

WIRE = "ACME Corp wins major defense contract worth $2 billion, sources say"


def _copies(n, claim=WIRE):
    return [{"evidence_id": f"EV-{i}", "symbol": "ACME", "confidence": 0.9,
             "freshness_days": 1.0, "claim": claim,
             "source_name": f"outlet_{i}"} for i in range(n)]


# ---------------------------------------------------------------------------
# Surprise upgrade acceptance: syndication collapse
# ---------------------------------------------------------------------------


def test_twenty_wire_copies_collapse_to_one_effective_source():
    result = syn.effective_sources(_copies(20))
    assert result["raw_count"] == 20
    assert result["effective_count"] == 1
    assert result["syndication_collapsed"] == 19
    assert len(result["clusters"][0]["outlets"]) == 20


def test_minor_editorial_rewrites_still_collapse():
    items = _copies(3) + [{
        "evidence_id": "EV-X", "symbol": "ACME", "confidence": 0.9,
        "freshness_days": 1.0, "source_name": "rewriter",
        "claim": "ACME Corp wins major defense contract worth $2 billion, "
                 "according to sources",
    }]
    assert syn.effective_sources(items)["effective_count"] == 1


def test_genuinely_distinct_stories_stay_independent():
    items = [
        {"evidence_id": "1", "claim": WIRE, "source_name": "a"},
        {"evidence_id": "2", "source_name": "b",
         "claim": "ACME quarterly filing shows 40% revenue growth in cloud"},
        {"evidence_id": "3", "source_name": "c",
         "claim": "ACME CFO resigns effective immediately amid audit"},
    ]
    assert syn.effective_sources(items)["effective_count"] == 3


def test_empty_text_items_stay_independent():
    items = [{"evidence_id": str(i), "claim": "", "source_name": "s"} for i in range(4)]
    assert syn.effective_sources(items)["effective_count"] == 4


def test_grounding_weight_with_20_syndicated_copies_equals_single_source():
    single = gg.ground_claim(claim=WIRE, symbol="ACME", base_weight=0.5,
                             evidence_items=_copies(1))
    syndicated = gg.ground_claim(claim=WIRE, symbol="ACME", base_weight=0.5,
                                 evidence_items=_copies(20))
    assert syndicated.weight == pytest.approx(single.weight)
    assert "syndicated copies collapsed" in syndicated.note


def test_independent_confirmations_still_beat_one_contradiction():
    """Three INDEPENDENT stories vs one contradiction keeps penalty 3/5;
    20 syndicated copies vs one contradiction is 1/3 — syndication can
    no longer outvote contradiction."""
    independent = [
        {"evidence_id": "1", "symbol": "ACME", "confidence": 0.9,
         "freshness_days": 1.0, "claim": "ACME wins defense contract", "source_name": "a"},
        {"evidence_id": "2", "symbol": "ACME", "confidence": 0.9,
         "freshness_days": 1.0, "claim": "ACME cloud revenue up 40 percent this quarter",
         "source_name": "b"},
        {"evidence_id": "3", "symbol": "ACME", "confidence": 0.9,
         "freshness_days": 1.0, "claim": "ACME announces buyback of five billion",
         "source_name": "c"},
        {"evidence_id": "C", "symbol": "ACME", "confidence": 0.9,
         "freshness_days": 1.0, "claim": "analyst disputes ACME contract value",
         "source_name": "d", "contradicts": True},
    ]
    indep = gg.ground_claim(claim="ACME outlook strong", symbol="ACME",
                            base_weight=0.5, evidence_items=independent)
    syndic = gg.ground_claim(claim="ACME outlook strong", symbol="ACME",
                             base_weight=0.5,
                             evidence_items=_copies(20) + [independent[-1]])
    assert indep.contradiction_penalty == pytest.approx(3 / 5)
    assert syndic.contradiction_penalty == pytest.approx(1 / 3)
    assert syndic.weight < indep.weight


def test_threshold_validation():
    with pytest.raises(ValueError):
        syn.cluster_claims([], threshold=0.0)


# ---------------------------------------------------------------------------
# Tournament + shadow ledger
# ---------------------------------------------------------------------------


def _samples(n=40):
    rows = []
    for i in range(n):
        rows.append({
            "signal_id": f"S{i}", "symbol": "SYN",
            "t_decision": (T0 + dt.timedelta(days=i)).isoformat(),
            "t_outcome": (T0 + dt.timedelta(days=i + 5)).isoformat(),
            "features": {"acqs": 0.8, "mean_model_score": 0.7,
                         "cross_model_agreement": 0.7, "why_today_score": 0.8,
                         "data_quality": 0.9, "freshness_score": 0.8,
                         "liquidity_quality": 0.7, "price_momentum": 0.6,
                         "grounded_weight": 0.5},
            "net_return": 0.01 if i % 3 else -0.02,
            "evidence_ids": [f"EV-{i}"],
        })
    return rows


def test_shadow_ledger_refuses_order_shaped_rows(tmp_path):
    path = tmp_path / "ledger.jsonl"
    for key in ("order_id", "broker", "broker_id", "execution_status",
                "fill_price", "order_type", "account_id"):
        with pytest.raises(st.LedgerContractError):
            st.append_shadow_observation({"variant": "x", key: "boom"}, path=path)
    assert not path.exists()  # nothing was written


def test_shadow_rows_carry_mandatory_advisory_stamps(tmp_path):
    path = tmp_path / "ledger.jsonl"
    st.append_shadow_observation({"variant": "x", "signal_id": "S1",
                                  "score": 0.5}, path=path)
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["NOT_AN_ORDER"] is True
    assert row["ADVISORY_ONLY"] is True
    assert row["HUMAN_REVIEW_REQUIRED"] is True
    assert row["broker_api_called"] is False


def test_tournament_ranks_out_of_sample_only(tmp_path):
    samples = _samples(40)
    # Poison the in-sample period with huge wins; OOS ranking must ignore it.
    for s in samples[:20]:
        s["net_return"] = 1.0
    result = st.run_tournament(
        samples, oos_start=(T0 + dt.timedelta(days=20)).isoformat(),
        ledger_path=tmp_path / "l.jsonl",
    )
    assert result["ranking_basis"] == "out_of_sample_only"
    prod = result["variants"]["production"]
    assert prod["in_sample_observations_excluded_from_ranking"] == 20
    # OOS expectancy reflects the modest OOS returns, not the poisoned 1.0s.
    assert prod["expectancy"] is None or prod["expectancy"] < 0.05


def test_variants_compared_on_same_guarded_window(tmp_path):
    samples = _samples(30)
    samples.append({  # leaked sample must be rejected for ALL variants
        "signal_id": "LEAK", "symbol": "SYN",
        "t_decision": (T0 + dt.timedelta(days=50)).isoformat(),
        "t_outcome": (T0 + dt.timedelta(days=50)).isoformat(),
        "features": {}, "net_return": 9.9,
    })
    result = st.run_tournament(
        samples, oos_start=(T0 + dt.timedelta(days=15)).isoformat(),
        ledger_path=tmp_path / "l.jsonl",
    )
    assert result["samples_rejected_by_temporal_guard"] == 1
    rows = [json.loads(l) for l in (tmp_path / "l.jsonl").read_text(
        encoding="utf-8").splitlines()]
    assert not any(r["signal_id"] == "LEAK" for r in rows)
    per_variant_counts = {}
    for r in rows:
        per_variant_counts[r["variant"]] = per_variant_counts.get(r["variant"], 0) + 1
    assert len(set(per_variant_counts.values())) == 1  # identical window


def test_small_sample_warning(tmp_path):
    result = st.run_tournament(
        _samples(10), oos_start=(T0 + dt.timedelta(days=5)).isoformat(),
        ledger_path=tmp_path / "l.jsonl",
    )
    assert all(m["small_sample_warning"] for m in result["variants"].values())


def test_report_renders_with_advisory_language(tmp_path):
    result = st.run_tournament(
        _samples(25), oos_start=(T0 + dt.timedelta(days=12)).isoformat(),
        ledger_path=tmp_path / "l.jsonl",
    )
    path = st.write_report(result, out_dir=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "NOT_AN_ORDER" in text and "out-of-sample only" in text
    for banned in ("guaranteed", "sure profit", "execute now", "place order"):
        assert banned not in text.lower()
