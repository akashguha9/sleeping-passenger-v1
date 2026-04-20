from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    from scripts.market_data_adapter import describe_market_data_adapter
    from scripts.signal_conversion_monitor import build_signal_conversion_report
except ModuleNotFoundError:
    from market_data_adapter import describe_market_data_adapter
    from signal_conversion_monitor import build_signal_conversion_report


REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_TEST_COMMAND = [
    sys.executable,
    "-m",
    "pytest",
    "tests\\test_moltbook_schema.py",
    "tests\\test_moltbook_loader.py",
    "-q",
]

SCORECARD_RULES = {
    "logging_quality": [
        "+2 if Moltbook counts are present",
        "+3 if qualifying_signals are present",
        "+3 if per_signal_attribution covers every above-threshold signal",
        "+2 if execution_policy includes rationale",
    ],
    "schema_reliability": [
        "+3 if Moltbook closes and MW seed both load",
        "+3 if SCM status counts use only supported ledger statuses",
        "+2 if signal count total is >= above-threshold count",
        "+2 if targeted tests were run and passed",
    ],
    "end_to_end_wiring": [
        "+3 if trade closes are loaded",
        "+3 if above-threshold signals are loaded",
        "+2 if gate states and SCM review are present",
        "+2 if execution_policy is present",
    ],
    "self_correction_maturity": [
        "+3 if SCM diagnosis is present",
        "+3 if per-signal attribution is present",
        "+2 if execution_policy includes minimum_conditions_to_improve",
        "+2 if execution_policy includes next_priority_action",
    ],
    "execution_readiness": [
        "+2 if execution_policy exists",
        "+2 if next_priority_action is explicit",
        "+2 if minimum_conditions_to_improve is explicit",
        "+2 if new risk is currently allowed",
        "+2 if chaos entries are not forbidden",
    ],
}


def _last_non_empty_line(*blocks: str) -> str | None:
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return None


def _bounded_score(value: int) -> int:
    return max(0, min(value, 10))


