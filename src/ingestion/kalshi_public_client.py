"""Read-only public Kalshi market-data client.

Mirrors ``src/ingestion/polymarket_public_client.py``: GET-only access to
public market-discovery endpoints, deterministic mock fallback when the
upstream is unreachable, and a clean ``health_check`` surface.  Strictly
advisory-only.

Hard non-goals (do not add):
- Authentication headers, API keys, or session tokens.
- ``POST`` / ``DELETE`` / ``PATCH`` of any kind.
- ``/portfolio/*``, ``/exchange/login``, ``/exchange/logout``, or any
  trade-side endpoint.
- Order placement, order cancel, order modify, fill subscription, or
  balance access.

Endpoints used (public, read-only):
- ``GET <base>/markets`` — discovery list (filtered to open markets).
- ``GET <base>/events``  — best-effort enrichment for category metadata.
- ``GET <base>/markets/{ticker}`` — single-market detail.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

try:
    from scripts.kalshi_normalizer import (
        CANONICAL_CATEGORIES,
        build_kalshi_semantic_text,
        classify_kalshi_category,
        kalshi_safety_stamps,
        stable_kalshi_event_id,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import sys
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from scripts.kalshi_normalizer import (  # type: ignore[no-redef]
        CANONICAL_CATEGORIES,
        build_kalshi_semantic_text,
        classify_kalshi_category,
        kalshi_safety_stamps,
        stable_kalshi_event_id,
    )

from src.models.kalshi_market import KalshiMarketSnapshot
from src.utils.config_loader import load_yaml_config
from src.utils.logging_utils import get_logger, log_event
from src.utils.time_utils import utc_now_iso

LOGGER = get_logger("kalshi_public_client")
DEFAULT_SOURCES_PATH = Path("config/sources.yaml")
_USER_AGENT = "sleeping-passenger-mvp/kalshi-readonly (advisory-only)"


class KalshiPublicClient:
    """Read-only public Kalshi market-data client.

    Reads endpoint config from ``config/sources.yaml`` (key ``kalshi``).
    Falls back to a deterministic mock-market list when the upstream is
    unreachable (controlled by ``use_mock_on_failure``).
    """

    def __init__(self, config_path: str | Path = DEFAULT_SOURCES_PATH) -> None:
        config = load_yaml_config(config_path)
        cfg = config.get("kalshi", {}) if isinstance(config, dict) else {}
        self.api_base_url = str(
            cfg.get("api_base_url", "https://api.elections.kalshi.com/trade-api/v2")
        ).rstrip("/")
        self.timeout_seconds = int(cfg.get("timeout_seconds", 12))
        self.retries = int(cfg.get("retries", 2))
        self.backoff_seconds = float(cfg.get("backoff_seconds", 1.0))
        self.max_markets = int(cfg.get("max_markets", 25))
        self.use_mock_on_failure = bool(cfg.get("use_mock_on_failure", True))
        raw_allowed = cfg.get("allowed_categories")
        if isinstance(raw_allowed, list):
            self.allowed_categories: tuple[str, ...] = tuple(
                str(x) for x in raw_allowed if x
            )
        else:
            self.allowed_categories = tuple(CANONICAL_CATEGORIES)
        self.session = requests.Session()

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------

    def _request_json(
        self, url: str, params: dict[str, Any] | None = None
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout_seconds,
                    headers={
                        "User-Agent": _USER_AGENT,
                        "Accept": "application/json",
                    },
                )
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                log_event(
                    LOGGER,
                    "api_call_failed",
                    module="kalshi_public_client",
                    url=url,
                    attempt=attempt,
                    error=str(exc),
                )
        if self.use_mock_on_failure:
            return None
        if last_error is not None:
            raise last_error
        return None

    # ------------------------------------------------------------------
    # Public read-only methods
    # ------------------------------------------------------------------

    def fetch_markets(self) -> list[KalshiMarketSnapshot]:
        log_event(LOGGER, "ingestion_started", module="kalshi_public_client")
        data = self._request_json(
            f"{self.api_base_url}/markets",
            params={"limit": self.max_markets, "status": "open"},
        )
        if not data:
            snapshots = self._mock_markets()
            log_event(
                LOGGER,
                "ingestion_completed",
                module="kalshi_public_client",
                market_count=len(snapshots),
                fallback="mock",
            )
            return snapshots
        items = data.get("markets") if isinstance(data, dict) else data
        if not isinstance(items, list):
            items = []
        snapshots: list[KalshiMarketSnapshot] = []
        for item in items[: self.max_markets]:
            if not isinstance(item, dict):
                continue
            snap = self.normalize_market(item)
            if snap is not None:
                snapshots.append(snap)
        log_event(
            LOGGER,
            "ingestion_completed",
            module="kalshi_public_client",
            market_count=len(snapshots),
            fallback="none",
        )
        return snapshots

    def fetch_events(self) -> list[dict[str, Any]]:
        data = self._request_json(
            f"{self.api_base_url}/events",
            params={"limit": self.max_markets},
        )
        if not data:
            return [
                {
                    "event_ticker": s.event_ticker,
                    "title": s.title,
                    "category": s.category,
                }
                for s in self._mock_markets()
            ]
        if isinstance(data, dict):
            events = data.get("events", [])
            return list(events) if isinstance(events, list) else []
        return list(data) if isinstance(data, list) else []

    def fetch_market_detail(self, ticker: str) -> KalshiMarketSnapshot | None:
        data = self._request_json(f"{self.api_base_url}/markets/{ticker}")
        if not data:
            for snap in self._mock_markets():
                if snap.source_market_id == ticker:
                    return snap
            return None
        if isinstance(data, dict) and "market" in data and isinstance(data["market"], dict):
            return self.normalize_market(data["market"])
        if isinstance(data, dict):
            return self.normalize_market(data)
        return None

    # ------------------------------------------------------------------
    # Normalization — only returns a snapshot for approved categories
    # ------------------------------------------------------------------

    def normalize_market(self, payload: dict[str, Any]) -> KalshiMarketSnapshot | None:
        """Normalize one raw Kalshi market into a snapshot.

        Returns ``None`` if the market lacks required identifiers or its
        category falls outside the approved Kalshi allowlist.
        """
        ticker = str(
            payload.get("ticker")
            or payload.get("market_ticker")
            or payload.get("id")
            or ""
        ).strip()
        if not ticker:
            return None

        raw_tags = payload.get("tags") or []
        if isinstance(raw_tags, list):
            tags = [
                (t.get("label") if isinstance(t, dict) else str(t))
                for t in raw_tags
                if t
            ]
        else:
            tags = []

        category_class = classify_kalshi_category(payload.get("category"), tags=tags)
        if not category_class["allowed"]:
            return None
        if (
            self.allowed_categories
            and category_class["display_category"] not in self.allowed_categories
        ):
            return None

        title = str(payload.get("title") or payload.get("subtitle") or "").strip()
        if not title:
            return None
        description = str(
            payload.get("description")
            or payload.get("subtitle")
            or ""
        ).strip()
        rules = str(
            payload.get("rules_primary")
            or payload.get("rules")
            or payload.get("resolution_criteria")
            or ""
        ).strip()

        yes_ask = _coerce_float(payload.get("yes_ask") or payload.get("yes_price"))
        no_ask = _coerce_float(payload.get("no_ask") or payload.get("no_price"))
        last = _coerce_float(payload.get("last_price"))
        implied = _coerce_float(payload.get("implied_probability"))
        if implied is None and yes_ask is not None:
            implied = yes_ask if yes_ask <= 1.0 else yes_ask / 100.0
        elif implied is None and last is not None:
            implied = last if last <= 1.0 else last / 100.0

        outcomes = ["YES", "NO"]
        snapshot = KalshiMarketSnapshot(
            source_market_id=ticker,
            event_ticker=str(payload.get("event_ticker") or "").strip(),
            title=title,
            description=description,
            rules=rules,
            category=str(category_class["display_category"] or ""),
            category_raw=str(category_class["raw_category"] or ""),
            outcomes=outcomes,
            yes_price=yes_ask,
            no_price=no_ask,
            implied_probability=implied,
            volume=_coerce_float(payload.get("volume")),
            open_interest=_coerce_int(payload.get("open_interest")),
            liquidity=_coerce_float(payload.get("liquidity")),
            close_time_utc=str(
                payload.get("close_time")
                or payload.get("expiration_time")
                or ""
            ).strip(),
            market_url=str(payload.get("market_url") or "").strip(),
            fetched_at_utc=utc_now_iso(),
            asset_tags=tags,
            event_tags=[],
            is_mock_fixture=bool(payload.get("is_mock_fixture")),
        )
        snapshot.semantic_text = build_kalshi_semantic_text(
            {
                "title": title,
                "description": description,
                "rules": rules,
                "outcomes": outcomes,
                "category": snapshot.category,
                "tags": tags,
                "close_time_utc": snapshot.close_time_utc,
            }
        )
        # Re-stamp safety fields defensively — guarantees no
        # caller-supplied payload can downgrade them.
        stamps = kalshi_safety_stamps()
        snapshot.advisory_status = stamps["advisory_status"]
        snapshot.execution_permission = stamps["execution_permission"]
        snapshot.execution_gate = stamps["execution_gate"]
        snapshot.advisory_only = True
        snapshot.human_review_required = stamps["human_review_required"]
        snapshot.broker_api_called = stamps["broker_api_called"]
        snapshot.ai_execution_count = stamps["ai_execution_count"]
        log_event(
            LOGGER,
            "market_normalized",
            module="kalshi_public_client",
            market_id=snapshot.source_market_id,
            category=snapshot.category,
        )
        return snapshot

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        markets = self.fetch_markets()
        return {
            "ok": bool(markets),
            "read_only": True,
            "auth_required": False,
            "market_count": len(markets),
            "truth_origin": "public_or_mock",
            "advisory_only": True,
            "execution_permission": "ADVISORY_ONLY",
            "broker_api_called": False,
            "ai_execution_count": 0,
        }

    # ------------------------------------------------------------------
    # Deterministic mock fallback
    # ------------------------------------------------------------------

    def _mock_markets(self) -> list[KalshiMarketSnapshot]:
        rows = [
            {
                "ticker": "BTCMAY-2026",
                "event_ticker": "BTC-2026",
                "title": "How high will Bitcoin get in May?",
                "description": (
                    "Market resolves based on whether Bitcoin reaches a specified "
                    "price during May."
                ),
                "rules_primary": (
                    "Settles to the highest BTC/USD print on Coinbase between "
                    "2026-05-01 and 2026-05-31."
                ),
                "category": "Crypto",
                "tags": ["bitcoin", "BTC", "May"],
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
                "event_ticker": "FED-2026-JUN",
                "title": "Will the Fed cut rates at the June 2026 meeting?",
                "description": "Resolves YES if FOMC June 2026 statement cuts the target range.",
                "rules_primary": "Settles to the FOMC June 2026 statement target-range change.",
                "category": "Economics",
                "tags": ["fed", "fomc"],
                "yes_ask": 0.31,
                "no_ask": 0.69,
                "volume": 4200,
                "open_interest": 2400,
                "close_time": "2026-06-18T18:00:00Z",
                "is_mock_fixture": True,
            },
            {
                "ticker": "PRES-2028-D",
                "event_ticker": "PRES-2028",
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
            # Deliberately rejected row — verifies the allowlist gate
            # filters mock markets too.
            {
                "ticker": "NBA-FINALS-2026",
                "event_ticker": "NBA-2026",
                "title": "Will the Lakers win the 2026 NBA Finals?",
                "category": "Sports",
                "yes_ask": 0.20,
                "is_mock_fixture": True,
            },
        ]
        out: list[KalshiMarketSnapshot] = []
        for row in rows:
            snap = self.normalize_market(row)
            if snap is not None:
                out.append(snap)
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


__all__ = ["KalshiPublicClient", "stable_kalshi_event_id"]
