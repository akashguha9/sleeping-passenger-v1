import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.market_data_adapter import describe_market_data_adapter
from scripts.repo_operating_mode import build_operating_mode_report
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_market_data_adapter_description_is_explicitly_placeholder() -> None:
    payload = describe_market_data_adapter()

    assert payload["live_quotes_available"] is False
    assert payload["contract_state"] == "placeholder"
    assert payload["truth_origin_tags"] == ["placeholder"]


def test_operating_mode_report_defaults_to_seeded() -> None:
    report = build_operating_mode_report()

    assert report["operating_mode"] == "seeded"
    assert report["truth_origin"] == "seeded"
    assert report["source_mode"] == "SYNTHETIC_RUNTIME_FALLBACK"
    assert report["quote_provider_state"] == "placeholder"
    assert report["paper_execution_enabled"] is False
    assert report["live_execution_enabled"] is False


def test_repo_operating_mode_summary_cli() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "repo_operating_mode.py"), "--summary"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip().splitlines() == [
        "Repo Operating Mode",
        "operating_mode=seeded",
        "truth_origin=seeded",
        "source_mode=SYNTHETIC_RUNTIME_FALLBACK",
        "quote_provider_state=placeholder",
        "paper_execution_enabled=false",
        "live_execution_enabled=false",
        "mode_reason=Seeded mode: local-file-driven signals, placeholder quote contract, and no execution path enabled.",
    ]


def test_repo_operating_mode_json_cli_shape() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "repo_operating_mode.py"), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["operating_mode"] == "seeded"
    assert payload["truth_origin"] == "seeded"
    assert payload["quote_provider_state"] == "placeholder"


def test_operating_mode_promotes_to_hybrid_only_with_external_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPELINE_ENABLE_PAPER_EXECUTION", "true")
    monkeypatch.setenv("PIPELINE_ENABLE_LIVE_EXECUTION", "false")
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report()
    )
    runtime_state["external_observation_active"] = True
    runtime_state["external_observation_source"] = "yahoo_finance"
    runtime_state["external_observation_fetched_at"] = "2026-04-22T12:00:00+00:00"

    report = build_operating_mode_report(runtime_state=runtime_state)

    assert report["operating_mode"] == "hybrid"
    assert report["truth_origin"] == "external"
