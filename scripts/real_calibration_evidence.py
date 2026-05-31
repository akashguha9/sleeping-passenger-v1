"""Real Evidence Sprint — Phase 3: Brier/ECE on real-forward & proxy corpora.

Computes calibration metrics by REUSING the audited primitives in
:mod:`scripts.snapshot_calibration_bridge` (Brier / ECE / LogLoss / MCE), but
keeps three corpora strictly separated:

    real_forward       actual paper/live advisory decisions + later outcomes
    historical_proxy   backtest/proxy labels — research/evidence only
    combined_debug_only  union — DEBUG ONLY, never used for any claim

Honest gate (only ``real_forward`` can ever unlock a predictive claim)::

    CalibrationAllowed = I(N_real_forward >= 200)
                       · I(Brier_real_forward <= 0.25)
                       · I(ECE_real_forward <= 0.10)

``historical_proxy`` metrics are reported but ``predictive_claim_allowed`` is
derived ONLY from ``real_forward``.  With today's corpus (N≈0) the status is
``INSUFFICIENT_EVIDENCE`` and the claim stays locked.

Writes ``runtime/release/calibration_evidence.json``.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # package layout
    from scripts.runtime_common import RUNTIME_DIR, write_json_atomic
    from scripts.snapshot_calibration_bridge import compute_brier_ece
    from scripts.decision_probability_snapshot import (
        TABLE,
        MODEL_VERSION,
        SCORING_VERSION,
        N_MIN,
        BRIER_THRESHOLD,
        ECE_THRESHOLD,
    )
    from scripts.outcome_labeling_flow import (
        REAL_FORWARD,
        HISTORICAL_PROXY,
        _ensure_outcome_columns,
        build_outcome_corpus_summary,
    )
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    from runtime_common import RUNTIME_DIR, write_json_atomic  # type: ignore[no-redef]
    from snapshot_calibration_bridge import compute_brier_ece  # type: ignore[no-redef]
    from decision_probability_snapshot import (  # type: ignore[no-redef]
        TABLE,
        MODEL_VERSION,
        SCORING_VERSION,
        N_MIN,
        BRIER_THRESHOLD,
        ECE_THRESHOLD,
    )
    from outcome_labeling_flow import (  # type: ignore[no-redef]
        REAL_FORWARD,
        HISTORICAL_PROXY,
        _ensure_outcome_columns,
        build_outcome_corpus_summary,
    )

_REPORT_NAME = "calibration_evidence.json"

_SAFETY = {
    "advisory_status": "ADVISORY_ONLY",
    "human_execution_required": True,
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid_p(p: Any) -> bool:
    try:
        pf = float(p)
    except (TypeError, ValueError):
        return False
    return 0.0 <= pf <= 1.0


def extract_datasets(db_path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Split persisted snapshots into ``real_forward`` / ``historical_proxy``.

    A row joins a corpus only when it carries a usable probability AND a binary
    outcome AND is not excluded from calibration.  ``real_forward`` additionally
    requires ``is_real_outcome`` and an elapsed horizon.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        _ensure_outcome_columns(conn)
        rows = conn.execute(
            f"SELECT model_probability, outcome_label, is_real_outcome,"
            f" outcome_kind, excluded_from_calibration, horizon_elapsed FROM {TABLE}"
        ).fetchall()
    finally:
        conn.close()

    real_forward: list[dict[str, Any]] = []
    historical_proxy: list[dict[str, Any]] = []
    for r in rows:
        p, y = r["model_probability"], r["outcome_label"]
        if not _valid_p(p) or y not in (0, 1):
            continue
        if bool(r["excluded_from_calibration"]):
            continue
        pair = {"p": float(p), "y": int(y)}
        kind = r["outcome_kind"]
        if kind == REAL_FORWARD and bool(r["is_real_outcome"]) and bool(r["horizon_elapsed"]):
            real_forward.append(pair)
        elif kind == HISTORICAL_PROXY:
            historical_proxy.append(pair)

    return {
        "real_forward": real_forward,
        "historical_proxy": historical_proxy,
        "combined_debug_only": real_forward + historical_proxy,
    }


def compute_corpus_metrics(
    dataset: list[dict[str, Any]],
    *,
    n_min: int = N_MIN,
    n_buckets: int = 10,
) -> dict[str, Any]:
    """Brier / ECE / LogLoss / MCE for a ``[{p, y}]`` dataset (audited path)."""
    return compute_brier_ece(dataset, n_min=n_min, n_buckets=n_buckets)


def build_calibration_evidence(
    db_path: str | Path,
    *,
    n_min: int = N_MIN,
    n_buckets: int = 10,
    now_utc: str | None = None,
) -> dict[str, Any]:
    """Build the calibration-evidence payload with corpora kept separate."""
    datasets = extract_datasets(db_path)
    rf = compute_corpus_metrics(datasets["real_forward"], n_min=n_min, n_buckets=n_buckets)
    proxy = compute_corpus_metrics(datasets["historical_proxy"], n_min=n_min, n_buckets=n_buckets)
    combined = compute_corpus_metrics(
        datasets["combined_debug_only"], n_min=n_min, n_buckets=n_buckets
    )
    summary = build_outcome_corpus_summary(db_path)

    # ONLY the real-forward corpus can unlock a predictive claim.
    predictive_claim_allowed = bool(rf["predictive_claim_allowed"])
    calibration_status = rf["calibration_status"]

    # Honest sub-status that distinguishes "no real-forward pairs yet" from
    # "the first real-forward pairs have attached but we are still below the
    # N>=200 gate".  Neither ever unlocks a predictive claim.
    n_rf = int(rf["n"])
    if predictive_claim_allowed:
        status_detail = "GATE_PASSED"
    elif n_rf <= 0:
        status_detail = "NO_REAL_FORWARD_PAIRS"
    elif n_rf < N_MIN:
        status_detail = "FIRST_REAL_FORWARD_PAIRS_ATTACHED_BUT_BELOW_GATE"
    else:  # N>=200 but Brier/ECE not met
        status_detail = "GATE_THRESHOLDS_NOT_MET"

    return {
        "generated_at_utc": now_utc or _utc_now_iso(),
        "model_version": MODEL_VERSION,
        "scoring_version": SCORING_VERSION,
        "n_min": n_min,
        "brier_threshold": BRIER_THRESHOLD,
        "ece_threshold": ECE_THRESHOLD,
        # Real-forward (the only gate-relevant corpus).
        "n_real_forward": rf["n"],
        "brier_real_forward": rf["brier"],
        "ece_real_forward": rf["ece"],
        "logloss_real_forward": rf["log_loss"],
        "mce_real_forward": rf["mce"],
        # Historical proxy (research/evidence only).
        "n_historical_proxy": proxy["n"],
        "brier_historical_proxy": proxy["brier"],
        "ece_historical_proxy": proxy["ece"],
        "logloss_historical_proxy": proxy["log_loss"],
        "historical_proxy_status": "HISTORICAL_PROXY_NOT_REAL_FORWARD_CALIBRATION",
        # Combined — DEBUG ONLY, never used for claims.
        "combined_debug_only": {
            "n": combined["n"],
            "brier": combined["brier"],
            "ece": combined["ece"],
            "note": "DEBUG ONLY — mixes real-forward and proxy; never used for claims",
        },
        # Honest gate.
        "calibration_status": calibration_status,
        "status_detail": status_detail,
        "predictive_claim_allowed": predictive_claim_allowed,
        "exclusion_reasons": summary["exclusion_reasons"],
        "corpus": {
            "n_snapshots": summary["n_snapshots"],
            "n_with_outcome": summary["n_with_outcome"],
            "n_valid_p": summary["n_valid_p"],
            "n_excluded": summary["n_excluded"],
        },
        **_SAFETY,
    }


def write_evidence(evidence: dict[str, Any], path: Any = None) -> str:
    target = path or (RUNTIME_DIR / "release" / _REPORT_NAME)
    write_json_atomic(target, dict(evidence))
    return str(target)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    import argparse
    import json

    try:
        from scripts import persistence
    except ModuleNotFoundError:
        import persistence  # type: ignore[no-redef]

    p = argparse.ArgumentParser(description="Real calibration evidence (advisory-only).")
    p.add_argument("--write", action="store_true")
    args = p.parse_args(argv)

    persistence.init_schema()
    evidence = build_calibration_evidence(persistence.DB_PATH)
    if args.write:
        evidence["report_path"] = write_evidence(evidence)
    print(json.dumps({
        "n_real_forward": evidence["n_real_forward"],
        "n_historical_proxy": evidence["n_historical_proxy"],
        "calibration_status": evidence["calibration_status"],
        "predictive_claim_allowed": evidence["predictive_claim_allowed"],
    }, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    raise SystemExit(main(sys.argv[1:]))


__all__ = [
    "extract_datasets",
    "compute_corpus_metrics",
    "build_calibration_evidence",
    "write_evidence",
    "main",
]
