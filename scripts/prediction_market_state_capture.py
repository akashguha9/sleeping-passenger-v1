"""Prediction-market daily state capture — the longitudinal dataset writer.

Fixes the root cause found in the data-pipeline forensics: probability
observations were only ever written once (2026-07-02, manual run) because
NOTHING scheduled appends to the ledger — signal_events dedups PM rows,
destroying the time series.  This module is invoked by the every-6-hour
refresh wrapper and appends the state of the world AS OBSERVED at time t:

1. **Probability observations** → ``data/calibration_corpus/
   pm_probability_ledger.jsonl`` (append-only; exact-duplicate guard on
   (venue, market_ticker, observed_at); prior observations are NEVER
   rewritten — the series builder collapses intraday polls).
2. **Frozen event→equity exposure map version** → ``data/exposure_maps/
   frozen/`` via the shock engine's hash-chained freeze (a new version is
   written ONLY when the curated map's content changed; history is never
   replaced).  When no curated map exists the capture reports
   NO_CURATED_MAP honestly and writes a schema template for the operator.
3. **Contemporaneous close prices** for mapped tickers (read-only from
   canonical SQLite) so future returns can be aligned to frozen beliefs.

Provider discipline (one provider failing must never destroy the day's
capture): every provider outcome is classified as one of

    OK / AUTH_FAILED / RATE_LIMITED / TIMEOUT / MALFORMED_RESPONSE /
    NO_DATA / UNKNOWN

Public read-only endpoints only; no secrets required, none read.
Advisory-only: no broker, no execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_REPO = Path(__file__).resolve().parents[1]
import sys
if str(_REPO) not in sys.path:  # direct `python scripts/...` invocation
    sys.path.insert(0, str(_REPO))

LEDGER_PATH = _REPO / "data" / "calibration_corpus" / "pm_probability_ledger.jsonl"
EXPOSURE_MAP_CURATED = _REPO / "data" / "exposure_maps" / "current_event_equity_map.json"
EXPOSURE_FROZEN_DIR = _REPO / "data" / "exposure_maps" / "frozen"
PRICE_SNAPSHOT_DIR = _REPO / "data" / "calibration_corpus" / "price_snapshots"
SUMMARY_PATH = _REPO / "runtime" / "pm_state_capture_summary.json"
DB_PATH = _REPO / "runtime" / "mvp_local.db"

# The unfiltered /markets page returns thousands of unpriced shard
# markets (last_price None) — the liquid, economically relevant series
# must be polled explicitly.  Pre-registered macro/policy series only
# (same series the original 2026-07-02 ledger observed; esports/
# cross-category shards are quarantined by kalshi_category_governance).
KALSHI_SERIES: tuple[str, ...] = ("KXCPIYOY", "KXFED", "KXFEDDECISION")
KALSHI_MARKETS_URL_TMPL = (
    "https://api.elections.kalshi.com/trade-api/v2/markets"
    "?limit=200&status=open&series_ticker={series}")
POLYMARKET_GAMMA_URL = (
    "https://gamma-api.polymarket.com/markets"
    "?limit=200&active=true&closed=false")
_POLYMARKET_CAPTURE_LIMIT = 200


def _polymarket_default_fetch() -> Any:
    """Fetch via the EXISTING working ingestion client (requests session +
    retries/backoff — the same path the 6-hour refresh uses successfully).

    The client's deterministic mock fallback is explicitly bypassed: a
    research ledger must never receive mock rows, so an exhausted-retries
    None becomes a raised error (classified upstream), not fake data.
    """
    from src.ingestion.polymarket_public_client import PolymarketPublicClient

    client = PolymarketPublicClient()
    payload = client._request_json(  # noqa: SLF001 — raw payload required
        f"{client.gamma_base_url}/markets",
        params={"limit": _POLYMARKET_CAPTURE_LIMIT,
                "closed": "false", "active": "true"})
    if payload is None:
        raise ConnectionError(
            "polymarket gamma request failed after client retries "
            "(mock fallback deliberately not used for the research ledger)")
    return payload

# Provider status classification (sprint contract).
OK = "OK"
AUTH_FAILED = "AUTH_FAILED"
RATE_LIMITED = "RATE_LIMITED"
TIMEOUT = "TIMEOUT"
MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
NO_DATA = "NO_DATA"
UNKNOWN = "UNKNOWN"

NO_CURATED_MAP = "NO_CURATED_MAP"
OBSERVED = "OBSERVED"

_TIMEOUT_S = 20


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_http_failure(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return AUTH_FAILED
        if exc.code == 429:
            return RATE_LIMITED
        return UNKNOWN
    if isinstance(exc, (TimeoutError, ConnectionError)):
        # Connection resets are transient-network class, not structural:
        # they must retry on the next scheduled cycle, never demote the
        # provider permanently.
        return TIMEOUT
    if isinstance(exc, urllib.error.URLError):
        reason = str(getattr(exc, "reason", "")).lower()
        return TIMEOUT if "timed out" in reason else UNKNOWN
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return MALFORMED_RESPONSE
    return UNKNOWN


def _http_get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={
        "User-Agent": "sleeping-passenger-research/1.0 (read-only)"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _rules_hash(*parts: Any) -> str:
    blob = json.dumps([p for p in parts if p], sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _obs_id(venue: str, ticker: str, observed_at: str) -> str:
    return hashlib.sha256(
        f"{venue}|{ticker}|{observed_at}".encode("utf-8")).hexdigest()[:16]


def _kalshi_price(m: dict[str, Any], cents_key: str,
                  dollars_key: str) -> float | None:
    """Kalshi price in [0, 1] from either API generation: integer cents
    (legacy ``last_price``) or string dollars (current
    ``last_price_dollars``)."""
    dollars = m.get(dollars_key)
    if dollars is not None:
        try:
            v = float(dollars)
        except (TypeError, ValueError):
            return None
        return v if 0.0 <= v <= 1.0 else None
    cents = m.get(cents_key)
    if cents is None:
        return None
    try:
        v = float(cents) / 100.0
    except (TypeError, ValueError):
        return None
    return v if 0.0 <= v <= 1.0 else None


def normalize_kalshi_markets(payload: Any, *, observed_at: str,
                             run_id: str) -> list[dict[str, Any]]:
    markets = (payload or {}).get("markets") or []
    rows = []
    for m in markets:
        ticker = m.get("ticker")
        p = _kalshi_price(m, "last_price", "last_price_dollars")
        if not ticker or p is None:
            continue
        bid = _kalshi_price(m, "yes_bid", "yes_bid_dollars")
        ask = _kalshi_price(m, "yes_ask", "yes_ask_dollars")
        rows.append({
            "observation_id": _obs_id("kalshi", ticker, observed_at),
            "venue": "kalshi",
            "market_ticker": ticker,
            "event_ticker": m.get("event_ticker"),
            "title": m.get("title") or m.get("yes_sub_title"),
            "rules_hash": _rules_hash(m.get("rules_primary"),
                                      m.get("rules_secondary"),
                                      m.get("expiration_time")),
            "resolution_close_time": m.get("close_time"),
            "p": round(p, 4),
            "bid": None if bid is None else round(bid, 4),
            "ask": None if ask is None else round(ask, 4),
            "spread": None if bid is None or ask is None
            else round(ask - bid, 4),
            "volume": m.get("volume") or m.get("volume_fp"),
            "open_interest": m.get("open_interest")
            or m.get("open_interest_fp"),
            "liquidity": m.get("liquidity") or m.get("liquidity_dollars"),
            "observed_at": observed_at,
            "adapter_run_id": run_id,
            "settled_source": "kalshi_public_market_endpoint",
            "epistemic_label": OBSERVED,
            "advisory_status": "ADVISORY_ONLY",
        })
    return rows


def normalize_polymarket_markets(payload: Any, *, observed_at: str,
                                 run_id: str) -> list[dict[str, Any]]:
    markets = payload if isinstance(payload, list) else []
    rows = []
    for m in markets:
        cid = m.get("conditionId") or m.get("id")
        prices = m.get("outcomePrices")
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except ValueError:
                prices = None
        if not cid or not prices:
            continue
        try:
            p_yes = float(prices[0])
        except (TypeError, ValueError, IndexError):
            continue
        if not 0.0 <= p_yes <= 1.0:
            continue
        rows.append({
            "observation_id": _obs_id("polymarket", str(cid), observed_at),
            "venue": "polymarket",
            "market_ticker": str(cid),
            "event_ticker": m.get("slug"),
            "title": m.get("question"),
            "rules_hash": _rules_hash(m.get("description"),
                                      m.get("endDate")),
            "resolution_close_time": m.get("endDate"),
            "p": round(p_yes, 4),
            "bid": None, "ask": None, "spread": m.get("spread"),
            "volume": m.get("volumeNum") or m.get("volume"),
            "open_interest": None,
            "liquidity": m.get("liquidityNum") or m.get("liquidity"),
            "observed_at": observed_at,
            "adapter_run_id": run_id,
            "settled_source": "polymarket_gamma_endpoint",
            "epistemic_label": OBSERVED,
            "advisory_status": "ADVISORY_ONLY",
        })
    return rows


def _existing_observation_keys(ledger_path: Path) -> set[str]:
    keys: set[str] = set()
    if not ledger_path.exists():
        return keys
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        keys.add(f"{r.get('venue')}|{r.get('market_ticker')}|"
                 f"{r.get('observed_at')}")
    return keys


def append_observations(rows: list[dict[str, Any]], *,
                        ledger_path: Path = LEDGER_PATH) -> dict[str, Any]:
    """Append-only write with exact-duplicate suppression.

    Existing lines are never modified; a row whose (venue, market_ticker,
    observed_at) already exists is skipped, not rewritten.
    """
    existing = _existing_observation_keys(ledger_path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    appended = 0
    duplicates = 0
    with ledger_path.open("a", encoding="utf-8") as fh:
        for r in rows:
            key = (f"{r.get('venue')}|{r.get('market_ticker')}|"
                   f"{r.get('observed_at')}")
            if key in existing:
                duplicates += 1
                continue
            existing.add(key)
            fh.write(json.dumps(r, default=str) + "\n")
            appended += 1
    return {"appended": appended, "duplicates_skipped": duplicates,
            "ledger_path": str(ledger_path)}


def capture_provider(name: str, fetch: Callable[[], Any],
                     normalize: Callable[..., list[dict[str, Any]]], *,
                     observed_at: str, run_id: str) -> dict[str, Any]:
    """Fetch + normalize one provider with full failure isolation."""
    try:
        payload = fetch()
    except Exception as exc:  # noqa: BLE001 — classify, never crash the day
        return {"provider": name, "status": classify_http_failure(exc),
                "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                "rows": []}
    try:
        rows = normalize(payload, observed_at=observed_at, run_id=run_id)
    except Exception as exc:  # noqa: BLE001
        return {"provider": name, "status": MALFORMED_RESPONSE,
                "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                "rows": []}
    if not rows:
        return {"provider": name, "status": NO_DATA, "rows": []}
    return {"provider": name, "status": OK, "rows": rows}


# --- frozen exposure map ------------------------------------------------------

_MAP_TEMPLATE = {
    "doctrine": "OPERATOR-CURATED event->equity exposure map. Every entry "
                "must cite evidence. This file is SNAPSHOT INPUT: the "
                "capture freezes a hash-chained version whenever content "
                "changes; frozen history is never rewritten.",
    "entries": [
        {"event_id": "<kalshi event_ticker or watch event_id>",
         "ticker": "<exchange ticker>", "company": "<name>",
         "direction": "<+1 benefits | -1 harmed>",
         "exposure": "<0..1>", "exposure_confidence": "<0..1>",
         "hop": "<0 direct, 1 first-order, 2 second-order, 3+ later>",
         "chain_position": "<UPSTREAM|MIDSTREAM|DOWNSTREAM>",
         "expected_lag_days": "<int>",
         "filing_confirmation": "<NONE|WEAK|STRONG>",
         "capture_rate": "<0..1 Porter value-capture proxy, optional>",
         "narrative_state": "<OLD|TRANSITION|NEW, optional>",
         "rationale": "<why>", "evidence_ref": "<citation — REQUIRED>"}
    ],
}


def _latest_frozen(frozen_dir: Path) -> dict[str, Any] | None:
    if not frozen_dir.exists():
        return None
    files = sorted(frozen_dir.glob("event_equity_map_v*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def freeze_exposure_map(*, curated_path: Path = EXPOSURE_MAP_CURATED,
                        frozen_dir: Path = EXPOSURE_FROZEN_DIR,
                        run_date_day: int, author: str = "state_capture",
                        ) -> dict[str, Any]:
    """Freeze the curated map as a new hash-chained version when changed.

    Never overwrites: versions are monotonically numbered files; the
    chain links via prev_hash (prediction_market_shock_engine custody).
    """
    from scripts.prediction_market_shock_engine import (
        canonical_map_hash,
        freeze_event_equity_map,
    )
    if not curated_path.exists():
        curated_path.parent.mkdir(parents=True, exist_ok=True)
        template_path = curated_path.with_name("TEMPLATE_event_equity_map.json")
        if not template_path.exists():
            template_path.write_text(
                json.dumps(_MAP_TEMPLATE, indent=2), encoding="utf-8")
        return {"status": NO_CURATED_MAP,
                "operator_action": f"curate {curated_path} using "
                                   f"{template_path.name}; every entry "
                                   "needs evidence_ref"}
    try:
        curated = json.loads(curated_path.read_text(encoding="utf-8"))
        entries = curated.get("entries") or []
    except ValueError as exc:
        return {"status": MALFORMED_RESPONSE, "error": str(exc)[:160]}
    cited = [e for e in entries if e.get("evidence_ref")]
    dropped = len(entries) - len(cited)
    if not cited:
        return {"status": NO_DATA, "dropped_uncited": dropped,
                "reason": "curated map has no cited entries"}
    latest = _latest_frozen(frozen_dir)
    version = 1 if latest is None else int(latest.get("version", 0)) + 1
    prev_hash = None if latest is None else latest.get("content_hash")
    frozen = freeze_event_equity_map(
        cited, author=author, created_day=run_date_day,
        version=version, prev_hash=prev_hash)
    if latest is not None:
        prev_body_hash = canonical_map_hash(
            {k: v for k, v in latest.items()
             if k not in ("content_hash", "version", "prev_hash",
                          "created_day")})
        new_body_hash = canonical_map_hash(
            {k: v for k, v in frozen.items()
             if k not in ("content_hash", "version", "prev_hash",
                          "created_day")})
        if prev_body_hash == new_body_hash:
            return {"status": "UNCHANGED", "version": latest.get("version"),
                    "content_hash": latest.get("content_hash"),
                    "dropped_uncited": dropped}
    frozen_dir.mkdir(parents=True, exist_ok=True)
    out = frozen_dir / f"event_equity_map_v{version:05d}.json"
    if out.exists():
        return {"status": "VERSION_COLLISION", "path": str(out)}
    out.write_text(json.dumps(frozen, indent=2, default=str),
                   encoding="utf-8")
    return {"status": OK, "version": version, "path": str(out),
            "entries": len(cited), "dropped_uncited": dropped,
            "content_hash": frozen.get("content_hash")}


def snapshot_mapped_prices(tickers: list[str], *, run_date: str,
                           db_path: Path = DB_PATH,
                           out_dir: Path = PRICE_SNAPSHOT_DIR,
                           ) -> dict[str, Any]:
    """Persist the latest known close per mapped ticker (append-only file
    per day; existing files are never rewritten)."""
    if not tickers:
        return {"status": NO_DATA, "tickers": 0}
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"mapped_prices_{run_date}.json"
    if out.exists():
        return {"status": "ALREADY_CAPTURED", "path": str(out)}
    from scripts.quant_return_engine import load_close_series
    closes = load_close_series(db_path, min_days=1)
    rows = {}
    for t in tickers:
        series = closes.get(t)
        if not series:
            rows[t] = {"status": NO_DATA}
            continue
        last_day = max(series)
        rows[t] = {"status": OK, "close": series[last_day],
                   "bar_date": last_day}
    out.write_text(json.dumps({"run_date": run_date, "prices": rows},
                              indent=2), encoding="utf-8")
    return {"status": OK, "path": str(out), "tickers": len(tickers)}


def run_state_capture(*, write: bool,
                      kalshi_fetch: Callable[[], Any] | None = None,
                      polymarket_fetch: Callable[[], Any] | None = None,
                      ledger_path: Path = LEDGER_PATH,
                      now_iso: str | None = None) -> dict[str, Any]:
    observed_at = now_iso or _utc_now()
    run_date = observed_at[:10]
    run_id = f"capture-{observed_at.replace(':', '').replace('-', '')[:15]}"
    def _kalshi_default_fetch() -> dict[str, Any]:
        merged: list[dict[str, Any]] = []
        for series in KALSHI_SERIES:
            payload = _http_get_json(
                KALSHI_MARKETS_URL_TMPL.format(series=series))
            merged.extend((payload or {}).get("markets") or [])
        return {"markets": merged}

    kfetch = kalshi_fetch or _kalshi_default_fetch
    pfetch = polymarket_fetch or _polymarket_default_fetch

    providers = [
        capture_provider("kalshi", kfetch, normalize_kalshi_markets,
                         observed_at=observed_at, run_id=run_id),
        capture_provider("polymarket", pfetch, normalize_polymarket_markets,
                         observed_at=observed_at, run_id=run_id),
    ]
    all_rows = [r for p in providers for r in p["rows"]]
    ledger_result: dict[str, Any] = {"appended": 0, "duplicates_skipped": 0}
    if write and all_rows:
        ledger_result = append_observations(all_rows,
                                            ledger_path=ledger_path)

    day_ordinal = datetime.fromisoformat(
        observed_at.replace("Z", "+00:00")).date().toordinal()
    frozen = freeze_exposure_map(run_date_day=day_ordinal) if write else {
        "status": "DRY_RUN"}
    mapped_tickers = []
    if frozen.get("status") == OK:
        doc = json.loads(Path(frozen["path"]).read_text(encoding="utf-8"))
        mapped_tickers = sorted({e["ticker"] for e in doc.get("entries", [])})
    prices = snapshot_mapped_prices(mapped_tickers, run_date=run_date) \
        if write and mapped_tickers else {"status": NO_DATA, "tickers": 0}

    summary = {
        "run_id": run_id, "observed_at": observed_at, "write": write,
        "providers": [{k: v for k, v in p.items() if k != "rows"}
                      | {"row_count": len(p["rows"])} for p in providers],
        "ledger": ledger_result,
        "frozen_exposure_map": frozen,
        "price_snapshot": prices,
        "advisory_status": "ADVISORY_ONLY",
        "signal_class": "RESEARCH_DATA_CAPTURE",
    }
    if write:
        SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        SUMMARY_PATH.write_text(json.dumps(summary, indent=2, default=str),
                                encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True)
    mode.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    summary = run_state_capture(write=bool(args.write))
    print(json.dumps({
        "providers": summary["providers"],
        "ledger": summary["ledger"],
        "frozen_exposure_map": summary["frozen_exposure_map"].get("status"),
    }, indent=2, default=str))
    # Partial capture is still a pass — provider isolation by design; only
    # a totally empty day with all providers erroring is a failure signal.
    statuses = {p["status"] for p in summary["providers"]}
    return 0 if statuses & {OK, NO_DATA} else 1


if __name__ == "__main__":
    raise SystemExit(main())
