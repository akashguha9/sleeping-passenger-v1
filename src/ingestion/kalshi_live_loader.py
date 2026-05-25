"""Read-only Kalshi live loader.

Walks the Kalshi demo (or prod) read-only endpoints via
:class:`KalshiLiveClient`, normalises each market through the existing
governance + normalizer pair, then writes the canonical
``kalshi_source_health.json`` + quarantine jsonl artifacts via the
existing :func:`scripts.kalshi_runner.write_kalshi_source_health` helper.

Strictly advisory-only.  No persistence to SQLite happens here; that
remains the runner's job and is gated behind ``dry_run``.

This loader purposefully:
- never returns or logs raw auth headers
- never returns or logs the API Key ID / private-key path
- never invokes a non-GET endpoint
- never accepts a market that doesn't pass the category allowlist
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.ingestion.kalshi_live_client import KalshiLiveClient, ReadOnlyKalshiViolation
from src.ingestion.kalshi_live_config import (
    KalshiConfigError,
    KalshiLiveConfig,
    load_kalshi_live_config,
)

# Re-export the canonical governance/normalizer entry points.  The scripts/
# directory is added to sys.path so they import in repo-script mode.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:  # pragma: no cover - defensive
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.kalshi_normalizer import (  # noqa: E402
    CANONICAL_SOURCE,
)
from scripts.ingestion.kalshi_loader import (  # noqa: E402
    partition_kalshi_records,
)
from scripts.kalshi_runner import write_kalshi_source_health  # noqa: E402
from scripts.runtime_common import utc_timestamp  # noqa: E402

_LOG = logging.getLogger(__name__)


@dataclass
class LiveSmokeResult:
    """In-memory summary returned by :func:`run_live_kalshi_smoke`.

    Mirrors the safety fields the runner already emits.  Never carries
    secret material.
    """

    status: str = "ok"
    env: str = "demo"
    api_base_url: str = ""
    auth_used: bool = False
    pages_fetched: int = 0
    records_seen_total: int = 0
    records_allowed: int = 0
    records_quarantined: int = 0
    accepted_category_counts: dict[str, int] = field(default_factory=dict)
    quarantined_category_counts: dict[str, int] = field(default_factory=dict)
    quarantine_reason_counts: dict[str, int] = field(default_factory=dict)
    source_freshness_status: str = "unverified"
    health_path: str = ""
    quarantine_path: str = ""
    advisory_only: bool = True
    human_review_required: bool = True
    execution_locked: bool = True
    broker_api_called: bool = False
    ai_execution_count: int = 0
    error_type: str = ""
    error_message: str = ""
    http_status: int | None = None
    sample_titles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "env": self.env,
            "api_base_url": self.api_base_url,
            "auth_used": self.auth_used,
            "pages_fetched": self.pages_fetched,
            "records_seen_total": self.records_seen_total,
            "records_allowed": self.records_allowed,
            "records_quarantined": self.records_quarantined,
            "accepted_category_counts": dict(self.accepted_category_counts),
            "quarantined_category_counts": dict(self.quarantined_category_counts),
            "quarantine_reason_counts": dict(self.quarantine_reason_counts),
            "source_freshness_status": self.source_freshness_status,
            "health_path": self.health_path,
            "quarantine_path": self.quarantine_path,
            "advisory_only": self.advisory_only,
            "human_review_required": self.human_review_required,
            "execution_locked": self.execution_locked,
            "broker_api_called": self.broker_api_called,
            "ai_execution_count": self.ai_execution_count,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "http_status": self.http_status,
            "sample_titles": list(self.sample_titles),
        }


def _extract_markets_page(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(payload, dict):
        markets = payload.get("markets") or payload.get("data") or []
        cursor = payload.get("cursor") or payload.get("next_cursor")
        if isinstance(cursor, str) and cursor.strip():
            return [m for m in markets if isinstance(m, dict)], cursor.strip()
        return [m for m in markets if isinstance(m, dict)], None
    if isinstance(payload, list):
        return [m for m in payload if isinstance(m, dict)], None
    return [], None


def _market_to_loader_record(market: dict[str, Any]) -> dict[str, Any] | None:
    """Defensive field extraction.

    Kalshi's live API has a couple of equivalent field names; tolerate
    the documented variations.  The raw payload is *not* returned —
    only the safe loader-record shape the normalizer expects.
    """
    ticker = str(
        market.get("ticker")
        or market.get("market_ticker")
        or market.get("id")
        or ""
    ).strip()
    if not ticker:
        return None
    title = str(
        market.get("title")
        or market.get("market_title")
        or market.get("question")
        or market.get("subtitle")
        or ""
    ).strip()
    raw_tags = market.get("tags") or []
    if isinstance(raw_tags, list):
        tags = [
            (t.get("label") if isinstance(t, dict) else str(t))
            for t in raw_tags
            if t
        ]
    else:
        tags = []
    outcomes_raw = (
        market.get("outcomes")
        or market.get("response_options")
        or market.get("yes_no_outcomes")
        or []
    )
    if isinstance(outcomes_raw, list):
        outcomes = [
            str(o.get("label") if isinstance(o, dict) else o).strip()
            for o in outcomes_raw
            if o
        ]
    else:
        outcomes = []
    return {
        "source": CANONICAL_SOURCE,
        "ticker": ticker,
        "title": title,
        "subtitle": str(market.get("subtitle") or "").strip(),
        "description": str(market.get("description") or "").strip(),
        "rules_primary": str(market.get("rules_primary") or "").strip(),
        "category": str(
            market.get("category") or market.get("category_slug") or ""
        ).strip(),
        "subcategory": str(market.get("subcategory") or "").strip(),
        "tags": tags,
        "outcomes": outcomes,
        "yes_ask": market.get("yes_ask"),
        "no_ask": market.get("no_ask"),
        "last_price": market.get("last_price"),
        "volume": market.get("volume"),
        "open_interest": market.get("open_interest"),
        "liquidity": market.get("liquidity"),
        "close_time": (
            market.get("close_time")
            or market.get("expiration_time")
            or market.get("close_ts")
        ),
        "market_url": market.get("market_url"),
        "event_ticker": market.get("event_ticker"),
        "series_ticker": market.get("series_ticker"),
    }


def _partition(
    records: list[dict[str, Any]],
    fetched_at: str,
    *,
    event_lookup: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Delegate to the canonical scripts/ partitioner.

    The repo-canonical helper enforces the allowlist, runs the
    inference layer with /events enrichment, and emits the audit
    quarantine record shape.  Reusing it guarantees the live loader
    cannot drift from the mock/loader path the existing tests cover.
    """
    return partition_kalshi_records(
        records,
        fetched_at_utc=fetched_at,
        event_lookup=event_lookup or {},
    )


