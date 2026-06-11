"""Model-evaluation honesty audit — no fake alpha confidence.

Two jobs, both honest by construction:

1. OVERCLAIM SCAN — fail on marketing-grade claims in human-facing text
   (docs, README, reports, frontend source). Phrases like "guaranteed",
   "risk-free", "beats the market", "real-money ready" are forbidden
   unless the line clearly negates them, lists them as forbidden
   vocabulary, or lives in a test file's banlist. ("Risk-free rate", the
   standard finance term for the benchmark rate, is explicitly allowed.)

2. EVIDENCE SCORECARD — report what evaluation machinery actually exists
   in this repo, probed from the tree at runtime (a capability is only
   "capability_present" when both its module and its tests exist). It
   distinguishes *capability* from *validated live results*: this repo
   has backtest/calibration/leakage tooling, but NO live out-of-sample
   performance evidence — and the scorecard says so instead of implying
   otherwise. Nothing here is hand-scored; delete the module and the
   status flips to missing.

Output: violations → exit 1; the scorecard is written to
``runtime/reports/model_evaluation_honesty.json`` (gitignored).

Stdlib only:  python scripts/audit_model_evaluation_honesty.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = _REPO_ROOT / "runtime" / "reports" / "model_evaluation_honesty.json"

# Files whose job is to NAME the forbidden phrases (this audit, its tests,
# and the frontend language-ban guard specs hold banlists).
GUARD_FILES = frozenset({
    "scripts/audit_model_evaluation_honesty.py",
    "tests/test_model_evaluation_honesty.py",
    # Readiness-ladder enum labels ("Manual real-money ready" etc.): UI
    # vocabulary for states the readiness ENGINE grants only when its
    # gates pass — definitions, not claims. Reviewed allowlist entry.
    "frontend/src/lib/realMoneyReadiness.ts",
})

# Human-facing surfaces. Code identifiers are not marketing claims.
_SCANNED_SUFFIXES = frozenset({".md", ".tsx", ".ts", ".txt", ".html"})

_FORBIDDEN_PHRASES = (
    "guaranteed",
    "risk-free",
    "risk free",
    "real-money ready",
    "real money ready",
    "beats the market",
    "beat the market",
    "profitable strategy",
    "production trading ready",
    "autonomous trading",
    "execution ready",
    "execution-ready",
    "always buy",
    "will make money",
    "certain profit",
    "guaranteed edge",
)

# "risk-free rate" is the standard finance term for the benchmark rate in
# Sharpe-style metrics — a measurement input, not a promise.
_TERM_OF_ART_RE = re.compile(r"(?i)risk[\s-]?free\s+rate")

_NEGATORS = (
    " no ", " not ", "never", "nothing", "is not", "are not", "isn't",
    "aren't", "doesn't", "does not", "must not", "without", "forbidden",
    "banned", "ban ", "banlist", "refuse", "reject", "avoid", "claim",
    "overclaim", "wording", "language", "phrase", "disclaimer", "anywhere",
)


def _is_exempt(rel_path: str) -> bool:
    if rel_path in GUARD_FILES:
        return True
    name = Path(rel_path).name
    return (
        rel_path.startswith(("tests/", "archived_experimental/"))
        or ".spec." in name
        or ".test." in name
        or name.startswith("test_")
    )


def scan_text(text: str, rel_path: str) -> list[str]:
    """Return overclaim violations for one file's content."""
    if _is_exempt(rel_path):
        return []
    if Path(rel_path).suffix.lower() not in _SCANNED_SUFFIXES:
        return []
    violations: list[str] = []
    negated_section = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if stripped.startswith("#"):
            # Markdown headings set section context: bullets under
            # "What this MVP is NOT" are denials, not claims.
            heading = f" {stripped.lower()} "
            negated_section = any(neg in heading for neg in _NEGATORS)
        line = _TERM_OF_ART_RE.sub("benchmark rate", raw)
        lowered = f" {line.lower()} "
        hit = next((p for p in _FORBIDDEN_PHRASES if p in lowered), None)
        if hit is None:
            continue
        if negated_section and stripped.startswith(("-", "*", ">")):
            continue
        # Negated / quoted-as-forbidden / vocabulary-discussion lines are
        # the honest usage we WANT in docs.
        if any(neg in lowered for neg in _NEGATORS):
            continue
        if f'"{hit}"' in line.lower() or f"'{hit}'" in line.lower() or (
            f"`{hit}`" in line.lower()
        ):
            continue
        violations.append(
            f"{rel_path}:{lineno}: overclaim {hit!r} without negation — "
            "advisory software earns trust with evidence, not adjectives"
        )
    return violations


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=_REPO_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def scan_repo() -> list[str]:
    violations: list[str] = []
    for rel in _tracked_files():
        path = _REPO_ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        violations.extend(scan_text(text, rel))
    return violations


# --- evidence scorecard ------------------------------------------------------
# (item, module probe, test probe, optional content regex the module must
# actually contain). Status is computed, never asserted.
_EVIDENCE_PROBES = (
    ("backtest_availability", "scripts/backtest_advisory_signals.py",
     "tests/test_backtest_advisory_signals.py", None),
    ("walk_forward_validation", "scripts/backtest_advisory_signals.py",
     "tests/test_backtest_advisory_signals.py", r"walk[_-]?forward"),
    ("leakage_controls", "scripts/temporal_guard.py",
     "tests/test_temporal_guard.py", None),
    ("calibration_evidence", "scripts/model_calibration.py",
     "tests/test_model_calibration_pass4.py", None),
    ("uncertainty_intervals", "scripts/model_calibration.py",
     "tests/test_model_calibration_pass4.py", r"(?i)interval|wilson|ci_low"),
    ("drawdown_reporting", "scripts/backtest_advisory_signals.py",
     "tests/test_backtest_advisory_signals.py", r"(?i)drawdown"),
    ("false_positive_analysis", "scripts/redteam_model.py",
     "tests/test_redteam_and_readiness_gate.py", r"(?i)false[_\s-]?positive"),
    ("manual_review_requirement", "scripts/advisory_contract.py",
     "tests/test_advisory_contract.py", r"human_review_required"),
    ("advisory_only_disclaimer", "scripts/audit_advisory_only_boundary.py",
     "tests/test_advisory_only_boundary.py", None),
)


def build_evidence_scorecard() -> dict[str, dict[str, str]]:
    card: dict[str, dict[str, str]] = {}
    for item, module, test, content_re in _EVIDENCE_PROBES:
        mod_path = _REPO_ROOT / module
        test_path = _REPO_ROOT / test
        present = mod_path.exists() and test_path.exists()
        if present and content_re is not None:
            present = bool(
                re.search(content_re, mod_path.read_text(encoding="utf-8"))
            )
        card[item] = {
            "status": "capability_present" if present else "missing",
            "module": module,
            "tests": test,
        }
    # The honest line investors actually need:
    card["live_out_of_sample_results"] = {
        "status": "missing",
        "module": "n/a",
        "tests": "n/a",
        "note": (
            "No live, out-of-sample performance evidence exists. Tooling "
            "capability above is NOT validated alpha. Advisory-only."
        ),
    }
    return card


def main() -> int:
    violations = scan_repo()
    card = build_evidence_scorecard()

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "overclaim_violations": violations,
                "evidence_scorecard": card,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"model-evaluation honesty audit (report: {REPORT_PATH})")
    for item, entry in card.items():
        print(f"  {entry['status']:19s} {item}")
    if violations:
        print(f"FAIL — {len(violations)} overclaim(s):")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("PASS — no unqualified performance claims in human-facing text.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
