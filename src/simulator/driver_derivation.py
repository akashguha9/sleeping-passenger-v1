"""Driver state derived from actual journal logs, not self-report.

The driver-license system scores violations; until now the caller had to
confess them. This module reads the journal's own records — manual trades
and reconciliation outcomes (shapes from ``scripts/persistence.py``) — and
derives the violations mechanically:

    no_thesis_no_helmet          thesis missing/trivial on a logged trade
    entered_without_invalidation invalidation_level empty (no fire extinguisher)
    ignored_black_flag           gallardo_block_at_decision set, traded anyway
    revenge_trading              re-entry in same ticker within the revenge
                                 window after a reconciled LOSS
    oversizing_under_crash_risk  leverage_breach flagged by leverage governance
    tailgating_hype              high stated confidence with empty entry_reason

Telemetry is truth: the trade log is the only driver testimony accepted.
Derivation never blocks anything by itself — it produces the violation list
that ``driver_license.score_driver`` already consumes. ADVISORY_ONLY.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.simulator.driver_license import (
    PENALTY_HALF_LIFE_DAYS,
    score_driver,
)

REVENGE_REENTRY_WINDOW_HOURS = 48.0
TRIVIAL_TEXT_LENGTH = 10
TAILGATING_CONFIDENCE_FLOOR = 80.0

# Demotion map applied when derived danger points suspend the driver.
_DEMOTION = {
    "team_principal": "engineer",
    "engineer": "pro_driver",
    "pro_driver": "pro_am",
    "pro_am": "club_racer",
    "club_racer": "rookie",
    "rookie": "learner",
    "learner": "learner",
}


@dataclass(slots=True)
class DerivedDriverState:
    """Driver state reconstructed from journal evidence."""

    driver_id: str
    derived_points: float
    violations: list[dict[str, Any]] = field(default_factory=list)
    decay_applied: bool = True
    license_level_before: str = "learner"
    license_level_after: str = "learner"
    permission_multiplier: float = 1.0
    status: str = "clean"
    trades_examined: int = 0
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _days_since(value: Any, as_of: datetime) -> float:
    parsed = _parse_time(value)
    if parsed is None:
        return 0.0
    return max((as_of - parsed).total_seconds() / 86400.0, 0.0)


def _is_trivial(text: Any) -> bool:
    return len(str(text or "").strip()) < TRIVIAL_TEXT_LENGTH


def derive_violations(
    trades: list[dict[str, Any]],
    reconciliations: list[dict[str, Any]],
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """Derive violation records from trade + reconciliation rows.

    Each violation is ``{"type", "days_since", "trade_id", "evidence"}`` —
    directly consumable by ``score_driver`` (extra keys are ignored there).
    """
    now = as_of or datetime.now(timezone.utc)
    violations: list[dict[str, Any]] = []
    losses_by_ticker: dict[str, list[datetime]] = {}

    recon_by_trade = {str(r.get("trade_id")): r for r in reconciliations}
    for recon in reconciliations:
        if str(recon.get("outcome_status", "")).upper() != "LOSS":
            continue
        trade_match = [
            t for t in trades if str(t.get("trade_id")) == str(recon.get("trade_id"))
        ]
        ticker = str(trade_match[0].get("ticker", "")).upper() if trade_match else ""
        loss_time = _parse_time(recon.get("reconciled_at"))
        if ticker and loss_time:
            losses_by_ticker.setdefault(ticker, []).append(loss_time)

    for trade in trades:
        # Cancelled rows are housekeeping, not behavior.
        if str(trade.get("reconciliation_status", "")).upper().startswith("CANCELLED"):
            continue
        trade_id = str(trade.get("trade_id", ""))
        executed_at = trade.get("executed_at")
        days = _days_since(executed_at, now)

        def _flag(violation_type: str, evidence: str) -> None:
            violations.append(
                {
                    "type": violation_type,
                    "days_since": days,
                    "trade_id": trade_id,
                    "evidence": evidence,
                }
            )

        if _is_trivial(trade.get("thesis")):
            _flag("no_thesis_no_helmet", "thesis missing or trivial on logged trade")
        if _is_trivial(trade.get("invalidation_level")):
            _flag(
                "entered_without_invalidation",
                "invalidation_level empty — no fire extinguisher on entry",
            )
        if bool(trade.get("gallardo_block_at_decision")):
            _flag(
                "ignored_black_flag",
                "gallardo block was active at decision time; trade logged anyway",
            )
        if bool(trade.get("leverage_breach")):
            _flag(
                "oversizing_under_crash_risk",
                f"leverage {trade.get('leverage')} breached ceiling "
                f"{trade.get('leverage_ceiling')}",
            )
        confidence = trade.get("confidence_before")
        if (
            confidence is not None
            and float(confidence) >= TAILGATING_CONFIDENCE_FLOOR
            and _is_trivial(trade.get("entry_reason"))
        ):
            _flag(
                "tailgating_hype",
                f"confidence_before {confidence} with empty entry_reason",
            )

        # Revenge re-entry: same ticker bought again inside the window
        # after a reconciled loss that happened BEFORE this entry.
        ticker = str(trade.get("ticker", "")).upper()
        entry_time = _parse_time(executed_at)
        if ticker and entry_time:
            for loss_time in losses_by_ticker.get(ticker, []):
                hours_after_loss = (entry_time - loss_time).total_seconds() / 3600.0
                if 0.0 < hours_after_loss <= REVENGE_REENTRY_WINDOW_HOURS:
                    own_recon = recon_by_trade.get(trade_id)
                    own_recon_time = (
                        _parse_time(own_recon.get("reconciled_at"))
                        if own_recon
                        else None
                    )
                    # Skip if "loss" IS this trade's own reconciliation.
                    if own_recon_time is not None and own_recon_time == loss_time:
                        continue
                    _flag(
                        "revenge_trading",
                        f"re-entered {ticker} {hours_after_loss:.1f}h after a "
                        "reconciled loss",
                    )
                    break

    return violations


def derive_driver_state(
    trades: list[dict[str, Any]],
    reconciliations: list[dict[str, Any]],
    *,
    driver_id: str = "local_user",
    license_level: str = "learner",
    as_of: datetime | None = None,
    penalty_half_life_days: float = PENALTY_HALF_LIFE_DAYS,
    process_scores: dict[str, float] | None = None,
) -> DerivedDriverState:
    """Full derived driver state: violations -> decayed points -> license.

    ``process_scores`` optionally carries the six positive process
    components for ``score_driver``; absent components default to 0 so the
    derivation stays conservative.
    """
    violations = derive_violations(trades, reconciliations, as_of=as_of)
    process = process_scores or {}
    driver = score_driver(
        license_level=license_level,
        violations=violations,
        thesis_logging_quality=float(process.get("thesis_logging_quality", 0.0)),
        invalidation_compliance=float(process.get("invalidation_compliance", 0.0)),
        position_sizing_discipline=float(
            process.get("position_sizing_discipline", 0.0)
        ),
        confirmation_patience=float(process.get("confirmation_patience", 0.0)),
        replay_audit_completion=float(process.get("replay_audit_completion", 0.0)),
        calibration_honesty=float(process.get("calibration_honesty", 0.0)),
        penalty_half_life_days=penalty_half_life_days,
    )

    license_after = driver.license_level
    if driver.status in ("suspended", "black_flag"):
        license_after = _DEMOTION.get(driver.license_level, "learner")

    return DerivedDriverState(
        driver_id=str(driver_id),
        derived_points=driver.danger_points,
        violations=violations,
        decay_applied=True,
        license_level_before=driver.license_level,
        license_level_after=license_after,
        permission_multiplier=driver.permission_multiplier,
        status=driver.status,
        trades_examined=len(trades),
    )
