"""Paper-outcome intake — validate + normalize closed paper trades.

KANTE_PAPER_OUTCOME_INTAKE
==========================

Kanté Ceiling Push II, Workstream A.  The invisible defensive-midfield work
that turns a pile of operator-entered closed paper trades into a clean,
auditable corpus *before* anything reaches calibration / Moltbook.

This module is the goalkeeper-of-data: it never invents an outcome, never
writes by default, never touches a broker, and never changes real-money
sizing.  It only reads candidate rows, checks their internal maths, and
classifies each one so a human can decide what is calibration-worthy.

Hard safety contract
--------------------
* :func:`validate_outcome` / :func:`build_intake_report` are pure — no I/O.
* The default CLI mode is ``--dry-run`` (read + classify only, writes nothing).
* ``--apply`` writes ONLY the normalized JSON to an audit-only intake store
  under ``runtime/`` and ONLY through the central operator permission guard.
  There is no canonical paper-outcome trade store to write into, so this
  module deliberately does NOT invent one (see ``FUTURE_WRITE_PATH_NOTE``):
  the canonical-store write path is future-only.
* ``real_money_sizing_impact`` is always ``PROHIBITED``.  A
  ``VALID_FOR_CALIBRATION`` verdict is a *data-quality* verdict only — it is
  never real-money readiness.
* No execution-instruction wording is ever emitted.

Maths (per the sprint spec)
---------------------------
    R_actual                     = (P_exit - P_entry) / P_entry
    realized_return_pct_expected = 100 * R_actual
    return_error                 = abs(realized_return_pct_input
                                       - realized_return_pct_expected)
    valid_return_math            = return_error <= 0.05
    outcome_y_0_or_1_expected    = 1 if realized_return_pct > 0 else 0
    holding_days_expected        = ceil((exit - entry) / 86400 seconds)

    outcome_quality_score =
          0.25 * has_required_ids
        + 0.25 * valid_price_math
        + 0.20 * valid_time_order
        + 0.15 * valid_outcome_label
        + 0.15 * valid_proof_status

    VALID_FOR_CALIBRATION     if score >= 0.90
    NEEDS_OPERATOR_REVIEW     if 0.60 <= score < 0.90
    REJECTED_INSUFFICIENT_PROOF if score < 0.60
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

# --- constants --------------------------------------------------------------

RETURN_TOLERANCE = 0.05  # percentage points

VALID_FOR_CALIBRATION = "VALID_FOR_CALIBRATION"
NEEDS_OPERATOR_REVIEW = "NEEDS_OPERATOR_REVIEW"
REJECTED_INSUFFICIENT_PROOF = "REJECTED_INSUFFICIENT_PROOF"

REAL_MONEY_SIZING_IMPACT = "PROHIBITED"
_PROOF = "PAPER_OUTCOME_INTAKE_PAPER_ONLY"

# Sources an operator may legitimately enter a closed paper outcome from.
ALLOWED_SOURCES: tuple[str, ...] = ("MANUAL_PAPER", "SHEET_IMPORT", "RECONCILIATION")

# proof_status values that are advisory/paper-safe (a closed paper trade whose
# fill + outcome have been confirmed by a human or a reconciliation pass).  An
# empty / unknown proof_status is NOT paper-safe.
ALLOWED_PROOF_STATUSES: tuple[str, ...] = (
    "PAPER_VERIFIED",
    "PAPER_RECONCILED",
    "OPERATOR_CONFIRMED",
    "SHEET_VERIFIED",
    "RECONCILED",
)

# There is no canonical paper-outcome *trade* store; the audit-only normalized
# intake artifact lives here and is never treated as canonical truth.
FUTURE_WRITE_PATH_NOTE = (
    "No canonical paper-outcome trade store exists yet. --apply writes an "
    "audit-only normalized JSON artifact under runtime/paper_outcome_intake/ "
    "via the operator permission guard. Promotion into a canonical calibration "
    "store is future-only and human-gated."
)
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_INTAKE_DIR = _REPO_ROOT / "runtime" / "paper_outcome_intake"
_OPERATION_NAME = "paper_outcome_intake_apply"


# --- helpers ----------------------------------------------------------------


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _parse_ts(value: Any) -> datetime | None:
    """Parse an ISO-8601 UTC timestamp; tolerate a trailing ``Z``."""
    s = _str(value)
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _expected_return_pct(entry: float | None, exit_: float | None) -> float | None:
    if entry is None or exit_ is None or entry <= 0:
        return None
    return 100.0 * (exit_ - entry) / entry


# --- pure validator ---------------------------------------------------------


def validate_outcome(record: dict[str, Any]) -> dict[str, Any]:
    """Validate + normalize a single closed paper-outcome record (pure).

    Returns a normalized dict carrying the five validity sub-checks, the
    derived expected values, ``outcome_quality_score``, the
    ``intake_classification`` label, a per-record ``missing_fields`` list, and
    the unconditional advisory / real-money-prohibited stamps.  Never raises.
    """
    rec = dict(record or {})

    trade_id = _str(rec.get("trade_id"))
    signal_id = _str(rec.get("signal_id"))
    ticker = _str(rec.get("ticker"))
    entry_price = _float(rec.get("entry_price"))
    exit_price = _float(rec.get("exit_price"))
    realized_return_pct = _float(rec.get("realized_return_pct"))
    realized_r_multiple = _float(rec.get("realized_r_multiple"))
    outcome_y = rec.get("outcome_y_0_or_1")
    proof_status = _str(rec.get("proof_status")).upper()
    source = _str(rec.get("source")).upper()
    exit_reason = _str(rec.get("exit_reason"))

    entry_ts = _parse_ts(rec.get("entry_timestamp_utc"))
    exit_ts = _parse_ts(rec.get("exit_timestamp_utc"))

    missing_fields: list[str] = []
    if not trade_id:
        missing_fields.append("trade_id")
    if not signal_id:
        missing_fields.append("signal_id")
    if not ticker:
        missing_fields.append("ticker")
    if entry_price is None:
        missing_fields.append("entry_price")
    if exit_price is None:
        missing_fields.append("exit_price")
    if entry_ts is None:
        missing_fields.append("entry_timestamp_utc")
    if exit_ts is None:
        missing_fields.append("exit_timestamp_utc")
    if realized_return_pct is None:
        missing_fields.append("realized_return_pct")
    if outcome_y in (None, ""):
        missing_fields.append("outcome_y_0_or_1")
    if not proof_status:
        missing_fields.append("proof_status")

    # --- derived / expected values
    expected_return_pct = _expected_return_pct(entry_price, exit_price)
    return_error: float | None = None
    if expected_return_pct is not None and realized_return_pct is not None:
        return_error = abs(realized_return_pct - expected_return_pct)

    outcome_y_expected: int | None = None
    if realized_return_pct is not None:
        outcome_y_expected = 1 if realized_return_pct > 0 else 0

    holding_days_expected: int | None = None
    if entry_ts is not None and exit_ts is not None:
        delta_seconds = (exit_ts - entry_ts).total_seconds()
        if delta_seconds >= 0:
            holding_days_expected = math.ceil(delta_seconds / 86400.0)

    # --- five validity sub-checks (each 0/1)
    has_required_ids = bool(trade_id and ticker and signal_id)

    valid_price_math = bool(
        entry_price is not None
        and exit_price is not None
        and entry_price > 0
        and exit_price > 0
        and return_error is not None
        and return_error <= RETURN_TOLERANCE
    )

    valid_time_order = bool(
        entry_ts is not None
        and exit_ts is not None
        and exit_ts >= entry_ts
    )

    valid_outcome_label = bool(
        outcome_y_expected is not None
        and _str(outcome_y) != ""
        and _outcome_int(outcome_y) == outcome_y_expected
    )

    valid_proof_status = bool(
        proof_status in ALLOWED_PROOF_STATUSES
        and (source == "" or source in ALLOWED_SOURCES)
    )

    outcome_quality_score = _clip(
        0.25 * float(has_required_ids)
        + 0.25 * float(valid_price_math)
        + 0.20 * float(valid_time_order)
        + 0.15 * float(valid_outcome_label)
        + 0.15 * float(valid_proof_status),
        0.0,
        1.0,
    )

    if outcome_quality_score >= 0.90:
        classification = VALID_FOR_CALIBRATION
    elif outcome_quality_score >= 0.60:
        classification = NEEDS_OPERATOR_REVIEW
    else:
        classification = REJECTED_INSUFFICIENT_PROOF

    out: dict[str, Any] = {
        "trade_id": trade_id,
        "signal_id": signal_id,
        "ticker": ticker,
        "entry_timestamp_utc": _str(rec.get("entry_timestamp_utc")),
        "exit_timestamp_utc": _str(rec.get("exit_timestamp_utc")),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "holding_days_input": _float(rec.get("holding_days")),
        "holding_days_expected": holding_days_expected,
        "realized_return_pct_input": realized_return_pct,
        "realized_return_pct_expected": (
            None if expected_return_pct is None else round(expected_return_pct, 6)
        ),
        "realized_r_multiple": realized_r_multiple,
        "return_error": None if return_error is None else round(return_error, 6),
        "outcome_y_0_or_1_input": _outcome_int(outcome_y),
        "outcome_y_0_or_1_expected": outcome_y_expected,
        "proof_status": proof_status,
        "source": source,
        # --- validity sub-checks
        "has_required_ids": has_required_ids,
        "valid_price_math": valid_price_math,
        "valid_return_math": valid_price_math,
        "valid_time_order": valid_time_order,
        "valid_outcome_label": valid_outcome_label,
        "valid_proof_status": valid_proof_status,
        "missing_fields": missing_fields,
        "outcome_quality_score": round(outcome_quality_score, 6),
        "intake_classification": classification,
        # --- unconditional safety
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "real_money_weight_allowed": False,
    }
    out.update(_contract.advisory_safety_stamps())
    out["advisory_only"] = True
    out["human_execution_required"] = True
    out["real_money_sizing_impact"] = REAL_MONEY_SIZING_IMPACT
    out["real_money_weight_allowed"] = False
    return out


def _outcome_int(value: Any) -> int | None:
    s = _str(value)
    if s == "":
        return None
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def build_intake_report(records: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Validate every record and aggregate an intake report (pure)."""
    rows = [validate_outcome(r) for r in (records or [])]
    n_total = len(rows)
    n_valid = sum(1 for r in rows if r["intake_classification"] == VALID_FOR_CALIBRATION)
    n_review = sum(
        1 for r in rows if r["intake_classification"] == NEEDS_OPERATOR_REVIEW
    )
    n_rejected = sum(
        1 for r in rows if r["intake_classification"] == REJECTED_INSUFFICIENT_PROOF
    )

    missing_counter: dict[str, int] = {}
    for r in rows:
        for f in r["missing_fields"]:
            missing_counter[f] = missing_counter.get(f, 0) + 1

    out: dict[str, Any] = {
        "report": "paper_outcome_intake",
        "records_total": n_total,
        "valid_for_calibration": n_valid,
        "needs_operator_review": n_review,
        "rejected_insufficient_proof": n_rejected,
        "missing_fields_summary": dict(sorted(missing_counter.items())),
        "normalized_records": rows,
        "future_write_path_note": FUTURE_WRITE_PATH_NOTE,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "real_money_weight_allowed": False,
        "proof_status": _PROOF,
    }
    out.update(_contract.advisory_safety_stamps())
    out["advisory_only"] = True
    out["human_execution_required"] = True
    out["operator_execution_required"] = True
    out["real_money_sizing_impact"] = REAL_MONEY_SIZING_IMPACT
    out["real_money_weight_allowed"] = False
    return out


