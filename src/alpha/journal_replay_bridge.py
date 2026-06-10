"""Journal-to-replay bridge: reconciled advisory outcomes → replay records.

Connects the operator's existing journal (manual trades + reconciliations
+ Moltbook, already extracted read-only by
``scripts/outcome_evidence_extractor``) to the Phase 2 replay harness, so
``calibration_support`` can be computed from real reconciled advisory
outcomes instead of staying at 0 on fixtures.

Honesty rules:
- The journal stores scores, not probabilities.  ``event_probability``
  is derived as ``score/100`` ONLY for calibration-eligible records and
  the derivation is stamped in lineage (``probability_derivation:
  score_proxy``) — the same score→outcome treatment the repo's
  ``scripts/calibration_map.py`` already applies.
- Open/unknown outcomes are skipped with reasons, never guessed.
- Synthetic fixtures are excluded from calibration records.
- Absent DB, absent tables, or schema mismatch degrade to an empty
  dataset with explicit ``missing_inputs`` (the extractor is defensive
  and returns ``[]`` on any failure).

    outcome_coverage = usable_replay_records / max(1, discovered_records)
    calibrated_confidence =
        base_confidence × (0.5 + 0.5 × calibration_support/100) × outcome_coverage
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.alpha.replay import REPLAY_DISCLAIMER, evaluate_replay
from src.utils.math_utils import clip

_RESOLVED_LABELS = {"WIN", "LOSS", "BREAKEVEN"}
_EXCLUDED_SOURCE_TYPES = {"SYNTHETIC_FIXTURE"}


def _normalize_score(value: Any) -> float | None:
    """Normalize a journal score proxy onto 0-100, conservatively.

    Journal score proxies arrive on mixed scales (fractions, 0-10
    confidence, 0-100 scores).  The mapping is recorded in lineage so an
    auditor can trace every normalized value.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    if 0.0 <= number <= 1.0:
        return number * 100.0
    if 0.0 <= number <= 10.0:
        return number * 10.0
    return clip(number, 0.0, 100.0)


def outcome_to_replay_record(
    outcome: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Convert one OutcomeEvidence dict into a replay record.

    Returns ``(record, None)`` on success or ``(None, skip_reason)``.
    """
    source_type = str(outcome.get("source_type") or "")
    if source_type in _EXCLUDED_SOURCE_TYPES:
        return None, "synthetic_fixture_source"
    label = str(outcome.get("outcome_label") or "").upper()
    if label not in _RESOLVED_LABELS:
        return None, "open_or_unknown_outcome"
    score = _normalize_score(outcome.get("score_at_entry"))
    if score is None:
        return None, "missing_score_at_entry"

    realized_return = outcome.get("realized_return")
    price_return = (
        float(realized_return)
        if isinstance(realized_return, (int, float))
        else None
    )
    fundamental = {"WIN": True, "LOSS": False}.get(label)

    calibration_eligible = bool(outcome.get("is_calibration_eligible"))
    record: dict[str, Any] = {
        "signal_id": str(
            outcome.get("signal_id") or outcome.get("outcome_id") or "unknown"
        ),
        "as_of_date": str(outcome.get("opened_at") or ""),
        "theme": str(outcome.get("signal_class") or outcome.get("archetype") or ""),
        "ticker": str(outcome.get("ticker") or ""),
        "opportunity_score": score,
        "confidence": clip(100.0 * float(outcome.get("quality") or 0.0), 0.0, 100.0),
        "verdict": str(outcome.get("archetype") or "journal_entry"),
        "subsequent_observation_window_days": 30,
        "observed_outcome": {
            "price_return": price_return,
            "drawdown": None,
            "fundamental_confirmation": fundamental,
            "narrative_persistence": None,
            "filing_confirmation": None,
        },
        "trap_flags": [],
        "source": "journal_reconciliation",
        "lineage": {
            "outcome_id": str(outcome.get("outcome_id") or ""),
            "trade_id": str(outcome.get("trade_id") or ""),
            "journal_source_type": source_type,
            "outcome_label": label,
            "quality": float(outcome.get("quality") or 0.0),
            "score_normalization": "mixed_scale_to_0_100",
            "probability_derivation": (
                "score_proxy" if calibration_eligible else "none"
            ),
        },
    }
    if calibration_eligible:
        # Score-as-probability proxy, eligible records only; the repo's
        # calibration_map applies the same score->outcome treatment.
        record["event_probability"] = score / 100.0
    return record, None


def build_replay_records_from_journal(
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Extract replay records from the journal DB.  Never raises."""
    missing_inputs: list[str] = []
    try:
        try:
            from scripts.outcome_evidence_extractor import extract_from_db
        except ModuleNotFoundError:  # pragma: no cover - script-style env
            from outcome_evidence_extractor import extract_from_db  # type: ignore[no-redef]
        outcomes = extract_from_db(Path(db_path) if db_path is not None else None)
    except Exception:  # pragma: no cover - defensive
        outcomes = []
    if not outcomes:
        missing_inputs.append("journal_outcomes")

    records: list[dict[str, Any]] = []
    skip_reasons: dict[str, int] = {}
    for outcome in outcomes:
        payload = outcome.to_dict() if hasattr(outcome, "to_dict") else dict(outcome)
        record, skip_reason = outcome_to_replay_record(payload)
        if record is not None:
            records.append(record)
        else:
            skip_reasons[skip_reason] = skip_reasons.get(skip_reason, 0) + 1

    discovered = len(outcomes)
    usable = len(records)
    return {
        "discovered_records": discovered,
        "usable_records": usable,
        "skipped_records": discovered - usable,
        "skip_reasons": skip_reasons,
        "outcome_coverage": usable / max(1, discovered),
        "records": records,
        "missing_inputs": missing_inputs,
    }


def calibrated_confidence(
    base_confidence: float,
    calibration_support: float,
    outcome_coverage: float,
) -> float:
    """base × (0.5 + 0.5 × support/100) × coverage, bounded 0-100."""
    base = clip(base_confidence, 0.0, 100.0)
    support = clip(calibration_support, 0.0, 100.0)
    coverage = clip(outcome_coverage, 0.0, 1.0)
    return clip(base * (0.5 + 0.5 * support / 100.0) * coverage, 0.0, 100.0)


def journal_replay_report(
    db_path: Path | str | None = None,
    *,
    k: int = 5,
) -> dict[str, Any]:
    """Bridge + replay in one deterministic, read-only report."""
    bridge = build_replay_records_from_journal(db_path)
    replay = evaluate_replay(bridge["records"], k=k)
    return {
        "bridge": {
            "discovered_records": bridge["discovered_records"],
            "usable_records": bridge["usable_records"],
            "skipped_records": bridge["skipped_records"],
            "skip_reasons": bridge["skip_reasons"],
            "outcome_coverage": bridge["outcome_coverage"],
            "missing_inputs": bridge["missing_inputs"],
        },
        "replay": replay,
        "calibration_support": replay["calibration_support"],
        "outcome_coverage": bridge["outcome_coverage"],
        "explanation": [
            f"{bridge['discovered_records']} journal outcome(s) discovered, "
            f"{bridge['usable_records']} usable for replay "
            f"(coverage {bridge['outcome_coverage']:.2f}).",
            "Event probabilities are score proxies on calibration-eligible "
            "records only; the derivation is stamped per-record in lineage.",
            f"calibration_support {replay['calibration_support']:.1f}/100 "
            "gates position-candidate verdicts in the opportunity engine.",
        ],
        "disclaimer": REPLAY_DISCLAIMER,
    }
