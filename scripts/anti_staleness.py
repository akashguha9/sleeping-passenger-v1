"""Layer 4 — Anti-staleness rules.

Yesterday's names may only repeat if the report states what changed today.
Discovery must hit a minimum novelty bar or be flagged. Stale candidates with
no fresh evidence are penalized, never silently carried forward. And — the
core fix — a phantom position can never set ``global_discovery_permission`` to
0.

    Y = yesterday_final_candidates
    T = today's final candidate board
    novelty_ratio    = |T \\ Y| / max(1, |T|)        target >= 0.30
    new_ticker_count = |T \\ Y|                       target >= 10
    ACQS(t)          = CQS(t) - staleness_penalty(t)
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.daily_discovery_config import load_discovery_thresholds
    from scripts.daily_payload import normalize_ticker
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from daily_discovery_config import load_discovery_thresholds
    from daily_payload import normalize_ticker


FRESHNESS_LABELS = (
    "FRESH_TODAY",
    "UPDATED_TODAY",
    "STALE_24H",
    "STALE_48H",
    "HISTORICAL_ONLY",
    "UNVERIFIED",
    "DO_NOT_TREAT_AS_OPEN",
    "CLOSED_OR_SOLD",
)


def freshness_label(
    ticker: str,
    *,
    fresh_evidence: bool,
    in_yesterday: bool,
    has_change_explanation: bool,
    truth_label: str | None = None,
    override: str | None = None,
) -> str:
    """Assign a freshness label to a single ticker."""
    if override and override.upper() in FRESHNESS_LABELS:
        return override.upper()
    if truth_label == "DO_NOT_TREAT_AS_OPEN":
        return "DO_NOT_TREAT_AS_OPEN"
    if truth_label == "CLOSED_OR_SOLD":
        return "CLOSED_OR_SOLD"
    if fresh_evidence and in_yesterday:
        return "UPDATED_TODAY"
    if fresh_evidence:
        return "FRESH_TODAY"
    if in_yesterday and has_change_explanation:
        return "UPDATED_TODAY"
    if in_yesterday:
        return "STALE_24H"
    return "UNVERIFIED"


def staleness_penalty(label: str, thresholds: dict[str, Any] | None = None) -> float:
    thresholds = thresholds or load_discovery_thresholds()
    table = thresholds.get("staleness_penalty", {})
    return float(table.get(str(label).upper(), 0.0))


def adjusted_cqs(cqs: float, label: str, thresholds: dict[str, Any] | None = None) -> float:
    return round(max(0.0, float(cqs) - staleness_penalty(label, thresholds)), 4)


def build_anti_staleness(
    payload: dict[str, Any],
    today_candidates: list[str],
    truth_gate: dict[str, Any],
    *,
    fresh_evidence_tickers: list[str] | None = None,
    change_explanations: dict[str, str] | None = None,
    freshness_overrides: dict[str, str] | None = None,
    cqs_by_ticker: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compute freshness labels, novelty ratio, and staleness warnings."""
    thresholds = load_discovery_thresholds()
    novelty_min = float(thresholds["novelty_ratio_min"])
    min_new = int(thresholds["min_new_ticker_count"])

    Y = set(payload["yesterday_candidates"]["final_candidates"])
    T = [normalize_ticker(t) for t in today_candidates]
    T_set = set(T)

    change_explanations = {normalize_ticker(k): v for k, v in (change_explanations or {}).items()}
    freshness_overrides = {normalize_ticker(k): v for k, v in (freshness_overrides or {}).items()}
    cqs_by_ticker = {normalize_ticker(k): v for k, v in (cqs_by_ticker or {}).items()}

    # Fresh evidence = ticker is in today's movers/news/filings.
    if fresh_evidence_tickers is None:
        fresh_set = (
            set(payload["price_movers"]["tickers"])
            | set(payload["news_events"]["tickers"])
            | set(payload["filings_events"]["tickers"])
        )
    else:
        fresh_set = {normalize_ticker(t) for t in fresh_evidence_tickers}

    do_not_treat = set(truth_gate["do_not_treat_as_open"])
    closed_or_sold = set(truth_gate["closed_or_sold"])

    labels: dict[str, str] = {}
    adjusted: dict[str, float] = {}
    repeats_missing_change: list[str] = []
    for ticker in T:
        if ticker in do_not_treat:
            truth_label = "DO_NOT_TREAT_AS_OPEN"
        elif ticker in closed_or_sold:
            truth_label = "CLOSED_OR_SOLD"
        elif ticker in set(truth_gate["verified_open_holdings"]):
            truth_label = "VERIFIED_OPEN_HOLDING"
        else:
            truth_label = "NOT_A_HOLDING"
        in_yesterday = ticker in Y
        has_change = ticker in change_explanations and bool(change_explanations[ticker])
        label = freshness_label(
            ticker,
            fresh_evidence=ticker in fresh_set,
            in_yesterday=in_yesterday,
            has_change_explanation=has_change,
            truth_label=truth_label,
            override=freshness_overrides.get(ticker),
        )
        labels[ticker] = label
        if ticker in cqs_by_ticker:
            adjusted[ticker] = adjusted_cqs(cqs_by_ticker[ticker], label, thresholds)
        # Rule 2: repeating yesterday's ticker requires a change explanation.
        if in_yesterday and not has_change:
            repeats_missing_change.append(ticker)

    new_tickers = sorted(T_set - Y)
    novelty_ratio = round(len(T_set - Y) / max(1, len(T_set)), 4)

    warnings: list[str] = []
    if novelty_ratio < novelty_min and T:
        warnings.append(
            f"STALE_DISCOVERY_WARNING: novelty_ratio {novelty_ratio:.2f} < {novelty_min:.2f}."
        )
    if repeats_missing_change:
        warnings.append(
            "STALE_DISCOVERY_WARNING: repeated yesterday tickers without a change "
            f"explanation: {', '.join(sorted(repeats_missing_change))}."
        )
    if len(new_tickers) < min_new:
        warnings.append(
            f"new_ticker_count {len(new_tickers)} < target {min_new}; "
            "data limitation likely (discovery underpowered). Not a stop — explain and proceed."
        )

    return {
        "freshness_labels": labels,
        "novelty_ratio": novelty_ratio,
        "novelty_ratio_min": novelty_min,
        "new_tickers": new_tickers,
        "new_ticker_count": len(new_tickers),
        "min_new_ticker_count": min_new,
        "repeats_missing_change_explanation": sorted(repeats_missing_change),
        "adjusted_cqs": adjusted,
        "stale_discovery_warning": any(w.startswith("STALE_DISCOVERY_WARNING") for w in warnings),
        "warnings": warnings,
        # No phantom blocker rule: phantom positions never disable discovery.
        "global_discovery_permission": True,
        "phantom_position_risk_blocks_discovery": False,
        "safety": advisory_safety_stamps(),
    }


__all__ = [
    "FRESHNESS_LABELS",
    "freshness_label",
    "staleness_penalty",
    "adjusted_cqs",
    "build_anti_staleness",
]
