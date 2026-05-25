"""Performance / load probe — prove bounded reads on a synthetic temp DB.

Kanté Sprint 2 — Task 3.  Builds a throwaway SQLite DB with synthetic rows,
runs the indexed query helpers from :mod:`scripts.signal_index_query`, and
asserts every result set is bounded by ``MAX_LIMIT`` regardless of how many
rows exist or how large a ``limit`` the caller asks for.

This NEVER touches the operator's runtime DB: it always creates its own temp
file (or uses a caller-supplied path).  Read-only with respect to any real
data; no broker calls; no execution.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import persistence as _persistence
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import persistence as _persistence  # type: ignore[no-redef]

try:
    from scripts import signal_index_query as _siq
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import signal_index_query as _siq  # type: ignore[no-redef]


def build_synthetic_db(db_path: Path, *, rows: int = 2000) -> dict[str, Any]:
    """Populate a temp DB with ``rows`` synthetic fingerprints and cells."""
    _persistence.init_schema(db_path)
    _siq.ensure_indexes(db_path)
    sectors = ("TECH", "ENERGY", "FIN", "HEALTH", "MATERIALS")
    for i in range(rows):
        _persistence.upsert_duplicate_fingerprint(
            f"fp-{i}", source_type="rss", event_type="news",
            ticker=f"T{i % 50}", event_id=f"EV{i}", db_path=db_path,
        )
        _persistence.upsert_signal_cell(
            f"cell-{i}", source_type="rss", sector=sectors[i % len(sectors)],
            event_type="earnings", db_path=db_path,
        )
    return {"rows_inserted": rows}


def probe(
    db_path: Path | None = None,
    *,
    rows: int = 2000,
    requested_limit: int = 10_000_000,
) -> dict[str, Any]:
    """Run the critical bounded queries and assert each is row-capped.

    ``requested_limit`` is deliberately absurd to prove the helper clamps it to
    ``MAX_LIMIT`` rather than returning an unbounded set.
    """
    own_temp = db_path is None
    if own_temp:
        tmp_dir = Path(tempfile.mkdtemp(prefix="mvp-perf-probe-"))
        target = tmp_dir / "perf_probe.db"
    else:
        target = Path(db_path)

    out: dict[str, Any] = {
        "report": "performance_probe",
        "db_path": str(target),
        "used_temp_db": own_temp,
        "max_limit": _siq.MAX_LIMIT,
        "requested_limit": requested_limit,
        "checks": [],
        **_contract.advisory_safety_stamps(),
    }
    build = build_synthetic_db(target, rows=rows)
    out["rows_inserted"] = build["rows_inserted"]

    def _record(name: str, result: dict[str, Any], elapsed_ms: float) -> None:
        rc = result.get("row_count", 0)
        out["checks"].append({
            "name": name,
            "row_count": rc,
            "bounded": rc <= _siq.MAX_LIMIT,
            "clamped_limit": result.get("limit"),
            "elapsed_ms": round(elapsed_ms, 3),
            "query_plan": result.get("query_plan", ""),
        })

    t0 = time.perf_counter()
    r = _siq.query_duplicate_fingerprints(target, ticker="T1",
                                          limit=requested_limit)
    _record("dfp_by_ticker", r, (time.perf_counter() - t0) * 1000)

    t0 = time.perf_counter()
    r = _siq.query_signal_cells(target, sector="TECH", limit=requested_limit)
    _record("sci_by_sector", r, (time.perf_counter() - t0) * 1000)

    t0 = time.perf_counter()
    r = _siq.query_signal_cells(target, source_type="rss", limit=requested_limit)
    _record("sci_by_source_type", r, (time.perf_counter() - t0) * 1000)

    out["all_bounded"] = all(c["bounded"] for c in out["checks"])
    out["max_row_count"] = max((c["row_count"] for c in out["checks"]), default=0)
    out["state"] = "PASS" if out["all_bounded"] else "FAIL"
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="performance_probe.py",
        description=(
            "Probe bounded query behaviour on a synthetic temp DB. Never "
            "touches the runtime DB; never a broker call."
        ),
    )
    p.add_argument("--rows", type=int, default=2000)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = probe(rows=args.rows)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Performance probe: {report['state']}")
        print(f"  rows inserted : {report['rows_inserted']}")
        print(f"  max row_count : {report['max_row_count']} (cap {report['max_limit']})")
        for c in report["checks"]:
            print(f"  [{'OK' if c['bounded'] else 'FAIL'}] {c['name']:<20} "
                  f"rows={c['row_count']} {c['elapsed_ms']}ms")
    return 0 if report["state"] == "PASS" else 1


__all__ = ["build_synthetic_db", "probe"]


if __name__ == "__main__":
    raise SystemExit(main())
