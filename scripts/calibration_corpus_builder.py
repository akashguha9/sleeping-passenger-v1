"""Calibration corpus builder — CSV → intake → checklist → link → calibration.

KANTE_CALIBRATION_CORPUS_BUILDER
================================

Closed Paper Outcome Corpus Sprint, Workstream C.  This is the one dry-run-first
pipeline that turns a paper-trading sheet into calibration-grade closed
outcomes.  It chains the invisible-work modules built this sprint:

    CSV / sheet rows
      → paper_outcome_importer (alias normalize + de-dup)
      → paper_outcome_intake    (validity maths + classification)
      → operator_readiness_checklist (advisory discipline scoring)
      → paper_outcome_external_evidence_linker (snapshot link search)
      → if dry-run: report only
      → if --apply: operator permission guard
      → record_external_evidence_outcome_for_trade (advisory calibration tables)
      → corpus quality + collection readiness, before vs after

Hard safety contract (mission non-negotiables)
----------------------------------------------
* **Dry-run by default.**  ``run_corpus_build(apply=False)`` writes NOTHING.
* ``--apply`` routes through :mod:`scripts.operator_permission_guard`
  (VIEWER denied) and only ever writes the advisory ``external_evidence_outcomes``
  / ``external_evidence_calibration_buckets`` tables via the existing guarded
  :func:`record_external_evidence_outcome_for_trade`.  It NEVER mutates trades,
  open positions, or execution state, and NEVER calls a broker.
* **Open trades never record** — only intake ``VALID_FOR_CALIBRATION`` rows that
  are closed AND auto-linked to an evidence snapshot are recorded.
* **No fabricated outcomes** — a missing price/timestamp fails intake and is
  skipped; it is never invented.
* ``real_money_sizing_impact`` is always ``PROHIBITED``; recording is
  advisory-only and can never enable real-money sizing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts import paper_outcome_importer as _importer
    from scripts import paper_outcome_intake as _intake
    from scripts import operator_readiness_checklist as _checklist
    from scripts import paper_outcome_external_evidence_linker as _linker
    from scripts import external_evidence_moltbook_calibration as _cal
    from scripts import external_evidence_persistence as _eep
    from scripts import paper_outcome_collection_readiness as _readiness
    from scripts import calibration_corpus_quality as _corpus
    from scripts import operator_permission_guard as _guard
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import paper_outcome_importer as _importer  # type: ignore[no-redef]
    import paper_outcome_intake as _intake  # type: ignore[no-redef]
    import operator_readiness_checklist as _checklist  # type: ignore[no-redef]
    import paper_outcome_external_evidence_linker as _linker  # type: ignore[no-redef]
    import external_evidence_moltbook_calibration as _cal  # type: ignore[no-redef]
    import external_evidence_persistence as _eep  # type: ignore[no-redef]
    import paper_outcome_collection_readiness as _readiness  # type: ignore[no-redef]
    import calibration_corpus_quality as _corpus  # type: ignore[no-redef]
    import operator_permission_guard as _guard  # type: ignore[no-redef]


OPERATION_NAME = "calibration_corpus_builder"
OPERATION_CLASS = _guard.OperationClass.AUDIT_ONLY_WRITE

REAL_MONEY_SIZING_IMPACT = "PROHIBITED"
EXECUTION_GATE_LOCKED = "LOCKED"
_PROOF = "CALIBRATION_CORPUS_BUILDER_PAPER_ONLY"


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _checks_for_outcome(
    record: dict[str, Any], *, snapshot_linked: bool
) -> dict[str, Any]:
    """Derive the advisory operator-readiness checks for one normalized outcome.

    Only checks derivable from the imported row are asserted True; thesis /
    invalidation / benchmark / Moltbook / DIABLO checks are NOT invented — they
    stay False until a human records them, so the checklist honestly reports
    REVIEW_REQUIRED / BLOCKED.  ``real_money_sizing_prohibited`` is always True.
    """
    return {
        "entry_price_recorded": record.get("entry_price") is not None,
        "exit_price_recorded": record.get("exit_price") is not None,
        "exit_reason_recorded": bool(_s(record.get("exit_reason"))),
        "signal_id_linked": bool(_s(record.get("signal_id"))),
        "outcome_math_verified": bool(record.get("valid_price_math")),
        "external_evidence_snapshot_linked": bool(snapshot_linked),
        "real_money_sizing_prohibited": True,
    }


def _trade_outcome_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """Build the ``trade_outcome`` dict the Moltbook recorder consumes.

    The record has already passed intake (closed, with entry/exit prices + a
    valid time order), so it is marked ``closed=True`` — this never re-opens or
    fabricates an outcome; it only forwards a verified closed paper outcome.
    """
    return {
        "trade_id": _s(record.get("trade_id")),
        "signal_id": _s(record.get("signal_id")),
        "ticker": _s(record.get("ticker")),
        "entry_price": record.get("entry_price"),
        "exit_price": record.get("exit_price"),
        "entry_timestamp_utc": _s(record.get("entry_timestamp_utc")),
        "exit_timestamp_utc": _s(record.get("exit_timestamp_utc")),
        "closed": True,
        "status": "CLOSED",
        "outcome_event_type": _s(record.get("exit_reason")) or "CLOSED",
        "realized_r_multiple": record.get("realized_r_multiple"),
        "holding_days": record.get("holding_days_expected"),
    }


def run_corpus_build(
    rows: list[dict[str, Any]] | None,
    *,
    apply: bool = False,
    limit: int | None = None,
    db_path: Path | None = None,
    permission_decision: "_guard.PermissionDecision | None" = None,
) -> dict[str, Any]:
    """Run the full corpus-build pipeline (dry-run by default).

    ``apply=False`` reports only and writes nothing.  ``apply=True`` records
    valid + closed + auto-linked outcomes into the advisory calibration tables
    via the guarded Moltbook recorder.  When ``permission_decision`` is provided
    (the CLI ``--apply`` path) the write boundary is re-asserted.  Never raises
    on data problems — they degrade to skips.
    """
    if apply and permission_decision is not None:
        _guard.assert_guarded_mutation(
            permission_decision,
            operation_name=OPERATION_NAME,
            operation_class=OPERATION_CLASS,
            expected_role_floor=_guard.OperatorRole.OPERATOR,
            require_dry_run=False,
        )

    # --- before snapshot of corpus health (read-only) -----------------------
    readiness_before = _readiness.build_from_db(db_path)
    corpus_before = _corpus.build_from_db(db_path)

    # --- normalize + validate every row -------------------------------------
    import_report = _importer.build_import_report(rows, applied=False)
    normalized_records = import_report["intake_report"]["normalized_records"]

    rows_seen = import_report["rows_seen"]
    valid_for_calibration = import_report["valid_for_calibration"]

    linked_auto = 0
    linked_review = 0
    no_link = 0
    outcomes_recorded = 0
    buckets_updated = 0
    skipped_open_or_invalid = 0
    per_outcome: list[dict[str, Any]] = []

    # One shared connection for the whole apply pass so records commit together.
    owned = False
    conn = None
    if apply:
        conn = _eep._open(db_path)
        owned = True

    processed = 0
    try:
        for record in normalized_records:
            classification = record.get("intake_classification")
            # Only calibration-grade rows are eligible.  Open / under-review /
            # rejected rows are skipped — never recorded, never fabricated.
            if classification != _intake.VALID_FOR_CALIBRATION:
                skipped_open_or_invalid += 1
                continue
            if limit is not None and processed >= limit:
                break
            processed += 1

            link = _linker.link_outcome_from_db(record, db_path=db_path, conn=conn)
            best = link["best_link_classification"]
            if best == _linker.AUTO_LINK:
                linked_auto += 1
            elif best == _linker.REVIEW_LINK:
                linked_review += 1
            else:
                no_link += 1

            checks = _checks_for_outcome(
                record, snapshot_linked=(best == _linker.AUTO_LINK)
            )
            checklist = _checklist.build_operator_checklist(checks)

            recorded_here = 0
            buckets_here = 0
            record_status = "DRY_RUN_REPORT_ONLY"
            # Record only valid + auto-linked closed outcomes, and only on apply.
            if best == _linker.AUTO_LINK:
                trade_outcome = _trade_outcome_from_record(record)
                # In apply mode ``conn`` is the shared transaction; in dry-run
                # ``conn`` is None so the recorder must be pointed at db_path
                # (read-only, since apply=False writes nothing).
                result = _cal.record_external_evidence_outcome_for_trade(
                    trade_outcome, apply=apply, conn=conn, db_path=db_path
                )
                record_status = result.get("status")
                if apply:
                    recorded_here = int(result.get("records_created", 0))
                    buckets_here = int(result.get("buckets_updated", 0))
                    outcomes_recorded += recorded_here
                    buckets_updated += buckets_here

            per_outcome.append(
                {
                    "trade_id": _s(record.get("trade_id")),
                    "signal_id": _s(record.get("signal_id")),
                    "ticker": _s(record.get("ticker")),
                    "best_link_classification": best,
                    "best_link_confidence": link["best_link_confidence"],
                    "checklist_label": checklist["readiness_label"],
                    "checklist_missing_critical": checklist["missing_critical_checks"],
                    "record_status": record_status,
                    "records_created": recorded_here,
                    "buckets_updated": buckets_here,
                }
            )

        if apply and conn is not None:
            conn.commit()
    finally:
        if owned and conn is not None:
            try:
                conn.close()
            except Exception:  # pragma: no cover - defensive
                pass

    # --- after snapshot of corpus health (read-only) ------------------------
    readiness_after = _readiness.build_from_db(db_path)
    corpus_after = _corpus.build_from_db(db_path)

    out: dict[str, Any] = {
        "report": "calibration_corpus_builder",
        "mode": "APPLY" if apply else "DRY_RUN",
        "dry_run": not apply,
        "rows_seen": rows_seen,
        "valid_for_calibration": valid_for_calibration,
        "linked_auto": linked_auto,
        "linked_review": linked_review,
        "no_link": no_link,
        "skipped_open_or_invalid": skipped_open_or_invalid,
        "outcomes_recorded": outcomes_recorded,
        "buckets_updated": buckets_updated,
        "corpus_quality_before": corpus_before.get("corpus_quality_score"),
        "corpus_quality_after": corpus_after.get("corpus_quality_score"),
        "corpus_label_before": corpus_before.get("corpus_label"),
        "corpus_label_after": corpus_after.get("corpus_label"),
        "readiness_label_before": readiness_before.get("readiness_label"),
        "readiness_label_after": readiness_after.get("readiness_label"),
        "closed_paper_outcomes_before": readiness_before.get(
            "closed_paper_outcomes_count"
        ),
        "closed_paper_outcomes_after": readiness_after.get(
            "closed_paper_outcomes_count"
        ),
        "next_required_action": readiness_after.get("next_required_action"),
        "per_outcome": per_outcome,
        # Hard advisory safety stamps.
        "advisory_only": True,
        "human_execution_required": True,
        "operator_execution_required": True,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "real_money_weight_allowed": False,
        "proof_status": _PROOF,
    }
    return out


# --- CLI --------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="calibration_corpus_builder.py",
        description=(
            "Turn a paper-trade CSV/sheet into calibration-grade closed "
            "outcomes. Dry-run by default; --apply writes only the advisory "
            "calibration tables via the operator guard; never calls a broker; "
            "real-money sizing PROHIBITED."
        ),
    )
    p.add_argument("--input", required=True, help="path to outcomes CSV or JSON")
    p.add_argument(
        "--apply",
        action="store_true",
        help="record valid + auto-linked closed outcomes (operator guard required)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="explicit dry-run (default): report only, writes nothing",
    )
    p.add_argument("--limit", type=int, default=None, help="cap outcomes processed")
    p.add_argument("--db-path", default=None, help="canonical DB path override")
    p.add_argument("--operator-role", default=None, help="VIEWER|OPERATOR|ADMIN")
    p.add_argument("--json", action="store_true", help="emit the JSON report")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] input not found: {input_path}")
        return 1
    try:
        rows = _intake.load_records(input_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] could not parse {input_path}: {exc}")
        return 1

    db_path = Path(args.db_path) if args.db_path else None

    if not args.apply:
        report = run_corpus_build(rows, apply=False, limit=args.limit, db_path=db_path)
        try:
            _guard.write_dry_run_receipt(
                OPERATION_NAME,
                target_count=report["valid_for_calibration"],
                db_path=str(db_path) if db_path else None,
            )
        except Exception:  # pragma: no cover - receipt is best-effort
            pass
        _emit(report, json_mode=args.json)
        return 0

    try:
        decision = _guard.build_apply_decision(
            OPERATION_NAME,
            OPERATION_CLASS,
            str(db_path) if db_path else None,
            operator_role=args.operator_role,
        )
    except PermissionError as exc:
        print(f"[corpus-builder] [DENY] {exc}")
        return 2

    report = run_corpus_build(
        rows,
        apply=True,
        limit=args.limit,
        db_path=db_path,
        permission_decision=decision,
    )
    _emit(report, json_mode=args.json)
    return 0


def _emit(report: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(report, indent=2, default=str))
        return
    print("calibration_corpus_builder")
    print(f"  mode              : {report['mode']}")
    print(f"  rows_seen         : {report['rows_seen']}")
    print(f"  valid             : {report['valid_for_calibration']}")
    print(f"  linked_auto       : {report['linked_auto']}")
    print(f"  linked_review     : {report['linked_review']}")
    print(f"  no_link           : {report['no_link']}")
    print(f"  outcomes_recorded : {report['outcomes_recorded']}")
    print(f"  buckets_updated   : {report['buckets_updated']}")
    print(
        f"  readiness         : {report['readiness_label_before']} -> "
        f"{report['readiness_label_after']}"
    )
    print(
        f"  corpus quality    : {report['corpus_quality_before']} -> "
        f"{report['corpus_quality_after']}"
    )
    print(f"  real-money        : {report['real_money_sizing_impact']}")
    print(f"  next action       : {report['next_required_action']}")


__all__ = [
    "OPERATION_NAME",
    "OPERATION_CLASS",
    "run_corpus_build",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
