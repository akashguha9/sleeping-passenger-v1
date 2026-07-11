"""Market Titration Engine — pure, deterministic, advisory-only.

Implements the Pre-Alpha / Market Titration framework as an explainable
diagnostic layer over Signal Inbox items.  The doctrine (see
``docs/MARKET_TITRATION_ENGINE.md``) is:

    The final drop is not the signal.  The signal is that the system has
    lost the ability to absorb one more drop.

This module therefore does NOT hunt for visible alpha (price already
moving).  It estimates, from per-event evidence timestamps and source
provenance, how close a candidate is to a state transition:

    per-event half-life decay      a_i(t) = m·q·r · 2^(-(t-t_i)/h_i)
    active evidence                A_t    = saturating sum of a_i(t)
    accumulation vs decay          dA_t   = A_now - A_retained_prev
    evidence-curve geometry        velocity / acceleration of A over
                                   fixed checkpoints -> CONVEX / CONCAVE /
                                   APPROX_LINEAR / FLAT / INSUFFICIENT_DATA
    activation barrier             B_t    = max(0, theta - A_t) / theta
    susceptibility (proxy)         chi_t  = f(acceleration, coherence,
                                             freshness)   [heuristic proxy]
    buffer capacity (proxy)        beta_t = 1 - chi_t     [bounded inverse]
    minimum catalytic dose (proxy) MCD_t  = B_t / (eps + chi_t)
    market temperature             T_t    = sigmoid(weighted inputs)
    Goldilocks quality             G_t    = exp(-(T_t-T*)^2 / 2*sigma^2)
    latent reaction readiness      LRR_t  = sigmoid(weighted components)
    visible market recognition     VMR_t  = breadth/velocity proxy
    pre-alpha gap                  PAG_t  = LRR_t - VMR_t
    false-transition risk          FTR_t  = heat/entropy/persistence risk
    free energy (proxy)            FE_t   = LRR·max(PAG,0)·G·Q - penalties

Honesty contract
----------------
* Every score is a bounded heuristic, NOT a calibrated probability.
  Every payload carries ``score_semantics =
  "heuristic_bounded_score_not_probability"``.
* Proxy estimators are labelled (``estimator`` / ``is_proxy``) and expose
  missing inputs instead of silently substituting zeros.
* ``INSUFFICIENT_DATA`` is a first-class state; sparse inputs degrade the
  payload, they never fabricate readiness.
* Direction / magnitude of individual evidence events is NOT available on
  the inbox path today; active evidence is unsigned readiness mass and is
  documented as such (``directional_evidence_available = False``).
* Susceptibility is NOT the true response derivative dR/dE (that requires
  evidence->price-response observations we do not yet collect); it is a
  labelled heuristic proxy, and the states that depend on true response
  curves (BUFFER_DEPLETING, ENDPOINT_CROSSING, REPRICING) are RESERVED —
  designed but deliberately not operational.

Safety contract (never regress)
-------------------------------
    advisory_status      == "ADVISORY_ONLY"
    execution_gate       == "LOCKED"
    broker_api_called    is False
    ai_execution_count   == 0
    execution_permission is False
    can_execute          is False

Public API
----------
    load_titration_config(path=None)                     -> dict
    evaluate_market_titration(item, now=None, config=None) -> dict
    compact_titration_fields(payload)                    -> dict

Optional CLI
------------
    python scripts/market_titration_engine.py --example --json
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
    "human_review_required": True,
}

TITRATION_SCHEMA_VERSION = "1.0.0"
TITRATION_SCORING_VERSION = "titration_v1"
SCORE_SEMANTICS = "heuristic_bounded_score_not_probability"

# States this engine can actually assign today, in precedence order.
TITRATION_STATES: tuple[str, ...] = (
    "INSUFFICIENT_DATA",
    "FALSE_TRANSITION_RISK",
    "CROWDED",
    "EXHAUSTING",
    "PRIMED",
    "PRE_ALPHA_WATCH",
    "LOADING",
    "NO_EDGE",
    "INERT",
)

# Designed in the state-transition model but NOT operational: they require
# evidence->response observations (true susceptibility) that the current
# data layer does not collect.  Kept here so tests and docs can assert the
# boundary between designed and operational honestly.
RESERVED_STATES: tuple[str, ...] = (
    "BUFFER_DEPLETING",
    "ENDPOINT_CROSSING",
    "REPRICING",
)

GEOMETRY_LABELS: tuple[str, ...] = (
    "CONVEX",
    "CONCAVE",
    "APPROX_LINEAR",
    "FLAT",
    "INSUFFICIENT_DATA",
)

TEMPERATURE_REGIMES: tuple[str, ...] = ("COLD", "WARM", "HOT", "OVERHEATED")

_EPS = 1e-9

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Half-lives (hours) per source family.  Values deliberately aligned with
# scripts/signal_decay_waste.DEFAULT_HALF_LIFE_HOURS so the two decay layers
# never disagree about how fast a source family goes stale.  Source: operator
# priors, NOT fitted from outcomes (config_status records this).
_DEFAULT_HALF_LIVES: dict[str, float] = {
    "official_filing": 168.0,
    "regulatory": 168.0,
    "filing": 168.0,
    "market_price": 24.0,
    "market_data": 24.0,
    "social_hype": 6.0,
    "social": 6.0,
    "news": 48.0,
    "polymarket": 24.0,
    "kalshi": 24.0,
    "prediction_market": 24.0,
    "ai_summary": 12.0,
    "unknown": 24.0,
}

# Evidence quality / reliability priors per source family (0..1).  These are
# operator priors, exposed on every contribution, never presented as learned.
_DEFAULT_SOURCE_PRIORS: dict[str, dict[str, float]] = {
    "official_filing": {"quality": 0.9, "reliability": 0.9},
    "regulatory": {"quality": 0.9, "reliability": 0.9},
    "filing": {"quality": 0.85, "reliability": 0.85},
    "news": {"quality": 0.6, "reliability": 0.6},
    "market_price": {"quality": 0.7, "reliability": 0.8},
    "market_data": {"quality": 0.7, "reliability": 0.8},
    "polymarket": {"quality": 0.65, "reliability": 0.7},
    "kalshi": {"quality": 0.65, "reliability": 0.7},
    "prediction_market": {"quality": 0.65, "reliability": 0.7},
    "social": {"quality": 0.35, "reliability": 0.35},
    "social_hype": {"quality": 0.3, "reliability": 0.3},
    "ai_summary": {"quality": 0.5, "reliability": 0.5},
    "unknown": {"quality": 0.4, "reliability": 0.4},
}

DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": "1.0.0",
    "half_life_hours_by_family": dict(_DEFAULT_HALF_LIVES),
    "source_priors": {k: dict(v) for k, v in _DEFAULT_SOURCE_PRIORS.items()},
    # Saturation mass: A_norm = A_raw / (A_raw + k).  k=3 means ~3 units of
    # fully-fresh high-quality evidence puts A_norm at 0.5.
    "evidence_saturation_mass": 3.0,
    # Evidence-series checkpoints for geometry/flow estimation.
    "series_checkpoint_hours": 6.0,
    "series_checkpoint_count": 5,
    "fresh_inflow_window_hours": 24.0,
    # Minimum observations before geometry / flow claims are made.
    "min_events_for_state": 1,
    "min_events_for_geometry": 3,
    "min_events_for_loading": 2,
    "geometry_flat_velocity_eps": 0.005,
    "geometry_accel_eps": 0.004,
    "loading_net_accumulation_eps": 0.01,
    # Activation threshold on normalized active evidence.
    "activation_threshold": 0.55,
    # Temperature model: weighted [0,1] inputs -> sigmoid.  Anchors (see
    # docs): no activity/no noise -> ~0.10 (COLD); reference-velocity clean
    # flow -> ~0.50 (WARM); dense burst -> ~0.77 (HOT); dense noisy burst
    # -> ~0.92 (OVERHEATED).
    "temperature_weights": {
        "event_velocity": 3.2,
        "chaos_sensitivity": 1.4,
        "contamination": 1.0,
    },
    "temperature_bias": -2.2,
    # Reference event velocity (events/day); at this rate the velocity
    # input is 0.5 (saturating per_day / (per_day + reference)).
    "reference_events_per_day": 2.0,
    "temperature_cold_max": 0.25,
    "temperature_warm_max": 0.55,
    "temperature_hot_max": 0.80,
    "goldilocks_center": 0.55,
    "goldilocks_width": 0.18,
    # Latent Reaction Readiness weights (heuristic priors, uncalibrated).
    "lrr_weights": {
        "active_evidence": 2.2,
        "coherence": 1.2,
        "susceptibility": 1.0,
        "persistence": 1.0,
        "barrier_openness": 1.2,
        "goldilocks": 0.8,
        "concentration_penalty": -0.9,
        "ftr_penalty": -1.4,
    },
    "lrr_bias": -2.6,
    # Visible Market Recognition proxy weights.
    "vmr_weights": {
        "source_breadth": 0.55,
        "event_velocity": 0.45,
    },
    "vmr_breadth_saturation": 4.0,
    # False-transition risk weights.
    "ftr_weights": {
        "overheat": 0.30,
        "single_source": 0.20,
        "low_persistence": 0.20,
        "contamination": 0.20,
        "low_sufficiency": 0.10,
    },
    "ftr_gate": 0.60,
    # State thresholds.
    "primed_lrr_min": 0.65,
    "primed_pag_min": 0.15,
    "primed_barrier_max": 0.45,
    "primed_goldilocks_min": 0.50,
    "watch_lrr_min": 0.45,
    "watch_pag_min": 0.05,
    "crowded_vmr_min": 0.65,
    "crowded_pag_max": 0.05,
    "exhausting_vmr_min": 0.40,
    "inert_evidence_floor": 0.10,
    # Free-energy proxy penalties (operator priors; no live friction feed).
    "friction_prior": 0.05,
    "uncertainty_penalty_weight": 0.15,
    "mcd_cap": 25.0,
    "epsilon": 1e-6,
}

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "market_titration_config.json"

_NUMERIC_BOUNDS: dict[str, tuple[float, float]] = {
    "evidence_saturation_mass": (0.1, 100.0),
    "series_checkpoint_hours": (0.5, 168.0),
    "fresh_inflow_window_hours": (1.0, 720.0),
    "activation_threshold": (0.05, 0.95),
    "goldilocks_center": (0.05, 0.95),
    "goldilocks_width": (0.01, 1.0),
    "ftr_gate": (0.05, 0.99),
    "friction_prior": (0.0, 1.0),
    "mcd_cap": (1.0, 1e6),
    "epsilon": (1e-12, 1e-2),
}


def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if key not in base:
            continue  # unknown keys ignored, recorded by caller
        if isinstance(base[key], dict) and isinstance(value, dict):
            merged = dict(base[key])
            for sub_k, sub_v in value.items():
                if isinstance(sub_v, (int, float)) and not isinstance(sub_v, bool):
                    merged[sub_k] = float(sub_v)
                elif isinstance(sub_v, dict):
                    merged[sub_k] = sub_v
            out[key] = merged
        elif isinstance(base[key], (int, float)) and not isinstance(base[key], bool):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                fval = float(value)
                if math.isfinite(fval):
                    out[key] = fval
        elif isinstance(value, type(base[key])):
            out[key] = value
    return out


def _validate_numeric_bounds(cfg: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for key, (lo, hi) in _NUMERIC_BOUNDS.items():
        val = cfg.get(key)
        if not isinstance(val, (int, float)) or isinstance(val, bool) or not math.isfinite(float(val)):
            problems.append(f"{key}:not_finite")
            cfg[key] = DEFAULT_CONFIG[key]
        elif not (lo <= float(val) <= hi):
            problems.append(f"{key}:out_of_range")
            cfg[key] = DEFAULT_CONFIG[key]
    count = cfg.get("series_checkpoint_count")
    if not isinstance(count, (int, float)) or isinstance(count, bool) or not (2 <= int(count) <= 24):
        problems.append("series_checkpoint_count:out_of_range")
        cfg["series_checkpoint_count"] = DEFAULT_CONFIG["series_checkpoint_count"]
    else:
        cfg["series_checkpoint_count"] = int(count)
    for family, hours in list(cfg.get("half_life_hours_by_family", {}).items()):
        if (
            not isinstance(hours, (int, float))
            or isinstance(hours, bool)
            or not math.isfinite(float(hours))
            or float(hours) <= 0.0
        ):
            problems.append(f"half_life:{family}:invalid")
            cfg["half_life_hours_by_family"][family] = _DEFAULT_HALF_LIVES.get(
                family, _DEFAULT_HALF_LIVES["unknown"]
            )
    return problems


def load_titration_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load the titration config, merging file overrides onto safe defaults.

    Never raises: an unreadable or invalid file degrades to defaults and the
    result records ``config_status`` so the operator can see what happened.
    ``half_life_source`` is always "configured_prior" — half-lives are NOT
    fitted from outcome data yet and the payload must never imply they are.
    """
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy, JSON-safe
    status = "defaults"
    problems: list[str] = []
    target = Path(path) if path is not None else CONFIG_PATH
    try:
        if target.exists():
            raw = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg = _merge_config(cfg, raw)
                status = "file_merged"
            else:
                status = "invalid_file_fallback_defaults"
    except (OSError, json.JSONDecodeError, ValueError):
        status = "invalid_file_fallback_defaults"
    problems = _validate_numeric_bounds(cfg)
    if problems and status == "file_merged":
        status = "file_merged_with_corrections"
    cfg["config_status"] = status
    cfg["config_problems"] = problems
    cfg["half_life_source"] = "configured_prior"
    return cfg


