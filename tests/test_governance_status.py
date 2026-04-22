import json
import subprocess
import sys
from pathlib import Path

from scripts.governance_status import build_governance_status_report


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_governance_status_report_is_conservative() -> None:
    report = build_governance_status_report()

    assert report["operating_mode"] == "seeded"
    assert report["truth_origin"] == "seeded"
    assert report["controls"]["artifact_coherence"]["state"] == "legacy_polluted"
    assert "runtime/signal_vocoder_report.json" in report["controls"]["artifact_coherence"]["legacy_artifacts"]
    assert report["controls"]["provenance"]["state"] == "basic"
    assert report["controls"]["operator_integrity"]["state"] == "not_implemented"
    assert report["controls"]["disclosure_discipline"]["state"] == "partial"


def test_governance_status_summary_cli() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "governance_status.py"), "--summary"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    lines = result.stdout.strip().splitlines()
    assert lines[0] == "Governance Status"
    assert "operating_mode=seeded" in lines
    assert "truth_origin=seeded" in lines
    assert "artifact_coherence_state=legacy_polluted" in lines
    assert "operator_integrity_state=not_implemented" in lines
    assert "disclosure_discipline_state=partial" in lines


def test_governance_status_json_cli_shape() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "governance_status.py"), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["operating_mode"] == "seeded"
    assert payload["truth_origin"] == "seeded"
    assert payload["controls"]["operator_integrity"]["state"] == "not_implemented"