# --- input loading (read-only) ----------------------------------------------


def load_records(path: Path) -> list[dict[str, Any]]:
    """Load candidate outcome records from a CSV or JSON file (read-only)."""
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("records") or data.get("outcomes") or []
        return [dict(r) for r in data if isinstance(r, dict)]
    # default: CSV
    reader = csv.DictReader(text.splitlines())
    return [dict(row) for row in reader]


# --- guarded apply (audit-only normalized write) ----------------------------


def apply_normalized_write(
    report: dict[str, Any],
    *,
    output_path: Path,
    operator_role: str | None = None,
) -> dict[str, Any]:
    """Write the normalized JSON via the operator permission guard.

    Audit-only: writes the normalized intake artifact (never the canonical
    trade store, never a broker call).  Fails closed — a denied permission
    raises :class:`PermissionError` and nothing is written.
    """
    try:
        from scripts import operator_permission_guard as _guard
    except ModuleNotFoundError:  # pragma: no cover
        import operator_permission_guard as _guard  # type: ignore[no-redef]

    decision = _guard.build_apply_decision(
        _OPERATION_NAME,
        _guard.OperationClass.AUDIT_ONLY_WRITE,
        str(output_path),
        operator_role=operator_role,
        reason="write audit-only normalized paper-outcome intake artifact",
    )
    # decision is allowed past this point (build_apply_decision raises on deny).
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {
        "written": True,
        "output_path": str(output_path),
        "permission_allowed": bool(decision.allowed),
        "canonical_store_written": False,
        "future_write_path_note": FUTURE_WRITE_PATH_NOTE,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
    }


