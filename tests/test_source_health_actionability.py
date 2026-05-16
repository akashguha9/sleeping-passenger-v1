"""Source-health audit is action-oriented, not score-hiding.

Existing classification (core_stale vs optional_config_missing vs
planned_not_scored) is kept loud where it should be loud and quiet
where it is purely operator-configurable.  This module locks in the
new ``actionable_next_step`` per source and ``actionable_next_steps``
+ ``issue_classification`` at the aggregate level.

Invariants:

* Stale CORE source still produces a loud severity + ``core_stale``
  classification.
* Missing OPTIONAL credential is ``optional_config_missing`` (not a
  core failure) and surfaces the exact env-var names to set.
* Missing CORE/SECONDARY credential surfaces the env-var names and
  is classified as a config_missing failure (counted in
  ``core_config_missing`` / ``secondary_config_missing``).
* Planned adapter is ``planned_not_scored`` and produces a no-action-
  required next step.
* Aggregate ``actionable_next_steps`` lists are deduped and prioritised
  so the operator sees core actions first.
* No source-health code implies trading permission.
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


def test_optional_missing_credential_lists_env_vars() -> None:
    """Etherscan-style: optional source missing key — must not be a core
    failure, must name the exact env var operator has to set."""
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
    assert r["config_state"] == "optional_missing"
    step = r["actionable_next_step"]
    assert "optional_config_missing" in step
    assert "ETHERSCAN_API_KEY" in step


def test_core_stale_step_recommends_refresh_command() -> None:
    """GDELT-like: core source stale — the next step is a concrete
    refresh command the operator can copy-paste."""
    r = shs.score_source(
        _entry(
            source_key="gdelt",
            tier="core",
            freshness_state="overdue",
            hours_since_last_success=36.0,
        )
    )
    assert r["stale_severity"] == "loud"
    step = r["actionable_next_step"]
    assert step.startswith("core_stale:")
    assert "gdelt" in step
    assert "refresh_live_signals.py" in step


def test_core_config_missing_lists_env_vars_in_step() -> None:
    """SEC EDGAR-like core source missing API key — the next step names
    the env vars verbatim so the operator doesn't have to grep .env."""
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
    assert r["config_state"] == "required_missing"
    step = r["actionable_next_step"]
    assert "config_missing" in step
    assert "SEC_USER_AGENT" in step


def test_planned_adapter_marks_no_action_required() -> None:
    r = shs.score_source(
        _entry(
            source_key="asia_disclosure",
            tier="planned",
            adapter_status="planned",
            freshness_state="never_run",
        )
    )
    assert r["health_label"] == shs.LABEL_PLANNED_NOT_SCORED
    step = r["actionable_next_step"]
    assert step.startswith("planned_not_scored:")
    assert "asia_disclosure" in step


def test_refresh_error_step_surfaces_first_line_only() -> None:
    """When a source has an upstream error, the action step must surface
    a short, recognisable identifier — never multiple lines, never a
    secret-like blob."""
    r = shs.score_source(
        _entry(
            source_key="etherscan",
            tier="core",
            freshness_state="failed",
            last_refresh_error=(
                "HTTPError: 429 too many requests\nTraceback details\nstack..."
            ),
            last_refresh_success=False,
        )
    )
    step = r["actionable_next_step"]
    assert step.startswith("refresh_error:")
    assert "etherscan" in step
    assert "Traceback" not in step


def test_aggregate_emits_actionable_next_steps_in_priority_order() -> None:
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
        "gdelt": shs.score_source(
            _entry(
                source_key="gdelt",
                tier="core",
                freshness_state="overdue",
                hours_since_last_success=36.0,
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
    assert any("SEC_USER_AGENT" in s for s in steps)
    assert any("gdelt" in s for s in steps)
    assert any("ETHERSCAN_API_KEY" in s for s in steps)
    # core_config_missing has the top priority; it must appear before
    # the optional_config_missing step.
    sec_idx = next(i for i, s in enumerate(steps) if "SEC_USER_AGENT" in s)
    eth_idx = next(i for i, s in enumerate(steps) if "ETHERSCAN_API_KEY" in s)
    assert sec_idx < eth_idx


def test_aggregate_classification_distinguishes_core_from_optional() -> None:
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
        "gdelt": shs.score_source(
            _entry(
                source_key="gdelt",
                tier="core",
                freshness_state="overdue",
                hours_since_last_success=36.0,
            )
        ),
        "asia_disclosure": shs.score_source(
            _entry(
                source_key="asia_disclosure",
                tier="planned",
                adapter_status="planned",
                freshness_state="never_run",
            )
        ),
    }
    summary = shs.aggregate_health(sources)
    classification = summary["issue_classification"]
    assert classification["core_stale"] >= 1
    assert classification["optional_config_missing"] >= 1
    assert classification["planned_not_scored"] >= 1
    # The optional missing-config source must NOT contaminate the core
    # failure bucket — the entire point of the action-oriented classifier.
    assert classification["core_config_missing"] == 0


def test_safety_stamps_present_on_actionable_payload() -> None:
    r = shs.score_source(_entry(source_key="gdelt"))
    assert r["advisory_status"] == "ADVISORY_ONLY"
    assert r["execution_gate"] == "LOCKED"
    assert r["broker_api_called"] is False
    assert r["execution_permission"] is False
    assert r["can_execute"] is False


def test_no_source_health_payload_implies_trade_permission() -> None:
    """The actionable next-step strings must NEVER imply that the
    operator is authorised to place an order based on source health."""
    for entry in (
        _entry(),
        _entry(tier="optional", credential_configured=False,
               freshness_state="skipped", missing_env_keys=["X"],
               requires_api_key=True),
        _entry(tier="core", freshness_state="overdue",
               hours_since_last_success=72.0),
    ):
        r = shs.score_source(entry)
        text = " ".join([
            r.get("operator_message") or "",
            r.get("actionable_next_step") or "",
            " ".join(r.get("health_reasons") or []),
        ]).lower()
        for forbidden in (
            "place order",
            "submit order",
            "execute trade",
            "trade now",
            "broker execute",
            "permission to trade",
            "ai-approved",
        ):
            assert forbidden not in text, (
                f"forbidden phrase {forbidden!r} in source-health output"
            )
