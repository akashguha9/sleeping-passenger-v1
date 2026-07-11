"""Transition-outcome contract — versioned, leakage-safe forward-response labels.

This module is the formal answer to "what counts as a market transition?"
for the Market Titration layer.  Before it existed, transition readiness
had no falsifiable target.  Every label produced here is:

* **versioned** — the outcome definition (family, thresholds, benchmark)
  is configuration, not code, and each computed row records the
  definition version it was produced under;
* **leakage-safe** — the reference price is the first bar at/after the
  event timestamp; pre-event volatility uses only bars STRICTLY BEFORE
  the entry bar; forward prices are used only as outcomes;
* **maturation-aware** — a horizon that has not elapsed yet is
  NOT_YET_MATURED, never silently dropped or zero-filled;
* **honest about direction** — per-event direction is mostly unavailable
  in this repository, so the PRIMARY outcome family is the absolute
  (unsigned) volatility-scaled response; directional labels are computed
  only when a real direction is supplied and are None otherwise.

Outcome families
----------------
    ABSOLUTE            y = 1[|Z_h| >= z_threshold]
    DIRECTIONAL         y = 1[s * Z_h >= z_threshold]     (needs direction s)
    BENCHMARK_RELATIVE  y = 1[|Z_h - Z_h(benchmark)| >= z_threshold]

with:
    R_h = P_(entry+h) / P_entry - 1          (bar-indexed: h TRADING days)
    Z_h = R_h / max(sigma_pre * sqrt(h), sigma_min)

``sigma_pre`` is the standard deviation of daily simple returns over the
configured lookback window ending strictly before the entry bar.

Horizons are TRADING days by bar-index arithmetic — market holidays and
weekend gaps are handled structurally rather than by calendar guesses.
(The older ``run_imported_backtest.py`` uses calendar-day horizons; this
contract deliberately upgrades to bar-indexed horizons and records that
difference here.)

Maturation states per (observation, horizon):
    MATURED / NOT_YET_MATURED / EXCLUDED / DATA_MISSING / INVALID

Safety: pure module, stdlib only, no execution surface.  Synthetic
fixture bars are EXCLUDED in runtime mode, matching the
``ohlcv_import_contract`` convention.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUTCOME_CONTRACT_SCHEMA_VERSION = "1.0.0"

MATURED = "MATURED"
NOT_YET_MATURED = "NOT_YET_MATURED"
EXCLUDED = "EXCLUDED"
DATA_MISSING = "DATA_MISSING"
INVALID = "INVALID"

MATURATION_STATES: tuple[str, ...] = (
    MATURED, NOT_YET_MATURED, EXCLUDED, DATA_MISSING, INVALID,
)

FAMILY_ABSOLUTE = "ABSOLUTE"
FAMILY_DIRECTIONAL = "DIRECTIONAL"
FAMILY_BENCHMARK_RELATIVE = "BENCHMARK_RELATIVE"

OUTCOME_FAMILIES: tuple[str, ...] = (
    FAMILY_ABSOLUTE, FAMILY_DIRECTIONAL, FAMILY_BENCHMARK_RELATIVE,
)

# Matches scripts/ohlcv_import_contract.SYNTHETIC_FIXTURE without importing
# it eagerly (pure-module hygiene); kept in sync by test.
SYNTHETIC_FIXTURE_SOURCE = "SYNTHETIC_FIXTURE"

DEFAULT_OUTCOME_CONFIG: dict[str, Any] = {
    "config_version": "1.0.0",
    "horizons_trading_days": [1, 3, 5, 10, 20],
    "sigma_pre_lookback_bars": 20,
    "min_pre_history_bars": 10,
    "sigma_min": 1e-4,
    "stale_entry_max_calendar_days": 10,
    "outcome_definitions": {
        "abs_z_1.0": {
            "family": FAMILY_ABSOLUTE,
            "z_threshold": 1.0,
            "version": "1.0.0",
        },
        "dir_z_1.0": {
            "family": FAMILY_DIRECTIONAL,
            "z_threshold": 1.0,
            "version": "1.0.0",
        },
        "bench_rel_z_1.0": {
            "family": FAMILY_BENCHMARK_RELATIVE,
            "z_threshold": 1.0,
            "benchmark": "SPY",
            "version": "1.0.0",
        },
    },
    # Direction is largely unavailable on this repo's evidence path, so the
    # primary falsifiable target is the absolute repricing family.
    "primary_definition": "abs_z_1.0",
}

CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "titration_outcome_config.json"
)


def load_outcome_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load the outcome config, merging the file onto safe defaults.

    Never raises; invalid files degrade to defaults with a recorded
    ``config_status`` so a corrupted config cannot fabricate or destroy
    labels silently.
    """
    cfg = json.loads(json.dumps(DEFAULT_OUTCOME_CONFIG))
    status = "defaults"
    target = Path(path) if path is not None else CONFIG_PATH
    try:
        if target.exists():
            raw = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key in cfg:
                    if key in raw and isinstance(raw[key], type(cfg[key])):
                        cfg[key] = raw[key]
                status = "file_merged"
            else:
                status = "invalid_file_fallback_defaults"
    except (OSError, json.JSONDecodeError, ValueError):
        status = "invalid_file_fallback_defaults"

    # Bounds validation with fallback to defaults per-key.
    problems: list[str] = []
    horizons = cfg.get("horizons_trading_days")
    if (
        not isinstance(horizons, list)
        or not horizons
        or not all(isinstance(h, int) and 1 <= h <= 250 for h in horizons)
    ):
        problems.append("horizons_trading_days:invalid")
        cfg["horizons_trading_days"] = list(DEFAULT_OUTCOME_CONFIG["horizons_trading_days"])
    cfg["horizons_trading_days"] = sorted(set(cfg["horizons_trading_days"]))
    for key, lo, hi in (
        ("sigma_pre_lookback_bars", 5, 250),
        ("min_pre_history_bars", 3, 250),
        ("stale_entry_max_calendar_days", 1, 90),
    ):
        val = cfg.get(key)
        if not isinstance(val, int) or not (lo <= val <= hi):
            problems.append(f"{key}:invalid")
            cfg[key] = DEFAULT_OUTCOME_CONFIG[key]
    sig = cfg.get("sigma_min")
    if not isinstance(sig, (int, float)) or isinstance(sig, bool) or not (
        0 < float(sig) <= 0.1
    ):
        problems.append("sigma_min:invalid")
        cfg["sigma_min"] = DEFAULT_OUTCOME_CONFIG["sigma_min"]
    defs = cfg.get("outcome_definitions")
    if not isinstance(defs, dict) or not defs:
        problems.append("outcome_definitions:invalid")
        cfg["outcome_definitions"] = json.loads(
            json.dumps(DEFAULT_OUTCOME_CONFIG["outcome_definitions"])
        )
    for name, spec in list(cfg["outcome_definitions"].items()):
        if (
            not isinstance(spec, dict)
            or spec.get("family") not in OUTCOME_FAMILIES
            or not isinstance(spec.get("z_threshold"), (int, float))
            or isinstance(spec.get("z_threshold"), bool)
            or not (0.1 <= float(spec["z_threshold"]) <= 10.0)
        ):
            problems.append(f"outcome_definition:{name}:invalid")
            del cfg["outcome_definitions"][name]
    if cfg.get("primary_definition") not in cfg["outcome_definitions"]:
        problems.append("primary_definition:invalid")
        cfg["primary_definition"] = DEFAULT_OUTCOME_CONFIG["primary_definition"]
        if cfg["primary_definition"] not in cfg["outcome_definitions"]:
            cfg["outcome_definitions"] = json.loads(
                json.dumps(DEFAULT_OUTCOME_CONFIG["outcome_definitions"])
            )
    if problems and status == "file_merged":
        status = "file_merged_with_corrections"
    cfg["config_status"] = status
    cfg["config_problems"] = problems
    cfg["schema_version"] = OUTCOME_CONTRACT_SCHEMA_VERSION
    return cfg


