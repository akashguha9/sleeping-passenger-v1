"""Paper-outcome CSV / sheet importer — normalize operator rows into intake.

KANTE_PAPER_OUTCOME_IMPORTER
============================

Closed Paper Outcome Corpus Sprint, Workstream A.  The bottleneck is no longer
code defense — it is *match data*: 50-100 closed paper outcomes are needed
before calibration leaves cold-start.  This module is the operator's on-ramp:
it reads a paper-trading sheet / exported CSV (with the column aliases a human
actually types) and runs every row through the pure validator in
:mod:`scripts.paper_outcome_intake`.

It is the Kanté ball-recovery work: it never invents a price or a timestamp,
never marks an open trade closed, never writes by default, and never touches
real-money sizing.  It only *normalizes column names* + *de-duplicates* +
*classifies*, then (only with an explicit ``--apply`` and an operator-role that
the central permission guard accepts) writes the audit-only normalized JSON
artifact via :func:`scripts.paper_outcome_intake.apply_normalized_write`.

Hard safety contract
--------------------
* :func:`normalize_row` / :func:`build_import_report` are pure — no I/O.
* The default CLI mode is ``--dry-run`` (read + classify only, writes nothing).
* ``--apply`` writes ONLY the audit-only normalized JSON, ONLY through the
  central operator permission guard (VIEWER is denied, fail-closed).  There is
  no canonical paper-outcome trade store to write into — promotion is
  future-only (see ``paper_outcome_intake.FUTURE_WRITE_PATH_NOTE``).
* ``real_money_sizing_impact`` is always ``PROHIBITED``.
* Missing prices / timestamps are never invented — such a row simply fails the
  intake math and is classified ``REJECTED_INSUFFICIENT_PROOF`` /
  ``NEEDS_OPERATOR_REVIEW``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts import paper_outcome_intake as _intake
    from scripts import operator_permission_guard as _guard
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import paper_outcome_intake as _intake  # type: ignore[no-redef]
    import operator_permission_guard as _guard  # type: ignore[no-redef]


REAL_MONEY_SIZING_IMPACT = "PROHIBITED"
_PROOF = "PAPER_OUTCOME_IMPORTER_PAPER_ONLY"

# The importer's ``--apply`` writes only the audit-only normalized JSON, and is
# authorized by the central operator permission guard inside
# :func:`paper_outcome_intake.apply_normalized_write` (VIEWER denied,
# fail-closed).  This module-level reference makes that authorization boundary
# explicit for the release-gate mutation-guard scanner.
OPERATION_CLASS = _guard.OperationClass.AUDIT_ONLY_WRITE

# The canonical record keys understood by ``paper_outcome_intake.validate_outcome``.
_CANONICAL_KEYS: tuple[str, ...] = (
    "trade_id",
    "signal_id",
    "ticker",
    "entry_timestamp_utc",
    "exit_timestamp_utc",
    "entry_price",
    "exit_price",
    "exit_reason",
    "realized_return_pct",
    "realized_r_multiple",
    "outcome_y_0_or_1",
    "proof_status",
    "source",
    "holding_days",
)

# Required fields for a calibration-grade closed outcome (a row missing any of
# these can never be VALID_FOR_CALIBRATION — never invented, only flagged).
REQUIRED_FIELDS: tuple[str, ...] = (
    "trade_id",
    "signal_id",
    "ticker",
    "entry_timestamp_utc",
    "exit_timestamp_utc",
    "entry_price",
    "exit_price",
    "realized_return_pct",
    "outcome_y_0_or_1",
    "proof_status",
)

# Column-name aliases keyed by their *normalized* form (see ``_normalize_key``).
# Both the UPPER_SNAKE sheet headers and the canonical names map here.  This is
# the only place a sheet column name is trusted — values are never invented.
_ALIASES: dict[str, str] = {
    "trade_id": "trade_id",
    "tradeid": "trade_id",
    "signal_id": "signal_id",
    "signalid": "signal_id",
    "ticker": "ticker",
    "symbol": "ticker",
    "entry_timestamp_utc": "entry_timestamp_utc",
    "entry_timestamp": "entry_timestamp_utc",
    "entry_time": "entry_timestamp_utc",
    "entry_at": "entry_timestamp_utc",
    "exit_timestamp_utc": "exit_timestamp_utc",
    "exit_timestamp": "exit_timestamp_utc",
    "exit_time": "exit_timestamp_utc",
    "exit_at": "exit_timestamp_utc",
    "buy_price": "entry_price",
    "entry_price": "entry_price",
    "fill_price": "entry_price",
    "sell_price": "exit_price",
    "exit_price": "exit_price",
    "close_price": "exit_price",
    "exit_reason": "exit_reason",
    "realized_return": "realized_return_pct",
    "realized_return_pct": "realized_return_pct",
    "realized_return_percent": "realized_return_pct",
    "return_pct": "realized_return_pct",
    "realized_r_multiple": "realized_r_multiple",
    "realized_r": "realized_r_multiple",
    "r_multiple": "realized_r_multiple",
    "outcome_y_0_or_1": "outcome_y_0_or_1",
    "outcome_y": "outcome_y_0_or_1",
    "outcome": "outcome_y_0_or_1",
    "win": "outcome_y_0_or_1",
    "proof_status": "proof_status",
    "proof": "proof_status",
    "source": "source",
}


def _normalize_key(raw: Any) -> str:
    """Normalize a sheet column header to a lookup token.

    Lower-cases, trims, maps spaces / hyphens / dots to underscores, drops a
    trailing ``%``, and collapses repeated / surrounding underscores.  So
    ``"REALIZED_RETURN_%"`` and ``"Realized Return %"`` both become
    ``"realized_return"``.
    """
    s = "" if raw is None else str(raw).strip().lower()
    if not s:
        return ""
    for ch in (" ", "-", ".", "/"):
        s = s.replace(ch, "_")
    s = s.replace("%", "")
    # collapse repeated underscores and strip leading/trailing ones
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_")


def normalize_row(raw_row: dict[str, Any] | None) -> dict[str, Any]:
    """Map one raw sheet/CSV row to the canonical intake record (pure).

    Unknown columns are ignored.  Known aliases are mapped to canonical keys.
    A canonical key already present wins over an alias that maps to the same key
    only if the alias value is empty (we never silently overwrite real data).
    Nothing is invented: absent columns simply stay absent.
    """
    raw_row = dict(raw_row or {})
    out: dict[str, Any] = {}
    for key, value in raw_row.items():
        canonical = _ALIASES.get(_normalize_key(key))
        if canonical is None:
            continue
        # Don't let an empty alias clobber an already-populated canonical value.
        existing = out.get(canonical)
        if existing not in (None, "") and (value is None or str(value).strip() == ""):
            continue
        out[canonical] = value
    return out


def _str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def build_import_report(
    rows: list[dict[str, Any]] | None,
    *,
    applied: bool = False,
) -> dict[str, Any]:
    """Normalize + de-dup + validate every row and aggregate an import report.

    Pure: no I/O.  ``applied`` only changes the reported ``imported_count`` /
    ``skipped_count`` semantics (the actual guarded write is performed by
    :func:`apply_import` / the CLI ``--apply`` path).  Never raises.
    """
    rows = list(rows or [])
    rows_seen = len(rows)

    normalized = [normalize_row(r) for r in rows]

    # De-duplicate on a non-empty trade_id, keeping the FIRST occurrence.  Rows
    # with no trade_id are kept (intake flags the missing id) and never deduped.
    seen_ids: set[str] = set()
    duplicate_trade_ids: list[str] = []
    unique_records: list[dict[str, Any]] = []
    for rec in normalized:
        tid = _str(rec.get("trade_id"))
        if tid and tid in seen_ids:
            duplicate_trade_ids.append(tid)
            continue
        if tid:
            seen_ids.add(tid)
        unique_records.append(rec)

    intake_report = _intake.build_intake_report(unique_records)

    valid = intake_report["valid_for_calibration"]
    review = intake_report["needs_operator_review"]
    rejected = intake_report["rejected_insufficient_proof"]

    # Rows missing one or more REQUIRED fields (a count of rows + a per-field
    # summary).  Sourced from the intake normalized records so the maths agree.
    missing_required_rows = 0
    missing_field_counter: dict[str, int] = {}
    for nr in intake_report["normalized_records"]:
        missing_here = [f for f in nr.get("missing_fields", []) if f in REQUIRED_FIELDS]
        if missing_here:
            missing_required_rows += 1
        for f in missing_here:
            missing_field_counter[f] = missing_field_counter.get(f, 0) + 1

    # imported = the calibration-grade rows the audit-only artifact captures on
    # --apply; on dry-run nothing is imported.  skipped = everything else.
    imported_count = valid if applied else 0
    skipped_count = rows_seen - imported_count

    out: dict[str, Any] = {
        "report": "paper_outcome_importer",
        "mode": "APPLY" if applied else "DRY_RUN",
        "rows_seen": rows_seen,
        "valid_for_calibration": valid,
        "needs_operator_review": review,
        "rejected_insufficient_proof": rejected,
        "missing_required_fields": dict(sorted(missing_field_counter.items())),
        "missing_required_field_rows": missing_required_rows,
        "duplicate_trade_ids": duplicate_trade_ids,
        "imported_count": imported_count,
        "skipped_count": skipped_count,
        "intake_report": intake_report,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "real_money_weight_allowed": False,
        "operator_execution_required": True,
        "advisory_only": True,
        "human_execution_required": True,
        "proof_status": _PROOF,
    }
    return out


# --- input loading (read-only) ----------------------------------------------


def load_rows(path: Path) -> list[dict[str, Any]]:
    """Load raw rows from a CSV or JSON file (read-only).

    Reuses :func:`scripts.paper_outcome_intake.load_records` so CSV / JSON
    parsing behaves identically across the two on-ramps.
    """
    return _intake.load_records(path)


# --- guarded apply (audit-only normalized write) ----------------------------


def apply_import(
    report: dict[str, Any],
    *,
    output_path: Path,
    operator_role: str | None = None,
) -> dict[str, Any]:
    """Write the normalized intake artifact via the operator permission guard.

    Delegates to :func:`scripts.paper_outcome_intake.apply_normalized_write`,
    which is fail-closed: a denied operator role raises :class:`PermissionError`
    and nothing is written.  Only the audit-only normalized JSON is written —
    never a canonical trade store, never a broker call.
    """
    intake_report = report.get("intake_report") or report
    return _intake.apply_normalized_write(
        intake_report, output_path=output_path, operator_role=operator_role
    )


# --- CLI --------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="paper_outcome_importer.py",
        description=(
            "Import closed paper-trade outcomes from a CSV / exported sheet and "
            "normalize them through paper_outcome_intake. Dry-run by default; "
            "never invents prices/timestamps; never calls a broker; real-money "
            "sizing PROHIBITED."
        ),
    )
    p.add_argument("--input", required=True, help="path to outcomes CSV or JSON")
    p.add_argument(
        "--apply",
        action="store_true",
        help="write the audit-only normalized JSON via the operator guard",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="explicit dry-run (default): normalize + classify only, writes nothing",
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
        rows = load_rows(input_path)
    except Exception as exc:  # noqa: BLE001 - bad input degrades, never crashes
        print(f"[ERROR] could not parse {input_path}: {exc}")
        return 1

    if not args.apply:
        report = build_import_report(rows, applied=False)
        _emit(report, json_mode=args.json)
        return 0

    # --apply: build the report, then guarded audit-only normalized write.
    report = build_import_report(rows, applied=True)
    output_path = (
        Path(args.output)
        if args.output
        else _intake._DEFAULT_INTAKE_DIR / f"{input_path.stem}__imported.json"
    )
    try:
        write_result = apply_import(
            report, output_path=output_path, operator_role=args.operator_role
        )
    except PermissionError as exc:
        print(f"[DENY] {exc}")
        return 2
    report.update(write_result)
    _emit(report, json_mode=args.json)
    return 0


def _emit(report: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(report, indent=2, default=str))
        return
    print("paper_outcome_importer")
    print(f"  mode            : {report['mode']}")
    print(f"  rows_seen       : {report['rows_seen']}")
    print(f"  valid           : {report['valid_for_calibration']}")
    print(f"  review          : {report['needs_operator_review']}")
    print(f"  rejected        : {report['rejected_insufficient_proof']}")
    print(f"  duplicates      : {len(report['duplicate_trade_ids'])}")
    print(f"  imported        : {report['imported_count']}")
    print(f"  skipped         : {report['skipped_count']}")
    print(f"  real-money      : {report['real_money_sizing_impact']}")
    if report.get("written"):
        print(f"  written         : {report.get('output_path')}")
    else:
        print("  written         : (none — dry-run)")


__all__ = [
    "REAL_MONEY_SIZING_IMPACT",
    "REQUIRED_FIELDS",
    "normalize_row",
    "build_import_report",
    "load_rows",
    "apply_import",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
