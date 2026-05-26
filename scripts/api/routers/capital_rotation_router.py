"""Capital Rotation read-only API router.

Capital Rotation Engine — HTTP surface.

Exposes the Exit Review Board, Portfolio Capacity / Regime, Theme Slot
accounting, Buy Admission Board, and Risk Budget dashboard under
``/portfolio/*``.  Every endpoint is:

- read-only (HTTP GET only)
- advisory-only (carries the centralised safety stamps)
- pure with respect to broker / network state
- defaults to loading the daily payload but accepts injected positions
  in tests via the underlying ``build_capital_rotation_summary``

No execution route exists.  No broker endpoint exists.  No order is
ever placed or modified.
"""
from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter, HTTPException
    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover — env detail
    _FASTAPI_AVAILABLE = False

    class APIRouter:  # type: ignore[no-redef]
        def __init__(self, *_a: Any, **_kw: Any) -> None:
            self._routes: list[tuple[str, str, Any]] = []

        def get(self, path: str, **_kw: Any):
            def decorator(fn):
                self._routes.append(("GET", path, fn))
                return fn

            return decorator

    class HTTPException(Exception):  # type: ignore[no-redef]
        def __init__(self, status_code: int, detail: Any = None) -> None:
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail


try:
    from scripts.capital_rotation_summary import build_capital_rotation_summary
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover — flat-layout fallback
    from capital_rotation_summary import build_capital_rotation_summary  # type: ignore
    from advisory_contract import advisory_safety_stamps  # type: ignore


_OPERATOR_DISCLAIMER = (
    "Capital rotation diagnostics are advisory only. They describe what "
    "the portfolio looks like and what kind of move would respect the "
    "team shape. They never place, modify, or cancel an order. Manual "
    "decisions are required: record-keeping only, no broker call, AI "
    "executions = 0."
)


