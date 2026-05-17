"""Tests for honest source display state on /live-sources/status.

Pins the contract documented in the Live Signals truthfulness fix:

  * Etherscan with OPTIONAL_CONFIG_MISSING and 25 archived rows shows
    display_state=optional_unconfigured_with_archive, current_live=0,
    archived=25, latest_archived row equals MAX(fetched_at).
  * Asia Disclosure (PLANNED_NOT_SCORED) shows display_state=
    planned_coverage with exactly 11 coverage rows, current_live=0, and
    India is NOT in the coverage rows.
  * A genuinely stale active core source (GDELT-like) shows
    display_state=stale_active.
  * Old persisted rows are NOT deleted by these display changes.
  * Advisory invariants remain intact end-to-end.
  * No execution endpoints are introduced by the display fix.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _isolated_db(tmp_path: Path, monkeypatch) -> Path:
    import scripts.persistence as p

    db = tmp_path / "display_state.db"
    monkeypatch.setattr(p, "DB_PATH", db)
    p.init_schema(db)
    return db


def _strip_live_keys(monkeypatch) -> None:
    for key in (
        "NEWS_API_KEY",
        "NEWSAPI_KEY",
        "EVENT_REGISTRY_API_KEY",
        "ETHERSCAN_API_KEY",
        "ETHERSCAN_ADDRESS",
        "ETHEREUM_ADDRESS",
        "PUBLIC_ETH_ADDRESS",
        "XAI_API_KEY",
        "GROK_API_KEY",
        "SEC_USER_AGENT",
        "SEC_DEFAULT_CIK",
        "SEC_DEFAULT_WATCHLIST",
        "SEC_USE_DEFAULT_WATCHLIST",
        "EDINET_API_KEY",
        "JAPAN_EDINET_API_KEY",
        "OPENDART_API_KEY",
        "KOREA_DART_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def _seed_signal_events(db_path: Path, source_name: str, count: int, fetched_at: str) -> None:
    """Insert ``count`` signal_events rows for ``source_name`` all dated
    ``fetched_at``.  Used to simulate an old Etherscan archive."""
    import scripts.persistence as p

    for i in range(count):
        p.insert_signal_event(
            event_id=f"{source_name}-row-{i}",
            source_name=source_name,
            raw_payload={"i": i, "title": f"old {source_name} row {i}"},
            fetched_at=fetched_at,
            db_path=db_path,
        )


# ---------------------------------------------------------------------------
# Etherscan — OPTIONAL_CONFIG_MISSING with archived rows
# ---------------------------------------------------------------------------


def test_etherscan_optional_unconfigured_with_archive_shape(tmp_path, monkeypatch):
    db = _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)

    _seed_signal_events(db, "etherscan", count=25, fetched_at="2026-05-12T12:00:00+00:00")

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    entry = payload["sources"]["etherscan"]

    # Stale-attribution layer must still exclude it.
    assert entry["is_stale"] is False
    assert entry.get("stale_excluded_reason") == "optional_config_missing"
    assert "etherscan" not in payload["stale_sources"]

    # Display-state layer must surface archived rows truthfully.
    assert entry["display_state"] == "optional_unconfigured_with_archive"
    assert entry["is_current_live"] is False
    assert entry["current_live_count"] == 0
    assert entry["archived_row_count"] == 25
    assert entry["total_persisted_count"] == 25
    assert entry["rows_are_current_live"] is False
    assert entry["rows_are_archived"] is True
    assert entry["rows_are_stale"] is False
    assert entry["display_count_label"] == "Archived/persisted rows"
    assert entry["display_timestamp_label"] == "Latest archived row"
    assert entry["latest_persisted_row_at_utc"] == "2026-05-12T12:00:00+00:00"
    assert entry["latest_current_refresh_at_utc"] is None
    assert "optional" in entry["source_display_warning"].lower()
    assert "not configured" in entry["source_display_warning"].lower()


def test_etherscan_archived_rows_are_not_deleted(tmp_path, monkeypatch):
    """The honest display fix MUST NOT delete old persisted rows."""
    db = _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)

    _seed_signal_events(db, "etherscan", count=25, fetched_at="2026-05-12T12:00:00+00:00")

    from scripts.api_server import _build_live_sources_status

    _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")

    import scripts.persistence as p

    events = p.get_signal_events(source_name="etherscan", limit=100, db_path=db)
    assert len(events) == 25


def test_etherscan_archived_timestamp_routes_to_persisted_not_refresh_field(
    tmp_path, monkeypatch
):
    """When the source is not configured, the May-12 row timestamp must be
    exposed as ``latest_persisted_row_at_utc`` — NOT as a refresh-success
    timestamp.  Confusing the two is exactly the bug we are fixing."""
    db = _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)
    _seed_signal_events(db, "etherscan", count=25, fetched_at="2026-05-12T12:00:00+00:00")

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    entry = payload["sources"]["etherscan"]
    assert entry["latest_persisted_row_at_utc"] == "2026-05-12T12:00:00+00:00"
    assert entry.get("last_refresh_success_at") in (None, "")
    assert entry.get("latest_current_refresh_at_utc") is None


def test_etherscan_with_no_rows_renders_optional_empty(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    entry = payload["sources"]["etherscan"]
    assert entry["display_state"] == "optional_unconfigured_empty"
    assert entry["current_live_count"] == 0
    assert entry["archived_row_count"] == 0
    assert entry["rows_are_archived"] is False


# ---------------------------------------------------------------------------
# Asia Disclosure — PLANNED_NOT_SCORED with coverage rows
# ---------------------------------------------------------------------------


def test_asia_disclosure_optional_unconfigured_with_coverage_shape(tmp_path, monkeypatch):
    """Without EDINET/OpenDART keys, Asia Disclosure renders coverage rows
    only — no current-live signals, optional-not-configured warning."""
    _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    entry = payload["sources"]["asia_disclosure"]

    assert entry["display_state"] == "optional_unconfigured_with_coverage"
    assert entry["is_current_live"] is False
    assert entry["current_live_count"] == 0
    assert entry["coverage_row_count"] == 11
    assert entry["display_count_label"] == "Coverage rows"
    warning = entry["source_display_warning"].lower()
    assert "optional" in warning and "not configured" in warning


def test_asia_disclosure_coverage_rows_exposed_at_top_level(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    rows = payload.get("asia_disclosure_coverage_rows") or []
    assert len(rows) == 11
    countries = [r["country"] for r in rows]
    assert countries == [
        "China",
        "Japan",
        "Russia",
        "South Korea",
        "Turkey",
        "Indonesia",
        "Saudi Arabia",
        "Taiwan",
        "Israel",
        "Singapore",
        "United Arab Emirates",
    ]
    assert "India" not in countries
    # Each row must carry the documented columns.
    for r in rows:
        assert set(r.keys()) >= {"country", "disclosure_source", "source_url", "status", "notes"}
        assert r["status"] == "Active"


def test_asia_disclosure_coverage_keyed_by_source(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    coverage_by_source = payload.get("source_coverage_rows") or {}
    assert "asia_disclosure" in coverage_by_source
    assert len(coverage_by_source["asia_disclosure"]) == 11


def test_asia_disclosure_does_not_fake_live_signals(tmp_path, monkeypatch):
    """Coverage rows are configuration only — they must NEVER appear as
    rows in /live-signals or be counted as current_live.

    Real EDINET/OpenDART rows are allowed once ingestion succeeds, but in
    the isolated no-key/no-ingestion setup the count is 0 because nothing
    has been persisted into the test DB.  This test pins both invariants:
    (a) coverage countries never bleed into signal_events, (b) the
    monkeypatched DB is the only DB read by _get_live_signals (regression
    for the previous default-arg DB_PATH leak that exposed runtime rows).
    """
    _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)

    from scripts.api_server import _build_live_sources_status, _get_live_signals

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    entry = payload["sources"]["asia_disclosure"]
    assert entry["current_live_count"] == 0
    assert entry["rows_are_current_live"] is False

    # Isolated, empty DB: no ingestion has occurred, no rows must surface.
    signals = _get_live_signals(source_name="asia_disclosure", limit=200)
    assert signals["count"] == 0
    assert signals["live_signal_events"] == []

    # Coverage rows are configuration metadata — they must not be
    # synthesised into signal_events.  Cross-check the coverage countries
    # never appear as event source rows.
    coverage_countries = {
        r["country"]
        for r in (payload.get("asia_disclosure_coverage_rows") or [])
    }
    assert coverage_countries  # sanity: coverage table is populated
    for event in signals["live_signal_events"]:
        payload_blob = event.get("raw_payload") or {}
        # If a row ever appears, its country must come from real
        # provider data, not be a bare echo of the coverage row.
        if isinstance(payload_blob, dict):
            assert payload_blob.get("source_class") != "coverage_only"


def test_asia_disclosure_real_provider_rows_appear_as_live_signals(
    tmp_path, monkeypatch
):
    """Real EDINET/OpenDART rows persisted into signal_events are
    legitimate Asia Disclosure live signals and MUST be returned by
    _get_live_signals with provider/disclosure_system/source_class
    metadata that proves they came from an official API — not coverage."""
    import scripts.persistence as p

    db = _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)

    p.insert_signal_event(
        event_id="asia_disclosure_edinet_test_1",
        source_name="asia_disclosure",
        raw_payload={
            "signal_type": "asia_regulatory_disclosure",
            "issuer_name": "Test EDINET Issuer",
            "ticker_or_identifier": "1234",
            "exchange_or_regulator": "EDINET",
            "jurisdiction": "JP",
            "country": "Japan",
            "disclosure_system": "EDINET",
            "provider": "edinet",
            "source_class": "official_api",
            "title": "EDINET Filing",
        },
        fetched_at="2026-05-17T10:00:00+00:00",
        db_path=db,
    )
    p.insert_signal_event(
        event_id="asia_disclosure_opendart_test_1",
        source_name="asia_disclosure",
        raw_payload={
            "signal_type": "asia_regulatory_disclosure",
            "issuer_name": "Test OpenDART Issuer",
            "ticker_or_identifier": "005930",
            "exchange_or_regulator": "OpenDART",
            "jurisdiction": "KR",
            "country": "South Korea",
            "disclosure_system": "OpenDART",
            "provider": "opendart",
            "source_class": "official_api",
            "title": "OpenDART Filing",
        },
        fetched_at="2026-05-17T11:00:00+00:00",
        db_path=db,
    )

    from scripts.api_server import _get_live_signals

    signals = _get_live_signals(source_name="asia_disclosure", limit=200)
    assert signals["count"] == 2

    providers = set()
    systems = set()
    countries = set()
    for event in signals["live_signal_events"]:
        payload_blob = event["raw_payload"]
        assert isinstance(payload_blob, dict)
        # Real provider rows carry these official-API markers.
        assert payload_blob["source_class"] == "official_api"
        providers.add(payload_blob["provider"])
        systems.add(payload_blob["disclosure_system"])
        countries.add(payload_blob["country"])
    assert providers == {"edinet", "opendart"}
    assert systems == {"EDINET", "OpenDART"}
    assert countries == {"Japan", "South Korea"}

    # Coverage-table-only countries (e.g. those without an active API in
    # this test) MUST NOT appear merely because they are listed in the
    # coverage rows.
    assert "China" not in countries
    assert "Singapore" not in countries

    # Advisory invariants are stamped onto every event.
    for event in signals["live_signal_events"]:
        assert event["advisory_status"] == "ADVISORY_ONLY"
        assert event["execution_gate"] == "LOCKED"
        assert event["ai_execution_count"] == 0
    assert signals["advisory_status"] == "ADVISORY_ONLY"
    assert signals["human_review_required"] is True
    assert signals["ai_execution_count"] == 0


def test_get_live_signals_uses_isolated_db_path(tmp_path, monkeypatch):
    """Regression: _get_live_signals must honour the monkeypatched
    persistence.DB_PATH.  Previously ``get_signal_events`` froze the
    default ``db_path=DB_PATH`` at function-definition time, so callers
    that did not pass an explicit path silently read from the real
    runtime DB (``runtime/mvp_local.db``).  This test pins lazy
    resolution by seeding only the isolated DB and asserting the runtime
    DB's rows do not leak through."""
    import scripts.persistence as p

    db = _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)

    # Seed two distinct rows into the isolated DB only.
    p.insert_signal_event(
        event_id="iso-edinet-1",
        source_name="asia_disclosure",
        raw_payload={"provider": "edinet", "source_class": "official_api"},
        fetched_at="2026-05-17T09:00:00+00:00",
        db_path=db,
    )
    p.insert_signal_event(
        event_id="iso-opendart-1",
        source_name="asia_disclosure",
        raw_payload={"provider": "opendart", "source_class": "official_api"},
        fetched_at="2026-05-17T09:01:00+00:00",
        db_path=db,
    )

    from scripts.api_server import _get_live_signals

    signals = _get_live_signals(source_name="asia_disclosure", limit=500)
    # Exactly the two seeded rows — never the runtime DB's rows.
    assert signals["count"] == 2
    event_ids = {e["event_id"] for e in signals["live_signal_events"]}
    assert event_ids == {"iso-edinet-1", "iso-opendart-1"}

    # Sanity-check unrelated sources also resolve through the same DB.
    other = _get_live_signals(source_name="gdelt", limit=10)
    assert other["count"] == 0


