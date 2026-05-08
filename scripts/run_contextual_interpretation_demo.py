from __future__ import annotations

import argparse
import json

try:
    from scripts.contextual_interpretation_engine import (
        CommunicationCodeType,
        RawInterpretationInput,
        SignalChannel,
        interpret_signal,
    )
except ModuleNotFoundError:
    from contextual_interpretation_engine import (  # type: ignore[no-redef]
        CommunicationCodeType,
        RawInterpretationInput,
        SignalChannel,
        interpret_signal,
    )


def demo_uno_recent_learner() -> RawInterpretationInput:
    return RawInterpretationInput(
        signal_id="demo_uno_recent_learner",
        source="demo",
        observed_event="recent UNO learner wins quickly under complex table conditions",
        channel=SignalChannel.PERFORMANCE_CHANNEL,
        code_type=CommunicationCodeType.PERFORMANCE_SIGNAL,
        signal_clarity=0.82,
        context_completeness=0.70,
        observed_performance=0.86,
        expected_baseline=0.35,
        exposure_time=0.15,
        task_difficulty=0.78,
        environment_complexity=0.72,
        constraint_burden=0.18,
        receiver_channel_match=0.80,
        receiver_shared_context=0.68,
        receiver_decoder_skill=0.72,
        repeatability=0.28,
        stress_survival=0.42,
        context_transferability=0.25,
        alternative_explanation_strength=0.36,
        randomness_risk=0.26,
        sample_size_risk=0.62,
    )


def demo_non_verbal_humour() -> RawInterpretationInput:
    return RawInterpretationInput(
        signal_id="demo_non_verbal_humour",
        source="demo",
        observed_event="non-verbal humour lands despite language constraint",
        channel=SignalChannel.NON_VERBAL,
        code_type=CommunicationCodeType.PERSONAL_SIGNAL,
        signal_clarity=0.78,
        context_completeness=0.74,
        observed_performance=0.80,
        expected_baseline=0.48,
        exposure_time=0.30,
        task_difficulty=0.70,
        environment_complexity=0.64,
        constraint_burden=0.58,
        receiver_channel_match=0.72,
        receiver_shared_context=0.66,
        receiver_decoder_skill=0.70,
        repeatability=0.34,
        stress_survival=0.44,
        context_transferability=0.31,
        alternative_explanation_strength=0.28,
        randomness_risk=0.22,
        sample_size_risk=0.35,
    )


def demo_receiver_failure() -> RawInterpretationInput:
    return RawInterpretationInput(
        signal_id="demo_receiver_failure",
        source="demo",
        observed_event="local joke fails because receiver lacks shared code",
        channel=SignalChannel.LOCAL_CODE,
        code_type=CommunicationCodeType.PERSONAL_SIGNAL,
        signal_clarity=0.88,
        context_completeness=0.62,
        observed_performance=0.74,
        expected_baseline=0.46,
        exposure_time=0.24,
        task_difficulty=0.60,
        environment_complexity=0.55,
        constraint_burden=0.30,
        receiver_channel_match=0.20,
        receiver_shared_context=0.12,
        receiver_decoder_skill=0.16,
        repeatability=0.42,
        stress_survival=0.38,
        context_transferability=0.26,
        alternative_explanation_strength=0.24,
        randomness_risk=0.18,
        sample_size_risk=0.32,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic contextual interpretation demos.")
    parser.add_argument("--json", action="store_true", help="Print full JSON results.")
    args = parser.parse_args()

    demos = [
        demo_uno_recent_learner(),
        demo_non_verbal_humour(),
        demo_receiver_failure(),
    ]
    results = [interpret_signal(row) for row in demos]

    if args.json:
        print(json.dumps([row.to_dict() for row in results], indent=2))
        return 0

    for row in results:
        payload = row.to_dict()
        main_guardrail = "none"
        if payload["recommended_action"] == "CHAOS_HOLD":
            main_guardrail = "chaos_override"
        elif payload["durability_score"] < 0.50:
            main_guardrail = "durability_not_proven"
        elif payload["alternative_explanation_risk"] >= 0.70:
            main_guardrail = "alternative_explanation_risk"
        elif payload["receiver_sensitivity_score"] < 0.30:
            main_guardrail = "receiver_decoder_mismatch"
        print(
            " | ".join(
                [
                    f"signal_id={payload['signal_id']}",
                    f"meaning_type={payload['meaning_type']}",
                    f"meaning_confidence={payload['meaning_confidence']:.3f}",
                    f"meaning_score={payload['meaning_score']:.3f}",
                    f"learning_velocity_score={payload['learning_velocity_score']:.3f}",
                    f"latent_capability_score={payload['latent_capability_score']:.3f}",
                    f"constraint_normalized_score={payload['constraint_normalized_score']:.3f}",
                    f"receiver_sensitivity_score={payload['receiver_sensitivity_score']:.3f}",
                    f"alternative_explanation_risk={payload['alternative_explanation_risk']:.3f}",
                    f"durability_score={payload['durability_score']:.3f}",
                    f"promotion_score={payload['promotion_score']:.3f}",
                    f"recommended_action={payload['recommended_action']}",
                    f"bull_state={payload['bull_state']}",
                    f"main_guardrail={main_guardrail}",
                ]
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