# ---------------------------------------------------------------------------
# Bar preparation
# ---------------------------------------------------------------------------


def _parse_date(value: Any) -> str | None:
    """Normalize a bar date to 'YYYY-MM-DD' or None."""
    if isinstance(value, str) and value.strip():
        text = value.strip()[:10]
        try:
            datetime.strptime(text, "%Y-%m-%d")
            return text
        except ValueError:
            return None
    return None


def _bar_price(bar: dict[str, Any]) -> tuple[float | None, str]:
    """Reference price for a bar: adjusted_close when finite, else close.

    Returns (price, field_used).  Corporate-action handling is therefore
    only as good as the imported adjusted series — recorded per row.
    """
    for field in ("adjusted_close", "close"):
        val = bar.get(field)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            f = float(val)
            if math.isfinite(f) and f > 0:
                return f, field
    return None, "none"


def prepare_bars(
    bars: list[dict[str, Any]] | None, *, runtime_mode: bool = True
) -> tuple[list[dict[str, Any]], str | None]:
    """Sort, de-duplicate (by date, last wins) and sanity-filter daily bars.

    Returns (clean_bars, exclusion_reason).  ``exclusion_reason`` is set
    when the whole series must be excluded (synthetic fixture in runtime
    mode).  Bars with unparseable dates or non-positive prices are dropped
    individually.
    """
    if not isinstance(bars, list) or not bars:
        return [], None
    if runtime_mode and any(
        str(b.get("source", "")).upper() == SYNTHETIC_FIXTURE_SOURCE
        for b in bars
        if isinstance(b, dict)
    ):
        return [], "synthetic_fixture_refused_in_runtime"
    by_date: dict[str, dict[str, Any]] = {}
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        date = _parse_date(bar.get("date"))
        if date is None:
            continue
        price, _field = _bar_price(bar)
        if price is None:
            continue
        by_date[date] = bar  # last wins on duplicates
    clean = [dict(by_date[d], date=d) for d in sorted(by_date)]
    return clean, None