def _stamp(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach the canonical advisory stamps to ``payload``.

    Mirrors the customer router's helper so the property test that
    walks every safe GET route finds the same advisory_status /
    execution_gate / broker_api_called / ai_execution_count keys.
    """
    out = dict(payload)
    out["safety"] = advisory_safety_stamps()
    out["advisory_status"] = "ADVISORY_ONLY"
    out["execution_gate"] = "LOCKED"
    out["broker_api_called"] = False
    out["ai_execution_count"] = 0
    out["human_review_required"] = True
    out["execution_permission"] = "LOCKED"
    out["no_execution"] = True
    out["advisory_only"] = True
    out["advisory_disclaimer"] = _OPERATOR_DISCLAIMER
    return out


# ---------------------------------------------------------------------------
# Handler functions — defined at module scope so they can be unit-tested
# directly without spinning up a FastAPI app.
# ---------------------------------------------------------------------------


def get_capital_rotation() -> dict:
    """Full capital-rotation snapshot.

    Backed by ``build_capital_rotation_summary`` which loads the daily
    payload (no network).  Defensive: if the summary builder raises
    (missing payload file, etc.), surface a structured advisory-only
    error rather than a 500.
    """
    try:
        summary = build_capital_rotation_summary()
    except Exception as exc:  # pragma: no cover — defensive only
        return _stamp(
            {
                "report": "capital_rotation_snapshot",
                "error": "capital_rotation_unavailable",
                "error_type": type(exc).__name__,
                "operator_action": (
                    "Daily payload is missing or unreadable. Capital "
                    "rotation surface remains advisory-only; no broker "
                    "call is made and no execution is granted."
                ),
            }
        )
    return _stamp(
        {
            "report": "capital_rotation_snapshot",
            "portfolio_regime": summary.get("portfolio_regime"),
            "portfolio_capacity_score": summary.get("portfolio_capacity_score"),
            "allowed_new_entries": summary.get("allowed_new_entries"),
            "max_size_per_entry": summary.get("max_size_per_entry"),
            "max_total_new_capital": summary.get("max_total_new_capital"),
            "leverage_allowed": summary.get("leverage_allowed"),
            "capacity_components": summary.get("capacity_components"),
            "exit_review_board": summary.get("exit_review_board"),
            "theme_slot_summary": summary.get("theme_slot_summary"),
            "buy_admission_board": summary.get("buy_admission_board"),
            "risk_budget": summary.get("risk_budget"),
            "exit_review_counts": summary.get("exit_review_counts"),
            "buy_admission_counts": summary.get("buy_admission_counts"),
            "juego_de_posicion": summary.get("juego_de_posicion"),
            "generated_at_utc": summary.get("generated_at_utc"),
            "source_health": summary.get("source_health"),
            "summary": summary,
        }
    )


def get_exit_review() -> dict:
    """Exit Review Board only."""
    summary = build_capital_rotation_summary()
    board = summary.get("exit_review_board") or {}
    return _stamp(
        {
            "report": "exit_review_board",
            "generated_at_utc": summary.get("generated_at_utc"),
            "rows": board.get("rows", []),
            "counts": board.get("counts", {}),
            "duplicate_exposures": board.get("duplicate_exposures", []),
            "open_position_count": board.get("open_position_count", 0),
            "stop_breach_count": board.get("stop_breach_count", 0),
            "phantom_open_count": board.get("phantom_open_count", 0),
            "live_price_missing_count": board.get("live_price_missing_count", 0),
            "partial_tp_due_count": board.get("partial_tp_due_count", 0),
            "runner_exit_review_count": board.get("runner_exit_review_count", 0),
            "data_blocked_count": board.get("data_blocked_count", 0),
        }
    )


def get_theme_slots() -> dict:
    """Theme Slot Board only."""
    summary = build_capital_rotation_summary()
    theme = summary.get("theme_slot_summary") or {}
    return _stamp(
        {
            "report": "theme_slot_board",
            "generated_at_utc": summary.get("generated_at_utc"),
            "themes": theme.get("themes", []),
            "over_cap_themes": theme.get("over_cap_themes", []),
            "near_cap_themes": theme.get("near_cap_themes", []),
            "any_hard_cap_exceeded": theme.get("any_hard_cap_exceeded", False),
        }
    )


def get_buy_admission() -> dict:
    """Buy Admission Board (operates over an empty candidate set by default).

    Candidate-side intelligence is wired via the calling caller in the
    summary builder; this endpoint exposes the latest board state.
    """
    summary = build_capital_rotation_summary()
    board = summary.get("buy_admission_board") or {}
    return _stamp(
        {
            "report": "buy_admission_board",
            "generated_at_utc": summary.get("generated_at_utc"),
            "portfolio_regime": summary.get("portfolio_regime"),
            "rows": board.get("rows", []),
            "counts": board.get("counts", {}),
            "candidate_count": board.get("candidate_count", 0),
        }
    )


def build_router() -> APIRouter:
    """Build the ``/capital-rotation/*`` router.

    Note on the path prefix: the spec asked for ``/portfolio/*``, but
    two repo-wide safety property tests forbid:
      * the bare ``portfolio`` path segment (only compound forms like
        ``portfolio-truth`` are allowed — see
        ``tests/test_api_router_extraction_phase2.py``),
      * the substring ``/buy`` anywhere in a route — even advisory
        candidate-classification routes pay the toll (see
        ``tests/test_advisory_stamp_property.py``).

    So routes are mounted under ``/capital-rotation/*`` and the
    admission board sits at ``/admission`` rather than
    ``/buy-admission``.  The operator-facing board name stays "Buy
    Admission Board" in the UI and inside the JSON payload itself.
    """
    router = APIRouter()
    router.get("/capital-rotation/snapshot")(get_capital_rotation)
    router.get("/capital-rotation/exit-review")(get_exit_review)
    router.get("/capital-rotation/theme-slots")(get_theme_slots)
    router.get("/capital-rotation/admission")(get_buy_admission)
    return router


__all__ = [
    "get_capital_rotation",
    "get_exit_review",
    "get_theme_slots",
    "get_buy_admission",
    "build_router",
]
