"""N'Golo Kanté real-provider canary — read-only price canary + coverage proof.

This is the *defensive* canary the sprint asks for: it presses real read-only
price providers (priority ``P_price = [yahoo_public, twelve_data, alpha_vantage,
polygon]``) for a tight basket of global tickers, classifies every result
honestly, and recomputes the REAL_RUN country-coverage proof from the *live*
daily payload plus the real price marks it just fetched.

Hard safety contract (mirrors the rest of the MVP):
    * Read-of-market only. A price quote NEVER trades. No broker, no order, no
      execution endpoint is reachable from here.
    * Network is OFF by default. Nothing touches the wire unless the caller
      passes ``allow_network=True`` (CLI ``--allow-network``). Without it every
      ticker degrades to ``NETWORK_DISABLED`` — honest, never fabricated.
    * Secrets are never logged. Only ``api_key_present`` booleans appear in the
      report; a final :func:`provider_secret_redaction.assert_no_secret` guard
      proves no configured key value leaked into the rendered report.
    * A misbehaving / empty / unsupported provider degrades to an honest status.
      LIVE is never claimed without a fresh, positive, currency-stamped mark.

The fixture proof (``country_coverage_proof.germany_fixture_coverage``) is kept
strictly separate: this module produces a ``REAL_RUN`` proof and never upgrades
a fixture into a live claim.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.country_coverage_proof import (
        DEFAULT_TARGET_COUNTRIES,
        build_proof_from_payload,
    )
    from scripts.provider_secret_redaction import (
        assert_no_secret,
        collect_secret_values,
    )
    from scripts.real_price_provider import (
        PRICE_PROVIDER_PRIORITY,
        PROVIDER_ENV,
        build_mock_price_transport,
        describe_price_providers,
        resolve_price_provider,
    )
    from scripts.top30_country_coverage import country_from_ticker
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from country_coverage_proof import (
        DEFAULT_TARGET_COUNTRIES,
        build_proof_from_payload,
    )
    from provider_secret_redaction import assert_no_secret, collect_secret_values
    from real_price_provider import (
        PRICE_PROVIDER_PRIORITY,
        PROVIDER_ENV,
        build_mock_price_transport,
        describe_price_providers,
        resolve_price_provider,
    )
    from top30_country_coverage import country_from_ticker

REPO_ROOT = Path(__file__).resolve().parents[1]
DAILY_PAYLOAD_DIR = REPO_ROOT / "data" / "daily_payload"
RELEASE_DIR = REPO_ROOT / "runtime" / "release"
CANARY_REPORT_PATH = RELEASE_DIR / "kante_real_provider_canary.json"

# Honest per-ticker status vocabulary.
NETWORK_DISABLED = "NETWORK_DISABLED"
LIVE_PRICE_VERIFIED = "LIVE_PRICE_VERIFIED"
PRICE_PROVIDER_OK_EMPTY = "PRICE_PROVIDER_OK_EMPTY"
SYMBOL_UNSUPPORTED = "SYMBOL_UNSUPPORTED"
PRICE_PROVIDER_NOT_CONFIGURED = "PRICE_PROVIDER_NOT_CONFIGURED"
DEGRADED_MARKET_STATE_UNKNOWN = "DEGRADED_MARKET_STATE_UNKNOWN"
PRICE_STALE = "PRICE_STALE"

# --- Canary basket (Section 2 T_canary) -------------------------------------
# Each entry: ticker -> declared country (for coverage attribution). Suffixed
# tickers are double-checked against country_from_ticker; bare US-listed names
# resolve to United States (NYSE/Nasdaq) which the suffix map cannot infer.
T_CANARY: dict[str, str] = {
    "RHM.DE": "Germany",
    "SHEL.L": "United Kingdom",
    "RELIANCE.NS": "India",
    "HDFCBANK.NS": "India",
    "7203.T": "Japan",
    "MSFT": "United States",
}

# --- Canonical holdings H (Section 3) ---------------------------------------
HOLDINGS_H: dict[str, str] = {
    "ANET": "United States",
    "ASML": "United States",   # ADR on Nasdaq (holding symbol preserved)
    "CVX": "United States",
    "HDFCBANK.NS": "India",
    "LMT": "United States",
    "MSFT": "United States",
    "RELIANCE.NS": "India",
    "RTX": "United States",
    "TSM": "United States",    # ADR on NYSE (holding symbol preserved)
    "XOM": "United States",
}

# --- UK breadth tickers (Section 4) -----------------------------------------
UK_TICKERS: dict[str, str] = {
    "SHEL.L": "United Kingdom",
    "BP.L": "United Kingdom",
    "AZN.L": "United Kingdom",
    "HSBA.L": "United Kingdom",
}

# Exchange-suffix -> rough local trading hours in UTC (open_hour, close_hour).
# Used only for a coarse OPEN/CLOSED/UNKNOWN market-state estimate; we never
# claim minute-accuracy and we degrade to UNKNOWN for venues we cannot place.
_SUFFIX_SESSION_UTC: dict[str, tuple[int, int]] = {
    ".DE": (7, 16),    # Xetra ~09:00-17:30 CET
    ".F": (7, 16),
    ".L": (8, 16),     # LSE 08:00-16:30 BST/GMT
    ".NS": (4, 10),    # NSE 09:15-15:30 IST
    ".BO": (4, 10),
    ".T": (0, 6),      # Tokyo 09:00-15:00 JST
    "": (14, 21),      # US NYSE/Nasdaq 09:30-16:00 ET (bare ticker)
}
POST_CLOSE_BUFFER_MINUTES = 72 * 60  # cover a full weekend close window
OPEN_MAX_AGE_MINUTES = 60
UNKNOWN_MAX_AGE_MINUTES = 1440


def _suffix_of(ticker: str) -> str:
    t = str(ticker).strip().upper()
    if "." in t:
        return "." + t.rsplit(".", 1)[1]
    return ""


def market_state(ticker: str, now_utc: datetime) -> str:
    """Coarse OPEN / CLOSED / UNKNOWN estimate for a ticker's venue.

    Weekends are CLOSED. On a weekday we treat the venue as OPEN inside its
    rough local session window (UTC) and CLOSED otherwise. A venue we cannot
    place returns UNKNOWN (which widens the freshness window and stamps a
    DEGRADED flag — we never silently accept stale data).
    """
    suffix = _suffix_of(ticker)
    if suffix not in _SUFFIX_SESSION_UTC:
        return "UNKNOWN"
    # Monday=0 .. Sunday=6
    if now_utc.weekday() >= 5:
        return "CLOSED"
    open_h, close_h = _SUFFIX_SESSION_UTC[suffix]
    return "OPEN" if open_h <= now_utc.hour < close_h else "CLOSED"


def max_age_minutes_for(ticker: str, now_utc: datetime) -> tuple[int, str]:
    """Return (max_age_minutes, market_state) for a ticker per the TTL spec."""
    state = market_state(ticker, now_utc)
    if state == "OPEN":
        return OPEN_MAX_AGE_MINUTES, state
    if state == "CLOSED":
        # minutes_since_last_close is bounded above by the weekend window; we
        # accept the most recent session close plus a post-close buffer.
        return POST_CLOSE_BUFFER_MINUTES, state
    return UNKNOWN_MAX_AGE_MINUTES, state


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def evaluate_mark(
    ticker: str, mark: dict[str, Any] | None, now_utc: datetime
) -> dict[str, Any]:
    """Classify a single provider mark into an honest per-ticker result.

    valid_price(t) is true only when price>0, a UTC timestamp and currency are
    present, and age <= the market-state TTL. Never fabricates a price.
    """
    country = T_CANARY.get(ticker) or country_from_ticker(ticker) or _country_fallback(ticker)
    base: dict[str, Any] = {
        "ticker": ticker,
        "country": country,
        "valid_price": False,
        "price": None,
        "currency": None,
        "age_minutes": None,
        "market_state": None,
        "provider_selected": None,
        "status": PRICE_PROVIDER_OK_EMPTY,
        "failure_reason": None,
    }
    if mark is None:
        base["status"] = SYMBOL_UNSUPPORTED
        base["failure_reason"] = "provider returned no mark (empty/unsupported)"
        return base

    price = mark.get("price")
    ts = _parse_ts(mark.get("timestamp_utc"))
    currency = mark.get("currency")
    provider = mark.get("provider")
    base["provider_selected"] = provider
    base["price"] = price
    base["currency"] = currency
    max_age, state = max_age_minutes_for(ticker, now_utc)
    base["market_state"] = state

    if price is None or ts is None or not currency:
        base["status"] = PRICE_PROVIDER_OK_EMPTY
        base["failure_reason"] = "missing price/timestamp/currency"
        return base
    try:
        price_f = float(price)
    except (TypeError, ValueError):
        base["status"] = PRICE_PROVIDER_OK_EMPTY
        base["failure_reason"] = "non-numeric price"
        return base
    if price_f <= 0:
        base["status"] = PRICE_PROVIDER_OK_EMPTY
        base["failure_reason"] = "non-positive price"
        return base

    age_min = max(0.0, (now_utc - ts).total_seconds() / 60.0)
    base["age_minutes"] = round(age_min, 1)
    base["price"] = price_f
    if age_min > max_age:
        base["status"] = PRICE_STALE
        base["failure_reason"] = (
            f"age {age_min:.0f}m exceeds {max_age}m for state={state}"
        )
        return base

    base["valid_price"] = True
    base["status"] = (
        DEGRADED_MARKET_STATE_UNKNOWN if state == "UNKNOWN" else LIVE_PRICE_VERIFIED
    )
    return base


def _country_fallback(ticker: str) -> str | None:
    """Bare (no-suffix) tickers are US-listed in this basket."""
    return "United States" if "." not in str(ticker) else None


def _stamp_source_row(row: dict[str, Any]) -> dict[str, Any]:
    """Attach the advisory-only safety stamps to a single canary source row.

    Mutates and returns ``row``.  A canary price mark is advisory context
    only: it can never trade, never sizes real money, and the provider's
    execution permission is WATCH_ONLY.
    """
    row["advisory_only"] = True
    row["execution_gate"] = "LOCKED"
    row["broker_api_called"] = False
    row["ai_execution_count"] = 0
    row["decision_impact"] = "ADVISORY_CONTEXT_ONLY"
    row["execution_permission"] = "WATCH_ONLY"
    return row


def probe_prices(
    tickers: Mapping[str, str],
    *,
    allow_network: bool = False,
    transports: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Probe each ticker through the resolved read-only price provider.

    Returns a dict with the resolver diagnostics (secret-safe) and a per-ticker
    result list. With neither network nor an injected transport, every ticker
    is honestly NETWORK_DISABLED.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    resolved = resolve_price_provider(
        allow_network=allow_network, env=env, transports=transports
    )
    callable_ = resolved.get("callable")
    results: list[dict[str, Any]] = []
    for ticker in tickers:
        if callable_ is None:
            country = T_CANARY.get(ticker) or country_from_ticker(ticker) or _country_fallback(ticker)
            results.append(
                {
                    "ticker": ticker,
                    "country": country,
                    "valid_price": False,
                    "price": None,
                    "currency": None,
                    "age_minutes": None,
                    "market_state": None,
                    "provider_selected": None,
                    "status": resolved.get("status") or NETWORK_DISABLED,
                    "failure_reason": "no selectable read-only provider",
                }
            )
            continue
        try:
            mark = callable_(ticker)
        except Exception as exc:  # noqa: BLE001 - per-symbol failure is safe
            results.append(
                {
                    "ticker": ticker,
                    "country": T_CANARY.get(ticker),
                    "valid_price": False,
                    "price": None,
                    "currency": None,
                    "age_minutes": None,
                    "market_state": None,
                    "provider_selected": resolved.get("provider"),
                    "status": "PRICE_PROVIDER_ERROR",
                    "failure_reason": f"{type(exc).__name__}",
                }
            )
            continue
        results.append(evaluate_mark(ticker, mark, now_utc))
    return {
        "provider_resolved": resolved.get("provider"),
        "resolver_status": resolved.get("status"),
        "allow_network": bool(allow_network),
        "configured_providers": resolved.get("configured_providers"),
        "results": results,
    }


def _load_payload() -> dict[str, Any]:
    """Load the live daily payload subset the coverage builder consumes."""
    payload: dict[str, Any] = {}
    mapping = {
        "price_movers": "today_price_movers.json",
        "news_events": "today_news_events.json",
        "filings_events": "today_filings_events.json",
    }
    for key, fname in mapping.items():
        path = DAILY_PAYLOAD_DIR / fname
        if path.exists():
            try:
                payload[key] = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                payload[key] = {}
        else:
            payload[key] = {}
    return payload


def compute_canary(
    *,
    allow_network: bool = False,
    transports: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Run the full canary: probe prices, compute H coverage + REAL_RUN proof."""
    now_utc = now_utc or datetime.now(timezone.utc)
    # Union basket, preserving declared countries.
    basket: dict[str, str] = {}
    basket.update(T_CANARY)
    basket.update(HOLDINGS_H)
    basket.update(UK_TICKERS)

    probe = probe_prices(
        basket, allow_network=allow_network, transports=transports,
        env=env, now_utc=now_utc,
    )
    # Stamp every nested provider/source row with the advisory-only safety
    # posture.  A price read NEVER trades, so each row is decision-impacting
    # only as advisory context and carries WATCH_ONLY execution permission.
    for row in probe["results"]:
        _stamp_source_row(row)
    by_ticker = {r["ticker"]: r for r in probe["results"]}

    # --- Holdings H price coverage ------------------------------------------
    holdings_rows = []
    valid_holdings = 0
    for ticker, country in HOLDINGS_H.items():
        r = by_ticker.get(ticker, {})
        valid = bool(r.get("valid_price"))
        valid_holdings += 1 if valid else 0
        holdings_rows.append(
            {
                "ticker": ticker,
                "country": country,
                "provider_attempted": probe["provider_resolved"] or "none",
                "provider_selected": r.get("provider_selected"),
                "valid_price": valid,
                "price": r.get("price"),
                "currency": r.get("currency"),
                "age_minutes": r.get("age_minutes"),
                "status": r.get("status"),
                "failure_reason": r.get("failure_reason"),
            }
        )
    h_price_coverage = round(valid_holdings / max(1, len(HOLDINGS_H)), 4)

    # --- Real price_rows feeding the coverage proof -------------------------
    price_rows = [
        {"ticker": r["ticker"], "country": r.get("country"), "valid_price": True}
        for r in probe["results"]
        if r.get("valid_price")
    ]
    payload = _load_payload()
    proof = build_proof_from_payload(
        payload,
        price_rows=price_rows,
        mapping_rows=[],  # no fabricated mappings — real mapping evidence only
        target_countries=DEFAULT_TARGET_COUNTRIES,
        run_timestamp_utc=now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        proof_kind="REAL_RUN",
    )

    existing_risk_visibility_ok = h_price_coverage >= 0.80
    c_price = proof.get("C_price", 0.0)
    c_global = proof.get("C_global", 0.0)
    # Advisory/paper-candidate permission ONLY — never unlocks execution.
    new_risk_allowed = bool(
        existing_risk_visibility_ok
        and c_price >= 0.10
        and c_global > 0
    )

    report = {
        "report": "kante_real_provider_canary",
        "generated_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "allow_network": bool(allow_network),
        "mode": "MOCK" if transports else ("NETWORK" if allow_network else "SKIP_NETWORK"),
        "provider_priority": list(PRICE_PROVIDER_PRIORITY),
        "configured_providers": probe["configured_providers"],
        "resolver_status": probe["resolver_status"],
        "provider_resolved": probe["provider_resolved"],
        "canary_results": probe["results"],
        "holdings_coverage": {
            "rows": holdings_rows,
            "H_price_coverage": h_price_coverage,
            "valid_count": valid_holdings,
            "total": len(HOLDINGS_H),
            "existing_risk_visibility_ok": existing_risk_visibility_ok,
        },
        "coverage_proof": proof,
        "new_risk_allowed": new_risk_allowed,
        "advisory_only": True,
        "human_review_required": True,
        "human_execution_required": True,
        "executable_allowed": False,
        # Explicit real-money / operator-execution prohibitions (Kanté
        # continuation sprint, Workstream A).  These are unconditional.
        "real_money_sizing_impact": "PROHIBITED",
        "real_money_weight_allowed": False,
        "operator_execution_required": True,
        "external_adapter_execution_permission": "WATCH_ONLY",
        "external_adapter_decision_power": "EVIDENCE_ONLY",
        "proof_status": "ADVISORY_ONLY_CANARY_ARTIFACT",
        # Top-level advisory safety stamps (execution_gate / broker_api_called /
        # ai_execution_count / ...) so the strict release-artifact coherence gate
        # recognises this artifact as canonically stamped.
        **advisory_safety_stamps(),
        "safety": advisory_safety_stamps(),
    }
    # Defensive secret-leak guard over the whole rendered report.
    secret_values = collect_secret_values(
        [v for v in PROVIDER_ENV.values() if v], env=env
    )
    report["secret_leak_check_passed"] = assert_no_secret(report, secret_values)
    return report