def locate_entry_index(
    clean_bars: list[dict[str, Any]],
    event_ts: str,
    *,
    max_stale_calendar_days: int = 10,
) -> tuple[int | None, str | None]:
    """First bar at/after the event date — the leakage-safe reference bar.

    Returns (index, reason_if_none).  Rejects entries where the first
    available bar is more than ``max_stale_calendar_days`` after the event
    (suspension / delisting / dead data)."""
    event_date = _parse_date(event_ts)
    if event_date is None:
        return None, "unparseable_event_timestamp"
    for idx, bar in enumerate(clean_bars):
        if bar["date"] >= event_date:
            gap = (
                datetime.strptime(bar["date"], "%Y-%m-%d")
                - datetime.strptime(event_date, "%Y-%m-%d")
            ).days
            if gap > max_stale_calendar_days:
                return None, "stale_entry_gap"
            return idx, None
    return None, "no_bar_at_or_after_event"


def compute_sigma_pre(
    clean_bars: list[dict[str, Any]],
    entry_idx: int,
    *,
    lookback_bars: int = 20,
    min_pre_history_bars: int = 10,
) -> tuple[float | None, str | None]:
    """Std-dev of daily simple returns STRICTLY BEFORE the entry bar.

    Uses only pre-event information — the leakage boundary is the entry
    bar itself.  Returns (sigma, reason_if_none).
    """
    if entry_idx <= 0:
        return None, "no_pre_event_history"
    window = clean_bars[max(0, entry_idx - lookback_bars - 1):entry_idx]
    prices = []
    for bar in window:
        price, _ = _bar_price(bar)
        if price is not None:
            prices.append(price)
    if len(prices) < min_pre_history_bars + 1:
        return None, "insufficient_pre_event_history"
    rets = [
        prices[i + 1] / prices[i] - 1.0
        for i in range(len(prices) - 1)
        if prices[i] > 0
    ]
    if len(rets) < min_pre_history_bars:
        return None, "insufficient_pre_event_history"
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
    sigma = math.sqrt(max(0.0, var))
    if not math.isfinite(sigma):
        return None, "non_finite_sigma"
    return sigma, None


# ---------------------------------------------------------------------------
# Forward responses
# ---------------------------------------------------------------------------


def _direction_value(direction: Any) -> int | None:
    """Normalize direction to -1/+1, or None when genuinely unavailable.

    UNKNOWN / empty / hostile values map to None — direction is never
    fabricated for legacy events.
    """
    if direction in (1, -1):
        return int(direction)
    if isinstance(direction, str):
        text = direction.strip().upper()
        if text in {"LONG", "BULLISH", "UP", "+1", "1", "POSITIVE"}:
            return 1
        if text in {"SHORT", "BEARISH", "DOWN", "-1", "NEGATIVE"}:
            return -1
    return None


