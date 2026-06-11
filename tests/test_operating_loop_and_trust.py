"""Daily operating loop, history bootstrap, and trust ladder proofs (Pass 6)."""
from __future__ import annotations

import datetime as dt
import json
import os

import pytest

from scripts import bootstrap_signal_history as boot
from scripts import daily_model_operating_loop as loop
from scripts import model_trust_ladder as ladder

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC).isoformat()


@pytest.fixture
def env(tmp_path, monkeypatch):
    import scripts.persistence as persistence

    db = tmp_path / "db.sqlite"
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=False)
    persistence.init_schema(db)
    monkeypatch.setenv("MVP_EVIDENCE_LEDGER_PATH", str(tmp_path / "ev.jsonl"))
    monkeypatch.setenv("MVP_DERIVED_SCORE_LEDGER_PATH", str(tmp_path / "ds.jsonl"))
    monkeypatch.setenv("MVP_SHADOW_LEDGER_PATH", str(tmp_path / "shadow.jsonl"))
    monkeypatch.setenv("MVP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    return {"db": db, "tmp": tmp_path}


# ---------------------------------------------------------------------------
# Daily operating loop
# ---------------------------------------------------------------------------


def test_loop_creates_report_with_advisory_framing(env, tmp_path, monkeypatch):
    monkeypatch.setattr(loop.memo if hasattr(loop, "memo") else None, "MEMO_DIR",
                        tmp_path / "memos", raising=False) if False else None
    result = loop.run_loop(env["db"])
    path = loop.write_report(result, out_dir=tmp_path / "reports")
    text = path.read_text(encoding="utf-8")
    assert path.name.startswith("daily_model_loop_")
    assert "ADVISORY ONLY" in text and "HUMAN REVIEW REQUIRED" in text
    assert "never acts" in text
    for banned in ("guaranteed", "sure profit", "execute now", "place order"):
        assert banned not in text.lower()


def test_loop_emits_no_execution_shaped_objects(env):
    from scripts import derived_score_ledger as dsl
    from scripts import signal_tournament as st

    loop.run_loop(env["db"])
    # Everything the loop persisted survives the contract verifiers.
    assert dsl.verify_chain()["valid"] is True
    shadow = st.shadow_ledger_path()
    if shadow.exists():
        for line in shadow.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            assert row["NOT_AN_ORDER"] is True
            assert "order_id" not in row and "broker" not in row


def test_loop_scores_are_research_abstains_linked_to_evidence(env):
    from scripts import data_quality as dq
    from scripts import derived_score_ledger as dsl
    from scripts import evidence_bridge as eb

    eb.record_evidence(source_type="api", source_name="gdelt",
                       claim="ACME wins contract", raw_evidence=b"x",
                       observed_at=NOW, symbol="ACME")
    result = loop.run_loop(env["db"])
    assert not result["failures"], result["steps"]
    records = dsl.read_ledger()
    assert records, "loop should ledger one research score per evidenced symbol"
    assert all(r["abstain"] is True for r in records)
    assert all(r["input_evidence_ids"] for r in records)
    assert dq.verify_ledger() == []


def test_due_outcome_detection(env, tmp_path, monkeypatch):
    from scripts import generate_decision_memo as memo

    memo_dir = tmp_path / "memos"
    memo_dir.mkdir()
    old_memo = memo_dir / "ACME_old.md"
    old_memo.write_text("# memo", encoding="utf-8")
    stale = (dt.datetime.now(UTC) - dt.timedelta(days=45)).timestamp()
    os.utime(old_memo, (stale, stale))
    monkeypatch.setattr(memo, "MEMO_DIR", memo_dir)
    result = loop.run_loop(env["db"])
    due = next(s for s in result["steps"] if s["step"] == "due_outcome_checks")
    assert "DUE for post-outcome review" in due["detail"]
    assert "ACME_old.md" in due["detail"]


def test_insufficient_data_warnings_everywhere(env):
    result = loop.run_loop(env["db"])
    steps = {s["step"]: s["detail"] for s in result["steps"]}
    assert "provisional" in steps["calibration_update"].lower() \
        or "no evidence" in steps["calibration_update"].lower() \
        or "UNCALIBRATED" in steps["calibration_update"]
    assert ("INSUFFICIENT" in steps["tournament_update"]
            or "PROVISIONAL" in steps["tournament_update"])
    assert "L1" in steps["trust_ladder"] or "L2" in steps["trust_ladder"]
    assert "execution_ready=False" in steps["trust_ladder"]


def test_tournament_refuses_ranking_below_oos_minimum(env, tmp_path, monkeypatch):
    from scripts import signal_tournament as st

    shadow = tmp_path / "shadow.jsonl"
    monkeypatch.setenv("MVP_SHADOW_LEDGER_PATH", str(shadow))
    for i in range(5):  # 5 < MIN_PROVISIONAL_OOS
        st.append_shadow_observation({"variant": "x", "signal_id": f"S{i}",
                                      "oos": True, "outcome_known": True,
                                      "net_return_hypothetical": 0.01})
    result = loop.run_loop(env["db"])
    detail = next(s["detail"] for s in result["steps"]
                  if s["step"] == "tournament_update")
    assert "PROVISIONAL ONLY" in detail and "refused" in detail


# ---------------------------------------------------------------------------
# History bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_ingests_resolved_outcomes_and_reports_exclusions(env, tmp_path):
    import scripts.persistence as persistence

    db = env["db"]
    persistence.insert_manual_trade(
        "T1", "E1", "ACME", "BUY", 1.0, 100.0, NOW, "thesis", "", "human",
        db_path=db)
    persistence.insert_reconciliation(
        "R1", "T1", "E1", "2026-06-05T12:00:00+00:00", 105.0, 1.0, "", 5.0,
        "WIN", db_path=db)
    # An unresolved trade → uncertain, not invented.
    persistence.insert_manual_trade(
        "T2", "E2", "ZETA", "BUY", 1.0, 50.0, NOW, "thesis", "", "human",
        db_path=db)
    report = boot.bootstrap(db, ledger_path=tmp_path / "shadow.jsonl")
    assert report["ingested"] >= 1
    assert report["uncertain"], "unresolved outcomes must be listed as uncertain"
    assert "future operating-loop usage" in report["honesty_note"]
    path = boot.write_report(report, out_dir=tmp_path)
    assert "excluded" in path.read_text(encoding="utf-8")
    rows = [json.loads(l) for l in (tmp_path / "shadow.jsonl").read_text(
        encoding="utf-8").splitlines()]
    assert all(r["NOT_AN_ORDER"] is True for r in rows)
    assert all(r["recommendation"] == "HISTORICAL_HUMAN_DECISION" for r in rows)


# ---------------------------------------------------------------------------
# Trust ladder — anti-overclaiming caps
# ---------------------------------------------------------------------------


def _inputs(**kw):
    base = dict(synthetic_tests_green=True, paper_tracking_started=True,
                real_oos_outcomes=0, ece=None,
                unresolved_temporal_violations=0, redteam_all_safe=True,
                independent_review=False)
    base.update(kw)
    return ladder.TrustInputs(**base)


def test_synthetic_only_capped_at_l1_l2():
    no_paper = ladder.evaluate(_inputs(paper_tracking_started=False))
    assert no_paper["level"] == "L1_SYNTHETIC_VALIDATED"
    with_paper = ladder.evaluate(_inputs())
    assert with_paper["level"] == "L2_PAPER_TRACKING_STARTED"


def test_29_oos_outcomes_cannot_reach_l3():
    result = ladder.evaluate(_inputs(real_oos_outcomes=29))
    assert result["level_index"] <= 2
    result30 = ladder.evaluate(_inputs(real_oos_outcomes=30))
    assert result30["level"] == "L3_MINIMUM_OOS_SAMPLE"


def test_100_oos_with_poor_calibration_capped_at_l3():
    poor = ladder.evaluate(_inputs(real_oos_outcomes=100, ece=0.25))
    assert poor["level"] == "L3_MINIMUM_OOS_SAMPLE"
    missing = ladder.evaluate(_inputs(real_oos_outcomes=100, ece=None))
    assert missing["level"] == "L3_MINIMUM_OOS_SAMPLE"
    good = ladder.evaluate(_inputs(real_oos_outcomes=100, ece=0.05))
    assert good["level"] == "L4_CALIBRATED_OOS"


def test_temporal_violations_cap_trust():
    result = ladder.evaluate(_inputs(real_oos_outcomes=100, ece=0.05,
                                     unresolved_temporal_violations=2))
    assert result["level_index"] <= 3
    assert any("temporal" in c for c in result["binding_caps"])


def test_redteam_failure_caps_at_l2():
    result = ladder.evaluate(_inputs(real_oos_outcomes=100, ece=0.05,
                                     redteam_all_safe=False))
    assert result["level_index"] <= 2


def test_independent_review_required_for_l5():
    no_review = ladder.evaluate(_inputs(real_oos_outcomes=200, ece=0.05))
    assert no_review["level"] == "L4_CALIBRATED_OOS"
    reviewed = ladder.evaluate(_inputs(real_oos_outcomes=200, ece=0.05,
                                       independent_review=True))
    assert reviewed["level"] == "L5_INDEPENDENTLY_REVIEWED"


def test_execution_readiness_always_false():
    for outcomes in (0, 30, 100, 1000):
        result = ladder.evaluate(_inputs(real_oos_outcomes=outcomes, ece=0.01,
                                         independent_review=True))
        assert result["execution_ready"] is False


def test_ladder_report_written(tmp_path):
    result = ladder.evaluate(_inputs())
    path = ladder.write_report(result, out_dir=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "model_trust_ladder_" in path.name
    assert "Execution ready: **False** (permanently)" in text
    assert "never expected profit" in text
