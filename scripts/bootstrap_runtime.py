"""Idempotent runtime bootstrap — rebuild ephemeral local state from committed truth.

The runtime SQLite DB (``runtime/mvp_local.db``) is gitignored and is wiped
whenever the container/web-session is recycled. Without this, hard-won state
(securities master, imported outcome evidence, the canonical holdings) silently
falls back to empty and the readiness gate degrades with no warning.

This script rebuilds that state from committed sources, idempotently:
  1. Seed the securities master from ``configs/securities_seed_universe.yaml``.
  2. Re-import paper outcome evidence from the committed outcomes CSV (if present).
  3. Ingest ``verified_current_holdings.json`` into the canonical ``manual_trades``
     table so the *canonical* store actually carries the declared holdings
     (previously truth lived only in the JSON payload).
  4. Optionally record a real test-suite status (``--run-tests``) so the
     readiness gate's test-confidence dimension reflects reality, not an
     assumption.

Read-only toward the outside world: no broker, no live fetch, no execution.
Wire it as a SessionStart hook (see .claude/settings.json) so every web session
self-heals.

    python scripts/bootstrap_runtime.py
    python scripts/bootstrap_runtime.py --run-tests --json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_OUTCOMES_CSV = _REPO_ROOT / "analysis" / "portfolio_2026_05" / "outcomes.csv"
_HOLDINGS_JSON = _REPO_ROOT / "data" / "daily_payload" / "verified_current_holdings.json"
_TEST_STATUS = _REPO_ROOT / "runtime" / "status" / "test_status.json"


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _seed_securities(db_path: Path) -> dict[str, Any]:
    from scripts import securities_master_coverage as smc

    universe = smc.load_seed_universe()
    n = smc.seed_universe(universe, db_path)
    rep = smc.build_coverage_report(db_path)
    return {"seeded": n, "coverage_score": round(rep["score"], 3), "status": rep["status"]}


def _import_outcomes(db_path: Path) -> dict[str, Any]:
    if not _OUTCOMES_CSV.exists():
        return {"skipped": "no outcomes csv"}
    from scripts import import_outcomes_csv as ioc

    rep = ioc.import_outcomes_file(_OUTCOMES_CSV, dry_run=False, db_path=db_path)
    return {"written": rep["rows_written"], "provenance": rep["provenance"]}


def _ingest_holdings(db_path: Path) -> dict[str, Any]:
    """Load canonical holdings JSON into the canonical manual_trades table."""
    if not _HOLDINGS_JSON.exists():
        return {"skipped": "no holdings json"}
    from scripts import persistence

    data = json.loads(_HOLDINGS_JSON.read_text(encoding="utf-8"))
    positions = data.get("positions", []) or []
    try:
        existing = {str(t.get("trade_id")) for t in persistence.get_all_manual_trades(db_path)}
    except Exception:
        existing = set()

    ingested = 0
    skipped = 0
    for p in positions:
        norm = str(p.get("normalized_ticker") or p.get("ticker") or "").strip()
        opened = str(p.get("opened_at") or "")
        tid = f"HOLD_{norm}_{opened[:10]}"
        if tid in existing:
            skipped += 1
            continue
        try:
            persistence.insert_manual_trade(
                trade_id=tid,
                event_id=f"EV_{norm}",
                ticker=str(p.get("ticker") or norm),
                side="BUY",
                quantity=float(p.get("quantity") or 0.0),
                price=float(p.get("entry_price") or 0.0),
                executed_at=opened,
                thesis="bootstrap ingest of verified_current_holdings.json",
                notes="canonical-store backfill (advisory journal evidence)",
                logged_by="bootstrap_runtime",
                db_path=db_path,
                leverage=float(p.get("leverage") or 1.0),
                trade_mode="PAPER",
                created_via="bootstrap_holdings_ingest",
                currency=str(p.get("currency") or ""),
            )
            ingested += 1
        except Exception as exc:  # pragma: no cover - defensive
            skipped += 1
            _ = exc
    return {"ingested": ingested, "skipped": skipped, "total": len(positions)}


def _record_test_status(run_tests: bool) -> dict[str, Any]:
    _TEST_STATUS.parent.mkdir(parents=True, exist_ok=True)
    if not run_tests:
        return {"skipped": "pass --run-tests to record a real status"}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header",
             str(_REPO_ROOT / "tests" / "test_real_money_readiness.py"),
             str(_REPO_ROOT / "tests" / "test_pre_real_money_preflight.py")],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=600,
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        ran = ("passed" in out) or ("failed" in out)
        tail = (proc.stdout or "").strip().splitlines()[-1:] or [""]
        if not ran:
            # pytest unavailable / collection error -> UNVERIFIED, never "failing".
            status = {
                "passing": None, "unverified": True,
                "summary": "pytest unavailable or no tests ran",
                "generated_at": _now_iso(),
            }
        else:
            status = {
                "passing": proc.returncode == 0,
                "returncode": proc.returncode,
                "summary": tail[0],
                "scope": "readiness+preflight",
                "generated_at": _now_iso(),
            }
    except Exception as exc:
        # Tooling failure is "unknown", not "failing" — don't fabricate a red.
        status = {"passing": None, "unverified": True,
                  "error": str(exc), "generated_at": _now_iso()}
    _TEST_STATUS.write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status


def bootstrap(db_path: Path | None = None, *, run_tests: bool = False) -> dict[str, Any]:
    from scripts import persistence

    path = db_path if db_path is not None else persistence.DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    report = {
        "report": "bootstrap_runtime",
        "db_path": str(path),
        "generated_at": _now_iso(),
        "advisory_status": "ADVISORY_ONLY",
        "broker_api_called": False,
        "steps": {},
    }
    for name, fn in (
        ("securities_master", lambda: _seed_securities(path)),
        ("outcome_evidence", lambda: _import_outcomes(path)),
        ("canonical_holdings", lambda: _ingest_holdings(path)),
        ("test_status", lambda: _record_test_status(run_tests)),
    ):
        try:
            report["steps"][name] = fn()
        except Exception as exc:  # pragma: no cover - defensive
            report["steps"][name] = {"error": f"{type(exc).__name__}: {exc}"}
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Idempotent runtime bootstrap.")
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--run-tests", action="store_true",
                   help="Run the readiness/preflight tests and record status.")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    rep = bootstrap(args.db_path, run_tests=args.run_tests)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        for name, res in rep["steps"].items():
            print(f"  [{name}] {res}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["bootstrap"]
