"""Safe, advisory live-price refresh — populate market_data before synthesis.

C_price was 0 because synthesis can run before any ``market_data`` mark exists
in SQLite. This module refreshes price marks from a *provider callable* and
persists them as canonical ``market_data`` ``signal_events`` rows, so the
existing :mod:`scripts.live_price_movers_bridge` can then see ``valid_price=1``.

Hard safety contract
--------------------
* No broker, no order placement, no execution. Refreshing a *price quote* is
  read-of-market only — it never trades. ``broker_api_called`` stays False,
  ``ai_execution_count`` stays 0, ``execution_gate`` stays LOCKED.
* The provider is injected (a callable). Tests pass a deterministic mock; no
  network and no API key are ever required. When no provider is configured the
  refresh writes nothing and reports ``PRICE_PROVIDER_NOT_CONFIGURED``.
* Never fabricates a price: a provider that returns nothing for a symbol yields
  an honest per-symbol failure status, not a fake mark.
* Writes only advisory ``market_data`` marks (idempotent on a deterministic
  event_id); never mutates trades, holdings, or execution state.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    import scripts.persistence as _persistence
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.live_price_movers_bridge import build_live_price_movers, infer_currency
    from scripts.runtime_common import utc_timestamp
    from scripts.top30_country_coverage import build_country_coverage_from_payload
except ModuleNotFoundError:  # pragma: no cover - script-style env
    import persistence as _persistence  # type: ignore[no-redef]
    from advisory_contract import advisory_safety_stamps
    from live_price_movers_bridge import build_live_price_movers, infer_currency
    from runtime_common import utc_timestamp
    from top30_country_coverage import build_country_coverage_from_payload


# Honest provider/price status vocabulary (mission P3). None is an instruction.
PRICE_PROVIDER_NOT_CONFIGURED = "PRICE_PROVIDER_NOT_CONFIGURED"
PRICE_PROVIDER_KEY_MISSING = "PRICE_PROVIDER_KEY_MISSING"
PRICE_PROVIDER_OK_EMPTY = "PRICE_PROVIDER_OK_EMPTY"
PRICE_PROVIDER_TIMEOUT = "PRICE_PROVIDER_TIMEOUT"
SYMBOL_UNSUPPORTED = "SYMBOL_UNSUPPORTED"
MARKET_CLOSED_STALE_OK = "MARKET_CLOSED_STALE_OK"
LIVE_PRICE_VERIFIED = "LIVE_PRICE_VERIFIED"
DEGRADED_MARKET_STATE_UNKNOWN = "DEGRADED_MARKET_STATE_UNKNOWN"

# Advisory thresholds for the new-risk visibility gate (early-MVP values).
THETA_H_PRICE = 0.80
THETA_C_PRICE_MIN = 0.10

# A provider takes a ticker and returns a mark dict (or None when it has no
# fresh quote). Expected keys: price|close, timestamp_utc|timestamp, currency?,
# volume?. It MUST be read-only (a quote), never an order.
PriceProvider = Callable[[str], "dict[str, Any] | None"]


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(microsecond=0).isoformat()


def refresh_price_marks(
    tickers: Iterable[str],
    *,
    provider: PriceProvider | None = None,
    db_path: Path | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Fetch (via the injected provider) + persist advisory market_data marks.

    Returns an honest summary. With ``provider=None`` nothing is written and the
    status is ``PRICE_PROVIDER_NOT_CONFIGURED`` (C_price will stay 0). Never
    raises — a misbehaving provider degrades to a per-symbol failure status.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    fetched_at = _iso(now_utc)
    unique = list(dict.fromkeys(str(t).strip().upper() for t in (tickers or []) if t))

    base = {
        "attempted": provider is not None,
        "written": 0,
        "symbols_requested": len(unique),
        "results": [],
        "is_live": False,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_gate": "LOCKED",
        "safety": advisory_safety_stamps(),
    }

    if provider is None:
        base["status"] = PRICE_PROVIDER_NOT_CONFIGURED
        base["reason"] = "no price provider configured; no marks written"
        return base

    written = 0
    results: list[dict[str, Any]] = []
    for ticker in unique:
        try:
            mark = provider(ticker)
        except Exception:  # noqa: BLE001 - provider failure is per-symbol safe
            results.append({"ticker": ticker, "status": PRICE_PROVIDER_TIMEOUT, "written": False})
            continue
        if not isinstance(mark, dict):
            results.append({"ticker": ticker, "status": SYMBOL_UNSUPPORTED, "written": False})
            continue
        price = mark.get("price")
        if price is None:
            price = mark.get("close")
        timestamp = mark.get("timestamp_utc") or mark.get("timestamp")
        if price is None or not timestamp:
            results.append({"ticker": ticker, "status": PRICE_PROVIDER_OK_EMPTY, "written": False})
            continue
        currency = str(mark.get("currency") or infer_currency(ticker))
        raw_payload = {
            "symbol": ticker,
            "close": float(price),
            "price": float(price),
            "timestamp": timestamp,
            "currency": currency,
            "volume": mark.get("volume"),
            "provider": str(mark.get("provider") or "injected_price_provider"),
        }
        event_id = f"market_data_{ticker}_{timestamp}"
        try:
            inserted = _persistence.insert_signal_event(
                event_id, "market_data", raw_payload, fetched_at, db_path=db_path
            )
        except Exception:  # noqa: BLE001 - persistence failure is safe
            results.append({"ticker": ticker, "status": PRICE_PROVIDER_TIMEOUT, "written": False})
            continue
        if inserted:
            written += 1
        results.append({"ticker": ticker, "status": LIVE_PRICE_VERIFIED, "written": bool(inserted)})

    base["written"] = written
    base["results"] = results
    base["is_live"] = written > 0
    base["status"] = LIVE_PRICE_VERIFIED if written > 0 else PRICE_PROVIDER_OK_EMPTY
    return base


def price_mark_valid(row: dict[str, Any]) -> bool:
    """A price row is valid iff the bridge flagged ``valid_price``."""
    return bool(row.get("valid_price"))


def compute_h_price_coverage(holding_rows: list[dict[str, Any]]) -> float:
    """H_price_coverage = |valid holding prices| / max(1, |holdings|)."""
    if not holding_rows:
        return 0.0
    valid = sum(1 for r in holding_rows if price_mark_valid(r))
    return round(valid / max(1, len(holding_rows)), 4)


def evaluate_new_risk_gate(
    h_price_coverage: float,
    c_price: float,
    *,
    theta_h: float = THETA_H_PRICE,
    theta_c: float = THETA_C_PRICE_MIN,
) -> dict[str, Any]:
    """Advisory new-risk visibility gate. NEVER unlocks execution.

    ``new_risk_allowed`` is advisory guidance for the operator/synthesis: when
    existing-holding price visibility is degraded, new discovery risk should be
    held back. It cannot and does not authorise any trade — the execution gate
    stays LOCKED and the human remains the only executor.
    """
    visibility_ok = h_price_coverage >= theta_h
    coverage_ok = c_price >= theta_c
    warnings: list[str] = []
    if not visibility_ok:
        warnings.append("EXISTING_RISK_VISIBILITY_DEGRADED")
    if not coverage_ok:
        warnings.append("GLOBAL_PRICE_COVERAGE_THIN")
    return {
        "new_risk_allowed": bool(visibility_ok and coverage_ok),
        "h_price_coverage": round(h_price_coverage, 4),
        "c_price": round(c_price, 4),
        "theta_h_price": theta_h,
        "theta_c_price_min": theta_c,
        "warnings": warnings,
        # Advisory only — gate never grants execution.
        "advisory_only": True,
        "human_review_required": True,
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


def build_price_coverage(
    db_path: Path | None,
    *,
    holdings: Iterable[str] | None = None,
    candidate_tickers: Iterable[str] | None = None,
    holding_countries: dict[str, str] | None = None,
    now_utc: datetime | None = None,
    market_state: str = "unknown",
    top30: list[str] | None = None,
) -> dict[str, Any]:
    """Build price rows + C_price + H_price_coverage from persisted marks."""
    movers = build_live_price_movers(
        db_path,
        now_utc=now_utc,
        holdings=holdings,
        candidate_tickers=candidate_tickers,
        holding_countries=holding_countries,
        market_state=market_state,
    )
    existing = movers["existing_position_price_review"]
    candidates = movers["new_candidate_price_movers"]
    price_rows = existing + candidates
    coverage = build_country_coverage_from_payload(
        {"price_movers": {"movers": price_rows}, "news_events": {"events": []},
         "filings_events": {"events": []}},
        price_rows=price_rows,
        universe_records=[],
        top30=top30,
    )
    h_price = compute_h_price_coverage(existing)
    return {
        "price_rows": price_rows,
        "C_price": coverage["ratios"]["C_price"],
        "H_price_coverage": h_price,
        "price_meta": movers["meta"],
        "coverage_ratios": coverage["ratios"],
    }


__all__ = [
    "PRICE_PROVIDER_NOT_CONFIGURED",
    "PRICE_PROVIDER_OK_EMPTY",
    "LIVE_PRICE_VERIFIED",
    "SYMBOL_UNSUPPORTED",
    "THETA_H_PRICE",
    "THETA_C_PRICE_MIN",
    "refresh_price_marks",
    "price_mark_valid",
    "compute_h_price_coverage",
    "evaluate_new_risk_gate",
    "build_price_coverage",
]
