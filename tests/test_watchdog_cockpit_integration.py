"""
Tests for the ``GET /source-health/watchdog`` API surface and its
cockpit-facing safety contract.

Asserts:
  - missing summary file returns a truthful MISSING payload
  - present + valid summary surfaces fresh top-level chip fields
  - summary older than 60 minutes is flagged ``stale=true``
  - malformed JSON returns ERROR — not pretend HEALTHY
  - all responses carry the advisory-only safety stamps
  - frontend live-signals page source-string contains the panel,
    advisory-only language, and no execute/trade verbs
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.api_server import _build_watchdog_summary_response


SAFETY_KEYS = {
    "advisory_only",
    "human_execution_required",
    "execution_gate",
    "broker_api_called",
    "can_execute",
    "ai_execution_count",
    "execution_permission",
}


def _assert_safety(payload: dict) -> None:
    for k in SAFETY_KEYS:
        assert k in payload, f"missing safety key: {k}"
    assert payload["advisory_only"] is True
    assert payload["human_execution_required"] is True
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["can_execute"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["execution_permission"] is False


# ---------------------------------------------------------------------------
# Missing-file behaviour
# ---------------------------------------------------------------------------


def test_returns_missing_when_summary_absent(tmp_path: Path) -> None:
    p = tmp_path / "refresh_watchdog_summary.json"
    payload = _build_watchdog_summary_response(summary_path=p)
    assert payload["present"] is False
    assert payload["status"] == "MISSING"
    assert "not found" in (payload.get("reason") or "").lower()
    assert payload["summary"] is None
    assert payload["age_seconds"] is None
    assert payload["stale"] is False
    _assert_safety(payload)


# ---------------------------------------------------------------------------
# Present-file behaviour
# ---------------------------------------------------------------------------


def _write_summary(path: Path, status: str, generated_at: str) -> None:
    payload = {
        "operation": "refresh_watchdog",
        "run_id": "abc",
        "status": status,
        "ttl_hours": 6,
        "max_retries": 3,
        "retries_attempted": 1,
        "backoff_seconds": [60, 180, 300],
        "backoff_jitter_pct": 0.15,
        "jitter_enabled": True,
        "planned_sleep_seconds_per_retry": [62.0],
        "actual_sleep_seconds_per_retry": [62.0],
        "stale_sources_before": ["kalshi", "gdelt"],
        "stale_sources_after": ["kalshi"],
        "excluded_optional_sources": ["etherscan"],
        "parent_stale_derived_sources": ["prediction_market_disagreement"],
        "derived_source_dependency_status": {
            "prediction_market_disagreement": {
                "freshness_state": "degraded_parent_stale",
                "is_stale_active": True,
                "degraded_parent_stale_parents": ["kalshi"],
                "parents": {
                    "polymarket": {
                        "freshness_state": "fresh",
                        "is_stale_active": False,
                        "dependency_critical": False,
                    },
                    "kalshi": {
                        "freshness_state": "stale",
                        "is_stale_active": True,
                        "dependency_critical": True,
                    },
                },
            }
        },
        "dependency_critical_sources": ["kalshi"],
        "kalshi_freshness_before": "stale",
        "kalshi_freshness_after": "stale",
        "prediction_market_disagreement_status_before": "degraded_parent_stale",
        "prediction_market_disagreement_status_after": "degraded_parent_stale",
        "kalshi_status_before": {"dependency_critical": True, "used_by": ["prediction_market_disagreement"]},
        "kalshi_status_after": {"dependency_critical": True, "used_by": ["prediction_market_disagreement"]},
        "gdelt_status_before": {"is_stale_active": True},
        "gdelt_status_after": {"is_stale_active": False},
        "freshness_improved": True,
        "improvement_reasons": ["stale_cleared"],
        "started_at_utc": generated_at,
        "finished_at_utc": generated_at,
        "generated_at_utc": generated_at,
        "advisory_only": True,
        "human_execution_required": True,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "can_execute": False,
        "ai_execution_count": 0,
        "execution_permission": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_present_summary_surfaces_top_level_chips(tmp_path: Path) -> None:
    p = tmp_path / "refresh_watchdog_summary.json"
    # 10 minutes ago — well within stale window.
    _write_summary(p, "IMPROVED_BUT_STALE", "2026-05-25T10:25:00+00:00")
    payload = _build_watchdog_summary_response(
        summary_path=p, now_iso="2026-05-25T10:35:00+00:00"
    )
    assert payload["present"] is True
    assert payload["status"] == "IMPROVED_BUT_STALE"
    assert payload["age_minutes"] == pytest.approx(10.0, abs=0.001)
    assert payload["stale"] is False
    inner = payload["summary"]
    assert inner is not None
    assert inner["stale_sources_before"] == ["kalshi", "gdelt"]
    assert inner["stale_sources_after"] == ["kalshi"]
    assert inner["excluded_optional_sources"] == ["etherscan"]
    assert inner["dependency_critical_sources"] == ["kalshi"]
    assert inner["jitter_enabled"] is True
    assert inner["backoff_jitter_pct"] == 0.15
    _assert_safety(payload)


def test_stale_summary_flag_set_when_summary_older_than_threshold(tmp_path: Path) -> None:
    p = tmp_path / "refresh_watchdog_summary.json"
    # 90 minutes ago — over the 60-min stale threshold.
    _write_summary(p, "HEALTHY", "2026-05-25T09:05:00+00:00")
    payload = _build_watchdog_summary_response(
        summary_path=p, now_iso="2026-05-25T10:35:00+00:00"
    )
    assert payload["present"] is True
    assert payload["stale"] is True
    assert payload["age_minutes"] is not None and payload["age_minutes"] > 60
    _assert_safety(payload)


def test_malformed_summary_returns_error(tmp_path: Path) -> None:
    p = tmp_path / "refresh_watchdog_summary.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not-valid-json", encoding="utf-8")
    payload = _build_watchdog_summary_response(
        summary_path=p, now_iso="2026-05-25T10:35:00+00:00"
    )
    assert payload["present"] is True
    assert payload["status"] == "ERROR"
    assert payload["summary"] is None
    _assert_safety(payload)


def test_route_never_exposes_arbitrary_top_level_keys(tmp_path: Path) -> None:
    """Adding e.g. ``broker_api_url`` to the summary file must not leak —
    the route only forwards the curated list of summary keys."""
    p = tmp_path / "refresh_watchdog_summary.json"
    _write_summary(p, "HEALTHY", "2026-05-25T10:25:00+00:00")
    # Mutate file to add a poisoned key the route should NOT forward.
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw["broker_api_url"] = "https://broker.invalid/orders"
    raw["secret_token"] = "leaked-token"
    p.write_text(json.dumps(raw), encoding="utf-8")
    payload = _build_watchdog_summary_response(
        summary_path=p, now_iso="2026-05-25T10:35:00+00:00"
    )
    inner = payload["summary"]
    assert "broker_api_url" not in inner
    assert "secret_token" not in inner
    _assert_safety(payload)


# ---------------------------------------------------------------------------
# Static safety scan — the frontend live-signals page must include the
# WatchdogStatusPanel, the advisory-only footer string, and zero
# execute/trade/order verbs introduced by this sprint.
# ---------------------------------------------------------------------------


def test_live_signals_page_includes_watchdog_panel_and_advisory_footer() -> None:
    src = (
        _REPO_ROOT / "frontend" / "src" / "app" / "live-signals" / "page.tsx"
    ).read_text(encoding="utf-8")
    assert "WatchdogStatusPanel" in src
    assert "watchdog-status-panel" in src
    assert "Watchdog is advisory-only" in src
    assert "does not trade" in src
    assert "does not authorize trades" in src or "does not authorize trade" in src
    # The new panel must NOT introduce any execute/order verb.  Anchor on
    # the function definition (not the JSX render site) so we are scanning
    # only the panel body.
    new_block_start = src.find("function WatchdogStatusPanel")
    assert new_block_start > -1, "WatchdogStatusPanel function definition missing"
    new_block_end = src.find("function AutoRefreshPanel", new_block_start)
    assert new_block_end > new_block_start, "AutoRefreshPanel marker missing after WatchdogStatusPanel"
    panel_block = src[new_block_start:new_block_end]
    lowered = panel_block.lower()
    forbidden = [
        "place order",
        "execute trade",
        "submit order",
        "place trade",
        "place a trade",
        "broker.invalid",
    ]
    for needle in forbidden:
        assert needle not in lowered, f"forbidden verb introduced: {needle}"
