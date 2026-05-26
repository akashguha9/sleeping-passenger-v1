"""Exit Review Board — per-position lifecycle aggregator.

Capital Rotation Engine — daily exit board.

Takes a list of open positions plus optional context (live-price
lookup, duplicate-exposure set, theme-slot summary, per-position
context overrides) and returns one classified row per position.

The board *runs* but never executes.  Every output carries the
advisory-only invariant: ``broker_api_called=false``,
``ai_execution_count=0``, ``human_action_required`` flags only.

Pure module
-----------
- No DB / filesystem / network / broker calls / AI execution.
- Importing has no side effects.
"""
from __future__ import annotations

from typing import Any, Iterable

try:
    from scripts.economic_exposure import (
        detect_duplicate_economic_exposure,
        normalize_economic_exposure,
    )
    from scripts.portfolio_lifecycle import (
        ALL_EXIT_STATUSES,
        EXIT_DATA_BLOCKED,
        EXIT_HOLD_OK,
        EXIT_NOW,
        EXIT_PARTIAL_TP_NOW,
        EXIT_RUNNER_EXIT_REVIEW,
        EXIT_RUNNER_HOLD,
        EXIT_STALE_REVIEW,
        EXIT_TRIM_REVIEW,
        classify_position,
    )
    from scripts.theme_slot_accounting import (
        STATUS_OVER_CAP,
        position_is_weakest_in_overcrowded_theme,
        theme_slot_summary,
    )
except ModuleNotFoundError:  # pragma: no cover — flat-layout fallback
    from economic_exposure import (  # type: ignore
        detect_duplicate_economic_exposure,
        normalize_economic_exposure,
    )
    from portfolio_lifecycle import (  # type: ignore
        ALL_EXIT_STATUSES,
        EXIT_DATA_BLOCKED,
        EXIT_HOLD_OK,
        EXIT_NOW,
        EXIT_PARTIAL_TP_NOW,
        EXIT_RUNNER_EXIT_REVIEW,
        EXIT_RUNNER_HOLD,
        EXIT_STALE_REVIEW,
        EXIT_TRIM_REVIEW,
        classify_position,
    )
    from theme_slot_accounting import (  # type: ignore
        STATUS_OVER_CAP,
        position_is_weakest_in_overcrowded_theme,
        theme_slot_summary,
    )


def _ticker_label(position: dict[str, Any]) -> str:
    return str(
        position.get("normalized_ticker")
        or position.get("ticker")
        or position.get("symbol")
        or ""
    )


def _enrich_with_live_data(
    position: dict[str, Any],
    live_price_lookup: dict[str, float] | None,
) -> dict[str, Any]:
    """Return a shallow copy of ``position`` with live_price filled if known.

    ``live_price_lookup`` is a ticker → price dict supplied by the
    caller; we never fetch a price ourselves.  Lookup keys are tried in
    several forms (raw ticker, normalized ticker, economic-exposure key).
    """
    enriched = dict(position)
    if not live_price_lookup:
        return enriched
    if enriched.get("live_price") not in (None, "", 0):
        return enriched
    for key in (
        enriched.get("normalized_ticker"),
        enriched.get("ticker"),
        enriched.get("symbol"),
    ):
        if key is None:
            continue
        if key in live_price_lookup:
            enriched["live_price"] = live_price_lookup[key]
            return enriched
        # case-insensitive
        for raw_key, value in live_price_lookup.items():
            if str(raw_key).strip().upper() == str(key).strip().upper():
                enriched["live_price"] = value
                return enriched
    return enriched