# ---------------------------------------------------------------------------
# GDELT — stale active truthfulness
# ---------------------------------------------------------------------------


def test_gdelt_stale_active_remains_truthful(tmp_path, monkeypatch):
    """A core source whose latest log entry is FAIL/rate-limited and whose
    last OK refresh is older than the threshold remains stale_active."""
    import scripts.persistence as p

    db = _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)
    # Last log row is a failure; last successful OK is days old.
    p.log_source_run(
        source_name="gdelt",
        status="ok",
        fetched_count=10,
        skipped_reason="",
        error_message="",
        timestamp_utc="2026-05-10T12:00:00+00:00",
        duration_ms=5,
        db_path=db,
    )
    p.log_source_run(
        source_name="gdelt",
        status="fail",
        fetched_count=0,
        skipped_reason="",
        error_message="HTTP 429 rate_limited",
        timestamp_utc="2026-05-17T16:00:00+00:00",
        duration_ms=2,
        db_path=db,
    )
    p.record_live_source_refresh_run(
        run_id="gdelt-1",
        source_name="gdelt",
        attempted=True,
        success=False,
        skipped=False,
        started_at="2026-05-17T16:00:00+00:00",
        finished_at="2026-05-17T16:00:01+00:00",
        duration_seconds=1.0,
        rows_before=10,
        rows_after=10,
        rows_added=0,
        error_message="HTTP 429 rate_limited",
        db_path=db,
    )
    _seed_signal_events(db, "gdelt", count=5, fetched_at="2026-05-10T12:00:00+00:00")

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    assert "gdelt" in payload["stale_sources"]
    entry = payload["sources"]["gdelt"]
    assert entry["is_stale"] is True
    assert entry["display_state"] == "stale_active"
    assert entry["is_current_live"] is False
    # Reason chain must explain the rate-limit honestly.
    text = json.dumps(entry).lower()
    assert "rate_limited" in text or "429" in text or "refresh error" in text


