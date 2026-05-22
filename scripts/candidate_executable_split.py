"""Layer 3 — Separate "Candidate" from "Executable".

A strong candidate that lacks execution hygiene (live source health, defined
invalidation, defined sizing) is NOT "no candidate" — it is a
BUY-CANDIDATE / NOT-EXECUTABLE, and the report must say *why* it is not
executable. This module enforces that distinction.

    EQS(t) = 0.25*DQ + 0.20*invalidation_defined + 0.15*position_sizing_defined
             + 0.15*source_health + 0.10*portfolio_truth_clean
             + 0.10*liquidity_quality + 0.05*human_review_ready

    EXECUTABLE_BUY(t) iff
        CQS >= CQS_MIN and EQS >= EQS_MIN
        and t ∉ C and t ∉ S and t ∉ D
        and source_health >= SOURCE_HEALTH_MIN
        and invalidation_defined and position_sizing_defined
        and advisory_only and human_execution_required   (always true here)
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


EQS_WEIGHTS = {
    "data_quality": 0.25,
    "invalidation_defined": 0.20,
    "position_sizing_defined": 0.15,
    "source_health": 0.15,
    "portfolio_truth_clean": 0.10,
    "liquidity_quality": 0.10,
    "human_review_ready": 0.05,
}

CLASSIFICATIONS = (
    "BUY-CANDIDATE",
    "EXECUTABLE-PAPER-BUY",
    "WATCHLIST-UPGRADE",
    "WATCHLIST",
    "WAIT",
    "SELL / EXIT REVIEW",
    "AVOID",
    "STALE / REMOVE",
    "BUY-CANDIDATE / NOT-EXECUTABLE",
)


def _clamp01(value: Any) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, num))


def _flag(value: Any) -> float:
    """Coerce a 0/1 / bool flag to float."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return _clamp01(value)


def compute_eqs(inputs: dict[str, Any] | None) -> dict[str, Any]:
    """Execution Quality Score with per-component breakdown."""
    inputs = dict(inputs or {})
    components = {
        "data_quality": _clamp01(inputs.get("data_quality")),
        "invalidation_defined": _flag(inputs.get("invalidation_defined")),
        "position_sizing_defined": _flag(inputs.get("position_sizing_defined")),
        "source_health": _clamp01(inputs.get("source_health")),
        "portfolio_truth_clean": _flag(inputs.get("portfolio_truth_clean", 1)),
        "liquidity_quality": _clamp01(inputs.get("liquidity_quality")),
        "human_review_ready": _flag(inputs.get("human_review_ready")),
    }
    eqs = round(sum(EQS_WEIGHTS[k] * components[k] for k in EQS_WEIGHTS), 4)
    return {"eqs": eqs, "components": components}


