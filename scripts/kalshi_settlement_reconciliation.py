"""Kalshi settlement reconciliation for the live probability ledger.

Feed-the-Loop sprint (2026-07-04).  The repo's largest REAL dataset — the
846-row ``data/calibration_corpus/pm_probability_ledger.jsonl`` of live
Kalshi probability observations — had no resolution loop: probabilities in,
nothing ever settled, zero calibration value extracted (forensic audit
SP-053 family).

This module closes that loop, append-only and fail-closed:

* identifies ledger observations without a recorded settlement,
* polls the PUBLIC Kalshi market endpoint (read-only; the same no-auth
  surface the ingestion client already uses) for market status/result,
* appends settlements to ``pm_settlements.jsonl`` — one line per
  (observation_id), never rewritten, never duplicated,
* computes per-row and aggregate Brier / logloss ONLY over rows whose
  settlement is a definitive WON/LOST,
* reports BLOCKED honestly when the provider is unreachable — an unknown
  settlement is UNKNOWN, never guessed.

Settlement mapping (Kalshi public market payload)::

    status in {settled, finalized} AND result == "yes"  -> WON  (y = 1)
    status in {settled, finalized} AND result == "no"   -> LOST (y = 0)
    status in {settled, finalized} AND result otherwise -> VOID
    any other status                                    -> UNSETTLED
    provider error / no payload                         -> UNKNOWN / BLOCKED

Math (ε = 1e-15)::

    Brier_e   = (p_e - y_e)^2
    LogLoss_e = -[ y_e ln(clip(p_e)) + (1 - y_e) ln(1 - clip(p_e)) ]

Dry-run by default: ``--poll`` is required for any network call, ``--write``
for any persistence.  Advisory-only throughout.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

try:  # package layout
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.runtime_common import REPO_ROOT
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from runtime_common import REPO_ROOT  # type: ignore[no-redef]

LEDGER_PATH = REPO_ROOT / "data" / "calibration_corpus" / "pm_probability_ledger.jsonl"
SETTLEMENTS_PATH = REPO_ROOT / "data" / "calibration_corpus" / "pm_settlements.jsonl"

EPS = 1e-15

ST_WON = "WON"
ST_LOST = "LOST"
ST_VOID = "VOID"
ST_UNSETTLED = "UNSETTLED"
ST_UNKNOWN = "UNKNOWN"
ST_BLOCKED = "BLOCKED"

_SETTLED_STATUSES = {"settled", "finalized"}

MarketFetcher = Callable[[str], dict[str, Any] | None]


def _clip(p: float) -> float:
    return min(max(p, EPS), 1.0 - EPS)


def brier(p: float, y: int) -> float:
    return (p - y) ** 2


def logloss(p: float, y: int) -> float:
    cp = _clip(p)
    return -(y * math.log(cp) + (1 - y) * math.log(1.0 - cp))


def classify_settlement(payload: dict[str, Any] | None) -> tuple[str, int | None]:
    """Map a raw Kalshi market payload onto (settlement_status, y)."""
    if payload is None:
        return ST_UNKNOWN, None
    market = payload.get("market") if isinstance(payload.get("market"), dict) else payload
    status = str(market.get("status") or "").lower()
    result = str(market.get("result") or "").lower()
    if status in _SETTLED_STATUSES:
        if result == "yes":
            return ST_WON, 1
        if result == "no":
            return ST_LOST, 0
        return ST_VOID, None
    return ST_UNSETTLED, None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _default_fetcher() -> MarketFetcher:  # pragma: no cover - network path
    """Read-only public-market fetcher via the existing ingestion client."""
    from src.ingestion.kalshi_public_client import KalshiPublicClient

    client = KalshiPublicClient()

    def fetch(market_ticker: str) -> dict[str, Any] | None:
        return client._request_json(  # noqa: SLF001 - raw payload needed for status/result
            f"{client.api_base_url}/markets/{market_ticker}"
        )

    return fetch


def reconcile_settlements(
    *,
    ledger_path: Any = None,
    settlements_path: Any = None,
    market_fetcher: MarketFetcher | None = None,
    poll: bool = False,
    write: bool = False,
    limit: int | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """One reconciliation pass over the probability ledger."""
    now = now_utc or datetime.now(timezone.utc)
    lpath = Path(ledger_path) if ledger_path else LEDGER_PATH
    spath = Path(settlements_path) if settlements_path else SETTLEMENTS_PATH

    ledger = _read_jsonl(lpath)
    settled_rows = _read_jsonl(spath)
    settled_obs = {
        str(r.get("observation_id")) for r in settled_rows
        if r.get("settlement_status") in (ST_WON, ST_LOST, ST_VOID)
    }
    unsettled = [
        r for r in ledger
        if str(r.get("observation_id")) not in settled_obs
        and r.get("market_ticker")
    ]
    result: dict[str, Any] = {
        "report": "kalshi_settlement_reconciliation",
        "generated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ledger_rows": len(ledger),
        "already_settled": len(settled_obs),
        "unsettled_rows": len(unsettled),
        "rows_expected": 0,
        "rows_persisted": 0,
        "poll_mode": bool(poll),
        "write_mode": bool(write),
        "provider_state": "NOT_ATTEMPTED",
        "statuses": {},
        **advisory_safety_stamps(),
    }
    if not poll:
        result["provider_state"] = "DRY_RUN_NO_NETWORK"
        result["detail"] = (
            "dry-run: no provider call attempted; rerun with --poll "
            "(and --write to persist settlements)"
        )
        return result

    fetcher = market_fetcher if market_fetcher is not None else _default_fetcher()
    targets = unsettled[: limit if limit else len(unsettled)]
    result["rows_expected"] = len(targets)

    new_rows: list[dict[str, Any]] = []
    statuses: dict[str, int] = {}
    provider_errors = 0
    # one fetch per unique market; settle every observation of that market
    by_market: dict[str, list[dict[str, Any]]] = {}
    for row in targets:
        by_market.setdefault(str(row["market_ticker"]), []).append(row)
    for market_ticker, rows in by_market.items():
        try:
            payload = fetcher(market_ticker)
        except Exception:  # noqa: BLE001 - provider failure is a visible state
            payload = None
            provider_errors += 1
        status, y = classify_settlement(payload)
        statuses[status] = statuses.get(status, 0) + len(rows)
        if status not in (ST_WON, ST_LOST, ST_VOID):
            continue  # never fake an outcome for unsettled/unknown rows
        for row in rows:
            p = row.get("p")
            try:
                pf = float(p)
            except (TypeError, ValueError):
                pf = None
            new_rows.append({
                "observation_id": row.get("observation_id"),
                "market_ticker": market_ticker,
                "event_ticker": row.get("event_ticker"),
                "p": pf,
                "settlement_status": status,
                "y": y,
                "brier": (
                    round(brier(pf, y), 6)
                    if pf is not None and y is not None else None
                ),
                "logloss": (
                    round(logloss(pf, y), 6)
                    if pf is not None and y is not None else None
                ),
                "observed_at": row.get("fetch_timestamp"),
                "settled_source": "kalshi_public_market_endpoint",
                "polled_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
    result["statuses"] = statuses
    result["provider_state"] = (
        ST_BLOCKED if provider_errors and not new_rows and not statuses.get(
            ST_UNSETTLED
        ) else "OK" if not provider_errors else "PARTIAL_ERRORS"
    )
    result["provider_errors"] = provider_errors

    scored = [r for r in new_rows if r["brier"] is not None]
    prior = [
        r for r in settled_rows
        if r.get("brier") is not None and r.get("settlement_status") in (ST_WON, ST_LOST)
    ]
    all_scored = prior + [r for r in scored if r["settlement_status"] in (ST_WON, ST_LOST)]
    if all_scored:
        result["brier_mean"] = round(
            sum(float(r["brier"]) for r in all_scored) / len(all_scored), 6
        )
        result["logloss_mean"] = round(
            sum(float(r["logloss"]) for r in all_scored) / len(all_scored), 6
        )
        result["n_scored_settlements"] = len(all_scored)

    if write and new_rows:
        spath.parent.mkdir(parents=True, exist_ok=True)
        with open(spath, "a", encoding="utf-8") as fh:
            for r in new_rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        result["rows_persisted"] = len(new_rows)
        result["settlements_path"] = str(spath)
    elif new_rows:
        result["rows_persisted"] = 0
        result["detail"] = f"{len(new_rows)} settlement(s) found; rerun with --write"
    return result


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--poll", action="store_true", help="allow provider calls")
    p.add_argument("--write", action="store_true", help="persist settlements")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true", help="explicit dry-run")
    args = p.parse_args(argv)
    result = reconcile_settlements(
        poll=args.poll and not args.dry_run,
        write=args.write and not args.dry_run,
        limit=args.limit,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["provider_state"] != ST_BLOCKED else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
