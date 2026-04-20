import json
import subprocess
import sys
from pathlib import Path

from scripts.market_data_adapter import describe_market_data_adapter
from scripts.pipeline_health_report import build_pipeline_health_report
from scripts.moltbook_loader import summarize_moltbook
from scripts.signal_conversion_monitor import load_signal_ledger

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_moltbook_loader_summary_smoke() -> None:
    summary = summarize_moltbook(REPO_ROOT / "moltbook")

    assert summary["trade_close_count"] == 4
    assert summary["mw_signal_count"] == 1
    assert summary["tickers"] == ["FCG", "TIP", "TLT", "UNG"]
    assert summary["classifications"] == ["CHAOS_LOSS", "GOOD_WIN", "MARGINAL_WIN"]
    assert summary["mw_signal_ids"] == ["MW_DIRECTION_V1_2026_04_19"]


def test_signal_conversion_monitor_runtime_report_uses_live_files() -> None:
    result = subprocess.run(
        [sys.executable, "scripts\\signal_conversion_monitor.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)

    assert payload["moltbook_summary"] == {
        "trade_close_count": 4,
        "mw_signal_count": 1,
        "clean_entries": 2,
        "chaos_entries": 2,
        "tickers": ["FCG", "TIP", "TLT", "UNG"],
    }
    assert payload["signal_summary"] == {
        "signal_count_total": 8,
        "signals_above_ce_threshold": 7,
        "qualifying_signal_ids": [
            "SIG_2026_04_01_001",
            "SIG_2026_04_02_002",
            "SIG_2026_04_03_003",
            "SIG_2026_04_04_004",
            "SIG_2026_04_05_005",
            "SIG_2026_04_06_006",
            "SIG_2026_04_07_007",
        ],
        "status_counts_above_threshold": {
            "EXECUTED_CLEAN": 2,
            "EXECUTED_CHAOS": 2,
            "WATCHLIST": 3,
        },
        "qualifying_signals": [
            {"signal_id": "SIG_2026_04_01_001", "ticker": "TLT", "ce_score": 0.62, "status": "EXECUTED_CLEAN"},
            {"signal_id": "SIG_2026_04_02_002", "ticker": "TIP", "ce_score": 0.68, "status": "EXECUTED_CLEAN"},
            {"signal_id": "SIG_2026_04_03_003", "ticker": "UNG", "ce_score": 0.35, "status": "EXECUTED_CHAOS"},
            {"signal_id": "SIG_2026_04_04_004", "ticker": "FCG", "ce_score": 0.30, "status": "EXECUTED_CHAOS"},
            {"signal_id": "SIG_2026_04_05_005", "ticker": "GLD", "ce_score": 0.60, "status": "WATCHLIST"},
            {"signal_id": "SIG_2026_04_06_006", "ticker": "RTX", "ce_score": 0.71, "status": "WATCHLIST"},
            {"signal_id": "SIG_2026_04_07_007", "ticker": "ZIM", "ce_score": 0.66, "status": "WATCHLIST"},
        ],
    }
    assert payload["per_signal_attribution"] == [
        {
            "signal_id": "SIG_2026_04_01_001",
            "ticker": "TLT",
            "ce_score": 0.62,
            "status": "EXECUTED_CLEAN",
            "conversion_state": "CLEAN_ENTRY",
            "blocker_attribution": "NONE",
        },
        {
            "signal_id": "SIG_2026_04_02_002",
            "ticker": "TIP",
            "ce_score": 0.68,
            "status": "EXECUTED_CLEAN",
            "conversion_state": "CLEAN_ENTRY",
            "blocker_attribution": "NONE",
        },
        {
            "signal_id": "SIG_2026_04_03_003",
            "ticker": "UNG",
            "ce_score": 0.35,
            "status": "EXECUTED_CHAOS",
            "conversion_state": "CHAOS_ENTRY",
            "blocker_attribution": "REALM_BIS",
        },
        {
            "signal_id": "SIG_2026_04_04_004",
            "ticker": "FCG",
            "ce_score": 0.3,
            "status": "EXECUTED_CHAOS",
            "conversion_state": "CHAOS_ENTRY",
            "blocker_attribution": "REALM_BIS",
        },
        {
            "signal_id": "SIG_2026_04_05_005",
            "ticker": "GLD",
            "ce_score": 0.6,
            "status": "WATCHLIST",
            "conversion_state": "NOT_EXECUTED",
            "blocker_attribution": "GSCE_PHASE_LOCK",
        },
        {
            "signal_id": "SIG_2026_04_06_006",
            "ticker": "RTX",
            "ce_score": 0.71,
            "status": "WATCHLIST",
            "conversion_state": "NOT_EXECUTED",
            "blocker_attribution": "GSCE_PHASE_LOCK",
        },
        {
            "signal_id": "SIG_2026_04_07_007",
            "ticker": "ZIM",
            "ce_score": 0.66,
            "status": "WATCHLIST",
            "conversion_state": "NOT_EXECUTED",
            "blocker_attribution": "GSCE_PHASE_LOCK",
        },
    ]
    assert payload["derived_gate_states"] == {
        "GSCE_PHASE_LOCK": True,
        "CEE_OVERLOAD": False,
        "MTL_TIMING": False,
        "NAR_ARCHETYPE": False,
        "TAT_PRESSURE_STATE": False,
        "REALM_BIS": True,
    }
    assert payload["scm_review"] == {
        "scm_rate": 0.286,
        "scm_state": "LOW_CONVERSION",
        "diagnosis": ["GSCE_PHASE_LOCK", "REALM_BIS"],
        "gap_type": "CONVERSION_FRICTION",
    }
    assert payload["execution_policy"] == {
        "policy_state": "RESTRICTED",
        "position_sizing_cap": "QUARTER_UNIT",
        "allow_clean_entries": False,
        "allow_chaos_entries": False,
        "allow_new_risk": False,
        "allow_only_exits_and_reductions": True,
        "retain_watchlist_names": True,
        "chaos_entries_forbidden": True,
        "watchlist_action": "DO_NOT_FORCE_ENTRY",
        "required_clearance_gates": ["GSCE_PHASE_LOCK", "REALM_BIS"],
        "blocked_entry_states": ["EXECUTED_CHAOS"],
        "next_priority_action": "CLEAR_BLOCKERS_BEFORE_NEW_RISK",
        "minimum_conditions_to_improve": [
            "SCM state improves to PARTIAL_CONVERSION or better",
            "GSCE_PHASE_LOCK clears for above-threshold WATCHLIST names",
            "REALM_BIS clears by eliminating chaos conversions",
        ],
        "rationale": [
            "2 clean entries across 7 above-threshold signals",
            "SCM rate remains below PARTIAL_CONVERSION threshold",
            "3 above-threshold signals remained WATCHLIST",
            "2 above-threshold signals converted into CHAOS entries",
        ],
    }


def test_signal_ledger_rejects_unknown_status() -> None:
    scratch_dir = REPO_ROOT / "tests" / "_tmp_runtime"
    ledger_path = scratch_dir / "signal_ledger_invalid_status.json"

    scratch_dir.mkdir(exist_ok=True)
    ledger_path.write_text(
        json.dumps(
            [
                {
                    "signal_id": "SIG_BAD_001",
                    "ticker": "BAD",
                    "ce_score": 0.61,
                    "above_ce_threshold": True,
                    "status": "UNKNOWN_STATUS",
                }
            ]
        ),
        encoding="utf-8",
    )

    try:
        load_signal_ledger(ledger_path)
    except ValueError as exc:
        assert "status must be one of" in str(exc)
    else:
        raise AssertionError("Expected load_signal_ledger to reject unknown status")
    finally:
        if ledger_path.exists():
            ledger_path.unlink()
        if scratch_dir.exists() and not any(scratch_dir.iterdir()):
            scratch_dir.rmdir()


def test_moltbook_loader_summary_cli() -> None:
    result = subprocess.run(
        [sys.executable, "scripts\\moltbook_loader.py", "--summary"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip().splitlines() == [
        "Moltbook Summary",
        "trade_close_count=4",
        "mw_signal_count=1",
        "tickers=FCG, TIP, TLT, UNG",
        "classifications=CHAOS_LOSS, GOOD_WIN, MARGINAL_WIN",
        "mw_signal_ids=MW_DIRECTION_V1_2026_04_19",
    ]


def test_signal_conversion_monitor_summary_cli() -> None:
    result = subprocess.run(
        [sys.executable, "scripts\\signal_conversion_monitor.py", "--summary"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip().splitlines() == [
        "Signal Conversion Monitor",
        "scm_state=LOW_CONVERSION",
        "scm_rate=0.286",
        "clean_entries=2",
        "chaos_entries=2",
        "watchlist_non_conversions=3",
        "active_gates=GSCE_PHASE_LOCK, REALM_BIS",
        "policy_state=RESTRICTED",
        "allow_new_risk=false",
        "next_priority_action=CLEAR_BLOCKERS_BEFORE_NEW_RISK",
    ]


def test_market_data_adapter_placeholder_contract() -> None:
    description = describe_market_data_adapter("yahoo")

    assert description == {
        "requested_provider": "yahoo",
        "resolved_provider": "yahoo_placeholder",
        "live_quotes_available": False,
        "contract_sample": {
            "requested_provider": "yahoo",
            "resolved_provider": "yahoo_placeholder",
            "symbol": "TLT",
            "ok": False,
            "quote": None,
            "error": "yahoo adapter not wired; returning placeholder contract only.",
            "retriable": True,
        },
        "note": "Placeholder adapter only. Core Moltbook and SCM runtime remain independent from market-data ingestion.",
    }


def test_pipeline_health_report_builder_shape() -> None:
    payload = build_pipeline_health_report(include_tests=False)

    assert payload["git_status"]["available"] is True
    assert isinstance(payload["git_status"]["head"], str) and payload["git_status"]["head"]
    assert payload["test_status"] == {
        "invoked": False,
        "command": [
            sys.executable,
            "-m",
            "pytest",
            "tests\\test_moltbook_schema.py",
            "tests\\test_moltbook_loader.py",
            "-q",
        ],
        "exit_code": None,
        "passed": None,
        "summary_line": None,
    }
    assert payload["moltbook_summary"]["trade_close_count"] == 4
    assert payload["signal_summary"]["signals_above_ce_threshold"] == 7
    assert payload["scm_review"]["scm_state"] == "LOW_CONVERSION"
    assert payload["execution_policy"]["policy_state"] == "RESTRICTED"
    assert payload["market_data_adapter"]["resolved_provider"] == "yahoo_placeholder"
    assert payload["scorecard"] == {
        "logging_quality": {"score": 10, "max_score": 10},
        "schema_reliability": {"score": 8, "max_score": 10},
        "end_to_end_wiring": {"score": 10, "max_score": 10},
        "self_correction_maturity": {"score": 10, "max_score": 10},
        "execution_readiness": {"score": 6, "max_score": 10},
    }
    assert "logging_quality" in payload["scorecard_rules"]


def test_pipeline_health_report_cli_json_shape() -> None:
    result = subprocess.run(
        [sys.executable, "scripts\\pipeline_health_report.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["moltbook_summary"]["trade_close_count"] == 4
    assert payload["signal_summary"]["signals_above_ce_threshold"] == 7
    assert payload["scm_review"]["scm_rate"] == 0.286
    assert payload["execution_policy"]["next_priority_action"] == "CLEAR_BLOCKERS_BEFORE_NEW_RISK"


def test_pipeline_health_report_summary_cli() -> None:
    result = subprocess.run(
        [sys.executable, "scripts\\pipeline_health_report.py", "--summary"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    output = result.stdout.strip().splitlines()
    assert output[0] == "Pipeline Health Report"
    assert "scm_state=LOW_CONVERSION" in output
    assert "policy_state=RESTRICTED" in output
