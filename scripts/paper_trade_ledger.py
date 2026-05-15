"""
Paper-trade ledger — Excel/CSV-compatible rehearsal & calibration workflow.

Sprint 7B.2.  This module is the **core helper** behind three thin CLIs:

  * ``scripts/export_paper_trade_template.py``  — write a blank CSV the
    operator opens in Excel and fills in by hand.
  * ``scripts/import_paper_trades.py``          — validate and (on
    ``--write``) import a maintained CSV into ``manual_trades`` with
    ``trade_mode=PAPER``.
  * ``scripts/export_paper_trades.py``          — round-trip the current
    paper rows back to CSV for further Excel review.

Safety contract — every invariant in
``docs/ADVISORY_ONLY_SAFETY_MODEL.md`` holds here:

  PAPER_TRADE_ONLY      = True   (for every row processed by this module)
  REAL_CAPITAL_AT_RISK  = False
  BROKER_ORDER_ID       = "NONE"
  BROKER_API_CALLED     = False
  EXECUTION_PERMISSION  = False
  CAN_EXECUTE           = False
  EXECUTION_GATE        = "LOCKED"
  AI_EXECUTION_COUNT    = 0
  ADVISORY_STATUS       = "ADVISORY_ONLY"
  HUMAN_REVIEW_REQUIRED = True

Paper trades NEVER prove real-money alpha, slippage survivability, or
production readiness.  They test the *process loop*: did we capture the
reactor snapshot, did we update the outcome later, did we write a lesson.
"""
from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

# Canonical column order — frozen so Excel templates round-trip cleanly.
# Adding columns later is allowed; reordering existing ones is not.
TEMPLATE_COLUMNS: tuple[str, ...] = (
    # identity / lifecycle
    "paper_trade_id",
    "created_at",
    # decision context
    "symbol",
    "side",
    "thesis",
    "planned_entry",
    "planned_exit",
    "invalidation_level",
    "risk_notes",
    "time_horizon",
    "source_signal_id",
    # reactor-at-decision snapshot
    "reactor_state_at_decision",
    "decision_grade_energy_at_decision",
    "echo_risk_score_at_decision",
    "meltdown_risk_at_decision",
    "fusion_validity_at_decision",
    "fission_branch_clarity_at_decision",
    "operator_heat_at_decision",
    "gallardo_block_at_decision",
    "preflight_state_at_decision",
    # outcome / reconciliation (filled later)
    "outcome_status",
    "outcome_quality",
    "process_quality",
    "mistake_tags",
    "lesson",
    "journal_complete",
    "reconciled_at",
    "notes",
    # paper economics (simulation only — never real fills)
    "paper_entry_price",
    "paper_exit_price",
    "paper_return_pct",
    "paper_pnl_nominal",
    "benchmark_return_pct",
    "holding_period_days",
    "source_freshness_state_at_decision",
)

# Columns the operator MUST fill before a row can be imported.  Everything
# else (reactor snapshot, outcome, paper economics) is optional and can be
# updated later as the rehearsal completes.
_REQUIRED_FOR_IMPORT: tuple[str, ...] = (
    "paper_trade_id",
    "symbol",
    "side",
    "thesis",
)

# Columns that, if present and non-empty, signal the operator is trying to
# log a broker/real-money artifact through the paper ledger.  This module
# refuses those rows — paper ledger is rehearsal, not a back door.
_FORBIDDEN_COLUMN_PATTERNS: tuple[str, ...] = (
    "broker_order_id",
    "broker_order",
    "broker_api",
    "execute_now",
    "submit_order",
    "place_order",
    "real_money",
    "real_capital",
    "execution_permission",
    "can_execute",
)

# Banned cell values (case-insensitive) — even in legal columns.
_FORBIDDEN_CELL_VALUES: tuple[str, ...] = (
    "place order",
    "submit order",
    "execute trade",
    "trade now",
    "broker api",
    "real money",
)

_OUTCOME_STATUS_ALLOWED: frozenset[str] = frozenset(
    {"", "OPEN", "WIN", "LOSS", "BREAKEVEN", "UNKNOWN"}
)


