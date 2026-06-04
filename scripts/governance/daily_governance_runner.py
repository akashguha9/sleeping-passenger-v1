"""CLI runner for the Daily Governance / Discovery Gate.

Loads a governance-inputs JSON (the five-model synthesis snapshot, e.g. the
deterministic regression fixture), evaluates the fail-closed gate, and writes
the six machine-readable artifacts.

This is the integration entry point: the governance result it produces is the
single source of truth for whether a Manual Add Consideration is allowed,
whether it is a no-new-risk day, which tickers are quarantined, and which
existing holdings require review. It NEVER executes, places orders, or sizes
positions; the execution gate is always reported LOCKED.

CLI:
    python scripts/governance/daily_governance_runner.py INPUTS.json [--out DIR] [--print]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# When invoked directly as a nested script (python scripts/governance/...),
# sys.path[0] is this file's dir; make the repo root importable so the
# canonical ``scripts.governance.*`` imports resolve.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.governance.artifacts import write_governance_artifacts
    from scripts.governance.daily_gate import evaluate_daily_governance
    from scripts.governance.models import DailyGovernanceResult
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from governance.artifacts import write_governance_artifacts  # type: ignore[no-redef]
    from governance.daily_gate import evaluate_daily_governance  # type: ignore[no-redef]
    from governance.models import DailyGovernanceResult  # type: ignore[no-redef]

_INPUT_KEYS = (
    "verified_current_holdings",
    "closed_positions",
    "sold_positions",
    "not_owned_do_not_manage",
    "current_prices",
    "today_market_snapshot",
    "today_price_movers",
    "today_news_events",
    "today_filings_events",
    "previous_candidates",
    "model_candidate_votes",
    "model_existing_holding_reviews",
    "trade_log",
)


def run_from_inputs(inputs: dict[str, Any]) -> DailyGovernanceResult:
    """Evaluate the governance gate from a loaded inputs dict."""
    kwargs = {k: inputs[k] for k in _INPUT_KEYS if k in inputs}
    return evaluate_daily_governance(
        run_date=inputs["run_date"], config=inputs.get("config"), **kwargs
    )


def run_from_file(path: str | Path) -> DailyGovernanceResult:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return run_from_inputs(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily Governance / Discovery Gate runner (advisory-only).")
    parser.add_argument("inputs", help="path to the governance-inputs JSON snapshot")
    parser.add_argument("--out", default="runtime", help="output directory for artifacts (default: runtime)")
    parser.add_argument("--print", action="store_true", dest="do_print", help="print the final decision board")
    parser.add_argument("--no-write", action="store_true", help="evaluate only; do not write artifacts")
    args = parser.parse_args(argv)

    data = json.loads(Path(args.inputs).read_text(encoding="utf-8"))
    result = run_from_inputs(data)
    run_id = (data.get("config") or {}).get("run_id")

    if not args.no_write:
        written = write_governance_artifacts(result, args.out, run_id=run_id)
        sys.stdout.write(f"wrote {len(written)} artifact files under {args.out}\n")

    if args.do_print or args.no_write:
        sys.stdout.write(json.dumps(result.final_daily_decision_board, indent=2) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
