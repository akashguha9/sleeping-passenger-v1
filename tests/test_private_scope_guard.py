"""Private-operator scope guard.

This is a *discipline* test, not a deletion test.  It verifies that:

* Approved core modules (signal/source/reactor/calibration/...) classify
  as in-scope.
* Known out-of-scope modules (e.g. the GMAT scraper) are detected but do
  not fail the suite unless they leave the ``KNOWN_OUT_OF_SCOPE`` set.
* A *new* out-of-scope module (one the operator has not explicitly
  acknowledged) trips a clearly-named assertion so it cannot slip in
  unnoticed.
* The guard is read-only and adds no broker / execution surface.

The guard never deletes anything.  When a future contributor wants to
land a new genuinely-in-scope module, they widen ``APPROVED_DOMAINS``
or add to ``EXPLICIT_IN_SCOPE`` with justification.  When they want to
land something deliberately out of scope, they add it to
``KNOWN_OUT_OF_SCOPE`` and document the reason in the PR.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import private_scope_guard as guard

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_known_out_of_scope_module_detected() -> None:
    """The GMAT scraper that caused the prior product-clarity penalty
    must show up in the out-of-scope list — but, since it is in
    ``KNOWN_OUT_OF_SCOPE``, it must NOT show up in the review-required
    list."""
    report = guard.build_report()
    assert "gmat_scraper" in report["out_of_scope"]
    assert "gmat_scraper" not in report["review_required"]


def test_no_new_review_required_modules_appear() -> None:
    """If you are seeing this test fail with a list of file names, you
    just added a module to ``scripts/`` that does not match any approved
    private-operator domain.  Either:

      * Move it to a domain the guard recognises, or
      * Widen ``APPROVED_DOMAINS`` in ``private_scope_guard.py`` and add
        a one-line rationale, or
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
    # All counts are integers; presence of out-of-scope items is allowed
    # so long as they are pre-accepted.
    assert isinstance(report.get("out_of_scope_count"), int)
    assert isinstance(report.get("review_required_count"), int)
    # The operator_message is human-readable; never a hostile assertion.
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
    """Build the report and verify the scripts directory is unchanged.

    Pointing the guard at a tmp copy guarantees we are exercising the
    real file-walk path; importing the module did not perform any I/O
    side effect.
    """
    fake_scripts = tmp_path / "scripts"
    fake_scripts.mkdir()
    (fake_scripts / "signal_engine.py").write_text("# placeholder\n", encoding="utf-8")
    (fake_scripts / "gmat_scraper").mkdir()
    (fake_scripts / "totally_new_module.py").write_text(
        "# placeholder\n", encoding="utf-8"
    )

    before = sorted(p.name for p in fake_scripts.iterdir())
    report = guard.build_report(fake_scripts)
    after = sorted(p.name for p in fake_scripts.iterdir())

    assert before == after, "scope guard must not mutate the scripts directory"
    assert "signal_engine.py" in report["in_scope"]
    assert "gmat_scraper" in report["out_of_scope"]
    assert "totally_new_module.py" in report["review_required"]
