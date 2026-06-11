"""Bootstrap real signal history into shadow-paper observations (Pass 6).

The final-score ceiling is real out-of-sample history. This tool starts
the honest accumulation: it reads the journal that already exists
(manual trades joined to reconciliations via the canonical
outcome-evidence extractor), validates every sample through the temporal
guard, and normalizes the survivors into shadow-paper observations with
evidence ids and decision timestamps. Invalid and uncertain samples are
REPORTED, never massaged in.

This is record-keeping over past human decisions — nothing here scores,
recommends, or executes.

Usage:  python scripts/bootstrap_signal_history.py [--db <path>]
Output: reports/history_bootstrap_<timestamp>.md + shadow ledger rows.
"""
from __future__ import annotations

import argparse
import datetime as _dt
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
import sys as _sys

if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))


def bootstrap(db_path: Path, *, ledger_path: Path | None = None) -> dict:
    try:
        from scripts.outcome_evidence_extractor import extract_from_db
        from scripts.temporal_guard import validate_sample
        from scripts.signal_tournament import append_shadow_observation
    except ModuleNotFoundError:  # pragma: no cover - script-style env
        from outcome_evidence_extractor import extract_from_db  # type: ignore[no-redef]
        from temporal_guard import validate_sample  # type: ignore[no-redef]
        from signal_tournament import append_shadow_observation  # type: ignore[no-redef]

    outcomes = extract_from_db(db_path)
    report: dict = {
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "outcomes_found": len(outcomes),
        "ingested": 0,
        "temporal_invalid": [],
        "uncertain": [],
        "advisory_only": True,
    }
    for outcome in outcomes:
        opened = getattr(outcome, "opened_at", None)
        closed = getattr(outcome, "closed_at", None)
        label = getattr(outcome, "outcome_label", "UNKNOWN")
        if label not in ("WIN", "LOSS", "BREAKEVEN"):
            report["uncertain"].append({
                "outcome_id": getattr(outcome, "outcome_id", "?"),
                "reason": f"unresolved label {label!r}",
            })
            continue
        verdict = validate_sample(t_decision=opened, t_outcome=closed)
        if not verdict.usable_for_evaluation:
            report["temporal_invalid"].append({
                "outcome_id": getattr(outcome, "outcome_id", "?"),
                "reasons": list(verdict.reasons),
            })
            continue
        ret = getattr(outcome, "realized_return", None)
        append_shadow_observation({
            "variant": "human_journal_history",
            "signal_id": getattr(outcome, "outcome_id", "?"),
            "symbol": getattr(outcome, "ticker", "?"),
            "t_decision": str(opened),
            "t_outcome": str(closed),
            "score": getattr(outcome, "score_at_entry", None),
            "recommendation": "HISTORICAL_HUMAN_DECISION",
            "oos": True,  # history is by definition out-of-sample for models
            "outcome_known": True,
            "net_return_hypothetical": ret,
            "outcome_label": label,
            "source_type": getattr(outcome, "source_type", "?"),
        }, path=ledger_path)
        report["ingested"] += 1
    report["honesty_note"] = (
        "Bootstrap normalizes PAST human decisions for model evaluation. "
        f"{len(report['temporal_invalid'])} sample(s) excluded for temporal "
        f"violations and {len(report['uncertain'])} for unresolved outcomes "
        "— they are listed, not repaired. Real OOS evidence accrues only "
        "from future operating-loop usage."
    )
    return report


def write_report(report: dict, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (_REPO_ROOT / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"history_bootstrap_{stamp}.md"
    lines = [
        "# Signal history bootstrap", "",
        f"Generated: {report['generated_utc']} · advisory-only", "",
        f"- outcomes found: {report['outcomes_found']}",
        f"- ingested into shadow ledger: {report['ingested']}",
        f"- excluded (temporal): {len(report['temporal_invalid'])}",
        f"- excluded (unresolved/uncertain): {len(report['uncertain'])}",
        "", f"> {report['honesty_note']}", "",
    ]
    for item in report["temporal_invalid"][:20]:
        lines.append(f"- temporal: {item['outcome_id']}: {'; '.join(item['reasons'])[:120]}")
    for item in report["uncertain"][:20]:
        lines.append(f"- uncertain: {item['outcome_id']}: {item['reason']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)
    if args.db:
        db_path = Path(args.db)
    else:
        try:
            from scripts.runtime_config import get_db_path
        except ModuleNotFoundError:  # pragma: no cover
            from runtime_config import get_db_path  # type: ignore[no-redef]
        db_path = get_db_path()
    if not db_path.exists():
        print(f"[error] DB not found: {db_path}")
        return 2
    report = bootstrap(db_path)
    path = write_report(report)
    print(f"[ok] ingested {report['ingested']}/{report['outcomes_found']} → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
