"""Contract tests: fresh payloads -> synthesis pipeline, advisory-only intact."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.advisory_contract import advisory_safety_stamps
from scripts.build_daily_payloads import build_all_daily_payloads
from scripts.daily_payload import load_daily_payload
from scripts.daily_synthesis_pipeline import run_daily_synthesis

RUN_DATE = "2026-05-22"


def _seed_protected(base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "verified_current_holdings.json").write_text(
        json.dumps({"run_date": RUN_DATE, "positions": []}), encoding="utf-8"
    )
    (base / "do_not_treat_as_open.json").write_text(
        json.dumps({"run_date": RUN_DATE, "not_owned_do_not_manage": ["UNG", "TIP", "TLT", "FCG"],
                    "closed_or_sold_positions": ["GLD"], "operator_note": "test"}),
        encoding="utf-8",
    )
    (base / "closed_positions.json").write_text(
        json.dumps({"run_date": RUN_DATE, "positions": [{"ticker": "GLD", "status": "CLOSED"}]}),
        encoding="utf-8",
    )
    (base / "sold_positions.json").write_text(
        json.dumps({"run_date": RUN_DATE, "tickers": ["GLD"]}), encoding="utf-8"
    )


def test_builders_produce_loadable_payload(tmp_path: Path) -> None:
    base = tmp_path / "payload"
    _seed_protected(base)
    build_all_daily_payloads(run_date=RUN_DATE, payload_dir=base)
    payload = load_daily_payload(base)
    # Loader sees the freshly built movers + snapshot.
    assert payload["price_movers"]["movers"], "loader must see built movers"
    assert payload["market_snapshot"]["source_health"] == "UNVERIFIED"


def test_envelope_fields_present_on_built_payloads(tmp_path: Path) -> None:
    base = tmp_path / "payload"
    _seed_protected(base)
    build_all_daily_payloads(run_date=RUN_DATE, payload_dir=base)
    for name, list_key in (
        ("today_price_movers.json", "movers"),
        ("today_news_events.json", "events"),
        ("today_filings_events.json", "events"),
    ):
        data = json.loads((base / name).read_text(encoding="utf-8"))
        for key in ("run_date", "generated_at_utc", "source_health", "provider", "is_live"):
            assert key in data, f"{name} missing envelope key {key}"
        # Synthesis-contract alias.
        assert "records" in data
        assert data["records"] == data[list_key]
        assert data["is_live"] is False


def test_synthesis_runs_and_is_underpowered(tmp_path: Path) -> None:
    base = tmp_path / "payload"
    _seed_protected(base)
    build_all_daily_payloads(run_date=RUN_DATE, payload_dir=base)
    result = run_daily_synthesis(payload_dir=base)

    disc = result["fresh_market_discovery"]
    assert disc["discovery_universe"], "universe must not be empty"
    # Static universe is always scanned.
    for t in ("AAPL", "RTX", "RELIANCE.NS"):
        assert t in disc["discovery_universe"]
    assert disc["discovery_underpowered"] is True

    # Every discovered ticker gets a why_today score; all are static fallbacks.
    why = result["why_today_scores"]
    assert why, "why_today scores must be present"
    assert all(s < 0.70 for s in why.values()), "no live trigger => no executable why-today"

    # With fallback-only data there are no executable buys, but discovery survives.
    assert result["candidate_executable_split"]["has_executable_buys"] is False


def test_advisory_safety_intact_through_pipeline(tmp_path: Path) -> None:
    base = tmp_path / "payload"
    _seed_protected(base)
    build_all_daily_payloads(run_date=RUN_DATE, payload_dir=base)
    result = run_daily_synthesis(payload_dir=base)

    expected = advisory_safety_stamps()
    assert result["safety"] == expected
    assert result["safety"]["execution_gate"] == "LOCKED"
    assert result["safety"]["broker_api_called"] is False
    assert result["safety"]["ai_execution_count"] == 0
    assert result["safety"]["can_execute"] is False
    assert result["execution"]["human_review_required"] is True
    assert result["execution"]["human_final_decision_required"] is True


def test_phantom_does_not_block_and_gld_not_executable(tmp_path: Path) -> None:
    base = tmp_path / "payload"
    _seed_protected(base)
    build_all_daily_payloads(run_date=RUN_DATE, payload_dir=base)
    result = run_daily_synthesis(payload_dir=base)
    gate = result["portfolio_truth_gate"]
    assert gate["global_discovery_permission"] is True
    # GLD is in U_static (MACRO_ETFS) yet closed/sold => never executable.
    split = result["candidate_executable_split"]
    gld = [r for r in split["classified"] if r["ticker"] == "GLD"]
    if gld:
        assert gld[0]["executable"] is False