# ---------------------------------------------------------------------------
# Cross-source roll-up + safety invariants
# ---------------------------------------------------------------------------


def test_optional_and_planned_excluded_from_stale_count(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    excluded = {(e["source"], e["reason"]) for e in payload.get("excluded_from_stale", [])}
    assert ("etherscan", "optional_config_missing") in excluded
    assert ("grok_xai", "optional_config_missing") in excluded
    # Asia Disclosure: now adapter_status=partial with optional EDINET /
    # OpenDART keys.  With no keys configured it is excluded via
    # optional_config_missing instead of planned_not_scored.
    assert ("asia_disclosure", "optional_config_missing") in excluded


def test_advisory_invariants_intact_under_display_state(tmp_path, monkeypatch):
    db = _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)
    _seed_signal_events(db, "etherscan", count=3, fetched_at="2026-05-12T12:00:00+00:00")

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["execution_permission"] is False
    assert payload["can_execute"] is False
    assert payload["human_review_required"] is True

    for key, entry in payload["sources"].items():
        assert entry["advisory_status"] == "ADVISORY_ONLY", key
        assert entry["execution_gate"] == "LOCKED", key
        assert entry["broker_api_called"] is False, key
        assert entry["can_execute"] is False, key
        assert entry["advisory_only"] is True, key