# ---------------------------------------------------------------------------
# Small numeric helpers
# ---------------------------------------------------------------------------


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return lo
    if not math.isfinite(x):
        return lo
    return min(hi, max(lo, x))


def _finite_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-min(x, 60.0)))
    e = math.exp(max(x, -60.0))
    return e / (1.0 + e)


def _parse_iso(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    text = ts.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def decay_factor(age_hours: float, half_life_hours: float) -> float | None:
    """Half-life decay 2^(-age/h).  Returns None on invalid inputs.

    Future-dated observations (negative age) are clamped to age 0 — the
    caller flags them; they never produce factors above 1.0.
    """
    age = _finite_or_none(age_hours)
    half = _finite_or_none(half_life_hours)
    if age is None or half is None or half <= 0.0:
        return None
    age = max(0.0, age)
    exponent = -age / half
    if exponent < -60.0:
        return 0.0
    return 2.0 ** exponent


def _source_family(source_name: str, cfg: dict[str, Any]) -> str:
    name = (source_name or "").strip().lower()
    families = cfg["half_life_hours_by_family"]
    if name in families:
        return name
    for family in families:
        if family != "unknown" and family in name:
            return family
    return "unknown"


# ---------------------------------------------------------------------------
# Evidence extraction and decay
# ---------------------------------------------------------------------------


def _extract_events(item: dict[str, Any], now: datetime) -> tuple[list[dict[str, Any]], list[str]]:
    """Normalize per-event (timestamp, source) pairs from an inbox item.

    Prefers the bridge-provided ``event_timestamps`` / ``event_sources``
    lists.  Falls back to the single representative ``observed_at`` so
    pre-existing payload shapes degrade to a one-event, low-sufficiency
    evaluation rather than crashing.  Returns (events, quality_notes).
    """
    notes: list[str] = []
    timestamps = item.get("event_timestamps")
    sources = item.get("event_sources")
    events: list[dict[str, Any]] = []

    if isinstance(timestamps, list) and timestamps:
        src_list = sources if isinstance(sources, list) else []
        for idx, ts in enumerate(timestamps):
            dt = _parse_iso(ts)
            if dt is None:
                notes.append("unparseable_timestamp_dropped")
                continue
            if dt > now + timedelta(minutes=5):
                notes.append("future_timestamp_clamped")
                dt = now
            source = str(src_list[idx]) if idx < len(src_list) else str(item.get("source_name", "") or "")
            events.append({"observed_at": dt, "source_name": source})
    else:
        dt = _parse_iso(item.get("observed_at") or item.get("last_observed_at"))
        if dt is not None:
            notes.append("degraded_single_representative_event")
            events.append({
                "observed_at": min(dt, now),
                "source_name": str(item.get("source_name", "") or ""),
            })

    # Deterministic order; duplicate timestamps allowed (multiple events can
    # genuinely land in the same fetch second) but recorded.
    events.sort(key=lambda e: e["observed_at"])
    seen: set[tuple[str, str]] = set()
    for e in events:
        key = (e["observed_at"].isoformat(), e["source_name"])
        if key in seen:
            notes.append("duplicate_event_timestamp")
        seen.add(key)
    return events, notes


def _event_mass_at(event: dict[str, Any], at: datetime, cfg: dict[str, Any]) -> float:
    """Decayed unit-evidence mass of one event at time ``at``.

    Magnitude/direction per event are unavailable on this path, so mass is
    unit (m=1) scaled by configured family quality+reliability priors — an
    unsigned readiness mass, not a directional conviction score.
    """
    family = _source_family(event["source_name"], cfg)
    half = float(cfg["half_life_hours_by_family"].get(family, _DEFAULT_HALF_LIVES["unknown"]))
    priors = cfg["source_priors"].get(family, _DEFAULT_SOURCE_PRIORS["unknown"])
    age_hours = (at - event["observed_at"]).total_seconds() / 3600.0
    if age_hours < 0.0:
        return 0.0  # event does not exist yet at this checkpoint
    factor = decay_factor(age_hours, half)
    if factor is None:
        return 0.0
    return _clamp(priors.get("quality", 0.4)) * _clamp(priors.get("reliability", 0.4)) * factor


def _normalize_mass(raw: float, cfg: dict[str, Any]) -> float:
    k = float(cfg["evidence_saturation_mass"])
    raw = max(0.0, raw)
    return raw / (raw + k)


def compute_active_evidence(
    events: list[dict[str, Any]], now: datetime, cfg: dict[str, Any]
) -> dict[str, Any]:
    """Time-decayed active evidence with per-source decomposition."""
    per_source: dict[str, float] = {}
    contributions: list[dict[str, Any]] = []
    raw = 0.0
    for event in events:
        mass = _event_mass_at(event, now, cfg)
        family = _source_family(event["source_name"], cfg)
        per_source[family] = per_source.get(family, 0.0) + mass
        raw += mass
        if len(contributions) < 50:
            age_hours = (now - event["observed_at"]).total_seconds() / 3600.0
            half = float(cfg["half_life_hours_by_family"].get(family, _DEFAULT_HALF_LIVES["unknown"]))
            contributions.append({
                "source_family": family,
                "age_hours": round(max(0.0, age_hours), 2),
                "half_life_hours": half,
                "half_life_source": cfg.get("half_life_source", "configured_prior"),
                "decayed_mass": round(mass, 6),
                "remaining_activity_ratio": round(
                    (decay_factor(age_hours, half) or 0.0), 6
                ),
            })
    return {
        "raw_mass": round(raw, 6),
        "normalized": round(_normalize_mass(raw, cfg), 6),
        "per_source_mass": {k: round(v, 6) for k, v in sorted(per_source.items())},
        "contributions": contributions,
        "event_count_used": len(events),
        "unit_mass_assumption": True,
        "directional_evidence_available": False,
    }


def compute_evidence_series(
    events: list[dict[str, Any]], now: datetime, cfg: dict[str, Any]
) -> list[float]:
    """Normalized active evidence at K fixed checkpoints ending at ``now``.

    Checkpoint j (j = K-1 .. 0) is evaluated at now - j*delta, counting only
    events already observed by that checkpoint.  Deterministic given
    (events, now, config); oldest first.
    """
    delta = float(cfg["series_checkpoint_hours"])
    count = int(cfg["series_checkpoint_count"])
    series: list[float] = []
    for j in range(count - 1, -1, -1):
        at = now - timedelta(hours=delta * j)
        raw = sum(_event_mass_at(e, at, cfg) for e in events)
        series.append(round(_normalize_mass(raw, cfg), 6))
    return series


def classify_geometry(
    series: list[float], event_count: int, cfg: dict[str, Any]
) -> dict[str, Any]:
    """Classify the evidence-accumulation curve.

    Velocity = mean first difference, acceleration = mean second difference
    over the checkpoint series.  Labels only claimed with enough events;
    otherwise INSUFFICIENT_DATA — a series is never forced into a shape.
    """
    min_events = int(cfg["min_events_for_geometry"])
    if event_count < min_events or len(series) < 3:
        return {
            "label": "INSUFFICIENT_DATA",
            "velocity": None,
            "acceleration": None,
            "checkpoints": series,
            "min_events_required": min_events,
        }
    diffs = [series[i + 1] - series[i] for i in range(len(series) - 1)]
    accels = [diffs[i + 1] - diffs[i] for i in range(len(diffs) - 1)]
    velocity = sum(diffs) / len(diffs)
    acceleration = sum(accels) / len(accels)
    v_eps = float(cfg["geometry_flat_velocity_eps"])
    a_eps = float(cfg["geometry_accel_eps"])
    if abs(velocity) <= v_eps and abs(acceleration) <= a_eps:
        label = "FLAT"
    elif acceleration > a_eps:
        label = "CONVEX"
    elif acceleration < -a_eps:
        label = "CONCAVE"
    else:
        label = "APPROX_LINEAR"
    return {
        "label": label,
        "velocity": round(velocity, 6),
        "acceleration": round(acceleration, 6),
        "checkpoints": series,
        "min_events_required": min_events,
    }


def compute_flow(
    events: list[dict[str, Any]], now: datetime, cfg: dict[str, Any]
) -> dict[str, Any]:
    """Fresh inflow vs decay outflow, separated per the doctrine.

    inflow_fresh   — decayed mass (now) of events inside the fresh window.
    prev_active    — normalized active evidence one checkpoint step ago.
    retained_prev  — mass now of only the events that existed a step ago.
    decay_outflow  — how much of the previous stock evaporated.
    net_accumulation — A_now - A_prev on the normalized scale.
    """
    delta = float(cfg["series_checkpoint_hours"])
    fresh_window = float(cfg["fresh_inflow_window_hours"])
    prev_at = now - timedelta(hours=delta)

    raw_now = sum(_event_mass_at(e, now, cfg) for e in events)
    prev_events = [e for e in events if e["observed_at"] <= prev_at]
    raw_prev = sum(_event_mass_at(e, prev_at, cfg) for e in prev_events)
    raw_retained = sum(_event_mass_at(e, now, cfg) for e in prev_events)

    inflow_fresh = sum(
        _event_mass_at(e, now, cfg)
        for e in events
        if (now - e["observed_at"]).total_seconds() / 3600.0 <= fresh_window
    )

    a_now = _normalize_mass(raw_now, cfg)
    a_prev = _normalize_mass(raw_prev, cfg)
    net = a_now - a_prev
    return {
        "active_now": round(a_now, 6),
        "active_prev_step": round(a_prev, 6),
        "net_accumulation": round(net, 6),
        "inflow_fresh_mass": round(inflow_fresh, 6),
        "decay_outflow_mass": round(max(0.0, raw_prev - raw_retained), 6),
        "loading": bool(net > float(cfg["loading_net_accumulation_eps"])),
        "step_hours": delta,
        "fresh_window_hours": fresh_window,
    }


# ---------------------------------------------------------------------------
# Coherence, concentration, temperature
# ---------------------------------------------------------------------------


def compute_coherence(
    item: dict[str, Any], per_source_mass: dict[str, float], cfg: dict[str, Any]
) -> dict[str, Any]:
    """Structural coherence proxy: diversity minus duplication/contamination.

    Directional agreement between events is NOT observable on this path, so
    this is a structure-only proxy (``is_proxy=True``) — it measures whether
    the evidence base is diversified and clean, not whether sources agree on
    direction.
    """
    distinct = len([k for k, v in per_source_mass.items() if v > 0.0])
    event_count = max(1, int(_finite_or_none(item.get("event_count")) or 1))
    dup = _clamp((_finite_or_none(item.get("duplicate_suppressed_count")) or 0.0) / event_count)
    contamination = _finite_or_none(item.get("contamination_score"))
    diversity = _clamp((distinct - 1) / 3.0)
    score = _clamp(0.45 + 0.45 * diversity - 0.25 * dup - 0.35 * (contamination or 0.0))
    return {
        "score": round(score, 6),
        "estimator": "structural_proxy_v1",
        "is_proxy": True,
        "distinct_source_families": distinct,
        "duplication_ratio": round(dup, 6),
        "contamination_score": contamination,
        "directional_agreement_available": False,
    }


def compute_source_concentration(per_source_mass: dict[str, float]) -> dict[str, Any]:
    """Shannon entropy of decayed mass across source families.

    Normalized entropy near 1 = mass spread across families (diversified);
    near 0 = concentrated.  ``concentration = 1 - normalized_entropy`` feeds
    the false-transition penalty.  This is source-structure entropy — NOT
    directional disagreement (which needs signed evidence we don't have).
    """
    masses = [v for v in per_source_mass.values() if v > 0.0]
    if not masses:
        return {
            "normalized_entropy": None,
            "concentration": None,
            "single_source_dependence": True,
            "source_family_count": 0,
            "estimator": "source_mass_entropy_v1",
        }
    if len(masses) == 1:
        return {
            "normalized_entropy": 0.0,
            "concentration": 1.0,
            "single_source_dependence": True,
            "source_family_count": 1,
            "estimator": "source_mass_entropy_v1",
        }
    total = sum(masses)
    shares = [m / total for m in masses]
    entropy = -sum(p * math.log(p) for p in shares if p > 0.0)
    normalized = entropy / math.log(len(masses))
    return {
        "normalized_entropy": round(_clamp(normalized), 6),
        "concentration": round(_clamp(1.0 - normalized), 6),
        "single_source_dependence": False,
        "source_family_count": len(masses),
        "estimator": "source_mass_entropy_v1",
    }


def compute_temperature(
    item: dict[str, Any],
    events: list[dict[str, Any]],
    now: datetime,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Explainable market-temperature score with regime + Goldilocks quality.

    Inputs actually available on the inbox path: event-arrival velocity,
    chaos-sensitivity diagnostic, contamination.  Classic temperature inputs
    (implied vol, cross-asset correlation, liquidity stress, macro stress)
    are NOT available and are listed in ``inputs_missing`` rather than
    silently zero-filled.
    """
    weights = cfg["temperature_weights"]
    available: dict[str, float] = {}
    missing: list[str] = []

    window_h = 48.0
    recent = [e for e in events if (now - e["observed_at"]).total_seconds() / 3600.0 <= window_h]
    if events:
        per_day = len(recent) * 24.0 / window_h
        ref = max(_EPS, float(cfg["reference_events_per_day"]))
        available["event_velocity"] = _clamp(per_day / (per_day + ref))
    else:
        missing.append("event_velocity")

    chaos = _finite_or_none(item.get("chaos_sensitivity_score"))
    if chaos is not None:
        available["chaos_sensitivity"] = _clamp(chaos)
    else:
        missing.append("chaos_sensitivity")

    contamination = _finite_or_none(item.get("contamination_score"))
    if contamination is not None:
        available["contamination"] = _clamp(contamination)
    else:
        missing.append("contamination")

    missing.extend([
        "implied_volatility", "cross_asset_correlation",
        "liquidity_stress", "macro_stress",
    ])

    if not available:
        return {
            "temperature": None,
            "regime": "INSUFFICIENT_DATA",
            "goldilocks_quality": None,
            "inputs_available": {},
            "inputs_missing": missing,
            "estimator": "sigmoid_weighted_v1",
        }

    z = float(cfg["temperature_bias"]) + sum(
        float(weights.get(name, 0.0)) * value for name, value in available.items()
    )
    temp = _sigmoid(z)
    if temp <= float(cfg["temperature_cold_max"]):
        regime = "COLD"
    elif temp <= float(cfg["temperature_warm_max"]):
        regime = "WARM"
    elif temp <= float(cfg["temperature_hot_max"]):
        regime = "HOT"
    else:
        regime = "OVERHEATED"
    center = float(cfg["goldilocks_center"])
    width = max(1e-3, float(cfg["goldilocks_width"]))
    goldilocks = math.exp(-((temp - center) ** 2) / (2.0 * width * width))
    return {
        "temperature": round(temp, 6),
        "regime": regime,
        "goldilocks_quality": round(_clamp(goldilocks), 6),
        "inputs_available": {k: round(v, 6) for k, v in sorted(available.items())},
        "inputs_missing": missing,
        "estimator": "sigmoid_weighted_v1",
    }


# ---------------------------------------------------------------------------
# Titration core: barrier, susceptibility, buffer, MCD
# ---------------------------------------------------------------------------


def compute_barrier(active_norm: float, cfg: dict[str, Any]) -> dict[str, Any]:
    theta = float(cfg["activation_threshold"])
    barrier = max(0.0, theta - _clamp(active_norm)) / max(theta, _EPS)
    return {
        "barrier": round(_clamp(barrier), 6),
        "activation_threshold": theta,
        "threshold_source": "configured_prior",
        "crossed": bool(active_norm >= theta),
    }


def compute_susceptibility(
    geometry: dict[str, Any],
    coherence_score: float,
    events: list[dict[str, Any]],
    now: datetime,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Susceptibility PROXY — labelled, never presented as the true dR/dE.

    True susceptibility is the derivative of market response with respect to
    evidence, which requires evidence->price-response pairs the platform
    does not collect yet.  Until then: a bounded heuristic combining
    evidence-curve acceleration (loading systems get more reactive),
    structural coherence, and freshness.  ``insufficient_data`` when the
    geometry layer could not establish a curve.
    """
    if geometry.get("label") == "INSUFFICIENT_DATA":
        return {
            "susceptibility": None,
            "estimator": "heuristic_proxy_v1",
            "is_proxy": True,
            "sufficient": False,
            "components": {},
        }
    accel = _finite_or_none(geometry.get("acceleration")) or 0.0
    accel_pos = _clamp(accel / max(float(cfg["geometry_accel_eps"]) * 4.0, _EPS))
    freshest_age = min(
        ((now - e["observed_at"]).total_seconds() / 3600.0 for e in events),
        default=None,
    )
    freshness = _clamp(1.0 - (freshest_age / 72.0)) if freshest_age is not None else 0.0
    chi = _clamp(0.5 * accel_pos + 0.3 * _clamp(coherence_score) + 0.2 * freshness)
    return {
        "susceptibility": round(chi, 6),
        "estimator": "heuristic_proxy_v1",
        "is_proxy": True,
        "sufficient": True,
        "components": {
            "acceleration_positive": round(accel_pos, 6),
            "coherence": round(_clamp(coherence_score), 6),
            "freshness": round(freshness, 6),
        },
    }


def compute_buffer_capacity(chi: float | None) -> dict[str, Any]:
    """Buffer capacity as bounded inverse of susceptibility.

    Conceptual form is beta ∝ 1/chi; we use beta = 1 - chi so the output
    stays on [0,1] without singularities.  Monotone-inverse is preserved;
    the deviation from the literal reciprocal is documented here and in the
    docs.  Inherits proxy status from susceptibility.
    """
    if chi is None:
        return {"buffer_capacity": None, "estimator": "bounded_inverse_proxy_v1", "is_proxy": True}
    return {
        "buffer_capacity": round(_clamp(1.0 - chi), 6),
        "estimator": "bounded_inverse_proxy_v1",
        "is_proxy": True,
    }


def compute_minimum_catalytic_dose(
    barrier: float, chi: float | None, cfg: dict[str, Any]
) -> dict[str, Any]:
    """MCD = barrier / (eps + susceptibility), bounded and normalized.

    Interpreted as "standardized additional coherent evidence required to
    cross the activation threshold".  Proxy: inherits susceptibility's
    proxy status; capped to avoid runaway values when chi -> 0.
    """
    if chi is None:
        return {
            "mcd_raw": None, "mcd_normalized": None,
            "estimator": "barrier_over_susceptibility_v1", "is_proxy": True,
        }
    eps = float(cfg["epsilon"])
    cap = float(cfg["mcd_cap"])
    raw = min(cap, max(0.0, barrier) / (eps + max(0.0, chi)))
    return {
        "mcd_raw": round(raw, 6),
        "mcd_normalized": round(raw / (raw + 1.0), 6),
        "estimator": "barrier_over_susceptibility_v1",
        "is_proxy": True,
    }


# ---------------------------------------------------------------------------
# Readiness, recognition, gap, risk, free energy
# ---------------------------------------------------------------------------


def compute_vmr(
    item: dict[str, Any],
    events: list[dict[str, Any]],
    now: datetime,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Visible Market Recognition PROXY from reporting breadth + velocity.

    Available recognition inputs today: how many independent source families
    are reporting (breadth) and how fast events are arriving (velocity —
    media-velocity analog).  Price extension, valuation repricing, analyst /
    social attention and options crowding are NOT available; they are listed
    in ``inputs_missing``.  LOW recognition with missing inputs is therefore
    a LOW-CONFIDENCE claim, and the confidence field says so.
    """
    weights = cfg["vmr_weights"]
    missing = [
        "price_extension", "valuation_repricing", "analyst_attention",
        "media_velocity_external", "social_attention", "options_crowding",
    ]
    if not events:
        return {
            "vmr": None,
            "estimator": "breadth_velocity_proxy_v1",
            "is_proxy": True,
            "confidence": "none",
            "inputs_missing": missing + ["event_velocity", "source_breadth"],
        }
    breadth_raw = _finite_or_none(item.get("cross_source_support_count")) or 0.0
    distinct_sources = len({_source_family(e["source_name"], cfg) for e in events})
    breadth = _clamp(max(breadth_raw, float(distinct_sources)) / max(float(cfg["vmr_breadth_saturation"]), 1.0))
    window_h = 48.0
    recent = [e for e in events if (now - e["observed_at"]).total_seconds() / 3600.0 <= window_h]
    per_day = len(recent) * 24.0 / window_h
    ref = max(_EPS, float(cfg["reference_events_per_day"]))
    velocity = _clamp(per_day / (per_day + ref))
    vmr = _clamp(
        float(weights.get("source_breadth", 0.5)) * breadth
        + float(weights.get("event_velocity", 0.5)) * velocity
    )
    return {
        "vmr": round(vmr, 6),
        "estimator": "breadth_velocity_proxy_v1",
        "is_proxy": True,
        "confidence": "low",
        "components": {
            "source_breadth": round(breadth, 6),
            "event_velocity": round(velocity, 6),
        },
        "inputs_missing": missing,
    }


def compute_ftr(
    temperature: dict[str, Any],
    concentration: dict[str, Any],
    item: dict[str, Any],
    coherence: dict[str, Any],
    sufficiency_score: float,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """False-transition risk with explicit reasons, not just a number."""
    weights = cfg["ftr_weights"]
    reasons: list[str] = []
    temp = _finite_or_none(temperature.get("temperature"))
    hot_max = float(cfg["temperature_hot_max"])
    overheat = 0.0
    if temp is not None and temp > hot_max:
        overheat = _clamp((temp - hot_max) / max(1.0 - hot_max, _EPS))
        reasons.append("temperature_overheated")
    single = 1.0 if concentration.get("single_source_dependence") else 0.0
    if single:
        reasons.append("single_source_dependence")
    persistence = _clamp(_finite_or_none(item.get("persistence_score")) or 0.0)
    low_persistence = 1.0 - persistence
    if low_persistence >= 0.7:
        reasons.append("low_persistence")
    contamination = _clamp(_finite_or_none(item.get("contamination_score")) or 0.0)
    if contamination >= 0.5:
        reasons.append("contamination_elevated")
    low_sufficiency = _clamp(1.0 - sufficiency_score)
    if low_sufficiency >= 0.7:
        reasons.append("low_data_sufficiency")
    score = _clamp(
        float(weights.get("overheat", 0.3)) * overheat
        + float(weights.get("single_source", 0.2)) * single
        + float(weights.get("low_persistence", 0.2)) * low_persistence
        + float(weights.get("contamination", 0.2)) * contamination
        + float(weights.get("low_sufficiency", 0.1)) * low_sufficiency
    )
    return {
        "ftr": round(score, 6),
        "gate": float(cfg["ftr_gate"]),
        "triggered": bool(score >= float(cfg["ftr_gate"])),
        "reasons": reasons,
        "components": {
            "overheat": round(overheat, 6),
            "single_source": single,
            "low_persistence": round(low_persistence, 6),
            "contamination": round(contamination, 6),
            "low_sufficiency": round(low_sufficiency, 6),
        },
    }


def compute_lrr(
    active_norm: float,
    coherence: dict[str, Any],
    susceptibility: dict[str, Any],
    barrier: dict[str, Any],
    temperature: dict[str, Any],
    concentration: dict[str, Any],
    ftr: dict[str, Any],
    item: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Latent Reaction Readiness — bounded sigmoid composite, NOT a probability.

    Weights are configurable operator priors (uncalibrated).  Every
    component contribution is exposed so the operator can see exactly why
    readiness is high or low.
    """
    w = cfg["lrr_weights"]
    chi = _finite_or_none(susceptibility.get("susceptibility")) or 0.0
    goldilocks = _finite_or_none(temperature.get("goldilocks_quality"))
    concentration_val = _finite_or_none(concentration.get("concentration")) or 0.0
    persistence = _clamp(_finite_or_none(item.get("persistence_score")) or 0.0)
    components = {
        "active_evidence": float(w["active_evidence"]) * _clamp(active_norm),
        "coherence": float(w["coherence"]) * _clamp(coherence.get("score", 0.0)),
        "susceptibility": float(w["susceptibility"]) * chi,
        "persistence": float(w["persistence"]) * persistence,
        "barrier_openness": float(w["barrier_openness"]) * (1.0 - _clamp(barrier.get("barrier", 1.0))),
        "goldilocks": float(w["goldilocks"]) * (goldilocks if goldilocks is not None else 0.0),
        "concentration_penalty": float(w["concentration_penalty"]) * concentration_val,
        "ftr_penalty": float(w["ftr_penalty"]) * _clamp(ftr.get("ftr", 0.0)),
    }
    z = float(cfg["lrr_bias"]) + sum(components.values())
    score = _sigmoid(z)
    return {
        "lrr": round(score, 6),
        "score_semantics": SCORE_SEMANTICS,
        "weights_source": "configured_prior_uncalibrated",
        "contributions": {k: round(v, 6) for k, v in components.items()},
        "bias": float(cfg["lrr_bias"]),
    }


def compute_free_energy(
    lrr: float,
    pag: float,
    temperature: dict[str, Any],
    sufficiency_score: float,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Free-energy PROXY: executable-opportunity composite after penalties.

    "Free energy" is a modelling metaphor, not thermodynamics.  Friction is
    a configured prior (no live spread/liquidity feed on this path); the
    uncertainty penalty scales with missing data.  Can be negative — a
    negative value is an explicit no-usable-opportunity claim.
    """
    goldilocks = _finite_or_none(temperature.get("goldilocks_quality"))
    g = goldilocks if goldilocks is not None else 0.0
    q = _clamp(sufficiency_score)
    gross = _clamp(lrr) * max(0.0, pag) * g * q
    friction = float(cfg["friction_prior"])
    uncertainty_penalty = float(cfg["uncertainty_penalty_weight"]) * (1.0 - q)
    net = gross - friction - uncertainty_penalty
    return {
        "free_energy": round(max(-1.0, min(1.0, net)), 6),
        "gross_opportunity": round(gross, 6),
        "friction_prior": friction,
        "uncertainty_penalty": round(uncertainty_penalty, 6),
        "is_proxy": True,
        "estimator": "composite_proxy_v1",
    }


def compute_data_sufficiency(
    events: list[dict[str, Any]], notes: list[str], cfg: dict[str, Any]
) -> dict[str, Any]:
    """Data-sufficiency block: level, score, and what is limiting it."""
    n = len(events)
    limits: list[str] = []
    if n == 0:
        return {
            "level": "insufficient",
            "score": 0.0,
            "observation_count": 0,
            "limits": ["no_parseable_events"],
            "notes": sorted(set(notes)),
        }
    span_hours = 0.0
    if n >= 2:
        span_hours = (events[-1]["observed_at"] - events[0]["observed_at"]).total_seconds() / 3600.0
    per_event = _clamp(n / 8.0)
    span_component = _clamp(span_hours / 48.0)
    degraded = 1.0 if "degraded_single_representative_event" in notes else 0.0
    if degraded:
        limits.append("per_event_timestamps_unavailable")
    if n < int(cfg["min_events_for_geometry"]):
        limits.append("below_geometry_minimum")
    if span_hours < float(cfg["series_checkpoint_hours"]):
        limits.append("observation_span_shorter_than_checkpoint_step")
    score = _clamp(0.6 * per_event + 0.4 * span_component) * (0.5 if degraded else 1.0)
    if n < int(cfg["min_events_for_state"]):
        level = "insufficient"
    elif score < 0.25:
        level = "low"
    elif score < 0.6:
        level = "moderate"
    else:
        level = "high"
    return {
        "level": level,
        "score": round(score, 6),
        "observation_count": n,
        "observation_span_hours": round(span_hours, 2),
        "limits": limits,
        "notes": sorted(set(notes)),
    }


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


def classify_titration_state(
    metrics: dict[str, Any], cfg: dict[str, Any]
) -> dict[str, Any]:
    """Assign the titration state via explicit precedence rules.

    Order: INSUFFICIENT_DATA > FALSE_TRANSITION_RISK > CROWDED > EXHAUSTING
    > PRIMED > PRE_ALPHA_WATCH > LOADING > NO_EDGE > INERT.  The rule trace
    records which comparisons fired so state assignment is reproducible and
    reviewable.
    """
    trace: list[str] = []
    sufficiency = metrics["data_sufficiency"]
    active = _clamp(metrics["active_evidence"]["normalized"])
    lrr = _clamp(metrics["lrr"]["lrr"])
    vmr = _finite_or_none(metrics["vmr"].get("vmr"))
    pag = metrics.get("pre_alpha_gap")
    ftr = metrics["false_transition_risk"]
    geometry = metrics["geometry"]["label"]
    flow = metrics["flow"]
    barrier = _clamp(metrics["barrier"]["barrier"])
    goldilocks = _finite_or_none(metrics["temperature"].get("goldilocks_quality")) or 0.0
    free_energy = metrics["free_energy"]["free_energy"]

    if sufficiency["level"] == "insufficient":
        trace.append("sufficiency=insufficient")
        return {"state": "INSUFFICIENT_DATA", "rule_trace": trace}

    if ftr["triggered"]:
        trace.append(f"ftr {ftr['ftr']} >= gate {ftr['gate']}")
        return {"state": "FALSE_TRANSITION_RISK", "rule_trace": trace}

    if (
        vmr is not None
        and vmr >= float(cfg["crowded_vmr_min"])
        and pag is not None
        and pag <= float(cfg["crowded_pag_max"])
    ):
        trace.append(f"vmr {vmr} >= {cfg['crowded_vmr_min']} and pag {pag} <= {cfg['crowded_pag_max']}")
        return {"state": "CROWDED", "rule_trace": trace}

    if (
        geometry == "CONCAVE"
        and vmr is not None
        and vmr >= float(cfg["exhausting_vmr_min"])
    ):
        trace.append(f"geometry=CONCAVE and vmr {vmr} >= {cfg['exhausting_vmr_min']}")
        return {"state": "EXHAUSTING", "rule_trace": trace}

    if (
        lrr >= float(cfg["primed_lrr_min"])
        and pag is not None
        and pag >= float(cfg["primed_pag_min"])
        and barrier <= float(cfg["primed_barrier_max"])
        and goldilocks >= float(cfg["primed_goldilocks_min"])
    ):
        trace.append(
            f"lrr {lrr} >= {cfg['primed_lrr_min']}, pag {pag} >= {cfg['primed_pag_min']},"
            f" barrier {barrier} <= {cfg['primed_barrier_max']},"
            f" goldilocks {goldilocks} >= {cfg['primed_goldilocks_min']}"
        )
        return {"state": "PRIMED", "rule_trace": trace}

    if lrr >= float(cfg["watch_lrr_min"]) and pag is not None and pag >= float(cfg["watch_pag_min"]):
        trace.append(f"lrr {lrr} >= {cfg['watch_lrr_min']} and pag {pag} >= {cfg['watch_pag_min']}")
        return {"state": "PRE_ALPHA_WATCH", "rule_trace": trace}

    event_count = int(metrics["active_evidence"].get("event_count_used", 0))
    if (
        flow["loading"]
        and active >= float(cfg["inert_evidence_floor"]) / 2.0
        and event_count >= int(cfg.get("min_events_for_loading", 2))
    ):
        trace.append(
            f"net_accumulation {flow['net_accumulation']} > eps"
            f" with {event_count} events"
        )
        return {"state": "LOADING", "rule_trace": trace}

    if active >= float(cfg["inert_evidence_floor"]) and free_energy <= 0.0:
        trace.append(f"active {active} >= floor and free_energy {free_energy} <= 0")
        return {"state": "NO_EDGE", "rule_trace": trace}

    trace.append("default_inert")
    return {"state": "INERT", "rule_trace": trace}


# ---------------------------------------------------------------------------
# Explanation
# ---------------------------------------------------------------------------


def _build_explanation(metrics: dict[str, Any], state: str) -> dict[str, Any]:
    supporting: list[str] = []
    penalties: list[str] = []
    invalidation: list[str] = []

    flow = metrics["flow"]
    geometry = metrics["geometry"]
    temperature = metrics["temperature"]
    ftr = metrics["false_transition_risk"]
    concentration = metrics["source_concentration"]
    sufficiency = metrics["data_sufficiency"]
    pag = metrics.get("pre_alpha_gap")

    if flow["loading"]:
        supporting.append(
            f"evidence accumulating faster than it decays (net +{flow['net_accumulation']})"
        )
    elif flow["net_accumulation"] < 0:
        penalties.append(
            f"active evidence decaying faster than fresh inflow (net {flow['net_accumulation']})"
        )
    if geometry["label"] == "CONVEX":
        supporting.append("evidence curve is convex (accelerating accumulation)")
    elif geometry["label"] == "CONCAVE":
        penalties.append("evidence curve is concave (decelerating accumulation)")
    if metrics["barrier"]["crossed"]:
        supporting.append("active evidence has crossed the activation threshold")
    else:
        penalties.append(
            f"activation barrier remaining: {metrics['barrier']['barrier']}"
        )
    if pag is not None and pag > 0:
        supporting.append(f"positive pre-alpha gap (+{round(pag, 4)}: readiness exceeds recognition proxy)")
    elif pag is not None and pag < 0:
        penalties.append(f"recognition proxy exceeds readiness (pag {round(pag, 4)})")
    if temperature.get("regime") == "OVERHEATED":
        penalties.append("temperature regime OVERHEATED — false-transition pressure")
    elif temperature.get("regime") in {"WARM", "HOT"}:
        supporting.append(f"temperature regime {temperature['regime']} (reaction can propagate)")
    elif temperature.get("regime") == "COLD":
        penalties.append("temperature regime COLD — reactions propagate weakly")
    for reason in ftr["reasons"]:
        penalties.append(f"false-transition factor: {reason}")
    if concentration.get("single_source_dependence"):
        penalties.append("all active evidence from a single source family")
    if sufficiency["level"] in {"insufficient", "low"}:
        penalties.append(f"data sufficiency {sufficiency['level']}")

    invalidation.append(
        "no fresh evidence within ~2x the dominant half-life -> active evidence decays toward INERT"
    )
    invalidation.append("recognition proxy rising above readiness -> gap closes toward CROWDED")
    invalidation.append("temperature entering OVERHEATED -> state downgrades via FALSE_TRANSITION_RISK")
    if state == "PRIMED":
        invalidation.append("net accumulation turning negative -> PRIMED no longer holds")

    return {
        "state": state,
        "supporting_factors": supporting,
        "penalties": penalties,
        "invalidation_conditions": invalidation,
    }


# ---------------------------------------------------------------------------
# Public evaluation
# ---------------------------------------------------------------------------


def _stamp(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["safety"] = dict(SAFETY_STAMPS)
    out.setdefault("advisory_status", ADVISORY_STATUS)
    out.setdefault("execution_gate", EXECUTION_GATE_LOCKED)
    return out


def evaluate_market_titration(
    item: dict[str, Any],
    *,
    now: Any = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate the titration state of one inbox item.  Pure and deterministic
    given (item, now, config); ``now`` defaults to the current UTC time and
    should be pinned in tests.
    """
    if not isinstance(item, dict):
        item = {}
    cfg = config if isinstance(config, dict) and "half_life_hours_by_family" in (config or {}) else load_titration_config()
    if isinstance(now, datetime):
        now_dt = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        now_dt = now_dt.astimezone(timezone.utc)
    else:
        parsed = _parse_iso(now) if isinstance(now, str) else None
        now_dt = parsed or datetime.now(timezone.utc)

    events, notes = _extract_events(item, now_dt)
    sufficiency = compute_data_sufficiency(events, notes, cfg)
    active = compute_active_evidence(events, now_dt, cfg)
    series = compute_evidence_series(events, now_dt, cfg)
    geometry = classify_geometry(series, len(events), cfg)
    flow = compute_flow(events, now_dt, cfg)
    coherence = compute_coherence(item, active["per_source_mass"], cfg)
    concentration = compute_source_concentration(active["per_source_mass"])
    temperature = compute_temperature(item, events, now_dt, cfg)
    susceptibility = compute_susceptibility(
        geometry, coherence["score"], events, now_dt, cfg
    )
    buffer_capacity = compute_buffer_capacity(susceptibility.get("susceptibility"))
    barrier = compute_barrier(active["normalized"], cfg)
    mcd = compute_minimum_catalytic_dose(
        barrier["barrier"], susceptibility.get("susceptibility"), cfg
    )
    vmr = compute_vmr(item, events, now_dt, cfg)
    ftr = compute_ftr(temperature, concentration, item, coherence, sufficiency["score"], cfg)
    lrr = compute_lrr(
        active["normalized"], coherence, susceptibility, barrier,
        temperature, concentration, ftr, item, cfg,
    )
    vmr_val = _finite_or_none(vmr.get("vmr"))
    pag = round(lrr["lrr"] - vmr_val, 6) if vmr_val is not None else None
    free_energy = compute_free_energy(
        lrr["lrr"], pag if pag is not None else 0.0, temperature, sufficiency["score"], cfg
    )

    metrics: dict[str, Any] = {
        "active_evidence": active,
        "evidence_series": series,
        "geometry": geometry,
        "flow": flow,
        "coherence": coherence,
        "source_concentration": concentration,
        "temperature": temperature,
        "susceptibility": susceptibility,
        "buffer_capacity": buffer_capacity,
        "barrier": barrier,
        "minimum_catalytic_dose": mcd,
        "lrr": lrr,
        "vmr": vmr,
        "pre_alpha_gap": pag,
        "false_transition_risk": ftr,
        "free_energy": free_energy,
        "data_sufficiency": sufficiency,
    }
    decision = classify_titration_state(metrics, cfg)
    state = decision["state"]
    explanation = _build_explanation(metrics, state)

    return _stamp({
        "titration_state": state,
        "state_rule_trace": decision["rule_trace"],
        "operational_states": list(TITRATION_STATES),
        "reserved_states_not_operational": list(RESERVED_STATES),
        **metrics,
        "explanation": explanation,
        "score_semantics": SCORE_SEMANTICS,
        "schema_version": TITRATION_SCHEMA_VERSION,
        "scoring_version": TITRATION_SCORING_VERSION,
        "config_version": str(cfg.get("config_version", "unknown")),
        "config_status": str(cfg.get("config_status", "defaults")),
        "half_life_source": str(cfg.get("half_life_source", "configured_prior")),
        "calculated_at": now_dt.isoformat(),
        "ticker": str(item.get("ticker", "") or ""),
        "horizon": "swing_multi_day",  # single-horizon v1; see docs
    })


def compact_titration_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Compact projection of a full titration payload for inbox embedding.

    Keeps the /signals payload small while preserving the state, headline
    scores, proxy labels and a short explanation.  The full payload remains
    available via the engine CLI or direct evaluation.
    """
    if not isinstance(payload, dict):
        return {"titration_state": "INSUFFICIENT_DATA", "titration_available": False}
    temperature = payload.get("temperature") or {}
    explanation = payload.get("explanation") or {}
    return {
        "titration_state": str(payload.get("titration_state") or "INSUFFICIENT_DATA"),
        "titration_available": True,
        "titration": {
            "active_evidence": (payload.get("active_evidence") or {}).get("normalized"),
            "net_accumulation": (payload.get("flow") or {}).get("net_accumulation"),
            "loading": (payload.get("flow") or {}).get("loading"),
            "geometry": (payload.get("geometry") or {}).get("label"),
            "temperature": temperature.get("temperature"),
            "temperature_regime": temperature.get("regime"),
            "goldilocks_quality": temperature.get("goldilocks_quality"),
            "activation_barrier": (payload.get("barrier") or {}).get("barrier"),
            "susceptibility_proxy": (payload.get("susceptibility") or {}).get("susceptibility"),
            "buffer_capacity_proxy": (payload.get("buffer_capacity") or {}).get("buffer_capacity"),
            "mcd_normalized": (payload.get("minimum_catalytic_dose") or {}).get("mcd_normalized"),
            "lrr": (payload.get("lrr") or {}).get("lrr"),
            "vmr_proxy": (payload.get("vmr") or {}).get("vmr"),
            "pre_alpha_gap": payload.get("pre_alpha_gap"),
            "free_energy_proxy": (payload.get("free_energy") or {}).get("free_energy"),
            "false_transition_risk": (payload.get("false_transition_risk") or {}).get("ftr"),
            "data_sufficiency": (payload.get("data_sufficiency") or {}).get("level"),
            "supporting_factors": list(explanation.get("supporting_factors") or [])[:4],
            "penalties": list(explanation.get("penalties") or [])[:4],
            "score_semantics": SCORE_SEMANTICS,
            "scoring_version": TITRATION_SCORING_VERSION,
            "schema_version": TITRATION_SCHEMA_VERSION,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _example_item(now: datetime) -> dict[str, Any]:
    timestamps = [
        (now - timedelta(hours=h)).isoformat()
        for h in (70.0, 46.0, 28.0, 16.0, 8.0, 3.0, 1.0)
    ]
    sources = ["news", "news", "polymarket", "news", "official_filing", "polymarket", "news"]
    return {
        "ticker": "EXAMPLE",
        "event_timestamps": timestamps,
        "event_sources": sources,
        "event_count": len(timestamps),
        "cross_source_support_count": 3,
        "duplicate_suppressed_count": 1,
        "persistence_score": 0.7,
        "contamination_score": 0.1,
        "chaos_sensitivity_score": 0.3,
        "observed_at": timestamps[-1],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Market Titration Engine advisory CLI.")
    parser.add_argument("--example", action="store_true", help="Emit a worked example.")
    parser.add_argument("--json", action="store_true", help="Emit JSON (default).")
    args = parser.parse_args(argv)

    if args.example:
        now = datetime.now(timezone.utc)
        payload = evaluate_market_titration(_example_item(now), now=now)
    else:
        payload = _stamp({
            "titration_state": "INSUFFICIENT_DATA",
            "note": "no input provided — use --example to see a worked example",
        })
    print(json.dumps(payload, indent=2, default=str))
    return 0


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "SAFETY_STAMPS",
    "TITRATION_STATES",
    "RESERVED_STATES",
    "GEOMETRY_LABELS",
    "TEMPERATURE_REGIMES",
    "TITRATION_SCHEMA_VERSION",
    "TITRATION_SCORING_VERSION",
    "SCORE_SEMANTICS",
    "DEFAULT_CONFIG",
    "load_titration_config",
    "decay_factor",
    "evaluate_market_titration",
    "compact_titration_fields",
]


if __name__ == "__main__":
    raise SystemExit(main())
