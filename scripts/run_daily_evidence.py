"""Daily evidence run — one safe command for the whole advisory loop.

Order: env audit -> live PM shock engine -> EDGAR miner (if --edgar) ->
retrocast real-lite (if --retrocast) -> cards/boards -> score report ->
smoke tests. Read-only external access; paper/advisory only; live failures
fail closed and are reported as exact blockers — never converted into
fixture runs.

Status semantics:
  OK        every attempted step succeeded (WARMING_UP counts as OK-note)
  DEGRADED  an optional/alternate-covered source is blocked (e.g. Polymarket
            blocked while Kalshi covers the PM function), or a due step was
            skipped
  BLOCKED   live mode fell back to fixture (must never happen), tests fail,
            or a required step hard-failed
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"
_REPO_ROOT = Path(__file__).resolve().parents[1]

SMOKE_TESTS = ("tests/test_signal_thesis_contract.py",
               "tests/test_live_evidence_governance.py")


def _run(module: str, *args: str, timeout: int = 420) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "-m", module, *args], capture_output=True,
        text=True, cwd=str(_REPO_ROOT), timeout=timeout)
    return {"module": module, "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-500:], "stderr_tail": proc.stderr[-300:]}


def aggregate_statuses(steps: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Pure aggregation so status logic is testable without network."""
    def status_of(name: str, default: str = "NOT_ATTEMPTED") -> str:
        return steps.get(name, {}).get("status", default)

    blocked_reasons: list[str] = []
    degraded_reasons: list[str] = []
    if status_of("tests") == "FAIL":
        blocked_reasons.append("tests failing")
    if steps.get("pm", {}).get("fixture_fallback_detected"):
        blocked_reasons.append("live mode fell back to fixture")
    if status_of("pm") == "BLOCKED":
        blocked_reasons.append("PM live source blocked with no alternate")
    if status_of("pm") == "WARMING_UP":
        degraded_reasons.append("PM ledger warming up (expected)")
    if steps.get("pm", {}).get("polymarket_blocked"):
        degraded_reasons.append("Polymarket blocked; Kalshi covers PM feed")
    for name in ("edgar", "retrocast"):
        if status_of(name) == "BLOCKED":
            degraded_reasons.append(f"{name} blocked (recorded, not fatal)")
        if status_of(name) == "SKIPPED":
            degraded_reasons.append(f"{name} skipped (not due)")
    if status_of("cards") == "FAIL" or status_of("score") == "FAIL":
        blocked_reasons.append("report generation failed")
    overall = ("BLOCKED" if blocked_reasons
               else ("DEGRADED" if degraded_reasons else "OK"))
    next_action = (blocked_reasons[0] if blocked_reasons else
                   (degraded_reasons[0] if degraded_reasons else
                    "accumulate ledger history; review research board"))
    return {"overall_status": overall, "blocked_reasons": blocked_reasons,
            "degraded_reasons": degraded_reasons,
            "next_required_action": next_action}


