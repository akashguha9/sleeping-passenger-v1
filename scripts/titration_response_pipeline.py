"""Evidence→response observation pipeline for the Market Titration layer.

Builds the dataset that turns titration from a heuristic readiness model
into a measurable one:

    signal_events (evidence arrivals, per ticker)
      × titration engine evaluated AS-OF each arrival (features)
      × ohlcv_bars forward responses (outcomes, bar-indexed horizons)
      → titration_response_observations
      → titration_susceptibility_estimates  (Theil–Sen, shrunk, gated)
      → titration_state_transitions          (historical state history)
      → runtime/titration_response_summary.json

Leakage safety (test-enforced in tests/test_titration_response_pipeline.py):

* Features at event time t use ONLY events with timestamp <= t — the
  engine is re-evaluated with the truncated event list and ``now=t``.
* The outcome reference bar is the first bar at/after t; sigma_pre uses
  bars strictly before it; forward prices appear only as outcomes.
* A horizon that has not elapsed is NOT_YET_MATURED and is excluded from
  every estimate.
* Synthetic fixture bars are EXCLUDED in runtime mode (matches the
  ohlcv_import_contract convention).

Advisory-only: this pipeline reads and writes local record-keeping tables;
it never places orders, never calls brokers, and its outputs carry the
platform's honesty labels (measured slopes are not probabilities).

CLI:
    python scripts/titration_response_pipeline.py --json
    python scripts/titration_response_pipeline.py --dry-run --json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import persistence
    from scripts.market_titration_engine import (
        TITRATION_SCHEMA_VERSION,
        TITRATION_SCORING_VERSION,
        evaluate_market_titration,
        load_titration_config,
    )
    from scripts.signal_inbox_bridge import _ticker_for_event
    from scripts.titration_outcome_contract import (
        MATURED,
        OUTCOME_CONTRACT_SCHEMA_VERSION,
        compute_forward_responses,
        load_outcome_config,
    )
    from scripts.titration_susceptibility import (
        DEFAULT_PARAMS as _CHI_PARAMS,
        estimate_scope,
        market_for_ticker,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import persistence  # type: ignore[no-redef]
    from market_titration_engine import (  # type: ignore[no-redef]
        TITRATION_SCHEMA_VERSION,
        TITRATION_SCORING_VERSION,
        evaluate_market_titration,
        load_titration_config,
    )
    from signal_inbox_bridge import _ticker_for_event  # type: ignore[no-redef]
    from titration_outcome_contract import (  # type: ignore[no-redef]
        MATURED,
        OUTCOME_CONTRACT_SCHEMA_VERSION,
        compute_forward_responses,
        load_outcome_config,
    )
    from titration_susceptibility import (  # type: ignore[no-redef]
        DEFAULT_PARAMS as _CHI_PARAMS,
        estimate_scope,
        market_for_ticker,
    )

try:
    from scripts.titration_susceptibility import estimate_catalytic_convexity
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from titration_susceptibility import (  # type: ignore[no-redef]
        estimate_catalytic_convexity,
    )

PIPELINE_VERSION = "titration_response_pipeline_v1"

SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
    "human_review_required": True,
}

# Per-ticker cap on evidence events considered (oldest dropped) — keeps the
# O(n^2) as-of engine replay bounded.
MAX_EVENTS_PER_TICKER = 200
# Cap on tickers processed per run (deterministic: alphabetical).
MAX_TICKERS = 500


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _collect_events_by_ticker(
    db_path: Path | None,
) -> dict[str, list[dict[str, Any]]]:
    """Group signal_events into per-ticker chronological evidence lists.

    Skips events whose ticker cannot be resolved (mapping failure is an
    exclusion, not a fabrication) and market-data candle rows (those are
    prices, not evidence).
    """
    kwargs: dict[str, Any] = {"limit": 100000}
    if db_path is not None:
        kwargs["db_path"] = db_path
    try:
        rows = persistence.get_signal_events(**kwargs)
    except Exception:
        return {}
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        source = str(row.get("source_name", "") or "")
        if source == "market_data":
            continue  # OHLCV backfill rows are outcomes, never evidence
        payload = row.get("raw_payload")
        if not isinstance(payload, dict):
            payload = {}
        try:
            ticker = _ticker_for_event(source, payload)
        except Exception:
            ticker = ""
        ticker = str(ticker or "").strip().upper()
        if not ticker or ticker in {"UNKNOWN", "N/A", "MULTI"}:
            continue
        ts = str(row.get("fetched_at", "") or "")
        if not ts:
            continue
        by_ticker.setdefault(ticker, []).append({
            "event_id": str(row.get("event_id", "") or ""),
            "fetched_at": ts,
            "source_name": source,
        })
    for ticker in list(by_ticker):
        events = sorted(by_ticker[ticker], key=lambda e: e["fetched_at"])
        by_ticker[ticker] = events[-MAX_EVENTS_PER_TICKER:]
    return dict(sorted(by_ticker.items())[:MAX_TICKERS])


def _security_context(ticker: str, db_path: Path | None) -> tuple[str, str | None]:
    """(market, sector) from the securities master, falling back to the
    ticker-suffix heuristic.  Sector stays None when the master has none —
    the hierarchy records the skip instead of inventing a sector."""
    country = None
    sector = None
    try:
        kwargs: dict[str, Any] = {}
        if db_path is not None:
            kwargs["db_path"] = db_path
        sec = persistence.get_global_security(ticker, **kwargs)
        if isinstance(sec, dict):
            country = sec.get("country") or None
            sector = (sec.get("sector") or "").strip() or None
    except Exception:
        pass
    return market_for_ticker(ticker, country), sector


def _engine_item_asof(
    ticker: str, events: list[dict[str, Any]], upto_idx: int
) -> dict[str, Any]:
    """Inbox-item shape for the engine using ONLY events[0..upto_idx]."""
    window = events[: upto_idx + 1]
    return {
        "ticker": ticker,
        "event_id": window[-1]["event_id"],
        "event_timestamps": [e["fetched_at"] for e in window],
        "event_sources": [e["source_name"] for e in window],
        "event_count": len(window),
        "cross_source_support_count": len({e["source_name"] for e in window}),
        "duplicate_suppressed_count": 0,
        "observed_at": window[-1]["fetched_at"],
        # contamination / chaos-sensitivity diagnostics are request-time
        # enrichments; historically unavailable -> engine lists them as
        # missing temperature inputs rather than zero-filling.
    }


def build_observations(
    *,
    db_path: Path | None = None,
    now: datetime | None = None,
    runtime_mode: bool = True,
) -> dict[str, Any]:
    """Compute the full observation set + state transitions (pure read)."""
    titration_cfg = load_titration_config()
    outcome_cfg = load_outcome_config()
    events_by_ticker = _collect_events_by_ticker(db_path)

    bars_cache: dict[str, list[dict[str, Any]]] = {}

    def _bars(ticker: str) -> list[dict[str, Any]]:
        if ticker not in bars_cache:
            try:
                kwargs: dict[str, Any] = {}
                if db_path is not None:
                    kwargs["db_path"] = db_path
                bars_cache[ticker] = persistence.get_ohlcv_bars(ticker, **kwargs)
            except Exception:
                bars_cache[ticker] = []
        return bars_cache[ticker]

    benchmark_name = None
    for spec in outcome_cfg["outcome_definitions"].values():
        if spec.get("family") == "BENCHMARK_RELATIVE":
            benchmark_name = str(spec.get("benchmark") or "") or None
    benchmark_bars = _bars(benchmark_name) if benchmark_name else []

    computed_at = _utc_now_iso()
    observations: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    tickers_with_bars = 0
    tickers_without_bars = 0

    for ticker, events in events_by_ticker.items():
        bars = _bars(ticker)
        if bars:
            tickers_with_bars += 1
        else:
            tickers_without_bars += 1
        market, sector = _security_context(ticker, db_path)
        prev_state: str | None = None
        for idx, event in enumerate(events):
            event_ts = event["fetched_at"]
            item = _engine_item_asof(ticker, events, idx)
            payload = evaluate_market_titration(
                item, now=event_ts, config=titration_cfg
            )
            state = str(payload.get("titration_state") or "INSUFFICIENT_DATA")
            if prev_state is not None and state != prev_state:
                transitions.append({
                    "ticker": ticker,
                    "event_id": event["event_id"],
                    "prev_state": prev_state,
                    "new_state": state,
                    "transitioned_at": event_ts,
                    "rule_trace": json.dumps(payload.get("state_rule_trace") or []),
                    "confidence": str(
                        (payload.get("data_sufficiency") or {}).get("level", "")
                    ),
                    "model_version": TITRATION_SCORING_VERSION,
                    "recorded_at": computed_at,
                })
            prev_state = state

            active_after = (payload.get("active_evidence") or {}).get("normalized")
            flow = payload.get("flow") or {}
            geometry = payload.get("geometry") or {}
            temperature = payload.get("temperature") or {}

            # Dose: decayed mass this event contributes at its own arrival
            # (age 0 => quality*reliability priors).  Derived by diffing
            # against the engine's own as-of evaluation one event earlier.
            if idx > 0:
                prev_payload = evaluate_market_titration(
                    _engine_item_asof(ticker, events, idx - 1),
                    now=event_ts, config=titration_cfg,
                )
                active_before = (prev_payload.get("active_evidence") or {}).get(
                    "normalized"
                )
            else:
                active_before = 0.0
            dose = None
            if isinstance(active_after, (int, float)) and isinstance(
                active_before, (int, float)
            ):
                dose = max(0.0, float(active_after) - float(active_before))

            responses = compute_forward_responses(
                bars, event_ts,
                direction=None,  # per-event direction unavailable — honest
                benchmark_bars=benchmark_bars if benchmark_name != ticker else None,
                config=outcome_cfg,
                runtime_mode=runtime_mode,
            )
            for hrow in responses["horizons"]:
                observations.append({
                    "obs_id": f"{event['event_id']}_{hrow['horizon']}",
                    "ticker": ticker,
                    "market": market,
                    "sector": sector,
                    "event_id": event["event_id"],
                    "event_ts": event_ts,
                    "entry_bar_date": responses["entry_bar_date"],
                    "reference_price": responses["reference_price"],
                    "price_field": responses["price_field"] or "",
                    "sigma_pre": responses["sigma_pre"],
                    "dose": dose,
                    "active_before": active_before,
                    "active_after": active_after,
                    "accumulation_velocity": geometry.get("velocity"),
                    "acceleration": geometry.get("acceleration"),
                    "geometry": geometry.get("label") or "",
                    "temperature": temperature.get("temperature"),
                    "goldilocks": temperature.get("goldilocks_quality"),
                    "barrier": (payload.get("barrier") or {}).get("barrier"),
                    "lrr": (payload.get("lrr") or {}).get("lrr"),
                    "vmr": (payload.get("vmr") or {}).get("vmr"),
                    "pag": payload.get("pre_alpha_gap"),
                    "ftr": (payload.get("false_transition_risk") or {}).get("ftr"),
                    "titration_state": state,
                    "horizon": int(hrow["horizon"]),
                    "maturation": hrow["maturation"],
                    "exclusion_reason": hrow["exclusion_reason"],
                    "r_raw": hrow["r_raw"],
                    "z": hrow["z"],
                    "mfe": hrow.get("mfe"),
                    "mae": hrow.get("mae"),
                    "time_to_transition_days": hrow.get("time_to_transition_days"),
                    "y_absolute": hrow["y_absolute"],
                    "y_directional": hrow["y_directional"],
                    "y_benchmark_relative": hrow["y_benchmark_relative"],
                    "outcome_def_version": OUTCOME_CONTRACT_SCHEMA_VERSION,
                    "model_version": TITRATION_SCHEMA_VERSION,
                    "scoring_version": TITRATION_SCORING_VERSION,
                    "computed_at": computed_at,
                    # flow diagnostics kept out of the table but available
                    # to callers via this in-memory row
                    "_net_accumulation": flow.get("net_accumulation"),
                })

    return {
        "observations": observations,
        "transitions": transitions,
        "ticker_count": len(events_by_ticker),
        "tickers_with_bars": tickers_with_bars,
        "tickers_without_bars": tickers_without_bars,
        "computed_at": computed_at,
    }


def build_susceptibility_estimates(
    observations: list[dict[str, Any]],
    *,
    outcome_def_version: str = OUTCOME_CONTRACT_SCHEMA_VERSION,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Hierarchy estimates from matured observations, gated and shrunk.

    Order matters: GLOBAL first, then MARKET (no parent shrinkage — pool
    is its own prior), then SECTOR×MARKET shrunk toward market, then
    TICKER shrunk toward its market (falling back to global).
    """
    cfg = {**_CHI_PARAMS, **(params or {})}
    matured = [
        {
            "dose": o.get("dose"),
            "z": abs(o["z"]) if isinstance(o.get("z"), (int, float)) else None,
            "event_ts": o.get("event_ts"),
            "ticker": o.get("ticker"),
            "market": o.get("market"),
            "sector": o.get("sector"),
            "horizon": o.get("horizon"),
        }
        for o in observations
        if o.get("maturation") == MATURED and o.get("z") is not None
    ]
    # NOTE: |Z| is used because per-event direction is unavailable — the
    # measured quantity is response MAGNITUDE per evidence dose, matching
    # the primary ABSOLUTE outcome family.  Recorded in docs.
    horizons = sorted({int(m["horizon"]) for m in matured if m.get("horizon") is not None})
    estimates: list[dict[str, Any]] = []
    computed_at = _utc_now_iso()

    for h in horizons:
        rows_h = [m for m in matured if int(m["horizon"]) == h]
        global_est = estimate_scope(
            rows_h, scope_type="GLOBAL", scope_key="GLOBAL", horizon=h,
            params=cfg, min_obs=int(cfg["min_obs_pooled"]),
        )
        global_slope = global_est["slope"] if global_est else None
        if global_est:
            estimates.append(global_est)

        market_slopes: dict[str, float | None] = {}
        for market in sorted({str(m.get("market") or "") for m in rows_h if m.get("market")}):
            rows_m = [m for m in rows_h if m.get("market") == market]
            est = estimate_scope(
                rows_m, scope_type="MARKET", scope_key=market, horizon=h,
                params=cfg, parent_slope=global_slope,
                min_obs=int(cfg["min_obs_pooled"]),
            )
            if est:
                estimates.append(est)
                market_slopes[market] = est["slope"]

        for sector_market in sorted({
            f"{m.get('sector')}|{m.get('market')}"
            for m in rows_h
            if m.get("sector")
        }):
            sector, _, market = sector_market.partition("|")
            rows_s = [
                m for m in rows_h
                if m.get("sector") == sector and m.get("market") == market
            ]
            parent = market_slopes.get(market, global_slope)
            est = estimate_scope(
                rows_s, scope_type="SECTOR", scope_key=sector_market, horizon=h,
                params=cfg, parent_slope=parent,
                min_obs=int(cfg["min_obs_pooled"]),
            )
            if est:
                estimates.append(est)

        for ticker in sorted({str(m.get("ticker") or "") for m in rows_h if m.get("ticker")}):
            rows_t = [m for m in rows_h if m.get("ticker") == ticker]
            market = str(rows_t[0].get("market") or "") if rows_t else ""
            parent = market_slopes.get(market, global_slope)
            est = estimate_scope(
                rows_t, scope_type="TICKER", scope_key=ticker, horizon=h,
                params=cfg, parent_slope=parent,
                min_obs=int(cfg["min_obs_ticker"]),
            )
            if est:
                estimates.append(est)

    for est in estimates:
        est["outcome_def_version"] = outcome_def_version
        est["computed_at"] = computed_at
    return estimates


