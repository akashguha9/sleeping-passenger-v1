"""Shock engine: frozen-map custody, conviction ΔP, snapshot writing."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import prediction_market_shock_engine as pm


def test_map_hash_changes_on_edit():
    m1 = pm.fixture_frozen_map()
    assert pm.verify_event_equity_map(m1)["valid"] is True
    tampered = json.loads(json.dumps(m1))
    tampered["entries"][0]["exposure"] = 0.99   # post-hoc edit
    assert pm.verify_event_equity_map(tampered)["valid"] is False


def test_tampered_map_refuses_to_load(tmp_path: Path):
    m1 = pm.fixture_frozen_map()
    tampered = json.loads(json.dumps(m1))
    tampered["entries"][0]["capture_rate"] = 1.0
    p = tmp_path / "map.json"
    p.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="FROZEN_MAP_HASH_MISMATCH"):
        pm.load_frozen_map(p)


def test_new_version_chains_to_prior_hash():
    m1 = pm.fixture_frozen_map()
    m2 = pm.new_map_version(m1, m1["entries"], author="operator", day=1001)
    assert m2["version"] == m1["version"] + 1
    assert m2["prev_hash"] == m1["content_hash"]
    assert m2["content_hash"] != m1["content_hash"]
    assert pm.verify_event_equity_map(m2)["valid"] is True


def test_versioning_a_tampered_map_is_refused():
    m1 = pm.fixture_frozen_map()
    m1["entries"][0]["exposure"] = 0.75
    with pytest.raises(ValueError, match="FROZEN_MAP_HASH_MISMATCH"):
        pm.new_map_version(m1, m1["entries"], author="x", day=1001)


def test_depth_conviction_weights():
    w_deep, avail = pm.depth_conviction(1_000_000.0)
    assert avail is True and w_deep == 1.0
    w_thin, _ = pm.depth_conviction(500.0)
    assert 0.0 < w_thin < 1.0
    w_none, avail_none = pm.depth_conviction(None)
    assert w_none == 1.0 and avail_none is False


def test_fixture_shock_detected_with_conviction():
    shock = pm.detect_shock(pm.fixture_market())
    assert shock is not None
    assert shock.delta_p >= pm.DEFAULT_SHOCK_THRESHOLD
    assert shock.depth_available is True
    assert abs(shock.delta_p_conv) <= abs(shock.delta_p)
    assert shock.data_mode == pm.FIXTURE_DEMONSTRATION


def test_small_or_spiky_move_is_not_a_shock():
    quiet = {"market_id": "Q", "price_history": [
        {"day": d, "p": 0.5 + 0.001 * (d % 2)} for d in range(990, 1001)]}
    assert pm.detect_shock(quiet) is None
    spike = {"market_id": "S", "price_history": [
        {"day": 996, "p": 0.60}, {"day": 997, "p": 0.44},
        {"day": 998, "p": 0.60}, {"day": 999, "p": 0.60},
        {"day": 1000, "p": 0.60}]}
    assert pm.detect_shock(spike) is None


def test_fixture_shock_creates_forward_snapshots(tmp_path: Path):
    shock = pm.detect_shock(pm.fixture_market())
    rows = pm.build_forward_snapshots(shock, pm.fixture_frozen_map(),
                                      pm.fixture_equity_prices())
    assert {r["ticker"] for r in rows} == {"FIXA", "FIXB"}
    up = next(r for r in rows if r["ticker"] == "FIXA")
    down = next(r for r in rows if r["ticker"] == "FIXB")
    assert up["direction"] == "UP" and down["direction"] == "DOWN"
    for r in rows:
        assert r["outcome"] == pm.PENDING
        assert r["data_mode"] == pm.FIXTURE_DEMONSTRATION
        assert r["provenance"]["exposure_capture"] == "ANALYST_PRIOR"
        assert r["map_hash"]
    out = tmp_path / "forward_snapshots.jsonl"
    dry = pm.append_snapshots(out, rows, mode="dry_run")
    assert dry["written"] == 0 and not out.exists()
    wrote = pm.append_snapshots(out, rows, mode="write")
    assert wrote["written"] == len(rows)
    again = pm.append_snapshots(out, rows, mode="write")
    assert again["written"] == 0
    assert again["skipped_duplicates"] == len(rows)


def test_negative_shock_flips_mapped_direction():
    m = pm.fixture_market()
    m["price_history"] = [{"day": r["day"], "p": round(1.0 - r["p"], 4)}
                          for r in m["price_history"]]
    shock = pm.detect_shock(m)
    assert shock is not None and shock.delta_p < 0
    rows = pm.build_forward_snapshots(shock, pm.fixture_frozen_map(),
                                      pm.fixture_equity_prices())
    up_entry = next(r for r in rows if r["ticker"] == "FIXA")
    assert up_entry["direction"] == "DOWN"
