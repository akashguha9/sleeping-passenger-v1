"""Chicken Gate daily bridge — wires the v1.2 gate into daily synthesis.

Placement (the latest advisory point before final action is emitted):

    model synthesis / candidate scoring (CQS/EQS)
        -> candidate_executable_split (EXISTING decision, untouched)
        -> chicken_gate.evaluate_chicken_gate per buy-side candidate
        -> demote-only integrated gate:  FINAL_RANK = min(existing, chicken)
        -> audit lines + runtime artifacts

Mathematical contract (tested):

    CHICKEN_FINAL_SCORE <= RAW_VALIDATED_SCORE            (chicken invariant)
    INTEGRATED_FINAL_SCORE = min(EXISTING_SCORE, CHICKEN_FINAL_SCORE)
    FINAL_GATE_RANK = min(EXISTING_GATE_RANK, CHICKEN_GATE_RANK)

The bridge NEVER upgrades an existing decision, never mutates the split
object, never executes anything, and degrades transparently when candidate
fields are missing (evidence notes + conservative haircuts inside the gate).

Field mapping honesty: only real pipeline data is mapped (CQS -> house
edge with source-health confidence, data quality -> input quality,
crowding_risk / why-today lateness -> IAP, mover move_pct -> price-move
slot, provider -> channel premium, verified holdings -> operator fit).
Components with no daily evidence (process integrity, label, bone, node)
are passed as documented conservative neutrals — the node stays unproven,
so every auto-mapped candidate caps at BUY_LIMITED until an operator
supplies node evidence via ``thesis_overrides`` (or
``runtime/chicken_gate_thesis_overrides.json``). The gate's evidence notes
list exactly what to add to unlock a higher gate.

Advisory-only. No broker calls, no order surface, no execution language.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.chicken_gate import (
        GATE_BUY_ALLOWED,
        GATE_BUY_BLOCKED,
        GATE_BUY_LIMITED,
        GATE_WATCHLIST,
        SCORING_PROFILE_VERSION,
        evaluate_chicken_gate,
    )
    from scripts.daily_payload import normalize_ticker
    from scripts.runtime_common import REPO_ROOT
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from chicken_gate import (
        GATE_BUY_ALLOWED,
        GATE_BUY_BLOCKED,
        GATE_BUY_LIMITED,
        GATE_WATCHLIST,
        SCORING_PROFILE_VERSION,
        evaluate_chicken_gate,
    )
    from daily_payload import normalize_ticker
    from runtime_common import REPO_ROOT

# Default ON.  The bypass exists for diagnostics only and discloses itself.
CHICKEN_GATE_ENABLED_DEFAULT = True
CHICKEN_GATE_DEBUG_BYPASS_DEFAULT = False
DISABLED_MODE = "CHICKEN_GATE_DISABLED_DEBUG_ONLY"
ENABLED_MODE = "CHICKEN_GATE_ENABLED"

THESIS_OVERRIDES_PATH = REPO_ROOT / "runtime" / "chicken_gate_thesis_overrides.json"

GATE_RANK: dict[str, int] = {
    GATE_BUY_BLOCKED: 0,
    GATE_WATCHLIST: 1,
    GATE_BUY_LIMITED: 2,
    GATE_BUY_ALLOWED: 3,
}
RANK_TO_GATE: dict[int, str] = {v: k for k, v in GATE_RANK.items()}

# Existing split classification -> existing buy-side action gate.
# SELL / EXIT REVIEW is not a buy decision and is excluded from gating.
CLASSIFICATION_TO_GATE: dict[str, str] = {
    "EXECUTABLE-PAPER-BUY": GATE_BUY_ALLOWED,
    "BUY-CANDIDATE / NOT-EXECUTABLE": GATE_BUY_LIMITED,
    "BUY-CANDIDATE": GATE_BUY_LIMITED,
    "WATCHLIST-UPGRADE": GATE_WATCHLIST,
    "WATCHLIST": GATE_WATCHLIST,
    "WAIT": GATE_WATCHLIST,
    "AVOID": GATE_BUY_BLOCKED,
    "STALE / REMOVE": GATE_BUY_BLOCKED,
}

# Provider/source substring -> channel premium (0 farm-gate .. 10 packaged).
_CHANNEL_PREMIUM_BY_SOURCE: tuple[tuple[str, float], ...] = (
    ("FILING", 1.0),
    ("EDGAR", 1.0),
    ("SEC", 1.0),
    ("EXCHANGE", 2.0),
    ("SCREEN", 3.0),
    ("YAHOO", 3.0),
    ("MARKET_DATA", 3.0),
    ("NEWS", 4.0),
    ("GDELT", 4.0),
    ("SOCIAL", 8.0),
    ("INFLUENCER", 9.0),
    ("STATIC_UNIVERSE_FALLBACK", 6.0),
)


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def integrate_final_gate(existing_gate: str, chicken_gate_value: str) -> str:
    """Demote-only integrated gate: min rank wins.  Mandatory contract."""
    existing_rank = GATE_RANK.get(str(existing_gate), 0)
    chicken_rank = GATE_RANK.get(str(chicken_gate_value), 0)
    return RANK_TO_GATE[min(existing_rank, chicken_rank)]


def classify_source_channel(provider: Any, source: Any) -> float | None:
    """Map a provider/source label to a channel premium.  None = unknown."""
    label = f"{provider or ''} {source or ''}".upper()
    if not label.strip():
        return None
    for token, premium in _CHANNEL_PREMIUM_BY_SOURCE:
        if token in label:
            return premium
    return None


def load_thesis_overrides(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """Operator-authored per-ticker evidence enrichment (optional file).

    This is how a daily candidate earns its way past the automatic
    conservative mapping: the operator supplies node evidence, confidences,
    probabilities, etc.  Absent/unreadable file -> empty dict, never a crash.
    """
    target = Path(path) if path is not None else THESIS_OVERRIDES_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        normalize_ticker(k): v
        for k, v in payload.items()
        if isinstance(v, dict) and normalize_ticker(k)
    }


def map_candidate_to_thesis(
    *,
    row: dict[str, Any],
    score: dict[str, Any],
    mover: dict[str, Any],
    why_today_score: float | None,
    in_yesterday: bool,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map one daily candidate into chicken_gate thesis inputs.

    Only real pipeline data becomes evidence; everything else is a
    documented conservative neutral so the gate's haircuts (not silence)
    decide the outcome.  ``overrides`` (operator-authored) win last.
    """
    ticker = str(row.get("ticker") or "")
    cqs = _num(score.get("cqs"))
    data_quality = _num(score.get("data_quality"))
    source_health = _num(mover.get("source_health"))
    crowding_risk = _num(score.get("crowding_risk"))
    move_pct = _num(mover.get("move_pct"))

    thesis: dict[str, Any] = {
        "ticker": ticker,
        "asset_lineage": "UNKNOWN",
        "thesis_text": str(mover.get("why_today") or row.get("reason") or ""),
        "catalyst_text": str(mover.get("why_today") or ""),
        "node_change_evidence": "NONE",
        "spoilage_risk": False,
        # No model/market probability exists at this pipeline layer ->
        # chicken_gate reports NET_EDGE INSUFFICIENT_EVIDENCE and caps at
        # BUY_LIMITED.  Never invented.
    }

    # Freshness: a live event today = age 0; carried from yesterday = 1 day;
    # otherwise unknown -> the gate applies the first-signal haircut.
    freshness_label = str(mover.get("freshness") or "").upper()
    if bool(mover.get("is_live")) or freshness_label in {"FRESH_TODAY", "UPDATED_TODAY"}:
        thesis["thesis_age_days"] = 0.0
    elif in_yesterday:
        thesis["thesis_age_days"] = 1.0

    # Raw components: CQS is the existing merit score; data quality feeds
    # input quality; both trust-weighted by live source health.
    if cqs is not None:
        thesis["house_edge_score"] = max(0.0, min(10.0, cqs * 10.0))
        thesis["house_edge_confidence"] = max(0.0, min(1.0, source_health or 0.0))
    if data_quality is not None:
        thesis["input_quality_score"] = max(0.0, min(10.0, data_quality * 10.0))
        thesis["input_quality_confidence"] = max(0.0, min(1.0, source_health or 0.0))
    # Documented conservative neutrals (no daily evidence exists for these):
    thesis.setdefault("process_integrity_score", 5.0)
    thesis.setdefault("process_integrity_confidence", 0.5)
    thesis.setdefault("label_authenticity_score", 0.5)
    thesis.setdefault("label_authenticity_confidence", 0.5)
    thesis.setdefault("residual_bone_value_score", 0.3)
    thesis.setdefault("residual_bone_value_confidence", 0.5)
    # Load-bearing node deliberately NOT set: the gate fails closed to the
    # BUY_LIMITED cap until an operator override supplies node evidence.

    # Information access: crowding_risk and why-today lateness are real
    # pipeline evidence; the worse one is the explicit IAP.
    lateness_candidates: list[float] = []
    if crowding_risk is not None:
        lateness_candidates.append(max(0.0, min(10.0, crowding_risk * 10.0)))
    if why_today_score is not None:
        lateness_candidates.append(
            max(0.0, min(10.0, (1.0 - max(0.0, min(1.0, why_today_score))) * 10.0))
        )
    if lateness_candidates:
        thesis["information_access_premium"] = max(lateness_candidates)
    if move_pct is not None:
        thesis["price_move_since_signal_pct"] = move_pct

    channel_premium = classify_source_channel(mover.get("provider"), mover.get("source"))
    if channel_premium is not None:
        thesis["channel_premium_score"] = channel_premium

    if isinstance(overrides, dict) and overrides:
        thesis.update(overrides)
        thesis["operator_override_applied"] = True
    return thesis


