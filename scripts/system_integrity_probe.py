"""
System integrity probe — one deterministic, read-only sweep of the
analytical spine.

Role
----
``/health`` answers "is the process alive"; ``/health/full`` answers
"what is the security posture".  Neither answers the operator's real
question after a deploy, an upgrade, or a suspicious morning: *does the
analytical machine still work?*  This probe does — one call walks:

  * schema        — every expected table exists; sentinel additive
                    migrations applied
  * configs       — titration, outcome-contract, and causal-graph
                    configs load and validate
  * engines       — titration, freshness, and linguistic engines
                    evaluate a fixed synthetic input twice and produce
                    byte-identical output (determinism is a contract,
                    not a hope)
  * cascade       — the narrative cascade runs against the real DB and
                    degrades to honest zeros rather than crashing
  * discipline    — clock injection on every time-sensitive evaluator,
                    and the eager-``db_path=DB_PATH``-default ratchet
                    (two bug classes that have each caused real defects
                    in this repository)
  * scope guards  — private-scope and core-module-boundary reports are
                    clean

Contract
--------
* READ-ONLY.  The probe never writes: the database is opened in SQLite
  read-only URI mode and is never created if absent (absence is an
  honest WARN, not a side effect).
* NEVER RAISES.  Every check is exception-walled; an unexpected error
  becomes a FAIL result with the exception name, and the probe carries
  on.  ``run_system_integrity_probe`` always returns a full payload.
* DETERMINISTIC.  Given a pinned ``now`` and unchanged repo/DB state,
  two runs produce identical results (latency fields excluded).
* ADVISORY-ONLY.  The probe evaluates software health.  It never
  touches a broker, never places orders, and stamps every payload.

Statuses: PASS / WARN / FAIL per check; overall PASS (all pass),
DEGRADED (warns, no fails), FAIL (any fail).

CLI:  python scripts/system_integrity_probe.py [--json]
      exit 0 on PASS/DEGRADED, exit 1 on FAIL.
API:  GET /api/system/integrity  (token-gated read).
"""
from __future__ import annotations

import datetime as _dt
import inspect
import io
import json
import re
import sqlite3
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Callable

PROBE_VERSION = "integrity_probe_v1"

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

_REPO_ROOT = Path(__file__).resolve().parents[1]

_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "human_review_required": True,
    "ai_execution_count": 0,
    "broker_api_called": False,
    "broker_order_id": "NONE",
}

# ---------------------------------------------------------------------------
# Discipline registries — the two bug classes this repo has actually shipped
# ---------------------------------------------------------------------------

# Ratchet baseline for eager ``db_path: Path = DB_PATH`` defaults.  Eager
# defaults bind DB_PATH at import time, silently ignoring test/runtime
# path injection — a bug class that has repeatedly bitten this repo.  The
# convention for ALL new code is ``db_path: Path | None = None`` with lazy
# resolution inside the function body.  Legacy counts below are frozen:
# they may shrink, never grow, and no new file may introduce the pattern.
EAGER_DB_PATH_PATTERN = re.compile(r"db_path:\s*Path\s*=\s*DB_PATH")
EAGER_DB_PATH_BASELINE: dict[str, int] = {
    "cleanup_polymarket_db.py": 1,
    "persistence.py": 46,
    "persistence_global_securities.py": 11,
}

