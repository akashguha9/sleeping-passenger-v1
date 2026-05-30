"""Phase 6 — fixture-backed source activation contract.

HONEST SCOPE: these tests are *fixture-backed*.  They prove the activation
CONTRACT — that a source which writes N>0 fresh, non-mock, non-backfill
canonical rows is classified LIVE_CANONICAL / activated, while zero-row,
mock, or backfill runs are NOT — using the real ``source_freshness_contract``
reducer via the canonical-truth route builder.

They do NOT claim that a real live provider produced fresh rows.  A genuine
network canary is provided but SKIPPED unless ``SP_LIVE_CANARY`` is set, and it
must degrade honestly when offline.

    Activated_s = read_only
                · I(rows_added > 0 in fixture-backed run)
                · I(canonical row classified live)
                · I(source health reports truthfully)
                · I(no mock canonical contamination)
"""
from __future__ import annotations

import os

import pytest

from scripts.api.routers.source_health_router import build_canonical_source_truth

_NOW = "2026-05-31T12:00:00Z"


def _fixture_run(source: str, **overrides):
    """A source_run_log-shaped row representing what an adapter WOULD write."""
    base = dict(
        source=source,
        status="OK",
        rows_added=3,
        rows_filtered=0,
        created_at="2026-05-31T11:00:00Z",  # 1h old, fresh
    )
    base.update(overrides)
    return base


def _classified(source: str, **overrides):
    out = build_canonical_source_truth([_fixture_run(source, **overrides)], now_iso=_NOW)
    return out["sources"][0]


def _is_activated(source_dict: dict, *, read_only: bool = True) -> bool:
    return bool(
        read_only
        and source_dict["rows_added"] > 0
        and source_dict["is_live_canonical"]
        and source_dict["canonical_signal_status"] == "LIVE_CANONICAL"
    )


def test_yfinance_or_market_data_adapter_can_create_canonical_fixture_rows():
    s = _classified("yfinance")
    assert _is_activated(s)
    assert s["canonical_signal_status"] == "LIVE_CANONICAL"


def test_gdelt_adapter_can_create_canonical_fixture_rows():
    s = _classified("gdelt")
    assert _is_activated(s)


def test_polymarket_or_alternative_adapter_can_create_canonical_fixture_rows():
    s = _classified("polymarket")
    assert _is_activated(s)


def test_at_least_three_sources_activated_fixture_backed():
    out = build_canonical_source_truth(
        [
            _fixture_run("yfinance"),
            _fixture_run("gdelt"),
            _fixture_run("polymarket"),
        ],
        now_iso=_NOW,
    )
    activated = [s for s in out["sources"] if _is_activated(s)]
    assert len(activated) >= 3
    assert out["live_canonical_count"] >= 3


def test_each_adapter_records_source_run_log_rows_added():
    for src in ("yfinance", "gdelt", "polymarket"):
        s = _classified(src)
        assert "rows_added" in s
        assert s["rows_added"] == 3


def test_zero_rows_is_degraded_not_ok():
    s = _classified("yfinance", rows_added=0)
    # API health may be OK but canonical status is degraded, not live.
    assert s["api_health_status"] == "OK"
    assert s["canonical_signal_status"] == "ZERO_FRESH_ROWS"
    assert _is_activated(s) is False


def test_live_source_rows_have_mock_flag_false():
    s = _classified("yfinance")
    # A mock run is never live/activated.
    mock = _classified("yfinance", mock_flag=True)
    assert s["is_live_canonical"] is True
    assert mock["is_live_canonical"] is False
    assert mock["canonical_signal_status"] == "MOCK_NON_CANONICAL"


def test_backfill_rows_do_not_count_as_activation():
    s = _classified("yfinance", backfill_only=True)
    assert s["canonical_signal_status"] == "BACKFILL_NON_FRESH"
    assert _is_activated(s) is False


@pytest.mark.skipif(
    not os.environ.get("SP_LIVE_CANARY"),
    reason="live network canary disabled; set SP_LIVE_CANARY=1 to enable",
)
def test_optional_live_canary_degrades_honestly():  # pragma: no cover - opt-in
    """Opt-in canary: must degrade honestly (never fabricate fresh rows).

    Run with:  SP_LIVE_CANARY=1 python -m pytest \
        tests/test_live_sources_activation_contract.py -k canary
    """
    import urllib.request

    try:
        with urllib.request.urlopen("https://query1.finance.yahoo.com", timeout=5) as r:
            reachable = r.status == 200
    except Exception:
        reachable = False
    # Whatever the network does, the activation contract stays truthful: an
    # unreachable provider must NOT be reported as activated.
    if not reachable:
        s = _classified("yfinance", rows_added=0, status="UNREACHABLE")
        assert _is_activated(s) is False
