"""Emit a truthful calibration corpus status report.

proof_loop_hardening_sprint, Phase 2.

Purpose
-------
Wraps :mod:`scripts.curate_calibration_corpus` to produce a small,
machine-readable status file at
``runtime/release/calibration_corpus_status.json`` whose only job is to
report:

* ``N_total``, ``N_real``
* ``N_excluded_fixture``, ``N_excluded_mock``, ``N_excluded_synthetic``
* ``N_missing_probability``, ``N_missing_outcome``, ``N_missing_horizon``
* ``calibration_status`` (per the sprint's tier table)
* ``output path`` of the corpus envelope that was inspected
* ``provenance_kind`` ∈ {REAL, EMPTY, FIXTURE, SYNTHETIC, DEMO_ONLY,
  INSUFFICIENT_EVIDENCE}

Safety
~~~~~~
* Read-only by default (``--dry-run`` is the default).
* Never fabricates outcomes.
* Never opens broker, order, fill, position, or execution endpoints.
* Advisory-only stamps on every output row.

Math
~~~~
``calibration_status`` maps from ``N_real`` per the sprint table:

::

    N_real = 0                          -> INSUFFICIENT_EVIDENCE
    1  <= N_real < 20                   -> TOO_FEW_OUTCOMES
    20 <= N_real < 200                  -> MEASURABLE_WITH_WARNING
    N_real >= 200                       -> MEASURED
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.curate_calibration_corpus import (  # noqa: E402
    build_corpus,
    validate_corpus,
)


SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_mode": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
    "human_review_required": True,
    "canonical_store": "sqlite",
    "jsonl_is_canonical": False,
}


def classify_status(n_real: int) -> str:
    n = int(n_real)
    if n <= 0:
        return "INSUFFICIENT_EVIDENCE"
    if n < 20:
        return "TOO_FEW_OUTCOMES"
    if n < 200:
        return "MEASURABLE_WITH_WARNING"
    return "MEASURED"


def classify_provenance(records: list[dict[str, Any]], n_real: int) -> str:
    """Pick a single provenance_kind stamp for the corpus envelope."""
    if not records:
        return "EMPTY"
    if n_real == 0:
        # All rows came from fixtures, mocks, or synthetic sources.
        if all(str(r.get("source", "")).lower() == "fixture_test_only" for r in records):
            return "FIXTURE"
        return "INSUFFICIENT_EVIDENCE"
    return "REAL"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compute_status(
    *,
    from_sqlite: Path | None,
    include_polymarket_closed: bool,
    from_fixture: Path | None,
    max_records: int,
) -> dict[str, Any]:
    """Pure compute: build corpus in-memory, return the status dict."""
    envelope = build_corpus(
        from_sqlite=from_sqlite,
        include_polymarket_closed=include_polymarket_closed,
        from_fixture=from_fixture,
        max_records=max_records,
    )
    records = envelope.get("records") or []
    metrics = envelope.get("metrics") or validate_corpus(records)

    n_total = int(metrics.get("n_total", 0))
    n_real = int(metrics.get("n_real", 0))
    n_fixture = int(metrics.get("n_fixture", 0))
    n_mock = int(metrics.get("n_mock", 0))
    # n_valid_p in upstream metrics counts records with a usable p in [0,1].
    n_valid_p = int(metrics.get("n_valid_p", 0))
    n_valid_y = int(metrics.get("n_valid_y", 0))
    n_missing_probability = max(0, n_total - n_valid_p)
    n_missing_outcome = max(0, n_total - n_valid_y)

    # Horizon missing — derived from the corpus rows directly.
    def _has_horizon(r: dict[str, Any]) -> bool:
        try:
            return float(r.get("horizon_days") or 0.0) > 0.0
        except (TypeError, ValueError):
            return False

    n_missing_horizon = sum(1 for r in records if not _has_horizon(r))

    # Synthetic rows: callers may stamp provenance.synthetic=True.
    def _is_synthetic(r: dict[str, Any]) -> bool:
        prov = r.get("provenance") or {}
        return bool(prov.get("synthetic"))

    n_synthetic = sum(1 for r in records if _is_synthetic(r))

    status = classify_status(n_real)
    provenance_kind = classify_provenance(records, n_real)

    return {
        "script": "calibration_corpus_status.py",
        "generated_at_utc": _utc_now_iso(),
        "sources_used": envelope.get("sources_used", []),
        "N_total": n_total,
        "N_real": n_real,
        "N_excluded_fixture": n_fixture,
        "N_excluded_mock": n_mock,
        "N_excluded_synthetic": n_synthetic,
        "N_missing_probability": int(n_missing_probability),
        "N_missing_outcome": int(n_missing_outcome),
        "N_missing_horizon": int(n_missing_horizon),
        "calibration_status": status,
        "provenance_kind": provenance_kind,
        "corpus_envelope_path": None,
        "thresholds": {
            "TOO_FEW_OUTCOMES_below": 20,
            "MEASURABLE_WITH_WARNING_below": 200,
            "MEASURED_at_least": 200,
        },
        "warning": (
            "INSUFFICIENT_EVIDENCE — no calibratable rows.  No predictive "
            "validity is claimed."
            if status == "INSUFFICIENT_EVIDENCE"
            else (
                f"calibration_status={status} (N_real={n_real})."
                if status != "MEASURED"
                else ""
            )
        ),
        **SAFETY_STAMPS,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Truthful calibration corpus status report.  Default is dry-run "
            "(no writes).  Pass --write to persist the JSON report."
        )
    )
    parser.add_argument(
        "--from-sqlite",
        type=Path,
        default=_REPO_ROOT / "runtime" / "mvp_local.db",
        help="Path to canonical SQLite (default runtime/mvp_local.db).",
    )
    parser.add_argument(
        "--include-polymarket-closed",
        action="store_true",
        help="Opt in to fetching public Polymarket closed markets (GET-only).",
    )
    parser.add_argument(
        "--from-fixture",
        type=Path,
        default=None,
        help="Optional JSON file of test fixture records (counted as FIXTURE).",
    )
    parser.add_argument("--max-records", type=int, default=250)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Default.  Compute the status but do not write any file.",
    )
    group.add_argument(
        "--write",
        action="store_true",
        help="Persist the status JSON to --output.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_REPO_ROOT / "runtime" / "release" / "calibration_corpus_status.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    # Guard against accidental SQLite reads when the file is absent.
    from_sqlite: Path | None = args.from_sqlite
    if from_sqlite is not None and not Path(from_sqlite).exists():
        from_sqlite = None

    report = compute_status(
        from_sqlite=from_sqlite,
        include_polymarket_closed=bool(args.include_polymarket_closed),
        from_fixture=args.from_fixture,
        max_records=int(args.max_records),
    )

    sys.stdout.write(
        f"calibration corpus status: N_real={report['N_real']} "
        f"N_total={report['N_total']} status={report['calibration_status']} "
        f"provenance={report['provenance_kind']}\n"
    )

    if args.write:
        out = Path(args.output)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            report["corpus_envelope_path"] = str(out)
            out.write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            sys.stdout.write(f"wrote {out}\n")
        except OSError as exc:  # pragma: no cover
            sys.stderr.write(f"could not write status: {type(exc).__name__}\n")
            return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
