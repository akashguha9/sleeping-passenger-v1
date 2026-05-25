"""Canonical SQLite bridge for the complex-systems / reactor layer.

Kanté Sprint 2 — Task 2.  The complex-systems diagnostics in
:mod:`scripts.complex_systems_diagnostics` are *pure*: they score whatever a
caller hands them.  Historically the caller supplied proxy / in-memory data,
so the diagnostics could be fed numbers that were never grounded in canonical
truth.  This module closes that gap: it derives the complex-systems inputs
**directly from the canonical SQLite tables** so the reactor reasons over real
operator history, not a caller-supplied proxy.

Canonical sources (read-only)
-----------------------------
* ``duplicate_fingerprints`` → source independence / echo risk
* ``signal_cell_index``      → narrative diffusion / sector spread / density
* ``moltbook_entries``       → broken-windows repair state
* ``reconciliation_results`` → closed-loss / mismatch state
* ``manual_trades``          → exposure / unresolved state / invalidation clarity

Math (mirrors the sprint contract)
----------------------------------
Echo risk             E = repeated_mentions / (total_mentions + eps)
Source independence   I = 1 - E
Moltbook repair       M = 1 - closed_losses_without_moltbook / (closed_losses + 1)
Unrepaired loss debt  U = closed_losses_without_moltbook / (closed_losses + 1)
Narrative diffusion   D = unique_cells / (total_signals + 1) * log(1 + related)

Hard rules
----------
* If a canonical table is **missing**, the affected component degrades to
  ``INSUFFICIENT_DATA`` — never a silent mock value, never an invented number.
* Read-only: opens the DB ``mode=ro``; no writes, no broker, no execution.
* No execution language is ever produced.  This strengthens *routing
  discipline*; it issues no orders.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

_EPS = 1e-9
INSUFFICIENT = "INSUFFICIENT_DATA"


def _default_db_path() -> Path:
    try:
        try:
            from scripts.persistence import DB_PATH  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            from persistence import DB_PATH  # type: ignore[no-redef]
        return Path(DB_PATH)
    except Exception:  # pragma: no cover - defensive
        return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


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


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None
    except sqlite3.Error:  # pragma: no cover - defensive
        return False


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return lo
    if v != v:  # NaN
        return lo
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Per-source components
# ---------------------------------------------------------------------------


def fingerprint_independence(conn: sqlite3.Connection) -> dict[str, Any]:
    """Source independence + echo risk from ``duplicate_fingerprints``.

    Each fingerprint's ``seen_count`` is how many times that exact catalyst was
    observed.  Mentions beyond the first sighting are *echoes*, not independent
    confirmation.
    """
    if not _table_exists(conn, "duplicate_fingerprints"):
        return {"available": False, "state": INSUFFICIENT,
                "independence_score": None, "echo_risk": None}
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS distinct_fp, COALESCE(SUM(seen_count),0) AS total"
            " FROM duplicate_fingerprints"
        ).fetchone()
    except sqlite3.Error:
        return {"available": False, "state": INSUFFICIENT,
                "independence_score": None, "echo_risk": None}
    distinct = int(row["distinct_fp"] or 0)
    total = int(row["total"] or 0)
    if total <= 0:
        return {"available": True, "state": INSUFFICIENT,
                "distinct_fingerprints": 0, "total_mentions": 0,
                "repeated_mentions": 0, "independence_score": None,
                "echo_risk": None,
                "note": "no fingerprint mentions yet — independence unknown."}
    repeated = max(total - distinct, 0)
    echo_risk = round(_clamp(repeated / (total + _EPS)), 4)
    independence = round(_clamp(1.0 - echo_risk), 4)
    return {
        "available": True,
        "state": "OK",
        "distinct_fingerprints": distinct,
        "total_mentions": total,
        "repeated_mentions": repeated,
        "independence_score": independence,
        "echo_risk": echo_risk,
    }


def signal_cell_diffusion(conn: sqlite3.Connection) -> dict[str, Any]:
    """Narrative diffusion / sector spread / density from ``signal_cell_index``."""
    if not _table_exists(conn, "signal_cell_index"):
        return {"available": False, "state": INSUFFICIENT, "diffusion": None}
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS unique_cells,"
            " COALESCE(SUM(seen_count),0) AS total_signals,"
            " COUNT(DISTINCT NULLIF(sector,'')) AS sectors,"
            " COUNT(DISTINCT NULLIF(narrative_cluster,'')) AS clusters,"
            " MAX(seen_count) AS max_seen"
            " FROM signal_cell_index"
        ).fetchone()
    except sqlite3.Error:
        return {"available": False, "state": INSUFFICIENT, "diffusion": None}
    unique_cells = int(row["unique_cells"] or 0)
    total_signals = int(row["total_signals"] or 0)
    sectors = int(row["sectors"] or 0)
    clusters = int(row["clusters"] or 0)
    max_seen = int(row["max_seen"] or 0)
    if unique_cells <= 0:
        return {"available": True, "state": INSUFFICIENT, "unique_cells": 0,
                "total_signals": 0, "diffusion": None,
                "note": "no signal cells yet — diffusion unknown."}
    related = max(sectors, clusters)
    diffusion = (unique_cells / (total_signals + 1.0)) * math.log(1.0 + related)
    # Crowding rises when one cell dominates the total sightings.
    crowding = _clamp(max_seen / (total_signals + _EPS)) if total_signals else 0.0
    return {
        "available": True,
        "state": "OK",
        "unique_cells": unique_cells,
        "total_signals": total_signals,
        "distinct_sectors": sectors,
        "distinct_clusters": clusters,
        "related_tickers": related,
        "diffusion": round(diffusion, 4),
        "crowding": round(crowding, 4),
    }


def moltbook_repair_state(conn: sqlite3.Connection) -> dict[str, Any]:
    """Broken-windows / Moltbook repair completeness from canonical losses.

    A *closed loss* is a reconciliation row whose ``outcome_status`` reads as a
    loss.  It is *repaired* when a Moltbook entry links to that trade
    (``manual_trade_log_id``).  GLD/TSM-style repaired losses lower the
    unrepaired-loss debt; an unlinked loss raises it (a visible broken window).
    """
    have_recon = _table_exists(conn, "reconciliation_results")
    have_mb = _table_exists(conn, "moltbook_entries")
    if not have_recon:
        return {"available": False, "state": INSUFFICIENT,
                "closed_losses": None, "moltbook_repair_score": None,
                "unrepaired_loss_debt": None}
    try:
        loss_trades = [
            str(r["trade_id"] or "")
            for r in conn.execute(
                "SELECT trade_id FROM reconciliation_results"
                " WHERE UPPER(COALESCE(outcome_status,'')) LIKE '%LOSS%'"
            ).fetchall()
        ]
    except sqlite3.Error:
        return {"available": False, "state": INSUFFICIENT,
                "closed_losses": None, "moltbook_repair_score": None,
                "unrepaired_loss_debt": None}
    linked: set[str] = set()
    if have_mb:
        try:
            linked = {
                str(r["manual_trade_log_id"] or "").strip()
                for r in conn.execute(
                    "SELECT manual_trade_log_id FROM moltbook_entries"
                    " WHERE TRIM(COALESCE(manual_trade_log_id,'')) != ''"
                ).fetchall()
            }
        except sqlite3.Error:
            linked = set()
    closed_losses = len(loss_trades)
    without_moltbook = sum(1 for tid in loss_trades if tid and tid not in linked)
    repair_score = round(1.0 - (without_moltbook / (closed_losses + 1.0)), 4)
    unrepaired_debt = round(without_moltbook / (closed_losses + 1.0), 4)
    return {
        "available": True,
        "state": "OK",
        "closed_losses": closed_losses,
        "closed_losses_without_moltbook": without_moltbook,
        "moltbook_repair_score": repair_score,
        "unrepaired_loss_debt": unrepaired_debt,
        "loss_bridge_complete": bool(without_moltbook == 0),
        "promotion_block_if_unrepaired": bool(without_moltbook > 0),
    }


def reconciliation_mismatch_state(conn: sqlite3.Connection) -> dict[str, Any]:
    """Contradiction proxy: reconciliation rows flagged as mismatch/error."""
    if not _table_exists(conn, "reconciliation_results"):
        return {"available": False, "state": INSUFFICIENT, "contradiction": None}
    try:
        total = int(conn.execute(
            "SELECT COUNT(*) FROM reconciliation_results"
        ).fetchone()[0])
        mismatches = int(conn.execute(
            "SELECT COUNT(*) FROM reconciliation_results"
            " WHERE UPPER(COALESCE(outcome_status,'')) LIKE '%MISMATCH%'"
            "    OR UPPER(COALESCE(process_error,'')) NOT IN ('','NONE')"
        ).fetchone()[0])
    except sqlite3.Error:
        return {"available": False, "state": INSUFFICIENT, "contradiction": None}
    if total <= 0:
        return {"available": True, "state": INSUFFICIENT, "contradiction": None,
                "reconciliations": 0}
    contradiction = round(_clamp(mismatches / (total + _EPS)), 4)
    return {"available": True, "state": "OK", "reconciliations": total,
            "mismatches": mismatches, "contradiction": contradiction}


def manual_trade_exposure(conn: sqlite3.Connection) -> dict[str, Any]:
    """Operator load + invalidation clarity from ``manual_trades``.

    Operator load rises with unresolved (unreconciled, active) manual trades.
    Invalidation clarity is the fraction of trades carrying an explicit
    invalidation level.
    """
    if not _table_exists(conn, "manual_trades"):
        return {"available": False, "state": INSUFFICIENT,
                "operator_load": None, "invalidation_clarity": None}
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(manual_trades)")}
        total = int(conn.execute("SELECT COUNT(*) FROM manual_trades").fetchone()[0])
    except sqlite3.Error:
        return {"available": False, "state": INSUFFICIENT,
                "operator_load": None, "invalidation_clarity": None}
    if total <= 0:
        return {"available": True, "state": INSUFFICIENT, "trades": 0,
                "operator_load": None, "invalidation_clarity": None}
    reconciled_ids: set[str] = set()
    if _table_exists(conn, "reconciliation_results"):
        try:
            reconciled_ids = {
                str(r[0] or "") for r in conn.execute(
                    "SELECT DISTINCT trade_id FROM reconciliation_results"
                ).fetchall()
            }
        except sqlite3.Error:
            reconciled_ids = set()
    try:
        trade_ids = [str(r[0] or "") for r in conn.execute(
            "SELECT trade_id FROM manual_trades"
        ).fetchall()]
    except sqlite3.Error:
        trade_ids = []
    unresolved = sum(1 for tid in trade_ids if tid and tid not in reconciled_ids)
    # Queue-load proxy: fraction of trades still unresolved.
    operator_load = round(_clamp(unresolved / (total + _EPS)), 4)
    invalidation_clarity = None
    if "invalidation_level" in cols:
        try:
            with_inval = int(conn.execute(
                "SELECT COUNT(*) FROM manual_trades"
                " WHERE TRIM(COALESCE(invalidation_level,'')) != ''"
            ).fetchone()[0])
            invalidation_clarity = round(_clamp(with_inval / (total + _EPS)), 4)
        except sqlite3.Error:
            invalidation_clarity = None
    return {
        "available": True,
        "state": "OK",
        "trades": total,
        "unresolved_trades": unresolved,
        "operator_load": operator_load,
        "invalidation_clarity": invalidation_clarity,
    }


def signal_freshness(conn: sqlite3.Connection) -> dict[str, Any]:
    """Freshness fraction from ``signal_cell_index.freshness_state``."""
    if not _table_exists(conn, "signal_cell_index"):
        return {"available": False, "state": INSUFFICIENT, "freshness": None}
    try:
        total = int(conn.execute(
            "SELECT COUNT(*) FROM signal_cell_index"
        ).fetchone()[0])
        fresh = int(conn.execute(
            "SELECT COUNT(*) FROM signal_cell_index"
            " WHERE LOWER(COALESCE(freshness_state,'')) IN ('fresh','recent','live')"
        ).fetchone()[0])
    except sqlite3.Error:
        return {"available": False, "state": INSUFFICIENT, "freshness": None}
    if total <= 0:
        return {"available": True, "state": INSUFFICIENT, "freshness": None}
    return {"available": True, "state": "OK",
            "freshness": round(_clamp(fresh / (total + _EPS)), 4),
            "fresh_cells": fresh, "total_cells": total}


# ---------------------------------------------------------------------------
# Aggregate canonical state
# ---------------------------------------------------------------------------


def build_canonical_complex_systems_state(
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Assemble all canonical-derived complex-systems inputs into one payload.

    Degrades to ``INSUFFICIENT_DATA`` (never mock) when the DB or a canonical
    table is missing.  Read-only.  Carries the advisory safety stamps.
    """
    path = Path(db_path) if db_path is not None else _default_db_path()
    out: dict[str, Any] = {
        "report": "complex_systems_sqlite_bridge",
        "db_path": str(path),
        "db_available": False,
        "data_origin": "canonical_sqlite",
        "components": {},
        "safety": _contract.advisory_safety_stamps(),
        **_contract.canonical_truth_declaration(),
    }
    conn = _readonly_connect(path)
    if conn is None:
        out["state"] = INSUFFICIENT
        out["note"] = "runtime DB missing/unreadable — degraded, no mock fallback."
        return out
    out["db_available"] = True
    try:
        components = {
            "fingerprint_independence": fingerprint_independence(conn),
            "signal_cell_diffusion": signal_cell_diffusion(conn),
            "moltbook_repair": moltbook_repair_state(conn),
            "reconciliation_mismatch": reconciliation_mismatch_state(conn),
            "manual_trade_exposure": manual_trade_exposure(conn),
            "signal_freshness": signal_freshness(conn),
        }
    finally:
        conn.close()
    out["components"] = components
    available = [c for c in components.values() if c.get("available")]
    out["state"] = "OK" if available else INSUFFICIENT
    out["available_component_count"] = len(available)

    # Bridge the canonical loss state into the existing broken-windows model so
    # downstream consumers reuse one repair vocabulary rather than re-deriving.
    repair = components["moltbook_repair"]
    if repair.get("available"):
        try:
            try:
                from scripts.complex_systems_diagnostics import (
                    compute_broken_windows_discipline,
                )
            except ModuleNotFoundError:  # pragma: no cover
                from complex_systems_diagnostics import (  # type: ignore[no-redef]
                    compute_broken_windows_discipline,
                )
            out["broken_windows"] = compute_broken_windows_discipline({
                "closed_losses_without_moltbook":
                    repair.get("closed_losses_without_moltbook", 0),
                "loss_bridge_complete": repair.get("loss_bridge_complete", True),
            })
        except Exception:  # pragma: no cover - defensive
            pass
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="complex_systems_sqlite_bridge.py",
        description=(
            "Derive complex-systems inputs from canonical SQLite (read-only). "
            "Degrades to INSUFFICIENT_DATA; never mock; never an order."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = Path(args.db_path) if args.db_path else None
    report = build_canonical_complex_systems_state(db)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Complex-systems SQLite bridge: {report.get('state')}")
        print(f"  db: {report['db_path']} (available={report['db_available']})")
        for name, comp in report.get("components", {}).items():
            print(f"  [{comp.get('state', '?'):<16}] {name}")
    return 0


__all__ = [
    "fingerprint_independence",
    "signal_cell_diffusion",
    "moltbook_repair_state",
    "reconciliation_mismatch_state",
    "manual_trade_exposure",
    "signal_freshness",
    "build_canonical_complex_systems_state",
]


if __name__ == "__main__":
    raise SystemExit(main())