def compute_forward_responses(
    bars: list[dict[str, Any]] | None,
    event_ts: str,
    *,
    direction: Any = None,
    benchmark_bars: list[dict[str, Any]] | None = None,
    config: dict[str, Any] | None = None,
    runtime_mode: bool = True,
) -> dict[str, Any]:
    """Compute versioned forward-response outcomes for one evidence event.

    Returns a payload with per-horizon rows:

        {"horizon": h, "maturation": ..., "r_raw": ..., "z": ...,
         "y_absolute": 0/1/None, "y_directional": 0/1/None,
         "y_benchmark_relative": 0/1/None, "exclusion_reason": ...}

    plus entry metadata (entry_bar_date, reference_price, price_field,
    sigma_pre) and the outcome-definition versions used.  Forward prices
    appear ONLY as outcomes; every feature-usable quantity here
    (sigma_pre, entry price) is observable at or before the entry bar.
    """
    cfg = config if isinstance(config, dict) and "outcome_definitions" in (config or {}) else load_outcome_config()
    horizons = list(cfg["horizons_trading_days"])
    defs = cfg["outcome_definitions"]
    primary = cfg["primary_definition"]

    def _all(maturation: str, reason: str | None) -> dict[str, Any]:
        return {
            "schema_version": OUTCOME_CONTRACT_SCHEMA_VERSION,
            "primary_definition": primary,
            "definitions": {k: dict(v) for k, v in defs.items()},
            "entry_bar_date": None,
            "reference_price": None,
            "price_field": None,
            "sigma_pre": None,
            "direction_used": None,
            "benchmark_used": None,
            "horizons": [
                {
                    "horizon": h,
                    "maturation": maturation,
                    "exclusion_reason": reason,
                    "r_raw": None,
                    "z": None,
                    "mfe": None,
                    "mae": None,
                    "time_to_transition_days": None,
                    "y_absolute": None,
                    "y_directional": None,
                    "y_benchmark_relative": None,
                }
                for h in horizons
            ],
        }

    clean, series_excluded = prepare_bars(bars, runtime_mode=runtime_mode)
    if series_excluded:
        return _all(EXCLUDED, series_excluded)
    if not clean:
        return _all(DATA_MISSING, "no_usable_bars")

    entry_idx, entry_reason = locate_entry_index(
        clean, event_ts,
        max_stale_calendar_days=int(cfg["stale_entry_max_calendar_days"]),
    )
    if entry_idx is None:
        state = INVALID if entry_reason == "unparseable_event_timestamp" else DATA_MISSING
        return _all(state, entry_reason)

    entry_bar = clean[entry_idx]
    ref_price, price_field = _bar_price(entry_bar)
    if ref_price is None:
        return _all(DATA_MISSING, "no_entry_price")

    sigma, sigma_reason = compute_sigma_pre(
        clean, entry_idx,
        lookback_bars=int(cfg["sigma_pre_lookback_bars"]),
        min_pre_history_bars=int(cfg["min_pre_history_bars"]),
    )

    direction_val = _direction_value(direction)

    # Benchmark forward responses (same entry-date alignment, same guards).
    bench_clean: list[dict[str, Any]] = []
    bench_entry_idx: int | None = None
    benchmark_name = None
    for spec in defs.values():
        if spec.get("family") == FAMILY_BENCHMARK_RELATIVE:
            benchmark_name = spec.get("benchmark")
    if benchmark_bars:
        bench_clean, bench_excl = prepare_bars(benchmark_bars, runtime_mode=runtime_mode)
        if not bench_excl and bench_clean:
            bench_entry_idx, _ = locate_entry_index(
                bench_clean, event_ts,
                max_stale_calendar_days=int(cfg["stale_entry_max_calendar_days"]),
            )

    sigma_min = float(cfg["sigma_min"])
    rows: list[dict[str, Any]] = []
    for h in horizons:
        target_idx = entry_idx + h
        if target_idx >= len(clean):
            rows.append({
                "horizon": h,
                "maturation": NOT_YET_MATURED,
                "exclusion_reason": "forward_bar_not_yet_available",
                "r_raw": None, "z": None,
                "mfe": None, "mae": None, "time_to_transition_days": None,
                "y_absolute": None, "y_directional": None,
                "y_benchmark_relative": None,
            })
            continue
        fwd_price, _ = _bar_price(clean[target_idx])
        if fwd_price is None:
            rows.append({
                "horizon": h,
                "maturation": DATA_MISSING,
                "exclusion_reason": "no_forward_price",
                "r_raw": None, "z": None,
                "mfe": None, "mae": None, "time_to_transition_days": None,
                "y_absolute": None, "y_directional": None,
                "y_benchmark_relative": None,
            })
            continue
        r_raw = fwd_price / ref_price - 1.0

        # Path features over (0, h]: maximum favourable / adverse excursion
        # and (when sigma exists) the first trading day the volatility-
        # scaled response crossed the primary threshold.  Forward-path
        # prices are OUTCOME data only.
        mfe: float | None = None
        mae: float | None = None
        ttt: int | None = None
        kappa = float(defs[primary]["z_threshold"])
        path_returns: list[tuple[int, float]] = []
        for tau in range(1, h + 1):
            p_tau, _ = _bar_price(clean[entry_idx + tau])
            if p_tau is None:
                continue
            path_returns.append((tau, p_tau / ref_price - 1.0))
        if path_returns:
            mfe = max(r for _, r in path_returns)
            mae = min(r for _, r in path_returns)
            if sigma is not None:
                for tau, r_tau in path_returns:
                    z_tau = r_tau / max(sigma * math.sqrt(tau), sigma_min)
                    if abs(z_tau) >= kappa:
                        ttt = tau
                        break

        if sigma is None:
            rows.append({
                "horizon": h,
                "maturation": EXCLUDED,
                "exclusion_reason": sigma_reason or "no_sigma_pre",
                "r_raw": round(r_raw, 8), "z": None,
                "mfe": round(mfe, 8) if mfe is not None else None,
                "mae": round(mae, 8) if mae is not None else None,
                "time_to_transition_days": None,
                "y_absolute": None, "y_directional": None,
                "y_benchmark_relative": None,
            })
            continue
        z = r_raw / max(sigma * math.sqrt(h), sigma_min)

        # Benchmark-relative z, when the benchmark matured for this horizon.
        z_rel = None
        if bench_entry_idx is not None and (bench_entry_idx + h) < len(bench_clean):
            b_ref, _ = _bar_price(bench_clean[bench_entry_idx])
            b_fwd, _ = _bar_price(bench_clean[bench_entry_idx + h])
            b_sigma, _ = compute_sigma_pre(
                bench_clean, bench_entry_idx,
                lookback_bars=int(cfg["sigma_pre_lookback_bars"]),
                min_pre_history_bars=int(cfg["min_pre_history_bars"]),
            )
            if b_ref and b_fwd and b_sigma is not None:
                b_r = b_fwd / b_ref - 1.0
                b_z = b_r / max(b_sigma * math.sqrt(h), sigma_min)
                z_rel = z - b_z

        row: dict[str, Any] = {
            "horizon": h,
            "maturation": MATURED,
            "exclusion_reason": None,
            "r_raw": round(r_raw, 8),
            "z": round(z, 6),
            "mfe": round(mfe, 8) if mfe is not None else None,
            "mae": round(mae, 8) if mae is not None else None,
            "time_to_transition_days": ttt,
            "y_absolute": None,
            "y_directional": None,
            "y_benchmark_relative": None,
        }
        for spec in defs.values():
            threshold = float(spec["z_threshold"])
            family = spec["family"]
            if family == FAMILY_ABSOLUTE:
                row["y_absolute"] = 1 if abs(z) >= threshold else 0
            elif family == FAMILY_DIRECTIONAL and direction_val is not None:
                row["y_directional"] = 1 if direction_val * z >= threshold else 0
            elif family == FAMILY_BENCHMARK_RELATIVE and z_rel is not None:
                row["y_benchmark_relative"] = 1 if abs(z_rel) >= threshold else 0
        rows.append(row)

    return {
        "schema_version": OUTCOME_CONTRACT_SCHEMA_VERSION,
        "primary_definition": primary,
        "definitions": {k: dict(v) for k, v in defs.items()},
        "entry_bar_date": entry_bar["date"],
        "reference_price": round(ref_price, 8),
        "price_field": price_field,
        "sigma_pre": round(sigma, 8) if sigma is not None else None,
        "sigma_pre_unavailable_reason": sigma_reason,
        "direction_used": direction_val,
        "benchmark_used": benchmark_name if bench_entry_idx is not None else None,
        "horizons": rows,
    }


__all__ = [
    "OUTCOME_CONTRACT_SCHEMA_VERSION",
    "MATURATION_STATES",
    "MATURED", "NOT_YET_MATURED", "EXCLUDED", "DATA_MISSING", "INVALID",
    "OUTCOME_FAMILIES",
    "FAMILY_ABSOLUTE", "FAMILY_DIRECTIONAL", "FAMILY_BENCHMARK_RELATIVE",
    "DEFAULT_OUTCOME_CONFIG",
    "load_outcome_config",
    "prepare_bars",
    "locate_entry_index",
    "compute_sigma_pre",
    "compute_forward_responses",
]