def get_git_status(repo_root: Path | None = None) -> dict:
    base = repo_root or REPO_ROOT

    try:
        head = subprocess.run(
            ["git", "--no-pager", "rev-parse", "--short", "HEAD"],
            cwd=base,
            capture_output=True,
            text=True,
            check=False,
        )
        status = subprocess.run(
            ["git", "--no-pager", "status", "--short"],
            cwd=base,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return {
            "available": False,
            "head": None,
            "is_clean": None,
            "changed_paths": [],
            "error": "git executable not available",
        }

    if head.returncode != 0 or status.returncode != 0:
        return {
            "available": False,
            "head": None,
            "is_clean": None,
            "changed_paths": [],
            "error": _last_non_empty_line(head.stderr, status.stderr),
        }

    changed_paths = []
    for line in status.stdout.splitlines():
        entry = line.strip()
        if not entry:
            continue
        parts = entry.split(maxsplit=1)
        changed_paths.append(parts[1] if len(parts) > 1 else parts[0])

    return {
        "available": True,
        "head": head.stdout.strip(),
        "is_clean": len(changed_paths) == 0,
        "changed_paths": changed_paths,
        "error": None,
    }


def run_targeted_tests(repo_root: Path | None = None) -> dict:
    base = repo_root or REPO_ROOT
    result = subprocess.run(
        TARGET_TEST_COMMAND,
        cwd=base,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "invoked": True,
        "command": TARGET_TEST_COMMAND,
        "exit_code": result.returncode,
        "passed": result.returncode == 0,
        "summary_line": _last_non_empty_line(result.stdout, result.stderr),
    }


def build_health_scorecard(scm_report: dict, test_status: dict) -> dict:
    signal_summary = scm_report["signal_summary"]
    execution_policy = scm_report["execution_policy"]
    per_signal_attribution = scm_report["per_signal_attribution"]

    logging_quality = 0
    if scm_report["moltbook_summary"]["trade_close_count"] >= 0:
        logging_quality += 2
    if signal_summary["qualifying_signals"]:
        logging_quality += 3
    if len(per_signal_attribution) == signal_summary["signals_above_ce_threshold"]:
        logging_quality += 3
    if execution_policy["rationale"]:
        logging_quality += 2

    schema_reliability = 0
    if (
        scm_report["moltbook_summary"]["trade_close_count"] > 0
        and scm_report["moltbook_summary"]["mw_signal_count"] > 0
    ):
        schema_reliability += 3
    if set(signal_summary["status_counts_above_threshold"]).issubset(
        {"EXECUTED_CLEAN", "EXECUTED_CHAOS", "WATCHLIST", "REJECTED"}
    ):
        schema_reliability += 3
    if signal_summary["signal_count_total"] >= signal_summary["signals_above_ce_threshold"]:
        schema_reliability += 2
    if test_status.get("invoked") and test_status.get("passed"):
        schema_reliability += 2

    end_to_end_wiring = 0
    if scm_report["moltbook_summary"]["trade_close_count"] > 0:
        end_to_end_wiring += 3
    if signal_summary["signals_above_ce_threshold"] > 0:
        end_to_end_wiring += 3
    if scm_report["scm_review"] and scm_report["derived_gate_states"]:
        end_to_end_wiring += 2
    if execution_policy:
        end_to_end_wiring += 2

    self_correction_maturity = 0
    if scm_report["scm_review"]["diagnosis"]:
        self_correction_maturity += 3
    if per_signal_attribution:
        self_correction_maturity += 3
    if execution_policy["minimum_conditions_to_improve"]:
        self_correction_maturity += 2
    if execution_policy["next_priority_action"]:
        self_correction_maturity += 2

    execution_readiness = 0
    if execution_policy:
        execution_readiness += 2
    if execution_policy["next_priority_action"]:
        execution_readiness += 2
    if execution_policy["minimum_conditions_to_improve"]:
        execution_readiness += 2
    if execution_policy["allow_new_risk"]:
        execution_readiness += 2
    if not execution_policy["chaos_entries_forbidden"]:
        execution_readiness += 2

    return {
        "logging_quality": {"score": _bounded_score(logging_quality), "max_score": 10},
        "schema_reliability": {"score": _bounded_score(schema_reliability), "max_score": 10},
        "end_to_end_wiring": {"score": _bounded_score(end_to_end_wiring), "max_score": 10},
        "self_correction_maturity": {
            "score": _bounded_score(self_correction_maturity),
            "max_score": 10,
        },
        "execution_readiness": {"score": _bounded_score(execution_readiness), "max_score": 10},
    }


def build_pipeline_health_report(
    include_tests: bool = False,
    repo_root: Path | None = None,
    market_data_provider: str | None = None,
) -> dict:
    base = repo_root or REPO_ROOT
    scm_report = build_signal_conversion_report()
    test_status = (
        run_targeted_tests(base)
        if include_tests
        else {
            "invoked": False,
            "command": TARGET_TEST_COMMAND,
            "exit_code": None,
            "passed": None,
            "summary_line": None,
        }
    )

    return {
        "git_status": get_git_status(base),
        "test_status": test_status,
        "moltbook_summary": scm_report["moltbook_summary"],
        "signal_summary": scm_report["signal_summary"],
        "scm_review": scm_report["scm_review"],
        "derived_gate_states": scm_report["derived_gate_states"],
        "execution_policy": scm_report["execution_policy"],
        "market_data_adapter": describe_market_data_adapter(market_data_provider),
        "scorecard": build_health_scorecard(scm_report, test_status),
        "scorecard_rules": SCORECARD_RULES,
        "note": "Health report is deterministic and built from live SCM output plus explicit local rule-based scoring.",
    }


def format_pipeline_health_summary(report: dict) -> str:
    git_status = report["git_status"]
    tests = report["test_status"]
    scores = report["scorecard"]
    return "\n".join(
        [
            "Pipeline Health Report",
            f"git_clean={git_status['is_clean']}",
            f"tests_invoked={tests['invoked']}",
            f"tests_passed={tests['passed']}",
            f"scm_state={report['scm_review']['scm_state']}",
            f"scm_rate={report['scm_review']['scm_rate']}",
            f"policy_state={report['execution_policy']['policy_state']}",
            f"allow_new_risk={str(report['execution_policy']['allow_new_risk']).lower()}",
            f"next_priority_action={report['execution_policy']['next_priority_action']}",
            (
                "scorecard="
                f"logging_quality={scores['logging_quality']['score']}/10, "
                f"schema_reliability={scores['schema_reliability']['score']}/10, "
                f"end_to_end_wiring={scores['end_to_end_wiring']['score']}/10, "
                f"self_correction_maturity={scores['self_correction_maturity']['score']}/10, "
                f"execution_readiness={scores['execution_readiness']['score']}/10"
            ),
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a deterministic pipeline health report.")
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Run the targeted pytest slice and include the result in the report.",
    )
    parser.add_argument(
        "--market-data-provider",
        default="yahoo",
        help="Describe the requested market-data adapter provider.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    report = build_pipeline_health_report(
        include_tests=args.include_tests,
        market_data_provider=args.market_data_provider,
    )
    if args.summary:
        print(format_pipeline_health_summary(report))
    else:
        print(json.dumps(report, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