# Every time-sensitive evaluator on the runtime path must accept an
# injectable clock.  A wall-clock leak inside a pure evaluator made nine
# CI tests fail purely by calendar passage (chart-structure, 2026-06);
# this registry keeps that class of defect extinct.
# Entries: (module_name, callable_name, required_parameter)
CLOCK_INJECTED_EVALUATORS: tuple[tuple[str, str, str], ...] = (
    ("scripts.market_titration_engine", "evaluate_market_titration", "now"),
    ("scripts.market_data_freshness", "evaluate", "now"),
    ("scripts.chart_structure_price_truth", "compute_price_truth", "now"),
    ("scripts.chart_structure_api_context", "_get_chart_structure", "now"),
    ("scripts.narrative_cascade_engine", "build_cascade_report", "now"),
    ("scripts.narrative_state_engine", "build_narrative_state", "now"),
    # NOTE: titration_outcome_contract.compute_forward_responses is
    # deliberately absent — it is bar-indexed (event_ts + bars), fully
    # deterministic by construction, and touches no clock at all.
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _check(check_id: str, fn: Callable[[], tuple[str, str, dict[str, Any]]]) -> dict[str, Any]:
    """Run one check exception-walled; return a structured result."""
    started = time.perf_counter()
    try:
        status, reason, detail = fn()
    except Exception as exc:  # noqa: BLE001 — the wall is the contract
        status = FAIL
        reason = f"unexpected {type(exc).__name__}: {exc}"
        detail = {}
    latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
    return {
        "check_id": check_id,
        "status": status,
        "reason": reason,
        "detail": detail,
        "latency_ms": latency_ms,
    }


def _open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the DB strictly read-only; raises if the file is absent."""
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _resolve_db_path(db_path: Path | None) -> Path:
    if db_path is not None:
        return Path(db_path)
    try:
        from scripts import persistence
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        import persistence  # type: ignore[no-redef]
    return Path(persistence.DB_PATH)


def _expected_tables() -> list[str]:
    """Parse the canonical schema DDL for expected table names."""
    try:
        from scripts import persistence
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        import persistence  # type: ignore[no-redef]
    return sorted(set(
        re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", persistence._SCHEMA_SQL)
    ))


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _check_schema_tables(db_path: Path) -> tuple[str, str, dict[str, Any]]:
    expected = _expected_tables()
    if not db_path.exists():
        return WARN, "database file not present (created on first write); schema unverifiable", {
            "expected_table_count": len(expected),
        }
    conn = _open_readonly(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    finally:
        conn.close()
    present = {r[0] for r in rows}
    missing = sorted(t for t in expected if t not in present)
    if missing:
        return FAIL, f"{len(missing)} expected table(s) missing", {"missing_tables": missing}
    return PASS, f"all {len(expected)} expected tables present", {
        "expected_table_count": len(expected),
    }


# Sentinel columns proving the additive-migration chain ran end-to-end
# (earliest, middle, and latest migration eras).
_MIGRATION_SENTINELS: tuple[str, ...] = (
    "leverage",
    "reactor_state_at_decision",
    "titration_state_at_decision",
    "trade_mode",
)


def _check_additive_migrations(db_path: Path) -> tuple[str, str, dict[str, Any]]:
    if not db_path.exists():
        return WARN, "database file not present; migrations unverifiable", {}
    conn = _open_readonly(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(manual_trades)")}
    finally:
        conn.close()
    if not cols:
        return WARN, "manual_trades table absent; migrations unverifiable", {}
    missing = sorted(c for c in _MIGRATION_SENTINELS if c not in cols)
    if missing:
        return FAIL, "additive migration sentinel column(s) missing", {
            "missing_columns": missing,
        }
    return PASS, f"all {len(_MIGRATION_SENTINELS)} sentinel migration columns present", {
        "sentinel_columns": list(_MIGRATION_SENTINELS),
    }


def _check_config_titration() -> tuple[str, str, dict[str, Any]]:
    from scripts.market_titration_engine import load_titration_config
    cfg = load_titration_config()
    if not isinstance(cfg, dict) or "half_life_hours_by_family" not in cfg:
        return FAIL, "titration config missing half_life_hours_by_family", {}
    families = cfg.get("half_life_hours_by_family") or {}
    bad = {k: v for k, v in families.items()
           if not isinstance(v, (int, float)) or v <= 0}
    if bad:
        return FAIL, "non-positive half-life value(s) in titration config", {"bad": bad}
    return PASS, f"titration config valid ({len(families)} half-life families)", {
        "family_count": len(families),
    }


def _check_config_outcome_contract() -> tuple[str, str, dict[str, Any]]:
    from scripts.titration_outcome_contract import load_outcome_config
    cfg = load_outcome_config()
    problems = cfg.get("config_problems") or []
    if problems or cfg.get("config_status") not in (None, "OK", "VALID"):
        if problems:
            return FAIL, "outcome config reports problems", {"problems": problems}
    horizons = cfg.get("horizons_trading_days") or []
    version = cfg.get("config_version")
    if not horizons or not all(isinstance(h, int) and h > 0 for h in horizons):
        return FAIL, "outcome config horizons invalid", {"horizons": horizons}
    if not version:
        return FAIL, "outcome config missing version", {}
    return PASS, f"outcome contract config valid (version {version})", {
        "version": version,
        "horizons_trading_days": list(horizons),
    }


def _check_config_causal_graph() -> tuple[str, str, dict[str, Any]]:
    from scripts.causal_event_graph import load_causal_graph
    graph = load_causal_graph()  # raises on structural invalidity
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    exposures = graph.get("exposures") or []
    if not nodes or not edges:
        return FAIL, "causal graph loaded but empty", {}
    return PASS, "causal graph loads and validates", {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "exposure_count": len(exposures),
    }


_SYNTHETIC_TITRATION_ITEM: dict[str, Any] = {
    "event_id": "PROBE_SYNTHETIC",
    "ticker": "PROBE",
    "event_timestamps": [
        "2026-05-01T00:00:00Z",
        "2026-05-02T12:00:00Z",
        "2026-05-03T06:00:00Z",
    ],
    "event_sources": ["news", "filings", "news"],
    "event_count": 3,
    "cross_source_support_count": 2,
    "duplicate_suppressed_count": 0,
    "persistence_score": 0.6,
    "contamination_score": 0.1,
    "chaos_sensitivity_score": 0.25,
    "observed_at": "2026-05-01T00:00:00Z",
}

_PROBE_FIXED_NOW = _dt.datetime(2026, 5, 4, 0, 0, 0, tzinfo=_dt.timezone.utc)


def _check_engine_titration_determinism() -> tuple[str, str, dict[str, Any]]:
    from scripts.market_titration_engine import evaluate_market_titration
    first = evaluate_market_titration(dict(_SYNTHETIC_TITRATION_ITEM), now=_PROBE_FIXED_NOW)
    second = evaluate_market_titration(dict(_SYNTHETIC_TITRATION_ITEM), now=_PROBE_FIXED_NOW)
    a = json.dumps(first, sort_keys=True, default=str)
    b = json.dumps(second, sort_keys=True, default=str)
    if a != b:
        return FAIL, "titration engine output differs across identical runs", {}
    state = first.get("titration_state")
    if not state:
        return FAIL, "titration engine returned no state", {}
    return PASS, f"titration engine deterministic (synthetic state {state})", {
        "state": state,
        "scoring_version": first.get("scoring_version"),
    }


def _check_engine_freshness_determinism() -> tuple[str, str, dict[str, Any]]:
    from scripts import market_data_freshness as m
    candles = [{"timestamp": "2026-05-03T16:00:00Z"}]
    first = m.evaluate(candles=candles, source_kind=m.CANONICAL_SQLITE, now=_PROBE_FIXED_NOW)
    second = m.evaluate(candles=candles, source_kind=m.CANONICAL_SQLITE, now=_PROBE_FIXED_NOW)
    if first != second:
        return FAIL, "freshness evaluation differs across identical runs", {}
    if first.get("data_freshness_status") != m.FRESH:
        return FAIL, "freshness engine misclassified a 0.3-day-old candle", {
            "got": first.get("data_freshness_status"),
        }
    return PASS, "freshness gate deterministic and correctly classifies", {
        "status": first.get("data_freshness_status"),
    }


def _check_engine_linguistic_determinism() -> tuple[str, str, dict[str, Any]]:
    from scripts.linguistic_state_engine import extract_linguistic_features
    text = "Regulator will certainly escalate export restrictions immediately."
    first = extract_linguistic_features(text)
    second = extract_linguistic_features(text)
    a = json.dumps(first, sort_keys=True, default=str)
    b = json.dumps(second, sort_keys=True, default=str)
    if a != b:
        return FAIL, "linguistic feature extraction differs across identical runs", {}
    framing = first.get("framing") or {}
    if framing.get("validation_status") != "UNVALIDATED":
        return FAIL, "framing features missing UNVALIDATED honesty stamp", {}
    return PASS, "linguistic engine deterministic; honesty labels intact", {
        "feature_type": framing.get("feature_type"),
    }


def _check_cascade_honest_degradation(db_path: Path, now: _dt.datetime) -> tuple[str, str, dict[str, Any]]:
    if not db_path.exists():
        return WARN, "database file not present; cascade smoke skipped (probe never creates the DB)", {}
    from scripts.narrative_cascade_engine import build_cascade_report
    report = build_cascade_report(db_path=db_path, now=now)
    if not isinstance(report, dict):
        return FAIL, "cascade report is not a dict", {}
    if report.get("advisory_status") != "ADVISORY_ONLY":
        return FAIL, "cascade report missing advisory stamp", {}
    summary = report.get("observation_summary") or {}
    obs = summary.get("observation_count") if isinstance(summary, dict) else None
    narratives = report.get("narrative_count")
    candidates = report.get("candidate_count")
    if not isinstance(narratives, int) or not isinstance(candidates, int):
        return FAIL, "cascade report counts malformed", {
            "narrative_count": narratives, "candidate_count": candidates,
        }
    return PASS, (
        f"cascade runs against real DB and degrades honestly "
        f"({narratives} narratives, {candidates} candidates)"
    ), {
        "observations": obs,
        "narrative_count": narratives,
        "candidate_count": candidates,
    }


def _check_clock_injection_discipline() -> tuple[str, str, dict[str, Any]]:
    import importlib
    violations: list[str] = []
    verified: list[str] = []
    for module_name, callable_name, param in CLOCK_INJECTED_EVALUATORS:
        try:
            module = importlib.import_module(module_name)
            fn = getattr(module, callable_name)
            sig = inspect.signature(fn)
        except Exception as exc:  # noqa: BLE001
            violations.append(f"{module_name}.{callable_name}: {type(exc).__name__}")
            continue
        if param not in sig.parameters:
            violations.append(
                f"{module_name}.{callable_name} lacks injectable clock parameter '{param}'"
            )
        else:
            verified.append(f"{module_name}.{callable_name}")
    if violations:
        return FAIL, "wall-clock leak: evaluator(s) without injectable clock", {
            "violations": violations,
        }
    return PASS, f"all {len(verified)} time-sensitive evaluators accept an injected clock", {
        "verified": verified,
    }


def scan_eager_db_path_defaults(scripts_dir: Path | None = None) -> dict[str, int]:
    """Per-file counts of eager DB_PATH-bound ``db_path`` defaults.

    Comment lines are excluded so documentation *about* the anti-pattern
    (like this module's) never counts as an occurrence of it.
    """
    root = scripts_dir if scripts_dir is not None else _REPO_ROOT / "scripts"
    counts: dict[str, int] = {}
    for path in sorted(root.glob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        n = sum(
            len(EAGER_DB_PATH_PATTERN.findall(line))
            for line in text.splitlines()
            if not line.lstrip().startswith("#")
        )
        if n:
            counts[path.name] = n
    return counts


def _check_db_path_discipline() -> tuple[str, str, dict[str, Any]]:
    counts = scan_eager_db_path_defaults()
    violations: list[str] = []
    for fname, n in sorted(counts.items()):
        allowed = EAGER_DB_PATH_BASELINE.get(fname, 0)
        if n > allowed:
            violations.append(
                f"{fname}: {n} eager db_path defaults (baseline {allowed}) — "
                "new code must use 'db_path: Path | None = None' with lazy resolution"
            )
    if violations:
        return FAIL, "eager DB_PATH default ratchet violated", {"violations": violations}
    total = sum(counts.values())
    baseline_total = sum(EAGER_DB_PATH_BASELINE.values())
    return PASS, (
        f"eager DB_PATH defaults at/below frozen baseline "
        f"({total}/{baseline_total} legacy occurrences)"
    ), {"per_file": counts}


def _check_scope_guards() -> tuple[str, str, dict[str, Any]]:
    from scripts import core_module_boundary, private_scope_guard
    with redirect_stdout(io.StringIO()):
        scope_report = private_scope_guard.build_report()
        unknown = core_module_boundary.new_unknown_modules()
        import_violations = core_module_boundary.core_import_violations()
    problems: list[str] = []
    if scope_report.get("review_required_count", 0) > 0:
        problems.append(
            f"{scope_report['review_required_count']} module(s) REVIEW_REQUIRED in private scope guard"
        )
    if scope_report.get("quarantine_leaks"):
        problems.append(f"quarantine leaks: {scope_report['quarantine_leaks']}")
    if unknown:
        problems.append(f"unclassified modules: {unknown}")
    if import_violations:
        problems.append(f"core import violations: {import_violations}")
    if problems:
        return FAIL, "; ".join(problems), {}
    return PASS, "scope and boundary guards clean", {
        "in_scope_count": scope_report.get("in_scope_count"),
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_system_integrity_probe(
    *,
    now: _dt.datetime | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Run the full sweep.  Read-only, exception-walled, deterministic
    given (now, repo state, DB state).  Always returns a full payload."""
    started = time.perf_counter()
    now_dt = now or _dt.datetime.now(_dt.timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=_dt.timezone.utc)
    db = _resolve_db_path(db_path)

    checks = [
        _check("schema_tables", lambda: _check_schema_tables(db)),
        _check("additive_migrations", lambda: _check_additive_migrations(db)),
        _check("config_titration", _check_config_titration),
        _check("config_outcome_contract", _check_config_outcome_contract),
        _check("config_causal_graph", _check_config_causal_graph),
        _check("engine_titration_determinism", _check_engine_titration_determinism),
        _check("engine_freshness_determinism", _check_engine_freshness_determinism),
        _check("engine_linguistic_determinism", _check_engine_linguistic_determinism),
        _check("cascade_honest_degradation",
               lambda: _check_cascade_honest_degradation(db, now_dt)),
        _check("clock_injection_discipline", _check_clock_injection_discipline),
        _check("db_path_discipline", _check_db_path_discipline),
        _check("scope_guards", _check_scope_guards),
    ]

    n_fail = sum(1 for c in checks if c["status"] == FAIL)
    n_warn = sum(1 for c in checks if c["status"] == WARN)
    n_pass = sum(1 for c in checks if c["status"] == PASS)
    overall = FAIL if n_fail else (("DEGRADED" if n_warn else PASS))

    return {
        **_SAFETY_STAMPS,
        "probe_version": PROBE_VERSION,
        "generated_at": now_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "overall_status": overall,
        "counts": {"pass": n_pass, "warn": n_warn, "fail": n_fail, "total": len(checks)},
        "checks": checks,
        "db_file_present": db.exists(),
        "total_latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "non_claims": [
            "This probe evaluates software integrity only.",
            "It makes no claim about market data quality or predictive performance.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="System integrity probe (read-only)")
    parser.add_argument("--json", action="store_true", help="emit full JSON payload")
    args = parser.parse_args(argv)
    result = run_system_integrity_probe()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        print(f"System Integrity Probe {PROBE_VERSION}")
        print("=" * 34)
        for c in result["checks"]:
            print(f"  [{c['status']:4}] {c['check_id']:32} {c['reason']}")
        counts = result["counts"]
        print(
            f"\noverall: {result['overall_status']} "
            f"({counts['pass']} pass / {counts['warn']} warn / {counts['fail']} fail) "
            f"in {result['total_latency_ms']} ms"
        )
    return 1 if result["overall_status"] == FAIL else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "PROBE_VERSION",
    "PASS", "WARN", "FAIL",
    "EAGER_DB_PATH_BASELINE",
    "EAGER_DB_PATH_PATTERN",
    "CLOCK_INJECTED_EVALUATORS",
    "scan_eager_db_path_defaults",
    "run_system_integrity_probe",
    "main",
]
