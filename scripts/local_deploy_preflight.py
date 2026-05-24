"""Local deploy preflight — read-only environment + safety checks.

This is the *positioning* layer (Kanté): before the operator starts the local
stack, run a battery of cheap, read-only checks and report each as
PASS / WARN / FAIL / INFO with an exact reason.  ``scripts/release_gate.py``
aggregates these into a single gate verdict.

Every check is read-only with respect to the DB and the network:
* no DB writes, no refresh runs, no broker calls, no order placement;
* the only optional network touch is a localhost backend health probe, and
  only when ``check_backend=True`` (off by default).

Severity model
--------------
* ``FAIL`` — a hard safety/readiness violation (blocks release).
* ``WARN`` — a real readiness signal that should be looked at.
* ``INFO`` — informational; never blocks (e.g. optional tooling absent).
* ``PASS`` — the check is satisfied.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / "runtime"
DEFAULT_DB = RUNTIME_DIR / "mvp_local.db"

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"
# Mutation-guard release impact can escalate to BLOCK (an unguarded high-risk
# mutation script).  Distinct from per-check FAIL; the release gate maps a
# BLOCK mutation impact onto a gate FAIL verdict.
BLOCK = "BLOCK"

# Core tables the advisory MVP relies on.
_CORE_TABLES = (
    "signal_events",
    "manual_trades",
    "reconciliation_results",
    "moltbook_entries",
    "duplicate_fingerprints",
    "signal_cell_index",
)

# Fake/demo Moltbook pollution markers (FABRIC_SPY / FABRIC_QQQ event ids,
# the "Persistence above 0.8" demo thesis, and the SPY "Thesis A" seed).
_POLLUTION_EVENT_PREFIXES = ("FABRIC_SPY", "FABRIC_QQQ", "FABRIC")
_POLLUTION_THESES = ("Persistence above 0.8", "Thesis A")


def _check(name: str, status: str, detail: str, **extra: Any) -> dict[str, Any]:
    out = {"name": name, "status": status, "detail": detail}
    out.update(extra)
    return out


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


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_python() -> dict[str, Any]:
    return _check(
        "python_available", PASS,
        f"Python {sys.version_info.major}.{sys.version_info.minor}."
        f"{sys.version_info.micro} on {sys.platform}.",
    )


def check_node_npm() -> dict[str, Any]:
    node = shutil.which("node")
    npm = shutil.which("npm")
    if node and npm:
        return _check("node_npm_available", PASS,
                      f"node={node}; npm={npm}.")
    # Frontend tooling is optional for the advisory backend — INFO, not a fail.
    return _check(
        "node_npm_available", INFO,
        "node/npm not found on PATH — frontend build skipped; advisory "
        "backend does not require them.",
        node=bool(node), npm=bool(npm),
    )


def check_db_exists(db_path: Path) -> dict[str, Any]:
    if db_path.exists():
        return _check("runtime_db_exists", PASS, f"DB present at {db_path}.")
    return _check("runtime_db_exists", FAIL,
                  f"runtime DB missing at {db_path} — initialize before release.")


def check_sqlite_tables(db_path: Path) -> dict[str, Any]:
    conn = _readonly_connect(db_path)
    if conn is None:
        return _check("sqlite_tables_exist", FAIL,
                      "DB unreadable or missing; cannot verify tables.")
    present: set[str] = set()
    try:
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            present = {r["name"] for r in rows}
        except sqlite3.DatabaseError as exc:
            # File exists and `_readonly_connect` succeeded, but the
            # blob is not a real SQLite database — fail closed instead
            # of letting the DatabaseError bubble up and crash the gate.
            return _check(
                "sqlite_tables_exist",
                FAIL,
                f"DB file is corrupt or not a SQLite database: {type(exc).__name__}.",
            )
    finally:
        conn.close()
    missing = [t for t in _CORE_TABLES if t not in present]
    if missing:
        return _check("sqlite_tables_exist", FAIL,
                      f"missing core tables: {missing}.", missing=missing)
    return _check("sqlite_tables_exist", PASS,
                  f"all {len(_CORE_TABLES)} core tables present.")


def check_moltbook_no_fake_pollution(db_path: Path) -> dict[str, Any]:
    """FAIL if any fake SPY/QQQ/FABRIC demo Moltbook rows survive."""
    conn = _readonly_connect(db_path)
    if conn is None:
        return _check("moltbook_no_fake_pollution", WARN,
                      "DB unreadable; cannot verify Moltbook hygiene.")
    polluted: list[str] = []
    try:
        try:
            rows = conn.execute(
                "SELECT entry_id, event_id, ticker, original_signal_thesis,"
                " manual_trade_log_id FROM moltbook_entries"
            ).fetchall()
        except sqlite3.Error:
            rows = []
        for r in rows:
            event_id = str(r["event_id"] or "")
            thesis = str(r["original_signal_thesis"] or "")
            linked = str(r["manual_trade_log_id"] or "").strip()
            is_fabric = any(event_id.upper().startswith(p)
                            for p in _POLLUTION_EVENT_PREFIXES)
            is_demo_thesis = any(t in thesis for t in _POLLUTION_THESES)
            # Only unlinked (no real trade) demo rows count as pollution.
            if (is_fabric or is_demo_thesis) and not linked:
                polluted.append(str(r["entry_id"]))
    finally:
        conn.close()
    if polluted:
        return _check("moltbook_no_fake_pollution", FAIL,
                      f"{len(polluted)} fake/demo Moltbook row(s) present — "
                      "run moltbook_cleanup_fake_seed.py --apply.",
                      polluted_entry_ids=polluted[:25])
    return _check("moltbook_no_fake_pollution", PASS,
                  "no fake SPY/QQQ/FABRIC Moltbook pollution detected.")


def check_moltbook_bridge_idempotent(db_path: Path) -> dict[str, Any]:
    """Run the bridge dry-run twice; the created count must be stable."""
    try:
        try:
            from scripts.moltbook_reconciliation_bridge import (
                sync_reconciliation_losses_to_moltbook,
            )
        except ModuleNotFoundError:
            from moltbook_reconciliation_bridge import (  # type: ignore[no-redef]
                sync_reconciliation_losses_to_moltbook,
            )
        first = sync_reconciliation_losses_to_moltbook(db_path, write=False)
        second = sync_reconciliation_losses_to_moltbook(db_path, write=False)
    except Exception as exc:  # pragma: no cover - defensive
        return _check("moltbook_bridge_idempotent", WARN,
                      f"bridge dry-run errored: {type(exc).__name__}.")
    if first.get("created") == second.get("created"):
        return _check("moltbook_bridge_idempotent", PASS,
                      f"bridge dry-run stable (created={first.get('created')}).")
    return _check("moltbook_bridge_idempotent", FAIL,
                  "bridge dry-run is not idempotent — created count changed "
                  f"between runs ({first.get('created')} -> {second.get('created')}).")


def check_closed_losses_detectable(db_path: Path) -> dict[str, Any]:
    """INFO: closed losses and their Moltbook coverage are *detectable*.

    GLD/TSM truth is not required forever, but if there are closed losses we
    should be able to see whether each has a Moltbook learning entry.
    """
    conn = _readonly_connect(db_path)
    if conn is None:
        return _check("closed_losses_detectable", INFO, "DB unreadable.")
    try:
        loss = 0
        mb = 0
        try:
            loss = int(conn.execute(
                "SELECT COUNT(*) FROM reconciliation_results"
                " WHERE UPPER(outcome_status) LIKE '%LOSS%'"
            ).fetchone()[0])
        except sqlite3.Error:
            pass
        try:
            mb = int(conn.execute(
                "SELECT COUNT(*) FROM moltbook_entries"
                " WHERE mistake_type IN ('trade_loss','manual_exit_loss',"
                "'stop_loss_breach')"
            ).fetchone()[0])
        except sqlite3.Error:
            pass
    finally:
        conn.close()
    return _check("closed_losses_detectable", INFO,
                  f"closed losses={loss}; loss-review Moltbook entries={mb}.",
                  closed_losses=loss, loss_review_entries=mb)


def check_execution_locked(db_path: Path) -> dict[str, Any]:
    """FAIL if any persisted row carries a broker flag or AI execution count.

    Defence in depth: the advisory contract says execution is LOCKED; this
    proves no row in the live DB contradicts it.
    """
    conn = _readonly_connect(db_path)
    if conn is None:
        # No DB → nothing can be unlocked; the contract still holds.
        return _check("execution_gate_locked", PASS,
                      "no DB present; execution gate LOCKED by contract.")
    offenders: list[str] = []
    try:
        for table in ("manual_trades", "reconciliation_results"):
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if "broker_api_called" in cols:
                n = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                    " WHERE COALESCE(broker_api_called,0) != 0"
                ).fetchone()[0]
                if n:
                    offenders.append(f"{table}.broker_api_called={n}")
            if "ai_execution_count" in cols:
                n = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                    " WHERE COALESCE(ai_execution_count,0) != 0"
                ).fetchone()[0]
                if n:
                    offenders.append(f"{table}.ai_execution_count={n}")
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        conn.close()
        return _check("execution_gate_locked", WARN,
                      f"could not verify broker flags: {type(exc).__name__}.")
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if offenders:
        return _check("execution_gate_locked", FAIL,
                      f"execution invariants violated: {offenders}.",
                      offenders=offenders)
    return _check("execution_gate_locked", PASS,
                  "execution_gate=LOCKED; ai_execution_count=0; "
                  "broker_api_called=0 across rows.")


def check_no_broker_route() -> dict[str, Any]:
    """FAIL if the API server exposes anything resembling a broker route."""
    api = REPO_ROOT / "scripts" / "api_server.py"
    if not api.exists():
        return _check("no_broker_route_exposed", INFO, "api_server.py absent.")
    text = api.read_text(encoding="utf-8", errors="ignore").lower()
    forbidden = (
        "/place_order", "/submit_order", "/execute_trade", "/broker",
        "place_broker_order", "submit_broker_order",
    )
    hits = [tok for tok in forbidden if tok in text]
    if hits:
        return _check("no_broker_route_exposed", FAIL,
                      f"api_server exposes broker-like route token(s): {hits}.",
                      hits=hits)
    return _check("no_broker_route_exposed", PASS,
                  "no broker / order-placement route exposed by api_server.")


def check_frontend_env() -> dict[str, Any]:
    """If frontend/.env.local exists, confirm it points at the expected backend."""
    env_path = REPO_ROOT / "frontend" / ".env.local"
    host = os.environ.get("API_HOST", "127.0.0.1")
    port = os.environ.get("API_PORT", "8000")
    expected_hosts = {f"{host}:{port}", f"127.0.0.1:{port}", f"localhost:{port}"}
    if not env_path.exists():
        return _check("frontend_env_points_to_backend", INFO,
                      "frontend/.env.local absent — using build defaults.")
    body = env_path.read_text(encoding="utf-8", errors="ignore")
    line = next(
        (ln for ln in body.splitlines()
         if ln.strip().startswith("NEXT_PUBLIC_API_BASE_URL")),
        "",
    )
    value = line.split("=", 1)[1].strip() if "=" in line else ""
    if value and any(h in value for h in expected_hosts):
        return _check("frontend_env_points_to_backend", PASS,
                      f"NEXT_PUBLIC_API_BASE_URL={value} matches backend.")
    return _check("frontend_env_points_to_backend", WARN,
                  f"NEXT_PUBLIC_API_BASE_URL={value or '(unset)'} does not "
                  f"match expected backend {sorted(expected_hosts)}.")


def check_mock_fallback_explicit() -> dict[str, Any]:
    """Confirm the synthetic/mock fallback mode is a *named* mode, not silent."""
    try:
        try:
            from scripts.runtime_common import get_source_mode, VALID_SOURCE_MODES
        except ModuleNotFoundError:
            from runtime_common import get_source_mode, VALID_SOURCE_MODES  # type: ignore[no-redef]
        mode = get_source_mode()
    except Exception as exc:  # pragma: no cover - defensive
        return _check("mock_fallback_explicit", WARN,
                      f"could not resolve source_mode: {type(exc).__name__}.")
    if mode in VALID_SOURCE_MODES:
        return _check("mock_fallback_explicit", PASS,
                      f"source_mode={mode} is explicit (fallback is named, "
                      "not silent).")
    return _check("mock_fallback_explicit", WARN,
                  f"source_mode={mode} not in {sorted(VALID_SOURCE_MODES)}.")


# ---------------------------------------------------------------------------
# Kanté Defensive Sprint — operator-guard coverage + diagnostics service health
# ---------------------------------------------------------------------------

# Modules considered an acceptable centralized authorization boundary.  A
# mutation-capable script is "guarded" if it routes through either of these.
_GUARD_MARKERS = ("operator_permission_guard", "operator_audit_log")


def scan_mutation_script_guarding() -> dict[str, Any]:
    """Discover ``--apply`` / ``--yes`` mutation scripts and their guard status.

    Read-only static scan of ``scripts/*.py``: a script that declares an
    ``--apply`` or ``--yes`` argparse flag is mutation-capable; it is *guarded*
    iff it references a centralized authorization boundary.
    """
    scripts_dir = REPO_ROOT / "scripts"
    guarded: list[str] = []
    unguarded: list[str] = []
    for path in sorted(scripts_dir.glob("*.py")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover - defensive
            continue
        is_mutation = ('"--apply"' in text or "'--apply'" in text
                       or '"--yes"' in text or "'--yes'" in text)
        if not is_mutation or "add_argument" not in text:
            continue
        if any(marker in text for marker in _GUARD_MARKERS):
            guarded.append(path.name)
        else:
            unguarded.append(path.name)
    return {"guarded": guarded, "unguarded": unguarded}


def diagnostics_service_health() -> dict[str, Any]:
    """Best-effort, cheap read of diagnostics_service availability + status.

    Does NOT force a heavy recompute: if no cached snapshot exists, the status
    is reported UNKNOWN rather than recomputing inside a preflight.
    """
    try:
        try:
            from scripts.diagnostics_service import get_diagnostics_snapshot
            from scripts import diagnostics_snapshot_cache as cache
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from diagnostics_service import get_diagnostics_snapshot  # type: ignore
            import diagnostics_snapshot_cache as cache  # type: ignore
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": False, "status": "UNKNOWN",
                "detail": f"import failed: {type(exc).__name__}"}
    try:
        if cache.read_snapshot() is None:
            return {"available": True, "status": "UNKNOWN",
                    "detail": "no cached snapshot (not recomputing in preflight)"}
        # Huge max_age so an existing (even stale) snapshot is reused, never
        # recomputed, keeping the preflight cheap.
        snap = get_diagnostics_snapshot(
            use_cache=True, refresh=False, include_heavy=False,
            max_age_seconds=10 ** 9)
        return {"available": True, "status": str(snap.get("status", "UNKNOWN")),
                "detail": f"cache_status={snap.get('cache_status')}"}
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": True, "status": "UNKNOWN",
                "detail": f"snapshot read failed: {type(exc).__name__}"}


def evaluate_guard_coverage_status(unguarded_count: int, guard_available: bool) -> str:
    """Pure: PASS iff the guard is importable and no mutation script is unwired."""
    if not guard_available:
        return WARN
    return WARN if unguarded_count > 0 else PASS


# A mutation script is HIGH severity (a BLOCK if unguarded) when it can restore
# the DB, migrate schema, delete/drop, mutate the runtime DB via
# UPDATE/DELETE/INSERT, or carries a broker/order/execution pattern.  Otherwise
# it is a low-severity repair-like write (a WARN if unguarded).
_HIGH_SEVERITY_NAME_TOKENS = ("restore", "migrat", "drop", "delete", "purge",
                              "wipe", "broker", "execute", "order")
_HIGH_SEVERITY_SQL_TOKENS = ("DELETE FROM", "DROP TABLE", "DROP INDEX",
                             "UPDATE ", "INSERT ", "ALTER TABLE")
_BROKER_EXEC_TOKENS = ("place_order", "submit_order", "execute_trade",
                       "broker_api", "unlock_execution")


def classify_mutation_script_severity(script_name: str) -> str:
    """Pure-ish: classify an unguarded mutation script as HIGH or LOW severity.

    Reads ``scripts/<name>`` and inspects its name + body.  Defaults to HIGH
    when the file cannot be read (fail safe — an unreadable unguarded mutation
    script must not silently downgrade the release impact).
    """
    name = script_name.lower()
    if any(tok in name for tok in _HIGH_SEVERITY_NAME_TOKENS):
        return "HIGH"
    path = REPO_ROOT / "scripts" / script_name
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "HIGH"
    upper = text.upper()
    if any(tok in upper for tok in _HIGH_SEVERITY_SQL_TOKENS):
        return "HIGH"
    if any(tok in text for tok in _BROKER_EXEC_TOKENS):
        return "HIGH"
    return "LOW"


def evaluate_mutation_guard_impact(
    guarded_count: int,
    unguarded_names: list[str],
    *,
    high_severity_count: int,
) -> dict[str, Any]:
    """Pure: compute MutationGuardCoverage / risk and the release impact.

    * risk == 0                         -> PASS
    * 0 < risk <= 0.25 and no HIGH      -> WARN
    * risk > 0.25 OR any HIGH unguarded -> BLOCK
    """
    total = guarded_count + len(unguarded_names)
    coverage = guarded_count / max(total, 1)
    risk = 1.0 - coverage
    if risk == 0:
        impact = PASS
    elif risk <= 0.25 and high_severity_count == 0:
        impact = WARN
    else:
        impact = BLOCK
    return {
        "mutation_guard_coverage": round(coverage, 4),
        "mutation_guard_risk": round(risk, 4),
        "mutation_guard_release_impact": impact,
        "mutation_scripts_unguarded_high_severity_count": high_severity_count,
    }


def build_kante_defensive_summary() -> dict[str, Any]:
    """Summarize operator-guard coverage + diagnostics service for the gate.

    Advisory / non-blocking: surfaced for operator visibility.  ``release_gate
    _impact`` is WARN when coverage is incomplete or the service is down, but
    this summary does not by itself FAIL the release gate.
    """
    try:
        try:
            from scripts import operator_permission_guard  # noqa: F401
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            import operator_permission_guard  # type: ignore  # noqa: F401
        guard_available = True
    except Exception:  # pragma: no cover - defensive
        guard_available = False

    coverage = scan_mutation_script_guarding()
    svc = diagnostics_service_health()

    # Severity-classify every unguarded mutation script.  A HIGH-severity
    # unguarded script (restore/migrate/delete/UPDATE/INSERT/broker) escalates
    # the mutation-guard impact to BLOCK; low-severity repair-like scripts only
    # WARN.  With all four repair scripts wired, the unguarded set is empty.
    severities = {name: classify_mutation_script_severity(name)
                  for name in coverage["unguarded"]}
    high_severity = [n for n, s in severities.items() if s == "HIGH"]

    mutation = evaluate_mutation_guard_impact(
        len(coverage["guarded"]), coverage["unguarded"],
        high_severity_count=len(high_severity))
    mutation_impact = (mutation["mutation_guard_release_impact"]
                       if guard_available else WARN)

    # auth_guard_status mirrors the mutation-guard impact (PASS/WARN/BLOCK),
    # downgraded to WARN if the guard module itself is unimportable.
    guard_status = mutation_impact if guard_available else WARN

    # Overall release impact = the most severe of mutation-guard impact and the
    # diagnostics-service signal.  A BLOCK from an unguarded high-risk mutation
    # script is a real BLOCK (the release gate fails on it).
    impact = mutation_impact
    if impact == PASS and (not svc["available"] or svc["status"] == "UNKNOWN"):
        impact = WARN
    if svc["status"] == "BLOCK" and impact == PASS:
        impact = WARN  # diagnostics BLOCK is advisory; do not auto-BLOCK release

    return {
        "operator_permission_guard_available": guard_available,
        "auth_guard_status": guard_status,
        "mutation_scripts_guarded": coverage["guarded"],
        "mutation_scripts_unguarded": coverage["unguarded"],
        "mutation_scripts_unguarded_names": coverage["unguarded"],
        "mutation_scripts_guarded_count": len(coverage["guarded"]),
        "mutation_scripts_unguarded_count": len(coverage["unguarded"]),
        "mutation_scripts_unguarded_high_severity": high_severity,
        "mutation_guard_coverage": mutation["mutation_guard_coverage"],
        "mutation_guard_risk": mutation["mutation_guard_risk"],
        "mutation_guard_release_impact": mutation_impact,
        "diagnostics_service_available": svc["available"],
        "diagnostics_service_status": svc["status"],
        "release_gate_impact": impact,
    }


def check_kante_defensive_gates() -> dict[str, Any]:
    """INFO check: surface guard coverage + diagnostics service in the preflight.

    Deliberately INFO (never affects the gate verdict): the unguarded-script
    and service-status signals are advisory.  The detailed status lives in the
    ``kante_defensive`` summary block of the report.
    """
    summary = build_kante_defensive_summary()
    detail = (
        f"guard={'avail' if summary['operator_permission_guard_available'] else 'MISSING'}; "
        f"mutation guarded={summary['mutation_scripts_guarded_count']}, "
        f"unguarded={summary['mutation_scripts_unguarded_count']}; "
        f"diagnostics_service={summary['diagnostics_service_status']} "
        f"(impact={summary['release_gate_impact']})."
    )
    return _check("kante_defensive_gates", INFO, detail, **summary)


def check_backend_health(timeout: float = 1.0) -> dict[str, Any]:
    """Probe the local backend /health route.  WARN (not FAIL) if not running."""
    host = os.environ.get("API_HOST", "127.0.0.1")
    port = os.environ.get("API_PORT", "8000")
    url = os.environ.get("MVP_BACKEND_HEALTH_URL", f"http://{host}:{port}/health")
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - localhost only
            ok = 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return _check("backend_health", WARN,
                      f"backend not reachable at {url} — start it before "
                      "serving the UI (offline checks still apply).")
    if ok:
        return _check("backend_health", PASS, f"backend healthy at {url}.")
    return _check("backend_health", WARN, f"backend at {url} returned non-2xx.")


def run_preflight(
    db_path: Path | None = None,
    *,
    check_backend: bool = False,
) -> dict[str, Any]:
    """Run all offline checks (plus the backend probe when requested)."""
    db = Path(db_path) if db_path is not None else DEFAULT_DB
    checks: list[dict[str, Any]] = [
        check_python(),
        check_node_npm(),
        check_db_exists(db),
        check_sqlite_tables(db),
        check_moltbook_no_fake_pollution(db),
        check_moltbook_bridge_idempotent(db),
        check_closed_losses_detectable(db),
        check_execution_locked(db),
        check_no_broker_route(),
        check_frontend_env(),
        check_mock_fallback_explicit(),
        check_kante_defensive_gates(),
    ]
    if check_backend:
        checks.append(check_backend_health())
    counts = {PASS: 0, WARN: 0, FAIL: 0, INFO: 0}
    for c in checks:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    return {
        "report": "local_deploy_preflight",
        "db_path": str(db),
        "db_exists": db.exists(),
        "checked_backend": bool(check_backend),
        "checks": checks,
        "counts": counts,
        # Advisory, non-blocking Kanté-defensive coverage summary.
        "kante_defensive": build_kante_defensive_summary(),
        **_contract.advisory_safety_stamps(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="local_deploy_preflight.py",
        description=(
            "Read-only local deploy preflight (PASS/WARN/FAIL/INFO per check). "
            "No DB writes, no broker calls."
        ),
    )
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--check-backend", action="store_true",
                   help="Also probe the local backend /health route.")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = run_preflight(args.db_path, check_backend=args.check_backend)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("Local Deploy Preflight")
        print("=" * 22)
        for c in report["checks"]:
            print(f"  [{c['status']:<4}] {c['name']:<28} {c['detail']}")
        print(f"\n  counts: {report['counts']}")
    return 0 if report["counts"][FAIL] == 0 else 1


__all__ = [
    "PASS", "WARN", "FAIL", "INFO",
    "run_preflight",
    "check_python", "check_node_npm", "check_db_exists",
    "check_sqlite_tables", "check_moltbook_no_fake_pollution",
    "check_moltbook_bridge_idempotent", "check_closed_losses_detectable",
    "check_execution_locked", "check_no_broker_route", "check_frontend_env",
    "check_mock_fallback_explicit", "check_backend_health",
    "check_kante_defensive_gates", "scan_mutation_script_guarding",
    "diagnostics_service_health", "evaluate_guard_coverage_status",
    "classify_mutation_script_severity", "evaluate_mutation_guard_impact",
    "build_kante_defensive_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
