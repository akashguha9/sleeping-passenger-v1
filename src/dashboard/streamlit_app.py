"""Streamlit dashboard for the read-only signal refinery MVP.

U3 fix (PARTIAL): Streamlit has no built-in auth; the only safe deployment
is loopback-only.  ``render_dashboard`` now enforces that posture: it
refuses to render when Streamlit's listen address is non-loopback unless
``MVP_DASHBOARD_ALLOW_NONLOOPBACK=1`` is set (the same explicit-override
pattern S1 uses for the API).  Reads carry no PII beyond what's already
in the SQLite store, but operator reflections / mistake tags are part of
that store, so the refusal matters.
"""

from __future__ import annotations

import os
from pathlib import Path

try:  # pragma: no cover - optional dependency path
    import streamlit as st
except Exception:  # pragma: no cover - optional dependency path
    st = None

from src.storage.sqlite_store import DEFAULT_DB_PATH, SQLiteStore

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _dashboard_bind_is_loopback() -> bool:
    """Inspect Streamlit's server address (or override) to decide if we
    are bound to loopback only."""
    host = os.environ.get("STREAMLIT_SERVER_ADDRESS", "").strip().lower()
    if not host:
        # Streamlit defaults to localhost when STREAMLIT_SERVER_ADDRESS is
        # unset.  Treat that as loopback.
        return True
    return host in _LOOPBACK_HOSTS


def _dashboard_unauth_override() -> bool:
    return os.environ.get("MVP_DASHBOARD_ALLOW_NONLOOPBACK", "").strip() in (
        "1",
        "true",
        "yes",
    )


def render_dashboard(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Render the Streamlit dashboard if Streamlit is available."""
    if st is None:
        raise RuntimeError("Streamlit is not installed. Dashboard rendering is optional.")
    if not _dashboard_bind_is_loopback() and not _dashboard_unauth_override():
        st.error(
            "Refusing to render: Streamlit dashboard is bound to a non-"
            "loopback address but MVP_DASHBOARD_ALLOW_NONLOOPBACK is not "
            "set.  This dashboard has no auth; expose it only to "
            "localhost.  Set STREAMLIT_SERVER_ADDRESS=127.0.0.1 (or the "
            "explicit override env var)."
        )
        return
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
    from src.dashboard.alpha_framework_view import render_alpha_framework_section

    render_alpha_framework_section(st)
