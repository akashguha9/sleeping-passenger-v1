"""Quant sprint — REAL PEG observation dataset builder + maturation.

Joins three frozen-at-t inputs into genuine (non-fixture) propagation-gap
observations:

    frozen exposure map (hash-chained version at t)
  × probability series ΔP over the trailing window (ledger, ≤ t only)
  × contemporaneous entry price (canonical daily bars)

Each observation is appended (never rewritten) to
``data/calibration_corpus/peg_observations.jsonl`` with
``data_mode="LIVE"`` and matures later: forward abnormal returns at
h ∈ {1,3,5,10,21} trading days are filled by ``mature_observations`` once
bars exist — computed with the existing return engine, never imputed.

Observation key (event_id, ticker, entry_date, map_version) — one frozen
belief per day per link.  Hop / filing_confirmation / chain_position ride
along from the frozen map so the hop-lag and filing-confirmation
experiments (phases 8–9) run from this same dataset.  RESEARCH_ONLY.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.prediction_market_series_builder import (
    build_daily_series,
    load_ledger,
    series_features,
)
from scripts.quant_return_engine import abnormal_return, load_close_series

_REPO = Path(__file__).resolve().parents[1]
PEG_OBS_PATH = _REPO / "data" / "calibration_corpus" / "peg_observations.jsonl"
FROZEN_DIR = _REPO / "data" / "exposure_maps" / "frozen"
DB_PATH = _REPO / "runtime" / "mvp_local.db"

LIVE = "LIVE"
OK = "OK"
NO_DATA = "NO_DATA"
HORIZONS = (1, 3, 5, 10, 21)
DELTA_P_WINDOW_DAYS = 5   # trailing probability move window (documented)
MIN_SERIES_DAYS = 3


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def latest_frozen_map(frozen_dir: Path = FROZEN_DIR) -> dict[str, Any] | None:
    if not frozen_dir.exists():
        return None
    files = sorted(frozen_dir.glob("event_equity_map_v*.json"))
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def _delta_p_for_event(event_id: str,
                       series_by_key: dict[tuple[str, str],
                                           list[tuple[str, float]]],
                       *, as_of_date: str) -> dict[str, Any] | None:
    """Trailing ΔP for the event's market(s), ledger data ≤ as_of only.

    Matches on market_ticker or event_ticker prefix.  Multiple matching
    markets: the one with the deepest series wins (documented choice).
    """
    best: dict[str, Any] | None = None
    for (venue, ticker), series in series_by_key.items():
        if event_id not in (ticker, ticker.split("-")[0]) and \
                not ticker.startswith(event_id):
            continue
        feats = series_features(series, as_of_date=as_of_date)
        if feats["status"] != OK:
            continue
        window = [(d, p) for d, p in series if d <= as_of_date]
        tail = window[-(DELTA_P_WINDOW_DAYS + 1):]
        delta = round(tail[-1][1] - tail[0][1], 6)
        cand = {"venue": venue, "market_ticker": ticker,
                "delta_p": delta, "n_days": feats["n_days"],
                "p_latest": feats["p_latest"],
                "velocity": feats["velocity"], "z_shock": feats["z_shock"]}
        if best is None or cand["n_days"] > best["n_days"]:
            best = cand
    return best


def build_new_observations(*, run_date: str,
                           frozen_map: dict[str, Any] | None = None,
                           ledger_rows: list[dict[str, Any]] | None = None,
                           db_path: Path = DB_PATH,
                           obs_path: Path = PEG_OBS_PATH) -> dict[str, Any]:
    """Create today's frozen PEG observations.  Append-only + dedup by
    (event_id, ticker, entry_date)."""
    frozen = frozen_map if frozen_map is not None else latest_frozen_map()
    if frozen is None:
        return {"status": NO_DATA, "reason": "no frozen exposure map",
                "created": 0}
    series_by_key = build_daily_series(
        ledger_rows if ledger_rows is not None else load_ledger())
    closes = load_close_series(db_path, min_days=1)
    existing = {(r.get("event_id"), r.get("ticker"), r.get("entry_date"))
                for r in _read_jsonl(obs_path)}
    created, skipped_dup, skipped_no_prob, skipped_no_price = 0, 0, 0, 0
    obs_path.parent.mkdir(parents=True, exist_ok=True)
    with obs_path.open("a", encoding="utf-8") as fh:
        for e in frozen.get("entries", []):
            key = (e.get("event_id"), e.get("ticker"), run_date)
            if key in existing:
                skipped_dup += 1
                continue
            prob = _delta_p_for_event(str(e.get("event_id")), series_by_key,
                                      as_of_date=run_date)
            if prob is None:
                skipped_no_prob += 1
                continue
            series = closes.get(str(e.get("ticker")))
            entry_bar = max((d for d in (series or {}) if d <= run_date),
                            default=None)
            if not series or entry_bar is None:
                skipped_no_price += 1
                continue
            row = {
                "data_mode": LIVE,
                "event_id": e.get("event_id"),
                "ticker": e.get("ticker"),
                "entry_date": run_date,
                "entry_bar_date": entry_bar,
                "entry_price": series[entry_bar],
                "map_version": frozen.get("version"),
                "map_content_hash": frozen.get("content_hash"),
                "direction": e.get("direction"),
                "exposure": e.get("exposure"),
                "exposure_confidence": e.get("exposure_confidence"),
                "hop": e.get("hop"),
                "chain_position": e.get("chain_position"),
                "expected_lag_days": e.get("expected_lag_days"),
                "filing_confirmation": e.get("filing_confirmation"),
                "capture_rate": e.get("capture_rate"),
                "narrative_state": e.get("narrative_state"),
                "evidence_ref": e.get("evidence_ref"),
                "prob": prob,
                "ar": {},          # matured later; missing != zero
                "matured_horizons": [],
                "advisory_status": "ADVISORY_ONLY",
                "signal_class": "RESEARCH_ONLY",
            }
            fh.write(json.dumps(row, default=str) + "\n")
            existing.add(key)
            created += 1
    return {"status": OK, "created": created, "skipped_dup": skipped_dup,
            "skipped_no_probability_series": skipped_no_prob,
            "skipped_no_price": skipped_no_price,
            "map_version": frozen.get("version")}


def mature_observations(*, benchmark: str = "SPY",
                        db_path: Path = DB_PATH,
                        obs_path: Path = PEG_OBS_PATH) -> dict[str, Any]:
    """Fill forward abnormal returns for horizons whose bars now exist.

    Rewrites the file ONLY by adding ar values to previously empty
    horizon slots — entry fields and already-matured horizons are never
    modified (verified by test).
    """
    rows = _read_jsonl(obs_path)
    if not rows:
        return {"status": NO_DATA, "matured": 0}
    closes = load_close_series(db_path, min_days=1)
    bench = closes.get(benchmark)
    if not bench:
        return {"status": NO_DATA, "reason": f"no benchmark {benchmark}"}
    matured = 0
    for r in rows:
        series = closes.get(str(r.get("ticker")))
        if not series:
            continue
        entry_bar = r.get("entry_bar_date")
        for h in HORIZONS:
            if str(h) in {str(k) for k in (r.get("ar") or {})}:
                continue
            ar = abnormal_return(series, bench, entry_bar, h)
            if ar["status"] != OK:
                continue    # horizon not yet mature — stays absent
            r.setdefault("ar", {})[str(h)] = round(ar["ar"], 6)
            r.setdefault("matured_horizons", []).append(h)
            matured += 1
    tmp = obs_path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows),
                   encoding="utf-8")
    tmp.replace(obs_path)
    return {"status": OK, "matured": matured, "rows": len(rows)}


def real_peg_census(obs_path: Path = PEG_OBS_PATH) -> dict[str, Any]:
    """Honest N for the readiness dashboard — LIVE rows only."""
    rows = [r for r in _read_jsonl(obs_path) if r.get("data_mode") == LIVE]
    by_h = {h: sum(1 for r in rows if str(h) in
                   {str(k) for k in (r.get("ar") or {})}) for h in HORIZONS}
    hops = {}
    filing = {}
    for r in rows:
        hops[str(r.get("hop"))] = hops.get(str(r.get("hop")), 0) + 1
        fc = str(r.get("filing_confirmation"))
        filing[fc] = filing.get(fc, 0) + 1
    return {"n_live_observations": len(rows),
            "n_matured_by_horizon": by_h,
            "hop_distribution": hops,
            "filing_confirmation_distribution": filing}