def _nested_audit_block(gate_result: dict[str, Any]) -> dict[str, Any]:
    """The Phase-4 nested ``chicken_gate`` audit object (lowercase keys)."""
    return {
        "scoring_profile_version": gate_result["SCORING_PROFILE_VERSION"],
        "raw_trade_score": gate_result["RAW_TRADE_SCORE"],
        "raw_validated_score": gate_result["RAW_VALIDATED_SCORE"],
        "raw_inflation_leakage": gate_result["RAW_INFLATION_LEAKAGE"],
        "freshness_state": gate_result["FRESHNESS_STATE"],
        "freshness_multiplier": gate_result["FRESHNESS_MULTIPLIER"],
        "iap_effective": gate_result["IAP_EFFECTIVE"],
        "iap_confidence": gate_result["IAP_CONFIDENCE"],
        "channel_multiplier": gate_result["CHANNEL_MULTIPLIER"],
        "operator_fit_score": gate_result["OPERATOR_FIT_SCORE"],
        "operator_fit_confidence": gate_result["OPERATOR_FIT_CONFIDENCE"],
        "final_score": gate_result["FINAL_SCORE"],
        "final_action_gate": gate_result["FINAL_ACTION_GATE"],
        "hard_flag_triggered": gate_result["HARD_FLAG_TRIGGERED"],
        "cap_rules_triggered": gate_result["CAP_RULES_TRIGGERED"],
        "value_extraction_ledger": gate_result["VALUE_EXTRACTION_LEDGER"],
        "evidence_notes": gate_result["EVIDENCE_NOTES"],
        "one_line_reason": gate_result["ONE_LINE_REASON"],
        "advisory_only_stamp": gate_result["ADVISORY_ONLY_STAMP"],
    }