def _safety_stamps() -> dict[str, Any]:
    return {
        "advisory_status": ADVISORY_STATUS,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "broker_order_id": "NONE",
        "ai_execution_count": 0,
        "execution_permission": False,
        "can_execute": False,
        "human_review_required": True,
        # Paper-specific stamps — frozen for every payload this module emits.
        "paper_trade_only": True,
        "real_capital_at_risk": False,
        "execution_simulated_label_only": True,
    }


def _normalise_unit_score(value: Any) -> float | None:
    """Accept None/'' or a numeric in [0, 1]; anything else -> None."""
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return None
        try:
            n = float(s)
        except ValueError:
            return None
    elif isinstance(value, bool):
        return None
    elif isinstance(value, (int, float)):
        n = float(value)
    else:
        return None
    if n != n:  # NaN
        return None
    if n < 0.0 or n > 1.0:
        return None
    return n


def _normalise_bool(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "on", "t"}
    return False


def _normalise_text(value: Any, *, max_len: int = 1000) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if len(s) > max_len:
        s = s[:max_len]
    return s


def _normalise_outcome_status(value: Any) -> str:
    s = _normalise_text(value).upper()
    if s in _OUTCOME_STATUS_ALLOWED:
        return s
    return "UNKNOWN"


def _row_has_forbidden_column(row: dict[str, Any]) -> str | None:
    """Return the offending column name, or None."""
    for key in row.keys():
        lk = (key or "").strip().lower()
        for bad in _FORBIDDEN_COLUMN_PATTERNS:
            if bad in lk:
                # Only flag if the column actually carries data.  Empty
                # columns are fine (operators may have a header from a
                # broker template they aren't using).
                if _normalise_text(row.get(key)):
                    return key
    return None


def _row_has_forbidden_value(row: dict[str, Any]) -> str | None:
    for key, val in row.items():
        text = _normalise_text(val).lower()
        if not text:
            continue
        for bad in _FORBIDDEN_CELL_VALUES:
            if bad in text:
                return f"{key}: {bad!r}"
    return None


@dataclass
class PaperRowReport:
    """Per-row outcome from the import dry-run / write."""
    paper_trade_id: str
    symbol: str
    valid: bool
    imported: bool
    duplicate: bool
    rejection_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    normalised: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_trade_id": self.paper_trade_id,
            "symbol": self.symbol,
            "valid": self.valid,
            "imported": self.imported,
            "duplicate": self.duplicate,
            "rejection_reasons": list(self.rejection_reasons),
            "warnings": list(self.warnings),
            "normalised": dict(self.normalised),
        }


