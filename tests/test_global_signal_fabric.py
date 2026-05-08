"""Tests for Phase 1 Global Signal Fabric.

Goals
-----
1. All tests use fixture seeds or in-memory data — no real network, no external
   API keys, no writes beyond scratch_path.
2. Advisory contract: every report and ticker summary carries advisory_status,
   human_review_required, and execution_gate.
3. No execution path: prove the module imports no paper/live-execution symbols
   and that SignalEvent / SnapshotRow have no order-placement fields.
4. Scoring skeletons: persistence, blocker_pressure, kill_rate, attach_scores.
5. Bull-state classifier: all five states including UNKNOWN edge case.
6. Fail-safe: missing files and malformed JSONL lines are tolerated.
7. Write isolation: with write_runtime=False the fabric report never touches
   SCM, policy, position, or paper-execution paths.
"""
from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path

import pytest

from scripts.global_signal_fabric import (
    SignalEvent,
    SnapshotRow,
    attach_scores,
    build_global_signal_fabric_report,
    classify_fabric_bull_state,
    load_signal_events_from_attribution,
    load_signal_events_from_kill_log,
    load_signal_events_from_snapshots,
    load_snapshot_rows,
    score_blocker_pressure,
    score_kill_rate,
    score_persistence,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
SEED_SNAPSHOTS = FIXTURES_DIR / "system_snapshots_seed.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(
    run_id: str = "test_run_01",
    scm_rate: float = 0.286,
    scm_state: str = "LOW_CONVERSION",
    policy_state: str = "RESTRICTED",
    allow_new_risk: bool = False,
    blockers_active: list[str] | None = None,
    clean_entries: int = 2,
    chaos_entries: int = 2,
    promotable_watchlist_count: int = 2,
    transition_state_rows: list[dict] | None = None,
) -> SnapshotRow:
    return SnapshotRow(
        run_id=run_id,
        timestamp="2026-05-01T12:00:00+00:00",
        scm_rate=scm_rate,
        scm_state=scm_state,
        policy_state=policy_state,
        allow_new_risk=allow_new_risk,
        blockers_active=blockers_active if blockers_active is not None else ["GSCE_PHASE_LOCK", "REALM_BIS"],
        clean_entries=clean_entries,
        chaos_entries=chaos_entries,
        signals_above_threshold=7,
        watchlist_count=3,
        promotable_watchlist_count=promotable_watchlist_count,
        transition_state_rows=transition_state_rows or [],
    )


def _make_event(
    ticker: str = "RTX",
    signal_state: str = "WATCHLIST",
    entry_type: str = "CLEAN",
    source_run_id: str = "run_01",
    blocker: str = "GSCE_PHASE_LOCK",
    source_file: str = "attribution",
) -> SignalEvent:
    return SignalEvent(
        signal_id=f"SIG_{ticker}_{source_run_id}",
        ticker=ticker,
        signal_state=signal_state,
        entry_type=entry_type,
        source_run_id=source_run_id,
        observed_at="2026-05-01T12:00:00+00:00",
        priority_score=0.75,
        blocker_attribution=blocker,
        source_file=source_file,
    )


def _five_events() -> list[SignalEvent]:
    return [
        _make_event("RTX", source_run_id="run_01", blocker="GSCE_PHASE_LOCK"),
        _make_event("RTX", source_run_id="run_02", blocker="GSCE_PHASE_LOCK"),
        _make_event("RTX", source_run_id="run_03", blocker="NONE"),
        _make_event("ZIM", source_run_id="run_01", blocker="REALM_BIS"),
        _make_event(
            "ZIM",
            signal_state="REJECTED",
            source_run_id="run_02",
            blocker="NONE",
            source_file="kill_log",
        ),
    ]


# ---------------------------------------------------------------------------
# Advisory contract
# ---------------------------------------------------------------------------


