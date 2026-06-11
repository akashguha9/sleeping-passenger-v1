"""Daily model operating loop — one manual command, eleven steps (Pass 6).

NOT a daemon, NOT automation: the owner runs it deliberately, reads the
report, and makes every decision OUTSIDE the system. The loop's job is to
force the honest accumulation of operating history that no amount of
engineering can fake:

  1. evidence ledger validation
  2. new signal capture summary (signal_events since last run window)
  3. derived score ledger append (for inbox signals with evidence)
  4. decision memo generation for newly scored signals
  5. shadow-paper ledger update
  6. due outcome checks (memos whose review date has arrived)
  7. calibration update (provisional below thresholds, and it says so)
  8. tournament update (refuses to rank without OOS sample unless
     labeled provisional)
  9. red-team smoke test
 10. readiness gate summary
 11. daily report → reports/daily_model_loop_<timestamp>.md

Advisory-only: no broker calls, no orders, no execution-shaped output —
the shadow ledger structurally refuses such rows.

Usage:  python scripts/daily_model_operating_loop.py [--db <path>]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
import sys as _sys

if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))
UTC = _dt.timezone.utc
MIN_PROVISIONAL_OOS = 20


def _step(name, fn, results):
    try:
        results.append((name, True, fn()))
    except Exception as exc:
        results.append((name, False, f"{type(exc).__name__}: {exc}"))


def run_loop(db_path: Path | None = None) -> dict:
    from scripts import data_quality as dq
    from scripts import derived_score_ledger as dsl
    from scripts import generate_decision_memo as memo
    from scripts import model_trust_ladder as ladder
    from scripts import redteam_model as rt
    from scripts import signal_annotation as ann
    from scripts.signal_tournament import shadow_ledger_path
    from scripts.score_calibration import compute_score_calibration

    if db_path is None:
        from scripts.runtime_config import get_db_path

        db_path = get_db_path()

    results: list[tuple[str, bool, object]] = []
    now = _dt.datetime.now(UTC)

    # 1. evidence ledger validation
    _step("evidence_ledger_validation",
          lambda: f"{len(dq.verify_ledger())} violation(s); "
                  f"{len(dq.read_ledger())} item(s)", results)

    # 2. new signal capture (last 24h of signal events)
    def capture():
        from scripts.persistence import get_signal_events

        events = get_signal_events(limit=500, db_path=db_path)
        cutoff = (now - _dt.timedelta(hours=24)).isoformat()
        fresh = [e for e in events if str(e.get("fetched_at", "")) >= cutoff]
        return f"{len(fresh)} signal event(s) in the last 24h"
    _step("new_signal_capture", capture, results)

    # 3+4. derived scores + memos for evidence-backed symbols
    def score_and_memo():
        evidence = dq.read_ledger()
        index = ann.build_evidence_index(evidence)
        appended = 0
        memos = 0
        for symbol, items in sorted(index.items()):
            if not symbol:
                continue
            confidence = min(
                1.0, sum(float(i.get("confidence", 0)) for i in items) / len(items)
            )
            memo_path = ""
            try:
                memo_path = str(memo.write_memo({
                    "ticker": symbol,
                    "signal": "daily-loop evidence summary (research note)",
                    "confidence": round(confidence, 3),
                    "evidence_summary": f"{len(items)} ledger item(s)",
                    "temporal_validity": "see evidence ledger stamps",
                    "calibration_context": "provisional — see daily report",
                    "falsifiers": "evidence retraction or contradiction cluster",
                }))
                memos += 1
            except memo.MemoError:
                pass
            dsl.append_score(
                model_name="daily_loop_evidence_summary",
                model_version="pass6",
                symbol=symbol,
                raw_score=round(confidence, 6),
                decision_time_utc=now.isoformat(),
                input_evidence_ids=[i.get("evidence_id", "") for i in items],
                confidence=confidence,
                abstain=True,  # research note: the loop never recommends
                temporal_validity="valid",
                grounding_status="evidence_backed",
                decision_memo_path=memo_path,
            )
            appended += 1
        return f"{appended} derived score(s) appended (all abstain/research), {memos} memo(s)"
    _step("derived_scores_and_memos", score_and_memo, results)

    # 5. shadow ledger state
    _step("shadow_ledger", lambda: (
        f"{sum(1 for _ in shadow_ledger_path().open(encoding='utf-8'))} row(s)"
        if shadow_ledger_path().exists() else "empty — bootstrap or operate to fill"
    ), results)

    # 6. due outcome checks: memos older than 30 days without review
    def due_outcomes():
        memo_dir = memo.MEMO_DIR
        if not memo_dir.exists():
            return "no memos yet"
        due = []
        for p in memo_dir.glob("*.md"):
            age = now - _dt.datetime.fromtimestamp(p.stat().st_mtime, UTC)
            if age.days >= 30:
                due.append(p.name)
        return (f"{len(due)} memo(s) DUE for post-outcome review: "
                + ", ".join(sorted(due)[:5])) if due else "no reviews due"
    _step("due_outcome_checks", due_outcomes, results)

    # 7. calibration (provisional below thresholds; the summary says so)
    def calibration():
        from scripts.persistence import _get_conn

        conn = _get_conn(db_path)
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM reconciliation_results").fetchall()]
        finally:
            conn.close()
        summary = compute_score_calibration(rows)
        return (f"status={summary['calibration_status']} n={summary['sample_size']} "
                f"temporal_uncertain_excluded={summary['temporal_uncertain_excluded']} "
                f"— {summary['message'][:80]}")
    _step("calibration_update", calibration, results)

    # 8. tournament status (refuses real ranking without OOS sample)
    def tournament():
        if not shadow_ledger_path().exists():
            return "INSUFFICIENT DATA — no shadow observations yet (provisional)"
        rows = [json.loads(l) for l in shadow_ledger_path().read_text(
            encoding="utf-8").splitlines() if l.strip()]
        oos = [r for r in rows if r.get("oos") and r.get("outcome_known")]
        if len(oos) < MIN_PROVISIONAL_OOS:
            return (f"PROVISIONAL ONLY — {len(oos)} OOS observation(s) < "
                    f"{MIN_PROVISIONAL_OOS}; ranking refused until more accumulate")
        return f"{len(oos)} OOS observation(s) available for ranking"
    _step("tournament_update", tournament, results)

    # 9. red-team smoke
    _step("redteam_smoke", lambda: (
        lambda cases: f"{sum(1 for c in cases if c['ok'])}/{len(cases)} safe"
    )(rt.run_cases()), results)

    # 10. trust ladder + readiness summary
    def trust():
        result = ladder.evaluate(ladder.current_inputs())
        return f"{result['level']} (caps: {len(result['binding_caps'])}); execution_ready=False"
    _step("trust_ladder", trust, results)

    failures = [name for name, ok, _ in results if not ok]
    return {
        "generated_utc": now.isoformat(),
        "steps": [{"step": n, "ok": ok, "detail": str(d)} for n, ok, d in results],
        "failures": failures,
        "advisory_only": True,
        "human_review_required": True,
        "note": ("Every decision happens OUTSIDE this system. The loop "
                 "records, validates, and reminds; it never acts."),
    }


def write_report(result: dict, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (_REPO_ROOT / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"daily_model_loop_{stamp}.md"
    lines = [
        "# Daily model operating loop", "",
        f"Generated: {result['generated_utc']}",
        "ADVISORY ONLY · HUMAN REVIEW REQUIRED — nothing here executes.", "",
        "| Step | Status | Detail |", "| ---- | ------ | ------ |",
    ]
    for s in result["steps"]:
        lines.append(f"| {s['step']} | {'✅' if s['ok'] else '❌'} | {s['detail'][:140]} |")
    lines += ["", f"> {result['note']}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)
    result = run_loop(Path(args.db) if args.db else None)
    path = write_report(result)
    print(f"[ok] daily loop report: {path}")
    for s in result["steps"]:
        print(f"  [{'ok' if s['ok'] else 'FAIL'}] {s['step']}: {s['detail'][:100]}")
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
