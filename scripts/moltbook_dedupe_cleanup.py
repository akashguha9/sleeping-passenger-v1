"""
Moltbook visibility + dedupe cleanup tool (advisory-only).

Scans ``moltbook_entries`` and either reports (default) or marks rows:

  --dry-run (default)
      Prints + writes runtime/release/moltbook_visibility_cleanup_report.json.
      Never mutates the database.

  --yes
      Required to actually mutate.  Mutations are ONLY:
        hidden_from_default_view = 1
        hidden_reason = '<SKIP_* or DUPLICATE_OF_*>'
        is_duplicate = 1
        duplicate_of = '<canonical_entry_id>'
      No row is ever deleted.  No broker call is ever made.

  --hide-ineligible
      In addition to hiding signature-level duplicates, also hide rows
      that fail the Moltbook eligibility contract (test/demo theses,
      open-trade event types, missing identity, missing exit/realized
      P/L, unsupported event types).  Default: off — only duplicates are
      reported/hidden so a single ``--yes`` run cannot accidentally hide
      every legacy row.

Safety
------
- Advisory-only.  ai_execution_count stays 0; broker_api_called is never
  set to true.
- Never deletes a row; the canonical operator-visible state survives
  every cleanup because hidden rows can be un-hidden with a single
  UPDATE.
- ``--yes`` is required for mutation.  Without it the script is a pure
  read-only diagnostic.

Usage
-----
    python scripts/moltbook_dedupe_cleanup.py                  # dry-run
    python scripts/moltbook_dedupe_cleanup.py --json           # dry-run JSON
    python scripts/moltbook_dedupe_cleanup.py --hide-ineligible
    python scripts/moltbook_dedupe_cleanup.py --hide-ineligible --yes
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_common import utc_timestamp  # type: ignore[no-redef]

try:
    import scripts.persistence as _persistence
except ModuleNotFoundError:  # pragma: no cover
    import persistence as _persistence  # type: ignore[no-redef]

try:
    import scripts.moltbook_learning_bridge as _bridge
except ModuleNotFoundError:  # pragma: no cover
    import moltbook_learning_bridge as _bridge  # type: ignore[no-redef]

try:
    import scripts.moltbook_visibility as _visibility
except ModuleNotFoundError:  # pragma: no cover
    import moltbook_visibility as _visibility  # type: ignore[no-redef]


REPORT_PATH = Path(__file__).resolve().parents[1] / "runtime" / "release" / "moltbook_visibility_cleanup_report.json"


def _default_db_path() -> Path:
    try:
        return Path(_persistence.DB_PATH)
    except Exception:  # pragma: no cover
        return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


def _normalized_signature(row: dict[str, Any]) -> tuple:
    """Stable signature for duplicate detection when idempotency_key is empty.

    Groups rows with identical (symbol, event_type, entry_price,
    exit_price, exit_quantity, realized_pl, final_human_decision,
    outcome) so structurally-identical records collapse to one canonical
    row regardless of differing entry_id / created_at.
    """
    def _r(v: Any, places: int = 4) -> str:
        try:
            return f"{round(float(v), places):.{places}f}"
        except (TypeError, ValueError):
            return ""

    return (
        str(row.get("ticker") or "").strip().upper(),
        str(row.get("event_type") or row.get("mistake_type") or "").strip().upper(),
        _r(row.get("entry_price")),
        _r(row.get("exit_price")),
        _r(row.get("exit_quantity"), 6),
        _r(row.get("realized_pl")),
        str(row.get("final_human_decision") or "")[:60],
        str(row.get("outcome") or "")[:60],
    )


def _richness_score(row: dict[str, Any]) -> int:
    """Pick the canonical row from a duplicate group.

    Higher score = richer content (longer lesson, reflection, thesis).
    Ties broken by earliest created_at later in the caller.
    """
    score = 0
    for field in ("lesson", "lesson_learned", "user_reflection",
                  "original_signal_thesis", "ai_interpretation"):
        text = str(row.get(field) or "").strip()
        score += len(text)
    return score


def _evaluate_eligibility(row: dict[str, Any]) -> dict[str, Any]:
    """Run the canonical eligibility helper against a stored Moltbook row.

    Maps the persisted column names back into the eligibility helper's
    expected event shape.  Legacy signal-decision rows (event_type=''
    with mistake_type in the original 12 categories) bypass the gate —
    they predate the reconciliation→Moltbook bridge and remain valid
    Moltbook content.  The eligibility contract targets *reconciliation-
    derived* rows.
    """
    event_type = str(row.get("event_type") or "").strip()
    if not event_type:
        # Legacy / manually-logged signal-decision row.  Still subject to
        # the test/demo thesis filter so polluted "test"/"t" rows can be
        # quarantined, but otherwise eligible.
        thesis = str(row.get("original_signal_thesis") or "").strip().lower()
        if thesis in _bridge.TEST_DEMO_THESIS_TOKENS:
            return {
                "eligible": False,
                "reason": _bridge.SKIP_TEST_DEMO_FIXTURE,
                "normalized_event_type": None,
                "learning_worthy": False,
                "hidden_reason": _bridge.SKIP_TEST_DEMO_FIXTURE,
            }
        return {
            "eligible": True,
            "reason": _bridge.ELIGIBLE_CLOSED_WIN,
            "normalized_event_type": None,
            "learning_worthy": True,
            "hidden_reason": None,
        }
    return _bridge.is_moltbook_eligible_reconciliation_event(
        {
            "event_type": event_type,
            "status": "",
            "symbol": row.get("ticker") or "",
            "trade_id": row.get("trade_id") or row.get("manual_trade_log_id") or "",
            "manual_trade_id": row.get("manual_trade_log_id") or "",
            "exit_price": row.get("exit_price"),
            "realized_pl": row.get("realized_pl"),
            "exit_reason": "",
            "stop_loss_hit": False,
            "thesis": row.get("original_signal_thesis") or "",
        }
    )


def scan(db_path: Path) -> dict[str, Any]:
    """Read every Moltbook row and return cleanup candidates.

    Mirrors the API-side dynamic classifier
    (:mod:`scripts.moltbook_visibility`) so the cleanup verdict matches
    what GET /moltbook would hide.  Returns a structured report with the
    full visibility breakdown:

      raw_total
      default_visible
      would_hide_persisted_hidden
      would_hide_fixture
      would_hide_cross_source_duplicates
      would_hide_unconfirmed_closed
      would_hide_open_or_not_final
      would_hide_missing_source
      would_hide_unsupported_event
      duplicate_targets (entry_id -> canonical entry_id)
      ineligible_targets (entry_id -> hidden_reason)
      visible_symbols / hidden_symbols
      canonical_groups
      samples_per_reason
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM moltbook_entries ORDER BY logged_at ASC, entry_id ASC"
        ).fetchall()]
    finally:
        conn.close()

    raw_total = len(rows)
    decisions = _visibility.classify_moltbook_entries(rows)

    duplicate_targets: dict[str, str] = {}
    ineligible_targets: dict[str, str] = {}
    canonical_groups: dict[str, list[str]] = defaultdict(list)
    samples_per_reason: dict[str, list[dict[str, Any]]] = defaultdict(list)
    visible_symbols: set[str] = set()
    hidden_symbols: set[str] = set()

    counts = {
        _visibility.HIDE_PERSISTED_HIDDEN: 0,
        _visibility.HIDE_DUPLICATE_SIGNATURE: 0,
        _visibility.HIDE_TEST_DEMO_FIXTURE: 0,
        _visibility.HIDE_UNCONFIRMED_CLOSED_TRADE: 0,
        _visibility.HIDE_OPEN_OR_NOT_FINAL: 0,
        _visibility.HIDE_MISSING_OPERATOR_SOURCE: 0,
        _visibility.HIDE_UNSUPPORTED_EVENT_TYPE: 0,
        _visibility.VISIBLE_OPERATOR_CONFIRMED_FINAL_OUTCOME: 0,
    }

    by_id = {str(r.get("entry_id") or ""): r for r in rows}
    for entry_id, decision in decisions.items():
        row = by_id.get(entry_id) or {}
        ticker = str(row.get("ticker") or "").upper()
        counts[decision.reason] = counts.get(decision.reason, 0) + 1
        if decision.canonical_group_key:
            canonical_groups[decision.canonical_group_key].append(entry_id)
        if decision.visible:
            if ticker:
                visible_symbols.add(ticker)
            continue
        if ticker:
            hidden_symbols.add(ticker)
        if decision.reason == _visibility.HIDE_DUPLICATE_SIGNATURE and decision.duplicate_of:
            duplicate_targets[entry_id] = decision.duplicate_of
            ineligible_targets[entry_id] = f"DUPLICATE_OF:{decision.duplicate_of}"
        elif decision.reason == _visibility.HIDE_PERSISTED_HIDDEN:
            # Already hidden in DB — no new mutation needed, but record
            # for accounting.
            ineligible_targets[entry_id] = str(row.get("hidden_reason") or "ALREADY_HIDDEN")
        else:
            ineligible_targets[entry_id] = decision.reason

        if len(samples_per_reason[decision.reason]) < 10:
            samples_per_reason[decision.reason].append({
                "entry_id": entry_id,
                "ticker": ticker,
                "thesis": str(row.get("original_signal_thesis") or "")[:80],
                "event_type": row.get("event_type") or row.get("mistake_type"),
                "entry_price": row.get("entry_price"),
                "exit_price": row.get("exit_price"),
                "exit_quantity": row.get("exit_quantity"),
                "realized_pl": row.get("realized_pl"),
                "canonical_group_key": decision.canonical_group_key,
                "duplicate_of": decision.duplicate_of,
            })

    hidden_union = set(ineligible_targets)
    visible = raw_total - len(hidden_union)
    legacy_visible_canonical = {
        k: v for k, v in canonical_groups.items() if len(v) > 1
    }

    return {
        "raw_total": raw_total,
        "default_visible": max(0, visible),
        "eligible_visible": max(0, visible),  # legacy alias for callers
        "would_hide_persisted_hidden": counts[_visibility.HIDE_PERSISTED_HIDDEN],
        "would_hide_fixture": counts[_visibility.HIDE_TEST_DEMO_FIXTURE],
        "would_hide_cross_source_duplicates": counts[_visibility.HIDE_DUPLICATE_SIGNATURE],
        "would_hide_unconfirmed_closed": counts[_visibility.HIDE_UNCONFIRMED_CLOSED_TRADE],
        "would_hide_open_or_not_final": counts[_visibility.HIDE_OPEN_OR_NOT_FINAL],
        "would_hide_missing_source": counts[_visibility.HIDE_MISSING_OPERATOR_SOURCE],
        "would_hide_unsupported_event": counts[_visibility.HIDE_UNSUPPORTED_EVENT_TYPE],
        "would_hide_duplicates": counts[_visibility.HIDE_DUPLICATE_SIGNATURE],
        "would_hide_ineligible": len(ineligible_targets),
        "would_hide_test_demo": counts[_visibility.HIDE_TEST_DEMO_FIXTURE],
        "canonical_groups": legacy_visible_canonical,
        "duplicate_targets": duplicate_targets,
        "ineligible_targets": ineligible_targets,
        "duplicate_groups": [
            {
                "canonical_group_key": key,
                "members": members,
            }
            for key, members in legacy_visible_canonical.items()
        ],
        "ineligible_samples": [
            sample
            for reason_samples in samples_per_reason.values()
            for sample in reason_samples
        ][:25],
        "samples_per_reason": dict(samples_per_reason),
        "visible_symbols": sorted(visible_symbols),
        "hidden_symbols": sorted(hidden_symbols),
        "visibility_counts": counts,
    }


