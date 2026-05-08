"""Tests for advisory-only report builders."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ingestion.base_loader import LoaderResult  # noqa: E402
from scripts.normalization.signal_event_schema import (  # noqa: E402
    ADVISORY_ONLY,
    SignalEvent,
)
from scripts.reports.advisory_action_report import build_advisory_action_report  # noqa: E402
from scripts.reports.global_signal_report import build_global_signal_report  # noqa: E402
from scripts.reports.human_review_queue import build_human_review_queue  # noqa: E402


def _events() -> list[SignalEvent]:
    return [
        SignalEvent(source_name="polymarket", source_type="prediction_market", mvp_state="MIURA"),
        SignalEvent(
            source_name="sec_edgar",
            source_type="official_filing",
            mvp_state="AVENTADOR",
            source_reliability=0.95,
            freshness_score=0.8,
            narrative_intensity=0.7,
            market_confirmation=0.5,
        ),
        SignalEvent(
            source_name="gdelt",
            source_type="news_event",
            mvp_state="MURCIELAGO",
            source_reliability=0.5,
        ),
    ]


def test_global_signal_report_invariants_present() -> None:
    loader_results = [
        LoaderResult(source_name="grok", status="skipped", skipped_reason="no key"),
        LoaderResult(source_name="newsapi", status="error", error="boom"),
    ]
    report = build_global_signal_report(_events(), loader_results=loader_results)
    assert report["execution_permission"] == ADVISORY_ONLY
    assert report["human_review_required"] is True
    assert report["ai_executions"] == 0
    assert report["total_signals"] == 3
    assert report["signals_by_source"]["sec_edgar"] == 1
    assert report["signals_by_state"]["AVENTADOR"] == 1
    assert report["advisory_only_count"] == 3
    assert report["execution_permission_summary"][ADVISORY_ONLY] == 3
    assert any(s["source_name"] == "grok" for s in report["skipped_sources"])
    assert any(s["source_name"] == "newsapi" for s in report["source_errors"])
    assert report["top_signals"][0]["source_name"] == "sec_edgar"


def test_human_review_queue_invariants_present() -> None:
    payload = build_human_review_queue(_events())
    assert payload["execution_permission"] == ADVISORY_ONLY
    assert payload["human_review_required"] is True
    assert payload["ai_executions"] == 0
    assert payload["queue_size"] == 3
    assert payload["items"][0]["needs_attention"] is True


def test_advisory_action_report_never_executes() -> None:
    payload = build_advisory_action_report(_events())
    assert payload["execution_permission"] == ADVISORY_ONLY
    assert payload["human_review_required"] is True
    assert payload["ai_executions"] == 0
    actions = {row["suggested_action"] for row in payload["items"]}
    assert "EXECUTE" not in actions
    assert "AUTO_BUY" not in actions
    assert "AUTO_SELL" not in actions
    for row in payload["items"]:
        assert row["execution_permission"] == ADVISORY_ONLY
        assert row["human_review_required"] is True
