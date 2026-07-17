"""
Chart structure API context helpers -- dependency-free.

Pure parsing utilities importable without FastAPI installed.
Used by scripts/api_server.py and testable in CI without backend deps.

Safety invariants (always present, never modified):
  advisory_status      = ADVISORY_ONLY
  execution_gate       = LOCKED
  human_review_required = True
  ai_execution_count   = 0
  broker_api_called    = False
  broker_order_id      = NONE

Freshness contract (Sprint H — Stale OHLCV repair):
  - Candles are selected as the *latest* N by their payload timestamp,
    never the oldest N — the SQL helper sorts on
    json_extract(raw_payload, '$.timestamp') DESC, not on the wall-clock
    fetched_at, because a historical backfill writes thousands of rows
    with identical fetched_at and SQLite's tie-break order would
    otherwise return the OLDEST candles first.
  - Every response carries a ``freshness`` block (data_freshness_status,
    freshness_gate, latest_candle_utc, data_age_days, source_kind, …)
    so the frontend can refuse to render a normal verdict over ancient
    fixture / seed data.
  - When the freshness gate is BLOCK the advisory verdict is overridden
    with a stale-data summary and suggested_next_step ∈
    {DATA_REFRESH_REQUIRED, HUMAN_REVIEW_DATA_STALE}.  Existing safety
    stamps are preserved.

Single-source-of-truth contract (Sprint I patch — Price truth root-cause fix):
  - ``selected_candles`` is built ONCE — raw events → OHLCV parse →
    strict engine validation → per-date dedupe → tail-slice to ``limit``.
  - Both the freshness gate AND the chart-structure engine receive the
    same ``selected_candles`` list.  Their ``latest_candle_utc`` /
    ``summary.latest_timestamp`` are therefore identical by construction;
    the response's defensive integrity check catches any future drift.
  - When freshness latest != summary latest the response is suppressed
    with ``price_truth_status = INTERNAL_DATA_CONSISTENCY_ERROR`` so the
    frontend never renders a normal verdict over internally inconsistent
    fields.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Any

try:
    from scripts import market_data_freshness as _freshness
except ModuleNotFoundError:
    import market_data_freshness as _freshness  # type: ignore[no-redef]

_ADVISORY_STATUS = "ADVISORY_ONLY"

# Optional deterministic "as-of" reporting clock for the freshness gate.
#
# By default (env var unset) the freshness gate uses the wall clock, so
# production behaviour is unchanged and genuinely stale data is still blocked.
# When ``MVP_CHART_STRUCTURE_AS_OF`` holds an ISO-8601 timestamp, the freshness
# gate evaluates candle age *as of that instant* instead.  This makes a chart
# report reproducible for a historical cutoff and lets deterministic OHLCV
# fixtures be evaluated against a fixed clock rather than drifting from FRESH to
# STALE as real time advances.  It never relaxes the staleness thresholds — it
# only changes the reference "now".
_AS_OF_ENV_VAR = "MVP_CHART_STRUCTURE_AS_OF"


def _resolve_as_of_now() -> _dt.datetime | None:
    """Return the configured as-of instant (tz-aware UTC), or None for wall clock."""
    raw = os.environ.get(_AS_OF_ENV_VAR, "").strip()
    if not raw:
        return None
    try:
        text = raw.replace("Z", "+00:00")
        parsed = _dt.datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)
_AI_EXECUTION_COUNT = 0


def _candles_from_market_events(events: list[dict]) -> list[dict]:
    """Extract OHLCV candle dicts from market_data signal_events raw_payload.

    Each event's raw_payload may already be a dict (parsed by get_signal_events)
    or a JSON string. Missing or non-numeric fields are silently skipped.
    """
    candles: list[dict] = []
    for ev in events:
        payload = ev.get("raw_payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                continue
        if not isinstance(payload, dict):
            continue
        o = payload.get("open")
        h = payload.get("high")
        lo = payload.get("low")
        c = payload.get("close") if payload.get("close") is not None else payload.get("latest_price")
        v = payload.get("volume")
        ts = payload.get("timestamp") or ev.get("fetched_at", "")
        if any(x is None for x in (o, h, lo, c, v)) or not ts:
            continue
        candles.append({
            "timestamp": str(ts),
            "open": o,
            "high": h,
            "low": lo,
            "close": c,
            "volume": v,
        })
    return candles


def _classify_event_source_kind(event_id: str) -> str:
    """Map a signal_events.event_id prefix to a market-data source kind.

    Known prefixes:
      ohlcv_*        — real backfill (yfinance) → CANONICAL_SQLITE
      seed_ohlcv_*   — deterministic offline demo seed → SEED
      everything else — UNKNOWN
    """
    eid = str(event_id or "")
    if eid.startswith("seed_ohlcv_") or eid.startswith("seed_"):
        return _freshness.SEED
    if eid.startswith("ohlcv_") or eid.startswith("global_ohlcv_"):
        return _freshness.CANONICAL_SQLITE
    return _freshness.UNKNOWN


def _resolve_source_kind(events: list[dict], candles: list[dict]) -> str:
    """Pick the most-trusted source_kind across the contributing events."""
    if not events and not candles:
        return _freshness.UNKNOWN
    kinds = {_classify_event_source_kind(ev.get("event_id", "")) for ev in events}
    # Trust hierarchy: CANONICAL_SQLITE wins if any real candle is present,
    # otherwise SEED, otherwise UNKNOWN.
    if _freshness.CANONICAL_SQLITE in kinds:
        return _freshness.CANONICAL_SQLITE
    if _freshness.SEED in kinds:
        return _freshness.SEED
    if kinds:
        # Single bucket — return whatever is there.
        return next(iter(kinds))
    return _freshness.UNKNOWN


def _normalise_ts(value: Any) -> str | None:
    """Normalise an ISO-8601 timestamp to a single comparable form (UTC, Z).

    Used by the defensive freshness-vs-summary integrity check so that
    "2026-05-14T16:00:00Z" and "2026-05-14T16:00:00+00:00" compare equal.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = _dt.datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return text  # fall back to raw string compare
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_and_dedupe_candles(
    raw_candles: list[dict],
    limit: int,
) -> list[dict]:
    """Build the single canonical candle list both freshness and engine consume.

    Steps:
      1. Run each candle through the chart-structure engine's strict
         OHLCV validation (rejects negative prices, high < low, etc.).
         This is the SAME validator the engine runs internally — so the
         engine cannot later drop a row the freshness gate already saw.
      2. Deduplicate per-date.  For multiple rows on the same calendar
         day (e.g., a backfill row plus an intraday refresh), keep the
         one with the highest timestamp string.  Daily-candle datasets
         must have exactly one row per date.
      3. Sort ascending and tail-slice to ``limit``.

    Returning an empty list is a valid outcome — callers handle it via
    the existing NO_LOCAL_OHLCV / freshness-MISSING branches.
    """
    try:
        try:
            from scripts.chart_structure_engine import _parse_candle as _engine_parse
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from chart_structure_engine import _parse_candle as _engine_parse  # type: ignore[no-redef]
    except Exception:  # pragma: no cover - defensive
        # If we cannot import the validator, fall back to the raw list
        # rather than crash.  The engine will validate again downstream
        # and the integrity check will catch divergence.
        return sorted(raw_candles, key=lambda c: str(c.get("timestamp", "")))[-limit:]

    validated: list[dict] = []
    for c in raw_candles:
        parsed = _engine_parse(c)
        if parsed is None:
            continue
        validated.append({
            "timestamp": parsed.timestamp,
            "open": parsed.open,
            "high": parsed.high,
            "low": parsed.low,
            "close": parsed.close,
            "volume": parsed.volume,
        })

    # Per-date dedupe: keep the lexicographically-latest timestamp for
    # each calendar day.  ISO-8601 timestamps sort correctly as strings.
    by_date: dict[str, dict] = {}
    for c in validated:
        date_key = str(c["timestamp"])[:10]
        existing = by_date.get(date_key)
        if existing is None or str(c["timestamp"]) > str(existing["timestamp"]):
            by_date[date_key] = c

    deduped = sorted(by_date.values(), key=lambda c: str(c["timestamp"]))
    if limit > 0 and len(deduped) > limit:
        deduped = deduped[-limit:]
    return deduped


