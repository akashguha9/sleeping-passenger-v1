from scripts.contextual_interpretation.context_profile import build_context_profile


def test_build_context_profile_derives_chaos_regime_from_signal_and_policy() -> None:
    profile = build_context_profile(
        {"chaos_score": 0.81, "spread_score": 0.8, "session": "eu"},
        {"execution_policy": {"allow_new_risk": True}, "truth_origin": "seeded"},
    )
    assert profile.regime == "CHAOS"
    assert profile.spread == "WIDE"
    assert profile.session == "EU"


def test_build_context_profile_uses_seeded_defaults() -> None:
    profile = build_context_profile({}, {"execution_policy": {"allow_new_risk": False}})
    assert profile.regime == "CHAOS"
    assert profile.data_truth_origin == "SEEDED"
