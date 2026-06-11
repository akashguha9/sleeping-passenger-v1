"""Model-quality annotation for signal cards (Pass 6, Phase 4).

Attaches the advisory/evidence/temporal/grounding block to every signal
inbox item so the human sees, on the card itself, what the score stands
on — and what is missing. Pure + cheap: the evidence and derived-score
ledgers are read once per request and indexed by symbol.

Every annotation carries the mandatory framing (test-pinned):

    ADVISORY ONLY · HUMAN REVIEW REQUIRED
    Evidence coverage / Temporal validity / LLM grounding /
    Score changed because / Sensitivity warning / Memo /
    What would change my mind / Post-outcome review date

No banned execution/profit phrasing; missing evidence and invalid
timestamps surface as explicit warnings, never silently.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

ADVISORY_LABEL = "ADVISORY ONLY"
HUMAN_LABEL = "HUMAN REVIEW REQUIRED"
_REVIEW_DAYS = 30


def _classify_ts(value: str | None) -> str:
    if not value or not str(value).strip():
        return "MISSING TIMESTAMP — warning: cannot evaluate temporally"
    try:
        dt = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return "UNPARSABLE TIMESTAMP — warning: excluded from evaluation"
    if dt.tzinfo is None:
        return ("NAIVE TIMESTAMP — warning: temporally uncertain, excluded "
                "from evaluation until migrated")
    return "valid (aware UTC)"


def build_evidence_index(evidence_items: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for item in evidence_items:
        symbol = str(item.get("symbol", "")).upper()
        if symbol:
            index.setdefault(symbol, []).append(item)
    return index


def build_score_index(score_records: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for record in score_records:
        index.setdefault(str(record.get("symbol", "")).upper(), []).append(record)
    return index


def _score_change_summary(history: list[dict]) -> str:
    if len(history) < 2:
        return "no prior score on the derived-score ledger — first observation"
    prev, last = history[-2], history[-1]
    delta = float(last.get("raw_score", 0.0)) - float(prev.get("raw_score", 0.0))
    causes = []
    if set(last.get("input_evidence_ids", [])) != set(prev.get("input_evidence_ids", [])):
        causes.append("evidence set changed")
    if last.get("model_version") != prev.get("model_version"):
        causes.append("model version changed")
    if not causes and abs(delta) > 1e-9:
        causes.append("WARNING: score moved without recorded evidence change")
    return (f"Δ {delta:+.4f} since {prev.get('generated_at_utc', '?')[:10]}"
            + (f" — {'; '.join(causes)}" if causes else " — unchanged inputs"))


def build_signal_annotation(
    item: dict[str, Any],
    *,
    evidence_index: dict[str, list[dict]] | None = None,
    score_index: dict[str, list[dict]] | None = None,
) -> dict[str, Any]:
    symbol = str(item.get("ticker", "")).upper()
    evidence = (evidence_index or {}).get(symbol, [])
    history = sorted(
        (score_index or {}).get(symbol, []),
        key=lambda r: str(r.get("generated_at_utc", "")),
    )
    latest = history[-1] if history else {}
    observed = item.get("observed_at")
    review_date = ""
    try:
        base = _dt.datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
        if base.tzinfo is not None:
            review_date = (base + _dt.timedelta(days=_REVIEW_DAYS)).date().isoformat()
    except (ValueError, TypeError):
        pass

    if evidence:
        evidence_line = (f"{len(evidence)} evidence item(s) on ledger "
                         f"(ids: {', '.join(e.get('evidence_id', '?')[:11] for e in evidence[:3])}"
                         + ("…" if len(evidence) > 3 else "") + ")")
        grounding_line = "evidence-backed — see ids above"
    else:
        evidence_line = "NO EVIDENCE ON LEDGER — warning: treat as unsupported"
        grounding_line = "NOT GROUNDED — any score derived from this signal must abstain"

    memo_path = str(latest.get("decision_memo_path", "") or "")
    return {
        "advisory_status": ADVISORY_LABEL,
        "human_review": HUMAN_LABEL,
        "evidence_coverage": evidence_line,
        "temporal_validity": _classify_ts(observed),
        "llm_grounding": grounding_line,
        "score_changed_because": _score_change_summary(history),
        "sensitivity_warning": str(latest.get("sensitivity_warning", "") or "none recorded"),
        "memo": memo_path or ("not yet generated — run "
                              "scripts/generate_decision_memo.py for this signal"),
        "what_would_change_my_mind": (
            "see memo falsifiers" if memo_path else
            "UNDEFINED — define falsifiers in the decision memo before acting"
        ),
        "post_outcome_review_date": review_date or "unset (observed_at unusable)",
    }


def annotate_items(items: list[dict]) -> list[dict]:
    """Attach ``model_quality`` to each inbox item (best-effort, no raise)."""
    try:
        try:
            from scripts.data_quality import read_ledger as read_evidence
            from scripts.derived_score_ledger import read_ledger as read_scores
        except ModuleNotFoundError:  # pragma: no cover - script-style env
            from data_quality import read_ledger as read_evidence  # type: ignore[no-redef]
            from derived_score_ledger import read_ledger as read_scores  # type: ignore[no-redef]
        evidence_index = build_evidence_index(read_evidence())
        score_index = build_score_index(read_scores())
    except Exception:  # pragma: no cover - annotation must never break the inbox
        evidence_index, score_index = {}, {}
    for item in items:
        try:
            item["model_quality"] = build_signal_annotation(
                item, evidence_index=evidence_index, score_index=score_index,
            )
        except Exception:  # pragma: no cover
            item["model_quality"] = {
                "advisory_status": ADVISORY_LABEL,
                "human_review": HUMAN_LABEL,
                "evidence_coverage": "annotation failed — treat as unsupported",
            }
    return items
