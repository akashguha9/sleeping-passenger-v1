"""AI / API integration readiness — schema validity, model coverage,
independence, reliability ledger, disagreement-routing wiring.

Integrated Sprint — Part 10 (Kanté defensive batch 2).  Aggregates the
existing :mod:`scripts.ai_report_ingestion`, :mod:`scripts.model_reliability_ledger`,
:mod:`scripts.five_model_independence`, and :mod:`scripts.model_disagreement_handling`
modules into a single AI-integration readiness summary at
``runtime/release/ai_integration_readiness_summary.json``.

No outbound AI calls; reports are read from caller-supplied dicts (or the
deterministic fixture) so the gate is reproducible in CI.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts import advisory_contract as _contract
    from scripts import five_model_independence as _fmi
    from scripts import model_disagreement_handling as _mdh
except ModuleNotFoundError:  # pragma: no cover
    import advisory_contract as _contract  # type: ignore[no-redef]
    import five_model_independence as _fmi  # type: ignore[no-redef]
    import model_disagreement_handling as _mdh  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_PATH = (
    REPO_ROOT / "runtime" / "release" / "ai_integration_readiness_summary.json"
)

EXPECTED_MODELS = _fmi.EXPECTED_MODELS

REQUIRED_REPORT_KEYS: tuple[str, ...] = (
    "model_name", "stance", "confidence", "asset_tags",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp01(v: float) -> float:
    if v < 0:
        return 0.0
    if v > 1:
        return 1.0
    return v


def schema_valid(report: dict[str, Any]) -> bool:
    if not isinstance(report, dict):
        return False
    for k in REQUIRED_REPORT_KEYS:
        if k not in report:
            return False
        value = report[k]
        if value is None:
            return False
        if isinstance(value, str) and not value.strip():
            return False
    try:
        conf = float(report.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return False
    if not 0.0 <= conf <= 1.0:
        return False
    if not isinstance(report.get("asset_tags"), list):
        return False
    return True


def _ai_integration_score(
    *,
    schema_valid_score: float,
    model_coverage_score: float,
    independence_score: float,
    reliability_ledger_present: bool,
    disagreement_routes_to_gate: bool,
    diablo_veto_routes_to_gate: bool,
) -> float:
    raw = (
        0.25 * _clamp01(schema_valid_score)
        + 0.20 * _clamp01(model_coverage_score)
        + 0.20 * _clamp01(independence_score)
        + 0.15 * (1.0 if reliability_ledger_present else 0.0)
        + 0.10 * (1.0 if disagreement_routes_to_gate else 0.0)
        + 0.10 * (1.0 if diablo_veto_routes_to_gate else 0.0)
    )
    return round(10.0 * _clamp01(raw), 4)


def _model_reliability_ledger_present() -> bool:
    """Importable presence + at least one known constructor function exists.

    Works in both package-form (``from scripts import …``) and script-form
    (``python scripts/ai_integration_readiness.py``) imports.
    """
    mrl = None
    try:
        from scripts import model_reliability_ledger as mrl  # type: ignore
    except ModuleNotFoundError:
        try:
            import model_reliability_ledger as mrl  # type: ignore[no-redef]
        except ModuleNotFoundError:
            return False
    return any(
        hasattr(mrl, sym)
        for sym in (
            "build_ledger", "reliability_for", "calibrate_confidence",
            "calibration_error", "ModelReliabilityLedger",
        )
    )


def _fixture_reports() -> list[dict[str, Any]]:
    """One schema-valid report per expected model + one bad-schema row."""
    base = [
        {"model_name": m, "stance": "BULLISH",
         "confidence": 0.75 + i * 0.02,
         "asset_tags": ["ABC", "XYZ"],
         "report_id": f"fixture-{m}",
         "outcome_status": "PENDING" if i % 2 else "COMPLETED"}
        for i, m in enumerate(EXPECTED_MODELS)
    ]
    base.append({
        # Bad schema — missing asset_tags.
        "model_name": "rogue", "stance": "BULLISH",
        "confidence": 0.8,
    })
    return base


def _fixture_asset_signals() -> list[dict[str, Any]]:
    """Reuse the model_disagreement_handling fixture to verify routing wiring."""
    return _mdh._fixture_assets()


def build_summary(
    reports: Iterable[dict[str, Any]] | None = None,
    asset_signals: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reports = list(reports) if reports is not None else _fixture_reports()
    asset_signals = (
        list(asset_signals) if asset_signals is not None
        else _fixture_asset_signals()
    )
    valid = [r for r in reports if schema_valid(r)]
    invalid = [r for r in reports if not schema_valid(r)]
    schema_valid_score = (
        len(valid) / len(reports) if reports else 0.0
    )
    seen_models = {
        str(r.get("model_name", "")).lower() for r in valid
    }
    model_coverage_score = (
        len(seen_models & set(EXPECTED_MODELS)) / len(EXPECTED_MODELS)
    )

    # Independence — reuse fmi.ModelRun for every schema-valid report.
    fmi_runs = []
    for i, r in enumerate(valid):
        if r["model_name"].lower() not in EXPECTED_MODELS:
            continue
        fmi_runs.append(_fmi.ModelRun(
            model_name=r["model_name"].lower(),
            prompt=f"prompt-{r['model_name']}",
            input_context="ctx",
            output=f"{r['model_name']}-{r['stance']}",
            run_order=i + 1,
        ))
    indep = _fmi.independence_score(fmi_runs)

    # Disagreement routing wiring.
    mdh_summary = _mdh.build_summary(asset_signals)
    diablo_veto_count = mdh_summary["diablo_veto_count"]
    high_disagreement_count = mdh_summary["high_disagreement_count"]

    pending = sum(
        1 for r in valid
        if str(r.get("outcome_status", "")).upper() == "PENDING"
    )
    completed = sum(
        1 for r in valid
        if str(r.get("outcome_status", "")).upper() == "COMPLETED"
    )

    reliability_present = _model_reliability_ledger_present()
    disagreement_routes = high_disagreement_count >= 1
    diablo_routes = diablo_veto_count >= 1

    score = _ai_integration_score(
        schema_valid_score=schema_valid_score,
        model_coverage_score=model_coverage_score,
        independence_score=indep["independence_score"],
        reliability_ledger_present=reliability_present,
        disagreement_routes_to_gate=disagreement_routes,
        diablo_veto_routes_to_gate=diablo_routes,
    )
    return {
        "report": "ai_integration_readiness_summary",
        "ok": score >= 9.5,
        "generated_at_utc": _utc_iso(),
        "reports_ingested": len(reports),
        "reports_valid": len(valid),
        "reports_rejected": len(invalid),
        "models_seen": sorted(seen_models),
        "expected_models": list(EXPECTED_MODELS),
        "schema_valid_score": round(schema_valid_score, 6),
        "model_coverage_score": round(model_coverage_score, 6),
        "independence_score": indep["independence_score"],
        "reliability_ledger_present": reliability_present,
        "pending_outcome_count": pending,
        "completed_outcome_count": completed,
        "diablo_veto_count": diablo_veto_count,
        "high_disagreement_count": high_disagreement_count,
        "disagreement_routes_to_gate": disagreement_routes,
        "diablo_veto_routes_to_gate": diablo_routes,
        "ai_integration_score": score,
        "advisory_only": True,
        **_contract.advisory_safety_stamps(),
    }


def write_summary(path: Path | None = None,
                  reports: Iterable[dict[str, Any]] | None = None,
                  asset_signals: Iterable[dict[str, Any]] | None = None,
                  ) -> dict[str, Any]:
    target = path or DEFAULT_SUMMARY_PATH
    summary = build_summary(reports, asset_signals)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    tmp.replace(target)
    summary["summary_path"] = str(target)
    return summary


def read_summary(path: Path | None = None) -> dict[str, Any] | None:
    target = path or DEFAULT_SUMMARY_PATH
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ai_integration_readiness.py")
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = write_summary() if args.write_summary else build_summary()
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"ai_integration_score = {summary['ai_integration_score']}")
        print(f"  schema_valid_score    = {summary['schema_valid_score']}")
        print(f"  model_coverage_score  = {summary['model_coverage_score']}")
        print(f"  independence_score    = {summary['independence_score']}")
        print(f"  reliability_present   = {summary['reliability_ledger_present']}")
        print(f"  diablo_routes/high    = "
              f"{summary['diablo_veto_routes_to_gate']}/"
              f"{summary['disagreement_routes_to_gate']}")
    return 0


__all__ = [
    "DEFAULT_SUMMARY_PATH", "EXPECTED_MODELS", "REQUIRED_REPORT_KEYS",
    "schema_valid", "build_summary", "write_summary", "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
