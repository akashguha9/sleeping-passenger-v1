from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline


def test_contextual_interpretation_layer_is_optional_and_backward_compatible() -> None:
    baseline = run_diagnostics_pipeline(write_runtime=False)
    contextual = run_diagnostics_pipeline(
        write_runtime=False,
        include_contextual_interpretation=True,
        contextual_interpretation_summary=True,
    )
    assert baseline.get("contextual_interpretation_enabled", False) is False
    assert contextual["contextual_interpretation_enabled"] is True
    assert contextual["interpretation_validation_input_mode"] == "INTERPRETED_PAYLOAD"
    assert contextual["policy"]["policy_state"] == baseline["policy"]["policy_state"]


def test_interpreted_payload_is_validation_input_when_enabled() -> None:
    report = run_diagnostics_pipeline(
        write_runtime=False,
        include_contextual_interpretation=True,
        interpretation_drift_threshold=0.3,
        render_operator_mode="execute",
    )
    packet = report["contextual_interpretation_report"]["example_interpretation_packet"]
    assert packet is not None
    assert packet["signal_id"]
    assert "reason_codes" in packet
    assert report["interpretation_validation_input_mode"] == "INTERPRETED_PAYLOAD"
    assert report["contextual_interpretation_report"]["rendered_reality_packets"][0]["payload"].get(
        "interpretation_confidence"
    ) is not None
