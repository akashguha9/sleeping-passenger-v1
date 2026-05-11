"""
Delete Polymarket rows that fail the current domain-gate filter.

Usage
-----
  python scripts/cleanup_polymarket_db.py --dry-run      # report only
  python scripts/cleanup_polymarket_db.py --write        # delete bad rows

Safety
------
- Never deletes NewsAPI, Event Registry, India, Market Data, or any other source.
- Only touches source_name = 'polymarket' rows.
- Dry-run always available.
- All deletions are logged to stdout.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from scripts.runtime_common import RUNTIME_DIR
from scripts.live_signal_filters import classify_market_domain

DB_PATH = RUNTIME_DIR / "mvp_local.db"


def _classify_row(row: dict) -> bool:
    """Return True if the row passes the domain gate (should be kept)."""
    payload = row.get("raw_payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}

    title = str(payload.get("title") or payload.get("question") or "")
    category = str(payload.get("category") or "")
    tags = payload.get("matched_terms") or payload.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []

    result = classify_market_domain(title, category or None, tags or None)
    return result["allowed"]


def run_cleanup(dry_run: bool, db_path: Path = DB_PATH) -> dict:
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return {"db_exists": False}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, event_id, raw_payload FROM signal_events WHERE source_name = 'polymarket'"
        )
        rows = cur.fetchall()

        total = len(rows)
        to_delete: list[int] = []

        for row in rows:
            row_dict = {
                "raw_payload": row["raw_payload"],
                "event_id": row["event_id"],
            }
            try:
                raw = json.loads(row["raw_payload"]) if isinstance(row["raw_payload"], str) else {}
            except Exception:
                raw = {}

            title = str(raw.get("title") or raw.get("question") or "")
            category = str(raw.get("category") or "")
            tags_raw = raw.get("matched_terms") or raw.get("tags") or []
            if isinstance(tags_raw, str):
                try:
                    tags_raw = json.loads(tags_raw)
                except Exception:
                    tags_raw = []

            result = classify_market_domain(title, category or None, tags_raw or None)
            if not result["allowed"]:
                to_delete.append(row["id"])
                print(
                    f"  [REJECT] id={row['id']} event_id={row['event_id']!r} "
                    f"title={title[:60]!r} reason={result['reason']}"
                )

        kept = total - len(to_delete)
        print(f"\nPolymarket rows: total={total}, keep={kept}, delete={len(to_delete)}")

        if to_delete and not dry_run:
            placeholders = ",".join("?" * len(to_delete))
            cur.execute(
                f"DELETE FROM signal_events WHERE id IN ({placeholders})",
                to_delete,
            )
            conn.commit()
            print(f"Deleted {len(to_delete)} rows.")
        elif to_delete and dry_run:
            print("Dry-run: no rows deleted.")
        else:
            print("Nothing to delete.")

        return {
            "db_exists": True,
            "total_polymarket": total,
            "kept": kept,
            "deleted": len(to_delete) if not dry_run else 0,
            "would_delete": len(to_delete),
            "dry_run": dry_run,
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete Polymarket DB rows that fail the domain-gate filter."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", dest="dry_run",
                      help="Report what would be deleted without deleting.")
    mode.add_argument("--write", action="store_true",
                      help="Delete rows that fail the domain gate.")
    parser.add_argument("--db", default=None, metavar="PATH",
                        help="Path to SQLite DB (default: runtime/mvp_local.db).")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else DB_PATH
    mode_label = "dry-run" if args.dry_run else "write"
    print(f"[Polymarket DB Cleanup] mode={mode_label} db={db_path}")
    print("Only source_name='polymarket' rows are evaluated — all other sources untouched.")
    print()

    result = run_cleanup(dry_run=args.dry_run, db_path=db_path)
    if not result.get("db_exists"):
        print("No database found — nothing to clean up.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
