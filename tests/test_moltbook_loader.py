from pathlib import Path

from scripts.moltbook_loader import summarize_moltbook


def test_moltbook_loader_summary_smoke() -> None:
    summary = summarize_moltbook(Path(__file__).resolve().parents[1] / "moltbook")

    assert summary["trade_close_count"] == 4
    assert summary["mw_signal_count"] == 1
    assert summary["tickers"] == ["FCG", "TIP", "TLT", "UNG"]
    assert summary["classifications"] == ["CHAOS_LOSS", "GOOD_WIN", "MARGINAL_WIN"]
    assert summary["mw_signal_ids"] == ["MW_DIRECTION_V1_2026_04_19"]
