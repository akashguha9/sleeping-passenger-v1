"""
Kalshi read-only market-data loader.

Mirrors the Polymarket read-only pattern (``scripts/ingestion/polymarket_loader.py``):
public market discovery only, no authentication, no trade-side endpoints,
no order placement, no portfolio/account/fill endpoints.

Endpoints used (public, read-only)
----------------------------------
- ``GET <base>/markets?limit=N&status=open``
    Public market discovery.  Returns the next page of open markets.
    Skipped cleanly when the upstream rejects the call (401 / 403 / 5xx /
    network error) — we never persist auth-gated data.
- ``GET <base>/events?limit=N`` (optional, best-effort)
    Public event discovery — fills in category metadata for markets that
    only expose an ``event_ticker`` reference.  Failure is non-fatal:
    markets without enriched category just rely on their own ``category``
    field for the allowlist gate.

Base URL is configurable via ``KALSHI_API_BASE`` and defaults to the
publicly documented Kalshi Elections API host.

Hard non-goals (do not add)
---------------------------
- Trading endpoints: ``/portfolio/orders``, ``/portfolio/fills``,
  ``/portfolio/positions``, ``/portfolio/balance``, ``/exchange/login``,
  ``/exchange/logout``, anything under ``/trade-api/v2/portfolio`` or any
  POST/DELETE method.
- API-key / private-key storage.  No env var is required to RUN the
  loader; ``KALSHI_API_KEY`` is registered for *informational* status
  display only and is never read here.
- Account, position, order, fill, or balance access.

Test mode
---------
``KALSHI_USE_MOCK_FIXTURES=1`` (or ``KalshiLoader(use_mock_fixtures=True)``)
swaps live HTTP for a deterministic in-process fixture list.  Every mock
row is explicitly tagged ``is_mock_fixture=True`` so it cannot be
confused with live data downstream.
"""
from __future__ import annotations

import os
from typing import Any

