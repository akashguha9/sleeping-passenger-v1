"""External observation lane — normalized, provider-agnostic price observations.

This module is the narrow, advisory-only sensory surface for external truth.
It produces ``ExternalObservation`` rows with a stable contract that
diagnostics, SCM context, and the action engine can consume without caring
which provider served the data.

Design contract:

* Every call returns a shaped ``ExternalObservation`` dataclass row. Provider
  failures do NOT raise — they return an observation with
  ``data_quality=PROVIDER_ERROR`` and ``error`` populated. This is what keeps
  diagnostics truthful under partial/zero-provider conditions.
* ``is_external`` is only ``True`` when a provider actually returned a
  finite price. Placeholder and seeded fallbacks are always
  ``is_external=False`` and ``is_placeholder=True`` respectively.
* ``source_mode`` and ``truth_origin`` on the row reflect this lane's view
  only; the runtime-wide source_mode is still governed by ``runtime_common``.
* The report written to ``runtime/external_observation_report.json`` is
  stamped via ``write_json_atomic`` so it inherits the runtime coherence
  layer (run_id, source_mode, operating_mode, truth_origin, timestamps).
* No internet calls on import. Tests inject a fake provider. The real
  provider hook is resolved lazily and is optional.

Advisory-only contract:
* This module is observation, not alpha. It does not emit buy/sell
  recommendations, and ``observations_to_signal_context`` deliberately
  labels its output as context rows, not trade signals.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    from scripts.runtime_common import (
        RUNTIME_DIR,
        get_source_mode,
        utc_timestamp,
        write_json_atomic,
    )
except ModuleNotFoundError:  # pragma: no cover - script-relative import fallback
    from runtime_common import (
        RUNTIME_DIR,
        get_source_mode,
        utc_timestamp,
        write_json_atomic,
    )


EXTERNAL_OBSERVATION_REPORT_PATH = RUNTIME_DIR / "external_observation_report.json"

VALID_DATA_QUALITY = {
    "VALID_EXTERNAL",
    "STALE_EXTERNAL",
    "MISSING_PRICE",
    "PROVIDER_ERROR",
    "PLACEHOLDER",
    "SEEDED_FALLBACK",
}

# Any observation older than this is flagged STALE_EXTERNAL rather than
# VALID_EXTERNAL. Six hours is deliberately generous — this lane is advisory
# context, not a microstructure feed.
DEFAULT_STALENESS_LIMIT_SECONDS = 6 * 60 * 60


@dataclass
class ExternalObservation:
    symbol: str
    provider: str
    observed_at_utc: str
    price: float | None = None
    previous_close: float | None = None
    change_pct: float | None = None
    volume: float | None = None
    currency: str | None = None
    source_mode: str = "SYNTHETIC_RUNTIME_FALLBACK"
    truth_origin: str = "seeded"
    is_external: bool = False
    is_placeholder: bool = True
    data_quality: str = "PLACEHOLDER"
    error: str | None = None
    staleness_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------


ProviderFetchFn = Callable[[str], dict[str, Any]]


def _default_yahoo_provider(symbol: str) -> dict[str, Any]:
    """Resolve the Yahoo provider lazily.

    Kept lazy so that importing this module never triggers a network-capable
    import chain. Tests must monkeypatch ``fetch_external_observation`` or
    pass an explicit ``provider_fn`` rather than relying on this fallback.
    """
    from scripts.yahoo_market_data_adapter import (  # local import on purpose
        _fetch_symbol_with_yfinance,
    )
    return _fetch_symbol_with_yfinance(symbol)


def _resolve_provider(provider: str) -> ProviderFetchFn:
    name = (provider or "").strip().lower()
    if name == "yahoo":
        return _default_yahoo_provider
    raise ValueError(
        f"unsupported external observation provider {provider!r}; "
        f"tests should pass provider_fn explicitly"
    )


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def _coerce_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return None


def _staleness_seconds(observed_at_utc: str | None, now_utc: str) -> float | None:
    if not observed_at_utc:
        return None
    try:
        obs = datetime.fromisoformat(observed_at_utc.replace("Z", "+00:00"))
    except ValueError:
        return None
    try:
        now = datetime.fromisoformat(now_utc.replace("Z", "+00:00"))
    except ValueError:
        return None
    if obs.tzinfo is None:
        obs = obs.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = (now - obs).total_seconds()
    return delta if delta >= 0 else 0.0


def _change_pct(price: float | None, previous_close: float | None) -> float | None:
    if price is None or previous_close is None or previous_close == 0:
        return None
    return round((price - previous_close) / previous_close, 6)


def _classify_data_quality(
    price: float | None,
    error: str | None,
    staleness_seconds: float | None,
    staleness_limit_seconds: float,
) -> str:
    if error:
        return "PROVIDER_ERROR"
    if price is None:
        return "MISSING_PRICE"
    if staleness_seconds is not None and staleness_seconds > staleness_limit_seconds:
        return "STALE_EXTERNAL"
    return "VALID_EXTERNAL"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_external_observation(
    symbol: str,
    provider: str = "yahoo",
    *,
    provider_fn: ProviderFetchFn | None = None,
    now_utc: str | None = None,
    staleness_limit_seconds: float = DEFAULT_STALENESS_LIMIT_SECONDS,
) -> ExternalObservation:
    """Fetch a single external observation.

    Never raises on provider failure. Returns a row with
    ``data_quality=PROVIDER_ERROR`` on exception, or
    ``data_quality=MISSING_PRICE`` when the provider responded but supplied
    no usable last price.
    """
    normalized_symbol = str(symbol or "").strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol must be a non-empty string")

    resolved_now = now_utc or utc_timestamp()
    provider_name = (provider or "").strip().lower() or "unknown"

    fetcher = provider_fn if provider_fn is not None else _resolve_provider(provider_name)

    raw: dict[str, Any] = {}
    error: str | None = None
    try:
        raw = fetcher(normalized_symbol) or {}
    except Exception as exc:  # provider must never crash diagnostics
        error = str(exc) or exc.__class__.__name__

    price = _coerce_float(raw.get("last_price"))
    previous_close = _coerce_float(raw.get("previous_close"))
    volume = _coerce_float(raw.get("volume"))
    currency = raw.get("currency") if raw.get("currency") is not None else None
    observed_at_utc = _coerce_timestamp(raw.get("regular_market_time")) or resolved_now
    staleness = _staleness_seconds(observed_at_utc, resolved_now)

    data_quality = _classify_data_quality(
        price=price,
        error=error,
        staleness_seconds=staleness,
        staleness_limit_seconds=staleness_limit_seconds,
    )
    is_external = data_quality in {"VALID_EXTERNAL", "STALE_EXTERNAL"}
    is_placeholder = not is_external

    if is_external:
        truth_origin = "external"
    else:
        truth_origin = "seeded" if data_quality != "PROVIDER_ERROR" else "seeded"

    return ExternalObservation(
        symbol=normalized_symbol,
        provider=provider_name,
        observed_at_utc=observed_at_utc,
        price=price,
        previous_close=previous_close,
        change_pct=_change_pct(price, previous_close),
        volume=volume,
        currency=str(currency) if currency is not None else None,
        source_mode=get_source_mode(),
        truth_origin=truth_origin,
        is_external=is_external,
        is_placeholder=is_placeholder,
        data_quality=data_quality,
        error=error,
        staleness_seconds=staleness,
    )


def fetch_external_observations(
    symbols: Iterable[str],
    provider: str = "yahoo",
    *,
    provider_fn: ProviderFetchFn | None = None,
    now_utc: str | None = None,
    staleness_limit_seconds: float = DEFAULT_STALENESS_LIMIT_SECONDS,
) -> list[ExternalObservation]:
    """Fetch a batch of external observations.

    Deterministic ordering: input symbols are deduplicated case-insensitively
    and returned sorted. Partial failure is tolerated — each symbol gets its
    own row with its own ``data_quality`` classification.
    """
    seen: set[str] = set()
    normalized: list[str] = []
    for raw_symbol in symbols:
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    normalized.sort()

    resolved_now = now_utc or utc_timestamp()
    rows: list[ExternalObservation] = []
    for symbol in normalized:
        rows.append(
            fetch_external_observation(
                symbol,
                provider=provider,
                provider_fn=provider_fn,
                now_utc=resolved_now,
                staleness_limit_seconds=staleness_limit_seconds,
            )
        )
    return rows


def summarize_external_observations(
    observations: Iterable[ExternalObservation],
) -> dict[str, Any]:
    """Collapse a batch of observations into a counts-first summary dict.

    Shape matches the fields the diagnostics pipeline surfaces.
    """
    rows = list(observations)
    total = len(rows)
    providers = sorted({row.provider for row in rows if row.provider})
    symbols = [row.symbol for row in rows]
    data_quality_counts: dict[str, int] = {q: 0 for q in VALID_DATA_QUALITY}
    for row in rows:
        key = row.data_quality if row.data_quality in VALID_DATA_QUALITY else "PROVIDER_ERROR"
        data_quality_counts[key] = data_quality_counts.get(key, 0) + 1

    valid_count = data_quality_counts.get("VALID_EXTERNAL", 0)
    stale_count = data_quality_counts.get("STALE_EXTERNAL", 0)
    error_count = (
        data_quality_counts.get("PROVIDER_ERROR", 0)
        + data_quality_counts.get("MISSING_PRICE", 0)
    )
    active_count = valid_count + stale_count

    return {
        "external_observation_count": total,
        "external_observation_valid_count": valid_count,
        "external_observation_stale_count": stale_count,
        "external_observation_error_count": error_count,
        "external_observation_active_count": active_count,
        "external_observation_providers": providers,
        "external_observation_symbols": symbols,
        "external_observation_data_quality_counts": data_quality_counts,
    }


def observations_to_signal_context(
    observations: Iterable[ExternalObservation],
) -> list[dict[str, Any]]:
    """Produce advisory context rows for SCM/action consumers.

    These rows are deliberately labeled ``is_trade_signal=False``. They
    describe reality (a real provider returned a real price), not a
    recommendation. Confidence is a function of data quality, not of any
    prediction.
    """
    context_rows: list[dict[str, Any]] = []
    confidence_by_quality = {
        "VALID_EXTERNAL": 0.8,
        "STALE_EXTERNAL": 0.5,
        "MISSING_PRICE": 0.1,
        "PROVIDER_ERROR": 0.0,
        "PLACEHOLDER": 0.0,
        "SEEDED_FALLBACK": 0.0,
    }
    for row in observations:
        context_rows.append(
            {
                "symbol": row.symbol,
                "source": "external_price_observation",
                "provider": row.provider,
                "truth_origin": row.truth_origin,
                "observed_at_utc": row.observed_at_utc,
                "price": row.price,
                "change_pct": row.change_pct,
                "volume": row.volume,
                "currency": row.currency,
                "data_quality": row.data_quality,
                "staleness_seconds": row.staleness_seconds,
                "confidence": confidence_by_quality.get(row.data_quality, 0.0),
                "is_external": row.is_external,
                "is_placeholder": row.is_placeholder,
                "is_trade_signal": False,
            }
        )
    return context_rows


def _observation_row_id(row: ExternalObservation) -> str:
    compact_timestamp = (
        str(row.observed_at_utc or "")
        .replace(":", "")
        .replace("-", "")
        .replace("+", "")
        .replace("T", "_")
    )
    return f"obs_{row.provider}_{row.symbol}_{compact_timestamp}"


def _candidate_ce_score(row: ExternalObservation) -> float:
    """Map observation strength into a bounded SCM-compatible advisory score.

    This is deliberately simple and conservative: it is a watchlist
    prioritization hint, not a predictive score.
    """
    if not row.is_external:
        return 0.0
    change_mag = abs(float(row.change_pct or 0.0))
    volume_bonus = 0.08 if row.volume and float(row.volume) > 0 else 0.0
    freshness_penalty = 0.12 if row.data_quality == "STALE_EXTERNAL" else 0.0
    base = 0.45 + min(change_mag * 8.0, 0.25) + volume_bonus - freshness_penalty
    return round(max(0.0, min(base, 0.95)), 3)


def observations_to_scm_candidates(
    observations: Iterable[ExternalObservation],
) -> list[dict[str, Any]]:
    """Convert valid external observations into advisory SCM candidate rows.

    Contract:
      * Advisory only: rows remain watchlist candidates and carry an explicit
        gate lock so they cannot imply deployment readiness.
      * Deterministic: candidate IDs derive from provider/symbol/timestamp.
      * Honest: only external/stale-external observations become SCM rows.
    """
    candidate_rows: list[dict[str, Any]] = []
    for row in observations:
        if (
            not isinstance(row, ExternalObservation)
            or row.data_quality != "VALID_EXTERNAL"
        ):
            continue
        observation_id = _observation_row_id(row)
        ce_score = _candidate_ce_score(row)
        candidate_rows.append(
            {
                "signal_id": f"EXT_OBS_{row.provider.upper()}_{row.symbol}_{observation_id.split('_')[-1]}",
                "ticker": row.symbol,
                "ce_score": ce_score,
                "above_ce_threshold": ce_score > 0.0,
                "status": "WATCHLIST",
                "conversion_state": "NOT_EXECUTED",
                "blocker_attribution": "GSCE_PHASE_LOCK",
                "promotable_clean_candidate": False,
                "watchlist_tier": "STANDARD",
                "candidate_conversion_state": "NOT_EXECUTED",
                "pre_entry_state": "EXTERNAL_OBSERVATION_CANDIDATE",
                "source_name": "external_observation",
                "signal_origin": "external",
                "origin_label": "external_observation_advisory_candidate",
                "provider": row.provider,
                "observed_at_utc": row.observed_at_utc,
                "price": row.price,
                "reference_price": row.price,
                "change_pct": row.change_pct,
                "volume": row.volume,
                "currency": row.currency,
                "data_quality": row.data_quality,
                "source_observation_id": observation_id,
                "is_trade_signal": False,
                "question": (
                    f"External observation candidate for {row.symbol} from "
                    f"{row.provider}; advisory watchlist context only."
                ),
            }
        )
    return candidate_rows


def apply_observation_summary_to_runtime_state(
    runtime_state: dict[str, Any] | None,
    observation_report: dict[str, Any] | None,
) -> dict[str, Any]:
    """Stamp the runtime state so downstream code sees live external quotes.

    This is the handoff between the lane and the pre-existing
    ``_external_observation_state`` / ``build_truth_context`` logic in
    runtime_common. Setting ``external_observation_active=True`` there is
    what flips operating_mode to ``hybrid`` and truth_origin to ``external``
    when the lane returns at least one valid observation.

    We do NOT mutate when no valid observation exists — seeded fallback
    stays in place.
    """
    state = dict(runtime_state or {})
    report = observation_report if isinstance(observation_report, dict) else {}
    if not report.get("external_observation_active"):
        return state
    providers = report.get("external_observation_providers") or []
    if isinstance(providers, list) and providers:
        state["external_observation_source"] = str(providers[0])
    else:
        state["external_observation_source"] = str(
            report.get("external_observation_provider") or "yahoo"
        )
    state["external_observation_active"] = True
    state["external_observation_fetched_at"] = utc_timestamp()
    return state


def safe_write_external_observation_report(
    observations: Iterable[ExternalObservation],
    path: Path | str | None = None,
    *,
    provider: str = "yahoo",
    write: bool = True,
) -> dict[str, Any]:
    """Build the external observation report and write it atomically.

    Always returns the report payload. When ``write=False`` the payload is
    computed but not persisted — used by tests and by callers that want the
    shape without touching disk.
    """
    rows = list(observations)
    summary = summarize_external_observations(rows)
    active = summary["external_observation_active_count"] > 0
    target = Path(path) if path is not None else EXTERNAL_OBSERVATION_REPORT_PATH

    report = {
        "external_observation_active": active,
        "external_observation_provider": provider,
        **summary,
        "observations": [row.to_dict() for row in rows],
        "advisory_note": (
            "External price observations are advisory context only. They do "
            "not enable capital deployment, and the governance layer keeps "
            "system_readiness_state unchanged."
        ),
    }
    if write:
        write_json_atomic(target, report)
    report["external_observation_report_path"] = str(target)
    return report


__all__ = [
    "EXTERNAL_OBSERVATION_REPORT_PATH",
    "VALID_DATA_QUALITY",
    "DEFAULT_STALENESS_LIMIT_SECONDS",
    "ExternalObservation",
    "ProviderFetchFn",
    "fetch_external_observation",
    "fetch_external_observations",
    "summarize_external_observations",
    "observations_to_signal_context",
    "observations_to_scm_candidates",
    "apply_observation_summary_to_runtime_state",
    "safe_write_external_observation_report",
]