class TestAdvisoryContract:
    def test_report_advisory_status(self) -> None:
        report = build_global_signal_fabric_report(
            snapshot_path=SEED_SNAPSHOTS, write_runtime=False
        )
        assert report["advisory_status"] == "ADVISORY_ONLY"

    def test_report_human_review_required(self) -> None:
        report = build_global_signal_fabric_report(
            snapshot_path=SEED_SNAPSHOTS, write_runtime=False
        )
        assert report["human_review_required"] is True

    def test_report_execution_gate_locked(self) -> None:
        report = build_global_signal_fabric_report(
            snapshot_path=SEED_SNAPSHOTS, write_runtime=False
        )
        assert report["execution_gate"] == "LOCKED"

    def test_ticker_summaries_carry_advisory_fields(self) -> None:
        report = build_global_signal_fabric_report(
            snapshot_path=SEED_SNAPSHOTS, write_runtime=False
        )
        for summary in report.get("ticker_summaries", []):
            assert summary["advisory_status"] == "ADVISORY_ONLY"
            assert summary["human_review_required"] is True

    def test_bull_state_context_has_advisory_note(self) -> None:
        snaps = [_make_snapshot(f"r{i}") for i in range(3)]
        result = classify_fabric_bull_state(snaps)
        assert "advisory_note" in result

    def test_report_contains_no_execution_fields(self) -> None:
        report = build_global_signal_fabric_report(
            snapshot_path=SEED_SNAPSHOTS, write_runtime=False
        )
        forbidden = {
            "buy", "sell", "order", "fill", "execute",
            "can_deploy_capital", "paper_execution_enabled",
            "live_execution_enabled",
        }
        assert not (set(report.keys()) & forbidden), (
            f"Report contains forbidden execution keys: {set(report.keys()) & forbidden}"
        )

    def test_bull_state_result_has_no_execution_keys(self) -> None:
        snaps = [_make_snapshot(f"r{i}") for i in range(3)]
        result = classify_fabric_bull_state(snaps)
        forbidden = {"buy", "sell", "order", "allow_new_risk", "execution_policy"}
        assert not (set(result.keys()) & forbidden)


# ---------------------------------------------------------------------------
# No execution path
# ---------------------------------------------------------------------------


class TestNoExecutionPath:
    def test_module_does_not_import_paper_execution(self) -> None:
        import scripts.global_signal_fabric as mod
        source = inspect.getsource(mod)
        for forbidden in ("paper_execution", "build_paper_order", "emit_paper_action",
                          "live_execution", "build_live_order"):
            assert forbidden not in source, (
                f"global_signal_fabric.py must not reference {forbidden!r}"
            )

    def test_module_does_not_call_persist_state(self) -> None:
        import scripts.global_signal_fabric as mod
        source = inspect.getsource(mod)
        for forbidden in ("persist_current_runtime_state", "write_scm_report",
                          "approve_action", "load_open_positions"):
            assert forbidden not in source, (
                f"global_signal_fabric.py must not reference {forbidden!r}"
            )

    def test_signal_event_has_no_order_fields(self) -> None:
        field_names = {f.name for f in dataclasses.fields(SignalEvent)}
        forbidden = {"order_id", "fill_price", "quantity", "side",
                     "execution_policy", "approval_state",
                     "human_execution_required"}
        assert not (field_names & forbidden), (
            f"SignalEvent has forbidden fields: {field_names & forbidden}"
        )

    def test_snapshot_row_has_no_order_fields(self) -> None:
        field_names = {f.name for f in dataclasses.fields(SnapshotRow)}
        forbidden = {"order_id", "fill_price", "quantity", "side", "entry_price"}
        assert not (field_names & forbidden)

    def test_write_false_does_not_touch_scm_paths(self, scratch_path: Path) -> None:
        scm_paths = [
            REPO_ROOT / "runtime" / "scm_report.json",
            REPO_ROOT / "runtime" / "execution_policy.json",
            REPO_ROOT / "logs" / "paper_decisions.jsonl",
            REPO_ROOT / "logs" / "paper_orders.jsonl",
        ]
        before = {p: p.stat().st_mtime if p.exists() else None for p in scm_paths}

        build_global_signal_fabric_report(
            snapshot_path=SEED_SNAPSHOTS,
            attribution_path=scratch_path / "empty_attr.json",
            kill_log_path=scratch_path / "empty_kill.jsonl",
            write_runtime=False,
        )

        after = {p: p.stat().st_mtime if p.exists() else None for p in scm_paths}
        assert before == after, "Fabric must not touch SCM/execution paths"


