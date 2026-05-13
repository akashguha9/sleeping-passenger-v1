"""
Signal sensitivity diagnostic — first P1 entry from the diagnostic roadmap.

Purpose
-------
Detect whether a signal's classification is fragile under small numeric
perturbations of its score-like fields. The diagnostic is **deterministic**,
makes **no live calls**, performs **no DB writes**, and never grants any
form of execution permission.

It answers one question:

    "If I nudge this signal's inputs by ±1%, ±3%, ±5%, does the
     classification flip? If yes, treat the signal as fragile."

Formula
-------

    Chaos Sensitivity              = flip_count / perturbation_count
    Classification Stability Score = 1 - Chaos Sensitivity

A high stability score (≥ 0.9) means the classification is robust under
small noise. A low stability score (< 0.6) means the recommendation flips
easily and the signal is fragile.

Safety contract (every output)
------------------------------

    advisory_status        = "ADVISORY_ONLY"
    execution_gate         = "LOCKED"
    broker_api_called      = False
    ai_execution_count     = 0
    execution_permission   = False
    can_execute            = False

This is a *diagnostic*. It does not gate execution, because there is no
execution path. It exists to inform the operator's manual review.

Public API
----------
- ``diagnose_signal_sensitivity(signal, classifier=None, *, perturbations=...)``
- ``default_bucket_classifier(signal)`` -> str
- ``DEFAULT_PERTURBATIONS`` -> tuple[float, ...]
- ``SENSITIVITY_NUMERIC_FIELDS`` -> tuple[str, ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, Iterable

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

# Default perturbation magnitudes (relative). Symmetric around zero is
# applied automatically — e.g. 0.01 generates +1% and -1% probes.
DEFAULT_PERTURBATIONS: tuple[float, ...] = (0.01, 0.03, 0.05)

# Fields the diagnostic considers numeric inputs. If a signal carries
# none of these, the diagnostic returns ``not_applicable``.
SENSITIVITY_NUMERIC_FIELDS: tuple[str, ...] = (
    "confidence_score",
    "reliability_score",
    "freshness_score",
    "narrative_intensity",
    "market_confirmation",
    "contradiction_score",
    "durability_score",
    "probability",
    "price_change",
    "priority_score",
    "persistence_score",
    "blocker_pressure_score",
    "kill_rate_score",
)

CLASSIFICATIONS: tuple[str, ...] = (
    "BLOCKED",
    "WATCHLIST",
    "REVIEW",
    "PROMOTE_FOR_HUMAN_REVIEW",
)

_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
    "may_inform_human_review": True,
    "may_execute": False,
    "may_call_broker": False,
}


def _coerce_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n:  # NaN
        return None
    return n


def _extract_numeric_fields(signal: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in SENSITIVITY_NUMERIC_FIELDS:
        if key in signal:
            n = _coerce_number(signal[key])
            if n is not None:
                out[key] = n
    return out


def default_bucket_classifier(signal: dict[str, Any]) -> str:
    """A deterministic, conservative bucket classifier.

    Logic, in priority order (first match wins):

    1. ``contradiction_score >= 0.7``  -> BLOCKED
    2. ``kill_rate_score    >= 0.8``   -> BLOCKED
    3. ``reliability_score < 0.3``     -> BLOCKED
    4. ``confidence_score < 0.4``      -> WATCHLIST
    5. ``persistence_score < 0.4``     -> WATCHLIST
    6. ``priority_score >= 0.7``       -> PROMOTE_FOR_HUMAN_REVIEW
    7. otherwise                       -> REVIEW

    This is **not** a recommendation. It is a label used by the sensitivity
    harness to detect whether small input noise flips the bucket.
    """
    contradiction = _coerce_number(signal.get("contradiction_score"))
    if contradiction is not None and contradiction >= 0.7:
        return "BLOCKED"
    kill_rate = _coerce_number(signal.get("kill_rate_score"))
    if kill_rate is not None and kill_rate >= 0.8:
        return "BLOCKED"
    reliability = _coerce_number(signal.get("reliability_score"))
    if reliability is not None and reliability < 0.3:
        return "BLOCKED"
    confidence = _coerce_number(signal.get("confidence_score"))
    if confidence is not None and confidence < 0.4:
        return "WATCHLIST"
    persistence = _coerce_number(signal.get("persistence_score"))
    if persistence is not None and persistence < 0.4:
        return "WATCHLIST"
    priority = _coerce_number(signal.get("priority_score"))
    if priority is not None and priority >= 0.7:
        return "PROMOTE_FOR_HUMAN_REVIEW"
    return "REVIEW"


def _build_safe_output(
    *,
    sensitivity: float | None,
    stability: float | None,
    flips: int,
    trials: int,
    fragile: bool,
    recommendation: str,
    baseline_classification: str | None,
    perturbation_classifications: dict[str, str],
    numeric_fields: dict[str, float],
    perturbations: Iterable[float],
    validation_status: str,
    notes: list[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "diagnostic": "signal_sensitivity",
        "chaos_sensitivity_score": sensitivity,
        "classification_stability_score": stability,
        "perturbation_count": trials,
        "flip_count": flips,
        "max_flip_severity": flips,  # alias: same scale, integer flip count
        "fragile": fragile,
        "recommendation": recommendation,
        "baseline_classification": baseline_classification,
        "perturbation_classifications": perturbation_classifications,
        "numeric_fields_considered": sorted(numeric_fields),
        "perturbations_applied": [float(p) for p in perturbations],
        "validation_status": validation_status,
        "notes": list(notes),
    }
    out.update(_SAFETY_STAMPS)
    return out


def diagnose_signal_sensitivity(
    signal: dict[str, Any],
    classifier: Callable[[dict[str, Any]], str] | None = None,
    *,
    perturbations: Iterable[float] = DEFAULT_PERTURBATIONS,
) -> dict[str, Any]:
    """Run the sensitivity diagnostic on a signal-like dict.

    Parameters
    ----------
    signal : dict
        A signal-like mapping. Only numeric fields in
        ``SENSITIVITY_NUMERIC_FIELDS`` are perturbed.
    classifier : callable, optional
        A function ``signal_dict -> classification_label``. Defaults to
        :func:`default_bucket_classifier`.
    perturbations : iterable of float, optional
        Relative perturbation magnitudes. Each generates two probes (±). The
        default is ``(0.01, 0.03, 0.05)`` — six probes per field.

    Returns
    -------
    dict
        A diagnostic record. Always carries the canonical safety stamps and
        never grants any form of execution permission.
    """
    if not isinstance(signal, dict):
        return _build_safe_output(
            sensitivity=None,
            stability=None,
            flips=0,
            trials=0,
            fragile=False,
            recommendation="invalid_input",
            baseline_classification=None,
            perturbation_classifications={},
            numeric_fields={},
            perturbations=perturbations,
            validation_status="invalid",
            notes=["signal_not_a_dict"],
        )

    clf = classifier or default_bucket_classifier
    perts = tuple(float(p) for p in perturbations if isinstance(p, (int, float)) and p > 0)
    if not perts:
        perts = DEFAULT_PERTURBATIONS

    numeric_fields = _extract_numeric_fields(signal)
    baseline_classification = clf(signal)

    if not numeric_fields:
        return _build_safe_output(
            sensitivity=0.0,
            stability=1.0,
            flips=0,
            trials=0,
            fragile=False,
            recommendation="not_applicable",
            baseline_classification=baseline_classification,
            perturbation_classifications={},
            numeric_fields=numeric_fields,
            perturbations=perts,
            validation_status="not_applicable",
            notes=["no_numeric_fields_for_sensitivity_test"],
        )

    perturbation_classifications: dict[str, str] = {}
    flips = 0
    trials = 0
    for field, value in numeric_fields.items():
        for magnitude in perts:
            for sign in (-1, +1):
                trials += 1
                probe = dict(signal)
                probe[field] = value * (1.0 + sign * magnitude)
                label = clf(probe)
                probe_key = f"{field}{'+' if sign > 0 else '-'}{magnitude:.4f}"
                perturbation_classifications[probe_key] = label
                if label != baseline_classification:
                    flips += 1

    sensitivity = flips / trials if trials else 0.0
    stability = max(0.0, 1.0 - sensitivity)
    fragile = sensitivity > 0.0  # any flip on a small perturbation = fragile

    if stability >= 0.9:
        recommendation = "stable"
    elif stability >= 0.6:
        recommendation = "fragile_watchlist"
    else:
        recommendation = "human_review_required"

    return _build_safe_output(
        sensitivity=round(sensitivity, 6),
        stability=round(stability, 6),
        flips=flips,
        trials=trials,
        fragile=fragile,
        recommendation=recommendation,
        baseline_classification=baseline_classification,
        perturbation_classifications=perturbation_classifications,
        numeric_fields=numeric_fields,
        perturbations=perts,
        validation_status="valid",
        notes=[],
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _example_signal() -> dict[str, Any]:
    return {
        "ticker": "EXAMPLE",
        "confidence_score": 0.62,
        "reliability_score": 0.78,
        "contradiction_score": 0.15,
        "kill_rate_score": 0.20,
        "priority_score": 0.55,
        "persistence_score": 0.58,
        "advisory_status": ADVISORY_STATUS,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="signal_sensitivity_diagnostics.py",
        description=(
            "Pure deterministic sensitivity diagnostic for a signal-like "
            "dict. Advisory-only; never grants execution permission."
        ),
    )
    parser.add_argument(
        "--example",
        action="store_true",
        help="Run on a small built-in example signal.",
    )
    parser.add_argument(
        "--json",
        type=str,
        default=None,
        help="Path to a JSON file holding a signal-like object to diagnose.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.example:
        signal = _example_signal()
    elif args.json:
        try:
            signal = json.loads(open(args.json, "r", encoding="utf-8").read())
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"error": f"failed_to_read_json: {exc}"}))
            return 2
    else:
        parser.print_help()
        return 2

    result = diagnose_signal_sensitivity(signal)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "DEFAULT_PERTURBATIONS",
    "SENSITIVITY_NUMERIC_FIELDS",
    "CLASSIFICATIONS",
    "default_bucket_classifier",
    "diagnose_signal_sensitivity",
]


if __name__ == "__main__":
    raise SystemExit(main())
