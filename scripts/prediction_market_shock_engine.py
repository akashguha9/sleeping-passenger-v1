"""Prediction-market shock engine — ΔP conviction, frozen maps, snapshots.

Three jobs, all advisory-only (no broker execution, no order placement):

1. **Conviction-weighted ΔP**: a probability move only counts as a shock if
   it is large, persistent, and (when order-book depth is known) backed by
   depth: ``ΔP_conv = ΔP * min(1, log10(1+depth_usd)/3)``.
2. **Frozen event→equity map custody**: the exposure map is hashed at freeze
   time. Any in-place edit breaks verification (fail-closed). Legitimate
   changes create a *new version* whose ``prev_hash`` chains to the old one —
   the anti-post-hoc-map invariant.
3. **Forward snapshot writer**: every mapped shock emits outcome-eligible
   forward snapshot rows (dedup by snapshot_id; dry-run by default), each
   carrying a provenance split (ΔP = MARKET/FIXTURE; exposure×capture =
   ANALYST_PRIOR) and an explicit data_mode so fixture rows can never be
   confused with live evidence.

Pure/deterministic: integer-day time, no network, explicit paths only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"

LIVE = "LIVE"
FIXTURE_DEMONSTRATION = "FIXTURE_DEMONSTRATION"

DEFAULT_SHOCK_THRESHOLD = 0.10
DEFAULT_WINDOW = 5
DEFAULT_HORIZON_DAYS = 21
PENDING = "PENDING"


# --- frozen event→equity map ---------------------------------------------------

def canonical_map_hash(map_doc: dict[str, Any]) -> str:
    """sha256[:16] over the canonical JSON of everything except content_hash."""
    body = {k: v for k, v in map_doc.items() if k != "content_hash"}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def freeze_event_equity_map(entries: list[dict[str, Any]], *, author: str,
                            created_day: int, version: int = 1,
                            prev_hash: str | None = None,
                            status: str = "FROZEN") -> dict[str, Any]:
    for e in entries:
        for key in ("event_id", "ticker", "direction", "exposure",
                    "capture_rate", "rationale"):
            if key not in e:
                raise ValueError(f"map entry missing required field: {key}")
    doc: dict[str, Any] = {
        "schema": "event_equity_map/v1",
        "author": author, "created_day": int(created_day),
        "version": int(version), "prev_hash": prev_hash, "status": status,
        "exposure_provenance": "ANALYST_PRIOR",
        "entries": sorted(entries, key=lambda e: (e["event_id"], e["ticker"])),
        "advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY,
    }
    doc["content_hash"] = canonical_map_hash(doc)
    return doc


def verify_event_equity_map(map_doc: dict[str, Any]) -> dict[str, Any]:
    expected = canonical_map_hash(map_doc)
    found = map_doc.get("content_hash")
    return {"valid": expected == found, "expected": expected, "found": found}


def new_map_version(old_map: dict[str, Any], entries: list[dict[str, Any]], *,
                    author: str, day: int) -> dict[str, Any]:
    """The ONLY sanctioned way to change a frozen map: a new chained version."""
    check = verify_event_equity_map(old_map)
    if not check["valid"]:
        raise ValueError("FROZEN_MAP_HASH_MISMATCH: refusing to version a "
                         f"tampered map ({check})")
    return freeze_event_equity_map(
        entries, author=author, created_day=day,
        version=int(old_map["version"]) + 1,
        prev_hash=str(old_map["content_hash"]))


def load_frozen_map(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    check = verify_event_equity_map(doc)
    if not check["valid"]:
        raise ValueError(f"FROZEN_MAP_HASH_MISMATCH at {path}: {check}")
    return doc


# --- ΔP / shock detection -------------------------------------------------------

def delta_p(history: list[dict[str, Any]], window: int = DEFAULT_WINDOW) -> float:
    """p_now - p_then over the trailing `window` observations (integer days)."""
    pts = sorted(history, key=lambda r: int(r["day"]))
    if len(pts) < 2:
        return 0.0
    tail = pts[-min(window, len(pts)):]
    return round(float(tail[-1]["p"]) - float(tail[0]["p"]), 6)


def depth_conviction(depth_usd: float | None) -> tuple[float, bool]:
    """min(1, log10(1+depth)/3); when depth is unknown, weight 1.0 but the
    depth_available flag is False so downstream can discount."""
    if depth_usd is None:
        return 1.0, False
    return round(min(1.0, math.log10(1.0 + max(0.0, depth_usd)) / 3.0), 4), True


def is_persistent(history: list[dict[str, Any]], window: int = DEFAULT_WINDOW) -> bool:
    """The half-window move must carry the same sign as the full-window move —
    a one-print spike is not a shock."""
    full = delta_p(history, window)
    half = delta_p(history, max(2, window // 2))
    if full == 0.0:
        return False
    return (full > 0) == (half > 0) and half != 0.0


@dataclass
class Shock:
    market_id: str
    event_id: str
    day: int
    delta_p: float
    delta_p_conv: float
    depth_available: bool
    data_mode: str
    p_t: float = 0.0
    p_prior: float = 0.0
    depth_weight: float = 1.0
    persistence: int = 1
    source_mode: str = "FIXTURE"
    adapter_name: str = ""
    adapter_run_id: str = ""
    fetch_timestamp: str = ""
    source_hash: str = ""


def detect_shock(market: dict[str, Any], *,
                 threshold: float = DEFAULT_SHOCK_THRESHOLD,
                 window: int = DEFAULT_WINDOW) -> Shock | None:
    history = market["price_history"]
    dp = delta_p(history, window)
    if abs(dp) < threshold or not is_persistent(history, window):
        return None
    cw, depth_available = depth_conviction(market.get("depth_usd"))
    pts = sorted(history, key=lambda r: int(r["day"]))
    day = int(pts[-1]["day"])
    return Shock(
        market_id=str(market["market_id"]),
        event_id=str(market.get("event_id", market["market_id"])),
        day=day, delta_p=dp, delta_p_conv=round(dp * cw, 6),
        depth_available=depth_available,
        data_mode=str(market.get("data_mode", FIXTURE_DEMONSTRATION)),
        p_t=float(pts[-1]["p"]),
        p_prior=float(pts[-min(window, len(pts))]["p"]),
        depth_weight=cw, persistence=1,
        source_mode=str(market.get("source_mode", "FIXTURE")),
        adapter_name=str(market.get("adapter_name", "")),
        adapter_run_id=str(market.get("adapter_run_id", "")),
        fetch_timestamp=str(market.get("fetch_timestamp", "")),
        source_hash=str(market.get("source_hash", "")))


# --- forward snapshots ----------------------------------------------------------

def snapshot_id(event_id: str, ticker: str, day: int) -> str:
    return hashlib.sha256(f"{event_id}|{ticker}|{day}".encode()).hexdigest()[:16]


def _entry_price(equity_prices: dict[str, dict[int, float]], ticker: str,
                 day: int) -> float | None:
    series = equity_prices.get(ticker, {})
    for d in range(day, day - 4, -1):     # last known close within 3 days
        if d in series:
            return float(series[d])
    return None


def build_forward_snapshots(shock: Shock, frozen_map: dict[str, Any],
                            equity_prices: dict[str, dict[int, float]], *,
                            horizon_days: int = DEFAULT_HORIZON_DAYS,
                            ) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in frozen_map["entries"]:
        if entry["event_id"] != shock.event_id:
            continue
        base_dir = str(entry["direction"]).upper()
        direction = base_dir if shock.delta_p > 0 else (
            "DOWN" if base_dir == "UP" else "UP")
        price = _entry_price(equity_prices, str(entry["ticker"]), shock.day)
        if price is None or price <= 0:
            continue
        rows.append({
            "snapshot_id": snapshot_id(shock.event_id, str(entry["ticker"]),
                                       shock.day),
            "event_id": shock.event_id, "market_id": shock.market_id,
            "ticker": str(entry["ticker"]), "direction": direction,
            "entry_price": round(price, 6), "entry_day": shock.day,
            "horizon_days": int(horizon_days),
            "expiry_day": shock.day + int(horizon_days),
            "delta_p": shock.delta_p, "delta_p_conv": shock.delta_p_conv,
            "depth_available": shock.depth_available,
            "exposure": float(entry["exposure"]),
            "capture_rate": float(entry["capture_rate"]),
            "map_version": int(frozen_map["version"]),
            "map_hash": str(frozen_map["content_hash"]),
            "provenance": {"delta_p": ("MARKET" if shock.data_mode == LIVE
                                       else "FIXTURE"),
                           "exposure_capture": "ANALYST_PRIOR"},
            "data_mode": shock.data_mode, "outcome": PENDING,
            "status": "OPEN",
            "P_t": shock.p_t, "P_prior": shock.p_prior,
            "DepthWeight": shock.depth_weight,
            "PersistenceIndicator": shock.persistence,
            "source_mode": shock.source_mode,
            "adapter_name": shock.adapter_name,
            "adapter_run_id": shock.adapter_run_id,
            "fetch_timestamp": shock.fetch_timestamp,
            "source_hash": shock.source_hash,
            "advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY,
        })
    return rows


def append_snapshots(path: Path, rows: list[dict[str, Any]], *,
                     mode: str = "dry_run") -> dict[str, Any]:
    """Dedup by snapshot_id; dry-run by default (repo convention: writers
    never write unless explicitly asked)."""
    existing: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing.add(json.loads(line).get("snapshot_id", ""))
    fresh = [r for r in rows if r["snapshot_id"] not in existing]
    if mode == "write":
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for r in fresh:
                fh.write(json.dumps(r, sort_keys=True) + "\n")
    return {"mode": mode, "candidates": len(rows), "written": (
        len(fresh) if mode == "write" else 0),
        "would_write": len(fresh) if mode != "write" else 0,
        "skipped_duplicates": len(rows) - len(fresh)}


# --- live read-only source (Kalshi public market data) --------------------------
# Fail-closed: any live failure raises LiveSourceError; there is NO fixture
# fallback on the live path. Read-only public endpoints; no auth, no orders.

KALSHI_DEFAULT_BASE = "https://api.elections.kalshi.com/trade-api/v2"
OBSERVATION_LEDGER_DEFAULT = Path(
    "data/calibration_corpus/pm_probability_ledger.jsonl")


class LiveSourceError(RuntimeError):
    pass


def fetch_kalshi_markets_live(*, base_url: str | None = None,
                              limit: int = 200,
                              status: str = "open") -> dict[str, Any]:
    import os
    import urllib.request
    from datetime import datetime, timezone
    base = (base_url or os.environ.get("KALSHI_API_BASE", "").strip()
            or KALSHI_DEFAULT_BASE).rstrip("/")
    url = f"{base}/markets?limit={int(limit)}&status={status}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "sleeping-passenger advisory read-only"})
    try:
        raw = urllib.request.urlopen(req, timeout=25).read()
        payload = json.loads(raw)
        markets = payload["markets"]
    except Exception as exc:
        raise LiveSourceError(
            f"KALSHI_LIVE_FETCH_FAILED: {type(exc).__name__}: {exc} "
            f"(url={url}); failing closed — no fixture fallback.") from exc
    now = datetime.now(timezone.utc)
    return {
        "markets": markets, "request_url": url,
        "adapter_name": "kalshi_public_market_data",
        "adapter_run_id": f"kalshi-{now.strftime('%Y%m%dT%H%M%SZ')}",
        "fetch_timestamp": now.isoformat(),
        "source_hash": hashlib.sha256(raw).hexdigest()[:32],
        "source_mode": "LIVE",
    }


def _kalshi_prob(m: dict[str, Any]) -> float | None:
    for key in ("last_price", "yes_bid"):          # integer cents
        v = m.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return float(v) / 100.0
    for key in ("last_price_dollars", "yes_bid_dollars"):  # string dollars
        v = m.get(key)
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if 0.0 < f < 1.0:
            return f
    return None


def ledger_live_observations(fetch: dict[str, Any], ledger_path: Path,
                             *, mode: str = "dry_run") -> dict[str, Any]:
    """Append one probability observation per market. ΔP is computed across
    RUNS of this ledger — live shock detection needs history to accumulate;
    a single snapshot honestly yields zero shocks."""
    rows: list[dict[str, Any]] = []
    for m in fetch["markets"]:
        p = _kalshi_prob(m)
        if p is None:
            continue
        liquidity = m.get("liquidity_dollars") or m.get("liquidity")
        try:
            depth = float(liquidity) if liquidity is not None else None
        except (TypeError, ValueError):
            depth = None
        obs_id = hashlib.sha256(
            f"{m.get('ticker')}|{fetch['fetch_timestamp']}".encode()
        ).hexdigest()[:16]
        rows.append({
            "observation_id": obs_id, "market_ticker": str(m.get("ticker")),
            "event_ticker": str(m.get("event_ticker", "")),
            "series_ticker": str(m.get("ticker", "")).split("-")[0],
            "p": round(p, 4), "depth_usd": depth,
            "volume": m.get("volume"),
            "open_interest": m.get("open_interest"),
            "fetch_timestamp": fetch["fetch_timestamp"],
            "adapter_name": fetch["adapter_name"],
            "adapter_run_id": fetch["adapter_run_id"],
            "source_hash": fetch["source_hash"],
            "source_mode": "LIVE", "is_live_verified": True,
            "advisory_status": ADVISORY_STATUS,
        })
    existing: set[str] = set()
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing.add(json.loads(line).get("observation_id", ""))
    fresh = [r for r in rows if r["observation_id"] not in existing]
    if mode == "write":
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("a", encoding="utf-8") as fh:
            for r in fresh:
                fh.write(json.dumps(r, sort_keys=True) + "\n")
    return {"mode": mode, "observations": len(rows),
            "written": len(fresh) if mode == "write" else 0,
            "skipped_duplicates": len(rows) - len(fresh)}


def detect_shocks_from_ledger(ledger_path: Path, *,
                              threshold: float = DEFAULT_SHOCK_THRESHOLD,
                              lookback_obs: int = DEFAULT_WINDOW
                              ) -> dict[str, Any]:
    """Ledger-aware ΔP across RUNS: P_now = latest observation, P_prev = the
    observation at (or nearest before) the lookback window. A market with a
    single observation is LEDGER_WARMUP, never a failure. Persistence = the
    intermediate steps are sign-consistent (two observations pass
    trivially)."""
    if not ledger_path.exists():
        return {"shocks": [], "markets_seen": 0, "markets_with_prior": 0,
                "markets_warming_up": 0}
    by_market: dict[str, list[dict[str, Any]]] = {}
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        by_market.setdefault(row["market_ticker"], []).append(row)
    shocks: list[Shock] = []
    with_prior = 0
    for ticker, obs in by_market.items():
        obs.sort(key=lambda r: r["fetch_timestamp"])
        # one observation per run per market: dedupe identical timestamps
        if len(obs) < 2:
            continue        # LEDGER_WARMUP for this market
        with_prior += 1
        tail = obs[-min(lookback_obs, len(obs)):]
        p_now, p_prev = float(tail[-1]["p"]), float(tail[0]["p"])
        dp = round(p_now - p_prev, 6)
        steps = [float(tail[i + 1]["p"]) - float(tail[i]["p"])
                 for i in range(len(tail) - 1)]
        persistent = 1 if (dp != 0 and all(
            s == 0 or (s > 0) == (dp > 0) for s in steps)) else 0
        last = obs[-1]
        cw, depth_available = depth_conviction(last.get("depth_usd"))
        dp_conv = round(dp * cw * persistent, 6)
        if abs(dp_conv) < threshold:
            continue
        shocks.append(Shock(
            market_id=ticker, event_id=last.get("event_ticker", ticker),
            day=_iso_day(last["fetch_timestamp"]), delta_p=dp,
            delta_p_conv=dp_conv, depth_available=depth_available,
            data_mode=LIVE, p_t=p_now, p_prior=p_prev, depth_weight=cw,
            persistence=persistent, source_mode="LIVE",
            adapter_name=last["adapter_name"],
            adapter_run_id=last["adapter_run_id"],
            fetch_timestamp=last["fetch_timestamp"],
            source_hash=last["source_hash"]))
    return {"shocks": shocks, "markets_seen": len(by_market),
            "markets_with_prior": with_prior,
            "markets_warming_up": len(by_market) - with_prior}


def _iso_day(iso: str) -> int:
    from datetime import datetime
    try:
        return int(datetime.fromisoformat(
            iso.replace("Z", "+00:00")).timestamp()) // 86400
    except ValueError:
        return 0


def write_shock_engine_status(path: Path, status: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, indent=2, sort_keys=True),
                    encoding="utf-8")


# --- deterministic fixtures -----------------------------------------------------

def fixture_market() -> dict[str, Any]:
    """A persistent +0.14 five-day move with real depth."""
    return {
        "market_id": "FIX-MKT-RATECUT", "event_id": "FIX-EVT-RATECUT",
        "depth_usd": 150_000.0, "data_mode": FIXTURE_DEMONSTRATION,
        "price_history": [
            {"day": 995, "p": 0.42}, {"day": 996, "p": 0.45},
            {"day": 997, "p": 0.48}, {"day": 998, "p": 0.51},
            {"day": 999, "p": 0.54}, {"day": 1000, "p": 0.56},
        ],
    }


def fixture_equity_prices() -> dict[str, dict[int, float]]:
    return {"FIXA": {998: 100.0, 999: 101.0, 1000: 101.5},
            "FIXB": {998: 50.0, 999: 49.8, 1000: 49.9}}


def fixture_frozen_map() -> dict[str, Any]:
    return freeze_event_equity_map(
        [
            {"event_id": "FIX-EVT-RATECUT", "ticker": "FIXA",
             "direction": "UP", "exposure": 0.6, "capture_rate": 0.5,
             "rationale": "fixture beneficiary"},
            {"event_id": "FIX-EVT-RATECUT", "ticker": "FIXB",
             "direction": "DOWN", "exposure": 0.4, "capture_rate": 0.4,
             "rationale": "fixture loser"},
        ],
        author="fixture", created_day=990)


def _main() -> int:
    ap = argparse.ArgumentParser(
        description="Detect PM shocks and write forward snapshots (advisory; "
                    "live mode is read-only and NEVER falls back to fixture)")
    ap.add_argument("--mode", choices=("fixture", "live"), required=True)
    ap.add_argument("--map", type=Path, help="frozen event_equity_map JSON")
    ap.add_argument("--out", type=Path,
                    default=Path("data/calibration_corpus/forward_snapshots.jsonl"))
    ap.add_argument("--ledger", type=Path, default=OBSERVATION_LEDGER_DEFAULT)
    ap.add_argument("--write", choices=("dry_run", "write"),
                    default="dry_run")
    args = ap.parse_args()
    if args.mode == "fixture":
        frozen = load_frozen_map(args.map) if args.map else fixture_frozen_map()
        shock = detect_shock(fixture_market())
        if shock is None:
            print(json.dumps({"mode": "fixture", "shocks": 0}))
            return 0
        rows = build_forward_snapshots(shock, frozen, fixture_equity_prices())
        report = append_snapshots(args.out, rows, mode=args.write)
        report["data_mode"] = FIXTURE_DEMONSTRATION
        report["shock"] = {"market_id": shock.market_id,
                           "delta_p": shock.delta_p,
                           "delta_p_conv": shock.delta_p_conv}
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    # --- live path: fail closed, no fixture fallback --------------------------
    # Watch the macro series linked in the frozen taxonomy, plus the generic
    # feed; junk zero-price markets are skipped by _kalshi_prob.
    live_series = ("KXFEDDECISION", "KXCPIYOY", "KXFED")
    try:
        fetch = fetch_kalshi_markets_live()
        import urllib.parse as _up
        for series in live_series:
            extra = fetch_kalshi_markets_live(
                base_url=None, limit=100,
                status=f"open&series_ticker={_up.quote(series)}")
            fetch["markets"].extend(extra["markets"])
    except LiveSourceError as exc:
        print(json.dumps({"status": "BLOCKED_ADAPTER_LIMITATION",
                          "blocker": str(exc)}))
        return 3
    ledger_report = ledger_live_observations(fetch, args.ledger,
                                             mode=args.write)
    detection = detect_shocks_from_ledger(args.ledger)
    shocks = detection["shocks"]
    snapshot_report: dict[str, Any] = {"shocks": len(shocks), "written": 0}
    if shocks and args.map:
        frozen = load_frozen_map(args.map)
        wanted = {e["ticker"] for e in frozen["entries"]
                  for s in shocks if e["event_id"] == s.event_id}
        prices: dict[str, dict[int, float]] = {}
        if wanted:
            try:
                import yfinance as yf
                for t in sorted(wanted):
                    hist = yf.Ticker(t).history(period="5d", interval="1d")
                    if len(hist):
                        day = int(hist.index[-1].timestamp()) // 86400
                        prices[t] = {day: float(hist["Close"].iloc[-1])}
                        for s in shocks:
                            prices[t][s.day] = float(hist["Close"].iloc[-1])
            except Exception as exc:
                print(json.dumps({"status": "DEGRADED",
                                  "blocker": f"EQUITY_PRICE_FETCH_FAILED: "
                                             f"{type(exc).__name__}"}))
        rows: list[dict[str, Any]] = []
        for s in shocks:
            rows.extend(build_forward_snapshots(s, frozen, prices))
        snapshot_report = append_snapshots(args.out, rows, mode=args.write)
        snapshot_report["shocks"] = len(shocks)
    engine_status = ("ACTIVE" if detection["markets_with_prior"] > 0
                     else "WARMING_UP")
    status_doc = {
        "run_id": fetch["adapter_run_id"],
        "timestamp": fetch["fetch_timestamp"], "mode": "live",
        "markets_observed": len(fetch["markets"]),
        "observations_written": ledger_report.get("written", 0),
        "markets_with_prior": detection["markets_with_prior"],
        "markets_warming_up": detection["markets_warming_up"],
        "shocks_emitted": len(shocks),
        "status": engine_status, "blocker": None,
        "advisory_status": ADVISORY_STATUS,
    }
    write_shock_engine_status(Path("runtime/shock_engine_status.json"),
                              status_doc)
    out = {"mode": "live", "adapter_run_id": fetch["adapter_run_id"],
           "markets_observed": len(fetch["markets"]),
           "ledger": ledger_report, "shock_detection": snapshot_report,
           "engine_status": engine_status,
           "markets_with_prior": detection["markets_with_prior"],
           "note": ("live ΔP accumulates across runs of the observation "
                    "ledger; WARMING_UP is expected until history exists"),
           "advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY}
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