# ---------------------------------------------------------------------------
# Snapshot loader
# ---------------------------------------------------------------------------


class TestSnapshotLoader:
    def test_loads_seed_file(self) -> None:
        rows = load_snapshot_rows(SEED_SNAPSHOTS)
        assert len(rows) >= 5

    def test_row_field_types(self) -> None:
        rows = load_snapshot_rows(SEED_SNAPSHOTS)
        first = rows[0]
        assert isinstance(first.run_id, str) and first.run_id
        assert isinstance(first.scm_rate, float)
        assert isinstance(first.blockers_active, list)
        assert isinstance(first.transition_state_rows, list)

    def test_missing_file_returns_empty(self, scratch_path: Path) -> None:
        assert load_snapshot_rows(scratch_path / "nonexistent.jsonl") == []

    def test_malformed_lines_skipped(self, scratch_path: Path) -> None:
        bad = scratch_path / "bad.jsonl"
        bad.write_text(
            '{"run_id":"ok1","scm_rate":0.5,"timestamp":"2026-01-01T00:00:00+00:00"}\n'
            "{broken json\n"
            '{"run_id":"ok2","scm_rate":0.3,"timestamp":"2026-01-02T00:00:00+00:00"}\n',
            encoding="utf-8",
        )
        rows = load_snapshot_rows(bad)
        assert len(rows) == 2

    def test_snapshot_row_to_dict(self) -> None:
        row = _make_snapshot()
        d = row.to_dict()
        assert isinstance(d, dict)
        assert d["run_id"] == "test_run_01"


# ---------------------------------------------------------------------------
# Attribution loader
# ---------------------------------------------------------------------------


class TestAttributionLoader:
    def test_loads_from_fixture(self, scratch_path: Path) -> None:
        attr_file = scratch_path / "attr.json"
        attr_file.write_text(
            json.dumps({
                "per_signal_attribution": [
                    {"signal_id": "SIG_001", "ticker": "RTX",
                     "entry_type": "CLEAN", "signal_state": "WATCHLIST",
                     "blocker_attribution": "GSCE_PHASE_LOCK",
                     "priority_score": 0.75},
                    {"signal_id": "SIG_002", "ticker": "ZIM",
                     "entry_type": "CHAOS", "signal_state": "ACTIVE",
                     "blocker_attribution": "REALM_BIS",
                     "priority_score": 0.45},
                ]
            }),
            encoding="utf-8",
        )
        events = load_signal_events_from_attribution(attr_file)
        assert len(events) == 2
        tickers = [e.ticker for e in events]
        assert "RTX" in tickers
        assert "ZIM" in tickers
        for e in events:
            assert e.source_file == "attribution"

    def test_missing_file_returns_empty(self, scratch_path: Path) -> None:
        assert load_signal_events_from_attribution(scratch_path / "nope.json") == []

    def test_events_have_no_order_fields(self, scratch_path: Path) -> None:
        attr_file = scratch_path / "attr.json"
        attr_file.write_text(
            json.dumps({"per_signal_attribution": [{"ticker": "GLD", "priority_score": 0.5}]}),
            encoding="utf-8",
        )
        for e in load_signal_events_from_attribution(attr_file):
            d = e.to_dict()
            assert "order_id" not in d
            assert "fill_price" not in d


# ---------------------------------------------------------------------------
# Kill-log loader
# ---------------------------------------------------------------------------


