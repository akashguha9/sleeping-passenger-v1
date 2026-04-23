import json
from pathlib import Path

from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report
from scripts.yahoo_market_data_adapter import (
    build_external_market_marks_report,
    write_external_market_marks_report,
)


def _success_fetcher(_: str) -> dict:
    return {
        "last_price": 101.5,
        "currency": "USD",
        "previous_close": 100.0,
        "open": 100.5,
        "day_high": 102.0,
        "day_low": 99.5,
        "volume": 123456,
        "regular_market_time": "2026-04-22T12:00:00+00:00",
        "raw_history": [
            {"close": 96.0},
            {"close": 97.0},
            {"close": 98.0},
            {"close": 99.0},
            {"close": 100.0},
            {"close": 101.0},
        ],
    }


def test_yahoo_market_marks_success_path_and_metadata(scratch_path: Path) -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report()
    )
    output_path = scratch_path / "external_market_marks.json"

    report = write_external_market_marks_report(
        tickers=["RTX"],
        runtime_state=runtime_state,
        fetcher=_success_fetcher,
        output_path=output_path,
        fetched_at="2026-04-22T12:10:00+00:00",
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert report["success_count"] == 1
    assert report["failure_count"] == 0
    assert payload["operating_mode"] == "hybrid"
    assert payload["truth_origin"] == "external"
    assert payload["run_id"]
    assert payload["commit_hash"]
    assert payload["config_fingerprint"]

    row = payload["marks"][0]
    assert row["ticker"] == "RTX"
    assert row["source_name"] == "yahoo_finance"
    assert row["source_type"] == "external_market_data"
    assert row["truth_origin"] == "external"
    assert row["last_price"] == 101.5
    assert row["currency"] == "USD"
    assert row["previous_close"] == 100.0
    assert row["context_5d_change_pct"] is not None
    assert row["context_1mo_change_pct"] is not None
    assert row["staleness_classification"] in {"fresh", "delayed"}
    assert row["run_id"]
    assert row["operating_mode"] == "hybrid"


def test_yahoo_market_marks_failure_path_is_persisted_truthfully() -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report()
    )

    def failing_fetcher(_: str) -> dict:
        raise RuntimeError("simulated_yahoo_failure")

    report = build_external_market_marks_report(
        tickers=["RTX"],
        runtime_state=runtime_state,
        fetcher=failing_fetcher,
    )

    assert report["success_count"] == 0
    assert report["failure_count"] == 1
    assert report["operating_mode"] == "seeded"

    row = report["marks"][0]
    assert row["ticker"] == "RTX"
    assert row["ok"] is False
    assert "simulated_yahoo_failure" in row["retrieval_error"]
    assert row["truth_origin"] == "external"
    assert row["staleness_classification"] == "unknown"