def _internal_consistency_error_response(
    *,
    base: dict[str, Any],
    symbol: str,
    candle_count: int,
    freshness: dict[str, Any],
    linked_event_id: str | None,
    summary_latest_utc: str | None,
    freshness_latest_utc: str | None,
) -> dict[str, Any]:
    """Build a blocking response for internal candle-timestamp mismatch.

    Triggered when the freshness gate and the engine's OHLCV summary
    disagree on which candle is "latest".  We refuse to ship a normal
    verdict over inconsistent fields — the operator gets a clear
    HUMAN_REVIEW_PRICE_MISMATCH directive instead.
    """
    reason = (
        f"Internal latest_candle_utc mismatch: freshness reports "
        f"{freshness_latest_utc} but OHLCV summary reports {summary_latest_utc}. "
        "Refusing to render a normal verdict over internally inconsistent fields."
    )
    return {
        **base,
        "ok": False,
        "symbol": symbol,
        "input_symbol": symbol,
        "source_event_id": linked_event_id,
        "candle_count": candle_count,
        "chart_state": "INTERNAL_DATA_CONSISTENCY_ERROR",
        "advisory_summary": reason,
        "suggested_next_step": "HUMAN_REVIEW_PRICE_MISMATCH",
        "freshness": freshness,
        "data_freshness_status": freshness.get("data_freshness_status"),
        "freshness_gate": "BLOCK",
        "latest_candle_utc": freshness.get("latest_candle_utc"),
        "data_age_days": freshness.get("data_age_days"),
        "source_kind": freshness.get("source_kind"),
        "report": None,
        "price_truth_status": "INTERNAL_DATA_CONSISTENCY_ERROR",
        "price_truth_reason": reason,
    }