def test_no_execution_routes_introduced_by_display_fix():
    """Display-state fix must not have added execution endpoints/methods."""
    from scripts import api_server

    forbidden_substrings = (
        "place_order",
        "submit_order",
        "broker_execute",
        "send_to_broker",
        "trade_execute",
        "live_trade_execute",
        "broker.connect",
        "broker.place",
    )
    src = Path(api_server.__file__).read_text(encoding="utf-8")
    for token in forbidden_substrings:
        assert token not in src, f"forbidden execution token introduced: {token}"


def test_india_remains_its_own_source_family():
    """India must remain a distinct, implemented source family — the
    Asia Disclosure coverage fix must not move/rename it."""
    from scripts.live_source_registry import get_source_family, ALL_SOURCE_KEYS

    assert "india" in ALL_SOURCE_KEYS
    india = get_source_family("india")
    assert india["adapter_status"] == "implemented"


# ---------------------------------------------------------------------------
# Asia Disclosure — excluded_from_stale must reflect sub-source health
# (EDINET / OpenDART integration).  See the truth-fix doc: HEALTHY parent
# + "optional — not configured" stale-banner row is a contradiction.
# ---------------------------------------------------------------------------


def _seed_asia_disclosure_success(
    db_path: Path,
    *,
    timestamp: str = "2026-05-17T16:55:00+00:00",
    refresh_finished_at: str = "2026-05-17T16:55:01+00:00",
    fetched: int = 3,
) -> None:
    """Seed a successful OpenDART-style source_run_log + refresh row so
    asia_disclosure looks freshly healthy in this DB."""
    import scripts.persistence as p

    p.log_source_run(
        source_name="asia_disclosure",
        status="ok",
        fetched_count=fetched,
        skipped_reason="",
        error_message="",
        timestamp_utc=timestamp,
        duration_ms=20,
        db_path=db_path,
    )
    p.record_live_source_refresh_run(
        run_id="asia-ok-1",
        source_name="asia_disclosure",
        attempted=True,
        success=True,
        skipped=False,
        started_at=timestamp,
        finished_at=refresh_finished_at,
        duration_seconds=1.0,
        rows_before=0,
        rows_after=fetched,
        rows_added=fetched,
        db_path=db_path,
    )
    for i in range(fetched):
        p.insert_signal_event(
            event_id=f"asia_disclosure-opendart-{i}",
            source_name="asia_disclosure",
            raw_payload={
                "provider": "opendart",
                "disclosure_system": "OpenDART",
                "country": "South Korea",
                "source_class": "official_api",
                "title": f"OpenDART filing {i}",
            },
            fetched_at=timestamp,
            db_path=db_path,
        )


