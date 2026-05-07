import shutil
import uuid
from pathlib import Path

from scripts.contextual_interpretation import (
    build_context_profile,
    build_contextual_interpretation_summary,
    default_operator_lenses,
    interpret_signal,
)


def test_same_raw_signal_produces_different_meanings_under_different_lenses() -> None:
    raw_signal = {
        "signal_id": "spike-1",
        "price_move_intensity": 0.9,
        "narrative_acceleration": 0.85,
        "minimum_validation": 0.5,
        "liquidity_fragility": 0.8,
        "momentum": 0.7,
        "sentiment_divergence": 0.75,
    }
    packet = interpret_signal(
        raw_signal,
        context_profile=build_context_profile(raw_signal, {"execution_policy": {"allow_new_risk": True}}),
        operator_lenses=default_operator_lenses(),
        runtime_state={"execution_policy": {"allow_new_risk": True}},
    )
    labels = {row.meaning_label for row in packet.lens_interpretations}
    assert "BREAKOUT" in labels
    assert "LIQUIDITY_GRAB" in labels or "STOP_RUN" in labels
    assert len(labels) > 1


def test_high_drift_recommends_block_or_reduce_size() -> None:
    raw_signal = {
        "signal_id": "spike-2",
        "price_move_intensity": 0.9,
        "narrative_acceleration": 0.9,
        "minimum_validation": 0.15,
        "liquidity_fragility": 0.9,
        "momentum": 0.2,
        "sentiment_divergence": 0.95,
    }
    packet = interpret_signal(
        raw_signal,
        context_profile=build_context_profile(raw_signal, {"execution_policy": {"allow_new_risk": True}}),
        operator_lenses=default_operator_lenses(),
        drift_threshold=0.2,
        runtime_state={"execution_policy": {"allow_new_risk": True}},
    )
    assert packet.interpretation_drift > 0.2
    assert packet.recommended_action in {"REDUCE_SIZE", "BLOCK"}
    assert packet.chaos_veto is True


def test_runtime_artifacts_are_written_correctly() -> None:
    tmp_path = Path("tests") / "_tmp_runtime" / f"contextual-{uuid.uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    summary = build_contextual_interpretation_summary(
        [
            {
                "signal_id": "abc",
                "price_move_intensity": 0.7,
                "narrative_acceleration": 0.5,
                "minimum_validation": 0.7,
            }
        ],
        runtime_state={"execution_policy": {"allow_new_risk": True}},
        write_runtime=True,
        artifact_paths={
            "context_profile": tmp_path / "context_profile_report.json",
            "interpretation_packet": tmp_path / "interpretation_packet_report.json",
            "interpretation_drift": tmp_path / "interpretation_drift_report.json",
            "reality_rendering": tmp_path / "reality_rendering_report.json",
            "failure_log": tmp_path / "interpretation_failure_log.jsonl",
            "summary": tmp_path / "contextual_interpretation_summary.json",
        },
    )
    assert summary["total_signals"] == 1
    for filename in (
        "context_profile_report.json",
        "interpretation_packet_report.json",
        "interpretation_drift_report.json",
        "reality_rendering_report.json",
        "contextual_interpretation_summary.json",
        "interpretation_failure_log.jsonl",
    ):
        path = tmp_path / filename
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "run_id" in text
    shutil.rmtree(tmp_path, ignore_errors=True)