def run_pipeline(
    *,
    db_path: Path | None = None,
    dry_run: bool = False,
    write_runtime_summary: bool = True,
    runtime_mode: bool = True,
) -> dict[str, Any]:
    """Full pipeline: observations → estimates → persistence → summary."""
    built = build_observations(db_path=db_path, runtime_mode=runtime_mode)
    observations = built["observations"]
    estimates = build_susceptibility_estimates(observations)

    # EXPERIMENTAL measured catalytic convexity (GLOBAL scope, per horizon).
    # Sample-gated and stability-checked inside the estimator; INSUFFICIENT
    # or UNSTABLE results are reported as such, never operationalized.
    matured_for_cc = [
        {
            "dose": o.get("dose"),
            "z": abs(float(o["z"])),
            "event_ts": o.get("event_ts"),
            "horizon": int(o["horizon"]),
        }
        for o in observations
        if o.get("maturation") == MATURED
        and isinstance(o.get("z"), (int, float))
    ]
    convexity_by_horizon: dict[str, Any] = {}
    for h in sorted({m["horizon"] for m in matured_for_cc}):
        rows_h = [m for m in matured_for_cc if m["horizon"] == h]
        convexity_by_horizon[str(h)] = estimate_catalytic_convexity(rows_h, horizon=h)

    matured_count = sum(1 for o in observations if o["maturation"] == MATURED)
    maturation_counts: dict[str, int] = {}
    for o in observations:
        maturation_counts[o["maturation"]] = maturation_counts.get(o["maturation"], 0) + 1
    # Historical state frequencies counted once per evidence event (the
    # per-horizon rows share the same as-of state).
    state_counts: dict[str, int] = {}
    seen_events: set[str] = set()
    for o in observations:
        if o["event_id"] in seen_events:
            continue
        seen_events.add(o["event_id"])
        state_counts[o["titration_state"]] = state_counts.get(o["titration_state"], 0) + 1

    written = {"observations": 0, "estimates": 0, "transitions": 0}
    if not dry_run:
        kwargs: dict[str, Any] = {}
        if db_path is not None:
            kwargs["db_path"] = db_path
        written["observations"] = persistence.replace_titration_observations(
            observations, **kwargs
        )
        written["estimates"] = persistence.replace_titration_susceptibility_estimates(
            estimates, **kwargs
        )
        written["transitions"] = persistence.insert_titration_state_transitions(
            built["transitions"], **kwargs
        )

    summary = {
        "pipeline_version": PIPELINE_VERSION,
        "outcome_contract_version": OUTCOME_CONTRACT_SCHEMA_VERSION,
        "scoring_version": TITRATION_SCORING_VERSION,
        "ticker_count": built["ticker_count"],
        "tickers_with_bars": built["tickers_with_bars"],
        "tickers_without_bars": built["tickers_without_bars"],
        "observation_count": len(observations),
        "matured_observation_count": matured_count,
        "maturation_counts": maturation_counts,
        "estimate_count": len(estimates),
        "estimates_by_scope": {
            scope: sum(1 for e in estimates if e["scope_type"] == scope)
            for scope in ("GLOBAL", "MARKET", "SECTOR", "TICKER")
        },
        "historical_state_counts": state_counts,
        "catalytic_convexity_by_horizon": convexity_by_horizon,
        "transition_count": len(built["transitions"]),
        "dry_run": bool(dry_run),
        "written": written,
        "computed_at": built["computed_at"],
        "note": (
            "Measured susceptibility uses |Z| response magnitude per evidence "
            "dose (direction unavailable). Slopes are robust Theil-Sen, "
            "sample-gated, shrunk toward parent pools; never probabilities."
        ),
        **SAFETY_STAMPS,
    }

    if not dry_run and write_runtime_summary:
        try:
            try:
                from scripts.runtime_common import write_json_atomic
            except ModuleNotFoundError:  # pragma: no cover
                from runtime_common import write_json_atomic  # type: ignore[no-redef]
            repo_root = Path(__file__).resolve().parents[1]
            write_json_atomic(
                repo_root / "runtime" / "titration_response_summary.json", summary
            )
        except Exception:
            pass
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build titration evidence-to-response observations "
                    "(advisory-only record-keeping).",
    )
    parser.add_argument("--db-path", default=None, help="SQLite DB path override.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute without writing tables.")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else None
    summary = run_pipeline(db_path=db_path, dry_run=bool(args.dry_run))
    print(json.dumps(summary, indent=2, default=str))
    return 0


__all__ = [
    "PIPELINE_VERSION",
    "build_observations",
    "build_susceptibility_estimates",
    "run_pipeline",
]


if __name__ == "__main__":
    raise SystemExit(main())
