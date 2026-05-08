from __future__ import annotations

from pathlib import Path

from scripts.external_adapters.trendradar_adapter import TrendRadarAdapter


FIXTURE_ROOT = Path("tests/fixtures/external_adapters/trendradar")


def test_trendradar_json_txt_parsing_and_noise_bounds() -> None:
    adapter = TrendRadarAdapter({"enabled": True, "fallback_path": str(FIXTURE_ROOT)})
    evidence = adapter.collect()[0]
    assert evidence.real_execution_allowed is False
    assert evidence.normalized_payload["items"]
    score = evidence.normalized_payload["items"][0]["engineered_noise_score"]
    assert 0.0 <= score <= 1.0
    assert evidence.normalized_payload["text_summaries"]
