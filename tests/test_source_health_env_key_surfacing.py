"""Source-health actionable_next_step must surface exact env-key names
for the four config-gated sources operators most often forget:

* SEC EDGAR (``SEC_USER_AGENT`` + either ``SEC_DEFAULT_CIK`` or
  ``SEC_DEFAULT_WATCHLIST`` / ``SEC_USE_DEFAULT_WATCHLIST``)
* Etherscan public-tx (``ETHERSCAN_API_KEY`` + address fallbacks
  ``ETHERSCAN_ADDRESS`` / ``ETHEREUM_ADDRESS`` / ``PUBLIC_ETH_ADDRESS``)
* GDELT (``GDELT_TIMEOUT_SECONDS``)

Invariants this module locks in:

* Naming exact env keys must not flip an unhealthy source healthy.
* Core stale / failed sources remain FAIL-loud (``core_stale`` /
  ``refresh_error``).
* Optional missing config remains a soft WARN
  (``optional_config_missing``).
* Planned adapters remain INFO-only.
* No trading / execution / broker language leaks into the message.
"""
from __future__ import annotations

from scripts import source_health_score as shs


def _entry(**overrides) -> dict:
    base = {
        "source_key": "x",
        "tier": "core",
        "adapter_status": "implemented",
        "freshness_state": "fresh",
        "credential_configured": True,
        "hours_since_last_success": 1.0,
        "refresh_age_hours": 1.0,
        "last_refresh_error": "",
        "last_refresh_skipped": False,
        "last_refresh_skipped_reason": "",
        "last_refresh_success": True,
        "missing_env_keys": [],
        "requires_api_key": False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# SEC EDGAR config gate
# ---------------------------------------------------------------------------


def test_sec_required_missing_lists_cik_and_watchlist_env_keys() -> None:
    r = shs.score_source(
        _entry(
            source_key="sec_edgar",
            tier="core",
            credential_configured=False,
            freshness_state="skipped",
            missing_env_keys=["SEC_USER_AGENT"],
            requires_api_key=True,
        )
    )
    step = r["actionable_next_step"]
    assert step.startswith("core_or_secondary_config_missing")
    for env_key in (
        "SEC_USER_AGENT",
        "SEC_DEFAULT_CIK",
        "SEC_DEFAULT_WATCHLIST",
        "SEC_USE_DEFAULT_WATCHLIST",
    ):
        assert env_key in step, f"missing env-key hint {env_key!r}"
    # required_missing remains a real failure — not flipped to healthy.
    assert r["config_state"] == "required_missing"
    assert r["health_label"] != shs.LABEL_HEALTHY


def test_sec_skipped_with_reason_appends_env_key_hints() -> None:
    r = shs.score_source(
        _entry(
            source_key="sec_edgar",
            tier="secondary",
            credential_configured=True,
            freshness_state="skipped",
            last_refresh_skipped=True,
            last_refresh_skipped_reason="no CIK or watchlist configured",
        )
    )
    step = r["actionable_next_step"]
    assert step.startswith("skipped:")
    assert "SEC_DEFAULT_CIK" in step
    assert "SEC_DEFAULT_WATCHLIST" in step


# ---------------------------------------------------------------------------
# Etherscan public-tx config gate
# ---------------------------------------------------------------------------


def test_etherscan_optional_missing_lists_all_address_fallbacks() -> None:
    r = shs.score_source(
        _entry(
            source_key="etherscan",
            tier="optional",
            credential_configured=False,
            freshness_state="skipped",
            missing_env_keys=["ETHERSCAN_API_KEY"],
            requires_api_key=True,
        )
    )
    assert r["health_label"] == shs.LABEL_OPTIONAL_MISSING_CONFIG
    step = r["actionable_next_step"]
    assert "ETHERSCAN_API_KEY" in step
    assert "ETHERSCAN_ADDRESS" in step
    assert "ETHEREUM_ADDRESS" in step
    assert "PUBLIC_ETH_ADDRESS" in step
    # Optional remains a soft WARN, not a core failure.
    assert r["config_state"] == "optional_missing"
    assert r["stale_severity"] == "soft"


def test_etherscan_skipped_address_reason_surfaces_env_keys() -> None:
    r = shs.score_source(
        _entry(
            source_key="etherscan",
            tier="optional",
            credential_configured=True,
            freshness_state="skipped",
            last_refresh_skipped=True,
            last_refresh_skipped_reason="no Ethereum address configured",
        )
    )
    # Optional + no credential is not the path here (credential is set);
    # the source still scores normally, but the skip hint must point at
    # the address fallbacks.
    step = r["actionable_next_step"]
    assert "skipped:" in step
    assert "ETHERSCAN_ADDRESS" in step
    assert "ETHEREUM_ADDRESS" in step
    assert "PUBLIC_ETH_ADDRESS" in step


# ---------------------------------------------------------------------------
# GDELT timeout config gate
# ---------------------------------------------------------------------------


def test_gdelt_skipped_reason_surfaces_timeout_env_key() -> None:
    r = shs.score_source(
        _entry(
            source_key="gdelt",
            tier="core",
            credential_configured=True,
            freshness_state="skipped",
            last_refresh_skipped=True,
            last_refresh_skipped_reason="upstream timeout exceeded",
        )
    )
    step = r["actionable_next_step"]
    assert step.startswith("skipped:")
    assert "GDELT_TIMEOUT_SECONDS" in step


def test_gdelt_core_stale_still_recommends_refresh_command() -> None:
    """Naming env keys must NOT mask a real core-stale failure."""
    r = shs.score_source(
        _entry(
            source_key="gdelt",
            tier="core",
            credential_configured=True,
            freshness_state="overdue",
            hours_since_last_success=48.0,
        )
    )
    step = r["actionable_next_step"]
    assert step.startswith("core_stale:")
    assert "refresh_live_signals.py" in step
    assert r["stale_severity"] == "loud"
    assert r["health_label"] != shs.LABEL_HEALTHY


# ---------------------------------------------------------------------------
# Discipline guardrails — no source-health envelope leakage
# ---------------------------------------------------------------------------


def test_env_key_surfacing_never_flips_unhealthy_to_healthy() -> None:
    """Verbose actionable_next_step output must not affect the label."""
    for src, tier, freshness in (
        ("sec_edgar", "core", "overdue"),
        ("etherscan", "core", "failed"),
        ("gdelt", "core", "never_run"),
    ):
        r = shs.score_source(
            _entry(
                source_key=src,
                tier=tier,
                freshness_state=freshness,
                hours_since_last_success=72.0,
            )
        )
        assert r["health_label"] in {
            shs.LABEL_WATCH,
            shs.LABEL_DEGRADED,
            shs.LABEL_UNHEALTHY,
        }, r["health_label"]


def test_planned_adapter_still_not_scored_even_for_known_sources() -> None:
    r = shs.score_source(
        _entry(
            source_key="sec_edgar",
            tier="planned",
            adapter_status="planned",
            freshness_state="never_run",
        )
    )
    assert r["health_label"] == shs.LABEL_PLANNED_NOT_SCORED


def test_aggregate_actionable_next_steps_orders_core_before_optional() -> None:
    sources = {
        "etherscan": shs.score_source(
            _entry(
                source_key="etherscan",
                tier="optional",
                credential_configured=False,
                freshness_state="skipped",
                missing_env_keys=["ETHERSCAN_API_KEY"],
                requires_api_key=True,
            )
        ),
        "sec_edgar": shs.score_source(
            _entry(
                source_key="sec_edgar",
                tier="core",
                credential_configured=False,
                freshness_state="skipped",
                missing_env_keys=["SEC_USER_AGENT"],
                requires_api_key=True,
            )
        ),
    }
    summary = shs.aggregate_health(sources)
    steps = summary["actionable_next_steps"]
    sec_idx = next(i for i, s in enumerate(steps) if "SEC_USER_AGENT" in s)
    eth_idx = next(
        i for i, s in enumerate(steps) if "ETHERSCAN_API_KEY" in s
    )
    assert sec_idx < eth_idx


def test_no_trading_or_execution_language_in_env_hint_paths() -> None:
    for cfg in (
        dict(source_key="sec_edgar", tier="core", credential_configured=False,
             freshness_state="skipped", missing_env_keys=["SEC_USER_AGENT"],
             requires_api_key=True),
        dict(source_key="etherscan", tier="optional", credential_configured=False,
             freshness_state="skipped", missing_env_keys=["ETHERSCAN_API_KEY"],
             requires_api_key=True),
        dict(source_key="gdelt", tier="core", credential_configured=True,
             freshness_state="skipped", last_refresh_skipped=True,
             last_refresh_skipped_reason="timeout"),
    ):
        r = shs.score_source(_entry(**cfg))
        text = " ".join([
            r.get("operator_message") or "",
            r.get("actionable_next_step") or "",
            " ".join(r.get("health_reasons") or []),
        ]).lower()
        for forbidden in (
            "place order",
            "submit order",
            "execute trade",
            "broker execute",
            "permission to trade",
            "auto-trading",
            "ai-approved",
            "trade now",
        ):
            assert forbidden not in text, forbidden


def test_safety_stamps_present_on_env_hint_payload() -> None:
    r = shs.score_source(
        _entry(
            source_key="sec_edgar",
            tier="core",
            credential_configured=False,
            freshness_state="skipped",
            missing_env_keys=["SEC_USER_AGENT"],
            requires_api_key=True,
        )
    )
    assert r["advisory_status"] == "ADVISORY_ONLY"
    assert r["execution_gate"] == "LOCKED"
    assert r["broker_api_called"] is False
    assert r["execution_permission"] is False
    assert r["can_execute"] is False