def write_template(
    out_path: Path,
    *,
    include_example: bool = False,
) -> dict[str, Any]:
    """Write a blank Excel-friendly CSV template at ``out_path``.

    ``include_example=True`` writes one obviously-fake example row so the
    operator can see how the columns line up.  The example row carries
    ``paper_trade_only=true`` semantics and uses non-real symbols.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    if include_example:
        rows.append({
            "paper_trade_id": "PAPER_EXAMPLE_0001",
            "created_at": "2026-01-01T09:00:00Z",
            "symbol": "EXAMPLE_TICKER",
            "side": "BUY",
            "thesis": "EXAMPLE — replace this row. Rehearsal-only / paper.",
            "planned_entry": "100.00",
            "planned_exit": "110.00",
            "invalidation_level": "95.00",
            "risk_notes": "<=1R",
            "time_horizon": "1w",
            "source_signal_id": "EXAMPLE_SIGNAL",
            "reactor_state_at_decision": "WARM_WATCH",
            "decision_grade_energy_at_decision": "0.42",
            "echo_risk_score_at_decision": "0.18",
            "meltdown_risk_at_decision": "0.21",
            "fusion_validity_at_decision": "weak_fusion",
            "fission_branch_clarity_at_decision": "0.60",
            "operator_heat_at_decision": "0.15",
            "gallardo_block_at_decision": "false",
            "preflight_state_at_decision": "OK",
            "outcome_status": "",
            "outcome_quality": "",
            "process_quality": "",
            "mistake_tags": "",
            "lesson": "",
            "journal_complete": "false",
            "reconciled_at": "",
            "notes": "Example row — delete before importing.",
            "paper_entry_price": "",
            "paper_exit_price": "",
            "paper_return_pct": "",
            "paper_pnl_nominal": "",
            "benchmark_return_pct": "",
            "holding_period_days": "",
            "source_freshness_state_at_decision": "fresh",
        })
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        # Excel reads UTF-8 + LF cleanly; Windows Excel handles CRLF too.
        writer = csv.DictWriter(fh, fieldnames=list(TEMPLATE_COLUMNS))
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return {
        "operation": "write_paper_trade_template",
        "path": str(out_path),
        "columns": list(TEMPLATE_COLUMNS),
        "example_rows_written": len(rows),
        "advisory_disclaimer": (
            "Paper-trade ledger template.  This is rehearsal data only — "
            "no broker is contacted, no order is placed, no real capital "
            "is committed.  Paper outcomes do not prove real-money edge."
        ),
        **_safety_stamps(),
    }


def _normalise_row(row: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return ``(normalised_row, warnings)`` for a single Excel-row dict.

    Always succeeds — bad fields degrade to safe defaults and produce
    warnings.  Validation/rejection happens in ``_validate_row``.
    """
    warnings: list[str] = []
    norm: dict[str, Any] = {}

    norm["paper_trade_id"] = _normalise_text(row.get("paper_trade_id"), max_len=64)
    norm["created_at"] = _normalise_text(row.get("created_at"), max_len=64)
    norm["symbol"] = _normalise_text(row.get("symbol"), max_len=32).upper()
    side = _normalise_text(row.get("side"), max_len=8).upper()
    if side not in {"BUY", "SELL", ""}:
        warnings.append(f"side coerced from {side!r} to BUY")
        side = "BUY"
    norm["side"] = side or "BUY"
    norm["thesis"] = _normalise_text(row.get("thesis"), max_len=2000)
    norm["planned_entry"] = _normalise_text(row.get("planned_entry"), max_len=64)
    norm["planned_exit"] = _normalise_text(row.get("planned_exit"), max_len=64)
    norm["invalidation_level"] = _normalise_text(row.get("invalidation_level"), max_len=128)
    norm["risk_notes"] = _normalise_text(row.get("risk_notes"), max_len=512)
    norm["time_horizon"] = _normalise_text(row.get("time_horizon"), max_len=32)
    norm["source_signal_id"] = _normalise_text(row.get("source_signal_id"), max_len=64)

    # Reactor snapshot
    norm["reactor_state_at_decision"] = _normalise_text(
        row.get("reactor_state_at_decision"), max_len=64
    )
    norm["decision_grade_energy_at_decision"] = _normalise_unit_score(
        row.get("decision_grade_energy_at_decision")
    )
    norm["echo_risk_score_at_decision"] = _normalise_unit_score(
        row.get("echo_risk_score_at_decision")
    )
    norm["meltdown_risk_at_decision"] = _normalise_unit_score(
        row.get("meltdown_risk_at_decision")
    )
    norm["fusion_validity_at_decision"] = _normalise_text(
        row.get("fusion_validity_at_decision"), max_len=64
    )
    norm["fission_branch_clarity_at_decision"] = _normalise_unit_score(
        row.get("fission_branch_clarity_at_decision")
    )
    norm["operator_heat_at_decision"] = _normalise_unit_score(
        row.get("operator_heat_at_decision")
    )
    norm["gallardo_block_at_decision"] = _normalise_bool(
        row.get("gallardo_block_at_decision")
    )
    norm["preflight_state_at_decision"] = _normalise_text(
        row.get("preflight_state_at_decision"), max_len=64
    )

    # Outcome / reconciliation
    norm["outcome_status"] = _normalise_outcome_status(row.get("outcome_status"))
    norm["outcome_quality"] = _normalise_text(row.get("outcome_quality"), max_len=64)
    norm["process_quality"] = _normalise_text(row.get("process_quality"), max_len=64)
    norm["mistake_tags"] = _normalise_text(row.get("mistake_tags"), max_len=256)
    norm["lesson"] = _normalise_text(row.get("lesson"), max_len=2000)
    norm["journal_complete"] = _normalise_bool(row.get("journal_complete"))
    norm["reconciled_at"] = _normalise_text(row.get("reconciled_at"), max_len=64)
    norm["notes"] = _normalise_text(row.get("notes"), max_len=2000)

    # Paper economics
    for k in (
        "paper_entry_price",
        "paper_exit_price",
        "paper_return_pct",
        "paper_pnl_nominal",
        "benchmark_return_pct",
        "holding_period_days",
    ):
        norm[k] = _normalise_text(row.get(k), max_len=64)
    norm["source_freshness_state_at_decision"] = _normalise_text(
        row.get("source_freshness_state_at_decision"), max_len=32
    )

    return norm, warnings


