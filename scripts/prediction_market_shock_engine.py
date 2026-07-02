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


def detect_shock(market: dict[str, Any], *,
                 threshold: float = DEFAULT_SHOCK_THRESHOLD,
                 window: int = DEFAULT_WINDOW) -> Shock | None:
    history = market["price_history"]
    dp = delta_p(history, window)
    if abs(dp) < threshold or not is_persistent(history, window):
        return None
    cw, depth_available = depth_conviction(market.get("depth_usd"))
    day = int(sorted(history, key=lambda r: int(r["day"]))[-1]["day"])
    return Shock(
        market_id=str(market["market_id"]),
        event_id=str(market.get("event_id", market["market_id"])),
        day=day, delta_p=dp, delta_p_conv=round(dp * cw, 6),
        depth_available=depth_available,
        data_mode=str(market.get("data_mode", FIXTURE_DEMONSTRATION)))


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
        description="Detect PM shocks and write forward snapshots (advisory)")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--map", type=Path, help="frozen event_equity_map JSON")
    ap.add_argument("--out", type=Path,
                    default=Path("data/calibration_corpus/forward_snapshots.jsonl"))
    ap.add_argument("--mode", choices=("dry_run", "write"), default="dry_run")
    args = ap.parse_args()
    if not args.demo:
        raise SystemExit("live adapter mode not wired in this sprint; use --demo")
    frozen = load_frozen_map(args.map) if args.map else fixture_frozen_map()
    shock = detect_shock(fixture_market())
    if shock is None:
        print(json.dumps({"shocks": 0}))
        return 0
    rows = build_forward_snapshots(shock, frozen, fixture_equity_prices())
    report = append_snapshots(args.out, rows, mode=args.mode)
    report["shock"] = {"market_id": shock.market_id, "delta_p": shock.delta_p,
                       "delta_p_conv": shock.delta_p_conv}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
