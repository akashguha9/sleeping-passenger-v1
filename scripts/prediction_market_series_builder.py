"""Prediction-market longitudinal series builder — no-lookahead features.

Consumes the append-only probability ledger and produces, per market:

    daily series  P_t  (last observation per UTC day — intraday polls and
                        exact duplicates collapse; nothing is rewritten)
    ΔP_t, dP/dt, d²P/dt²   (finite differences on trading-day ordinals)
    Z^P_t                  (standardized vs STRICTLY PRIOR deltas)

and, for cross-venue matched contracts (CES-gated via the existing
semantic pairing + contract-equivalence modules):

    D_t = |P_K − P_P|,  ΔD_t

Rules: features at day d use observations with observed_at date ≤ d only;
markets below the minimum observation count are reported UNDERPOWERED,
never zero-filled.  RESEARCH_ONLY.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.quant_statistics_engine import standardized_shock
from scripts.regime_transition_market_state_engine import (
    divergence_dynamics,
    probability_dynamics,
)

_REPO = Path(__file__).resolve().parents[1]
LEDGER_PATH = _REPO / "data" / "calibration_corpus" / "pm_probability_ledger.jsonl"

OK = "OK"
UNDERPOWERED = "UNDERPOWERED"
MIN_DAILY_OBS = 3   # documented floor: velocity needs 2 pts, accel 3

# Per-contract history-quality bands (distinct observation DAYS — never
# raw observation counts; intraday polls collapse first):
LEVEL_ONLY = "LEVEL_ONLY"                    # 1 day: level only
TWO_POINT_HISTORY = "TWO_POINT_HISTORY"      # 2 days: ΔP + velocity
SHORT_SERIES = "SHORT_SERIES"                # 3–6: acceleration possible
EXPLORATORY_SERIES = "EXPLORATORY_SERIES"    # 7–20: rolling stats begin
RESEARCH_READY = "RESEARCH_READY"            # >=21: standardized inference

# Feature capability per depth (matches the estimators' documented
# minimums: velocity 2 pts, acceleration 3 pts, Z-shock 10 pts —
# standardized_shock needs 8 strictly-prior deltas + the current one).
FEATURE_CAPABILITY_BANDS: tuple[tuple[int, str], ...] = (
    (10, "STANDARDIZED_SHOCK_POSSIBLE"),
    (3, "ACCELERATION_POSSIBLE"),
    (2, "DELTA_AND_VELOCITY_POSSIBLE"),
    (1, "LEVEL_ONLY"),
)


def contract_history_quality(n_distinct_days: int) -> str:
    if n_distinct_days >= 21:
        return RESEARCH_READY
    if n_distinct_days >= 7:
        return EXPLORATORY_SERIES
    if n_distinct_days >= 3:
        return SHORT_SERIES
    if n_distinct_days == 2:
        return TWO_POINT_HISTORY
    return LEVEL_ONLY


def feature_capability(n_distinct_days: int) -> str:
    for floor, label in FEATURE_CAPABILITY_BANDS:
        if n_distinct_days >= floor:
            return label
    return "NO_OBSERVATIONS"


def load_ledger(path: Path = LEDGER_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        venue = r.get("venue") or ("kalshi" if (
            "kalshi" in str(r.get("settled_source", ""))
            or str(r.get("adapter_name", "")).startswith("kalshi")) else None)
        ticker = r.get("market_ticker")
        p = r.get("p")
        ts = str(r.get("observed_at") or r.get("fetch_timestamp") or "")
        if not venue or not ticker or p is None or len(ts) < 10:
            continue
        rows.append({"venue": venue, "market_ticker": ticker,
                     "p": float(p), "date": ts[:10], "observed_at": ts,
                     "title": r.get("title"),
                     "event_ticker": r.get("event_ticker")})
    return rows


def build_daily_series(rows: list[dict[str, Any]],
                       ) -> dict[tuple[str, str], list[tuple[str, float]]]:
    """(venue, market) -> sorted [(date, p_last_of_day)].  Duplicate and
    intraday observations collapse to the LAST of each UTC day."""
    by_key: dict[tuple[str, str], dict[str, tuple[str, float]]] = {}
    for r in rows:
        key = (r["venue"], r["market_ticker"])
        day = r["date"]
        cur = by_key.setdefault(key, {})
        prev = cur.get(day)
        if prev is None or r["observed_at"] > prev[0]:
            cur[day] = (r["observed_at"], r["p"])
    return {key: sorted((d, pv[1]) for d, pv in days.items())
            for key, days in by_key.items()}


def series_features(series: list[tuple[str, float]], *,
                    as_of_date: str | None = None) -> dict[str, Any]:
    """No-lookahead features for one market's daily series.

    ``as_of_date`` truncates the series (features must never see later
    observations); default = full series (i.e. as of the last day).
    """
    pts = [(d, p) for d, p in series if as_of_date is None or d <= as_of_date]
    if len(pts) < MIN_DAILY_OBS:
        return {"status": UNDERPOWERED, "n_days": len(pts),
                "n_min": MIN_DAILY_OBS}
    day_pts = [(_ordinal(d), p) for d, p in pts]
    dyn = probability_dynamics(day_pts)
    z = standardized_shock(day_pts)
    return {"status": OK, "n_days": len(pts),
            "first_date": pts[0][0], "last_date": pts[-1][0],
            "p_latest": pts[-1][1],
            "delta_p_total": round(pts[-1][1] - pts[0][1], 6),
            "velocity": dyn.get("velocity"),
            "acceleration": dyn.get("acceleration"),
            "z_shock": z.get("z") if z.get("status") == "OK" else None,
            "z_status": z.get("status"),
            "lookahead_free": True}


def _ordinal(date_iso: str) -> int:
    from datetime import date
    return date.fromisoformat(date_iso).toordinal()


def matched_pair_divergence(series_a: list[tuple[str, float]],
                            series_b: list[tuple[str, float]], *,
                            ces_verdict: dict[str, Any],
                            ) -> dict[str, Any]:
    """CES-gated cross-venue divergence series.  A blocked CES gate yields
    a blocked result — never a divergence number."""
    from scripts.regime_transition_contract_equivalence_score import (
        divergence_comparison_allowed,
    )
    if not divergence_comparison_allowed(ces_verdict):
        return {"status": "BLOCKED_BY_CES",
                "ces_gate": ces_verdict.get("gate")}
    return divergence_dynamics(
        [(_ordinal(d), p) for d, p in series_a],
        [(_ordinal(d), p) for d, p in series_b])


def ledger_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Observation-depth census for the readiness dashboard.

    Depth is measured in DISTINCT observation days per contract —
    ObservationCount (raw rows), DistinctDayCount (temporal depth) and
    ElapsedCalendarDepth (first→last day span) are reported separately
    and must never be conflated.
    """
    series = build_daily_series(rows)
    depth = {k: len(v) for k, v in series.items()}
    days = sorted({r["date"] for r in rows})
    def _n_at_least(n: int) -> int:
        return sum(1 for c in depth.values() if c >= n)
    depths_sorted = sorted(depth.values())
    median_depth = (depths_sorted[len(depths_sorted) // 2]
                    if depths_sorted else 0)
    capability: dict[str, int] = {}
    per_venue: dict[str, dict[str, int]] = {}
    for (venue, _), c in depth.items():
        capability[feature_capability(c)] = \
            capability.get(feature_capability(c), 0) + 1
        v = per_venue.setdefault(venue, {"contracts": 0, "ge_2_days": 0})
        v["contracts"] += 1
        v["ge_2_days"] += 1 if c >= 2 else 0
    elapsed_days = 0
    if len(days) >= 2:
        from datetime import date
        elapsed_days = (date.fromisoformat(days[-1])
                        - date.fromisoformat(days[0])).days
    return {
        "total_observations": len(rows),
        "distinct_markets": len(series),
        "distinct_days": len(days),
        "first_day": days[0] if days else None,
        "last_day": days[-1] if days else None,
        "elapsed_calendar_days": elapsed_days,
        "markets_ge_2_days": _n_at_least(2),
        "markets_ge_3_days": _n_at_least(3),
        "markets_ge_7_days": _n_at_least(7),
        "markets_ge_14_days": _n_at_least(14),
        "markets_ge_21_days": _n_at_least(21),
        "max_depth_days": depths_sorted[-1] if depths_sorted else 0,
        "median_depth_days": median_depth,
        "feature_capability_counts": capability,
        "per_venue": per_venue,
        "venues": sorted({k[0] for k in series}),
    }
