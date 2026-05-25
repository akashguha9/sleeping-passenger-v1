"""AI report ingestion — normalize five-model reports into AIReportSignal.

Integrated Sprint — Part 4.  The repo already has:

* ``scripts.ai_output_schema`` — validates raw AI output,
* ``scripts.model_signal_normalizer`` — collapses raw multi-model reports,
* ``scripts.model_reliability_ledger`` — scores each model's reliability,
* ``scripts.model_disagreement`` — scores disagreement.

This module adds the *integrated sprint surface*: one canonical AIReportSignal
record per (model, asset) plus consensus, weighted-disagreement, DIABLO veto,
and a JSON summary the release gate reads at
``runtime/release/ai_ingestion_summary.json``.

Stance numeric mapping (per sprint spec)::

    BULLISH      +1.00
    NEUTRAL       0.00
    WAIT          0.00
    BEARISH      -1.00
    AVOID        -0.50
    NO_NEW_RISK  -0.75
    DIABLO       -1.00  (also: hard_veto=True)

Pure module; no DB, no broker calls, no execution, no AI execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_PATH = REPO_ROOT / "runtime" / "release" / "ai_ingestion_summary.json"

STANCE_NUMERIC: dict[str, float] = {
    "BULLISH": 1.00,
    "NEUTRAL": 0.00,
    "WAIT": 0.00,
    "BEARISH": -1.00,
    "AVOID": -0.50,
    "NO_NEW_RISK": -0.75,
    "DIABLO": -1.00,
}

STANCES_WITH_HARD_VETO: frozenset[str] = frozenset({"DIABLO"})

DISAGREEMENT_REFERENCE = 1.0
RELIABILITY_EWMA_LAMBDA = 0.85
DEFAULT_DIAGREE_VETO = 0.60


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp01(value: float) -> float:
    if value is None or math.isnan(value):
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _clamp_pm1(value: float) -> float:
    if value is None or math.isnan(value):
        return 0.0
    if value < -1.0:
        return -1.0
    if value > 1.0:
        return 1.0
    return value


def _report_id(model_name: str, generated_at_utc: str, asset_tags: list[str],
               raw_text: str) -> str:
    payload = "|".join([
        str(model_name).lower(),
        str(generated_at_utc),
        ",".join(sorted(asset_tags or [])),
        hashlib.sha256(str(raw_text or "").encode("utf-8")).hexdigest()[:16],
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single AI report dict into the AIReportSignal schema.

    Missing fields degrade conservatively: an absent confidence is 0.0 (no
    earned confidence), an unknown stance becomes NEUTRAL, missing asset_tags
    is an empty list (which never promotes).
    """
    model_name = str(report.get("model_name") or report.get("model") or "").strip()
    family = str(report.get("model_family") or "").strip() or model_name.split("/")[0]
    generated = str(report.get("generated_at_utc") or "")
    asset_tags = list(report.get("asset_tags") or [])
    raw_text = str(report.get("raw_text") or report.get("body") or "")

    stance_raw = str(report.get("stance") or "NEUTRAL").upper()
    if stance_raw not in STANCE_NUMERIC:
        stance_raw = "NEUTRAL"

    try:
        confidence = float(report.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = _clamp01(confidence)

    def _clamp_or_zero(key: str) -> float:
        try:
            return _clamp01(float(report.get(key, 0.0)))
        except (TypeError, ValueError):
            return 0.0

    return {
        "report_id": _report_id(model_name, generated, asset_tags, raw_text),
        "model_name": model_name,
        "model_family": family,
        "generated_at_utc": generated,
        "ingested_at_utc": _utc_iso(),
        "asset_tags": asset_tags,
        "stance": stance_raw,
        "stance_numeric": STANCE_NUMERIC[stance_raw],
        "confidence": confidence,
        "time_horizon": str(report.get("time_horizon") or "").strip() or None,
        "why_today_score": _clamp_or_zero("why_today_score"),
        "risk_score": _clamp_or_zero("risk_score"),
        "invalidation_quality": _clamp_or_zero("invalidation_quality"),
        "evidence_quality": _clamp_or_zero("evidence_quality"),
        "raw_text_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        if raw_text else None,
        "extracted_claims": list(report.get("extracted_claims") or []),
        "hard_veto": stance_raw in STANCES_WITH_HARD_VETO,
        "advisory_only": True,
        "human_review_required": True,
        "execution_permission": "ADVISORY_ONLY",
    }


def compute_consensus(
    normalized: Iterable[dict[str, Any]],
    *,
    asset: str | None = None,
    reliabilities: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Aggregate normalized reports for a single asset (or unfiltered).

    Returns unweighted and reliability-weighted mean / variance / disagreement.
    """
    rows = [r for r in normalized
            if asset is None or asset in (r.get("asset_tags") or [])]
    if not rows:
        return {
            "asset": asset,
            "model_count": 0,
            "mean_signal": 0.0,
            "variance": 0.0,
            "disagreement": 0.0,
            "weighted_mean_signal": 0.0,
            "weighted_disagreement": 0.0,
            "consensus_confidence": 0.0,
            "hard_veto": False,
            "models": [],
        }

    rel = dict(reliabilities or {})
    signals = []
    weights = []
    hard_veto = False
    for r in rows:
        s = float(r.get("stance_numeric", 0.0)) * float(r.get("confidence", 0.0))
        signals.append(s)
        weights.append(_clamp01(rel.get(r.get("model_name"), 1.0)))
        if r.get("hard_veto"):
            hard_veto = True

    m = len(signals)
    mean = sum(signals) / m
    variance = sum((s - mean) ** 2 for s in signals) / m
    disagreement = _clamp01(math.sqrt(variance) / max(DISAGREEMENT_REFERENCE, 1e-9))

    w_total = sum(weights) or 1e-9
    weighted_mean = sum(w * s for w, s in zip(weights, signals)) / w_total
    weighted_var = sum(w * (s - weighted_mean) ** 2
                       for w, s in zip(weights, signals)) / w_total
    weighted_disagreement = _clamp01(math.sqrt(weighted_var))

    consensus_confidence = _clamp01(abs(mean) * (1.0 - disagreement))

    return {
        "asset": asset,
        "model_count": m,
        "mean_signal": round(_clamp_pm1(mean), 6),
        "variance": round(variance, 6),
        "disagreement": round(disagreement, 6),
        "weighted_mean_signal": round(_clamp_pm1(weighted_mean), 6),
        "weighted_disagreement": round(weighted_disagreement, 6),
        "consensus_confidence": round(consensus_confidence, 6),
        "hard_veto": bool(hard_veto),
        "models": [r.get("model_name") for r in rows],
    }


def cqs_ai_adjustment(cqs_base: float, weighted_disagreement: float) -> float:
    """``CQS_base * (1 - 0.25 * D_weighted)``; clamps to [0,1]."""
    return round(
        _clamp01(cqs_base) * (1.0 - 0.25 * _clamp01(weighted_disagreement)),
        6,
    )


def reliability_update(
    *,
    calibration_score: float,
    directional_hit: bool | int,
    invalidation_quality: float,
    evidence_quality: float,
    why_today_score: float,
    risk_penalty: float = 0.0,
) -> float:
    """One-shot reliability_update_m per the sprint spec formula."""
    update = (
        0.45 * _clamp01(calibration_score)
        + 0.25 * (1.0 if directional_hit else 0.0)
        + 0.15 * _clamp01(invalidation_quality)
        + 0.10 * _clamp01(evidence_quality)
        + 0.05 * _clamp01(why_today_score)
        - max(0.0, float(risk_penalty))
    )
    return round(_clamp01(update), 6)


def rolling_reliability(
    previous: float,
    update: float,
    *,
    lambda_: float = RELIABILITY_EWMA_LAMBDA,
) -> float:
    """``λ * R_{t-1} + (1-λ) * update``; clamps to [0,1]."""
    lam = _clamp01(lambda_)
    value = lam * _clamp01(previous) + (1.0 - lam) * _clamp01(update)
    return round(_clamp01(value), 6)


def build_ingestion_summary(
    reports: Iterable[dict[str, Any]],
    *,
    reliabilities: dict[str, float] | None = None,
    cqs_base: float | None = None,
    write_summary: bool = True,
    summary_path: Path | None = None,
) -> dict[str, Any]:
    """Top-level entry — normalize, aggregate, optionally persist a summary."""
    normalized = [normalize_report(r) for r in reports]
    assets = sorted({a for r in normalized for a in (r.get("asset_tags") or [])})
    consensus_by_asset = {
        a: compute_consensus(normalized, asset=a, reliabilities=reliabilities)
        for a in assets
    }
    any_hard_veto = any(c["hard_veto"] for c in consensus_by_asset.values()) \
        or any(r["hard_veto"] for r in normalized)
    avg_disagreement = (
        sum(c["disagreement"] for c in consensus_by_asset.values())
        / max(len(consensus_by_asset), 1)
    )
    weighted_avg_disagreement = (
        sum(c["weighted_disagreement"] for c in consensus_by_asset.values())
        / max(len(consensus_by_asset), 1)
    )
    cqs_adjustment = None
    if cqs_base is not None:
        cqs_adjustment = cqs_ai_adjustment(cqs_base, weighted_avg_disagreement)

    summary = {
        "report": "ai_ingestion_summary",
        "generated_at_utc": _utc_iso(),
        "model_count": len({r.get("model_name") for r in normalized
                            if r.get("model_name")}),
        "report_count": len(normalized),
        "asset_count": len(assets),
        "assets": assets,
        "consensus_by_asset": consensus_by_asset,
        "average_disagreement": round(avg_disagreement, 6),
        "weighted_average_disagreement": round(weighted_avg_disagreement, 6),
        "any_hard_veto": any_hard_veto,
        "cqs_base": cqs_base,
        "cqs_ai_adjusted": cqs_adjustment,
        "normalized_reports": normalized,
        "ai_ingestion_ok": True,
        "advisory_only": True,
        "human_review_required": True,
        # Spread contract stamps first, then re-assert our string-form
        # execution_permission so it is not overwritten by the contract's
        # boolean alias.
        **_contract.advisory_safety_stamps(),
        "execution_permission": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
    }

    if write_summary:
        target = summary_path or DEFAULT_SUMMARY_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(summary, indent=2, default=str),
                       encoding="utf-8")
        tmp.replace(target)
        summary["summary_path"] = str(target)
    return summary


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ai_report_ingestion.py",
        description=(
            "Normalize AI reports into AIReportSignal, aggregate consensus + "
            "disagreement, and optionally persist a summary. Read-only; "
            "advisory-only; no broker calls."
        ),
    )
    p.add_argument("--reports-file", type=str, default=None,
                   help="JSON file with a list of raw AI reports")
    p.add_argument("--reliabilities-file", type=str, default=None,
                   help="JSON file with {model_name: reliability_score}")
    p.add_argument("--cqs-base", type=float, default=None)
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    reports: list[dict[str, Any]] = []
    if args.reports_file:
        reports = list(json.loads(Path(args.reports_file)
                                  .read_text(encoding="utf-8")))
    reliabilities = None
    if args.reliabilities_file:
        reliabilities = dict(json.loads(Path(args.reliabilities_file)
                                        .read_text(encoding="utf-8")))
    summary = build_ingestion_summary(
        reports,
        reliabilities=reliabilities,
        cqs_base=args.cqs_base,
        write_summary=args.write_summary,
    )
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print("AI Report Ingestion Summary (advisory)")
        print("======================================")
        for key in ("model_count", "report_count", "asset_count",
                    "average_disagreement", "any_hard_veto",
                    "cqs_ai_adjusted"):
            print(f"  {key:<32} : {summary.get(key)}")
    return 0


__all__ = [
    "STANCE_NUMERIC",
    "STANCES_WITH_HARD_VETO",
    "DISAGREEMENT_REFERENCE",
    "RELIABILITY_EWMA_LAMBDA",
    "DEFAULT_SUMMARY_PATH",
    "normalize_report",
    "compute_consensus",
    "cqs_ai_adjustment",
    "reliability_update",
    "rolling_reliability",
    "build_ingestion_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
