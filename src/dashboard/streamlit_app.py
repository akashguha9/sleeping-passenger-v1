"""Streamlit dashboard for the read-only signal refinery MVP."""

from __future__ import annotations

from pathlib import Path

try:  # pragma: no cover - optional dependency path
    import streamlit as st
except Exception:  # pragma: no cover - optional dependency path
    st = None

from src.storage.sqlite_store import DEFAULT_DB_PATH, SQLiteStore


def render_dashboard(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Render the Streamlit dashboard if Streamlit is available."""
    if st is None:
        raise RuntimeError("Streamlit is not installed. Dashboard rendering is optional.")
    store = SQLiteStore(db_path)
    snapshots = store.read_latest_market_snapshots()
    scores = store.read_latest_signal_scores()
    clusters = store.read_attention_clusters()
    trades = store.read_paper_trades()
    st.title("Geopolitical / Narrative / Prediction-Market Signal Refinery MVP")
    st.caption("Read-only public-data scoring and paper-trading dashboard.")
    st.subheader("Overview")
    st.write(
        {
            "total_markets_ingested": len(snapshots),
            "ignored_count": sum(1 for row in scores if row.get("state") == "IGNORE"),
            "watch_count": sum(1 for row in scores if row.get("state") == "WATCH"),
            "validate_count": sum(1 for row in scores if row.get("state") == "VALIDATE"),
            "paper_trade_count": sum(1 for row in scores if row.get("state") == "PAPER_TRADE"),
        }
    )
    st.subheader("Signal Table")
    st.dataframe(scores)
    st.subheader("Rejection Log")
    st.dataframe([row for row in scores if row.get("state") == "IGNORE"])
    st.subheader("Attention Clusters")
    st.dataframe(clusters)
    st.subheader("Paper Trades")
    st.dataframe(trades)
    st.subheader("System Health")
    st.write({"database_path": str(Path(db_path)), "threshold_config_loaded": True})
