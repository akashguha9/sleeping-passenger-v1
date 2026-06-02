"""Model-version cohort performance (advisory-only).

The model changed materially between 2026-05-14 and 2026-06-02, so blended
all-time stats are misleading.  This module reports performance per model
version and, crucially, refuses to overclaim improvement on a small sample —
cohorts with N < 30 are labelled "promising but immature".

It REUSES the cohort math in :mod:`scripts.trade_log_metrics` (single source of
truth for win-rate / expectancy / profit-factor) rather than re-deriving it.

Version derivation prefers an explicit ``model_version`` column, else infers
from the entry date::

    2026-05-14 .. 2026-05-20  -> v2026_05_early
    2026-05-21 .. 2026-05-24  -> v2026_05_override
    2026-05-25 .. 2026-05-31  -> v2026_05_recalibration
    >= 2026-06-01             -> v2026_06_global_watchlist

Contract — pure module: no DB, no network, no broker calls, no AI execution.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.google_sheet_schema import TradeLogRow, load_trade_log_csv
    from scripts.trade_log_metrics import compute_model_versions, model_cohort
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from google_sheet_schema import TradeLogRow, load_trade_log_csv  # type: ignore[no-redef]
    from trade_log_metrics import compute_model_versions, model_cohort  # type: ignore[no-redef]


def build_model_version_report(rows: Sequence[TradeLogRow]) -> dict[str, Any]:
    """Per-version cohort stats + an honest cross-cohort improvement note."""
    cohorts = compute_model_versions(rows)

    # Cross-cohort comparison is only stated when each side has a usable sample.
    note = "Per-cohort stats below; do not blend across model versions."
    immature = [name for name, c in cohorts.items() if c["n"] < 30]
    if immature:
        note += (
            " Cohorts with N<30 are 'promising but immature' — improvement is "
            "not yet statistically established: " + ", ".join(sorted(immature)) + "."
        )

    report: dict[str, Any] = {
        "cohort_count": len(cohorts),
        "model_version_performance": cohorts,
        "interpretation_note": note,
    }
    report.update(advisory_safety_stamps())
    report["human_execution_required"] = True
    return report


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    parser = argparse.ArgumentParser(
        description="Per-model-version trade performance (advisory-only)."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--format", choices=("text", "json"), default="json")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    rows = load_trade_log_csv(args.input).rows
    report = build_model_version_report(rows)
    if args.format == "json":
        print(json.dumps(report, indent=2, default=str))
    else:
        for name, c in report["model_version_performance"].items():
            print(
                f"{name}: N={c['n']} PL={c['total_pl']} win_rate={c['win_rate']} "
                f"PF={c['profit_factor']} conf={c['confidence']} ({c['maturity_note']})"
            )
        print(report["interpretation_note"])
    return 0


__all__ = ["build_model_version_report", "model_cohort"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
