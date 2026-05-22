"""Schema tests for the committed data/daily_payload/* files."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_DIR = REPO_ROOT / "data" / "daily_payload"

REQUIRED_FILES = (
    "verified_current_holdings.json",
    "closed_positions.json",
    "sold_positions.json",
    "do_not_treat_as_open.json",
    "today_market_snapshot.json",
    "today_price_movers.json",
    "today_news_events.json",
    "today_filings_events.json",
    "yesterday_final_candidates.json",
)


def _load(name: str) -> dict:
    path = PAYLOAD_DIR / name
    assert path.exists(), f"missing payload file: {path}"
    return json.loads(path.read_text(encoding="utf-8-sig"))


@pytest.mark.parametrize("name", REQUIRED_FILES)
def test_payload_file_exists_and_is_object(name: str) -> None:
    payload = _load(name)
    assert isinstance(payload, dict), f"{name} must be a JSON object"
    assert "run_date" in payload, f"{name} must carry a run_date"


def test_verified_holdings_structure() -> None:
    payload = _load("verified_current_holdings.json")
    assert isinstance(payload["positions"], list)
    for pos in payload["positions"]:
        for key in ("ticker", "normalized_ticker", "status", "human_confirmed"):
            assert key in pos, f"verified holding missing {key}"
        assert pos["status"] in {"OPEN", "REDUCED", "ADD", "PARTIAL_OPEN"}


def test_do_not_treat_as_open_override_content() -> None:
    payload = _load("do_not_treat_as_open.json")
    assert set(payload["not_owned_do_not_manage"]) == {"UNG", "TIP", "TLT", "FCG"}
    assert payload["closed_or_sold_positions"] == ["GLD"]
    assert payload.get("operator_note")


def test_sold_and_closed_reference_gld() -> None:
    sold = _load("sold_positions.json")
    closed = _load("closed_positions.json")
    assert "GLD" in sold["tickers"]
    assert any(p.get("ticker") == "GLD" for p in closed["positions"])


def test_gld_and_phantoms_not_in_verified_holdings() -> None:
    payload = _load("verified_current_holdings.json")
    norm = {p.get("normalized_ticker") for p in payload["positions"]}
    for phantom in ("UNG", "TIP", "TLT", "FCG", "GLD"):
        assert phantom not in norm, f"{phantom} must not be a verified open holding"


def test_market_snapshot_and_movers_shapes() -> None:
    snap = _load("today_market_snapshot.json")
    for key in ("indices", "rates", "commodities", "fx", "regime_notes"):
        assert isinstance(snap[key], list)
    movers = _load("today_price_movers.json")
    assert isinstance(movers["movers"], list)


def test_yesterday_candidates_shape() -> None:
    payload = _load("yesterday_final_candidates.json")
    for key in ("final_candidates", "watchlist", "avoids"):
        assert isinstance(payload[key], list)
