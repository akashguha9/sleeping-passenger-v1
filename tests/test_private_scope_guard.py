"""Private-operator scope guard.

This is a *discipline* test, not a deletion test.  It verifies that:

* Approved core modules (signal/source/reactor/calibration/...) classify
  as in-scope.
* The GMAT scraper has been physically removed from ``scripts/`` and
  lives under ``tools/gmat_scraper`` — i.e. it is *quarantined* off the
  MVP runtime surface and the guard's quarantine inventory tracks it.
* A *new* out-of-scope module (one the operator has not explicitly
  acknowledged) trips a clearly-named assertion so it cannot slip in
  unnoticed.
* A quarantine *leak* — a previously-relocated tool reappearing inside
  ``scripts/`` — is surfaced as a discipline failure.
* The guard is read-only and adds no broker / execution surface.

The guard never deletes anything.  When a future contributor wants to
land a new genuinely-in-scope module, they widen ``APPROVED_DOMAINS``
or add to ``EXPLICIT_IN_SCOPE`` with justification.  When they want to
land something deliberately out of scope, they either quarantine it
under ``tools/`` (preferred) or add it to ``KNOWN_OUT_OF_SCOPE`` and
document the reason in the PR.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import private_scope_guard as guard

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_gmat_scraper_is_not_present_under_scripts() -> None:
    """The GMAT scraper that caused the prior product-clarity penalty
    must NOT live under ``scripts/`` — it belongs in ``tools/``."""
    assert not (_REPO_ROOT / "scripts" / "gmat_scraper").exists(), (
        "scripts/gmat_scraper exists; the scraper must remain quarantined "
        "under tools/gmat_scraper to stay off the MVP runtime surface."
    )


def test_gmat_scraper_is_quarantined_under_tools() -> None:
    """The quarantined GMAT scraper directory must exist under tools/
    and be tracked in the scope-guard quarantine inventory."""
    assert (_REPO_ROOT / "tools" / "gmat_scraper").is_dir()
    assert "gmat_scraper" in guard.QUARANTINED_TOOL_DIRS
    report = guard.build_report()
    names = {q["name"] for q in report["quarantined_tools"]}
    assert "gmat_scraper" in names
    entry = next(q for q in report["quarantined_tools"] if q["name"] == "gmat_scraper")
    assert entry["expected_relative_path"] == "tools/gmat_scraper"
    assert entry["tools_path_exists"] is True
    assert entry["leaked_back_to_scripts"] is False


def test_no_new_review_required_modules_appear() -> None:
    """If you are seeing this test fail with a list of file names, you
    just added a module to ``scripts/`` that does not match any approved
    private-operator domain.  Either:

      * Move it to a domain the guard recognises, or
      * Widen ``APPROVED_DOMAINS`` in ``private_scope_guard.py`` and add
        a one-line rationale, or
      * Quarantine it under ``tools/`` and register it in
        ``QUARANTINED_TOOL_DIRS``, or
      * Add it to ``KNOWN_OUT_OF_SCOPE`` if you accept the scope creep
        intentionally (and document why in the PR description).
    """
    report = guard.build_report()
    review = report["review_required"]
    assert review == [], (
        "New out-of-scope module(s) detected; "
        "see scripts/private_scope_guard.py to acknowledge or remove: "
        f"{review!r}"
    )


def test_no_quarantine_leaks_on_live_repo() -> None:
    """A live repo must not show any quarantined directory leaking back
    into ``scripts/``.  If this fails, move the directory back under
    ``tools/`` or update ``QUARANTINED_TOOL_DIRS``."""
    report = guard.build_report()
    assert report["quarantine_leaks"] == [], (
        "Quarantined tool directory leaked back into scripts/: "
        f"{report['quarantine_leaks']!r}"
    )


@pytest.mark.parametrize(
    "module_name",
    [
        "signal_reactor.py",
        "signal_inbox_api.py",
        "source_health_score.py",
        "refresh_live_signals.py",
        "calibration_gate.py",
        "manual_trade_origin.py",
        "paper_trade_ledger.py",
        "paper_reconciliation.py",
        "reactor_calibration_report.py",
        "persistence.py",
        "api_server.py",
        "local_mvp_audit.py",
        "operator_control.py",
        "private_scope_guard.py",
    ],
)
def test_core_mvp_module_classified_in_scope(module_name: str) -> None:
    assert guard._classify(module_name) == "in_scope"


def test_gmat_scraper_classified_out_of_scope() -> None:
    assert guard._classify("gmat_scraper") == "out_of_scope"


def test_report_carries_safety_stamps() -> None:
    report = guard.build_report()
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["execution_permission"] is False
    assert report["can_execute"] is False
    assert report["ai_execution_count"] == 0


def test_report_is_not_a_failure_by_default() -> None:
    """Guard is informational — its existence does not by itself FAIL
    the test suite or the MVP audit."""
    report = guard.build_report()
    assert isinstance(report.get("out_of_scope_count"), int)
    assert isinstance(report.get("review_required_count"), int)
    assert isinstance(report.get("quarantine_leaks"), list)
    assert "REVIEW_REQUIRED" in report["operator_message"] or report[
        "operator_message"
    ].startswith("OK")


def test_guard_module_has_no_broker_execution_language() -> None:
    text = (_REPO_ROOT / "scripts" / "private_scope_guard.py").read_text(
        encoding="utf-8"
    )
    lowered = text.lower()
    for forbidden in (
        "place_order",
        "submit_order",
        "execute_trade",
        "broker_execute",
        "trade now",
        "ai-approved",
        "permission to trade",
        "auto-trading",
    ):
        assert forbidden not in lowered, (
            f"forbidden phrase {forbidden!r} present in scope guard"
        )


def test_guard_does_not_delete_or_move_files(tmp_path: Path) -> None:
    """Build the report against a synthetic tree and verify the scripts
    directory is unchanged.  Pointing the guard at a tmp copy guarantees
    we are exercising the real file-walk path; importing the module did
    not perform any I/O side effect."""
    fake_scripts = tmp_path / "scripts"
    fake_scripts.mkdir()
    fake_tools = tmp_path / "tools"
    fake_tools.mkdir()
    (fake_scripts / "signal_engine.py").write_text("# placeholder\n", encoding="utf-8")
    (fake_scripts / "totally_new_module.py").write_text(
        "# placeholder\n", encoding="utf-8"
    )
    # Quarantined tool lives under tools/, not scripts/.
    (fake_tools / "gmat_scraper").mkdir()

    before_scripts = sorted(p.name for p in fake_scripts.iterdir())
    before_tools = sorted(p.name for p in fake_tools.iterdir())
    report = guard.build_report(fake_scripts, tools_dir=fake_tools)
    after_scripts = sorted(p.name for p in fake_scripts.iterdir())
    after_tools = sorted(p.name for p in fake_tools.iterdir())

    assert before_scripts == after_scripts, "scope guard must not mutate scripts/"
    assert before_tools == after_tools, "scope guard must not mutate tools/"
    assert "signal_engine.py" in report["in_scope"]
    assert "totally_new_module.py" in report["review_required"]


def test_new_unknown_module_triggers_review_required(tmp_path: Path) -> None:
    """A brand-new top-level entry under scripts/ that does not match any
    approved domain, is not in PREEXISTING_BASELINE, and is not in
    KNOWN_OUT_OF_SCOPE must show up in ``review_required`` so the
    operator sees it explicitly."""
    fake_scripts = tmp_path / "scripts"
    fake_scripts.mkdir()
    fake_tools = tmp_path / "tools"
    fake_tools.mkdir()
    (fake_scripts / "experimental_scope_violation.py").write_text(
        "# placeholder\n", encoding="utf-8"
    )
    (fake_tools / "gmat_scraper").mkdir()

    report = guard.build_report(fake_scripts, tools_dir=fake_tools)
    assert "experimental_scope_violation.py" in report["review_required"]
    assert report["review_required_count"] >= 1
    assert "REVIEW_REQUIRED" in report["operator_message"]


def test_quarantine_leak_is_surfaced(tmp_path: Path) -> None:
    """If a previously-quarantined directory reappears under scripts/,
    the guard must mark it as a quarantine leak so the operator can move
    it back."""
    fake_scripts = tmp_path / "scripts"
    fake_scripts.mkdir()
    fake_tools = tmp_path / "tools"
    fake_tools.mkdir()
    # Simulate the leak: scripts/gmat_scraper has been re-created.
    (fake_scripts / "gmat_scraper").mkdir()
    (fake_tools / "gmat_scraper").mkdir()

    report = guard.build_report(fake_scripts, tools_dir=fake_tools)
    assert report["quarantine_leaks"] == ["scripts/gmat_scraper"]
    assert "REVIEW_REQUIRED" in report["operator_message"]
    entry = next(q for q in report["quarantined_tools"] if q["name"] == "gmat_scraper")
    assert entry["leaked_back_to_scripts"] is True


def test_quarantined_tool_dirs_are_acknowledged() -> None:
    """Each quarantined tool entry must carry a non-empty rationale so
    the operator-facing report can explain why the directory was moved
    off the MVP surface."""
    assert guard.QUARANTINED_TOOL_DIRS, "expected at least one quarantined entry"
    for name, rationale in guard.QUARANTINED_TOOL_DIRS.items():
        assert rationale.strip(), f"quarantine entry {name!r} has empty rationale"
