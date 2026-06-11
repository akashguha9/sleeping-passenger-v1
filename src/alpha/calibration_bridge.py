"""Calibration bridge: replay records -> fitted, OOS-validated probability map.

Reuses the repo's existing ``scripts/calibration_map.py`` machinery
(stdlib isotonic PAV + Platt scaling, train/test split, identity
fallback when neither method beats raw out of sample) and adds what it
lacked: model-parameter serialization, so a fitted map becomes a
loadable artifact with provenance.

    raw_probability        = clamp(score / 100, 0, 1)
    calibrated_probability = f_calibration(raw_probability)
    Brier                  = (p − y)^2
    expected_calibration_error =
        Σ_bucket weight_bucket × |mean(p)_bucket − empirical_freq_bucket|

Honesty contract: with fewer resolved outcomes than ``MIN_RESOLVED_FOR_FIT``
this module refuses to fit and reports ``method = "insufficient_data"``
with an identity mapping — a calibrated probability is never invented.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.alpha.replay import classify_outcome
from src.utils.math_utils import clamp01, clip

try:
    from scripts.calibration_map import (
        CalibrationMap,
        IsotonicModel,
        PlattModel,
        fit_calibration_map,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style env
    import sys as _sys

    _repo_root = str(Path(__file__).resolve().parents[2])
    if _repo_root not in _sys.path:
        _sys.path.insert(0, _repo_root)
    from scripts.calibration_map import (  # type: ignore[no-redef]
        CalibrationMap,
        IsotonicModel,
        PlattModel,
        fit_calibration_map,
    )

# Below this many resolved (confirmed/refuted) records, fitting would
# memorise noise; the repo's chooser needs ~12 for a train/test split.
MIN_RESOLVED_FOR_FIT = 12

ARTIFACT_KIND = "alpha_calibration_map"


def extract_probability_outcome_pairs(
    replay_records: list[dict[str, Any]] | None,
) -> list[tuple[float, float]]:
    """(raw probability, outcome) pairs from resolved replay records.

    confirmed -> 1.0, refuted -> 0.0; unresolved records are excluded —
    an unverifiable call must not teach the calibrator anything.
    """
    pairs: list[tuple[float, float]] = []
    for record in replay_records or []:
        outcome = classify_outcome(record)
        if outcome == "unresolved":
            continue
        probability = record.get("raw_event_probability", record.get("event_probability"))
        if probability is None:
            score = record.get("raw_score", record.get("opportunity_score"))
            if score is None:
                continue
            probability = clamp01(float(score) / 100.0)
        pairs.append((clamp01(float(probability)), 1.0 if outcome == "confirmed" else 0.0))
    return pairs


def fit_alpha_calibration_map(
    replay_records: list[dict[str, Any]] | None,
    *,
    method: str = "auto",
) -> tuple[CalibrationMap | None, dict[str, Any]]:
    """Fit a calibration map from replay records, or refuse honestly.

    Returns ``(map_or_None, summary)``.  ``method="auto"`` uses the
    repo's OOS chooser (isotonic vs Platt vs identity); the only other
    accepted value is ``"identity"`` for an explicit no-op map.
    """
    pairs = extract_probability_outcome_pairs(replay_records)
    resolved_count = len(pairs)
    missing_inputs: list[str] = []
    warnings: list[str] = []

    if method == "identity":
        cmap = CalibrationMap(method="identity", train_n=0, test_n=0)
        return cmap, summarize_alpha_calibration(
            cmap, resolved_count=resolved_count, warnings=["identity map requested"]
        )
    if method != "auto":
        raise ValueError("method must be 'auto' or 'identity'")

    if resolved_count < MIN_RESOLVED_FOR_FIT:
        missing_inputs.append(
            f"resolved_replay_records (have {resolved_count}, "
            f"need {MIN_RESOLVED_FOR_FIT})"
        )
        warnings.append(
            "insufficient resolved outcomes: refusing to fit; identity "
            "fallback in force"
        )
        summary = summarize_alpha_calibration(
            None,
            resolved_count=resolved_count,
            warnings=warnings,
            missing_inputs=missing_inputs,
        )
        return None, summary

    cmap = fit_calibration_map(
        [p for p, _ in pairs], [y for _, y in pairs]
    )
    if cmap.method == "identity":
        warnings.append(
            "neither isotonic nor Platt beat raw probabilities out of "
            "sample; identity kept (we do not claim a fit that does not "
            "generalise)"
        )
    return cmap, summarize_alpha_calibration(
        cmap, resolved_count=resolved_count, warnings=warnings
    )


def apply_alpha_calibration(
    raw_probability: float, calibration_map: CalibrationMap | None
) -> float:
    """calibrated_probability = f_calibration(clamp(raw, 0, 1))."""
    raw = clamp01(float(raw_probability))
    if calibration_map is None:
        return raw
    return clamp01(calibration_map.apply(raw))


def calibration_map_to_artifact(cmap: CalibrationMap) -> dict[str, Any]:
    """Serialize a fitted map (parameters + metrics) into a JSON artifact."""
    payload: dict[str, Any] = {
        "kind": ARTIFACT_KIND,
        "method": cmap.method,
        "isotonic": (
            {"xs": list(cmap.isotonic.xs), "ys": list(cmap.isotonic.ys)}
            if cmap.isotonic is not None
            else None
        ),
        "platt": (
            {"a": cmap.platt.a, "b": cmap.platt.b}
            if cmap.platt is not None
            else None
        ),
        "metrics": cmap.to_dict(),
        "advisory_only": True,
    }
    canonical = json.dumps(payload, sort_keys=True, default=str)
    payload["artifact_id"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return payload


def artifact_to_calibration_map(artifact: dict[str, Any]) -> CalibrationMap:
    """Reconstruct a usable map from a serialized artifact."""
    if artifact.get("kind") != ARTIFACT_KIND:
        raise ValueError("not an alpha calibration artifact")
    isotonic = None
    if artifact.get("isotonic"):
        isotonic = IsotonicModel(
            xs=[float(x) for x in artifact["isotonic"]["xs"]],
            ys=[float(y) for y in artifact["isotonic"]["ys"]],
        )
    platt = None
    if artifact.get("platt"):
        platt = PlattModel(
            a=float(artifact["platt"]["a"]), b=float(artifact["platt"]["b"])
        )
    metrics = artifact.get("metrics") or {}
    return CalibrationMap(
        method=str(artifact.get("method", "identity")),
        isotonic=isotonic,
        platt=platt,
        train_n=int(metrics.get("train_n", 0)),
        test_n=int(metrics.get("test_n", 0)),
        raw_test_brier=float(metrics.get("raw_test_brier", 0.0)),
        cal_test_brier=float(metrics.get("cal_test_brier", 0.0)),
        raw_test_ece=float(metrics.get("raw_test_ece", 0.0)),
        cal_test_ece=float(metrics.get("cal_test_ece", 0.0)),
        improved=bool(metrics.get("improved_out_of_sample", False)),
    )


def save_alpha_calibration_map(cmap: CalibrationMap, path: Path | str) -> dict[str, Any]:
    """Write the artifact JSON to an explicit caller-supplied path."""
    artifact = calibration_map_to_artifact(cmap)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact, indent=2, sort_keys=True))
    return artifact


def load_alpha_calibration_map(path: Path | str) -> tuple[CalibrationMap, dict[str, Any]]:
    """Load an artifact and reconstruct the map.  Raises on bad input."""
    artifact = json.loads(Path(path).read_text())
    return artifact_to_calibration_map(artifact), artifact


def summarize_alpha_calibration(
    cmap: CalibrationMap | None,
    *,
    resolved_count: int = 0,
    artifact_path: str | None = None,
    warnings: list[str] | None = None,
    missing_inputs: list[str] | None = None,
) -> dict[str, Any]:
    """Honest one-look summary of calibration state (bounded, explicit)."""
    warnings = list(warnings or [])
    missing_inputs = list(missing_inputs or [])
    calibration_support = clip(
        100.0 * min(1.0, resolved_count / 50.0), 0.0, 100.0
    )
    if cmap is None:
        return {
            "calibration_available": False,
            "method": "insufficient_data",
            "sample_size": 0,
            "resolved_count": resolved_count,
            "brier_before": None,
            "brier_after": None,
            "expected_calibration_error": None,
            "calibration_support": calibration_support,
            "artifact_path": artifact_path,
            "warnings": warnings,
            "missing_inputs": missing_inputs,
        }
    metrics = cmap.to_dict()
    fitted = cmap.method in ("isotonic", "platt")
    return {
        "calibration_available": fitted,
        "method": cmap.method,
        "sample_size": cmap.train_n + cmap.test_n,
        "resolved_count": resolved_count,
        "brier_before": metrics["raw_test_brier"] if cmap.test_n else None,
        "brier_after": metrics["cal_test_brier"] if cmap.test_n else None,
        "expected_calibration_error": (
            metrics["cal_test_ece"] if cmap.test_n else None
        ),
        "calibration_support": calibration_support,
        "artifact_path": artifact_path,
        "warnings": warnings,
        "missing_inputs": missing_inputs,
    }
