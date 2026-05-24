"""Tests for the canonical live source registry."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from scripts.live_source_registry import (
    ADAPTER_IMPLEMENTED,
    ADAPTER_PARTIAL,
    ADAPTER_PLANNED,
    ADVISORY_STATUS,
    ALL_SOURCE_KEYS,
    DEFAULT_REFRESH_HOURS,
    EXECUTION_GATE_LOCKED,
    build_refresh_plan,
    detect_source_credential_state,
    get_source_family,
    list_live_source_families,
)


EXPECTED_SOURCE_KEYS = (
    "polymarket",
    # Kalshi sits beside Polymarket as a first-class prediction-market
    # source.  Added in the Kalshi read-only adapter sprint.
    "kalshi",
    "gdelt",
    "sec_edgar",
    "newsapi",
    "event_registry",
    "etherscan",
    "grok_xai",
    "market_data",
    "india",
    "global_filings",
    "asia_disclosure",
    # Derived signal — Polymarket × Kalshi disagreement scanner.  Added
    # in the prediction-market closure sprint so source-health/never-run/
    # stale state are reported alongside other sources.
    "prediction_market_disagreement",
)


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------


def test_all_source_families_present_in_canonical_order() -> None:
    families = list_live_source_families()
    keys = tuple(f["source_key"] for f in families)
    assert keys == EXPECTED_SOURCE_KEYS
    assert ALL_SOURCE_KEYS == EXPECTED_SOURCE_KEYS
    assert len(families) == len(EXPECTED_SOURCE_KEYS)


def test_every_source_has_six_hour_default_cadence() -> None:
    for family in list_live_source_families():
        assert family["default_refresh_hours"] == 6
        assert family["default_refresh_hours"] == DEFAULT_REFRESH_HOURS


def test_every_source_is_advisory_only_and_locked() -> None:
    for family in list_live_source_families():
        assert family["advisory_only"] is True
        assert family["can_execute"] is False


def test_every_source_declares_a_known_adapter_status() -> None:
    allowed = {ADAPTER_IMPLEMENTED, ADAPTER_PARTIAL, ADAPTER_PLANNED}
    for family in list_live_source_families():
        assert family["adapter_status"] in allowed


def test_partial_status_is_documented_when_used() -> None:
    families = {f["source_key"]: f for f in list_live_source_families()}
    # global_filings is intentionally partial — ASX implemented, others
    # placeholders. The registry must not claim it as fully implemented.
    assert families["global_filings"]["adapter_status"] == ADAPTER_PARTIAL


def test_asia_disclosure_status_is_partial() -> None:
    """Asia Disclosure is now partial: EDINET (Japan) + OpenDART (Korea) are
    wired as live official-API sub-sources, while the legacy SSE/SZSE/HKEX/
    TDnet/SGX/dart entries remain placeholders.  ADAPTER_PLANNED must NOT
    be used for asia_disclosure any more."""
    families = {f["source_key"]: f for f in list_live_source_families()}
    assert families["asia_disclosure"]["adapter_status"] == ADAPTER_PARTIAL


# ---------------------------------------------------------------------------
# get_source_family
# ---------------------------------------------------------------------------


def test_get_source_family_returns_a_copy() -> None:
    entry = get_source_family("polymarket")
    entry["display_name"] = "MUTATED"
    # Mutating the copy should not affect the registry.
    fresh = get_source_family("polymarket")
    assert fresh["display_name"] != "MUTATED"


def test_get_source_family_unknown_raises() -> None:
    with pytest.raises(KeyError):
        get_source_family("totally_made_up_source")


def test_get_source_family_empty_key_raises() -> None:
    with pytest.raises(KeyError):
        get_source_family("")


# ---------------------------------------------------------------------------
# Credential detection
# ---------------------------------------------------------------------------


def test_credential_state_redacts_values_completely() -> None:
    env = {
        "XAI_API_KEY": "xai-supersecret1234567890",
        "NEWS_API_KEY": "news-supersecret",
        "ETHERSCAN_API_KEY": "ethsupersecret",
        "EVENT_REGISTRY_API_KEY": "er-supersecret",
        "SEC_USER_AGENT": "Sleeping Passenger / akashguha@example.com",
    }
    state = detect_source_credential_state(env=env)
    for entry in state.values():
        # No state entry should leak the secret value anywhere.
        for k, v in entry.items():
            assert "supersecret" not in str(v), f"Secret value leaked into {k}"
            assert "xai-" not in str(v), f"xai- key prefix leaked into {k}"


def test_credential_state_marks_missing_keys() -> None:
    state = detect_source_credential_state(env={})
    assert state["newsapi"]["configured"] is False
    assert state["newsapi"]["missing_env_keys"] == ["NEWS_API_KEY"]
    assert state["grok_xai"]["configured"] is False
    assert "XAI_API_KEY" in state["grok_xai"]["missing_env_keys"]


def test_credential_state_passes_when_all_keys_present() -> None:
    env = {
        "XAI_API_KEY": "x",
        "NEWS_API_KEY": "x",
        "ETHERSCAN_API_KEY": "x",
        "EVENT_REGISTRY_API_KEY": "x",
        "SEC_USER_AGENT": "x",
    }
    state = detect_source_credential_state(env=env)
    assert state["grok_xai"]["configured"] is True
    assert state["newsapi"]["configured"] is True
    assert state["etherscan"]["configured"] is True
    assert state["event_registry"]["configured"] is True


def test_credential_state_keyless_sources_are_always_configured() -> None:
    state = detect_source_credential_state(env={})
    # Polymarket, GDELT, market_data, india, global_filings, asia_disclosure
    # require no API key — they should be reported as configured even with
    # an empty env.
    for key in ("polymarket", "gdelt", "market_data", "india",
                "global_filings", "asia_disclosure"):
        assert state[key]["configured"] is True, key


# ---------------------------------------------------------------------------
# Refresh plan
# ---------------------------------------------------------------------------


def test_refresh_plan_default_includes_all_sources_in_canonical_order() -> None:
    plan = build_refresh_plan(env={})
    assert plan["cadence_hours"] == 6
    assert plan["requested_source_keys"] == list(EXPECTED_SOURCE_KEYS)
    assert set(plan["implemented"]).issubset(set(EXPECTED_SOURCE_KEYS))
    # asia_disclosure is now PARTIAL (EDINET + OpenDART live; rest
    # placeholder).  global_filings is also partial.
    assert "asia_disclosure" in plan["partial"]
    assert "global_filings" in plan["partial"]
    assert "asia_disclosure" not in plan["planned"]


def test_refresh_plan_advisory_safety_stamps_present_per_entry() -> None:
    plan = build_refresh_plan(env={})
    for entry in plan["entries"]:
        assert entry["advisory_status"] == ADVISORY_STATUS
        assert entry["execution_gate"] == EXECUTION_GATE_LOCKED
        assert entry["broker_api_called"] is False
        assert entry["ai_execution_count"] == 0
        assert entry["human_review_required"] is True


def test_refresh_plan_advisory_stamps_on_envelope() -> None:
    plan = build_refresh_plan(env={})
    assert plan["advisory_status"] == ADVISORY_STATUS
    assert plan["execution_gate"] == EXECUTION_GATE_LOCKED
    assert plan["broker_api_called"] is False
    assert plan["ai_execution_count"] == 0
    assert plan["human_review_required"] is True
    assert plan["dry_run_supported"] is True


def test_refresh_plan_skips_sources_with_missing_credentials() -> None:
    plan = build_refresh_plan(env={})  # empty env -> all paid sources skipped
    skipped = set(plan["skipped_missing_creds"])
    for required in ("newsapi", "event_registry", "etherscan", "grok_xai"):
        assert required in skipped, required


def test_refresh_plan_single_source_selection() -> None:
    plan = build_refresh_plan(["polymarket"], env={})
    assert plan["requested_source_keys"] == ["polymarket"]
    assert len(plan["entries"]) == 1
    assert plan["entries"][0]["source_key"] == "polymarket"


def test_refresh_plan_unknown_source_raises() -> None:
    with pytest.raises(KeyError):
        build_refresh_plan(["polymarket", "not_real"], env={})


def test_refresh_plan_partial_source_not_claimed_implemented() -> None:
    """Asia Disclosure must be reported as PARTIAL (real sub-sources for
    Japan/Korea, placeholders elsewhere), never as fully implemented and
    never as fully planned."""
    plan = build_refresh_plan(["asia_disclosure"], env={})
    assert plan["partial"] == ["asia_disclosure"]
    assert plan["implemented"] == []
    assert plan["planned"] == []
    assert plan["entries"][0]["adapter_status"] == ADAPTER_PARTIAL


def test_refresh_plan_dedupes_and_preserves_canonical_order() -> None:
    plan = build_refresh_plan(["GDELT", "polymarket", "gdelt"], env={})
    # Canonical order says polymarket then gdelt.
    assert plan["requested_source_keys"] == ["polymarket", "gdelt"]


def test_refresh_plan_cadence_default_is_six_hours() -> None:
    plan = build_refresh_plan(env={})
    assert plan["cadence_hours"] == 6


def test_refresh_plan_explicit_cadence_respected() -> None:
    plan = build_refresh_plan(["polymarket"], cadence_hours=12, env={})
    assert plan["cadence_hours"] == 12


def test_refresh_plan_no_secret_value_appears_anywhere() -> None:
    env = {"XAI_API_KEY": "xai-shouldnotleak-1234567890ABCDEF"}
    plan = build_refresh_plan(env=env)
    flat = repr(plan)
    assert "shouldnotleak" not in flat
    assert "xai-shouldnotleak" not in flat
