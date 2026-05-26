"""Capital Rotation Summary — daily release artefact.

Capital Rotation Engine — release-output layer.

Composes the four sub-summaries (exit review, portfolio capacity,
theme slots, buy admission, risk budget) into a single release JSON
under ``runtime/release/capital_rotation_summary.json`` and writes
the four sibling files defined in Section 12.

Pure module
-----------
- No DB / network / broker calls / AI execution.
- Writes to ``runtime/release/`` only when ``write_release_files`` is
  explicitly called.  Importing the module does nothing.
- Every payload carries advisory-only invariants.

Football analogy in code
------------------------
- ``exit_review_board``     = recycling possession / dropping players
- ``theme_slot_summary``    = pitch zones / spacing
- ``portfolio_capacity``    = team shape / fitness
- ``portfolio_regime``      = press intensity (allowed / limited / off)
- ``buy_admission_board``   = positional progression / rotation
- ``risk_budget``           = goalkeeper / rest defense / cash reserve
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.runtime_common import REPO_ROOT
    from scripts.daily_payload import load_verified_holdings, load_market_snapshot
    from scripts.exit_review_board import build_exit_review_board
    from scripts.portfolio_capacity import (
        REGIME_BUY_ALLOWED,
        REGIME_BUY_LIMITED,
        REGIME_BUY_BLOCKED,
        classify_portfolio_regime,
        compute_portfolio_capacity,
        compute_risk_budget,
    )
    from scripts.buy_admission import build_buy_admission_board
    from scripts.economic_exposure import normalize_economic_exposure
    from scripts.position_context import (
        load_position_context,
        position_context_to_lifecycle_input,
    )
    from scripts.candidate_feed import (
        candidate_to_admission_input,
        load_candidate_feed,
    )
except ModuleNotFoundError:  # pragma: no cover — flat-layout fallback
    from runtime_common import REPO_ROOT  # type: ignore
    from daily_payload import (  # type: ignore
        load_verified_holdings,
        load_market_snapshot,
    )
    from exit_review_board import build_exit_review_board  # type: ignore
    from portfolio_capacity import (  # type: ignore
        REGIME_BUY_ALLOWED,
        REGIME_BUY_LIMITED,
        REGIME_BUY_BLOCKED,
        classify_portfolio_regime,
        compute_portfolio_capacity,
        compute_risk_budget,
    )
    from buy_admission import build_buy_admission_board  # type: ignore
    from economic_exposure import normalize_economic_exposure  # type: ignore
    from position_context import (  # type: ignore
        load_position_context,
        position_context_to_lifecycle_input,
    )
    from candidate_feed import (  # type: ignore
        candidate_to_admission_input,
        load_candidate_feed,
    )


RELEASE_DIR = REPO_ROOT / "runtime" / "release"

CAPITAL_ROTATION_SUMMARY_PATH = RELEASE_DIR / "capital_rotation_summary.json"
EXIT_REVIEW_SUMMARY_PATH = RELEASE_DIR / "exit_review_summary.json"
PORTFOLIO_CAPACITY_SUMMARY_PATH = RELEASE_DIR / "portfolio_capacity_summary.json"
THEME_SLOT_SUMMARY_PATH = RELEASE_DIR / "theme_slot_summary.json"
BUY_ADMISSION_SUMMARY_PATH = RELEASE_DIR / "buy_admission_summary.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safety_stamps() -> dict[str, Any]:
    return {
        "advisory_only": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_execution_required": True,
        "execution_permission": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "advisory_status": "ADVISORY_ONLY",
    }


def build_capital_rotation_summary(
    *,
    positions: Iterable[dict[str, Any]] | None = None,
    candidates: Iterable[dict[str, Any]] | None = None,
    live_price_lookup: dict[str, float] | None = None,
    source_health: str | None = None,
    cash_available: float | None = None,
    target_cash_buffer: float | None = None,
    minimum_cash_reserve: float = 0.0,
    leverage_risk_limit: float = 0.0,
    india_4x_unreviewed_count: int = 0,
    position_context: dict[str, dict[str, Any]] | None = None,
    standard_position_size: float | None = None,
    db_path: Path | None = None,
    holdings_path: Path | None = None,
    manual_trade_path: Path | None = None,
    release_dir: Path | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Compose the daily capital-rotation summary.

    Defaults:
    - if ``positions`` is omitted, auto-load via
      ``load_position_context`` so the open rows carry merged
      manual-trade context (buy / stop / leverage / thesis / horizon);
    - if ``candidates`` is omitted, auto-load via
      ``load_candidate_feed`` from the release directory so the Buy
      Admission Board is not silently empty;
    - if ``source_health`` is None, derive from the daily market
      snapshot.
    """
    position_context_status: dict[str, Any] = {
        "open_positions_loaded": 0,
        "quality_counts": {},
        "source_counts": {},
        "reason_codes": [],
        "db_available": False,
        "holdings_present": False,
    }

    if positions is None:
        loaded_ctx = load_position_context(
            db_path=db_path,
            holdings_path=holdings_path,
            manual_trade_path=manual_trade_path,
            release_dir=release_dir,
            now_utc=now_utc,
        )
        positions_list = [
            position_context_to_lifecycle_input(ctx)
            for ctx in loaded_ctx.contexts
            if str(ctx.trade_state or "").upper() == "OPEN"
        ]
        position_context_status = {
            "open_positions_loaded": loaded_ctx.open_positions_loaded,
            "quality_counts": dict(loaded_ctx.quality_counts),
            "source_counts": dict(loaded_ctx.source_counts),
            "reason_codes": list(loaded_ctx.reason_codes),
            "db_available": loaded_ctx.db_available,
            "holdings_present": loaded_ctx.holdings_present,
        }
    else:
        positions_list = list(positions)
        position_context_status = {
            "open_positions_loaded": len(positions_list),
            "quality_counts": {},
            "source_counts": {"INJECTED": len(positions_list)},
            "reason_codes": ["CONTEXT_INJECTED_BY_CALLER"],
            "db_available": False,
            "holdings_present": False,
        }

    candidate_feed_status: dict[str, Any] = {
        "status": "NO_CANDIDATE_FILE",
        "candidate_count": 0,
        "source_files": [],
        "reason_codes": ["NO_CANDIDATE_FILE"],
    }
    if candidates is None:
        feed = load_candidate_feed(
            release_dir=release_dir,
            now_utc=now_utc,
        )
        candidates_list = [
            candidate_to_admission_input(c) for c in feed.candidates
        ]
        candidate_feed_status = {
            "status": feed.feed_status,
            "candidate_count": feed.candidate_count,
            "source_files": list(feed.source_files),
            "reason_codes": list(feed.reason_codes),
            "generated_at_utc": feed.generated_at_utc,
        }
    else:
        candidates_list = list(candidates)
        candidate_feed_status = {
            "status": "CANDIDATES_INJECTED",
            "candidate_count": len(candidates_list),
            "source_files": [],
            "reason_codes": ["CANDIDATES_INJECTED_BY_CALLER"],
        }

    if source_health is None:
        snapshot = load_market_snapshot()
        source_health = str(snapshot.get("source_health") or "MISSING")

    exit_board = build_exit_review_board(
        positions_list,
        live_price_lookup=live_price_lookup,
        position_context=position_context,
        standard_position_size=standard_position_size,
    )
    theme_summary = exit_board.get("theme_slot_summary") or {}

    # Detect leveraged India exposure that lacks a review override.
    if india_4x_unreviewed_count == 0:
        for pos in positions_list:
            country = str(pos.get("country") or "").strip().lower()
            try:
                lev = float(pos.get("leverage") or 1.0)
            except (TypeError, ValueError):
                lev = 1.0
            if country == "india" and lev >= 4.0:
                ticker = (
                    pos.get("normalized_ticker")
                    or pos.get("ticker")
                    or pos.get("symbol")
                )
                ctx = (position_context or {}).get(ticker, {})
                if not ctx.get("india_4x_reviewed"):
                    india_4x_unreviewed_count += 1

    # Best-effort leveraged exposure estimate for the capacity score
    # (only used when the caller did not pass one explicitly via the
    # risk-budget config).  Computed as Σ notional · (L - 1).
    leveraged_exposure = 0.0
    for pos in positions_list:
        try:
            lev = float(pos.get("leverage") or 1.0)
        except (TypeError, ValueError):
            lev = 1.0
        try:
            notional = float(
                pos.get("money_allocated")
                or pos.get("notional")
                or 0.0
            )
        except (TypeError, ValueError):
            notional = 0.0
        if lev > 1.0 and notional > 0:
            leveraged_exposure += notional * (lev - 1.0)

    capacity = compute_portfolio_capacity(
        exit_board=exit_board,
        theme_summary=theme_summary,
        source_health=source_health,
        cash_available=cash_available,
        target_cash_buffer=target_cash_buffer,
        leveraged_risk_exposure=leveraged_exposure,
        leverage_risk_limit=leverage_risk_limit,
        india_4x_unreviewed_count=india_4x_unreviewed_count,
    )
    regime = classify_portfolio_regime(
        capacity,
        exit_board=exit_board,
        theme_summary=theme_summary,
        source_health=source_health,
        india_4x_unreviewed_count=india_4x_unreviewed_count,
    )
    risk_budget = compute_risk_budget(
        exit_board=exit_board,
        regime=regime,
        cash_available=cash_available,
        minimum_cash_reserve=minimum_cash_reserve,
    )

    held_exposures = sorted(
        {
            normalize_economic_exposure(
                p.get("normalized_ticker") or p.get("ticker") or p.get("symbol")
            )
            for p in positions_list
        }
        - {""}
    )

    admission = build_buy_admission_board(
        candidates_list,
        portfolio_regime=regime["portfolio_regime"],
        regime_max_size_per_entry=float(regime.get("max_size_per_entry") or 0.0),
        theme_rows=theme_summary.get("themes") or [],
        exit_rows=exit_board.get("rows") or [],
        held_exposures=held_exposures,
    )

    summary = {
        "report": "capital_rotation_summary",
        "generated_at_utc": _utc_now(),
        "source_health": source_health,
        "position_context_status": position_context_status,
        "candidate_feed_status": candidate_feed_status,
        "portfolio_regime": regime["portfolio_regime"],
        "portfolio_regime_reasons": regime["reason_codes"],
        "portfolio_capacity_score": capacity["portfolio_capacity_score"],
        "capacity_components": capacity["raw_components"],
        "allowed_new_entries": regime["allowed_new_entries"],
        "max_size_per_entry": regime["max_size_per_entry"],
        "max_total_new_capital": regime["max_total_new_capital"],
        "leverage_allowed": regime["leverage_allowed"],
        "exit_review_counts": exit_board.get("counts", {}),
        "open_position_count": exit_board.get("open_position_count", 0),
        "stop_breach_count": exit_board.get("stop_breach_count", 0),
        "phantom_open_count": exit_board.get("phantom_open_count", 0),
        "live_price_missing_count": exit_board.get("live_price_missing_count", 0),
        "partial_tp_due_count": exit_board.get("partial_tp_due_count", 0),
        "runner_exit_review_count": exit_board.get("runner_exit_review_count", 0),
        "data_blocked_count": exit_board.get("data_blocked_count", 0),
        "duplicate_exposure_count": exit_board.get("duplicate_exposure_count", 0),
        "duplicate_exposures": exit_board.get("duplicate_exposures", []),
        "theme_slot_summary": theme_summary,
        "exit_review_board": exit_board,
        "buy_admission_board": admission,
        "buy_admission_counts": admission.get("counts", {}),
        "risk_budget": risk_budget,
        "india_4x_unreviewed_count": india_4x_unreviewed_count,
        # Football analogy projection — surfaced so the operator can
        # see at a glance which "team-shape" lever is active today.
        "juego_de_posicion": {
            "press_intensity": regime["portfolio_regime"],
            "rest_defense_cash_unknown": risk_budget.get("cash_budget_unknown", False),
            "zones_overcrowded": theme_summary.get("over_cap_themes", []),
            "zones_near_cap": theme_summary.get("near_cap_themes", []),
            "rotation_pressure": exit_board.get("trim_review_count", 0)
            + exit_board.get("runner_exit_review_count", 0),
        },
    }
    summary.update(_safety_stamps())
    return summary


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def write_release_files(
    summary: dict[str, Any],
    *,
    release_dir: Path | None = None,
) -> dict[str, str]:
    """Write the five sibling JSONs.  Returns ``{name: path_str}``."""
    base = release_dir or RELEASE_DIR

    main = base / "capital_rotation_summary.json"
    exit_path = base / "exit_review_summary.json"
    capacity_path = base / "portfolio_capacity_summary.json"
    theme_path = base / "theme_slot_summary.json"
    admission_path = base / "buy_admission_summary.json"

    _write_json(main, summary)
    _write_json(
        exit_path,
        {
            "report": "exit_review_summary",
            "generated_at_utc": summary.get("generated_at_utc"),
            "position_context_status": summary.get("position_context_status", {}),
            "exit_review_board": summary.get("exit_review_board", {}),
            **_safety_stamps(),
        },
    )
    _write_json(
        capacity_path,
        {
            "report": "portfolio_capacity_summary",
            "generated_at_utc": summary.get("generated_at_utc"),
            "portfolio_regime": summary.get("portfolio_regime"),
            "portfolio_capacity_score": summary.get("portfolio_capacity_score"),
            "capacity_components": summary.get("capacity_components"),
            "allowed_new_entries": summary.get("allowed_new_entries"),
            "max_size_per_entry": summary.get("max_size_per_entry"),
            "max_total_new_capital": summary.get("max_total_new_capital"),
            "risk_budget": summary.get("risk_budget"),
            **_safety_stamps(),
        },
    )
    _write_json(
        theme_path,
        {
            "report": "theme_slot_summary",
            "generated_at_utc": summary.get("generated_at_utc"),
            "theme_slot_summary": summary.get("theme_slot_summary", {}),
            **_safety_stamps(),
        },
    )
    _write_json(
        admission_path,
        {
            "report": "buy_admission_summary",
            "generated_at_utc": summary.get("generated_at_utc"),
            "candidate_feed_status": summary.get("candidate_feed_status", {}),
            "buy_admission_board": summary.get("buy_admission_board", {}),
            **_safety_stamps(),
        },
    )

    return {
        "capital_rotation_summary": str(main),
        "exit_review_summary": str(exit_path),
        "portfolio_capacity_summary": str(capacity_path),
        "theme_slot_summary": str(theme_path),
        "buy_admission_summary": str(admission_path),
    }


def main() -> int:  # pragma: no cover — CLI entry point
    """CLI entry point: build summary from defaults and write release files."""
    summary = build_capital_rotation_summary()
    paths = write_release_files(summary)
    print(json.dumps({"summary_keys": sorted(summary.keys()), "paths": paths}, indent=2))
    return 0


__all__ = [
    "RELEASE_DIR",
    "CAPITAL_ROTATION_SUMMARY_PATH",
    "EXIT_REVIEW_SUMMARY_PATH",
    "PORTFOLIO_CAPACITY_SUMMARY_PATH",
    "THEME_SLOT_SUMMARY_PATH",
    "BUY_ADMISSION_SUMMARY_PATH",
    "build_capital_rotation_summary",
    "write_release_files",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