def classify_candidate(
    *,
    cqs: float,
    eqs: float,
    eqs_components: dict[str, Any],
    portfolio_truth: str,
    forbidden_for_execution: bool,
    source_health: float,
    chaos_risk: float = 0.0,
    staleness_label: str | None = None,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return classification + human-readable reason for one candidate."""
    thresholds = thresholds or load_discovery_thresholds()
    cqs_min = float(thresholds["cqs_min"])
    eqs_min = float(thresholds["eqs_min"])
    watchlist_min = float(thresholds["watchlist_fcs_min"])
    source_health_min = float(thresholds["source_health_min"])

    invalidation_ok = eqs_components.get("invalidation_defined", 0) >= 1.0
    sizing_ok = eqs_components.get("position_sizing_defined", 0) >= 1.0
    label = (staleness_label or "").upper()

    reason: str
    classification: str

    # Verified open holdings are the only tickers eligible for exit review.
    if portfolio_truth == "VERIFIED_OPEN_HOLDING":
        classification = "SELL / EXIT REVIEW"
        reason = "Verified open holding — eligible for human exit/TP/stop review only."
        return _result(classification, reason, cqs, eqs, executable=False)

    # Closed/sold/do-not-treat names can be discovery candidates but never
    # executable buys (t ∈ C ∪ S ∪ D).
    if forbidden_for_execution:
        if cqs >= watchlist_min:
            classification = "WATCHLIST"
            reason = (
                "Closed/sold/do-not-treat ticker with a fresh signal — historical "
                "context, watch only. Not executable (t ∈ C ∪ S ∪ D)."
            )
        else:
            classification = "AVOID"
            reason = "Closed/sold/do-not-treat ticker with no fresh edge — historical only."
        return _result(classification, reason, cqs, eqs, executable=False)

    if label in {"STALE_48H", "HISTORICAL_ONLY"} and cqs < cqs_min:
        return _result(
            "STALE / REMOVE",
            f"Old candidate ({label}) with no fresh supporting signal.",
            cqs, eqs, executable=False,
        )

    # Executable requires both quality and hygiene gates.
    executable = (
        cqs >= cqs_min
        and eqs >= eqs_min
        and source_health >= source_health_min
        and invalidation_ok
        and sizing_ok
    )
    if executable:
        return _result(
            "EXECUTABLE-PAPER-BUY",
            "Clears CQS and EQS, source health adequate, invalidation + sizing "
            "defined. Advisory-only paper buy for human execution.",
            cqs, eqs, executable=True,
        )

    if cqs >= cqs_min:
        missing: list[str] = []
        if eqs < eqs_min:
            missing.append(f"EQS {eqs:.2f} < {eqs_min:.2f}")
        if source_health < source_health_min:
            missing.append(f"source_health {source_health:.2f} < {source_health_min:.2f}")
        if not invalidation_ok:
            missing.append("invalidation not defined")
        if not sizing_ok:
            missing.append("position sizing not defined")
        reason = "Good candidate, not executable because " + "; ".join(missing) + "."
        return _result("BUY-CANDIDATE / NOT-EXECUTABLE", reason, cqs, eqs, executable=False)

    if cqs >= watchlist_min:
        return _result(
            "WATCHLIST-UPGRADE" if cqs >= (cqs_min + watchlist_min) / 2 else "WATCHLIST",
            "Getting stronger but below the candidate floor — incomplete confirmation.",
            cqs, eqs, executable=False,
        )

    if chaos_risk >= 0.6:
        return _result("AVOID", "Chaos risk too high for the available edge.", cqs, eqs, executable=False)

    return _result("WAIT", "Insufficient confirmation today.", cqs, eqs, executable=False)


def _result(classification: str, reason: str, cqs: float, eqs: float, *, executable: bool) -> dict[str, Any]:
    return {
        "classification": classification,
        "reason": reason,
        "cqs": cqs,
        "eqs": eqs,
        "executable": executable,
    }


def build_candidate_executable_split(
    discovery: dict[str, Any],
    truth_gate: dict[str, Any],
    eqs_features: dict[str, dict[str, Any]] | None = None,
    staleness_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Classify every discovered candidate into candidate/executable buckets."""
    thresholds = load_discovery_thresholds()
    eqs_features = {normalize_ticker(k): v for k, v in (eqs_features or {}).items()}
    staleness_labels = {normalize_ticker(k): v for k, v in (staleness_labels or {}).items()}

    rows: list[dict[str, Any]] = []
    for score in discovery["scored_candidates"]:
        ticker = score["ticker"]
        feats = dict(eqs_features.get(ticker) or {})
        feats.setdefault("data_quality", score["data_quality"])
        feats.setdefault("liquidity_quality", score["components"].get("liquidity_quality", 0.0))
        feats.setdefault("portfolio_truth_clean", 0 if score["forbidden_for_execution"] else 1)
        source_health = _clamp01(feats.get("source_health"))
        eqs_obj = compute_eqs(feats)
        verdict = classify_candidate(
            cqs=score["cqs"],
            eqs=eqs_obj["eqs"],
            eqs_components=eqs_obj["components"],
            portfolio_truth=score["portfolio_truth"],
            forbidden_for_execution=score["forbidden_for_execution"],
            source_health=source_health,
            chaos_risk=score.get("chaos_risk", 0.0),
            staleness_label=staleness_labels.get(ticker),
            thresholds=thresholds,
        )
        rows.append(
            {
                "ticker": ticker,
                "portfolio_truth": score["portfolio_truth"],
                "cqs": score["cqs"],
                "eqs": eqs_obj["eqs"],
                "eqs_components": eqs_obj["components"],
                "classification": verdict["classification"],
                "executable": verdict["executable"],
                "reason": verdict["reason"],
            }
        )

    def bucket(name: str) -> list[dict[str, Any]]:
        return [r for r in rows if r["classification"] == name]

    executable_buys = [r for r in rows if r["executable"]]
    candidate_not_executable = bucket("BUY-CANDIDATE / NOT-EXECUTABLE")

    return {
        "classified": rows,
        "executable_paper_buys": executable_buys,
        "buy_candidate_not_executable": candidate_not_executable,
        "watchlist_upgrades": bucket("WATCHLIST-UPGRADE"),
        "watchlist": bucket("WATCHLIST"),
        "wait": bucket("WAIT"),
        "sell_exit_review": bucket("SELL / EXIT REVIEW"),
        "avoid": bucket("AVOID"),
        "stale_remove": bucket("STALE / REMOVE"),
        "has_executable_buys": bool(executable_buys),
        "safety": advisory_safety_stamps(),
    }


__all__ = [
    "EQS_WEIGHTS",
    "CLASSIFICATIONS",
    "compute_eqs",
    "classify_candidate",
    "build_candidate_executable_split",
]
