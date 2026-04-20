import json
import subprocess
import sys
from pathlib import Path

from scripts.moltbook_loader import summarize_moltbook


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
    }
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