def _audit_line(row: dict[str, Any]) -> str:
    return (
        f"{row['TICKER']} | {row['EXISTING_ACTION_GATE']} -> "
        f"{row['CHICKEN_ACTION_GATE']} -> {row['FINAL_ACTION_GATE']} | "
        f"{row['INTEGRATED_FINAL_SCORE']:.2f} | {row['CHICKEN_ONE_LINE_REASON']}"
    )


def build_chicken_gate_integration(
    *,
    split: dict[str, Any],
    discovery: dict[str, Any],
    payload: dict[str, Any],
    why_today_scores: dict[str, float] | None = None,
    enabled: bool = CHICKEN_GATE_ENABLED_DEFAULT,
    debug_bypass: bool = CHICKEN_GATE_DEBUG_BYPASS_DEFAULT,
    thesis_overrides: dict[str, dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run every buy-side classified candidate through the chicken gate.

    Returns the integration object stored on the daily synthesis result.
    The existing split decision is read, never mutated.
    """
    scores_by_ticker = {
        s["ticker"]: s for s in discovery.get("scored_candidates", [])
    }
    movers_by_ticker: dict[str, dict[str, Any]] = {}
    for mover in payload.get("price_movers", {}).get("movers", []):
        ticker = normalize_ticker(mover.get("ticker") or mover.get("symbol"))
        if ticker:
            movers_by_ticker[ticker] = mover
    yesterday = set(
        payload.get("yesterday_candidates", {}).get("final_candidates", [])
    ) | set(payload.get("yesterday_candidates", {}).get("watchlist", []))
    why_today_scores = why_today_scores or {}
    if thesis_overrides is None:
        thesis_overrides = load_thesis_overrides()
    holdings = payload.get("verified_holdings", {}).get("positions")
    holdings = holdings if isinstance(holdings, list) else None

    bypassed = bool(debug_bypass) or not bool(enabled)
    mode = DISABLED_MODE if bypassed else ENABLED_MODE

    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for candidate in split.get("classified", []):
        ticker = str(candidate.get("ticker") or "")
        classification = str(candidate.get("classification") or "")
        existing_gate = CLASSIFICATION_TO_GATE.get(classification)
        if existing_gate is None:
            excluded.append({
                "TICKER": ticker,
                "classification": classification,
                "excluded_reason": "NOT_A_BUY_DECISION",
            })
            continue

        cqs = _num(candidate.get("cqs")) or 0.0
        existing_score = round(max(0.0, min(10.0, cqs * 10.0)), 4)

        if bypassed:
            rows.append({
                "TICKER": ticker,
                "EXISTING_ACTION_GATE": existing_gate,
                "CHICKEN_ACTION_GATE": DISABLED_MODE,
                "FINAL_ACTION_GATE": existing_gate,
                "EXISTING_SCORE": existing_score,
                "CHICKEN_FINAL_SCORE": None,
                "INTEGRATED_FINAL_SCORE": existing_score,
                "CHICKEN_HARD_FLAG_TRIGGERED": DISABLED_MODE,
                "CHICKEN_CAP_RULES_TRIGGERED": [],
                "CHICKEN_ONE_LINE_REASON": DISABLED_MODE,
                "FINAL_EXECUTABLE": bool(candidate.get("executable")),
                "chicken_gate": {"mode": DISABLED_MODE},
            })
            continue

        thesis = map_candidate_to_thesis(
            row=candidate,
            score=scores_by_ticker.get(ticker, {}),
            mover=movers_by_ticker.get(ticker, {}),
            why_today_score=why_today_scores.get(ticker),
            in_yesterday=ticker in yesterday,
            overrides=thesis_overrides.get(ticker),
        )
        gate_result = evaluate_chicken_gate(thesis, now=now, holdings=holdings)

        chicken_gate_value = gate_result["FINAL_ACTION_GATE"]
        final_gate = integrate_final_gate(existing_gate, chicken_gate_value)
        chicken_final = float(gate_result["FINAL_SCORE"])
        integrated_score = round(min(existing_score, chicken_final), 4)

        row_out = {
            "TICKER": ticker,
            "EXISTING_ACTION_GATE": existing_gate,
            "CHICKEN_ACTION_GATE": chicken_gate_value,
            "FINAL_ACTION_GATE": final_gate,
            "EXISTING_SCORE": existing_score,
            "CHICKEN_FINAL_SCORE": chicken_final,
            "CHICKEN_RAW_VALIDATED_SCORE": gate_result["RAW_VALIDATED_SCORE"],
            "INTEGRATED_FINAL_SCORE": integrated_score,
            "CHICKEN_HARD_FLAG_TRIGGERED": gate_result["HARD_FLAG_TRIGGERED"],
            "CHICKEN_CAP_RULES_TRIGGERED": gate_result["CAP_RULES_TRIGGERED"],
            "CHICKEN_ONE_LINE_REASON": gate_result["ONE_LINE_REASON"],
            "FINAL_EXECUTABLE": (
                bool(candidate.get("executable")) and final_gate == GATE_BUY_ALLOWED
            ),
            "chicken_gate": _nested_audit_block(gate_result),
            "chicken_gate_thesis_inputs": thesis,
        }
        row_out["AUDIT_LINE"] = _audit_line(row_out)
        rows.append(row_out)

    gate_counts: dict[str, int] = {}
    for row in rows:
        gate_counts[row["FINAL_ACTION_GATE"]] = (
            gate_counts.get(row["FINAL_ACTION_GATE"], 0) + 1
        )

    return {
        "mode": mode,
        "scoring_profile_version": SCORING_PROFILE_VERSION,
        "rows": rows,
        "excluded_rows": excluded,
        "final_gate_counts": gate_counts,
        "audit_lines": [r["AUDIT_LINE"] for r in rows if "AUDIT_LINE" in r],
        "demotions": [
            r["TICKER"] for r in rows
            if GATE_RANK.get(r["FINAL_ACTION_GATE"], 0)
            < GATE_RANK.get(r["EXISTING_ACTION_GATE"], 0)
        ],
        "safety": advisory_safety_stamps(),
    }


def reevaluate_daily_decay(
    integration: dict[str, Any], *, now: datetime, holdings: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Re-run stored thesis inputs at a later ``now`` (daily freshness decay).

    Freshness can only fall or hold as time passes with fixed inputs, so the
    re-evaluated final score never exceeds the stored one (demote-only over
    time).  Returns a compact report; does not mutate the input.
    """
    rows: list[dict[str, Any]] = []
    for row in integration.get("rows", []):
        thesis = row.get("chicken_gate_thesis_inputs")
        if not isinstance(thesis, dict):
            continue
        # Age explicit thesis_age_days is a point-in-time snapshot; decay is
        # driven by thesis_first_signal_date when present, else we age the
        # snapshot manually by re-dating it.
        result = evaluate_chicken_gate(thesis, now=now, holdings=holdings)
        rows.append({
            "TICKER": row.get("TICKER"),
            "previous_final_score": row.get("CHICKEN_FINAL_SCORE"),
            "reevaluated_final_score": result["FINAL_SCORE"],
            "previous_gate": row.get("CHICKEN_ACTION_GATE"),
            "reevaluated_gate": result["FINAL_ACTION_GATE"],
            "freshness_state": result["FRESHNESS_STATE"],
        })
    return {"reevaluated": rows, "safety": advisory_safety_stamps()}


__all__ = [
    "CHICKEN_GATE_ENABLED_DEFAULT",
    "CHICKEN_GATE_DEBUG_BYPASS_DEFAULT",
    "DISABLED_MODE",
    "ENABLED_MODE",
    "GATE_RANK",
    "RANK_TO_GATE",
    "CLASSIFICATION_TO_GATE",
    "THESIS_OVERRIDES_PATH",
    "integrate_final_gate",
    "classify_source_channel",
    "load_thesis_overrides",
    "map_candidate_to_thesis",
    "build_chicken_gate_integration",
    "reevaluate_daily_decay",
]
