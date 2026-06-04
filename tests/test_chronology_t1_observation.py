"""Real T1 event-prior detector + observation runner (observation-only).

Verifies T1 fires/does-not-fire correctly, fails closed on inadequate data,
and that the runner writes observation events/stats ONLY — no execution, no
broker import, no action authorization.
"""

import ast
import json
from pathlib import Path

from scripts import chronology_store as cs
from scripts.chronology_detectors import detect_t1_event_prior
from scripts import chronology_observation_runner as runner

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _rising_series():
    # 6 calm prior steps (~+0.01 each) then a sharp +0.20 jump on the last step.
    return [0.10, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.36]


def test_t1_fires_on_strong_anomalous_jump_with_volume() -> None:
    result = detect_t1_event_prior({"prob_series": _rising_series(), "volume": 5000})
    assert result.available is True
    assert result.detected is True
    assert result.status == "FIRED"
    assert result.evidence["prob_delta"] >= 0.05
    assert result.evidence["z_score"] >= 2.0


def test_t1_does_not_fire_below_prob_delta() -> None:
    # Tiny final step -> prob_delta below floor.
    series = [0.10, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.163]
    result = detect_t1_event_prior({"prob_series": series, "volume": 5000})
    assert result.detected is False
    assert result.status == "NO_FIRE"
    assert "prob_delta_below_floor" in result.reason


def test_t1_does_not_fire_below_volume_floor() -> None:
    result = detect_t1_event_prior(
        {"prob_series": _rising_series(), "volume": 0.0}, volume_floor=1.0
    )
    assert result.detected is False
    assert result.status == "NO_FIRE"
    assert "volume_below_floor" in result.reason


def test_t1_insufficient_sample_for_zscore() -> None:
    result = detect_t1_event_prior({"prob_series": [0.1, 0.2, 0.4], "volume": 5000})
    assert result.available is True
    assert result.detected is False
    assert result.status == "INSUFFICIENT_DATA"


def test_t1_fails_closed_on_missing_data() -> None:
    for bad in (None, {}, {"volume": 10}, {"prob_series": "nope", "volume": 10}):
        result = detect_t1_event_prior(bad)
        assert result.detected is False
        assert result.status == "INSUFFICIENT_DATA"


def test_t1_zero_variance_prior_is_insufficient() -> None:
    # Flat prior (no variance) then a jump -> z-score undefined -> fail closed.
    series = [0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.5]
    result = detect_t1_event_prior({"prob_series": series, "volume": 5000})
    assert result.status == "INSUFFICIENT_DATA"


def test_runner_writes_observation_events_only(tmp_path: Path) -> None:
    conn = cs.get_connection(tmp_path / "obs.db")
    cs.init_schema(conn)
    # One firing candidate, one non-firing candidate.
    cs.log_signal_candidate(conn, {
        "candidate_id": "c_fire", "ticker": "AAA", "first_seen_ts": "t",
        "source": "test",
        "payload_json": json.dumps({"prob_series": _rising_series(), "volume": 9000}),
    })
    cs.log_signal_candidate(conn, {
        "candidate_id": "c_flat", "ticker": "BBB", "first_seen_ts": "t",
        "source": "test",
        "payload_json": json.dumps({"prob_series": [0.1, 0.2, 0.3], "volume": 9000}),
    })

    summary = runner.run_observation_cycle(conn)
    assert summary["status"] == "OBSERVED"
    assert summary["evaluated"] == 2
    assert summary["fired"] == 1
    assert summary["insufficient"] == 1

    events = conn.execute("SELECT COUNT(*) FROM chronology_events").fetchone()[0]
    assert events == 2  # one observation event per candidate
    rate = conn.execute(
        "SELECT hit_rate, observations_count, hits_count FROM pattern_hit_rates "
        "WHERE pattern_id='T1_event_prior'"
    ).fetchone()
    assert rate == (0.5, 2, 1)
    conn.close()


def test_runner_fails_closed_on_empty_db(tmp_path: Path) -> None:
    conn = cs.get_connection(tmp_path / "empty.db")
    cs.init_schema(conn)
    summary = runner.run_observation_cycle(conn)
    assert summary["status"] == "NO_CANDIDATES"
    assert summary["evaluated"] == 0
    assert conn.execute("SELECT COUNT(*) FROM chronology_events").fetchone()[0] == 0
    conn.close()


def test_no_execution_or_broker_imports_in_chronology_code() -> None:
    forbidden = ("action_engine", "broker", "execution_governance", "paper_execution")
    for stem in ("chronology_observation_runner", "chronology_detectors", "chronology_store"):
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


def test_chronology_code_has_no_buy_enter_language() -> None:
    for stem in ("chronology_observation_runner", "chronology_detectors"):
        src = (SCRIPTS / f"{stem}.py").read_text(encoding="utf-8-sig")
        for token in ('"BUY"', '"ENTER"', "place_order", "submit_order"):
            assert token not in src, f"{stem} must stay observation-only ({token})"