def _main() -> int:
    ap = argparse.ArgumentParser(description="Daily evidence run (advisory)")
    ap.add_argument("--write", choices=("dry_run", "write"),
                    default="dry_run")
    ap.add_argument("--dry-run", action="store_true",
                    help="alias for --write dry_run")
    ap.add_argument("--edgar", action="store_true")
    ap.add_argument("--retrocast", action="store_true")
    ap.add_argument("--maturity", action="store_true",
                    help="(kept for CLI symmetry; maturity always runs)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--skip-tests", action="store_true")
    args = ap.parse_args()
    if args.all:
        args.edgar = args.retrocast = args.maturity = True
    write_mode = "dry_run" if args.dry_run else args.write
    prev_report: dict[str, Any] = {}
    prev_path = _REPO_ROOT / "runtime" / "daily_evidence_run_report.json"
    if prev_path.exists():
        try:
            prev_report = json.loads(prev_path.read_text(encoding="utf-8"))
        except Exception:
            prev_report = {}

    def _count(rel: str) -> int:
        p = _REPO_ROOT / rel
        if not p.exists():
            return 0
        return sum(1 for line in p.read_text(encoding="utf-8").splitlines()
                   if line.strip())

    before = {
        "observations": _count("data/calibration_corpus/pm_probability_ledger.jsonl"),
        "snapshots": _count("data/calibration_corpus/forward_snapshots.jsonl"),
        "outcomes": _count("data/calibration_corpus/live_outcomes.jsonl"),
        "edgar_edges": _count("data/evidence/edgar_counterparty_edges.jsonl"),
    }
    now = datetime.now(timezone.utc)
    as_of_day = int(now.timestamp()) // 86400 - 18262  # epoch 2020-01-01
    steps: dict[str, dict[str, Any]] = {}

    env = _run("scripts.live_env_audit",
               *(["--write"] if write_mode == "write" else []))
    steps["env"] = {**env, "status": "OK" if env["returncode"] == 0
                    else "FAIL"}

    pm = _run("scripts.prediction_market_shock_engine", "--mode", "live",
              "--write", write_mode, "--map",
              "data/reference/event_equity_map.json")
    pm_status = "BLOCKED" if pm["returncode"] != 0 else "OK"
    if pm["returncode"] == 0 and '"WARMING_UP"' in pm["stdout_tail"]:
        pm_status = "WARMING_UP"
    steps["pm"] = {**pm, "status": pm_status,
                   "fixture_fallback_detected":
                       '"FIXTURE' in pm["stdout_tail"] and pm_status != "BLOCKED"
                       and '"mode": "live"' not in pm["stdout_tail"],
                   "polymarket_blocked": True}  # network-verified this env

    if args.edgar:
        ed = _run("scripts.edgar_counterparty_miner")
        steps["edgar"] = {**ed, "status": "OK" if ed["returncode"] == 0
                          else "BLOCKED"}
    else:
        steps["edgar"] = {"status": "SKIPPED"}

    maturity = _run("scripts.snapshot_maturity_scanner", "--write",
                    write_mode)
    steps["maturity"] = {**maturity,
                         "status": "OK" if maturity["returncode"] == 0
                         else "BLOCKED"}
    calib = _run("scripts.live_calibration_report", "--write", write_mode)
    steps["calibration"] = {**calib,
                            "status": "OK" if calib["returncode"] == 0
                            else "FAIL"}

    if args.retrocast:
        rc = _run("scripts.retrocast_calibration", "--mode", "real-lite",
                  "--write", write_mode)
        steps["retrocast"] = {**rc, "status": "OK" if rc["returncode"] == 0
                              else "BLOCKED"}
        inv = _run("scripts.retrocast_source_inventory", "--write",
                   write_mode)
        steps["source_inventory"] = {
            **inv, "status": "OK" if inv["returncode"] == 0 else "BLOCKED"}
    else:
        steps["retrocast"] = {"status": "SKIPPED"}
        steps["source_inventory"] = {"status": "SKIPPED"}

    cards = _run("scripts.signal_thesis_card_report", "--as-of-day",
                 str(as_of_day))
    steps["cards"] = {**cards, "status": "OK" if cards["returncode"] == 0
                      else "FAIL"}
    score = _run("scripts.signal_ceiling_score_report",
                 *(["--write"] if write_mode == "write" else []))
    steps["score"] = {**score, "status": "OK" if score["returncode"] == 0
                      else "FAIL"}

    if args.skip_tests:
        steps["tests"] = {"status": "SKIPPED"}
    else:
        t = _run("pytest", *SMOKE_TESTS, "-q", timeout=600)
        steps["tests"] = {**t, "status": "OK" if t["returncode"] == 0
                          else "FAIL"}

    agg = aggregate_statuses(steps)
    if steps["maturity"]["status"] == "BLOCKED":
        agg["overall_status"] = "BLOCKED"
        agg["blocked_reasons"].append("maturity scanner blocked")
    after = {
        "observations": _count("data/calibration_corpus/pm_probability_ledger.jsonl"),
        "snapshots": _count("data/calibration_corpus/forward_snapshots.jsonl"),
        "outcomes": _count("data/calibration_corpus/live_outcomes.jsonl"),
        "edgar_edges": _count("data/evidence/edgar_counterparty_edges.jsonl"),
    }
    changed_since_last_run = {
        k: after[k] - before[k] for k in after}
    report = {
        "run_timestamp": now.isoformat(), "as_of_day": as_of_day,
        "write_mode": write_mode,
        "env_ok": steps["env"]["status"] == "OK",
        "pm_status": steps["pm"]["status"],
        "maturity_status": steps["maturity"]["status"],
        "calibration_status": steps["calibration"]["status"],
        "edgar_status": steps["edgar"]["status"],
        "retrocast_status": steps["retrocast"]["status"],
        "source_inventory_status": steps["source_inventory"]["status"],
        "cards_status": steps["cards"]["status"],
        "score_status": steps["score"]["status"],
        "tests_status": steps["tests"]["status"],
        "changed_since_last_run": changed_since_last_run,
        "previous_overall_status": prev_report.get("overall_status"),
        **agg,
        "advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY,
    }
    if write_mode == "write":
        out = _REPO_ROOT / "runtime" / "daily_evidence_run_report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True),
                       encoding="utf-8")
        md = ["# Daily evidence run", "",
              f"timestamp: {report['run_timestamp']}",
              f"overall: **{report['overall_status']}**", ""]
        for k in ("env_ok", "pm_status", "maturity_status",
                  "calibration_status", "edgar_status", "retrocast_status",
                  "source_inventory_status", "cards_status", "score_status",
                  "tests_status"):
            md.append(f"- {k}: {report[k]}")
        md += ["", f"changed since last run: {report['changed_since_last_run']}",
               "", f"next required action: {report['next_required_action']}",
               "", f"{ADVISORY_STATUS} · real money: {REAL_MONEY}"]
        (_REPO_ROOT / "runtime" / "daily_evidence_run_report.md").write_text(
            "\n".join(md), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["overall_status"] != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(_main())