def run_live_kalshi_smoke(
    *,
    config: KalshiLiveConfig | None = None,
    client: KalshiLiveClient | None = None,
    max_pages: int = 1,
    limit: int = 20,
    dry_run: bool = True,
    health_path: Path | None = None,
    quarantine_path: Path | None = None,
    write_health: bool = True,
) -> LiveSmokeResult:
    """Run the Kalshi live read-only smoke + governance pipeline.

    Always writes ``kalshi_source_health.json`` (under ``runtime/release``
    by default) unless ``write_health=False``.  Tests can redirect
    artifacts to ``tmp_path`` via ``health_path`` / ``quarantine_path``.
    """
    cfg = config or load_kalshi_live_config()
    if client is None:
        client = KalshiLiveClient(cfg)

    result = LiveSmokeResult(
        env=cfg.env,
        api_base_url=cfg.api_base_url,
        auth_used=client.auth_used,
    )

    attempted_at = utc_timestamp()
    fetched_at = attempted_at
    accepted: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    cursor: str | None = None
    status_label = "OK"
    http_status: int | None = None
    error_type = ""
    error_message = ""

    try:
        # Lightweight health probe — non-fatal; failure here gets recorded
        # via the main /markets call.
        try:
            client.get_exchange_status()
        except ReadOnlyKalshiViolation:  # pragma: no cover - defensive
            raise
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "kalshi_exchange_status_probe_failed type=%s",
                type(exc).__name__,
            )

        # Best-effort /events enrichment so markets that only carry an
        # event_ticker resolve a category through the existing
        # governance + inference layer.
        #
        # We use two enrichment passes:
        # 1) One bulk ``/events?limit=N`` pull (cheap, covers popular
        #    events).
        # 2) Targeted ``/events/{event_ticker}`` lookups for each event
        #    referenced by the page of markets but not present in the
        #    bulk dictionary.  These calls are still strictly GET and
        #    pass through the read-only blocklist check.
        #
        # All enrichment is non-fatal: on failure the inference layer
        # (ticker prefix / keyword fallback) still runs.
        event_lookup: dict[str, dict[str, Any]] = {}
        try:
            events_payload = client.get_events(limit=max(50, int(limit) * 2))
            events_raw = (
                events_payload.get("events", [])
                if isinstance(events_payload, dict)
                else []
            )
            for ev in events_raw:
                if not isinstance(ev, dict):
                    continue
                ticker = str(ev.get("event_ticker") or ev.get("ticker") or "").strip()
                if ticker:
                    event_lookup[ticker] = ev
        except ReadOnlyKalshiViolation:  # pragma: no cover - defensive
            raise
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "kalshi_events_enrichment_failed type=%s", type(exc).__name__
            )

        for _page in range(max(1, int(max_pages))):
            payload = client.get_markets(limit=limit, cursor=cursor)
            page_markets, next_cursor = _extract_markets_page(payload)
            result.pages_fetched += 1

            # Fill in event_lookup for any event_ticker referenced by
            # this page of markets but missing from the bulk pull.
            missing_event_tickers: set[str] = set()
            for market in page_markets:
                et = str(market.get("event_ticker") or "").strip()
                if et and et not in event_lookup:
                    missing_event_tickers.add(et)
            for et in sorted(missing_event_tickers):
                try:
                    ev_payload = client.get_event(et)
                except ReadOnlyKalshiViolation:  # pragma: no cover - defensive
                    raise
                except Exception:
                    # Skip on per-event failure; ticker/keyword inference
                    # still has a chance.
                    continue
                ev_body = (
                    ev_payload.get("event")
                    if isinstance(ev_payload, dict) and "event" in ev_payload
                    else ev_payload
                )
                if isinstance(ev_body, dict):
                    event_lookup[et] = ev_body

            page_records: list[dict[str, Any]] = []
            for market in page_markets:
                rec = _market_to_loader_record(market)
                if rec is None:
                    continue
                # Forward enriched event title/category/tags onto the
                # record so the normalizer/inference layer can recover
                # category metadata when /markets omits it.
                ev_ticker = str(rec.get("event_ticker") or "").strip()
                ev_meta = event_lookup.get(ev_ticker) if ev_ticker else None
                if isinstance(ev_meta, dict):
                    if not rec.get("category"):
                        rec["category"] = str(ev_meta.get("category") or "").strip()
                    if not rec.get("subcategory"):
                        rec["subcategory"] = str(
                            ev_meta.get("subcategory") or ""
                        ).strip()
                    if not rec.get("series_ticker"):
                        rec["series_ticker"] = str(
                            ev_meta.get("series_ticker") or ""
                        ).strip()
                    if not rec.get("description"):
                        rec["description"] = str(ev_meta.get("title") or "").strip()
                page_records.append(rec)
            result.records_seen_total += len(page_records)
            page_accepted, page_quarantined = _partition(
                page_records, fetched_at, event_lookup=event_lookup
            )
            accepted.extend(page_accepted)
            quarantined.extend(page_quarantined)
            if not next_cursor:
                break
            cursor = next_cursor
            # Polite pacing between pages.
            time.sleep(0.05)
    except ReadOnlyKalshiViolation as exc:
        status_label = "ERROR"
        error_type = type(exc).__name__
        error_message = str(exc)
    except Exception as exc:  # noqa: BLE001
        status_label = "ERROR"
        error_type = type(exc).__name__
        # Try to surface HTTP status without echoing response body.
        response = getattr(exc, "response", None)
        if response is not None and getattr(response, "status_code", None):
            http_status = int(response.status_code)
        error_message = f"{error_type}: {exc.__class__.__qualname__}"
        # Be careful with the message — Kalshi errors can echo path/query.
        # Keep only the type name + status.
        _LOG.warning(
            "kalshi_live_smoke_failed type=%s http_status=%s",
            error_type,
            http_status,
        )

    result.records_allowed = len(accepted)
    result.records_quarantined = len(quarantined)

    # Counts.
    accepted_counts: dict[str, int] = {}
    for rec in accepted:
        slug = str(rec.get("mvp_category") or rec.get("category") or "")
        accepted_counts[slug] = accepted_counts.get(slug, 0) + 1
    quarantined_counts: dict[str, int] = {}
    quarantine_reason_counts: dict[str, int] = {}
    for rec in quarantined:
        raw = str(
            rec.get("raw_category")
            or rec.get("category_decision", {}).get("kalshi_category_raw", "")
            or "<missing>"
        )
        quarantined_counts[raw] = quarantined_counts.get(raw, 0) + 1
        reason = str(rec.get("quarantine_reason") or "")
        quarantine_reason_counts[reason] = quarantine_reason_counts.get(reason, 0) + 1

    result.accepted_category_counts = accepted_counts
    result.quarantined_category_counts = quarantined_counts
    result.quarantine_reason_counts = quarantine_reason_counts
    result.status = "ok" if status_label != "ERROR" else "error"
    result.error_type = error_type
    result.error_message = error_message
    result.http_status = http_status

    # Sample titles (cap to 3) — useful for the operator, no PII.
    for rec in accepted[:3]:
        title = rec.get("title")
        if isinstance(title, str) and title:
            result.sample_titles.append(title)

    if write_health:
        completed_at = utc_timestamp()
        summary = write_kalshi_source_health(
            attempted_at_utc=attempted_at,
            completed_at_utc=completed_at,
            status=status_label,
            records_seen_total=result.records_seen_total,
            accepted=accepted,
            quarantined=quarantined,
            events_persisted=0,  # dry-run smoke never persists
            error_type=error_type,
            error_message=error_message,
            http_status=http_status,
            last_successful_fetch_at_utc=(
                completed_at if status_label != "ERROR" else None
            ),
            freshness_ttl_seconds=cfg.freshness_ttl_seconds,
            is_mock_run=False,
            health_path=health_path,
            quarantine_path=quarantine_path,
        )
        # Augment the on-disk summary with the live-mode block (no secrets).
        summary["mode"] = "live_read_only"
        summary["env"] = cfg.env
        summary["auth_used"] = client.auth_used
        summary["api_base_url"] = cfg.api_base_url
        summary["dry_run"] = bool(dry_run)
        # Re-write with the appended fields.
        try:
            import json as _json
            from scripts.kalshi_runner import (
                DEFAULT_KALSHI_HEALTH_PATH as _DEFAULT_HEALTH,
            )
            target = health_path or _DEFAULT_HEALTH
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_json.dumps(summary, indent=2), encoding="utf-8")
            result.health_path = str(target)
        except OSError as exc:  # pragma: no cover
            _LOG.warning("kalshi live health re-write failed: %s", exc)
        try:
            from scripts.kalshi_runner import (
                DEFAULT_KALSHI_QUARANTINE_PATH as _DEFAULT_Q,
            )
            result.quarantine_path = str(quarantine_path or _DEFAULT_Q)
        except Exception:  # pragma: no cover
            result.quarantine_path = ""
        result.source_freshness_status = summary.get(
            "source_freshness_status", result.source_freshness_status
        )

    return result


__all__ = [
    "LiveSmokeResult",
    "run_live_kalshi_smoke",
]