class TestKillLogLoader:
    def test_all_kill_events_are_rejected(self) -> None:
        events = load_signal_events_from_kill_log()
        for e in events:
            assert e.signal_state == "REJECTED"
            assert e.source_file == "kill_log"

    def test_missing_file_returns_empty(self, scratch_path: Path) -> None:
        assert load_signal_events_from_kill_log(scratch_path / "nope.jsonl") == []

    def test_rejection_fields_populated(self, scratch_path: Path) -> None:
        kill_file = scratch_path / "kill.jsonl"
        kill_file.write_text(
            json.dumps({
                "ticker": "FCG",
                "signal_id": "SIG_001",
                "run_id": "run_test",
                "timestamp": "2026-05-01T00:00:00+00:00",
                "rejection_dimensions": ["relevance"],
                "rejection_reason": "ce_score_below_floor",
            }) + "\n",
            encoding="utf-8",
        )
        events = load_signal_events_from_kill_log(kill_file)
        assert len(events) == 1
        assert events[0].rejection_reason == "ce_score_below_floor"
        assert events[0].rejection_dimensions == ["relevance"]
        assert events[0].ticker == "FCG"

    def test_rows_without_ticker_are_skipped(self, scratch_path: Path) -> None:
        kill_file = scratch_path / "kill.jsonl"
        kill_file.write_text(
            '{"signal_id": "SIG_001", "run_id": "r1"}\n'
            '{"ticker": "GLD", "signal_id": "SIG_002", "run_id": "r2"}\n',
            encoding="utf-8",
        )
        events = load_signal_events_from_kill_log(kill_file)
        assert len(events) == 1
        assert events[0].ticker == "GLD"


# ---------------------------------------------------------------------------
# Snapshot-events loader
# ---------------------------------------------------------------------------


class TestSnapshotEventsLoader:
    def test_loads_transition_rows_from_seed(self) -> None:
        events = load_signal_events_from_snapshots(SEED_SNAPSHOTS)
        tickers = {e.ticker for e in events}
        assert "RTX" in tickers
        assert "ZIM" in tickers

    def test_all_snapshot_events_are_watchlist_clean(self) -> None:
        events = load_signal_events_from_snapshots(SEED_SNAPSHOTS)
        for e in events:
            assert e.signal_state == "WATCHLIST"
            assert e.source_file == "snapshots"

    def test_missing_file_returns_empty(self, scratch_path: Path) -> None:
        assert load_signal_events_from_snapshots(scratch_path / "nope.jsonl") == []


# ---------------------------------------------------------------------------
# Scoring skeletons
# ---------------------------------------------------------------------------


class TestPersistenceScore:
    def test_range(self) -> None:
        events = _five_events()
        assert 0.0 <= score_persistence("RTX", events) <= 1.0

    def test_full_persistence(self) -> None:
        events = _five_events()
        # RTX appears in {run_01, run_02, run_03} = 3 unique runs
        # Total unique runs across all events = {run_01, run_02, run_03} = 3
        assert score_persistence("RTX", events) == 1.0

    def test_partial_persistence_with_total(self) -> None:
        events = _five_events()
        assert score_persistence("RTX", events, total_run_count=10) == 0.3

    def test_missing_ticker_returns_zero(self) -> None:
        assert score_persistence("NOSUCHSTOCK", _five_events()) == 0.0

    def test_empty_events_returns_zero(self) -> None:
        assert score_persistence("RTX", []) == 0.0


class TestBlockerPressureScore:
    def test_rtx_partial_block(self) -> None:
        # RTX: 2/3 appearances blocked (run_01, run_02 have GSCE_PHASE_LOCK; run_03 NONE)
        bp = score_blocker_pressure("RTX", _five_events())
        assert abs(bp - 2 / 3) < 0.001

    def test_zim_half_blocked(self) -> None:
        # ZIM: run_01 REALM_BIS (blocked), run_02 NONE (not blocked) → 0.5
        bp = score_blocker_pressure("ZIM", _five_events())
        assert bp == 0.5

    def test_missing_ticker_returns_zero(self) -> None:
        assert score_blocker_pressure("NOSUCHSTOCK", []) == 0.0

    def test_none_blocker_not_counted(self, scratch_path: Path) -> None:
        events = [_make_event("GLD", blocker="NONE")]
        assert score_blocker_pressure("GLD", events) == 0.0


class TestKillRateScore:
    def test_zim_half_killed(self) -> None:
        # ZIM: 1 REJECTED out of 2 events → 0.5
        assert score_kill_rate("ZIM", _five_events()) == 0.5

    def test_rtx_not_killed(self) -> None:
        assert score_kill_rate("RTX", _five_events()) == 0.0

    def test_missing_ticker_returns_zero(self) -> None:
        assert score_kill_rate("NONE", []) == 0.0

    def test_fully_killed(self) -> None:
        events = [
            _make_event("TLT", signal_state="REJECTED", source_run_id="r1"),
            _make_event("TLT", signal_state="REJECTED", source_run_id="r2"),
        ]
        assert score_kill_rate("TLT", events) == 1.0


