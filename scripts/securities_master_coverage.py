"""Securities-master coverage metrics + optional explicit seeding.

Measures how well the canonical securities master covers the active tracked
universe (configs/securities_seed_universe.yaml) so leverage governance can
resolve bare tickers from data rather than ticker-suffix heuristics.

Read-only by default. Seeding writes only when explicitly requested
(``seed_universe`` / ``--seed``), and tests point it at a temp DB. No live
fetch, no broker calls.

Coverage math
-------------
C = |R| / |U|                      (resolvable / required)
completeness_j = 0.20·symbol + 0.20·exchange + 0.20·country
               + 0.15·currency + 0.15·name + 0.10·asset_type
M = mean(completeness_j) over the required universe (missing -> 0)
J = |jurisdiction in {INDIA, REST_OF_WORLD}| / |U|
S = 0.50·C + 0.30·M + 0.20·J

Status: CRITICAL <0.50, PARTIAL <0.80, STRONG <0.95, COMPLETE_ENOUGH >=0.95
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_SEED_PATH = _REPO_ROOT / "configs" / "securities_seed_universe.yaml"

CRITICAL = "CRITICAL"
PARTIAL = "PARTIAL"
STRONG = "STRONG"
COMPLETE_ENOUGH = "COMPLETE_ENOUGH"

_ADVISORY_STAMPS = {
    "advisory_status": "ADVISORY_ONLY",
    "advisory_only": True,
    "human_execution_required": True,
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}


def load_seed_universe(path: Path | None = None) -> list[dict[str, Any]]:
    """Load + de-duplicate the seed universe (first occurrence per symbol)."""
    import yaml

    p = path or DEFAULT_SEED_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    rows = data.get("securities", []) or []
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        sym = str(r.get("symbol", "")).strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append({
            "symbol": sym,
            "exchange": str(r.get("exchange", "")).strip().upper(),
            "country": str(r.get("country", "")).strip().upper(),
            "currency": str(r.get("currency", "")).strip().upper(),
            "name": str(r.get("name", "")).strip(),
            "asset_type": str(r.get("asset_type", "EQUITY")).strip().upper(),
        })
    return out


def _completeness(row: dict[str, Any] | None) -> float:
    if not row:
        return 0.0
    m_symbol = 1.0 if (row.get("canonical_symbol") or row.get("symbol")) else 0.0
    m_exchange = 1.0 if (row.get("exchange_code") or row.get("exchange")) else 0.0
    m_country = 1.0 if row.get("country") else 0.0
    m_currency = 1.0 if row.get("currency") else 0.0
    m_name = 1.0 if row.get("name") else 0.0
    m_asset = 1.0 if (row.get("asset_type")) else 0.0
    return (0.20 * m_symbol + 0.20 * m_exchange + 0.20 * m_country
            + 0.15 * m_currency + 0.15 * m_name + 0.10 * m_asset)


def _jurisdiction_group(row: dict[str, Any] | None) -> str:
    try:
        from scripts.leverage_governance import resolve_leverage_ceiling
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        from leverage_governance import resolve_leverage_ceiling  # type: ignore[no-redef]
    if not row:
        return "UNKNOWN"
    res = resolve_leverage_ceiling(
        ticker=row.get("canonical_symbol") or row.get("symbol"),
        exchange=row.get("exchange_code") or row.get("exchange"),
        country=row.get("country"),
    )
    return res["jurisdiction_group"]


def compute_coverage(
    universe: list[dict[str, Any]],
    lookup: Callable[[str], dict[str, Any] | None] | None,
) -> dict[str, Any]:
    """Compute coverage metrics given a securities-master lookup callable."""
    total = len(universe)
    if total == 0:
        return {"report": "securities_master_coverage", "required": 0,
                "resolvable": 0, "coverage": 0.0, "mean_completeness": 0.0,
                "jurisdiction_resolvable": 0.0, "score": 0.0, "status": CRITICAL,
                "gaps": [], **_ADVISORY_STAMPS}

    resolvable = 0
    completeness_sum = 0.0
    jurisdiction_ok = 0
    gaps: list[str] = []
    for entry in universe:
        sym = entry["symbol"]
        row = None
        if lookup is not None:
            try:
                row = lookup(sym)
            except Exception:
                row = None
        if row:
            resolvable += 1
            completeness_sum += _completeness(row)
            if _jurisdiction_group(row) in {"INDIA", "REST_OF_WORLD"}:
                jurisdiction_ok += 1
        else:
            gaps.append(sym)

    C = resolvable / total
    M = completeness_sum / total
    J = jurisdiction_ok / total
    S = 0.50 * C + 0.30 * M + 0.20 * J

    if S < 0.50:
        status = CRITICAL
    elif S < 0.80:
        status = PARTIAL
    elif S < 0.95:
        status = STRONG
    else:
        status = COMPLETE_ENOUGH

    return {
        "report": "securities_master_coverage",
        "required": total,
        "resolvable": resolvable,
        "coverage": C,
        "mean_completeness": M,
        "jurisdiction_resolvable": J,
        "score": S,
        "status": status,
        "gaps": gaps,
        # Spec-named aliases (stable contract for the evidence pipeline).
        "required_universe_count": total,
        "resolved_count": resolvable,
        "coverage_C": C,
        "mean_completeness_M": M,
        "jurisdiction_resolvability_J": J,
        "securities_score_S": S,
        "coverage_status": status,
        "missing_symbols": gaps,
        **_ADVISORY_STAMPS,
    }


def seed_universe(
    universe: list[dict[str, Any]],
    db_path: Path,
) -> int:
    """EXPLICIT seed of missing canonical entries into the given DB.

    Only ever called behind an explicit flag (CLI ``--seed``) or in tests with
    a temp DB. Returns the number of securities upserted.
    """
    try:
        from scripts import persistence
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        import persistence  # type: ignore[no-redef]
    count = 0
    for e in universe:
        persistence.upsert_global_security(
            canonical_symbol=e["symbol"],
            name=e.get("name", ""),
            exchange_code=e.get("exchange", ""),
            country=e.get("country", ""),
            currency=e.get("currency") or None,
            asset_type=e.get("asset_type", "EQUITY"),
            db_path=db_path,
        )
        count += 1
    return count


def build_coverage_report(db_path: Path | None = None, seed_path: Path | None = None) -> dict[str, Any]:
    """Read-only coverage report against the current securities master."""
    try:
        from scripts import persistence
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        import persistence  # type: ignore[no-redef]
    universe = load_seed_universe(seed_path)
    path = db_path if db_path is not None else persistence.DB_PATH

    def _lookup(sym: str):
        try:
            return persistence.get_global_security(sym, db_path=path)
        except Exception:
            return None

    return compute_coverage(universe, _lookup)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Securities-master coverage report.")
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--seed-path", type=Path, default=None)
    p.add_argument("--seed", action="store_true",
                   help="EXPLICITLY seed missing canonical entries (writes DB).")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    import json

    args = _build_parser().parse_args(argv)
    universe = load_seed_universe(args.seed_path)
    if args.seed:
        try:
            from scripts import persistence
        except ModuleNotFoundError:  # pragma: no cover
            import persistence  # type: ignore[no-redef]
        path = args.db_path if args.db_path is not None else persistence.DB_PATH
        n = seed_universe(universe, path)
        print(f"seeded {n} securities into {path}")
    report = build_coverage_report(args.db_path, args.seed_path)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"coverage score : {report['score']:.3f} ({report['status']})")
        print(f"resolvable     : {report['resolvable']}/{report['required']}")
        print(f"gaps           : {len(report['gaps'])}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "CRITICAL", "PARTIAL", "STRONG", "COMPLETE_ENOUGH",
    "load_seed_universe", "compute_coverage", "seed_universe",
    "build_coverage_report",
]