def _stale_safe_response(
    *,
    base: dict[str, Any],
    symbol: str,
    candle_count: int,
    freshness: dict[str, Any],
    linked_event_id: str | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a freshness-blocked response that NEVER leaks a normal verdict.

    Used when ``freshness_gate == BLOCK`` (ancient / stale / mock-or-demo).
    The advisory_summary + suggested_next_step are stale-aware and the
    `report` field is set to None so the frontend cannot render the usual
    OHLCV summary tiles over fixture data.
    """
    advisory = _freshness.stale_advisory_summary(
        symbol=symbol, freshness=freshness,
    )
    payload: dict[str, Any] = {
        **base,
        "ok": False,
        "symbol": symbol,
        "input_symbol": symbol,
        "source_event_id": linked_event_id,
        "candle_count": candle_count,
        "chart_state": "STALE_DATA_BLOCKED",
        "advisory_summary": advisory["advisory_summary"],
        "suggested_next_step": advisory["suggested_next_step"],
        "freshness": freshness,
        "data_freshness_status": freshness.get("data_freshness_status"),
        "freshness_gate": freshness.get("freshness_gate"),
        "latest_candle_utc": freshness.get("latest_candle_utc"),
        "data_age_days": freshness.get("data_age_days"),
        "source_kind": freshness.get("source_kind"),
        "report": None,
    }
    if extra:
        payload.update(extra)
    return payload


_CURRENCY_SUFFIX_MAP: dict[str, str] = {
    # India
    ".NS": "INR", ".BO": "INR",
    # Europe
    ".DE": "EUR", ".PA": "EUR", ".AS": "EUR", ".MI": "EUR", ".MC": "EUR",
    ".BR": "EUR", ".LS": "EUR", ".HE": "EUR", ".VI": "EUR", ".IR": "EUR",
    ".F": "EUR", ".BE": "EUR", ".HM": "EUR", ".MU": "EUR", ".SG": "EUR",
    # United Kingdom
    ".L": "GBP", ".IL": "GBP",
    # Other developed markets
    ".TO": "CAD", ".V": "CAD", ".AX": "AUD", ".NZ": "NZD",
    ".HK": "HKD", ".T": "JPY", ".KS": "KRW", ".KQ": "KRW",
    ".SW": "CHF", ".ST": "SEK", ".OL": "NOK", ".CO": "DKK",
    ".SS": "CNY", ".SZ": "CNY", ".TW": "TWD", ".SI": "SGD",
    ".BK": "THB", ".JK": "IDR", ".KL": "MYR",
    # Latin America
    ".MX": "MXN", ".SA": "BRL", ".SN": "CLP", ".BA": "ARS",
    # Africa / Middle East
    ".JO": "ZAR", ".TA": "ILS",
}


def _resolve_display_currency(
    symbol: str,
    quote_currency: str | None,
    security_meta: dict | None,
) -> tuple[str | None, str]:
    """Return (display_currency, currency_source).

    Resolution order — first hit wins:
      1. ``PROVIDER``                — currency the quote source returned
      2. ``MARKET_METADATA``         — currency stamped in global_securities
      3. ``SYMBOL_SUFFIX_FALLBACK``  — best-effort suffix guess
      4. ``UNKNOWN``                 — give up and label the value plain

    Never hardcodes $ or INR.  ``SYMBOL_SUFFIX_FALLBACK`` is only used
    when neither provider nor market metadata is available.
    """
    if quote_currency and str(quote_currency).strip():
        return str(quote_currency).strip().upper(), "PROVIDER"

    if isinstance(security_meta, dict):
        cur = security_meta.get("currency") or security_meta.get("currency_code")
        if cur and str(cur).strip():
            return str(cur).strip().upper(), "MARKET_METADATA"

    sym = str(symbol or "").strip().upper()
    if not sym:
        return None, "UNKNOWN"

    for suffix, cur in _CURRENCY_SUFFIX_MAP.items():
        if sym.endswith(suffix):
            return cur, "SYMBOL_SUFFIX_FALLBACK"

    # Crypto / FX pair convention: SOMETHING-FIAT3 → fiat3.
    if "-" in sym:
        parts = sym.split("-")
        if len(parts) == 2 and len(parts[1]) == 3 and parts[1].isalpha():
            return parts[1], "SYMBOL_SUFFIX_FALLBACK"

    # Bare ticker with no suffix is almost always a US listing on yfinance.
    if "." not in sym and "-" not in sym:
        return "USD", "SYMBOL_SUFFIX_FALLBACK"

    return None, "UNKNOWN"


def _get_chart_structure(
    symbol: str,
    source_event_id: str | None = None,
    limit: int = 100,
    db_path=None,
) -> dict:
    """Fetch market_data signal events for *symbol*, adapt to candles, run engine.

    Returns an advisory-only chart structure report. Never places orders.
    Safety invariants are always present in the returned dict.
    Importable without FastAPI — no web framework dependency.
    """
    _safe_base = {
        "advisory_status": _ADVISORY_STATUS,
        "execution_gate": "LOCKED",
        "human_review_required": True,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": False,
        "broker_order_id": "NONE",
    }
    try:
        try:
            from scripts.persistence import get_signal_events, get_signal_events_for_symbol
        except ModuleNotFoundError:
            from persistence import get_signal_events, get_signal_events_for_symbol  # type: ignore

        try:
            from scripts.chart_structure_engine import analyze_chart_structure
        except ModuleNotFoundError:
            from chart_structure_engine import analyze_chart_structure  # type: ignore

        symbol_upper = symbol.strip().upper()

        # Try to resolve market-metadata currency early so the response
        # always carries `latest_daily_close_currency` / `display_currency`
        # even when the engine never runs.
        security_meta: dict | None = None
        try:
            try:
                from scripts.symbol_normalizer import normalize_symbol
            except ModuleNotFoundError:  # pragma: no cover - script-style fallback
                from symbol_normalizer import normalize_symbol  # type: ignore[no-redef]
            norm_kwargs: dict = {}
            if db_path is not None:
                norm_kwargs["db_path"] = db_path
            norm = normalize_symbol(symbol_upper, **norm_kwargs)
            security_meta = norm.get("security")
        except Exception:
            security_meta = None

        # Pull a generous window of events ordered by candle timestamp DESC
        # (see persistence.get_signal_events_for_symbol — the sort key is
        # the embedded raw_payload.timestamp, NOT fetched_at).  We grab
        # ``limit * 6`` (min 600) so we can dedupe seed-vs-real candles by
        # date and still have at least ``limit`` real ones left.
        kwargs: dict = {
            "symbol": symbol_upper,
            "source_name": "market_data",
            "limit": max(limit * 6, 600),
        }
        if db_path is not None:
            kwargs["db_path"] = db_path

        events = get_signal_events_for_symbol(**kwargs)

        linked_event_id: str | None = None
        if source_event_id:
            matched = [ev for ev in events if ev.get("event_id") == source_event_id]
            if not matched:
                ge_kwargs: dict = {"limit": limit * 5}
                if db_path is not None:
                    ge_kwargs["db_path"] = db_path
                broader = get_signal_events(**ge_kwargs)
                matched = [ev for ev in broader if ev.get("event_id") == source_event_id]
            if matched:
                linked_event_id = matched[0].get("event_id")

        # Split real-backfill events from seed/demo events by event_id prefix.
        # Real backfill uses ``ohlcv_*`` (and ``global_ohlcv_*``); the demo
        # seeder uses ``seed_ohlcv_*``.
        real_evts = [
            ev for ev in events
            if str(ev.get("event_id", "")).startswith(("ohlcv_", "global_ohlcv_"))
        ]
        seed_evts = [
            ev for ev in events
            if str(ev.get("event_id", "")).startswith(("seed_ohlcv_", "seed_"))
        ]

        if real_evts:
            real_candles = _candles_from_market_events(real_evts)
            real_dates = {c["timestamp"][:10] for c in real_candles}
            extra_seed = [
                c for c in _candles_from_market_events(seed_evts)
                if c["timestamp"][:10] not in real_dates
            ]
            merged_raw = real_candles + extra_seed
            # Source-kind reflects that we've got at least one real backfill row.
            source_kind = _freshness.CANONICAL_SQLITE
        else:
            merged_raw = _candles_from_market_events(seed_evts or events)
            # No real backfill rows → either pure seed/demo or an unknown
            # provenance bucket.  classify accordingly so the freshness gate
            # can refuse to render a normal verdict over fixture data.
            source_kind = _resolve_source_kind(seed_evts or events, merged_raw)

        # Single source of truth: validate, dedupe by date, sort, and
        # tail-slice ONCE.  Both the freshness gate and the engine
        # receive the same `selected_candles` list — their notions of
        # "latest candle" must agree by construction.
        selected_candles = _validate_and_dedupe_candles(merged_raw, limit=limit)

        if not selected_candles:
            canonical_symbol = symbol_upper
            try:
                norm_for_empty = normalize_symbol(  # type: ignore[name-defined]
                    symbol_upper,
                    **({"db_path": db_path} if db_path is not None else {}),
                )
                canonical_symbol = norm_for_empty.get("canonical_symbol", symbol_upper)
                if security_meta is None:
                    security_meta = norm_for_empty.get("security")
            except Exception:
                pass

            discovery_cmd = (
                f"python scripts/global_security_master_discovery.py --symbols {canonical_symbol} --write"
            )
            backfill_cmd = (
                f"python scripts/backfill_global_ohlcv.py --symbols {canonical_symbol} --period max --interval 1d --write"
            )

            freshness = _freshness.evaluate(
                candles=[], source_kind=source_kind, now=_resolve_as_of_now(),
            )
            display_cur, cur_source = _resolve_display_currency(
                canonical_symbol, None, security_meta,
            )
            return {
                **_safe_base,
                "ok": False,
                "reason": "NO_LOCAL_OHLCV",
                "can_bootstrap": True,
                "message": (
                    f"No local OHLCV candles found for {canonical_symbol}."
                ),
                "execution_mode": "HUMAN_ONLY",
                "symbol": canonical_symbol,
                "input_symbol": symbol_upper,
                "source_event_id": linked_event_id,
                "candle_count": 0,
                "chart_state": "INSUFFICIENT_DATA",
                "advisory_summary": (
                    f"No OHLCV candle data available for {canonical_symbol}. "
                    f"Click 'Yes, download data' to discover + backfill from the UI, "
                    f"or run manually: {discovery_cmd}  &&  {backfill_cmd}"
                ),
                "suggested_next_step": "DATA_REFRESH_REQUIRED",
                "freshness": freshness,
                "data_freshness_status": freshness.get("data_freshness_status"),
                "freshness_gate": freshness.get("freshness_gate"),
                "latest_candle_utc": freshness.get("latest_candle_utc"),
                "data_age_days": freshness.get("data_age_days"),
                "source_kind": freshness.get("source_kind"),
                "discovery_command": discovery_cmd,
                "backfill_command": backfill_cmd,
                "security": security_meta,
                "display_currency": display_cur,
                "currency_source": cur_source,
                "latest_daily_close_currency": display_cur,
                "report": None,
            }

        # Freshness gate — block ancient / stale / mock-or-demo datasets
        # BEFORE running the chart structure engine.  This prevents the
        # frontend from ever seeing a normal "TRENDING_UP" verdict over
        # 2004 candles.
        freshness = _freshness.evaluate(
            candles=selected_candles, source_kind=source_kind,
            now=_resolve_as_of_now(),
        )
        if freshness.get("freshness_gate") == _freshness.BLOCK:
            return _stale_safe_response(
                base=_safe_base,
                symbol=symbol_upper,
                candle_count=len(selected_candles),
                freshness=freshness,
                linked_event_id=linked_event_id,
            )

        report = analyze_chart_structure(
            selected_candles, symbol=symbol_upper, source="market_data",
        )
        report_dict = report.to_dict()

        summary_block = report_dict.get("summary") or {}
        summary_latest_utc = summary_block.get("latest_timestamp")
        freshness_latest_utc = freshness.get("latest_candle_utc")

        # Defensive integrity check: by construction `selected_candles`
        # is the single source of truth so these two timestamps MUST be
        # equal.  If they ever drift (e.g., the engine adds new
        # filtering downstream), block the response loudly rather than
        # ship inconsistent fields.
        if (
            summary_latest_utc
            and freshness_latest_utc
            and _normalise_ts(summary_latest_utc) != _normalise_ts(freshness_latest_utc)
        ):
            return _internal_consistency_error_response(
                base=_safe_base,
                symbol=symbol_upper,
                candle_count=len(selected_candles),
                freshness=freshness,
                linked_event_id=linked_event_id,
                summary_latest_utc=summary_latest_utc,
                freshness_latest_utc=freshness_latest_utc,
            )

        daily_close = summary_block.get("latest_close")
        # The freshness gate and the engine summary now agree — both
        # report the same timestamp.  Pass that one canonical value to
        # the price-truth layer so it can fold in the Yahoo quote.
        canonical_latest_utc = summary_latest_utc or freshness_latest_utc

        try:
            try:
                from scripts.chart_structure_price_truth import compute_price_truth
            except ModuleNotFoundError:  # pragma: no cover
                from chart_structure_price_truth import compute_price_truth  # type: ignore[no-redef]
            price_truth = compute_price_truth(
                symbol=symbol_upper,
                daily_close=daily_close,
                daily_candle_utc=canonical_latest_utc,
                freshness_latest_utc=freshness_latest_utc,
            )
        except Exception as exc:  # pragma: no cover - defensive
            price_truth = {
                "price_truth_status": "QUOTE_UNAVAILABLE",
                "price_truth_reason": (
                    f"price-truth enrichment failed: {type(exc).__name__}"
                ),
                "suggested_next_step": "WATCH_ONLY",
                "latest_daily_close": daily_close,
                "latest_daily_candle_utc": canonical_latest_utc,
            }

        quote_currency = price_truth.get("latest_quote_currency")
        display_cur, cur_source = _resolve_display_currency(
            symbol_upper, quote_currency, security_meta,
        )

        return {
            **_safe_base,
            "symbol": symbol_upper,
            "source_event_id": linked_event_id,
            "candle_count": len(selected_candles),
            "report": report_dict,
            "freshness": freshness,
            "data_freshness_status": freshness.get("data_freshness_status"),
            "freshness_gate": freshness.get("freshness_gate"),
            "latest_candle_utc": freshness.get("latest_candle_utc"),
            "data_age_days": freshness.get("data_age_days"),
            "source_kind": freshness.get("source_kind"),
            # Sprint I — generic price-truth fields.  Optional on
            # purpose so legacy frontend/test code still parses the
            # response cleanly.
            "price_truth": price_truth,
            "latest_daily_close": price_truth.get("latest_daily_close"),
            "latest_daily_candle_utc": price_truth.get("latest_daily_candle_utc"),
            "latest_quote_price": price_truth.get("latest_quote_price"),
            "latest_quote_currency": price_truth.get("latest_quote_currency"),
            "latest_quote_timestamp_utc": price_truth.get(
                "latest_quote_timestamp_utc"
            ),
            "latest_quote_source": price_truth.get("latest_quote_source"),
            "quote_freshness_status": price_truth.get("quote_freshness_status"),
            "quote_freshness_gate": price_truth.get("quote_freshness_gate"),
            "quote_age_minutes": price_truth.get("quote_age_minutes"),
            "quote_price_delta": price_truth.get("quote_price_delta"),
            "quote_price_delta_pct": price_truth.get("quote_price_delta_pct"),
            "price_truth_status": price_truth.get("price_truth_status"),
            "price_truth_reason": price_truth.get("price_truth_reason"),
            "suggested_next_step": price_truth.get("suggested_next_step"),
            # Currency resolution — symbol-agnostic, never hardcodes
            # $ or INR.  `currency_source` lets the UI label inferred
            # currencies differently if it wants to.
            "display_currency": display_cur,
            "currency_source": cur_source,
            "latest_daily_close_currency": display_cur,
            "security": security_meta,
        }

    except Exception as exc:
        return {
            **_safe_base,
            "symbol": symbol,
            "source_event_id": source_event_id,
            "candle_count": 0,
            "chart_state": "ERROR",
            "error": str(exc),
            "report": None,
        }
