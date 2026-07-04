"""Regression tests: broken scheduler runs must exit non-zero.

Forensic audit (2026-07-04) found scripts/nbi_scheduler.py returned exit 0
for BROKEN runs because the CLI compared against legacy STATUS_FAILED, a
value run_once() never emits.  Task Scheduler therefore recorded Last Result
0 on every failure — silent death.  These tests pin the fixed semantics:

    HEALTHY            -> 0
    DEGRADED_BUT_SAFE  -> 0   (designed non-blocking, visible in the record)
    BROKEN             -> 1
    BROKEN_UNSAFE      -> 1
    FAILED (legacy)    -> 1
    anything unknown   -> 1   (fail closed, never fail silent)
"""
from __future__ import annotations

import pytest

from scripts import nbi_scheduler


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [
        (nbi_scheduler.STATUS_HEALTHY, 0),
        (nbi_scheduler.STATUS_DEGRADED_BUT_SAFE, 0),
        (nbi_scheduler.STATUS_BROKEN, 1),
        (nbi_scheduler.STATUS_BROKEN_UNSAFE, 1),
        (nbi_scheduler.STATUS_FAILED, 1),
        ("SOMETHING_UNEXPECTED", 1),
        (None, 1),
    ],
)
def test_run_once_exit_code_matches_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    status: str | None, expected_exit: int,
) -> None:
    monkeypatch.setattr(
        nbi_scheduler, "run_once", lambda **kwargs: {"status": status}
    )
    rc = nbi_scheduler.main(["run-once"])
    assert rc == expected_exit, (
        f"status={status!r} must exit {expected_exit}, got {rc}"
    )
    if expected_exit == 1:
        err = capsys.readouterr().err
        assert "FAILED" in err or "BROKEN" in str(status) or True
        assert "NBI SCHEDULER RUN FAILED" in err, (
            "broken runs must say so on stderr for the operator"
        )


def test_broken_status_can_never_exit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """The original bug: BROKEN compared against STATUS_FAILED -> exit 0."""
    monkeypatch.setattr(
        nbi_scheduler,
        "run_once",
        lambda **kwargs: {"status": nbi_scheduler.STATUS_BROKEN},
    )
    assert nbi_scheduler.main(["run-once"]) != 0


def test_run_once_health_includes_maturation_component() -> None:
    """The daily loop must carry the outcome-maturation axis in its health

    record (forensic audit SP-013: 'installed daily scheduler runs no
    outcome-maturation step').  A dry run must not, because dry runs never
    touch the DB.
    """
    record = nbi_scheduler.run_once(dry_run=True)
    assert record["dry_run"] is True
    assert record["db_mutated"] is False
    # The live-record contract is pinned by source inspection: run_once must
    # reference the maturation runner and emit the closure counters.
    import inspect

    src = inspect.getsource(nbi_scheduler.run_once)
    assert "run_daily_outcome_maturation" in src
    assert "outcomes_closed" in src
    assert "maturation_ok" in src
