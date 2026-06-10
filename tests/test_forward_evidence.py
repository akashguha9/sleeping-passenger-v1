"""S4-E1/E2 regression: forward-only ledger + gated evidence report.

Edge firewall: NOTHING here claims edge.  The tests prove the machinery
refuses retroactive signals, never deletes, computes exact Decimal P/L,
and the report suppresses edge language until T>=30 with CI lower > 0.
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from scripts import persistence
from scripts.forward_evidence_ledger import (
    ForwardLedgerError,
    invalidate_signal,
    correct_record,
    load_cohort,
    record_entry,
    record_exit,
    register_signal,
)
from scripts.forward_evidence_report import (
    GATE_MIN_T,
    MSG_CI_ZERO,
    MSG_DIRECTIONAL,
    MSG_SAMPLE,
    compute_report,
)


@pytest.fixture()
def db(tmp_path) -> Path:
    p = tmp_path / "fwd.db"
    persistence.init_schema(p)
    return p


def _register(db, sid="S1", **over):
    base = dict(
        signal_id=sid, ticker="BTC", signal_at="2026-06-01T10:00:00Z",
        entry_eligible_at="2026-06-01T15:30:00Z", probability=0.6,
        capital_at_risk="1000", db_path=db,
    )
    base.update(over)
    return register_signal(**base)


def _close(db, sid, entry="100", exit_="110", qty="1", fees="1", prob=0.6,
           entered="2026-06-01T15:31:00Z", exited="2026-06-05T15:31:00Z"):
    record_entry(signal_id=sid, entered_at=entered, entry_price=entry,
                 entry_price_source="pinned", entry_snapshot_sha256="abc",
                 db_path=db)
    return record_exit(signal_id=sid, exited_at=exited, exit_price=exit_,
                       exit_price_source="pinned", exit_snapshot_sha256="def",
                       quantity=qty, fees=fees, db_path=db)


# ---------------------------------------------------------------------------
# E1 — forward-only contract
# ---------------------------------------------------------------------------


def test_future_looking_signal_accepted(db):
    out = _register(db)
    assert out["status"] == "OPEN"
    assert out["execution_gate"] == "LOCKED"


def test_signal_at_or_after_eligibility_rejected(db):
    with pytest.raises(ForwardLedgerError) as exc:
        _register(db, sid="S_BAD", signal_at="2026-06-01T15:30:00Z")
    assert "forward-only violation" in str(exc.value)
    with pytest.raises(ForwardLedgerError):
        _register(db, sid="S_BAD2", signal_at="2026-06-02T00:00:00Z")


def test_entry_before_eligibility_rejected(db):
    _register(db, sid="S_EARLY")
    with pytest.raises(ForwardLedgerError):
        record_entry(signal_id="S_EARLY", entered_at="2026-06-01T12:00:00Z",
                     entry_price="100", entry_price_source="pinned",
                     entry_snapshot_sha256="abc", db_path=db)


def test_no_hard_delete_possible(db):
    import scripts.forward_evidence_ledger as ledger

    _register(db, sid="S_KEEP")
    # No delete API exists on the module...
    assert not any("delete" in name.lower() for name in dir(ledger)
                   if not name.startswith("_"))
    # ...and the row is still there after an invalidation (status change only).
    invalidate_signal("S_KEEP", "thesis broken", db_path=db)
    conn = sqlite3.connect(str(db))
    n = conn.execute("SELECT COUNT(*) FROM paper_signals").fetchone()[0]
    status = conn.execute(
        "SELECT status FROM paper_signals WHERE signal_id='S_KEEP'"
    ).fetchone()[0]
    conn.close()
    assert n == 1 and status == "INVALIDATED"


def test_correction_writes_audit_row(db):
    _register(db, sid="S_CORR")
    correct_record("S_CORR", "status_reason", "clarified", "typo fix", db_path=db)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    audit = conn.execute(
        "SELECT * FROM audit_log WHERE row_id='S_CORR'"
    ).fetchall()
    conn.close()
    assert len(audit) == 1
    assert audit[0]["operation"] == "CORRECTION"


def test_unpinned_price_marks_data_invalid_not_excluded(db):
    _register(db, sid="S_NOPIN")
    out = record_entry(signal_id="S_NOPIN", entered_at="2026-06-01T16:00:00Z",
                       entry_price="100", entry_price_source="live-fetch",
                       entry_snapshot_sha256="", db_path=db)
    assert out["status"] == "DATA_INVALID"
    report = compute_report(load_cohort(db))
    # counted in the denominator, not silently dropped
    assert report["registered_forward_signals"] == 1
    assert report["invalid_or_data_invalid"] == 1


def test_closed_trade_pnl_is_exact_decimal(db):
    _register(db, sid="S_PNL")
    out = _close(db, "S_PNL", entry="100.10", exit_="100.40", qty="3", fees="0.05")
    # (100.40-100.10)*3 - 0.05 = 0.85 exactly
    assert Decimal(out["pnl_net"]) == Decimal("0.85")
    assert out["status"] == "CLOSED_WIN"


# ---------------------------------------------------------------------------
# E2 — gated report
# ---------------------------------------------------------------------------


def _cohort_with_closed(db, n, *, winners=None):
    for i in range(n):
        sid = f"S_{i:03d}"
        _register(db, sid=sid, probability=0.55)
        win = winners[i] if winners is not None else (i % 3 != 0)
        _close(db, sid, entry="100", exit_="110" if win else "95", fees="1")


def test_t0_report_suppresses_edge(db):
    report = compute_report(load_cohort(db))
    assert report["closed_forward_trades"] == 0
    assert MSG_SAMPLE in report["statements"]
    assert report["edge_proven"] is False


@pytest.mark.parametrize("t", [7, 29])
def test_below_gate_suppresses_edge(db, t):
    _cohort_with_closed(db, t)
    report = compute_report(load_cohort(db))
    assert report["closed_forward_trades"] == t
    assert MSG_SAMPLE in report["statements"]
    assert report["sharpe"] is None
    assert "below 30" in report["sharpe_note"]


def test_t30_with_ci_including_zero_suppresses_edge(db):
    # Alternate winners/losers symmetric → mean ~0, CI includes 0.
    winners = [i % 2 == 0 for i in range(GATE_MIN_T)]
    _cohort_with_closed(db, GATE_MIN_T, winners=winners)
    report = compute_report(load_cohort(db))
    assert report["closed_forward_trades"] == GATE_MIN_T
    assert report["ci95_lower"] <= 0
    assert MSG_CI_ZERO in report["statements"]
    assert MSG_DIRECTIONAL not in report["statements"]


def test_t30_positive_ci_is_directional_not_proven(db):
    _cohort_with_closed(db, GATE_MIN_T, winners=[True] * GATE_MIN_T)
    report = compute_report(load_cohort(db))
    assert report["ci95_lower"] is not None
    # all-winner cohort has zero variance → CI degenerates; mean > 0
    assert MSG_DIRECTIONAL in report["statements"]
    assert report["edge_proven"] is False  # never proven by this report
    assert "size-up" in MSG_DIRECTIONAL


def test_brier_score_exactness(db):
    _register(db, sid="S_B1", probability=1.0)
    _close(db, "S_B1", exit_="110")  # win, y=1 → (1-1)^2 = 0
    _register(db, sid="S_B2", probability=0.5)
    _close(db, "S_B2", exit_="95")  # loss, y=0 → (0.5)^2 = 0.25
    report = compute_report(load_cohort(db))
    assert report["brier_score"] == pytest.approx((0.0 + 0.25) / 2)


def test_drawdown_exactness(db):
    # +10, -20, +5 → equity 10, -10, -5; peak 10 → MDD = (-10-10)/10 = -2
    _register(db, sid="S_D1")
    _close(db, "S_D1", entry="100", exit_="110", fees="0")
    _register(db, sid="S_D2")
    _close(db, "S_D2", entry="100", exit_="80", fees="0")
    _register(db, sid="S_D3")
    _close(db, "S_D3", entry="100", exit_="105", fees="0")
    report = compute_report(load_cohort(db))
    assert Decimal(report["max_drawdown"]) == Decimal("-2")


def test_denominators_include_invalid(db):
    _cohort_with_closed(db, 3)
    _register(db, sid="S_INV")
    invalidate_signal("S_INV", "broken", db_path=db)
    report = compute_report(load_cohort(db))
    assert report["registered_forward_signals"] == 4
    assert report["closed_forward_trades"] == 3
    assert report["invalid_or_data_invalid"] == 1
