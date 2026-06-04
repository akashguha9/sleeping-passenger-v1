"""Gap 5: repo-discipline guards.

Locks two things so future entropy is gated:
  1. safety-critical modules cannot be deleted silently, and
  2. the god-module split plan exists and still names the god modules.

These add no capability — they are tripwires.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
DOCS = REPO_ROOT / "docs"

# Modules enforcing the advisory-only / fail-closed posture. See
# docs/REPO_DISCIPLINE_CENSUS.md §3.
SAFETY_CRITICAL = (
    "pipeline_health_report",
    "narrative_operator_wisdom_filter",
    "busquets_pre_execution_audit",
    "board_control_safety_layer",
    "execution_governance",
    "paper_execution",
    "execution_integrity_audit",
    "tag_engine",
)

GOD_MODULES = ("pipeline_health_report.py", "api_server.py", "structural_admission_layer.py")


def test_safety_critical_modules_exist() -> None:
    for stem in SAFETY_CRITICAL:
        assert (SCRIPTS / f"{stem}.py").exists(), f"safety-critical module missing: {stem}"


def test_god_module_split_plan_exists_and_names_them() -> None:
    plan = DOCS / "REPO_DISCIPLINE_CENSUS.md"
    assert plan.exists(), "god-module split plan doc missing"
    text = plan.read_text(encoding="utf-8")
    for module in GOD_MODULES:
        assert module in text, f"split plan no longer names {module}"


def test_census_doc_present() -> None:
    assert (DOCS / "module_census.md").exists()
