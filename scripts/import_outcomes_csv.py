"""Import resolved trade outcomes (paper / real-manual / backtest) from CSV.

Validates provenance and required fields, then idempotently stores the raw
inputs in ``imported_outcomes``. Eligibility/quality/labels are recomputed via
outcome_evidence.build_outcome so the math is centralised and honest.

Provenance rules (non-negotiable):
  * REAL_MANUAL_TRADE / PAPER_TRADE require a trade_id or signal_id.
  * IMPORTED_BACKTEST should normally come from the backtest runner; a manual
    CSV is accepted but WARNED.
  * SYNTHETIC_FIXTURE is rejected in runtime mode (tests only).

Read-only journal evidence. No broker, no execution.

Usage:
    python scripts/import_outcomes_csv.py templates/outcome_import_template.csv
    python scripts/import_outcomes_csv.py outcomes.csv --dry-run --json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts import outcome_evidence as oe
    from scripts import ohlcv_import_contract as contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import outcome_evidence as oe  # type: ignore[no-redef]
    import ohlcv_import_contract as contract  # type: ignore[no-redef]

VALID_SOURCE_TYPES = {
    oe.REAL_MANUAL_TRADE, oe.PAPER_TRADE, oe.IMPORTED_BACKTEST, oe.SYNTHETIC_FIXTURE,
}
_REQUIRES_ID = {oe.REAL_MANUAL_TRADE, oe.PAPER_TRADE}


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _outcome_id(row: dict[str, Any]) -> str:
    st = str(row.get("source_type", "")).upper()
    key = (str(row.get("trade_id") or row.get("signal_id") or "").strip()
           or f"{row.get('ticker','')}@{row.get('opened_at','')}")
    return f"{st}:{key}"


def validate_outcome_row(row: dict[str, Any], *, runtime_mode: bool = True) -> tuple[bool, str | None]:
    st = str(row.get("source_type", "")).strip().upper()
    if st not in VALID_SOURCE_TYPES:
        return False, "invalid_source_type"
    if st == oe.SYNTHETIC_FIXTURE and runtime_mode:
        return False, "synthetic_fixture_rejected_in_runtime"
    if st in _REQUIRES_ID and not (str(row.get("trade_id") or "").strip()
                                   or str(row.get("signal_id") or "").strip()):
        return False, "missing_trade_or_signal_id"
    if _num(row.get("entry_price")) is not None and _num(row.get("entry_price")) <= 0:
        return False, "non_positive_entry_price"
    lev = _num(row.get("leverage"))
    if lev is not None and lev < 1.0:
        return False, "leverage_below_1"
    oa = contract.parse_date(row.get("opened_at"))
    ca = contract.parse_date(row.get("closed_at"))
    if oa and ca and ca < oa:
        return False, "closed_before_opened"
    return True, None


def build_outcome_from_row(row: dict[str, Any]) -> oe.OutcomeEvidence:
    return oe.build_outcome(
        outcome_id=_outcome_id(row),
        source_type=str(row.get("source_type", "")).upper(),
        ticker=str(row.get("ticker", "")),
        direction=str(row.get("direction", "UNKNOWN")),
        signal_id=str(row.get("signal_id") or "") or None,
        trade_id=str(row.get("trade_id") or "") or None,
        opened_at=row.get("opened_at"),
        closed_at=row.get("closed_at"),
        entry_price=_num(row.get("entry_price")),
        exit_price=_num(row.get("exit_price")),
        realized_pnl=_num(row.get("realized_pnl")),
        capital_at_risk=_num(row.get("capital_at_risk")),
        leverage=_num(row.get("leverage")) or 1.0,
        score_at_entry=_num(row.get("score_at_entry")),
        archetype=str(row.get("archetype") or "") or None,
        signal_class=str(row.get("signal_class") or "") or None,
    )


def import_outcomes(
    rows: list[dict[str, Any]],
    *,
    runtime_mode: bool = True,
    dry_run: bool = False,
    db_path: Path | None = None,
) -> dict[str, Any]:
    accepted_rows: list[dict[str, Any]] = []
    outcomes: list[oe.OutcomeEvidence] = []
    rejected: list[dict[str, Any]] = []
    warnings: list[str] = []
    for i, r in enumerate(rows):
        ok, reason = validate_outcome_row(r, runtime_mode=runtime_mode)
        if not ok:
            rejected.append({"row_index": i, "reason": reason, "ticker": r.get("ticker")})
            continue
        if str(r.get("source_type", "")).upper() == oe.IMPORTED_BACKTEST:
            warnings.append(f"row {i}: IMPORTED_BACKTEST via manual CSV — prefer the backtest runner")
        o = build_outcome_from_row(r)
        outcomes.append(o)
        accepted_rows.append({**r, "outcome_id": o.outcome_id})

    written = 0
    if not dry_run and accepted_rows:
        try:
            try:
                from scripts import persistence
            except ModuleNotFoundError:  # pragma: no cover - script-style fallback
                import persistence  # type: ignore[no-redef]
            path = db_path if db_path is not None else persistence.DB_PATH
            written = persistence.insert_imported_outcomes(accepted_rows, db_path=path)
        except Exception as exc:  # pragma: no cover - defensive
            warnings.append(f"write_error: {exc}")

    prov = oe.provenance_counts(outcomes)
    return {
        "report": "outcome_import",
        "rows_read": len(rows),
        "accepted_count": len(accepted_rows),
        "rejected_count": len(rejected),
        "rejected": rejected[:50],
        "warnings": warnings[:50],
        "rows_written": written,
        "dry_run": dry_run,
        "provenance": prov,
        "advisory_only": "ADVISORY_ONLY",
        "human_execution_required": True,
        "broker_api_called": False,
    }


def import_outcomes_file(path: Path, **kwargs) -> dict[str, Any]:
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    return import_outcomes(rows, **kwargs)


def rebuild_imported_outcomes(db_path: Path | None = None) -> list[oe.OutcomeEvidence]:
    """Rebuild OutcomeEvidence from the stored imported_outcomes rows."""
    try:
        from scripts import persistence
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        import persistence  # type: ignore[no-redef]
    path = db_path if db_path is not None else persistence.DB_PATH
    rows = persistence.get_imported_outcome_rows(path)
    return [build_outcome_from_row(r) for r in rows]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Import resolved trade outcomes CSV.")
    p.add_argument("csv_path", type=Path)
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-synthetic", action="store_true", help="TEST ONLY.")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rep = import_outcomes_file(args.csv_path, runtime_mode=not args.allow_synthetic,
                               dry_run=args.dry_run, db_path=args.db_path)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        p = rep["provenance"]
        print(f"read {rep['rows_read']}, accepted {rep['accepted_count']}, "
              f"rejected {rep['rejected_count']}, written {rep['rows_written']}")
        print(f"provenance: real={p['real_n']} paper={p['paper_n']} "
              f"backtest={p['backtest_n']} eligible={p['eligible_n']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "validate_outcome_row", "build_outcome_from_row", "import_outcomes",
    "import_outcomes_file", "rebuild_imported_outcomes", "VALID_SOURCE_TYPES",
]
