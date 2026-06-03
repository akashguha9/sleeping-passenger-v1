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
    why_today_score: float = 1.0,
    entry_quality_pass: bool | None = None,
    entry_quality_score: float | None = None,
    entry_quality_reasons: list[str] | None = None,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return classification + human-readable reason for one candidate.

    ``why_today_score`` gates EXECUTABLE: a strong candidate with a weak
    why-today (< why_today_min_for_executable) stays a BUY-CANDIDATE /
    NOT-EXECUTABLE. Defaults to 1.0 so callers that do not supply it keep
    their prior behaviour.
    """
    thresholds = thresholds or load_discovery_thresholds()
    cqs_min = float(thresholds["cqs_min"])
    eqs_min = float(thresholds["eqs_min"])
    watchlist_min = float(thresholds["watchlist_fcs_min"])
    source_health_min = float(thresholds["source_health_min"])
    why_today_min = float(thresholds.get("why_today_min_for_executable", 0.70))

    invalidation_ok = eqs_components.get("invalidation_defined", 0) >= 1.0
    sizing_ok = eqs_components.get("position_sizing_defined", 0) >= 1.0
    why_today_ok = float(why_today_score) >= why_today_min
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

    # Entry-quality gate is opt-in: when not supplied (None) behave as if it
    # had passed, preserving backward-compatible behaviour for callers that
    # haven't wired daily OHLCV through yet. When supplied, a False blocks
    # EXECUTABLE and routes to BUY-CANDIDATE / NOT-EXECUTABLE.
    entry_quality_ok = entry_quality_pass is None or bool(entry_quality_pass)

    # Executable requires both quality and hygiene gates AND a fresh why-today.
    executable = (
        cqs >= cqs_min
        and eqs >= eqs_min
        and source_health >= source_health_min
        and invalidation_ok
        and sizing_ok
        and why_today_ok
        and entry_quality_ok
    )
    if executable:
        return _result(
            "EXECUTABLE-PAPER-BUY",
            "Clears CQS and EQS, source health adequate, invalidation + sizing "
            "defined, fresh why-today trigger. Advisory-only paper buy for human execution.",
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
        if not why_today_ok:
            missing.append(
                f"Missing sufficient why-today trigger (why_today_score "
                f"{float(why_today_score):.2f} < {why_today_min:.2f})"
            )
        if not entry_quality_ok:
            eq_reasons = entry_quality_reasons or []
            tail = f" ({'; '.join(eq_reasons)})" if eq_reasons else ""
            missing.append(f"entry-quality gate failed{tail}")
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
    why_today_scores: dict[str, float] | None = None,
    entry_quality_by_ticker: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Classify every discovered candidate into candidate/executable buckets.

    ``why_today_scores`` maps normalized-ticker -> WHY_TODAY_SCORE. A ticker
    without an entry defaults to 1.0 (no why-today penalty) to preserve
    backward-compatible behaviour; the daily pipeline passes real scores so the
    WHY_TODAY gate can block stale executables.

    ``entry_quality_by_ticker`` maps normalized-ticker -> entry_quality_gate
    result dict (``entry_quality_pass``, ``entry_quality_score``, ``reasons``).
    Tickers not present skip the entry-quality gate (treated as pass) — wire
    this in callers that have daily OHLCV available.
    """
    thresholds = load_discovery_thresholds()
    eqs_features = {normalize_ticker(k): v for k, v in (eqs_features or {}).items()}
    staleness_labels = {normalize_ticker(k): v for k, v in (staleness_labels or {}).items()}
    why_today_scores = {normalize_ticker(k): v for k, v in (why_today_scores or {}).items()}
    entry_quality_by_ticker = {
        normalize_ticker(k): v for k, v in (entry_quality_by_ticker or {}).items()
    }

    rows: list[dict[str, Any]] = []
    for score in discovery["scored_candidates"]:
        ticker = score["ticker"]
        feats = dict(eqs_features.get(ticker) or {})
        feats.setdefault("data_quality", score["data_quality"])
        feats.setdefault("liquidity_quality", score["components"].get("liquidity_quality", 0.0))
        feats.setdefault("portfolio_truth_clean", 0 if score["forbidden_for_execution"] else 1)
        source_health = _clamp01(feats.get("source_health"))
        why_today = float(why_today_scores.get(ticker, 1.0))
        eqs_obj = compute_eqs(feats)
        eq = entry_quality_by_ticker.get(ticker)
        eq_pass = eq.get("entry_quality_pass") if isinstance(eq, dict) else None
        eq_score = eq.get("entry_quality_score") if isinstance(eq, dict) else None
        eq_reasons = eq.get("reasons") if isinstance(eq, dict) else None
        verdict = classify_candidate(
            cqs=score["cqs"],
            eqs=eqs_obj["eqs"],
            eqs_components=eqs_obj["components"],
            portfolio_truth=score["portfolio_truth"],
            forbidden_for_execution=score["forbidden_for_execution"],
            source_health=source_health,
            chaos_risk=score.get("chaos_risk", 0.0),
            staleness_label=staleness_labels.get(ticker),
            why_today_score=why_today,
            entry_quality_pass=eq_pass,
            entry_quality_score=eq_score,
            entry_quality_reasons=eq_reasons,
            thresholds=thresholds,
        )
        rows.append(
            {
                "ticker": ticker,
                "portfolio_truth": score["portfolio_truth"],
                "cqs": score["cqs"],
                "eqs": eqs_obj["eqs"],
                "eqs_components": eqs_obj["components"],
                "why_today_score": round(why_today, 4),
                "entry_quality_pass": eq_pass,
                "entry_quality_score": eq_score,
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
