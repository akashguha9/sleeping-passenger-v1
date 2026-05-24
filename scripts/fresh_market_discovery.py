"""Layer 2 — Fresh Market Discovery Gate.

The system must produce fresh candidates EVEN WHEN execution is blocked. A
phantom holding, dirty hygiene, or missing live data may downgrade a name to
WATCHLIST / NOT_EXECUTABLE, but it must never erase the name from discovery.

This module builds the candidate universe and scores each ticker with a
null-safe Candidate Quality Score (CQS). Unknown data is never fabricated —
it lowers data_quality and routes the ticker to WATCHLIST rather than deleting
it.

    U = price_movers ∪ news ∪ filings ∪ yesterday_final_candidates
        ∪ yesterday_watchlist ∪ old_signal_ledger_watchlist ∪ model_names

    CQS(t) = 0.20*S + 0.15*N + 0.15*P + 0.10*M + 0.10*LQ
             + 0.10*F + 0.10*DQ - 0.05*K - 0.05*CR
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.daily_discovery_config import load_discovery_thresholds
    from scripts.daily_payload import load_daily_payload, normalize_ticker
    from scripts.minimum_daily_universe import minimum_universe_tickers
    from scripts.portfolio_truth_gate import build_portfolio_truth_gate, classify_ticker
    from scripts.runtime_common import SIGNAL_LEDGER_PATH, load_json_file
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from daily_discovery_config import load_discovery_thresholds
    from daily_payload import load_daily_payload, normalize_ticker
    from minimum_daily_universe import minimum_universe_tickers
    from portfolio_truth_gate import build_portfolio_truth_gate, classify_ticker
    from runtime_common import SIGNAL_LEDGER_PATH, load_json_file


CQS_WEIGHTS = {
    "signal_strength": 0.20,
    "narrative_velocity": 0.15,
    "price_momentum": 0.15,
    "filing_materiality": 0.10,
    "liquidity_quality": 0.10,
    "freshness": 0.10,
    "data_quality": 0.10,
}
CQS_PENALTIES = {"chaos_risk": 0.05, "crowding_risk": 0.05}

# Positive scoring fields whose presence informs an inferred data_quality.
_EVIDENCE_FIELDS = (
    "signal_strength",
    "narrative_velocity",
    "price_momentum",
    "filing_materiality",
    "liquidity_quality",
    "freshness",
)


def _clamp01(value: Any) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0.0
    if num < 0.0:
        return 0.0
    if num > 1.0:
        return 1.0
    return num


def _inferred_data_quality(features: dict[str, Any]) -> float:
    """When data_quality is not supplied, infer it from evidence coverage.

    Unknown evidence lowers DQ rather than being silently treated as strong.
    """
    known = sum(1 for key in _EVIDENCE_FIELDS if features.get(key) is not None)
    return round(known / len(_EVIDENCE_FIELDS), 4)


def score_candidate(ticker: str, features: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the CQS and component breakdown for one ticker (null-safe)."""
    features = dict(features or {})
    components: dict[str, float] = {}
    known_flags: dict[str, bool] = {}
    for field in CQS_WEIGHTS:
        if field == "data_quality":
            continue
        raw = features.get(field)
        known_flags[field] = raw is not None
        components[field] = _clamp01(raw)

    if features.get("data_quality") is not None:
        data_quality = _clamp01(features.get("data_quality"))
    else:
        data_quality = _inferred_data_quality(features)
    components["data_quality"] = data_quality
    known_flags["data_quality"] = features.get("data_quality") is not None

    chaos_risk = _clamp01(features.get("chaos_risk"))
    crowding_risk = _clamp01(features.get("crowding_risk"))

    cqs = sum(CQS_WEIGHTS[field] * components[field] for field in CQS_WEIGHTS)
    cqs -= CQS_PENALTIES["chaos_risk"] * chaos_risk
    cqs -= CQS_PENALTIES["crowding_risk"] * crowding_risk
    cqs = round(max(0.0, min(1.0, cqs)), 4)

    return {
        "ticker": normalize_ticker(ticker),
        "cqs": cqs,
        "components": components,
        "chaos_risk": chaos_risk,
        "crowding_risk": crowding_risk,
        "portfolio_contamination_penalty": _clamp01(features.get("portfolio_contamination_penalty")),
        "known_fields": [f for f, ok in known_flags.items() if ok],
        "unknown_fields": [f for f, ok in known_flags.items() if not ok],
        "data_quality": data_quality,
    }


def _signal_ledger_watchlist(signal_ledger_path: Path | None = None) -> list[str]:
    payload = load_json_file(signal_ledger_path or SIGNAL_LEDGER_PATH, default=[])
    out: list[str] = []
    if isinstance(payload, list):
        for row in payload:
            if not isinstance(row, dict):
                continue
            if str(row.get("status") or "").strip().upper() == "WATCHLIST":
                ticker = normalize_ticker(row.get("ticker") or row.get("symbol"))
                if ticker and ticker not in out:
                    out.append(ticker)
    return out


