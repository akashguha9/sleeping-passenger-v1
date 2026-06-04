"""Daily Governance / Discovery Gate — advisory-only, fail-closed.

Public surface:
    evaluate_daily_governance  — the single source of truth for the daily board.
    DailyGovernanceResult       — JSON-serialisable result container.

This package never executes trades, never places orders, never sizes
positions, and always reports the execution gate as LOCKED.
"""
from __future__ import annotations

try:
    from scripts.governance.daily_gate import evaluate_daily_governance
    from scripts.governance.models import DailyGovernanceResult
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from governance.daily_gate import evaluate_daily_governance  # type: ignore[no-redef]
    from governance.models import DailyGovernanceResult  # type: ignore[no-redef]

__all__ = ["evaluate_daily_governance", "DailyGovernanceResult"]