def apply(
    db_path: Path,
    scan_result: dict[str, Any],
    *,
    hide_ineligible: bool,
    permission_decision: Any = None,
) -> dict[str, Any]:
    """Apply the cleanup verdict to the database.

    Only marks ``hidden_from_default_view = 1`` and sets a hidden_reason
    / duplicate_of pointer.  Never deletes; never touches broker state.

    Mutation boundary: when invoked directly (without going through the
    CLI), the caller must supply a guard-validated permission_decision.
    The DELETE-equivalent UPDATE boundary re-checks it via
    operator_permission_guard.guarded_mutation_context so an import-time
    bypass cannot land DB writes.
    """
    mutated_duplicates = 0
    mutated_ineligible = 0
    try:
        from scripts import operator_permission_guard as _guard
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        import operator_permission_guard as _guard  # type: ignore[no-redef]
    duplicate_targets = scan_result["duplicate_targets"]
    ineligible_targets = scan_result["ineligible_targets"]
    with _guard.guarded_mutation_context(
        permission_decision,
        operation_name="moltbook_dedupe_cleanup",
        operation_class=_guard.OperationClass.REPAIR_WRITE,
        require_dry_run=False,
    ):
        for dup_id, canonical_id in duplicate_targets.items():
            if not dup_id:
                continue
            _persistence.mark_moltbook_entry_hidden(
                dup_id,
                hidden_reason=f"DUPLICATE_OF:{canonical_id}",
                duplicate_of=canonical_id,
                is_duplicate=True,
                db_path=db_path,
            )
            mutated_duplicates += 1
        if hide_ineligible:
            for entry_id, reason in ineligible_targets.items():
                if not entry_id or entry_id in duplicate_targets:
                    continue
                if str(reason).startswith("DUPLICATE_OF:"):
                    # Already counted above; defensive guard.
                    continue
                _persistence.mark_moltbook_entry_hidden(
                    entry_id,
                    hidden_reason=str(reason),
                    db_path=db_path,
                )
                mutated_ineligible += 1
    return {
        "hidden_duplicates_applied": mutated_duplicates,
        "hidden_ineligible_applied": mutated_ineligible,
    }


