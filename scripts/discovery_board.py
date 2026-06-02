"""Daily 5-model synthesis DISCOVERY BOARD (advisory-only).

Separates *discovered stock* from *trade candidate*.  The daily synthesis must
produce a DISCOVERY BOARD — many names per country — BEFORE any manual-review
trade candidate is named.  Promotion to a manual-review candidate stays
quality-gated and capped per country by :mod:`scripts.country_diversity_gate`;
diversity never forces a trade and the engine never fabricates a ticker.

Advisory labels only — NEVER BUY / SELL / EXECUTE::

    WATCH  WAIT  AVOID  RISK_BLOCK
    TRADE_CANDIDATE_FOR_MANUAL_REVIEW  WATCH_CAP_LIMITED  OUTCOME_REVIEW_NEEDED

Discovery score (each component normalized to [0, 100])::

    raw = 0.18*CRS + 0.18*SRS + 0.18*CAT + 0.14*LIQ + 0.14*CON + 0.10*FRESH
        - 0.12*CHAOS - 0.10*CONTRA - 0.08*CORR - 0.06*DUP
    score = clamp(raw, 0, 100)

Contract — pure module: no DB, no network, no broker calls, no AI execution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.country_diversity_gate import (
        TRADE_CANDIDATE,
        WATCH_CAP_LIMITED,
        apply_trade_candidate_cap,
        build_diversity_report,
        load_quotas,
        region_for_country,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import sys

    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from country_diversity_gate import (  # type: ignore[no-redef]
        TRADE_CANDIDATE,
        WATCH_CAP_LIMITED,
        apply_trade_candidate_cap,
        build_diversity_report,
        load_quotas,
        region_for_country,
    )

# Advisory promotion labels (no execution vocabulary).
WATCH = "WATCH"
WAIT = "WAIT"
AVOID = "AVOID"
RISK_BLOCK = "RISK_BLOCK"
OUTCOME_REVIEW_NEEDED = "OUTCOME_REVIEW_NEEDED"

ALLOWED_LABELS = frozenset(
    {WATCH, WAIT, AVOID, RISK_BLOCK, TRADE_CANDIDATE, WATCH_CAP_LIMITED, OUTCOME_REVIEW_NEEDED}
)

_GLOBAL_TOP_N = 30


@dataclass(frozen=True)
class DiscoveryCandidate:
    date: date | None = None
    ticker: str = ""
    country: str = ""
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap_band: str | None = None
    liquidity_score: float = 0.0
    catalyst_score: float = 0.0
    country_relative_strength: float = 0.0
    sector_relative_strength: float = 0.0
    model_consensus: float = 0.0
    contradiction_score: float = 0.0
    chaos_risk: float = 0.0
    correlation_cluster: str | None = None
    correlation_penalty: float = 0.0
    duplicate_theme_penalty: float = 0.0
    data_freshness_score: float = 0.0
    discovery_score: float | None = None
    promotion_status: str | None = None
    rejection_reason: str | None = None


def compute_discovery_score(cand: DiscoveryCandidate) -> float:
    raw = (
        0.18 * cand.country_relative_strength
        + 0.18 * cand.sector_relative_strength
        + 0.18 * cand.catalyst_score
        + 0.14 * cand.liquidity_score
        + 0.14 * cand.model_consensus
        + 0.10 * cand.data_freshness_score
        - 0.12 * cand.chaos_risk
        - 0.10 * cand.contradiction_score
        - 0.08 * cand.correlation_penalty
        - 0.06 * cand.duplicate_theme_penalty
    )
    return round(max(0.0, min(100.0, raw)), 2)


def classify_promotion(cand: DiscoveryCandidate, score: float) -> str:
    """Advisory promotion label.  Never BUY/SELL."""
    if cand.chaos_risk >= 80:
        return RISK_BLOCK
    if cand.contradiction_score >= 75:
        return AVOID
    if cand.liquidity_score < 40:
        return AVOID
    if cand.data_freshness_score < 35:
        return WAIT
    if (
        score >= 85
        and cand.model_consensus >= 70
        and cand.chaos_risk <= 40
        and cand.contradiction_score <= 45
    ):
        return TRADE_CANDIDATE
    if score >= 70:
        return WATCH
    if score >= 55:
        return WAIT
    return AVOID


def score_candidates(candidates: Sequence[DiscoveryCandidate]) -> list[dict[str, Any]]:
    """Score + classify each candidate into a plain dict (pre-cap)."""
    scored: list[dict[str, Any]] = []
    for c in candidates:
        score = c.discovery_score if c.discovery_score is not None else compute_discovery_score(c)
        label = classify_promotion(c, score)
        scored.append(
            {
                "ticker": c.ticker,
                "country": c.country,
                "sector": c.sector,
                "discovery_score": score,
                "chaos_risk": c.chaos_risk,
                "contradiction_score": c.contradiction_score,
                "liquidity_score": c.liquidity_score,
                "data_freshness_score": c.data_freshness_score,
                "model_consensus": c.model_consensus,
                "promotion_status": label,
            }
        )
    return scored


# --------------------------------------------------------------------------- #
# Board tables
# --------------------------------------------------------------------------- #
def _country_discovery_table(
    scored: Sequence[dict[str, Any]], quotas: dict[str, Any]
) -> list[dict[str, Any]]:
    by_country: dict[str, list[dict[str, Any]]] = {}
    for s in scored:
        by_country.setdefault(str(s["country"] or "UNKNOWN"), []).append(s)

    rows: list[dict[str, Any]] = []
    for country, items in sorted(by_country.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        region = region_for_country(country, quotas)
        scores = [i["discovery_score"] for i in items]
        # Strongest sector = sector with the highest summed discovery score.
        sector_strength: dict[str, float] = {}
        for i in items:
            sec = str(i.get("sector") or "UNKNOWN")
            sector_strength[sec] = sector_strength.get(sec, 0.0) + i["discovery_score"]
        strongest = max(sector_strength.items(), key=lambda kv: kv[1])[0] if sector_strength else "UNKNOWN"
        top_names = [i["ticker"] for i in sorted(items, key=lambda x: -x["discovery_score"])[:3]]
        rows.append(
            {
                "country": country,
                "region": region,
                "names_discovered": len(items),
                "top_names": top_names,
                "avg_discovery_score": round(sum(scores) / len(scores), 2),
                "strongest_sector": strongest,
                "model_agreement": round(sum(i["model_consensus"] for i in items) / len(items), 2),
                "contradiction_risk": round(sum(i["contradiction_score"] for i in items) / len(items), 2),
                "data_freshness": round(sum(i["data_freshness_score"] for i in items) / len(items), 2),
            }
        )
    return rows


def _global_ranked_table(scored: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(scored, key=lambda s: -s["discovery_score"])[:_GLOBAL_TOP_N]
    return [
        {
            "rank": idx + 1,
            "ticker": s["ticker"],
            "country": s["country"],
            "sector": s.get("sector"),
            "discovery_score": s["discovery_score"],
            "chaos_risk": s["chaos_risk"],
            "contradiction_score": s["contradiction_score"],
            "promotion_status": s["promotion_status"],
        }
        for idx, s in enumerate(ranked)
    ]


def build_daily_discovery_board(
    candidates: Sequence[DiscoveryCandidate],
    quotas: dict[str, Any] | None = None,
    *,
    board_date: date | None = None,
) -> dict[str, Any]:
    """Produce the daily discovery board: country table, global ranked table,
    capped manual-review candidates, and concentration warnings — in that order
    (discovery before trade candidates).
    """
    q = quotas if quotas is not None else load_quotas()
    scored = score_candidates(candidates)

    # Per-country trade-candidate cap (downgrades excess to WATCH_CAP_LIMITED).
    capped = apply_trade_candidate_cap(scored, q)
    cap_status_by_ticker: dict[str, str] = {}
    for row, src in zip(capped, scored):
        cap_status_by_ticker[src["ticker"]] = row["promotion_status"]
        src["promotion_status"] = row["promotion_status"]  # apply cap back

    diversity_report = build_diversity_report(scored, q)

    # (C) Manual-review candidate table — capped, advisory labels only.
    manual_review = [
        {
            "ticker": s["ticker"],
            "country": s["country"],
            "region": region_for_country(s["country"], q),
            "discovery_score": s["discovery_score"],
            "label": TRADE_CANDIDATE,
        }
        for s in scored
        if s["promotion_status"] == TRADE_CANDIDATE
    ]

    board: dict[str, Any] = {
        "board_date": board_date.isoformat() if board_date else None,
        "discovery_board_precedes_trade_candidates": True,
        "total_discovered": len(scored),
        # (A)
        "country_discovery_table": _country_discovery_table(scored, q),
        # (B)
        "global_ranked_top30": _global_ranked_table(scored),
        # (C)
        "manual_review_candidates": manual_review,
        # (D)
        "concentration_warnings": diversity_report["diversity"]["concentration_warnings"],
        "diversity": diversity_report["diversity"],
        "quota": diversity_report["quota"],
        "promoted_count": diversity_report["promoted_count"],
        "cap_limited_count": diversity_report["cap_limited_count"],
        "diversity_forces_trades": False,
        "fabricates_countries": False,
    }
    # (E) advisory-only stamps + label invariant.
    board.update(advisory_safety_stamps())
    board["human_execution_required"] = True
    board["allowed_labels"] = sorted(ALLOWED_LABELS)
    return board


__all__ = [
    "WATCH",
    "WAIT",
    "AVOID",
    "RISK_BLOCK",
    "OUTCOME_REVIEW_NEEDED",
    "TRADE_CANDIDATE",
    "WATCH_CAP_LIMITED",
    "ALLOWED_LABELS",
    "DiscoveryCandidate",
    "compute_discovery_score",
    "classify_promotion",
    "score_candidates",
    "build_daily_discovery_board",
]