def test_asia_disclosure_with_opendart_success_is_not_optional_config_missing(
    tmp_path, monkeypatch
):
    """OPENDART_API_KEY configured and a recent successful run → parent
    must NOT be flagged optional_config_missing in excluded_from_stale,
    and the per-entry stale_excluded_reason must be absent.  This is the
    core contradiction the truth-fix closes."""
    db = _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)
    monkeypatch.setenv("OPENDART_API_KEY", "placeholder")

    _seed_asia_disclosure_success(db)

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    entry = payload["sources"]["asia_disclosure"]

    assert entry.get("stale_excluded_reason") is None
    assert entry["is_stale"] is False
    excluded = {(e["source"], e["reason"]) for e in payload.get("excluded_from_stale", [])}
    assert ("asia_disclosure", "optional_config_missing") not in excluded

    # And the parent should look like a current-live, configured source.
    assert entry["is_current_live"] is True
    assert entry["display_state"] == "current_live"
    assert entry["current_live_count"] == 3


def test_asia_disclosure_with_both_keys_missing_is_optional_config_missing(
    tmp_path, monkeypatch
):
    """When BOTH EDINET and OpenDART keys are missing and no active
    sub-source has succeeded, optional_config_missing is the truthful
    label and the source belongs in excluded_from_stale."""
    _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    entry = payload["sources"]["asia_disclosure"]

    assert entry["is_stale"] is False
    assert entry.get("stale_excluded_reason") == "optional_config_missing"
    excluded = {(e["source"], e["reason"]) for e in payload.get("excluded_from_stale", [])}
    assert ("asia_disclosure", "optional_config_missing") in excluded