class TestAttachScores:
    def test_does_not_mutate_input(self) -> None:
        events = _five_events()
        original = [(e.persistence_score, e.blocker_pressure_score) for e in events]
        attach_scores(events)
        for i, e in enumerate(events):
            assert e.persistence_score == original[i][0]
            assert e.blocker_pressure_score == original[i][1]

    def test_output_scores_in_range(self) -> None:
        for e in attach_scores(_five_events()):
            assert 0.0 <= e.persistence_score <= 1.0
            assert 0.0 <= e.blocker_pressure_score <= 1.0
            assert 0.0 <= e.kill_rate_score <= 1.0

    def test_output_length_matches_input(self) -> None:
        events = _five_events()
        assert len(attach_scores(events)) == len(events)


# ---------------------------------------------------------------------------
# Bull-state classifier
# ---------------------------------------------------------------------------


class TestBullStateClassifier:
    def test_insufficient_history_returns_unknown(self) -> None:
        result = classify_fabric_bull_state([_make_snapshot("r1")])
        assert result["fabric_bull_state"] == "UNKNOWN"

    def test_dormant_state(self) -> None:
        snaps = [
            _make_snapshot(
                f"r{i}", scm_rate=0.28, allow_new_risk=False,
                clean_entries=0, chaos_entries=0, promotable_watchlist_count=0,
            )
            for i in range(5)
        ]
        assert classify_fabric_bull_state(snaps)["fabric_bull_state"] == "DORMANT"

    def test_active_state(self) -> None:
        snaps = [
            _make_snapshot(
                f"r{i}", scm_rate=0.7, allow_new_risk=True,
                clean_entries=4, chaos_entries=1,
                blockers_active=[], promotable_watchlist_count=2,
            )
            for i in range(3)
        ]
        assert classify_fabric_bull_state(snaps)["fabric_bull_state"] == "ACTIVE"

    def test_overextended_state(self) -> None:
        snaps = [
            _make_snapshot(
                f"r{i}", scm_rate=0.4, allow_new_risk=False,
                clean_entries=1, chaos_entries=5,
                blockers_active=["REALM_BIS"],
            )
            for i in range(3)
        ]
        assert classify_fabric_bull_state(snaps)["fabric_bull_state"] == "OVEREXTENDED"

    def test_emerging_via_promotable(self) -> None:
        snaps = [
            _make_snapshot(
                f"r{i}", scm_rate=0.3, allow_new_risk=False,
                clean_entries=0, chaos_entries=0, promotable_watchlist_count=3,
            )
            for i in range(3)
        ]
        assert classify_fabric_bull_state(snaps)["fabric_bull_state"] == "EMERGING"

    def test_emerging_via_scm_trend(self) -> None:
        snaps = [
            _make_snapshot("r1", scm_rate=0.20, allow_new_risk=False,
                           clean_entries=0, chaos_entries=0, promotable_watchlist_count=0),
            _make_snapshot("r2", scm_rate=0.30, allow_new_risk=False,
                           clean_entries=0, chaos_entries=0, promotable_watchlist_count=0),
            _make_snapshot("r3", scm_rate=0.40, allow_new_risk=False,
                           clean_entries=0, chaos_entries=0, promotable_watchlist_count=0),
        ]
        assert classify_fabric_bull_state(snaps)["fabric_bull_state"] == "EMERGING"

    def test_classifier_from_seed_returns_valid_state(self) -> None:
        rows = load_snapshot_rows(SEED_SNAPSHOTS)
        result = classify_fabric_bull_state(rows)
        valid_states = {"DORMANT", "EMERGING", "ACTIVE", "OVEREXTENDED", "UNKNOWN"}
        assert result["fabric_bull_state"] in valid_states
        assert "advisory_note" in result
        assert "rationale" in result

    def test_classifier_window_capped_at_five(self) -> None:
        snaps = [_make_snapshot(f"r{i}", allow_new_risk=True, clean_entries=3)
                 for i in range(10)]
        result = classify_fabric_bull_state(snaps)
        assert result["window_run_count"] <= 5

    def test_avg_scm_rate_is_float(self) -> None:
        snaps = [_make_snapshot(f"r{i}") for i in range(3)]
        result = classify_fabric_bull_state(snaps)
        assert isinstance(result["avg_scm_rate"], float)