try:
    from scripts.ingestion.base_loader import (
        BaseSourceLoader,
        LoaderResult,
        SkipLoader,
    )
    from scripts.kalshi_normalizer import (
        CANONICAL_SOURCE,
        normalize_kalshi_market,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from ingestion.base_loader import (  # type: ignore[no-redef]
        BaseSourceLoader,
        LoaderResult,
        SkipLoader,
    )
    from kalshi_normalizer import (  # type: ignore[no-redef]
        CANONICAL_SOURCE,
        normalize_kalshi_market,
    )

_DEFAULT_BASE = "https://api.elections.kalshi.com/trade-api/v2"
_DEFAULT_LIMIT = 50
_DEFAULT_MAX_PAGES = 3
_DEFAULT_TIMEOUT = 12
_USER_AGENT = "sleeping-passenger-mvp/kalshi-readonly (advisory-only)"


# Mock fixture set used when ``KALSHI_USE_MOCK_FIXTURES=1``.  Every row is
# tagged ``is_mock_fixture=True`` and covers the seven approved categories
# plus one deliberately rejected Sports row so the allowlist gate can be
# verified end-to-end without touching the network.
_MOCK_FIXTURES: list[dict[str, Any]] = [
    {
        "ticker": "BTCMAY-2026",
        "title": "How high will Bitcoin get in May?",
        "subtitle": (
            "Market resolves based on whether Bitcoin reaches a specified price during May."
        ),
        "rules_primary": "Settles to the highest BTC/USD print on Coinbase between 2026-05-01 and 2026-05-31.",
        "category": "Crypto",
        "tags": ["bitcoin", "BTC", "May", "price level"],
        "yes_ask": 0.42,
        "no_ask": 0.58,
        "volume": 1250,
        "open_interest": 800,
        "close_time": "2026-05-31T23:59:00Z",
        "market_url": "https://kalshi.com/markets/BTCMAY-2026",
        "is_mock_fixture": True,
    },
    {
        "ticker": "FED-CUT-JUN-2026",
        "title": "Will the Fed cut rates at the June 2026 meeting?",
        "subtitle": "Resolves YES if the FOMC June 2026 statement reduces the target range.",
        "rules_primary": "Settles to the FOMC statement target-range change.",
        "category": "Economics",
        "tags": ["fed", "fomc", "rates"],
        "yes_ask": 0.31,
        "no_ask": 0.69,
        "volume": 4200,
        "open_interest": 2400,
        "close_time": "2026-06-18T18:00:00Z",
        "is_mock_fixture": True,
    },
    {
        "ticker": "PRES-2028-D",
        "title": "Will a Democrat win the 2028 US Presidential Election?",
        "category": "Elections",
        "tags": ["election", "president", "2028"],
        "yes_ask": 0.49,
        "no_ask": 0.51,
        "volume": 9500,
        "open_interest": 7300,
        "close_time": "2028-11-08T05:00:00Z",
        "is_mock_fixture": True,
    },
    {
        "ticker": "WTI-JUN-2026",
        "title": "Will WTI crude close above $80 by end of June 2026?",
        "category": "Commodities",
        "tags": ["oil", "wti", "crude"],
        "yes_ask": 0.22,
        "no_ask": 0.78,
        "volume": 1100,
        "open_interest": 600,
        "close_time": "2026-06-30T20:00:00Z",
        "is_mock_fixture": True,
    },
    {
        "ticker": "NBA-FINALS-2026",
        "title": "Will the Lakers win the 2026 NBA Finals?",
        "category": "Sports",  # deliberately rejected by the allowlist
        "yes_ask": 0.20,
        "is_mock_fixture": True,
    },
]


def _request_kwargs(timeout: int) -> dict[str, Any]:
    """Common kwargs for every public Kalshi GET.

    No Authorization header.  No API key.  Polite user-agent only.
    """
    return {
        "headers": {"User-Agent": _USER_AGENT, "Accept": "application/json"},
        "timeout": timeout,
    }


class KalshiLoader(BaseSourceLoader):
    """Read-only Kalshi market-data loader (no auth, no trading).

    Parameters
    ----------
    limit:
        Per-page market limit forwarded to the upstream ``/markets`` call.
    max_pages:
        Maximum pages to walk for the broad market discovery sweep.
    base:
        Override the upstream base URL (useful for tests).  Defaults to the
        ``KALSHI_API_BASE`` env var if set, otherwise the public Elections
        host.
    timeout:
        Per-request timeout in seconds.
    use_mock_fixtures:
        When True, bypass HTTP entirely and emit the in-process mock
        fixture set.  Honours ``KALSHI_USE_MOCK_FIXTURES=1`` env var.
    """

    source_name = CANONICAL_SOURCE
    requires_key = False  # public read-only — no auth ever

    def __init__(
        self,
        limit: int = _DEFAULT_LIMIT,
        max_pages: int = _DEFAULT_MAX_PAGES,
        base: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        use_mock_fixtures: bool | None = None,
    ) -> None:
        self._limit = max(1, int(limit))
        self._max_pages = max(1, int(max_pages))
        self._base = (
            base
            or os.environ.get("KALSHI_API_BASE", "").strip()
            or _DEFAULT_BASE
        ).rstrip("/")
        self._timeout = int(timeout)
        env_mock = os.environ.get("KALSHI_USE_MOCK_FIXTURES", "").strip()
        self._use_mock = (
            bool(use_mock_fixtures)
            if use_mock_fixtures is not None
            else env_mock in {"1", "true", "TRUE", "yes"}
        )

    # ------------------------------------------------------------------
    # Public fetch entry point
    # ------------------------------------------------------------------

    def fetch(self) -> LoaderResult:
        if self._use_mock:
            return self._fetch_mock()

        try:
            import requests  # lazy import — no network at module load
        except ImportError as exc:  # pragma: no cover - dev env always has requests
            raise SkipLoader(f"requests library not installed: {exc}")

        markets_raw = self._fetch_markets(requests)
        if markets_raw is None:
            raise SkipLoader(
                "Kalshi public market discovery unreachable or auth-gated — "
                "skipped cleanly (no auth attempted)."
            )

        # Best-effort enrichment: pull /events to fill in any missing
        # category fields for markets that only carry an event_ticker.
        events_by_ticker: dict[str, dict[str, Any]] = {}
        try:
            events_raw = self._fetch_events(requests) or []
            for ev in events_raw:
                if not isinstance(ev, dict):
                    continue
                ticker = str(ev.get("event_ticker") or ev.get("ticker") or "").strip()
                if ticker:
                    events_by_ticker[ticker] = ev
        except Exception:
            # Event enrichment is purely additive; never fail the run.
            events_by_ticker = {}

        records: list[dict[str, Any]] = []
        for market in markets_raw:
            if not isinstance(market, dict):
                continue
            event = None
            ev_ticker = str(market.get("event_ticker") or "").strip()
            if ev_ticker:
                event = events_by_ticker.get(ev_ticker)
            rec = self._market_to_record(market, event=event)
            if rec is not None:
                self._stamp_record(rec)
                records.append(rec)
        return LoaderResult(source_name=self.source_name, records=records)

    # ------------------------------------------------------------------
    # Mock mode
    # ------------------------------------------------------------------

    def _fetch_mock(self) -> LoaderResult:
        records: list[dict[str, Any]] = []
        for fixture in _MOCK_FIXTURES:
            rec = dict(fixture)
            rec.setdefault("source", CANONICAL_SOURCE)
            self._stamp_record(rec)
            records.append(rec)
        return LoaderResult(source_name=self.source_name, records=records)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _fetch_markets(self, requests_mod: Any) -> list[dict[str, Any]] | None:
        """Page through ``GET /markets`` and return aggregated market dicts.

        Returns ``None`` ONLY when every page request failed (auth gate,
        network error, etc.) — the runner treats ``None`` as "skip".
        Returns ``[]`` for a successful-but-empty response.
        """
        url = f"{self._base}/markets"
        gathered: list[dict[str, Any]] = []
        any_succeeded = False
        cursor: str | None = None

        for _ in range(self._max_pages):
            params: dict[str, Any] = {"limit": self._limit, "status": "open"}
            if cursor:
                params["cursor"] = cursor
            try:
                resp = requests_mod.get(url, params=params, **_request_kwargs(self._timeout))
                resp.raise_for_status()
                payload = resp.json()
            except Exception:
                # Page-level failure: stop pagination, return what we got.
                break
            any_succeeded = True
            page_markets, next_cursor = self._extract_markets(payload)
            for m in page_markets:
                if isinstance(m, dict):
                    gathered.append(m)
            if not next_cursor:
                break
            cursor = next_cursor

        if not any_succeeded:
            return None
        return gathered

    def _fetch_events(self, requests_mod: Any) -> list[dict[str, Any]] | None:
        """One-shot best-effort fetch of ``GET /events`` for category enrichment."""
        url = f"{self._base}/events"
        try:
            resp = requests_mod.get(
                url,
                params={"limit": self._limit},
                **_request_kwargs(self._timeout),
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return None
        if isinstance(payload, dict):
            events = payload.get("events", [])
            return [ev for ev in events if isinstance(ev, dict)]
        if isinstance(payload, list):
            return [ev for ev in payload if isinstance(ev, dict)]
        return []

    @staticmethod
    def _extract_markets(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
        if isinstance(payload, dict):
            markets = payload.get("markets") or payload.get("data") or []
            cursor = payload.get("cursor") or payload.get("next_cursor")
            if isinstance(cursor, str) and cursor.strip():
                return list(markets), cursor.strip()
            return list(markets), None
        if isinstance(payload, list):
            return payload, None
        return [], None

    # ------------------------------------------------------------------
    # Raw → loader record
    # ------------------------------------------------------------------

    @staticmethod
    def _market_to_record(
        market: dict[str, Any],
        *,
        event: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Convert a raw Kalshi market dict into a loader record.

        Returns ``None`` if the market lacks the minimum required identifiers.
        The category-allowlist gate is enforced later by ``normalize_kalshi_market``.
        """
        ticker = str(
            market.get("ticker")
            or market.get("market_ticker")
            or market.get("id")
            or ""
        ).strip()
        if not ticker:
            return None
        category = (
            str(market.get("category") or "").strip()
            or str((event or {}).get("category") or "").strip()
        )

        # Tags: Kalshi exposes a few shapes — keep this defensive.
        raw_tags = market.get("tags") or (event or {}).get("tags") or []
        if isinstance(raw_tags, list):
            tags = [
                t.get("label", "") if isinstance(t, dict) else str(t)
                for t in raw_tags
                if t
            ]
        else:
            tags = []

        return {
            "source": CANONICAL_SOURCE,
            "ticker": ticker,
            "title": str(market.get("title") or market.get("subtitle") or "").strip(),
            "subtitle": str(market.get("subtitle") or "").strip(),
            "description": str(
                market.get("description")
                or (event or {}).get("title")
                or ""
            ).strip(),
            "rules_primary": str(market.get("rules_primary") or "").strip(),
            "category": category,
            "tags": tags,
            "yes_ask": market.get("yes_ask"),
            "no_ask": market.get("no_ask"),
            "last_price": market.get("last_price"),
            "volume": market.get("volume"),
            "open_interest": market.get("open_interest"),
            "liquidity": market.get("liquidity"),
            "close_time": market.get("close_time") or market.get("expiration_time"),
            "market_url": market.get("market_url"),
            "event_ticker": market.get("event_ticker"),
        }


# ---------------------------------------------------------------------------
# Normalize loader records to canonical signal_events payloads
# ---------------------------------------------------------------------------


def normalize_kalshi_records(
    records: list[dict[str, Any]],
    *,
    fetched_at_utc: str,
) -> list[dict[str, Any]]:
    """Normalize loader records, dropping disallowed categories.

    Returns only payloads that pass ``normalize_kalshi_market`` (i.e. that
    survive the category allowlist).  Rejected rows return ``None`` from
    the normalizer and are excluded here.
    """
    out: list[dict[str, Any]] = []
    for rec in records or []:
        normalized = normalize_kalshi_market(rec, fetched_at_utc=fetched_at_utc)
        if normalized is None:
            continue
        out.append(normalized)
    return out


__all__ = ["KalshiLoader", "normalize_kalshi_records"]
