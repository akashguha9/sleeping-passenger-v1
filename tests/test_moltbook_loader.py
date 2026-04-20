import json
import subprocess
import sys
from pathlib import Path

from scripts.moltbook_loader import summarize_moltbook
from scripts.signal_conversion_monitor import load_signal_ledger


def test_moltbook_loader_summary_smoke() -> None:
    summary = summarize_moltbook(Path(__file__).resolve().parents[1] / "moltbook")

    assert summary["trade_close_count"] == 4
    assert summary["mw_signal_count"] == 1
    assert summary["tickers"] == ["FCG", "TIP", "TLT", "UNG"]
    assert summary["classifications"] == ["CHAOS_LOSS", "GOOD_WIN", "MARGINAL_WIN"]
    assert summary["mw_signal_ids"] == ["MW_DIRECTION_V1_2026_04_19"]


def test_signal_conversion_monitor_runtime_report_uses_live_files() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "scripts\\signal_conversion_monitor.py"],
        cwd=repo_root,
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
        "watchlist_action": "DO_NOT_FORCE_ENTRY",
        "required_clearance_gates": ["GSCE_PHASE_LOCK", "REALM_BIS"],
        "blocked_entry_states": ["EXECUTED_CHAOS"],
        "next_priority_action": "CLEAR_BLOCKERS_BEFORE_NEW_RISK",
        "rationale": [
            "2 clean entries across 7 above-threshold signals",
            "SCM rate remains below PARTIAL_CONVERSION threshold",
            "3 above-threshold signals remained WATCHLIST",
            "2 above-threshold signals converted into CHAOS entries",
        ],
    }


def test_signal_ledger_rejects_unknown_status() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    scratch_dir = repo_root / "tests" / "_tmp_runtime"
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
