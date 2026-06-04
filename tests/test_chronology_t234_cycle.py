"""T2/T3/T4 detectors + full observation cycle + replay lab (observation-only).

Covers Phase-1 requirements: persistence threshold, contradiction/reversal,
outcome attribution vs OUTCOME_PENDING, honest provenance labelling, end-to-end
cycle writing observation events only, and the no-execution import boundary.
"""

import ast
import json
from pathlib import Path

from scripts import chronology_store as cs
from scripts import chronology_detectors as det
from scripts import run_observation_cycle as roc
from scripts import chronology_replay_lab as lab

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


# ---- T2 persistence -------------------------------------------------------

def test_t2_fires_only_after_repeated_t1_hits() -> None:
    res = det.detect_t2_asset_attachment([True, True, True], min_hits=3)
    assert res.detected is True and res.status == "FIRED"


def test_t2_fails_closed_below_threshold() -> None:
    res = det.detect_t2_asset_attachment([True, False], min_hits=3)
    assert res.status == "INSUFFICIENT_DATA"
    assert res.detected is False


def test_t2_no_fire_when_hits_under_min_but_enough_samples() -> None:
    res = det.detect_t2_asset_attachment([True, False, False, False], min_hits=3)
    assert res.status == "NO_FIRE"
    assert res.detected is False


# ---- T3 contradiction -----------------------------------------------------

def test_t3_fires_on_probability_reversal() -> None:
    res = det.detect_t3_commitment({"prob_series": [0.6, 0.4]})
    assert res.detected is True and "probability_reversal" in res.reason


def test_t3_fires_on_volume_collapse() -> None:
    res = det.detect_t3_commitment(
        {"prob_series": [0.5, 0.5], "volume_series": [1000, 1000, 1000, 10]}
    )
    assert res.detected is True and "volume_collapse" in res.reason


def test_t3_fails_closed_on_insufficient_fields() -> None:
    assert det.detect_t3_commitment({}).status == "INSUFFICIENT_DATA"
    assert det.detect_t3_commitment({"prob_series": [0.5]}).status == "INSUFFICIENT_DATA"


def test_t3_no_fire_on_stable_advance() -> None:
    res = det.detect_t3_commitment({"prob_series": [0.50, 0.52]})
    assert res.detected is False and res.status == "NO_FIRE"


# ---- T4 outcome attribution ----------------------------------------------

def test_t4_outcome_pending_when_outcome_missing() -> None:
    assert det.detect_t4_market_confirmation({}).status == "OUTCOME_PENDING"
    assert det.detect_t4_market_confirmation(
        {"outcome": {"resolved": False}}
    ).status == "OUTCOME_PENDING"


def test_t4_attributes_only_with_real_outcome_data() -> None:
    res = det.detect_t4_market_confirmation({"outcome": {"resolved": True, "realized": "YES"}})
    assert res.status == "OUTCOME_ATTRIBUTED" and res.detected is True
    assert res.evidence["logged_pnl_present"] is False  # never inferred


def test_t4_never_infers_pnl() -> None:
    res = det.detect_t4_market_confirmation(
        {"outcome": {"resolved": True, "realized": "NO", "logged_pnl": -12.5}}
    )
    assert res.evidence["logged_pnl"] == -12.5  # only because explicitly logged


# ---- replay lab provenance labelling --------------------------------------

def test_replay_defaults_unlabelled_to_synthetic() -> None:
    assert lab.classify_data_origin({}) == "SYNTHETIC_TEST"
    assert lab.classify_data_origin({"data_origin": "nonsense"}) == "SYNTHETIC_TEST"


def test_replay_respects_declared_labels_without_upgrading() -> None:
    assert lab.classify_data_origin({"data_origin": "HISTORICAL_BACKFILL"}) == "HISTORICAL_BACKFILL"
    assert lab.classify_data_origin({"data_origin": "forward_real"}) == "FORWARD_REAL"


def _seed(conn, candidate_id, payload):
    cs.log_signal_candidate(conn, {
        "candidate_id": candidate_id, "ticker": "AAA", "first_seen_ts": "t",
        "source": "test", "payload_json": json.dumps(payload),
    })


