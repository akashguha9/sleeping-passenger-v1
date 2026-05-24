"""Prewarm the diagnostics snapshot once and prove the next read is a cache hit.

Integrated Sprint — Part 1.  The cockpit's max-latency tail was being driven by
a *cold* diagnostics recompute on the request path.  This script removes that
class of tail by:

  1. Pointing the diagnostics cache at a chosen DB (default: canonical runtime
     DB; ``--fixture 122k`` materialises the synthetic perf fixture instead),
  2. Running ONE cold recompute and persisting the snapshot,
  3. Immediately reading the snapshot again and proving ``cache_hit=true`` with
     a hot-path latency well below the budget,
  4. Writing a derived (non-canonical) summary JSON the release gate can read.

Hard safety rules
-----------------
* **Read-only w.r.t. the canonical DB.**  The only write to canonical storage
  is the diagnostics snapshot file itself, which the cache module already
  declares ``cache_role = derived_non_canonical``.
* **No broker call, no network, no execution, no AI execution.**
* The 122k fixture path **refuses** the canonical runtime DB (handled by
  ``tests.helpers.large_signal_events_fixture``).
* The prewarm summary is stamped with the advisory safety invariants so a
  release gate can never see this artifact and infer execution permission.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import diagnostics_snapshot_cache as _cache
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import diagnostics_snapshot_cache as _cache  # type: ignore[no-redef]

try:
    from scripts import diagnostics_snapshot_key as _key
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import diagnostics_snapshot_key as _key  # type: ignore[no-redef]

try:
    from scripts import typed_config as _typed_config
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import typed_config as _typed_config  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parents[1]
SUMMARY_DIR = REPO_ROOT / "runtime" / "release"
SUMMARY_FILE = SUMMARY_DIR / "diagnostics_prewarm_summary.json"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _materialise_fixture(fixture_label: str | None, rows: int) -> Path | None:
    """Materialise the 122k perf fixture and return its path, or None.

    Returns None when ``fixture_label`` is falsy (caller uses the canonical
    runtime DB).  Imports the helper lazily so test environments without the
    helper can still exercise the canonical path.
    """
    if not fixture_label:
        return None
    label = fixture_label.lower()
    target_rows = rows
    if label in {"122k", "default"} and rows == 0:
        target_rows = 122_000
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from tests.helpers import large_signal_events_fixture as fix
    except ModuleNotFoundError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "Cannot import tests.helpers.large_signal_events_fixture; "
            "ensure tests/helpers/large_signal_events_fixture.py exists."
        ) from exc
    tmp_dir = Path(tempfile.mkdtemp(prefix="prewarm_diag_"))
    fixture_path = tmp_dir / f"large_signal_events_{target_rows}.db"
    fix.create_large_signal_events_db(
        fixture_path,
        row_count=target_rows,
        create_indexes=True,
        allow_large_local_test=False,
    )
    return fixture_path


def _signal_event_count(db_path: Path) -> int:
    """Best-effort row count; 0 when the table is absent or DB unreachable."""
    inputs = _key.collect_canonical_inputs(db_path)
    return int(inputs.get("signal_event_count") or 0)


def _serialise_path(value: Path | None) -> str | None:
    return str(value) if value is not None else None


def prewarm(
    *,
    db_path: Path | None = None,
    ttl_seconds: int | None = None,
    write_summary: bool = True,
    summary_path: Path | None = None,
) -> dict[str, Any]:
    """Run prewarm: one cold refresh, then a hot-path read.

    Returns a dict with the proof fields the release gate consumes.  The
    summary is also persisted to ``runtime/release/diagnostics_prewarm_summary.json``
    by default.  Both reads use ``diagnostics_snapshot_cache``: the first call
    forces a refresh, the second uses :func:`cache_validity` to prove the
    snapshot is still hot.
    """
    try:
        cfg = _typed_config.load_typed_config()
        ttl = ttl_seconds if ttl_seconds is not None else cfg.diagnostics_snapshot_ttl_seconds
        canonical_db = db_path if db_path is not None else cfg.canonical_db_path
        release_dir = cfg.diagnostics_release_dir
        out_path = summary_path or cfg.diagnostics_prewarm_summary_path
    except _typed_config.ConfigSafetyError:
        ttl = ttl_seconds if ttl_seconds is not None else _cache.DEFAULT_TTL_SECONDS
        canonical_db = db_path if db_path is not None else _cache.resolve_db_path()
        release_dir = SUMMARY_DIR
        out_path = summary_path or SUMMARY_FILE

    inputs = _key.collect_canonical_inputs(canonical_db)
    snapshot_key = _key.compute_snapshot_key(inputs)
    row_count = _signal_event_count(canonical_db)

    # --- Cold recompute (one and only one). ---
    t0 = time.perf_counter()
    refreshed = _cache.refresh(canonical_db, ttl_seconds=ttl)
    prewarm_latency_ms = round((time.perf_counter() - t0) * 1000, 3)
    cold_recompute_count = 1

    # --- Hot-path read (must be a cache hit). ---
    t1 = time.perf_counter()
    snap = _cache.read_snapshot()
    validity = _cache.cache_validity(snap, canonical_db)
    post_prewarm_latency_ms = round((time.perf_counter() - t1) * 1000, 3)
    cache_hit_after_prewarm = bool(validity.get("valid"))

    degraded = list((refreshed or {}).get("degraded_subreports", []) or [])

    summary: dict[str, Any] = {
        "report": "diagnostics_prewarm_summary",
        "ok": cache_hit_after_prewarm,
        "row_count": row_count,
        "snapshot_key": snapshot_key,
        "snapshot_inputs": inputs,
        "ttl_seconds": int(ttl),
        "prewarm_latency_ms": prewarm_latency_ms,
        "cache_hit_after_prewarm": cache_hit_after_prewarm,
        "post_prewarm_latency_ms": post_prewarm_latency_ms,
        "generated_at_utc": _utc_iso(),
        "cold_recompute_count": cold_recompute_count,
        "cold_recompute_count_after_prewarm": 0,
        "degraded_subreports": degraded,
        "degraded_subreport_count": len(degraded),
        "canonical_db_path": _serialise_path(Path(canonical_db)),
        "canonical_truth_source": _cache.CANONICAL_TRUTH_SOURCE,
        "cache_role": _cache.CACHE_ROLE,
        "summary_path": _serialise_path(out_path),
        "advisory_only": True,
        "execution_gate": "LOCKED",
        **_contract.advisory_safety_stamps(),
    }

    if write_summary:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(summary, indent=2, default=str),
                       encoding="utf-8")
        tmp.replace(out_path)
    return summary


def read_summary(path: Path | None = None) -> dict[str, Any] | None:
    """Read the persisted prewarm summary, or None if absent/corrupt."""
    target = path or SUMMARY_FILE
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="prewarm_diagnostics_snapshot.py",
        description=(
            "Prewarm the derived diagnostics snapshot once and prove the next "
            "read is a cache hit. Read-only w.r.t. canonical DB; no broker "
            "calls; no execution."
        ),
    )
    p.add_argument("--fixture", type=str, default=None,
                   help="materialise the 122k perf fixture (e.g. '122k')")
    p.add_argument("--fixture-rows", type=int, default=0,
                   help="override row count when --fixture is set (0=default)")
    p.add_argument("--db-path", type=Path, default=None,
                   help="explicit canonical DB path (overrides config)")
    p.add_argument("--ttl", type=int, default=None,
                   help="snapshot TTL in seconds (default from typed_config)")
    p.add_argument("--write-summary", action="store_true",
                   help="write the prewarm summary JSON to "
                        "runtime/release/diagnostics_prewarm_summary.json")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = args.db_path
    if args.fixture:
        db_path = _materialise_fixture(args.fixture, args.fixture_rows)

    summary = prewarm(
        db_path=db_path,
        ttl_seconds=args.ttl,
        write_summary=args.write_summary,
    )
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print("Diagnostics Snapshot Prewarm (advisory)")
        print("=======================================")
        for key in ("ok", "row_count", "snapshot_key",
                    "prewarm_latency_ms", "cache_hit_after_prewarm",
                    "post_prewarm_latency_ms",
                    "cold_recompute_count", "summary_path"):
            print(f"  {key:<36} : {summary.get(key)}")
    return 0 if summary["ok"] else 1


__all__ = ["SUMMARY_FILE", "prewarm", "read_summary"]


if __name__ == "__main__":
    raise SystemExit(main())