def build_exit_review_board(
    positions: Iterable[dict[str, Any]],
    *,
    live_price_lookup: dict[str, float] | None = None,
    position_context: dict[str, dict[str, Any]] | None = None,
    standard_position_size: float | None = None,
) -> dict[str, Any]:
    """Run lifecycle classification across all positions.

    Parameters
    ----------
    positions
        Iterable of position dicts as produced by
        ``scripts.daily_payload.load_verified_holdings``.
    live_price_lookup
        Optional ``{ticker: price}`` map.  When absent, positions that
        lack ``live_price`` will fall into ``DATA_BLOCKED`` — which is
        the *correct* honest behaviour: we can't grade a position
        without a current price.
    position_context
        Optional per-ticker context overrides (thesis hints, hard
        invalidation flags, custom relative-strength scores).
    standard_position_size
        Optional override for the slot-weight calculation in the theme
        accounting helper.

    Returns
    -------
    dict with:
      - ``rows``                  list of classified positions
      - ``counts``                dict of exit_status -> int
      - ``duplicate_exposures``   list of duplicate records
      - ``theme_slot_summary``    output of ``theme_slot_summary``
      - safety stamps
    """
    rows_in = [p for p in (positions or []) if isinstance(p, dict)]
    enriched = [_enrich_with_live_data(p, live_price_lookup) for p in rows_in]

    # Precompute theme summary so we know which positions are weakest in
    # overcrowded themes (feeds back into TRIM_REVIEW context).
    slot_kwargs: dict[str, Any] = {}
    if standard_position_size is not None:
        slot_kwargs["standard_position_size"] = standard_position_size
    theme_summary = theme_slot_summary(enriched, **slot_kwargs)
    over_cap_themes = set(theme_summary.get("over_cap_themes") or [])

    duplicates = detect_duplicate_economic_exposure(enriched)
    duplicate_keys = {d["economic_exposure_key"] for d in duplicates}

    ctx_overrides = dict(position_context or {})

    classified: list[dict[str, Any]] = []
    for pos in enriched:
        ticker = _ticker_label(pos)
        per_ticker_ctx = dict(ctx_overrides.get(ticker, {}))
        exposure_key = normalize_economic_exposure(ticker)
        is_dup = exposure_key in duplicate_keys
        weakest = position_is_weakest_in_overcrowded_theme(
            ticker, theme_summary.get("themes") or []
        )
        # Theme hard cap exceeded for *any* theme this ticker occupies?
        position_themes = set()
        for row in theme_summary.get("themes") or []:
            if ticker in (row.get("holdings") or []):
                position_themes.add(row.get("theme"))
        theme_hard_cap_breached = bool(over_cap_themes & position_themes)

        per_ticker_ctx.setdefault("duplicate_economic_exposure", is_dup)
        per_ticker_ctx.setdefault("weakest_in_overcrowded_theme", weakest)
        per_ticker_ctx.setdefault("theme_hard_cap_exceeded", theme_hard_cap_breached)

        classified.append(classify_position(pos, per_ticker_ctx))

    counts: dict[str, int] = {status: 0 for status in ALL_EXIT_STATUSES}
    for row in classified:
        status = row["exit_status"]
        counts[status] = counts.get(status, 0) + 1

    # A position can land in EXIT_NOW for several reasons (stop breach,
    # phantom row, thesis broken).  ``stop_breach_count`` should be the
    # narrow count of price-vs-stop breaches so the capacity score
    # weights it correctly.
    stop_breach_count = sum(
        1
        for r in classified
        if "stop_breach" in (r.get("reason_codes") or [])
    )
    phantom_open_count = sum(
        1
        for r in classified
        if "phantom_or_do_not_manage_row" in (r.get("reason_codes") or [])
    )
    live_price_missing_count = sum(
        1
        for r in classified
        if r.get("exit_status") == EXIT_DATA_BLOCKED
        and (
            "live_price" in (r.get("missing_fields") or [])
            or any(
                str(code).startswith("data_blocked:") and "live_price" in str(code)
                for code in r.get("reason_codes") or []
            )
        )
    )

    return {
        "rows": classified,
        "counts": counts,
        "duplicate_exposures": duplicates,
        "duplicate_exposure_count": len(duplicates),
        "theme_slot_summary": theme_summary,
        "stop_breach_count": stop_breach_count,
        "phantom_open_count": phantom_open_count,
        "live_price_missing_count": live_price_missing_count,
        "partial_tp_due_count": counts.get(EXIT_PARTIAL_TP_NOW, 0),
        "runner_exit_review_count": counts.get(EXIT_RUNNER_EXIT_REVIEW, 0),
        "data_blocked_count": counts.get(EXIT_DATA_BLOCKED, 0),
        "stale_review_count": counts.get(EXIT_STALE_REVIEW, 0),
        "trim_review_count": counts.get(EXIT_TRIM_REVIEW, 0),
        "runner_hold_count": counts.get(EXIT_RUNNER_HOLD, 0),
        "hold_ok_count": counts.get(EXIT_HOLD_OK, 0),
        "open_position_count": len(classified),
        "advisory_only": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_execution_required": True,
        "execution_permission": "LOCKED",
    }


__all__ = ["build_exit_review_board"]
