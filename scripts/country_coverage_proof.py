"""C_global country-coverage proof (mission P4) — honest, never fabricated.

A country is "covered" only when ALL five required layers align::

    coverage(c) = universe_loaded(c) * price_support(c) * news_support(c)
                  * mapping_support(c) * synthesis_consumed(c)

    C_global = (1 / |G|) * sum_c coverage(c)        (|G| = top-30 set size)

This module builds the per-target proof table (coverage, target_readiness,
missing_layers, status) on top of the canonical coverage engine in
:mod:`scripts.top30_country_coverage`, and writes
``data/daily_payload/country_coverage_proof.json``.

It separates a deterministic FIXTURE proof (which proves the math —
coverage(Germany)=1 and C_global=1/30 when exactly one country is covered) from
a REAL-RUN proof derived from actual payload/price/mapping rows. It NEVER marks
a fixture as a live run, NEVER fabricates a layer, and is advisory-only (no
broker, no execution).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.runtime_common import REPO_ROOT, ensure_directory, utc_timestamp
    from scripts.top30_country_coverage import (
        build_country_coverage_from_payload,
        compute_country_coverage,
        load_top30_countries,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from runtime_common import REPO_ROOT, ensure_directory, utc_timestamp
    from top30_country_coverage import (
        build_country_coverage_from_payload,
        compute_country_coverage,
        load_top30_countries,
    )

# Default payload staleness TTL (hours). A payload JSON older than this — or with
# no recoverable timestamp — is treated as STALE and cannot suppress fresh
# SQLite-bridge evidence.
PAYLOAD_TTL_HOURS = 24.0


DAILY_PAYLOAD_DIR = REPO_ROOT / "data" / "daily_payload"
COUNTRY_COVERAGE_PROOF_PATH = DAILY_PAYLOAD_DIR / "country_coverage_proof.json"

DEFAULT_TARGET_COUNTRIES: tuple[str, ...] = (
    "Germany",
    "United Kingdom",
    "India",
    "Japan",
    "United States",
)

# The five layers that multiply into coverage(c) (filings is tracked but is not
# a coverage factor — coverage uses news_support per the canonical formula).
COVERAGE_LAYERS: tuple[str, ...] = (
    "universe_loaded",
    "price_support",
    "news_support",
    "mapping_support",
    "synthesis_consumed",
)


def target_readiness(row: dict[str, Any]) -> float:
    """0.20 weight on each of the five coverage layers, in [0,1]."""
    return round(sum(0.20 * int(bool(row.get(layer))) for layer in COVERAGE_LAYERS), 4)


def missing_layers(row: dict[str, Any]) -> list[str]:
    """The coverage layers a country still lacks (empty when covered)."""
    return [layer for layer in COVERAGE_LAYERS if not row.get(layer)]


def _global_status(covered_count: int, max_readiness: float) -> str:
    if covered_count >= 1:
        return "C_GLOBAL_POSITIVE"
    if max_readiness >= 0.80:
        return "ONE_LAYER_MISSING"
    if max_readiness >= 0.60:
        return "PARTIAL_TARGET_COUNTRY_COVERAGE"
    return "COVERAGE_THIN"


def _proof_envelope(
    coverage_result: dict[str, Any],
    *,
    target_countries: Iterable[str],
    run_timestamp_utc: str | None,
    proof_kind: str,
) -> dict[str, Any]:
    """Assemble the proof envelope from a canonical coverage result."""
    targets = list(target_countries)
    rows_by_country = {r["country"]: r for r in coverage_result["countries"]}
    ratios = coverage_result["ratios"]

    target_rows: list[dict[str, Any]] = []
    for country in targets:
        base = rows_by_country.get(country, {})
        row = {
            "country": country,
            "universe_loaded": int(bool(base.get("universe_loaded"))),
            "price_support": int(bool(base.get("price_support"))),
            "news_support": int(bool(base.get("news_support"))),
            "filings_support": int(bool(base.get("filings_support"))),
            "mapping_support": int(bool(base.get("mapping_support"))),
            "synthesis_consumed": int(bool(base.get("synthesis_consumed"))),
            "coverage": int(bool(base.get("coverage"))),
        }
        row["target_readiness"] = target_readiness(row)
        row["missing_layers"] = missing_layers(row)
        row["status"] = base.get("coverage_status", "NOT_IN_UNIVERSE")
        target_rows.append(row)

    covered = [r for r in coverage_result["countries"] if r.get("coverage")]
    covered_count = len(covered)
    first_covered = covered[0]["country"] if covered else None
    max_readiness = max((r["target_readiness"] for r in target_rows), default=0.0)

    return {
        "proof_kind": proof_kind,  # "FIXTURE" or "REAL_RUN" — never conflated
        "run_timestamp_utc": run_timestamp_utc or utc_timestamp(),
        "target_countries": targets,
        "country_rows": target_rows,
        "C_global": ratios["C_global"],
        "C_universe": ratios["C_universe"],
        "C_price": ratios["C_price"],
        "C_news": ratios["C_news"],
        "C_filings": ratios["C_filings"],
        "C_mapping": ratios["C_mapping"],
        "C_synthesis": ratios["C_synthesis"],
        "covered_country_count": covered_count,
        "first_covered_country": first_covered,
        "global_status": _global_status(covered_count, max_readiness),
        "top30_country_count": coverage_result.get("top30_country_count"),
        "advisory_only": True,
        "human_review_required": True,
        "executable_allowed": False,
        "safety": advisory_safety_stamps(),
    }


def build_coverage_proof(
    *,
    universe_countries: Iterable[str],
    price_countries: Iterable[str],
    news_countries: Iterable[str],
    filings_countries: Iterable[str],
    mapping_countries: Iterable[str],
    synthesis_countries: Iterable[str],
    target_countries: Iterable[str] = DEFAULT_TARGET_COUNTRIES,
    top30: list[str] | None = None,
    run_timestamp_utc: str | None = None,
    proof_kind: str = "FIXTURE",
) -> dict[str, Any]:
    """Build a proof from explicit per-layer country sets (deterministic)."""
    coverage_result = compute_country_coverage(
        universe_countries=universe_countries,
        price_countries=price_countries,
        news_countries=news_countries,
        filings_countries=filings_countries,
        mapping_countries=mapping_countries,
        synthesis_countries=synthesis_countries,
        top30=top30,
    )
    return _proof_envelope(
        coverage_result,
        target_countries=target_countries,
        run_timestamp_utc=run_timestamp_utc,
        proof_kind=proof_kind,
    )


def build_proof_from_payload(
    payload: dict[str, Any],
    *,
    price_rows: list[dict[str, Any]] | None = None,
    mapping_rows: list[dict[str, Any]] | None = None,
    universe_records: list[dict[str, Any]] | None = None,
    target_countries: Iterable[str] = DEFAULT_TARGET_COUNTRIES,
    top30: list[str] | None = None,
    run_timestamp_utc: str | None = None,
    proof_kind: str = "REAL_RUN",
) -> dict[str, Any]:
    """Build a proof from real daily-payload + price/mapping rows."""
    coverage_result = build_country_coverage_from_payload(
        payload,
        price_rows=price_rows,
        mapping_rows=mapping_rows,
        universe_records=universe_records,
        top30=top30,
    )
    return _proof_envelope(
        coverage_result,
        target_countries=target_countries,
        run_timestamp_utc=run_timestamp_utc,
        proof_kind=proof_kind,
    )


def germany_fixture_coverage(top30: list[str] | None = None) -> dict[str, Any]:
    """Deterministic single-country (Germany) coverage fixture.

    Proves the math: with exactly Germany covered across all five layers and a
    30-country G, ``coverage(Germany)=1`` and ``C_global=1/30=0.0333``. This is
    a FIXTURE proof (no live data) — every layer here is an explicit fixture
    assertion, NEVER a real-run claim.
    """
    g = ["Germany"]
    return build_coverage_proof(
        universe_countries=g,
        price_countries=g,       # RHM.DE valid price
        news_countries=g,        # fresh Rheinmetall news/disclosure
        filings_countries=g,
        mapping_countries=g,     # Rheinmetall -> RHM.DE conf >= 0.70
        synthesis_countries=g,   # consumed by the daily payload
        target_countries=DEFAULT_TARGET_COUNTRIES,
        top30=top30,
        proof_kind="FIXTURE",
    )


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _payload_fresh_events(
    payload_path: Path, now_utc: datetime, ttl_hours: float
) -> tuple[list[dict[str, Any]], bool, int]:
    """Return ``(fresh_events, payload_stale, rows_considered)`` for one JSON file.

    ``payload_stale`` is True when the file is missing, has no recoverable
    timestamp, or its newest event is older than ``ttl_hours``. Fresh events are
    the rows whose own timestamp is within ``ttl_hours`` — a stale file's rows
    are NEVER allowed to satisfy a coverage layer.
    """
    if not payload_path.exists():
        return [], True, 0
    try:
        blob = json.loads(payload_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], True, 0
    events = []
    if isinstance(blob, dict):
        events = blob.get("events") or []
    rows_considered = len(events)

    def _row_ts(row: dict[str, Any]) -> datetime | None:
        for key in ("event_timestamp_utc", "published_at_utc", "published_at", "timestamp_utc"):
            dt = _parse_iso(row.get(key))
            if dt is not None:
                return dt
        return None

    fresh: list[dict[str, Any]] = []
    newest: datetime | None = None
    for row in events:
        if not isinstance(row, dict):
            continue
        ts = _row_ts(row)
        if ts is None:
            continue
        if newest is None or ts > newest:
            newest = ts
        age_hours = (now_utc - ts).total_seconds() / 3600.0
        if age_hours <= ttl_hours:
            fresh.append(row)
    payload_stale = newest is None or (now_utc - newest).total_seconds() / 3600.0 > ttl_hours
    return fresh, payload_stale, rows_considered


def build_proof_from_sqlite_bridge(
    db_path: Path | None,
    *,
    payload_dir: Path | None = None,
    price_rows: list[dict[str, Any]] | None = None,
    universe_records: list[dict[str, Any]] | None = None,
    target_countries: Iterable[str] = DEFAULT_TARGET_COUNTRIES,
    top30: list[str] | None = None,
    now_utc: datetime | None = None,
    payload_ttl_hours: float = PAYLOAD_TTL_HOURS,
    securities_master_path: Path | None = None,
    run_timestamp_utc: str | None = None,
) -> dict[str, Any]:
    """REAL_RUN proof that prefers FRESH SQLite-bridge rows over stale JSON (P3).

    Evidence precedence::

        E_real = E_sqlite_fresh ∪ E_payload_fresh

    Fresh rows from the canonical SQLite ``signal_events`` bridge always count;
    on-disk payload rows count only when their file is NOT stale. A stale JSON
    payload can therefore never suppress fresh SQLite evidence — and the proof
    records ``payload_stale`` + per-source diagnostics so nothing is silent.

    ``mapping_support`` is fed from the bridge's own mapped rows
    (mapping_confidence >= theta_map), so a fresh mapped RHM.DE row satisfies
    Germany mapping_support without any fabricated mapping.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    payload_dir = payload_dir or DAILY_PAYLOAD_DIR

    try:
        from scripts.signal_events_to_daily_payload import (
            build_filings_payload_from_signal_events,
            build_news_payload_from_signal_events,
        )
    except ModuleNotFoundError:  # pragma: no cover - script-style env
        from signal_events_to_daily_payload import (  # type: ignore[no-redef]
            build_filings_payload_from_signal_events,
            build_news_payload_from_signal_events,
        )

    # --- E_sqlite_fresh: canonical SQLite bridge (already fresh-only) --------
    news_bridge = build_news_payload_from_signal_events(
        db_path, now_utc=now_utc, securities_master_path=securities_master_path
    )
    filings_bridge = build_filings_payload_from_signal_events(
        db_path, now_utc=now_utc, securities_master_path=securities_master_path
    )
    sqlite_news = list(news_bridge.get("events") or [])
    sqlite_filings = list(filings_bridge.get("events") or [])
    sqlite_fresh_rows_count = len(sqlite_news) + len(sqlite_filings)

    # --- E_payload_fresh: on-disk JSON, only if not stale -------------------
    news_fresh_disk, news_payload_stale, news_rows_considered = _payload_fresh_events(
        payload_dir / "today_news_events.json", now_utc, payload_ttl_hours
    )
    filings_fresh_disk, filings_payload_stale, filings_rows_considered = _payload_fresh_events(
        payload_dir / "today_filings_events.json", now_utc, payload_ttl_hours
    )
    payload_stale = bool(news_payload_stale or filings_payload_stale)
    payload_rows_considered = news_rows_considered + filings_rows_considered

    # Union: SQLite fresh always; disk fresh only when its file is not stale.
    combined_news = list(sqlite_news)
    if not news_payload_stale:
        combined_news += news_fresh_disk
    combined_filings = list(sqlite_filings)
    if not filings_payload_stale:
        combined_filings += filings_fresh_disk

    payload = {
        "news_events": {"events": combined_news},
        "filings_events": {"events": combined_filings},
        "price_movers": {"movers": []},
    }

    # mapping_support comes from the bridge's MAPPED fresh rows (>= theta_map).
    try:
        from scripts.entity_ticker_mapper import DEFAULT_THETA_MAP
    except ModuleNotFoundError:  # pragma: no cover - script-style env
        from entity_ticker_mapper import DEFAULT_THETA_MAP  # type: ignore[no-redef]
    theta = DEFAULT_THETA_MAP
    mapping_rows: list[dict[str, Any]] = []
    for row in combined_news + combined_filings:
        if row.get("mapping_status") != "MAPPED":
            continue
        try:
            conf = float(row.get("mapping_confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < theta:
            continue
        mapping_rows.append(
            {
                "ticker": row.get("ticker"),
                "country": row.get("country"),
                "mapping_confidence": conf,
            }
        )

    proof = build_proof_from_payload(
        payload,
        price_rows=price_rows or [],
        mapping_rows=mapping_rows,
        universe_records=universe_records,
        target_countries=target_countries,
        top30=top30,
        run_timestamp_utc=run_timestamp_utc or now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        proof_kind="REAL_RUN",
    )

    sources_used = []
    if sqlite_fresh_rows_count:
        sources_used.append("SQLITE_BRIDGE")
    if (news_fresh_disk and not news_payload_stale) or (filings_fresh_disk and not filings_payload_stale):
        sources_used.append("PAYLOAD_FRESH")
    if not sources_used:
        sources_used.append("NONE_FRESH")

    proof.update(
        proof_sources_used=sources_used,
        sqlite_rows_considered=sqlite_fresh_rows_count,
        payload_rows_considered=payload_rows_considered,
        fixture_rows_considered=0,
        payload_stale=payload_stale,
        sqlite_fresh_rows_count=sqlite_fresh_rows_count,
        sqlite_bridge_diagnostics={
            "news": news_bridge.get("meta", {}).get("diagnostics"),
            "filings": filings_bridge.get("meta", {}).get("diagnostics"),
        },
        mapped_bridge_rows=len(mapping_rows),
    )
    return proof


def write_country_coverage_proof(
    proof: dict[str, Any], path: Path | None = None
) -> Path:
    """Atomically write the proof JSON to disk."""
    target = path or COUNTRY_COVERAGE_PROOF_PATH
    ensure_directory(target.parent)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(proof, indent=2, default=str), encoding="utf-8")
    tmp.replace(target)
    return target


__all__ = [
    "DEFAULT_TARGET_COUNTRIES",
    "COVERAGE_LAYERS",
    "COUNTRY_COVERAGE_PROOF_PATH",
    "target_readiness",
    "missing_layers",
    "PAYLOAD_TTL_HOURS",
    "build_coverage_proof",
    "build_proof_from_payload",
    "build_proof_from_sqlite_bridge",
    "germany_fixture_coverage",
    "write_country_coverage_proof",
]
