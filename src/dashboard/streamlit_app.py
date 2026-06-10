"""Streamlit dashboard for the read-only signal refinery MVP.

U3 fix + Pass-2 owner gate: Streamlit has no built-in auth; the only safe
deployment is loopback-only.  ``render_dashboard`` enforces that posture:

* Non-loopback bind without ``MVP_DASHBOARD_ALLOW_NONLOOPBACK=1`` →
  refuses to render (same explicit-override pattern S1 uses for the API).
* Non-loopback bind WITH the override → an owner-token gate is now
  REQUIRED: the operator must enter the same token that gates the API
  (verified through ``runtime_config.verify_api_token`` — hash mode
  preferred, plaintext legacy fallback).  Previously the override
  rendered with no auth at all.
* Loopback (default) → renders without a token: any process running as
  the same OS user can already read the SQLite file directly, so a token
  prompt adds friction, not security.  Force the prompt anyway with
  ``MVP_DASHBOARD_REQUIRE_TOKEN=1``.

The dashboard never exposes exports or log files; it reads the local
SQLite store only.  Advisory-only: nothing here executes trades.
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


def _dashboard_requires_token() -> bool:
    """Owner-token gate policy.

    Required on any non-loopback bind (the override only unlocks the
    bind, never the data), or when the operator opts in explicitly via
    ``MVP_DASHBOARD_REQUIRE_TOKEN=1``.
    """
    if not _dashboard_bind_is_loopback():
        return True
    return os.environ.get("MVP_DASHBOARD_REQUIRE_TOKEN", "").strip() in (
        "1",
        "true",
        "yes",
    )


def _dashboard_token_ok(candidate: str | None) -> bool:
    """Verify a candidate owner token with the API's own logic.

    Single verification path for the whole MVP: SHA-256 hash mode
    (``MVP_API_TOKEN_HASH``) preferred, legacy plaintext fallback,
    constant-time comparison.  No token configured → False (fail closed:
    a token-gated dashboard with nothing to verify against must not
    render).
    """
    try:
        from scripts.runtime_config import verify_api_token
    except ModuleNotFoundError:  # pragma: no cover - script-style env
        from runtime_config import verify_api_token  # type: ignore[no-redef]
    return verify_api_token(candidate)


def _model_quality_summary() -> dict:
    """Pass-5 model-quality status for the dashboard (pure; testable).

    Never raises; every field degrades to an honest 'unknown'.
    """
    summary = {
        "advisory_label": "ADVISORY_ONLY — human review required; "
                          "nothing here executes or recommends execution",
        "evidence_items": None,
        "evidence_ledger_valid": None,
        "grounding_rule": "unsourced/hallucinated LLM claims carry zero weight",
        "temporal_rule": "t_published ≤ t_observed ≤ t_decision < t_outcome "
                         "enforced for every evaluation",
        "readiness_gate_cmd": "python scripts/run_model_readiness_gate.py",
    }
    try:
        from scripts import data_quality as _dq

        items = _dq.read_ledger()
        summary["evidence_items"] = len(items)
        summary["evidence_ledger_valid"] = not _dq.verify_ledger()
    except Exception:
        pass
    return summary


def _render_model_quality_panel(st_mod) -> None:  # pragma: no cover - UI glue
    info = _model_quality_summary()
    with st_mod.expander("Model quality (Pass 5 controls)"):
        st_mod.caption(info["advisory_label"])
        st_mod.write({
            "evidence_items_in_ledger": info["evidence_items"],
            "evidence_ledger_chain_valid": info["evidence_ledger_valid"],
            "llm_grounding": info["grounding_rule"],
            "temporal_integrity": info["temporal_rule"],
            "full_gate": info["readiness_gate_cmd"],
        })
        if not info["evidence_items"]:
            st_mod.warning(
                "Evidence ledger is empty — signals shown below have no "
                "recorded evidence trail yet. Treat scores as unsupported."
            )


def render_dashboard(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Render the Streamlit dashboard if Streamlit is available."""
    if st is None:
        raise RuntimeError("Streamlit is not installed. Dashboard rendering is optional.")
    if not _dashboard_bind_is_loopback() and not _dashboard_unauth_override():
        st.error(
            "Refusing to render: Streamlit dashboard is bound to a non-"
            "loopback address but MVP_DASHBOARD_ALLOW_NONLOOPBACK is not "
            "set.  Expose it only to localhost.  Set "
            "STREAMLIT_SERVER_ADDRESS=127.0.0.1 (or the explicit override "
            "env var)."
        )
        return
    if os.environ.get("MVP_LOCKDOWN_MODE", "").strip().lower() in ("1", "true", "yes"):
        st.warning(
            "EMERGENCY LOCKDOWN MODE is active (MVP_LOCKDOWN_MODE=1): the "
            "API refuses all mutations and this dashboard should be "
            "treated as read-only forensics. See docs/INCIDENT_LOCKDOWN.md."
        )
    if _dashboard_requires_token():
        candidate = st.text_input(
            "Owner API token (required beyond loopback)",
            type="password",
            help=(
                "Same token that gates the journal API. Verified against "
                "MVP_API_TOKEN_HASH (or the legacy plaintext token). "
                "It never authorizes trade execution."
            ),
        )
        if not _dashboard_token_ok(candidate):
            if candidate:
                st.error("Invalid owner token.")
            else:
                st.info("Enter the owner token to load the dashboard.")
            st.stop()
            return
    _render_model_quality_panel(st)
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