def test_replay_does_not_earn_confidence_on_synthetic_data(tmp_path) -> None:
    conn = cs.get_connection(tmp_path / "r.db")
    cs.init_schema(conn)
    _seed(conn, "c1", {"data_origin": "SYNTHETIC_TEST", "prob_series": [0.1] * 8, "volume": 9000})
    report = lab.build_replay_report(conn)
    assert report["forward_real_count"] == 0
    assert report["earned_forward_confidence"] is False
    assert report["observation_state"] == "STRUCTURAL_REPLAY_ONLY"
    conn.close()


def test_replay_counts_forward_real_separately(tmp_path) -> None:
    conn = cs.get_connection(tmp_path / "r2.db")
    cs.init_schema(conn)
    _seed(conn, "c1", {"data_origin": "FORWARD_REAL", "prob_series": [0.1] * 8, "volume": 9000})
    _seed(conn, "c2", {"data_origin": "HISTORICAL_BACKFILL", "prob_series": [0.1] * 8, "volume": 9000})
    report = lab.build_replay_report(conn)
    assert report["origin_counts"]["FORWARD_REAL"] == 1
    assert report["origin_counts"]["HISTORICAL_BACKFILL"] == 1
    assert report["earned_forward_confidence"] is True
    conn.close()


# ---- full observation cycle ----------------------------------------------

def test_cycle_writes_observation_events_only(tmp_path) -> None:
    conn = cs.get_connection(tmp_path / "cyc.db")
    cs.init_schema(conn)
    rising = [0.10, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.36]
    _seed(conn, "cfire", {"prob_series": rising, "volume": 9000,
                          "outcome": {"resolved": True, "realized": "YES"}})
    summary = roc.run_full_observation_cycle(conn)
    assert summary["status"] == "OBSERVED"
    assert summary["evaluated"] == 1
    assert summary["t1_fired"] == 1
    assert summary["t4_attributed"] == 1
    # One event per detector (T1..T4) for the single candidate.
    n_events = conn.execute("SELECT COUNT(*) FROM chronology_events").fetchone()[0]
    assert n_events == 4
    # pattern_hit_rates recomputed honestly from events.
    rates = dict(conn.execute(
        "SELECT pattern_id, hits_count FROM pattern_hit_rates").fetchall())
    assert rates["T1_event_prior"] == 1
    assert rates["T4_outcome"] == 1
    conn.close()


def test_cycle_fails_closed_on_empty(tmp_path) -> None:
    conn = cs.get_connection(tmp_path / "empty.db")
    cs.init_schema(conn)
    assert roc.run_full_observation_cycle(conn)["status"] == "NO_CANDIDATES"
    assert conn.execute("SELECT COUNT(*) FROM chronology_events").fetchone()[0] == 0
    conn.close()


def test_t2_accumulates_across_repeated_cycles(tmp_path) -> None:
    conn = cs.get_connection(tmp_path / "acc.db")
    cs.init_schema(conn)
    rising = [0.10, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.36]
    _seed(conn, "crepeat", {"prob_series": rising, "volume": 9000})
    # Run the cycle 3 times -> 3 T1 fires accumulate -> T2 should fire on run 3.
    for _ in range(3):
        roc.run_full_observation_cycle(conn)
    t2_rows = conn.execute(
        "SELECT payload_json FROM chronology_events WHERE event_class='T2_persistence' ORDER BY id"
    ).fetchall()
    last = json.loads(t2_rows[-1][0])
    assert last["detected"] is True
    conn.close()


# ---- safety boundary ------------------------------------------------------

def test_no_execution_or_broker_imports_in_new_chronology_modules() -> None:
    forbidden = ("action_engine", "broker", "execution_governance", "paper_execution",
                 "ibkr", "order")
    for stem in ("run_observation_cycle", "chronology_replay_lab", "chronology_detectors"):
        tree = ast.parse((SCRIPTS / f"{stem}.py").read_text(encoding="utf-8-sig"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
                imported += [f"{node.module}.{a.name}" for a in node.names]
        joined = " ".join(imported).lower()
        for bad in forbidden:
            assert bad not in joined, f"{stem} must not import {bad}"


def test_no_detector_emits_forbidden_action_terms() -> None:
    for stem in ("chronology_detectors", "run_observation_cycle", "chronology_replay_lab"):
        src = (SCRIPTS / f"{stem}.py").read_text(encoding="utf-8-sig")
        for token in ('"BUY"', '"SELL"', '"ENTER"', '"EXECUTE"', '"ORDER"', "place_order"):
            assert token not in src, f"{stem} must stay observation-only ({token})"
