"""Test inventory report — proof_loop_hardening_sprint, Phase 11.

Heuristic classifier that scans test filenames and bucket them into the
sprint's marker taxonomy.  Filename heuristics are an honest stop-gap
until tests are migrated to explicit pytest markers; the report makes
the *unknown* bucket loud so a high unknown_pct can't hide.

Safety
~~~~~~
* Read-only.  No DB writes.  No network.
* No broker / order / execution path.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]


SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}


# Filename heuristics, in priority order.  First match wins.
# Patterns are case-insensitive regexes against the test filename
# (e.g. "test_advisory_contract.py").
HEURISTICS: tuple[tuple[str, str], ...] = (
    # Safety floor: advisory / no-execution / no-secrets / broker
    ("safety_floor", r"advisory|credential|hygiene|safety|no_execution|api_token_gate"),
    # Calibration corpus + math
    ("calibration", r"calibration|brier|ece|mce|log_loss|n_real|outcome_label"),
    # Moltbook learning loop
    ("moltbook", r"moltbook|reconcil|outcome.*learning"),
    # Reliability: freshness, watchdog, provider failures, persistence,
    # scheduler, retry, backup-restore.
    (
        "reliability",
        r"watchdog|refresh|freshness|persistence|scheduler|backup|restore|"
        r"provider|live_source|source_health|failure_mode|anti_staleness|"
        r"runtime_artifact",
    ),
    # Frontend truth surfaces.  Backend tests that scan FE files belong here.
    (
        "frontend_truth",
        r"frontend|truth|top_truth|component|page_layout|customer_frontend",
    ),
)


@dataclass
class TestFileClassification:
    path: str
    bucket: str
    matched_pattern: str | None


def classify_test_file(name: str) -> TestFileClassification:
    lower = name.lower()
    for bucket, pat in HEURISTICS:
        if re.search(pat, lower):
            return TestFileClassification(path=name, bucket=bucket, matched_pattern=pat)
    return TestFileClassification(path=name, bucket="cosmetic_or_unknown", matched_pattern=None)


def build_inventory(tests_dir: Path) -> dict[str, Any]:
    if not tests_dir.exists():
        return {
            "tests_dir": str(tests_dir),
            "total_tests_collected": 0,
            "safety_floor_count": 0,
            "reliability_count": 0,
            "calibration_count": 0,
            "moltbook_count": 0,
            "frontend_truth_count": 0,
            "cosmetic_or_unknown_count": 0,
            "unknown_pct": 0.0,
            "warning": f"tests directory missing: {tests_dir}",
            **SAFETY_STAMPS,
        }

    files: list[TestFileClassification] = []
    for f in sorted(tests_dir.glob("test_*.py")):
        files.append(classify_test_file(f.name))

    counts: dict[str, int] = {
        "safety_floor": 0,
        "reliability": 0,
        "calibration": 0,
        "moltbook": 0,
        "frontend_truth": 0,
        "cosmetic_or_unknown": 0,
    }
    for f in files:
        counts[f.bucket] += 1
    total = len(files)
    unknown_pct = (
        (100.0 * counts["cosmetic_or_unknown"] / total) if total else 0.0
    )

    return {
        "script": "test_inventory_report.py",
        "tests_dir": str(tests_dir),
        "total_tests_collected": int(total),
        "safety_floor_count": int(counts["safety_floor"]),
        "reliability_count": int(counts["reliability"]),
        "calibration_count": int(counts["calibration"]),
        "moltbook_count": int(counts["moltbook"]),
        "frontend_truth_count": int(counts["frontend_truth"]),
        "cosmetic_or_unknown_count": int(counts["cosmetic_or_unknown"]),
        "unknown_pct": round(float(unknown_pct), 4),
        "honest_note": (
            "Filename heuristics — not authoritative.  Tests should "
            "carry explicit pytest markers (safety_floor / reliability / "
            "calibration / moltbook / frontend_truth / cosmetic) per "
            "pytest.ini.  Until migration, the cosmetic_or_unknown bucket "
            "is intentionally loud."
        ),
        "files": [
            {"path": f.path, "bucket": f.bucket, "matched_pattern": f.matched_pattern}
            for f in files
        ],
        **SAFETY_STAMPS,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test inventory report by filename heuristic."
    )
    parser.add_argument(
        "--tests-dir",
        type=Path,
        default=_REPO_ROOT / "tests",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON here (skip to stdout-only).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_inventory(Path(args.tests_dir))
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(
            f"test inventory: total={report['total_tests_collected']} "
            f"safety={report['safety_floor_count']} "
            f"reliability={report['reliability_count']} "
            f"calibration={report['calibration_count']} "
            f"moltbook={report['moltbook_count']} "
            f"frontend={report['frontend_truth_count']} "
            f"unknown_pct={report['unknown_pct']}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