def run(
    db_path: Path | None = None,
    *,
    apply_changes: bool = False,
    hide_ineligible: bool = False,
    report_path: Path | None = None,
    permission_decision: Any = None,
) -> dict[str, Any]:
    path = Path(db_path) if db_path is not None else _default_db_path()
    if not path.exists():
        return {
            "operation": "moltbook_dedupe_cleanup",
            "db_path": str(path),
            "db_exists": False,
            "applied": False,
            "advisory_status": "ADVISORY_ONLY",
            "broker_api_called": False,
            "ai_execution_count": 0,
            "generated_at": utc_timestamp(),
            "warning": "db_missing",
        }

    scan_result = scan(path)
    applied: dict[str, Any] = {"hidden_duplicates_applied": 0, "hidden_ineligible_applied": 0}
    if apply_changes:
        applied = apply(
            path, scan_result, hide_ineligible=hide_ineligible,
            permission_decision=permission_decision,
        )

    report: dict[str, Any] = {
        "operation": "moltbook_dedupe_cleanup",
        "db_path": str(path),
        "db_exists": True,
        "applied": apply_changes,
        "hide_ineligible_flag": hide_ineligible,
        "raw_total": scan_result["raw_total"],
        "default_visible": scan_result["default_visible"],
        "eligible_visible": scan_result["eligible_visible"],
        "would_hide_persisted_hidden": scan_result["would_hide_persisted_hidden"],
        "would_hide_fixture": scan_result["would_hide_fixture"],
        "would_hide_cross_source_duplicates": scan_result["would_hide_cross_source_duplicates"],
        "would_hide_unconfirmed_closed": scan_result["would_hide_unconfirmed_closed"],
        "would_hide_open_or_not_final": scan_result["would_hide_open_or_not_final"],
        "would_hide_missing_source": scan_result["would_hide_missing_source"],
        "would_hide_unsupported_event": scan_result["would_hide_unsupported_event"],
        "would_hide_ineligible": scan_result["would_hide_ineligible"],
        "would_hide_duplicates": scan_result["would_hide_duplicates"],
        "would_hide_test_demo": scan_result["would_hide_test_demo"],
        "duplicate_groups": scan_result["duplicate_groups"],
        "canonical_groups": scan_result["canonical_groups"],
        "visible_symbols": scan_result["visible_symbols"],
        "hidden_symbols": scan_result["hidden_symbols"],
        "visibility_counts": scan_result["visibility_counts"],
        "samples_per_reason": scan_result["samples_per_reason"],
        "sample_hidden_rows": scan_result["ineligible_samples"],
        "applied_changes": applied,
        "advisory_status": "ADVISORY_ONLY",
        "execution_mode": "HUMAN_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_review_required": True,
        "generated_at": utc_timestamp(),
    }

    target_report = report_path if report_path is not None else REPORT_PATH
    try:
        target_report.parent.mkdir(parents=True, exist_ok=True)
        target_report.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        report["report_written_to"] = str(target_report)
    except OSError as e:  # pragma: no cover - best-effort
        report["report_write_error"] = str(e)
    return report


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="moltbook_dedupe_cleanup.py",
        description=(
            "Dedupe + visibility cleanup for Moltbook entries.  Dry-run by "
            "default; --yes is required to mutate.  Never deletes; only "
            "marks hidden_from_default_view.  Advisory-only — never calls "
            "the broker, never grants execution permission."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument("--yes", action="store_true",
                   help="Apply the hidden_from_default_view mutations.")
    p.add_argument("--hide-ineligible", action="store_true",
                   help="Also hide rows that fail the eligibility contract.")
    p.add_argument("--operator-role", default=None,
                   help="VIEWER|OPERATOR|ADMIN (default: MVP_OPERATOR_ROLE env). "
                        "--yes requires ADMIN.")
    p.add_argument("--json", action="store_true")
    p.add_argument("--report-path", type=str, default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = Path(args.db_path) if args.db_path else _default_db_path()
    report_path = Path(args.report_path) if args.report_path else None

    # CLI authorization: --yes is an ADMIN-only mutation; dry-run is open.
    # operator_audit_log.enforce is the established role gate; the central
    # operator_permission_guard then verifies advisory safety invariants
    # and writes the unified audit event.
    decision = None
    if args.yes:
        try:
            try:
                from scripts.operator_audit_log import enforce as _enforce
            except ModuleNotFoundError:  # pragma: no cover - script-style fallback
                from operator_audit_log import enforce as _enforce  # type: ignore[no-redef]
            _enforce("cleanup_scripts", role=args.operator_role,
                     resource="moltbook_entries.dedupe_visibility")
        except PermissionError as exc:
            print(f"[DENY] {exc}")
            return 2
        try:
            try:
                from scripts import operator_permission_guard as _guard
            except ModuleNotFoundError:  # pragma: no cover - script-style fallback
                import operator_permission_guard as _guard  # type: ignore[no-redef]
            decision = _guard.build_apply_decision(
                "moltbook_dedupe_cleanup",
                _guard.OperationClass.REPAIR_WRITE,
                str(db),
                operator_role=args.operator_role,
                reason=f"{_guard.NO_DRY_RUN_NEEDED}: hidden_from_default_view "
                       "is reversible; no row is deleted.",
            )
        except PermissionError as exc:
            print(f"[DENY] {exc}")
            return 2

    report = run(
        db,
        apply_changes=args.yes,
        hide_ineligible=args.hide_ineligible,
        report_path=report_path,
        permission_decision=decision,
    )

    if not args.yes:
        # Dry-run is open to any role; record a receipt so a later --yes
        # (by an ADMIN) can prove a dry-run happened.
        try:
            try:
                from scripts import operator_permission_guard as _guard
            except ModuleNotFoundError:  # pragma: no cover - script-style fallback
                import operator_permission_guard as _guard  # type: ignore[no-redef]
            _guard.write_dry_run_receipt(
                "moltbook_dedupe_cleanup",
                target_count=report["would_hide_duplicates"] + report["would_hide_ineligible"],
                db_path=str(db),
            )
        except Exception:  # pragma: no cover - receipt is best-effort
            pass
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        mode = "APPLY" if report["applied"] else "DRY-RUN"
        print(f"Moltbook visibility cleanup [{mode}]")
        print(f"  db_path                 : {report['db_path']}")
        print(f"  raw_total               : {report['raw_total']}")
        print(f"  eligible_visible        : {report['eligible_visible']}")
        print(f"  would_hide_duplicates   : {report['would_hide_duplicates']}")
        print(f"  would_hide_ineligible   : {report['would_hide_ineligible']}")
        print(f"  would_hide_test_demo    : {report['would_hide_test_demo']}")
        print(f"  duplicate_groups        : {len(report['duplicate_groups'])}")
        if report["applied"]:
            print(f"  hidden_duplicates_applied : {report['applied_changes']['hidden_duplicates_applied']}")
            print(f"  hidden_ineligible_applied : {report['applied_changes']['hidden_ineligible_applied']}")
        if report.get("report_written_to"):
            print(f"  report                   : {report['report_written_to']}")
    return 0


__all__ = ["scan", "apply", "run", "REPORT_PATH"]


if __name__ == "__main__":
    raise SystemExit(main())
