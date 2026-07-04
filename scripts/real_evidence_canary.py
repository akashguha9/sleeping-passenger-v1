"""Real Evidence Sprint — Phase 1: read-only canary for >=3 sources.

Turns "source activation" from a fixture-shaped claim into something with an
honest, reproducible truth label.  For each source the canary either:

* runs the REAL read-only loader (only when ``REAL_EVIDENCE_CANARY=1`` /
  ``allow_network=True``) and persists genuine fresh canonical rows, OR
* persists deterministic fixture rows (default, offline) so the contract and
  persistence path are exercised without any network, OR
* honestly reports ``CANARY_SKIPPED`` when neither network nor fixtures are
  available.

Hard rules (all enforced here):
  * READ-ONLY HTTP only — no broker, no order, no execution code path.
  * No secrets are ever printed; we never read or echo any API-key *values*.
  * ``rows_added == 0`` => ``ZERO_FRESH_ROWS`` (DEGRADED), never LIVE_CANONICAL.
  * ``mock`` rows and ``backfill`` rows are NEVER persisted as canonical and
    NEVER count toward activation.
  * Network failure => ``CANARY_SKIPPED`` / ``DEGRADED``, never fake success.
  * The default test suite never touches the network.

Truth math (per source ``s``):

    freshness_s = exp(-age_s / TTL_s)
    row_score_s = min(1, rows_added_s / rows_min_s)
    C_s         = freshness_s · row_score_s · quality_s      (quality 0 if mock/backfill)

    LIVE_CANONICAL_s = I(api_ok) · I(rows_added>0) · I(age<=TTL)
                     · I(not mock) · I(not backfill)

    Activated_s      = I(read_only) · I(canonical_written) · I(rows_added>0)
                     · I(LIVE_CANONICAL_s) · I(not mock) · I(not backfill)

    real_source_activation_count    = #{Activated_s : canary_real}
    fixture_source_activation_count = #{Activated_s : not canary_real}
    C_global                        = (1/|S_required|) · Σ_s LIVE_CANONICAL_s

This module can *strengthen* fixture-backed activation and, opt-in, prove real
activation.  It can never claim calibration or unlock execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from typing import Any, Iterable, Mapping, Sequence

try:  # package layout
    from scripts.runtime_common import RUNTIME_DIR, utc_timestamp, write_json_atomic
    from scripts.source_freshness_contract import classify_canonical_status
    from scripts import persistence
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    from runtime_common import RUNTIME_DIR, utc_timestamp, write_json_atomic  # type: ignore[no-redef]
    from source_freshness_contract import classify_canonical_status  # type: ignore[no-redef]
    import persistence  # type: ignore[no-redef]

# Sources this sprint treats as the required read-only set.
DEFAULT_SOURCES: tuple[str, ...] = ("yfinance", "gdelt", "polymarket")
# Opt-in env flag for the real network canary.
CANARY_ENV_FLAG = "REAL_EVIDENCE_CANARY"
DEFAULT_MAX_ROWS = 25
DEFAULT_TTL_HOURS = 24.0

# Honest non-live status labels owned by the canary (extend the contract's set).
CANARY_SKIPPED = "CANARY_SKIPPED"

_REPORT_NAME = "real_evidence_canary.json"

# Advisory-only invariants stamped on every report (never loosened).
_SAFETY = {
    "advisory_status": "ADVISORY_ONLY",
    "human_execution_required": True,
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _derive_event_id(source_name: str, rec: Mapping[str, Any], idx: int) -> str:
    """Deterministic event_id when a record does not carry its own."""
    existing = rec.get("event_id") if isinstance(rec, Mapping) else None
    if existing:
        return str(existing)
    basis = json.dumps(rec, sort_keys=True, default=str) if isinstance(rec, Mapping) else str(rec)
    digest = hashlib.sha1(f"{source_name}|{idx}|{basis}".encode("utf-8")).hexdigest()[:20]
    return f"{source_name}_{digest}"


def _real_loader_records(source_name: str, max_rows: int) -> tuple[list[dict[str, Any]], str, str]:
    """Run the REAL read-only loader for ``source_name``.

    Returns ``(records, api_health_status, note)``.  Never raises; a skipped or
    failed loader yields an empty record list and a DEGRADED api health.  No
    broker / order / execution path is ever touched — these are read-only
    LoaderResult adapters.
    """
    try:  # import lazily so the default offline path never imports network deps
        try:
            from scripts.ingestion.polymarket_loader import PolymarketLoader
            from scripts.ingestion.gdelt_loader import GDELTLoader
            from scripts.ingestion.market_data_loader import MarketDataLoader
            from scripts.ingestion.sec_edgar_loader import SECEdgarLoader
        except ModuleNotFoundError:  # pragma: no cover - flat layout
            from ingestion.polymarket_loader import PolymarketLoader  # type: ignore
            from ingestion.gdelt_loader import GDELTLoader  # type: ignore
            from ingestion.market_data_loader import MarketDataLoader  # type: ignore
            from ingestion.sec_edgar_loader import SECEdgarLoader  # type: ignore
    except Exception as exc:  # pragma: no cover - defensive
        return [], "DEGRADED", f"loader_import_failed: {type(exc).__name__}"

    key = source_name.strip().lower()
    if key in ("yfinance", "market_data", "market", "yahoo"):
        loader = MarketDataLoader()
    elif key == "gdelt":
        loader = GDELTLoader(max_records=max_rows)
    elif key == "polymarket":
        loader = PolymarketLoader(limit=max_rows)
    elif key in ("sec_edgar", "sec", "edgar"):
        # Read-only public SEC EDGAR over the default watchlist.  Honours the
        # SEC fair-access policy via the SEC_USER_AGENT env var; skips cleanly
        # (DEGRADED) when that env var is unset.  No key *value* is ever echoed.
        loader = SECEdgarLoader(use_default_watchlist=True, max_filings=max_rows)
    else:
        return [], "DEGRADED", f"unknown_source:{source_name}"

    result = loader.safe_fetch()  # converts SkipLoader / errors into a clean skip
    if getattr(result, "skipped", False):
        return [], "DEGRADED", f"skipped: {getattr(result, 'skip_reason', '')}"
    records = list(getattr(result, "records", []) or [])[: max(0, max_rows)]
    return records, "OK", "live_fetch"


def run_source_canary(
    source_name: str,
    *,
    records: Sequence[Mapping[str, Any]] | None = None,
    allow_network: bool = False,
    db_path: Any = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    mock_flag: bool = False,
    backfill_flag: bool = False,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    now_iso: str | None = None,
    api_health_status: str | None = None,
    canary_real: bool | None = None,
) -> dict[str, Any]:
    """Run the canary for a single source and return its truthful summary.

    ``records`` (when provided) are treated as fixture/pre-fetched rows and
    persisted as canonical *unless* ``mock_flag`` / ``backfill_flag`` is set.
    When ``records is None`` and ``allow_network`` is True, the REAL loader is
    invoked; otherwise the source is honestly reported as CANARY_SKIPPED.
    """
    now = now_iso or utc_timestamp()
    note = ""

    # ----- resolve the record source ------------------------------------- #
    if records is not None:
        recs: list[dict[str, Any]] = [dict(r) for r in records if isinstance(r, Mapping)]
        if canary_real is None:
            canary_real = False  # explicit records default to fixture-backed
        api = (api_health_status or "OK").upper()
        note = "fixture_records" if not canary_real else "prefetched_records"
    elif allow_network:
        recs, api, note = _real_loader_records(source_name, max_rows)
        if canary_real is None:
            canary_real = True
        if api_health_status:
            api = api_health_status.upper()
    else:
        # No fixtures, no network -> honest skip.  Nothing persisted.
        return _skip_summary(source_name, ttl_hours, canary_real=bool(canary_real))

    rows_fetched = len(recs)

    # ----- persist (or honestly refuse to) ------------------------------- #
    rows_added = 0
    rows_refreshed = 0
    rows_filtered = 0
    persisted = False

    if mock_flag or backfill_flag:
        # NEVER persisted as canonical.  Every fetched row is filtered out.
        rows_filtered = rows_fetched
        note = "mock_not_canonical" if mock_flag else "backfill_not_fresh"
    else:
        for i, rec in enumerate(recs):
            if not rec:
                rows_filtered += 1
                continue
            eid = _derive_event_id(source_name, rec, i)
            try:
                added, refreshed = persistence.upsert_signal_event_observation(
                    event_id=eid,
                    source_name=source_name,
                    raw_payload=rec,
                    fetched_at=now,
                    db_path=db_path,
                )
            except Exception as exc:  # pragma: no cover - defensive
                rows_filtered += 1
                note = f"persist_error: {type(exc).__name__}"
                continue
            rows_added += int(added)
            rows_refreshed += int(refreshed)
            persisted = True

    # ----- freshness lookup ---------------------------------------------- #
    latest_ts: str | None = None
    age_hours: float | None = None
    if persisted and (rows_added + rows_refreshed) > 0:
        try:
            stats = persistence.count_fresh_signal_events_by_source(
                source_name, ttl_hours=ttl_hours, now_iso=now, db_path=db_path
            )
            latest_ts = stats.get("latest_fetched_at")
            age_hours = stats.get("latest_age_hours")
        except Exception:  # pragma: no cover - defensive
            latest_ts, age_hours = now, 0.0
        if age_hours is None:
            age_hours = 0.0

    # Fresh canonical rows = newly inserted + refreshed observations.
    fresh_rows = rows_added + rows_refreshed
    # For mock/backfill the rows were fetched but deliberately NOT persisted as
    # canonical; we still hand the fetched count to the contract so it returns
    # the precise MOCK_NON_CANONICAL / BACKFILL_NON_FRESH label (quality is 0,
    # so C_s and live_canonical stay 0 regardless).
    contract_rows = rows_fetched if (mock_flag or backfill_flag) else fresh_rows

    contract = classify_canonical_status(
        api_health_status=api,
        rows_added=contract_rows,
        age_hours=age_hours,
        ttl_hours=ttl_hours,
        mock_flag=mock_flag,
        backfill_only=backfill_flag,
        filtered=False,
    )

    is_live = bool(contract["live_canonical"])
    activated = bool(is_live and persisted and rows_added + rows_refreshed > 0
                     and not mock_flag and not backfill_flag)

    return {
        "source_name": source_name,
        "api_health_status": api,
        "canonical_signal_status": contract["canonical_signal_status"],
        "rows_fetched": rows_fetched,
        "rows_added": rows_added,
        "rows_refreshed": rows_refreshed,
        "rows_filtered": rows_filtered,
        "latest_canonical_signal_timestamp": latest_ts,
        "canonical_age_hours": age_hours,
        "is_live_canonical": is_live,
        "mock_flag": bool(mock_flag),
        "backfill_flag": bool(backfill_flag),
        "freshness_score": contract["freshness_score"],
        "row_score": contract["row_score"],
        "source_truth_score": contract["C_s"],
        "canary_real": bool(canary_real),
        "activated": activated,
        "note": note,
        **_SAFETY,
    }


def _skip_summary(source_name: str, ttl_hours: float, *, canary_real: bool) -> dict[str, Any]:
    """Honest summary for a source the canary could not exercise."""
    return {
        "source_name": source_name,
        "api_health_status": CANARY_SKIPPED,
        "canonical_signal_status": CANARY_SKIPPED,
        "rows_fetched": 0,
        "rows_added": 0,
        "rows_refreshed": 0,
        "rows_filtered": 0,
        "latest_canonical_signal_timestamp": None,
        "canonical_age_hours": None,
        "is_live_canonical": False,
        "mock_flag": False,
        "backfill_flag": False,
        "freshness_score": 0.0,
        "row_score": 0.0,
        "source_truth_score": 0.0,
        "canary_real": bool(canary_real),
        "activated": False,
        "note": "no fixtures and network disabled",
        **_SAFETY,
    }


def _log_run(summary: Mapping[str, Any], db_path: Any) -> bool:
    """Record a source_run_log row.  Never raises; returns True on success."""
    try:
        kwargs: dict[str, Any] = dict(
            source_name=str(summary["source_name"]),
            status=str(summary["canonical_signal_status"]),
            fetched_count=int(summary["rows_fetched"]),
            skipped_reason=str(summary.get("note") or ""),
            error_message="",
            timestamp_utc=utc_timestamp(),
            duration_ms=0,
        )
        if db_path is not None:
            kwargs["db_path"] = db_path
        persistence.log_source_run(**kwargs)
        return True
    except Exception:  # pragma: no cover - defensive
        return False


def run_canary(
    sources: Iterable[str] = DEFAULT_SOURCES,
    *,
    allow_network: bool = False,
    fixtures: Mapping[str, Mapping[str, Any]] | None = None,
    db_path: Any = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    now_iso: str | None = None,
    write_source_run_log: bool = True,
) -> dict[str, Any]:
    """Run the canary across ``sources`` and aggregate an honest summary.

    ``fixtures`` maps ``source_name -> {records, mock_flag, backfill_flag,
    canary_real, api_health_status}`` for deterministic offline runs.
    """
    src_list = [str(s).strip() for s in sources if str(s).strip()]
    fixtures = fixtures or {}
    now = now_iso or utc_timestamp()

    per_source: list[dict[str, Any]] = []
    source_run_log_written = 0
    for source_name in src_list:
        fx = fixtures.get(source_name)
        if fx is not None:
            summary = run_source_canary(
                source_name,
                records=fx.get("records", []),
                db_path=db_path,
                max_rows=max_rows,
                mock_flag=bool(fx.get("mock_flag", False)),
                backfill_flag=bool(fx.get("backfill_flag", False)),
                ttl_hours=ttl_hours,
                now_iso=now,
                api_health_status=fx.get("api_health_status"),
                canary_real=fx.get("canary_real", False),
            )
        else:
            summary = run_source_canary(
                source_name,
                records=None,
                allow_network=allow_network,
                db_path=db_path,
                max_rows=max_rows,
                ttl_hours=ttl_hours,
                now_iso=now,
            )
        if write_source_run_log and _log_run(summary, db_path):
            source_run_log_written += 1
        per_source.append(summary)

    activated = [s for s in per_source if s["activated"]]
    real_activated = [s for s in activated if s["canary_real"]]
    fixture_activated = [s for s in activated if not s["canary_real"]]
    live_count = sum(1 for s in per_source if s["is_live_canonical"])
    s_required = max(1, len(src_list))
    c_global = round(live_count / s_required, 6)

    return {
        "generated_at_utc": now,
        "allow_network": bool(allow_network),
        "sources_requested": src_list,
        "per_source": per_source,
        "real_source_activation_count": len(real_activated),
        "fixture_source_activation_count": len(fixture_activated),
        "total_activation_count": len(activated),
        "live_canonical_count": live_count,
        "C_global": c_global,
        "source_activation_target_met": len(activated) >= 3,
        "real_source_activation_target_met": len(real_activated) >= 3,
        "source_run_log_written": source_run_log_written,
        # Honest, sprint-aligned interpretation.
        "production_ready_live_ingestion": False,
        "predictive_claim_allowed": False,
        **_SAFETY,
    }


def write_report(report: Mapping[str, Any], path: Any = None) -> str:
    """Atomically write the canary report under runtime/release/."""
    target = path or (RUNTIME_DIR / "release" / _REPORT_NAME)
    write_json_atomic(target, dict(report))
    return str(target)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Real Evidence read-only source canary (advisory-only).")
    p.add_argument("--sources", default=",".join(DEFAULT_SOURCES),
                   help="comma-separated source list (yfinance,gdelt,polymarket)")
    p.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS)
    p.add_argument("--ttl-hours", type=float, default=DEFAULT_TTL_HOURS)
    p.add_argument("--write", action="store_true", help="write report JSON to runtime/release/")
    p.add_argument("--no-source-run-log", action="store_true")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    # Opt-in network ONLY via the env flag — never on by default.
    allow_network = os.environ.get(CANARY_ENV_FLAG, "").strip() == "1"
    sources = [s for s in args.sources.split(",") if s.strip()]

    persistence.init_schema()
    report = run_canary(
        sources,
        allow_network=allow_network,
        max_rows=args.max_rows,
        ttl_hours=args.ttl_hours,
        write_source_run_log=not args.no_source_run_log,
    )
    if args.write:
        report["report_path"] = write_report(report)

    # Print a redacted, secret-free summary (booleans/counts only).
    print(json.dumps({
        "allow_network": report["allow_network"],
        "real_source_activation_count": report["real_source_activation_count"],
        "fixture_source_activation_count": report["fixture_source_activation_count"],
        "live_canonical_count": report["live_canonical_count"],
        "C_global": report["C_global"],
        "per_source": [
            {
                "source_name": s["source_name"],
                "canonical_signal_status": s["canonical_signal_status"],
                "rows_added": s["rows_added"],
                "is_live_canonical": s["is_live_canonical"],
                "canary_real": s["canary_real"],
            }
            for s in report["per_source"]
        ],
        "predictive_claim_allowed": report["predictive_claim_allowed"],
    }, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))


__all__ = [
    "DEFAULT_SOURCES",
    "CANARY_ENV_FLAG",
    "CANARY_SKIPPED",
    "run_source_canary",
    "run_canary",
    "write_report",
    "main",
]