def build_discovery_universe(
    payload: dict[str, Any],
    model_candidates: list[str] | None = None,
    signal_ledger_path: Path | None = None,
    include_static_universe: bool = True,
) -> list[str]:
    """Ordered union U_today of all discovery sources.

        U_today = U_static ∪ U_price ∪ U_news ∪ U_filings
                  ∪ U_yesterday ∪ U_old ∪ U_model

    ``U_static`` is the minimum viable fresh universe — it guarantees the
    discovery gate is never starved even when no live feed is wired. Universe
    membership NEVER implies portfolio ownership (that comes only from the
    Portfolio Truth Gate).
    """
    universe: list[str] = []

    def add(tickers: list[str]) -> None:
        for ticker in tickers:
            norm = normalize_ticker(ticker)
            if norm and norm not in universe:
                universe.append(norm)

    if include_static_universe:
        add(minimum_universe_tickers())
    add(payload["price_movers"]["tickers"])
    add(payload["news_events"]["tickers"])
    add(payload["filings_events"]["tickers"])
    add(payload["yesterday_candidates"]["final_candidates"])
    add(payload["yesterday_candidates"]["watchlist"])
    add(_signal_ledger_watchlist(signal_ledger_path))
    add([normalize_ticker(t) for t in (model_candidates or [])])
    return universe


def build_fresh_market_discovery(
    payload: dict[str, Any] | None = None,
    payload_dir: Path | None = None,
    truth_gate: dict[str, Any] | None = None,
    model_candidates: list[str] | None = None,
    features: dict[str, dict[str, Any]] | None = None,
    signal_ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Compute the Fresh Market Discovery Gate output.

    ``features`` maps normalized-ticker -> conceptual-field dict. Tickers with
    no features still appear (discovery is never skipped) but score low and
    classify as WATCHLIST.
    """
    if payload is None:
        payload = load_daily_payload(payload_dir)
    if truth_gate is None:
        truth_gate = build_portfolio_truth_gate(payload=payload)
    thresholds = load_discovery_thresholds()
    cqs_min = float(thresholds["cqs_min"])
    watchlist_min = float(thresholds["watchlist_fcs_min"])
    features = {normalize_ticker(k): v for k, v in (features or {}).items()}

    universe = build_discovery_universe(payload, model_candidates, signal_ledger_path)
    forbidden = set(truth_gate["closed_or_sold"]) | set(truth_gate["do_not_treat_as_open"])
    holdings = set(truth_gate["verified_open_holdings"])

    scored: list[dict[str, Any]] = []
    for ticker in universe:
        score = score_candidate(ticker, features.get(ticker))
        score["portfolio_truth"] = classify_ticker(ticker, truth_gate)
        score["forbidden_for_execution"] = ticker in forbidden
        score["is_verified_holding"] = ticker in holdings
        scored.append(score)
    scored.sort(key=lambda s: (-s["cqs"], s["ticker"]))

    yesterday = set(payload["yesterday_candidates"]["final_candidates"])
    new_tickers = [s["ticker"] for s in scored if s["ticker"] not in yesterday]

    # Boards. A name is a fresh BUY-CANDIDATE only if it clears CQS and is not a
    # closed/sold/do-not-treat ticker (those degrade to watchlist/historical).
    buy_candidates = [
        s for s in scored if s["cqs"] >= cqs_min and not s["forbidden_for_execution"]
    ]
    watchlist_upgrades = [
        s for s in scored
        if watchlist_min <= s["cqs"] < cqs_min and not s["forbidden_for_execution"]
    ]
    sell_avoid = [
        s for s in scored
        if s["cqs"] < watchlist_min or s["chaos_risk"] >= 0.6 or s["forbidden_for_execution"]
    ]

    source_health = str(payload["market_snapshot"]["source_health"]).upper()
    live_movers = any(
        m.get("freshness") not in (None, "UNVERIFIED")
        for m in payload["price_movers"]["movers"]
    )
    underpowered = (
        source_health in {"MISSING_OR_UNVERIFIED", "UNVERIFIED", "STALE", "COLLAPSED", "MISSING"}
        or not live_movers
    )
    discovery_notes: list[str] = []
    if underpowered:
        discovery_notes.append(
            "Discovery underpowered but not skipped. Live market snapshot / movers "
            "are MISSING_OR_UNVERIFIED, so candidates are research-grade and most "
            "will classify NOT_EXECUTABLE until source health clears."
        )

    return {
        "discovery_universe": universe,
        "scored_candidates": scored,
        "buy_candidate_board": buy_candidates,
        "watchlist_upgrade_board": watchlist_upgrades,
        "sell_avoid_board": sell_avoid,
        "new_tickers_not_seen_yesterday": new_tickers,
        "new_ticker_count": len(new_tickers),
        "discovery_underpowered": underpowered,
        "global_discovery_permission": True,
        "source_health": source_health,
        "discovery_notes": discovery_notes,
        "thresholds": {"cqs_min": cqs_min, "watchlist_fcs_min": watchlist_min},
        "safety": advisory_safety_stamps(),
    }


__all__ = [
    "CQS_WEIGHTS",
    "CQS_PENALTIES",
    "score_candidate",
    "build_discovery_universe",
    "build_fresh_market_discovery",
]