def _validate_row(
    row: dict[str, Any],
    norm: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []

    # 1) Required fields present.
    for col in _REQUIRED_FOR_IMPORT:
        if not str(norm.get(col, "")).strip():
            reasons.append(f"missing_required:{col}")

    # 2) Forbidden columns / values — paper ledger is NOT a broker shim.
    bad_col = _row_has_forbidden_column(row)
    if bad_col:
        reasons.append(f"forbidden_column:{bad_col}")
    bad_val = _row_has_forbidden_value(row)
    if bad_val:
        reasons.append(f"forbidden_value:{bad_val}")

    # 3) Side semantic.
    if norm.get("side") not in {"BUY", "SELL"}:
        reasons.append("invalid_side")

    return reasons


def _generate_event_id(paper_trade_id: str, symbol: str) -> str:
    """Build a deterministic event_id so re-imports collide in the
    INSERT-OR-IGNORE path on the manual_trades.trade_id key."""
    return f"PAPER:{paper_trade_id or 'NOID'}"


def import_paper_trades(
    csv_path: Path,
    *,
    write: bool = False,
    log_manual_trade_fn: Any = None,
) -> dict[str, Any]:
    """Validate (and optionally write) a CSV ledger of paper trades.

    ``write=False`` is dry-run: nothing is persisted, but every row is
    normalised and classified.  ``write=True`` calls
    ``signal_inbox_api.log_manual_trade`` for each valid row with
    ``trade_mode='PAPER'``.

    Dependency-injection point: ``log_manual_trade_fn`` lets tests pass a
    stub.  Production callers should leave it ``None`` so the real helper
    is resolved lazily (keeps this module importable without persistence).
    """
    rows_seen = 0
    rows_valid = 0
    rows_imported = 0
    rows_rejected = 0
    rows_duplicate = 0
    seen_ids: set[str] = set()
    per_row: list[dict[str, Any]] = []
    warnings_global: list[str] = []

    if not csv_path.exists():
        return {
            "operation": "import_paper_trades",
            "path": str(csv_path),
            "rows_seen": 0,
            "rows_valid": 0,
            "rows_imported": 0,
            "rows_rejected": 0,
            "rows_duplicate": 0,
            "items": [],
            "warnings": ["csv_missing"],
            "write": bool(write),
            **_safety_stamps(),
        }

    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            warnings_global.append("csv_empty_or_unreadable")
        else:
            missing_headers = [c for c in _REQUIRED_FOR_IMPORT if c not in reader.fieldnames]
            if missing_headers:
                warnings_global.append(
                    "missing_required_headers:" + ",".join(missing_headers)
                )

        for raw_row in reader or []:
            rows_seen += 1
            norm, row_warnings = _normalise_row(raw_row)
            reasons = _validate_row(raw_row, norm)

            # Deduplicate by paper_trade_id inside the file.
            pid = norm.get("paper_trade_id", "")
            is_dup = False
            if pid:
                if pid in seen_ids:
                    is_dup = True
                    reasons.append("duplicate_paper_trade_id_in_file")
                else:
                    seen_ids.add(pid)

            valid = not reasons
            imported = False

            if valid and write:
                # Lazy-resolve to avoid a hard dependency at import time.
                fn = log_manual_trade_fn
                if fn is None:
                    try:
                        from scripts.signal_inbox_api import log_manual_trade as fn  # type: ignore
                    except ModuleNotFoundError:
                        try:
                            from signal_inbox_api import log_manual_trade as fn  # type: ignore[no-redef]
                        except ModuleNotFoundError:
                            fn = None
                if fn is None:
                    warnings_global.append("log_manual_trade_unavailable")
                else:
                    try:
                        # Convert paper-template fields into log_manual_trade kwargs.
                        # `quantity` and `price` are required by log_manual_trade
                        # (>0). Paper rows often have planned but not actual fills,
                        # so we default to 1.0 / 1.0 if missing.  These are NOT real
                        # fills; they exist only to satisfy the numeric guards.
                        def _to_float(v: Any, default: float = 0.0) -> float:
                            try:
                                if v is None or v == "":
                                    return default
                                return float(v)
                            except (TypeError, ValueError):
                                return default

                        qty = _to_float(norm.get("paper_entry_price"), 0.0)
                        # Paper "quantity" is not on the template; default to 1.0
                        # so the persistence guard is happy.  PnL is tracked
                        # separately as paper_pnl_nominal (notes column for now).
                        quantity = 1.0
                        planned_entry = _to_float(norm.get("planned_entry"), 0.0)
                        if planned_entry <= 0.0:
                            planned_entry = 1.0
                        # Compose notes that preserve the paper economics.
                        notes_parts = [
                            f"[PAPER]",
                            f"planned_entry={norm.get('planned_entry') or 'n/a'}",
                            f"planned_exit={norm.get('planned_exit') or 'n/a'}",
                            f"paper_entry_price={norm.get('paper_entry_price') or 'n/a'}",
                            f"paper_exit_price={norm.get('paper_exit_price') or 'n/a'}",
                            f"paper_return_pct={norm.get('paper_return_pct') or 'n/a'}",
                            f"paper_pnl_nominal={norm.get('paper_pnl_nominal') or 'n/a'}",
                        ]
                        if norm.get("notes"):
                            notes_parts.append(f"notes={norm['notes']}")
                        combined_notes = " | ".join(notes_parts)

                        result = fn(
                            event_id=_generate_event_id(pid, norm.get("symbol", "")),
                            ticker=norm.get("symbol", "PAPER"),
                            side=norm.get("side", "BUY"),
                            quantity=quantity,
                            price=planned_entry,
                            thesis=norm.get("thesis", ""),
                            notes=combined_notes,
                            logged_by="paper_ledger_import",
                            invalidation_level=norm.get("invalidation_level", ""),
                            expected_horizon=norm.get("time_horizon", ""),
                            risk_reason=norm.get("risk_notes", ""),
                            entry_reason="",
                            exit_plan="",
                            confidence_before=None,
                            emotional_state="",
                            mistake_tags=norm.get("mistake_tags", ""),
                            lesson=norm.get("lesson", ""),
                            reactor_state_at_decision=norm.get("reactor_state_at_decision", ""),
                            decision_grade_energy_at_decision=norm.get("decision_grade_energy_at_decision"),
                            echo_risk_score_at_decision=norm.get("echo_risk_score_at_decision"),
                            meltdown_risk_at_decision=norm.get("meltdown_risk_at_decision"),
                            fusion_validity_at_decision=norm.get("fusion_validity_at_decision", ""),
                            fission_branch_clarity_at_decision=norm.get("fission_branch_clarity_at_decision"),
                            operator_heat_at_decision=norm.get("operator_heat_at_decision"),
                            gallardo_block_at_decision=norm.get("gallardo_block_at_decision", False),
                            preflight_state_at_decision=norm.get("preflight_state_at_decision", ""),
                            trade_mode="PAPER",
                        )
                        if isinstance(result, dict) and result.get("status") == "logged":
                            imported = True
                        else:
                            reasons.append("log_manual_trade_rejected")
                    except Exception as exc:
                        reasons.append(f"log_manual_trade_error:{type(exc).__name__}")

            if reasons:
                valid = False

            report = PaperRowReport(
                paper_trade_id=pid,
                symbol=norm.get("symbol", ""),
                valid=valid,
                imported=imported,
                duplicate=is_dup,
                rejection_reasons=reasons,
                warnings=row_warnings,
                normalised=norm,
            )
            per_row.append(report.to_dict())

            if valid:
                rows_valid += 1
                if imported:
                    rows_imported += 1
            else:
                rows_rejected += 1
            if is_dup:
                rows_duplicate += 1

    return {
        "operation": "import_paper_trades",
        "path": str(csv_path),
        "rows_seen": rows_seen,
        "rows_valid": rows_valid,
        "rows_imported": rows_imported,
        "rows_rejected": rows_rejected,
        "rows_duplicate": rows_duplicate,
        "items": per_row,
        "warnings": warnings_global,
        "write": bool(write),
        "advisory_disclaimer": (
            "Paper-trade import.  No broker is contacted, no order is "
            "placed, no real capital is committed.  Imported rows carry "
            "trade_mode=PAPER; calibration reports treat them as rehearsal "
            "data, not proof of real-money edge."
        ),
        **_safety_stamps(),
    }


def export_paper_trades(
    out_path: Path,
    *,
    rows: Iterable[dict[str, Any]] | None = None,
    list_manual_trades_fn: Any = None,
) -> dict[str, Any]:
    """Write current paper trades back to CSV at ``out_path``.

    If ``rows`` is provided, that is used directly (testing).  Otherwise we
    lazily resolve ``signal_inbox_api.list_manual_trades`` and filter for
    ``trade_mode='PAPER'``.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if rows is None:
        fn = list_manual_trades_fn
        if fn is None:
            try:
                from scripts.signal_inbox_api import list_manual_trades as fn  # type: ignore
            except ModuleNotFoundError:
                try:
                    from signal_inbox_api import list_manual_trades as fn  # type: ignore[no-redef]
                except ModuleNotFoundError:
                    fn = None
        if fn is None:
            payload_rows: list[dict[str, Any]] = []
        else:
            try:
                listing = fn(include_journal_quality=False)
            except TypeError:
                listing = fn()
            payload_rows = [
                t for t in (listing.get("trades") or [])
                if str(t.get("trade_mode") or "").upper() == "PAPER"
            ]
    else:
        payload_rows = list(rows)

    written = 0
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(TEMPLATE_COLUMNS))
        writer.writeheader()
        for row in payload_rows:
            out_row = {col: "" for col in TEMPLATE_COLUMNS}
            out_row["paper_trade_id"] = str(row.get("trade_id") or row.get("paper_trade_id") or "")
            out_row["created_at"] = str(row.get("executed_at") or row.get("created_at") or "")
            out_row["symbol"] = str(row.get("ticker") or row.get("symbol") or "")
            out_row["side"] = str(row.get("side") or "")
            out_row["thesis"] = str(row.get("thesis") or "")
            out_row["invalidation_level"] = str(row.get("invalidation_level") or "")
            out_row["risk_notes"] = str(row.get("risk_reason") or row.get("risk_notes") or "")
            out_row["time_horizon"] = str(row.get("expected_horizon") or row.get("time_horizon") or "")
            out_row["reactor_state_at_decision"] = str(
                row.get("reactor_state_at_decision") or ""
            )
            for k in (
                "decision_grade_energy_at_decision",
                "echo_risk_score_at_decision",
                "meltdown_risk_at_decision",
                "fission_branch_clarity_at_decision",
                "operator_heat_at_decision",
            ):
                v = row.get(k)
                out_row[k] = "" if v is None else str(v)
            out_row["fusion_validity_at_decision"] = str(
                row.get("fusion_validity_at_decision") or ""
            )
            out_row["gallardo_block_at_decision"] = (
                "true" if row.get("gallardo_block_at_decision") else "false"
            )
            out_row["preflight_state_at_decision"] = str(
                row.get("preflight_state_at_decision") or ""
            )
            out_row["mistake_tags"] = str(row.get("mistake_tags") or "")
            out_row["lesson"] = str(row.get("lesson") or "")
            out_row["notes"] = str(row.get("notes") or "")
            writer.writerow(out_row)
            written += 1

    return {
        "operation": "export_paper_trades",
        "path": str(out_path),
        "rows_exported": written,
        "advisory_disclaimer": (
            "Exported paper-trade ledger.  Paper outcomes are rehearsal "
            "data only; they do not prove real-money alpha."
        ),
        **_safety_stamps(),
    }


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "TEMPLATE_COLUMNS",
    "write_template",
    "import_paper_trades",
    "export_paper_trades",
    "PaperRowReport",
    "_normalise_row",
    "_validate_row",
    "_normalise_unit_score",
    "_normalise_bool",
    "_safe_trade_mode_value",
]


# Public alias for the safe-mode helper, in case external scripts want it.
def _safe_trade_mode_value(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"PAPER", "REAL_MANUAL", "UNKNOWN"}:
        return text
    return "REAL_MANUAL"
