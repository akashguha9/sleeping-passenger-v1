from scripts.contextual_interpretation.reality_renderer import render_reality_packet


def _packet() -> dict:
    return {
        "signal_id": "abc",
        "selected_interpretation": "BREAKOUT",
        "interpretation_drift": 0.2,
        "interpretation_confidence": 0.73,
        "recommended_action": "ALLOW",
        "chaos_veto": False,
        "reason_codes": ["RAW_SIGNAL_INTERPRETED"],
        "context_profile": {"regime": "NORMAL", "liquidity": "DEEP", "spread": "TIGHT"},
        "lens_interpretations": [
            {"lens_name": "Retail", "meaning_label": "BREAKOUT", "meaning_score": 0.8},
            {"lens_name": "Institution", "meaning_label": "ACCUMULATION", "meaning_score": 0.6},
        ],
        "raw_signal": {
            "entry_condition": "CONFIRM_BREAK",
            "invalidation": "LOSE_LEVEL",
            "exit_logic": "TAKE_PARTIALS",
        },
    }


def test_reality_renderer_changes_output_by_mode() -> None:
    scout = render_reality_packet(_packet(), mode="scout").to_dict()
    execute = render_reality_packet(_packet(), mode="execute").to_dict()
    risk = render_reality_packet(_packet(), mode="risk").to_dict()
    assert "possible_meanings" in scout["payload"]
    assert "entry" in execute["payload"]
    assert "interpretation_confidence" in execute["payload"]
    assert "ambiguity" in risk["payload"]