# ---------------------------------------------------------------------------
# Full report builder
# ---------------------------------------------------------------------------


class TestReportBuilder:
    def test_report_shape_from_seed(self) -> None:
        report = build_global_signal_fabric_report(
            snapshot_path=SEED_SNAPSHOTS, write_runtime=False
        )
        required_keys = {
            "report_name", "schema_version", "advisory_status",
            "human_review_required", "execution_gate", "advisory_note",
            "fabric_bull_state_context", "fabric_stats", "ticker_summaries",
            "source_files", "generated_at",
        }
        assert required_keys.issubset(set(report.keys()))

    def test_report_name(self) -> None:
        report = build_global_signal_fabric_report(
            snapshot_path=SEED_SNAPSHOTS, write_runtime=False
        )
        assert report["report_name"] == "global_signal_fabric_report"

    def test_fabric_stats_non_negative_ints(self) -> None:
        report = build_global_signal_fabric_report(
            snapshot_path=SEED_SNAPSHOTS, write_runtime=False
        )
        for key, value in report["fabric_stats"].items():
            assert isinstance(value, int) and value >= 0, (
                f"fabric_stats[{key!r}]={value!r} must be a non-negative int"
            )

    def test_writes_file_with_coherence_stamp(self, scratch_path: Path) -> None:
        out = scratch_path / "fabric_report.json"
        build_global_signal_fabric_report(
            snapshot_path=SEED_SNAPSHOTS,
            write_runtime=True,
            output_path=out,
        )
        assert out.exists()
        written = json.loads(out.read_text(encoding="utf-8"))
        assert written["advisory_status"] == "ADVISORY_ONLY"
        assert "run_id" in written       # coherence stamp
        assert "source_mode" in written  # coherence stamp

    def test_empty_sources_returns_safe_report(self, scratch_path: Path) -> None:
        empty_snap = scratch_path / "empty.jsonl"
        empty_snap.write_text("", encoding="utf-8")
        empty_attr = scratch_path / "empty_attr.json"
        empty_attr.write_text("{}", encoding="utf-8")
        empty_kill = scratch_path / "empty_kill.jsonl"
        empty_kill.write_text("", encoding="utf-8")

        report = build_global_signal_fabric_report(
            snapshot_path=empty_snap,
            attribution_path=empty_attr,
            kill_log_path=empty_kill,
            write_runtime=False,
        )
        assert report["advisory_status"] == "ADVISORY_ONLY"
        assert report["fabric_stats"]["total_signal_events"] == 0
        assert report["fabric_bull_state_context"]["fabric_bull_state"] == "UNKNOWN"

    def test_missing_sources_returns_safe_report(self, scratch_path: Path) -> None:
        report = build_global_signal_fabric_report(
            snapshot_path=scratch_path / "nope.jsonl",
            attribution_path=scratch_path / "nope.json",
            kill_log_path=scratch_path / "nope_kill.jsonl",
            write_runtime=False,
        )
        assert report["advisory_status"] == "ADVISORY_ONLY"
        assert report["execution_gate"] == "LOCKED"
        assert report["human_review_required"] is True

    def test_ticker_summaries_present_for_seed_tickers(self) -> None:
        report = build_global_signal_fabric_report(
            snapshot_path=SEED_SNAPSHOTS, write_runtime=False
        )
        observed = {s["ticker"] for s in report["ticker_summaries"]}
        # Seed snapshots contain RTX and ZIM in transition_state_rows
        assert "RTX" in observed
        assert "ZIM" in observed

    def test_ticker_summary_scores_in_range(self) -> None:
        report = build_global_signal_fabric_report(
            snapshot_path=SEED_SNAPSHOTS, write_runtime=False
        )
        for summary in report["ticker_summaries"]:
            assert 0.0 <= summary["persistence_score"] <= 1.0
            assert 0.0 <= summary["blocker_pressure_score"] <= 1.0
            assert 0.0 <= summary["kill_rate_score"] <= 1.0