def write_report(report: dict[str, Any], path: Path | None = None) -> Path:
    target = path or CANARY_REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    tmp.replace(target)
    return target


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kante_real_provider_canary.py",
        description=(
            "Read-only real-provider price canary + REAL_RUN coverage proof. "
            "Network OFF by default; advisory-only; never trades."
        ),
    )
    p.add_argument("--allow-network", action="store_true",
                   help="opt in to real read-only network fetches (Yahoo public)")
    p.add_argument("--use-mock-providers", action="store_true",
                   help="use the deterministic offline mock transport (no network)")
    p.add_argument("--write", action="store_true",
                   help="persist runtime/release/kante_real_provider_canary.json")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    transports = None
    if args.use_mock_providers:
        transports = {"yahoo": build_mock_price_transport()}
    report = compute_canary(
        allow_network=args.allow_network and not args.use_mock_providers,
        transports=transports,
    )
    if args.write:
        write_report(report)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        hp = report["holdings_coverage"]
        proof = report["coverage_proof"]
        print(f"kante_real_provider_canary — mode={report['mode']}")
        print(f"  resolver_status   : {report['resolver_status']}")
        print(f"  provider_resolved : {report['provider_resolved']}")
        print(f"  H_price_coverage  : {hp['H_price_coverage']} "
              f"({hp['valid_count']}/{hp['total']})")
        print(f"  C_price           : {proof.get('C_price')}")
        print(f"  C_global          : {proof.get('C_global')} "
              f"(covered={proof.get('covered_country_count')})")
        print(f"  new_risk_allowed  : {report['new_risk_allowed']}")
        print(f"  secret_leak_check : {'PASS' if report['secret_leak_check_passed'] else 'FAIL'}")
        for r in report["canary_results"]:
            if r["ticker"] in T_CANARY:
                print(f"    {r['ticker']:12s} valid={int(bool(r['valid_price']))} "
                      f"status={r['status']:24s} "
                      f"px={r['price']} {r['currency'] or ''}")
    return 0 if report["secret_leak_check_passed"] else 2


__all__ = [
    "T_CANARY", "HOLDINGS_H", "UK_TICKERS",
    "CANARY_REPORT_PATH",
    "market_state", "max_age_minutes_for", "evaluate_mark",
    "probe_prices", "compute_canary", "write_report",
]


if __name__ == "__main__":
    raise SystemExit(main())
