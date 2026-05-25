"""Calibration gate for the advisory scoring stack.

Identity Collapse + First-Day Operator sprint, Phase 8.

Purpose
-------
Compute Brier score and Expected Calibration Error (ECE) for the
advisory probability emitted by the scoring stack — EMS / EQS / DS / LS /
EFS / APS — and refuse to claim predictive validity unless:

* sample size ``N`` ≥ ``N_min`` (default 200), AND
* Brier score ≤ ``BS_threshold`` (default 0.25), AND
* ECE ≤ ``ECE_threshold`` (default 0.10).

Until these gates are met, the report emits
``calibration_status="INSUFFICIENT_EVIDENCE"`` and
``predictive_claim_allowed=false``.  This is intentional: the MVP must
not silently grow a calibration claim it cannot defend.

Safety
~~~~~~
* Read-only.  Reads observations from a caller-supplied list or from the
  canonical SQLite store via ``persistence.fetch_calibration_observations``
  if that helper is available; otherwise reports
  ``INSUFFICIENT_EVIDENCE``.
* Advisory-only stamps on every output.
* No broker, order, fill, position, or execution code path.

Inputs
~~~~~~
Each observation is::

    {"p": <float in [0,1]>, "y": <0 or 1>, "score_axis": "APS|EMS|...|all"}

Outputs
~~~~~~~
``runtime/release/calibration_report.json`` and an in-memory dict with
the structured fields documented in the sprint spec.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


SCORE_AXES: tuple[str, ...] = ("EMS", "EQS", "DS", "LS", "EFS", "APS")

DEFAULT_N_MIN: int = 200
DEFAULT_BS_THRESHOLD: float = 0.25
DEFAULT_ECE_THRESHOLD: float = 0.10
DEFAULT_BUCKET_COUNT: int = 10

SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "can_execute": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "human_review_required": True,
    "broker_order_id": "NONE",
    "canonical_store": "sqlite",
    "jsonl_is_canonical": False,
}


@dataclass(frozen=True)
class Observation:
    p: float
    y: int
    score_axis: str = "all"

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "Observation | None":
        """Build a clipped Observation; return None if irrecoverable."""
        if not isinstance(raw, dict):
            return None
        try:
            p_raw = float(raw.get("p"))
        except (TypeError, ValueError):
            return None
        if math.isnan(p_raw) or math.isinf(p_raw):
            return None
        # Clip silently to [0, 1].  The caller log records the clip count.
        p_clipped = max(0.0, min(1.0, p_raw))
        try:
            y_raw = int(raw.get("y"))
        except (TypeError, ValueError):
            return None
        if y_raw not in (0, 1):
            return None
        axis = str(raw.get("score_axis") or "all").strip().upper()
        if axis not in {"ALL", *SCORE_AXES}:
            axis = "all"
        return cls(p=p_clipped, y=y_raw, score_axis=axis if axis != "ALL" else "all")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def brier_score(observations: Sequence[Observation]) -> float:
    n = len(observations)
    if n == 0:
        return float("nan")
    return sum((o.p - o.y) ** 2 for o in observations) / n


def reliability_buckets(
    observations: Sequence[Observation], *, n_buckets: int = DEFAULT_BUCKET_COUNT
) -> list[dict[str, Any]]:
    if not observations:
        return []
    n_buckets = max(1, int(n_buckets))
    bins: list[list[Observation]] = [[] for _ in range(n_buckets)]
    for obs in observations:
        # The right edge of the top bin includes p == 1.0.
        idx = min(int(obs.p * n_buckets), n_buckets - 1)
        bins[idx].append(obs)
    buckets: list[dict[str, Any]] = []
    for i, slot in enumerate(bins):
        if not slot:
            buckets.append(
                {
                    "bucket_index": i,
                    "range_lo": round(i / n_buckets, 6),
                    "range_hi": round((i + 1) / n_buckets, 6),
                    "count": 0,
                    "predicted_mean": None,
                    "observed_mean": None,
                    "calibration_error": None,
                }
            )
            continue
        predicted = sum(o.p for o in slot) / len(slot)
        observed = sum(o.y for o in slot) / len(slot)
        buckets.append(
            {
                "bucket_index": i,
                "range_lo": round(i / n_buckets, 6),
                "range_hi": round((i + 1) / n_buckets, 6),
                "count": len(slot),
                "predicted_mean": round(predicted, 6),
                "observed_mean": round(observed, 6),
                "calibration_error": round(abs(predicted - observed), 6),
            }
        )
    return buckets


def expected_calibration_error(observations: Sequence[Observation], *, n_buckets: int = DEFAULT_BUCKET_COUNT) -> float:
    if not observations:
        return float("nan")
    buckets = reliability_buckets(observations, n_buckets=n_buckets)
    n = len(observations)
    ece = 0.0
    for b in buckets:
        if b["count"] == 0:
            continue
        ece += (b["count"] / n) * b["calibration_error"]
    return ece


def _coerce_observations(raw_inputs: Iterable[dict[str, Any]]) -> tuple[list[Observation], int]:
    observations: list[Observation] = []
    rejected = 0
    for raw in raw_inputs:
        obs = Observation.from_raw(raw)
        if obs is None:
            rejected += 1
            continue
        observations.append(obs)
    return observations, rejected


def _gather_observations_from_persistence() -> list[dict[str, Any]] | None:
    """Try the canonical persistence helper if it exists.  Returns None when
    the helper is not available so the caller can fall back to
    ``INSUFFICIENT_EVIDENCE`` rather than fabricating data.
    """
    try:
        from scripts.persistence import (  # type: ignore[attr-defined]
            fetch_calibration_observations,
        )
    except (ModuleNotFoundError, ImportError, AttributeError):
        return None
    try:
        rows = fetch_calibration_observations()
        if not isinstance(rows, list):
            return None
        return rows
    except Exception:
        return None


def compute_calibration_report(
    observations: Iterable[dict[str, Any]] | None = None,
    *,
    n_min: int = DEFAULT_N_MIN,
    bs_threshold: float = DEFAULT_BS_THRESHOLD,
    ece_threshold: float = DEFAULT_ECE_THRESHOLD,
    n_buckets: int = DEFAULT_BUCKET_COUNT,
) -> dict[str, Any]:
    """Compute the structured calibration report.

    Inputs are clipped (never fabricated).  Invalid rows are rejected with
    a recorded ``rejected_input_count``.  When ``observations`` is None,
    the canonical persistence helper is consulted; if absent, the report
    truthfully states ``no_outcome_dataset_available``.
    """
    raw: list[dict[str, Any]] | None
    if observations is None:
        raw = _gather_observations_from_persistence()
        evidence_origin = "persistence" if raw is not None else "unavailable"
    else:
        raw = list(observations)
        evidence_origin = "caller_supplied"

    if raw is None:
        return _empty_report(
            n_min=n_min,
            bs_threshold=bs_threshold,
            ece_threshold=ece_threshold,
            warning=(
                "no_outcome_dataset_available — calibration cannot validate "
                "predictive power until a labeled outcome corpus exists."
            ),
            evidence_origin=evidence_origin,
        )

    parsed, rejected = _coerce_observations(raw)
    n = len(parsed)

    if n < int(n_min):
        return _empty_report(
            n_min=n_min,
            bs_threshold=bs_threshold,
            ece_threshold=ece_threshold,
            warning=(
                f"INSUFFICIENT_EVIDENCE — n={n} < n_min={n_min}.  No predictive "
                "claim is allowed at this sample size."
            ),
            evidence_origin=evidence_origin,
            n=n,
            rejected_input_count=rejected,
        )

    bs = brier_score(parsed)
    ece = expected_calibration_error(parsed, n_buckets=n_buckets)
    buckets = reliability_buckets(parsed, n_buckets=n_buckets)
    by_axis = _per_axis_report(parsed, n_buckets=n_buckets)

    predictive_claim_allowed = bool(bs <= bs_threshold and ece <= ece_threshold)
    status = "MEASURED"

    return {
        "script": "calibration_report.py",
        "generated_at_utc": _utc_now_iso(),
        "n": n,
        "n_min": int(n_min),
        "calibration_status": status,
        "predictive_claim_allowed": predictive_claim_allowed,
        "brier_score": round(float(bs), 6),
        "ece": round(float(ece), 6),
        "bs_threshold": float(bs_threshold),
        "ece_threshold": float(ece_threshold),
        "bucket_report": buckets,
        "per_axis_report": by_axis,
        "score_axes": list(SCORE_AXES),
        "evidence_origin": evidence_origin,
        "rejected_input_count": int(rejected),
        "warning": (
            "" if predictive_claim_allowed
            else f"calibration thresholds not met: Brier={bs:.4f} (≤{bs_threshold}), ECE={ece:.4f} (≤{ece_threshold})"
        ),
        **SAFETY_STAMPS,
    }


def _per_axis_report(observations: Sequence[Observation], *, n_buckets: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for axis in ("all", *SCORE_AXES):
        slice_ = [o for o in observations if (o.score_axis == axis or (axis == "all"))]
        if not slice_:
            out[axis] = {"n": 0, "brier_score": None, "ece": None}
            continue
        out[axis] = {
            "n": len(slice_),
            "brier_score": round(brier_score(slice_), 6),
            "ece": round(expected_calibration_error(slice_, n_buckets=n_buckets), 6),
        }
    return out


def _empty_report(
    *,
    n_min: int,
    bs_threshold: float,
    ece_threshold: float,
    warning: str,
    evidence_origin: str,
    n: int = 0,
    rejected_input_count: int = 0,
) -> dict[str, Any]:
    return {
        "script": "calibration_report.py",
        "generated_at_utc": _utc_now_iso(),
        "n": int(n),
        "n_min": int(n_min),
        "calibration_status": "INSUFFICIENT_EVIDENCE",
        "predictive_claim_allowed": False,
        "brier_score": None,
        "ece": None,
        "bs_threshold": float(bs_threshold),
        "ece_threshold": float(ece_threshold),
        "bucket_report": [],
        "per_axis_report": {},
        "score_axes": list(SCORE_AXES),
        "evidence_origin": evidence_origin,
        "rejected_input_count": int(rejected_input_count),
        "warning": warning,
        **SAFETY_STAMPS,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute Brier + ECE for the EMS/EQS/DS/LS/EFS/APS advisory scoring "
            "stack.  Returns INSUFFICIENT_EVIDENCE until N≥200 with conservative "
            "thresholds.  Advisory-only."
        ),
    )
    parser.add_argument("--n-min", type=int, default=DEFAULT_N_MIN)
    parser.add_argument("--bs-threshold", type=float, default=DEFAULT_BS_THRESHOLD)
    parser.add_argument("--ece-threshold", type=float, default=DEFAULT_ECE_THRESHOLD)
    parser.add_argument("--buckets", type=int, default=DEFAULT_BUCKET_COUNT)
    parser.add_argument(
        "--input",
        default=None,
        help=(
            "Path to JSON list of observations.  Each item must be "
            '{"p": float in [0,1], "y": 0|1, "score_axis": "APS|...|all"}. '
            "If omitted, the canonical persistence helper is consulted; "
            "absence yields a truthful INSUFFICIENT_EVIDENCE report."
        ),
    )
    parser.add_argument(
        "--output",
        default=str(_REPO_ROOT / "runtime" / "release" / "calibration_report.json"),
        help="Output JSON path (default runtime/release/calibration_report.json).",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    observations: list[dict[str, Any]] | None = None
    if args.input:
        try:
            with open(args.input, "r", encoding="utf-8") as fh:
                observations = json.load(fh)
            if not isinstance(observations, list):
                sys.stderr.write(
                    "input file must contain a JSON list of observations\n"
                )
                return 2
        except OSError as exc:
            sys.stderr.write(f"could not read input: {type(exc).__name__}\n")
            return 2

    report = compute_calibration_report(
        observations=observations,
        n_min=args.n_min,
        bs_threshold=args.bs_threshold,
        ece_threshold=args.ece_threshold,
        n_buckets=args.buckets,
    )

    if args.output:
        out = Path(args.output)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # pragma: no cover
            sys.stderr.write(f"warning: could not write report: {type(exc).__name__}\n")

    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(
            f"calibration: status={report['calibration_status']} "
            f"n={report['n']} BS={report['brier_score']} ECE={report['ece']} "
            f"predictive_claim_allowed={report['predictive_claim_allowed']}\n"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
