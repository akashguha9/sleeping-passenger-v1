"""Runtime truth-purity audit — fake data in canonical memory is poisoning.

Read-only release gate that scans the canonical runtime SQLite DB for demo /
mock / seed pollution that should never live in operator truth:

    * FABRIC_SPY / FABRIC_QQQ style demo Moltbook event_ids
    * the generic "Persistence above 0.8" fake thesis
    * the synthetic SPY "Thesis A" seed signature
    * test/seed/demo event-id prefixes (SEED_, DEMO_, TEST_, FIXTURE_ ...)
    * fake operator trades (the canonical ``is_fake_manual_trade_row`` rules)
    * trade-derived (loss-review) Moltbook entries with a BLANK
      manual_trade_log_id (an orphaned lesson that cannot be traced to a trade)

The audit reuses the *same* fake-detection vocabulary as
``scripts/manual_trade_origin.py`` and ``scripts/moltbook_cleanup_fake_seed.py``
so detection and cleanup can never drift apart.

Safety
------
* READ-ONLY.  This script never deletes or mutates anything.  Cleanup is a
  separate, explicit, role-gated invocation
  (``scripts/moltbook_cleanup_fake_seed.py --apply`` /
  ``scripts/quarantine_fake_manual_trades.py``), surfaced as
  ``recommended_cleanup_command``.
* No broker calls, no execution state.

Usage
-----
    python scripts/runtime_truth_purity_audit.py
    python scripts/runtime_truth_purity_audit.py --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_common import utc_timestamp  # type: ignore[no-redef]

try:
    from scripts.manual_trade_origin import (
        is_fake_manual_trade_row,
        fake_manual_trade_reason,
        FAKE_EVENT_ID_PREFIXES,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from manual_trade_origin import (  # type: ignore[no-redef]
        is_fake_manual_trade_row,
        fake_manual_trade_reason,
        FAKE_EVENT_ID_PREFIXES,
    )

try:
    from scripts.moltbook_api import LOSS_REVIEW_CATEGORIES
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from moltbook_api import LOSS_REVIEW_CATEGORIES  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "runtime" / "mvp_local.db"

# Known demo tickers that have historically polluted runtime Moltbook.
KNOWN_DEMO_TICKERS: frozenset[str] = frozenset({"FABRIC", "FABRIC_SPY", "FABRIC_QQQ"})
# Fake thesis fragments (case-insensitive substring match).
FAKE_THESIS_FRAGMENTS: tuple[str, ...] = (
    "persistence above 0.8",
    "thesis a",
)

ADVISORY_DISCLAIMER = (
    "Advisory-only, read-only truth-purity gate. It detects but never deletes; "
    "cleanup is a separate, explicit, role-gated command. No broker calls."
)

CLEANUP_COMMAND = (
    "python scripts/moltbook_cleanup_fake_seed.py --apply  (Moltbook seed rows); "
    "python scripts/quarantine_fake_manual_trades.py --apply  (fake trades)"
)


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.Error:
            return None
    conn.row_factory = sqlite3.Row
    return conn


def _rows(conn: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    try:
        return [dict(r) for r in conn.execute(sql).fetchall()]
    except sqlite3.Error:
        return []


def _moltbook_row_is_fake(row: dict[str, Any]) -> str:
    """Return a non-empty reason string if a Moltbook row looks like pollution."""
    event_id = str(row.get("event_id") or "")
    ticker = str(row.get("ticker") or "").upper()
    thesis = str(row.get("original_signal_thesis") or "").lower()
    mistake_type = str(row.get("mistake_type") or "")
    trade_ref = str(row.get("manual_trade_log_id") or "").strip()

    if event_id.upper().startswith(tuple(p.upper() for p in FAKE_EVENT_ID_PREFIXES)):
        return f"demo_event_id_prefix:{event_id}"
    if event_id.upper().startswith("FABRIC"):
        return f"fabric_demo_event_id:{event_id}"
    if ticker in KNOWN_DEMO_TICKERS:
        return f"known_demo_ticker:{ticker}"
    for frag in FAKE_THESIS_FRAGMENTS:
        if frag in thesis:
            return f"fake_thesis_fragment:{frag}"
    # Trade-derived lesson with no trace back to a trade = orphaned/poisoned.
    if mistake_type in LOSS_REVIEW_CATEGORIES and not trade_ref:
        return "loss_review_entry_without_trade_reference"
    return ""


def build_audit(db_path: Path | None = None) -> dict[str, Any]:
    """Build the truth-purity audit (read-only, advisory-only)."""
    db = Path(db_path) if db_path is not None else DEFAULT_DB
    report: dict[str, Any] = {
        "report": "runtime_truth_purity_audit",
        "db_path": str(db),
        "db_available": False,
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        "truth_purity_score": 1.0,
        "fake_rows_detected": 0,
        "affected_tables": [],
        "pollution_examples": [],
        "release_gate_passed": True,
        "recommended_cleanup_command": "",
        "total_rows_scanned": 0,
        "notes": [],
        **_contract.advisory_safety_stamps(),
        "generated_at": utc_timestamp(),
    }

    conn = _readonly_connect(db)
    if conn is None:
        # A missing DB is not pollution, but it is not a verified-clean state
        # either.  Fail the gate conservatively and say why.
        report["release_gate_passed"] = False
        report["notes"].append(
            "DB not available — cannot verify purity; gate fails closed."
        )
        return report
    report["db_available"] = True

    affected: set[str] = set()
    examples: list[dict[str, Any]] = []
    fake_count = 0
    total_scanned = 0

    try:
        # --- Moltbook entries -------------------------------------------
        moltbook = _rows(conn, "SELECT * FROM moltbook_entries")
        total_scanned += len(moltbook)
        for row in moltbook:
            reason = _moltbook_row_is_fake(row)
            if reason:
                fake_count += 1
                affected.add("moltbook_entries")
                if len(examples) < 20:
                    examples.append({
                        "table": "moltbook_entries",
                        "id": row.get("entry_id"),
                        "event_id": row.get("event_id"),
                        "ticker": row.get("ticker"),
                        "reason": reason,
                    })

        # --- manual trades ----------------------------------------------
        trades = _rows(conn, "SELECT * FROM manual_trades")
        total_scanned += len(trades)
        for row in trades:
            if is_fake_manual_trade_row(row):
                fake_count += 1
                affected.add("manual_trades")
                if len(examples) < 20:
                    examples.append({
                        "table": "manual_trades",
                        "id": row.get("trade_id"),
                        "event_id": row.get("event_id"),
                        "ticker": row.get("ticker"),
                        "reason": fake_manual_trade_reason(row) or "fake_trade",
                    })
    finally:
        conn.close()

    report["total_rows_scanned"] = total_scanned
    report["fake_rows_detected"] = fake_count
    report["affected_tables"] = sorted(affected)
    report["pollution_examples"] = examples
    report["release_gate_passed"] = fake_count == 0
    if fake_count:
        report["recommended_cleanup_command"] = CLEANUP_COMMAND
        report["notes"].append(
            f"{fake_count} polluted row(s) detected. Canonical truth is "
            "compromised until cleanup is run explicitly."
        )
    # Purity score: clean fraction of scanned rows (1.0 when nothing scanned).
    if total_scanned:
        report["truth_purity_score"] = round(
            max(total_scanned - fake_count, 0) / total_scanned, 4
        )
    else:
        report["truth_purity_score"] = 1.0

    return report


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="runtime_truth_purity_audit.py",
        description=(
            "Read-only scan of canonical runtime SQLite for demo/seed/fake "
            "pollution. Detects but never deletes. No broker calls."
        ),
    )
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rep = build_audit(args.db_path)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print("Runtime Truth-Purity Audit (advisory-only)")
        print("=" * 44)
        print(f"  DB available          : {rep['db_available']}")
        print(f"  rows scanned          : {rep['total_rows_scanned']}")
        print(f"  fake rows detected    : {rep['fake_rows_detected']}")
        print(f"  affected tables       : {rep['affected_tables']}")
        print(f"  truth purity score    : {rep['truth_purity_score']}")
        print(f"  release gate passed   : {rep['release_gate_passed']}")
        for ex in rep["pollution_examples"]:
            print(f"    - [{ex['table']}] {ex.get('id')} {ex.get('ticker')} :: {ex['reason']}")
        if rep["recommended_cleanup_command"]:
            print(f"  cleanup: {rep['recommended_cleanup_command']}")
        for note in rep["notes"]:
            print(f"  note: {note}")
        print(f"\n  {rep['advisory_disclaimer']}")
    return 0


__all__ = [
    "ADVISORY_DISCLAIMER",
    "KNOWN_DEMO_TICKERS",
    "FAKE_THESIS_FRAGMENTS",
    "build_audit",
]


if __name__ == "__main__":
    raise SystemExit(main())
