#!/usr/bin/env python3
"""Import resolved outcomes into the calibration view — honestly tiered.

The calibration ledger had scaffolding but no entry path: the importer
(``src.strategy.outcome_import``) was reachable only from its own tests
— exactly the "tested but unwired" class the live-surface census exists
to catch. This CLI is the wire.

Reads JSONL rows (one resolved case per line; see
``examples/outcomes/calibration_seed.jsonl`` for the contract), groups
them by truth-status tier, and reports per-tier calibration summaries:

    synthetic_fixture  — handcrafted demo rows; prove the plumbing only
    backtest_replay    — real prices, counterfactual decisions
    empirical          — real resolved decisions (the only tier that
                         can ever justify confidence)

Rows never get a better tier than declared; rows with no tier (or an
unknown one) collapse DOWNWARD to synthetic_fixture. Tiers are never
mixed in one summary — synthetic rows cannot launder a backtest batch.

Usage:
    python scripts/import_outcomes.py examples/outcomes/calibration_seed.jsonl
    python scripts/import_outcomes.py rows.jsonl --json
    python scripts/import_outcomes.py rows.jsonl --streak

ADVISORY_ONLY: this reads research records and prints analysis. It
never places, sizes, or routes anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.strategy.outcome_import import (  # noqa: E402
    DATA_TIERS,
    audit_streak,
    load_resolved_outcomes,
    streak_inputs_from_outcomes,
)


def read_rows(path: Path) -> list[dict]:
    """Parse JSONL; malformed lines are reported, never fatal."""
    rows: list[dict] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        try:
            rows.append(json.loads(text))
        except json.JSONDecodeError as exc:
            rows.append({"_parse_error": f"line {line_number}: {exc}"})
    return rows


def import_grouped(rows: list[dict]) -> dict:
    """Group rows by declared tier and import each group separately."""
    groups: dict[str, list[dict]] = {}
    parse_errors: list[str] = []
    for row in rows:
        if "_parse_error" in row:
            parse_errors.append(str(row["_parse_error"]))
            continue
        tier = str(row.get("data_tier", "synthetic_fixture"))
        if tier not in DATA_TIERS:
            tier = "synthetic_fixture"  # unknown collapses downward
        groups.setdefault(tier, []).append(row)

    by_tier: dict[str, dict] = {}
    reports = {}
    for tier in DATA_TIERS:  # stable, worst-first order
        if tier in groups:
            report = load_resolved_outcomes(groups[tier], data_tier=tier)
            reports[tier] = report
            by_tier[tier] = report.to_dict()
    return {
        "rows_read": len(rows),
        "parse_errors": parse_errors,
        "tiers_present": [t for t in DATA_TIERS if t in groups],
        "by_tier": by_tier,
        "_reports": reports,  # objects for callers; stripped from JSON
        "advisory_status": "ADVISORY_ONLY",
        "note": (
            "tiers are summarized separately by design — synthetic rows "
            "can never launder a backtest or empirical batch"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import resolved outcome rows (JSONL) into the "
        "calibration view, grouped by truth-status tier.",
    )
    parser.add_argument("path", type=Path, help="JSONL file of outcomes")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output")
    parser.add_argument("--streak", action="store_true",
                        help="also run the streak audit per tier")
    args = parser.parse_args(argv)

    if not args.path.exists():
        print(f"error: {args.path} not found", file=sys.stderr)
        return 2

    result = import_grouped(read_rows(args.path))
    reports = result.pop("_reports")

    if args.streak:
        for tier, report in reports.items():
            audit = audit_streak(
                streak_inputs_from_outcomes(report.imported),
                data_tier=tier,
            )
            result["by_tier"][tier]["streak_audit"] = audit.to_dict()

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print("Calibration outcome import — ADVISORY_ONLY")
    print(f"  rows read     : {result['rows_read']}")
    if result["parse_errors"]:
        print(f"  parse errors  : {len(result['parse_errors'])}")
    for tier in result["tiers_present"]:
        summary = result["by_tier"][tier]["summary"]
        print(f"  [{tier}] {summary['count']} imported / "
              f"{summary['rejected']} rejected — status "
              f"{summary['status']}")
        for key in ("win_rate", "mean_realized_alpha",
                    "mean_prediction_error",
                    "mean_expiry_accuracy_days"):
            print(f"      {key}: {summary[key]}")
        if tier == "synthetic_fixture":
            print("      (synthetic seed: proves the plumbing, "
                  "never the model)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