def test_asia_disclosure_edinet_no_rows_opendart_success_is_partial_healthy(
    tmp_path, monkeypatch
):
    """If EDINET reports no_rows but OpenDART succeeds, the parent must
    surface as fresh/healthy (a real sub-source produced data) and never
    as optional_config_missing.  Truthful PARTIAL HEALTHY — not faked."""
    db = _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)
    # Only OpenDART key present in the env.
    monkeypatch.setenv("OPENDART_API_KEY", "placeholder")

    # OpenDART produced rows; record a successful refresh.  No EDINET rows.
    _seed_asia_disclosure_success(db, fetched=2)

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    entry = payload["sources"]["asia_disclosure"]

    assert entry.get("stale_excluded_reason") is None
    assert entry["is_stale"] is False
    assert entry["freshness_state"] == "fresh"
    assert entry["is_current_live"] is True
    # Health score derived from freshness=fresh + scored path → healthy.
    assert entry.get("health_label") == "healthy"
    # Sub-source state reflects the partial truth: OpenDART configured,
    # EDINET not — but the parent is not labelled missing-config.
    sub = entry.get("asia_disclosure_subsource_state") or {}
    assert sub.get("any_configured") is True
    assert sub.get("has_active_subsource_success") is True
    sub_map = sub.get("sub_sources") or {}
    assert sub_map.get("korea_opendart", {}).get("configured") is True
    assert sub_map.get("japan_edinet", {}).get("configured") is False


def test_asia_disclosure_healthy_payload_has_no_optional_config_missing_in_excluded(
    tmp_path, monkeypatch
):
    """Stale-banner reason must match backend per-entry truth: when
    asia_disclosure shows up as healthy/fresh in the per-source map, it
    must NOT appear in excluded_from_stale with optional_config_missing.

    This is the cross-field consistency check the UI relies on — the
    frontend ``StaleRefreshBanner`` reads ``excluded_from_stale`` and
    must not contradict the ``sources`` table the UI also renders.
    """
    db = _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)
    monkeypatch.setenv("OPENDART_API_KEY", "placeholder")

    _seed_asia_disclosure_success(db)

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    entry = payload["sources"]["asia_disclosure"]
    healthy = entry.get("health_label") == "healthy" and entry["is_current_live"]
    excluded = {(e["source"], e["reason"]) for e in payload.get("excluded_from_stale", [])}
    if healthy:
        assert ("asia_disclosure", "optional_config_missing") not in excluded, (
            "healthy parent must not appear in excluded_from_stale as "
            "optional_config_missing"
        )
        assert entry.get("stale_excluded_reason") is None


def test_asia_disclosure_not_excluded_when_no_key_but_run_succeeded(
    tmp_path, monkeypatch
):
    """The central truth-fix guarantee: a process whose env no longer has
    the sub-source key but whose DB shows a successful sub-source run
    must NOT slander the source as optional_config_missing.  Run history
    is the source of truth, not just the env probe.
    """
    db = _isolated_db(tmp_path, monkeypatch)
    _strip_live_keys(monkeypatch)
    # Simulate: key was set when refresh ran; rows persisted; env now bare.
    _seed_asia_disclosure_success(db)

    from scripts.api_server import _build_live_sources_status

    payload = _build_live_sources_status(now_iso="2026-05-17T17:00:00+00:00")
    excluded = {e["source"] for e in payload.get("excluded_from_stale", [])}
    assert "asia_disclosure" not in excluded
    entry = payload["sources"]["asia_disclosure"]
    assert entry.get("stale_excluded_reason") is None
    sub = entry.get("asia_disclosure_subsource_state") or {}
    assert sub.get("has_active_subsource_success") is True