# --- CLI --------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="paper_outcome_intake.py",
        description=(
            "Validate + normalize closed paper-trade outcomes before they "
            "enter calibration. Dry-run by default; never invents outcomes; "
            "never calls a broker; real-money sizing PROHIBITED."
        ),
    )
    p.add_argument("--input", required=True, help="path to outcomes CSV or JSON")
    p.add_argument(
        "--apply",
        action="store_true",
        help="write normalized JSON via the operator permission guard (audit-only)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="explicit dry-run (default): validate + classify only, writes nothing",
    )
    p.add_argument("--operator-role", default=None, help="VIEWER|OPERATOR|ADMIN")
    p.add_argument(
        "--output",
        default=None,
        help="normalized JSON output path (default runtime/paper_outcome_intake/)",
    )
    p.add_argument("--json", action="store_true", help="emit the JSON report")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] input not found: {input_path}")
        return 1
    try:
        records = load_records(input_path)
    except Exception as exc:  # noqa: BLE001 - bad input degrades, never crashes
        print(f"[ERROR] could not parse {input_path}: {exc}")
        return 1

    report = build_intake_report(records)

    if not args.apply:
        report["mode"] = "DRY_RUN"
        report["written"] = False
        _emit(report, json_mode=args.json)
        return 0

    # --apply: guarded audit-only normalized write.
    output_path = (
        Path(args.output)
        if args.output
        else _DEFAULT_INTAKE_DIR / f"{input_path.stem}__normalized.json"
    )
    try:
        write_result = apply_normalized_write(
            report, output_path=output_path, operator_role=args.operator_role
        )
    except PermissionError as exc:
        print(f"[DENY] {exc}")
        return 2
    report["mode"] = "APPLY"
    report.update(write_result)
    _emit(report, json_mode=args.json)
    return 0


def _emit(report: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(report, indent=2))
        return
    print("paper_outcome_intake")
    print(f"  mode            : {report.get('mode', 'DRY_RUN')}")
    print(f"  records         : {report['records_total']}")
    print(f"  valid           : {report['valid_for_calibration']}")
    print(f"  review          : {report['needs_operator_review']}")
    print(f"  rejected        : {report['rejected_insufficient_proof']}")
    print(f"  real-money      : {report['real_money_sizing_impact']}")
    if report.get("written"):
        print(f"  written         : {report.get('output_path')}")
    else:
        print("  written         : (none — dry-run)")


__all__ = [
    "RETURN_TOLERANCE",
    "VALID_FOR_CALIBRATION",
    "NEEDS_OPERATOR_REVIEW",
    "REJECTED_INSUFFICIENT_PROOF",
    "ALLOWED_SOURCES",
    "ALLOWED_PROOF_STATUSES",
    "FUTURE_WRITE_PATH_NOTE",
    "validate_outcome",
    "build_intake_report",
    "load_records",
    "apply_normalized_write",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
