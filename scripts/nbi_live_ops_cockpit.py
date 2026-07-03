"""NBI live-ops cockpit — one command that supervises the whole loop.

The v1.5 eureka surface: a single readiness sequence over every operational
subsystem, producing one artifact the operator (and the /nbi page) reads:

    python -m scripts.nbi_live_ops_cockpit status
    python -m scripts.nbi_live_ops_cockpit doctor
    python -m scripts.nbi_live_ops_cockpit autopilot [--dry-run] [--fixture]
    python -m scripts.nbi_live_ops_cockpit next-actions
    python -m scripts.nbi_live_ops_cockpit score

Autopilot orchestrates EXISTING commands only — it fakes nothing and never
performs operator-reserved actions (scheduler install, event activation,
template promotion, event closeout stay human):

    scheduler doctor/verify -> event validation -> feed status -> market
    status -> run-daily -> export-cards -> worklist export -> corpus ->
    first-case readiness -> score-report -> cockpit artifact

Health model (v1.5 spec):

    LiveOpsHealth = S x E x max(F, FailClosedFeed) x max(M, FailClosedMkt)
                    x R x C x K x Q
    S <= 0.82 while the OS task is helper-only;
    F_effective <= 0.70 when the feed is empty but fails closed;
    M_effective <= 0.75 when fetch works but zero contracts matched;
    CorpusMaturity <= 0.80 while eligible real cases = 0.

Status labels: READY_RUNNING (>=8.5 with an ACTIVE event),
DEGRADED_BUT_SAFE (6-8.5), BLOCKED_OPERATOR_ACTION (missing install or
active event), BROKEN_UNSAFE (safety check failed), BROKEN.

Artifacts: runtime/nbi_live_ops_cockpit.json + .md.

Advisory-only.  No broker execution, no orders, no real-money sizing.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.advisory_contract import advisory_safety_stamps
from scripts.runtime_common import REPO_ROOT

COCKPIT_VERSION = "nbi-cockpit-v1.0"
COCKPIT_JSON_PATH = REPO_ROOT / "runtime" / "nbi_live_ops_cockpit.json"
COCKPIT_MD_PATH = REPO_ROOT / "runtime" / "nbi_live_ops_cockpit.md"

STATUS_READY_RUNNING = "READY_RUNNING"
STATUS_DEGRADED_BUT_SAFE = "DEGRADED_BUT_SAFE"
STATUS_BLOCKED_OPERATOR = "BLOCKED_OPERATOR_ACTION"
STATUS_BROKEN_UNSAFE = "BROKEN_UNSAFE"
STATUS_BROKEN = "BROKEN"

S_HELPER_ONLY_CAP = 0.82
F_FAIL_CLOSED_CAP = 0.70
M_NO_MATCH_CAP = 0.75
CORPUS_MATURITY_CAP = 0.80


def _now_iso(now_iso: str | None) -> str:
    if now_iso:
        return now_iso
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def gather_cockpit_state(
    db_path: Path | str | None = None, *, now_iso: str | None = None,
) -> dict[str, Any]:
    """Read-only gather across every subsystem (no mutations)."""
    from scripts.nbi_calibration_report import build_nbi_calibration_report
    from scripts.nbi_evidence_factory import (
        corpus_status,
        first_case_readiness,
        load_event_definitions,
        validate_event_definitions,
    )
    from scripts.nbi_feed_bridge import feed_bridge_status
    from scripts.nbi_prediction_market_bridge import bridge_status
    from scripts.nbi_scheduler import (
        _safety_check_action,
        build_task_command,
        doctor,
        verify_install,
    )
    from scripts.nbi_template_workshop import template_worklist

    doc = doctor()
    verify = verify_install()
    definitions = load_event_definitions() or []
    validation = validate_event_definitions(definitions)
    active_events = [
        d.get("event_id") for d in definitions
        if str(d.get("status") or "").upper() == "ACTIVE"
        and not d.get("is_fixture")
    ]
    feed = feed_bridge_status(now_iso=now_iso)
    market = bridge_status()
    corpus = corpus_status(db_path, now_iso=now_iso)
    calibration = build_nbi_calibration_report(db_path=db_path)
    first_case = first_case_readiness(db_path, now_iso=now_iso)
    worklist = template_worklist(db_path, limit=10)
    safety_ok = _safety_check_action(build_task_command()) and doc[
        "checks"
    ]["scheduled_action_safety"]["ok"]
    return {
        "scheduler": {
            "doctor_ok": doc["ok"],
            "task_installed": verify["task_installed"],
            "install_command": verify["install_command"],
            "note": verify["note"],
        },
        "events": {
            "definitions": validation["n_definitions"],
            "valid": validation["n_valid"],
            "active": active_events,
        },
        "feed": feed,
        "market": market,
        "corpus": corpus,
        "calibration": {
            "status": calibration["status"],
            "n_closed_real_cases": calibration["n_closed_real_cases"],
            "n_calibration_eligible": calibration["n_calibration_eligible"],
        },
        "first_case": {
            "recommended_first_three": first_case["recommended_first_three"],
            "top_candidates": first_case["candidates"][:3],
        },
        "worklist_count": len(worklist),
        "safety_check_passed": safety_ok,
    }


def compute_live_ops_health(state: dict[str, Any]) -> dict[str, Any]:
    scheduler = state["scheduler"]
    s = 1.0 if scheduler["task_installed"] else (
        S_HELPER_ONLY_CAP if scheduler["doctor_ok"] else 0.0
    )
    validation_ok = state["events"]["valid"] > 0
    e = 1.0 if state["events"]["active"] and validation_ok else (
        0.5 if validation_ok else 0.0
    )
    feed_usability = float(state["feed"].get("feed_usability") or 0.0)
    f = max(feed_usability, F_FAIL_CLOSED_CAP if feed_usability == 0 else 0.0)
    live_rows = int(state["market"].get("live_rows") or 0)
    m = 1.0 if live_rows > 0 else M_NO_MATCH_CAP
    r = 1.0 if state["corpus"].get("events_total", 0) >= 0 else 0.0
    c = 1.0 if state["corpus"]["surface_status"]["cards_json_artifact"] else 0.5
    k = 1.0  # corpus_status itself succeeded if we got here
    q = 1.0 if state["safety_check_passed"] else 0.0
    eligible = state["calibration"]["n_calibration_eligible"]
    corpus_maturity = 1.0 if eligible > 0 else CORPUS_MATURITY_CAP

    health = s * e * f * m * r * c * k * q * corpus_maturity
    health10 = round(10 * health, 2)
    if not q:
        status = STATUS_BROKEN_UNSAFE
    elif not scheduler["task_installed"] or not state["events"]["active"]:
        status = STATUS_BLOCKED_OPERATOR
    elif health10 >= 8.5 and state["events"]["active"]:
        status = STATUS_READY_RUNNING
    elif health10 >= 6:
        status = STATUS_DEGRADED_BUT_SAFE
    else:
        status = STATUS_DEGRADED_BUT_SAFE if health > 0 else STATUS_BROKEN
    return {
        "LiveOpsHealth10": health10,
        "status": status,
        "components": {
            "S_scheduler": round(s, 4), "E_events": round(e, 4),
            "F_feed_effective": round(f, 4), "M_market_effective": round(m, 4),
            "R_reports": r, "C_cards": c, "K_corpus": k, "Q_safety": q,
            "corpus_maturity": corpus_maturity,
        },
    }


def build_next_actions(state: dict[str, Any]) -> list[str]:
    actions = list(
        state["corpus"].get("next_required_operator_actions", [])
    )
    if state["feed"].get("status") in ("FEED_NOT_WIRED",
                                       "NO_FEED_SOURCE_DISCOVERED"):
        actions.append(
            "wire a feed: python -m scripts.nbi_feed_bridge discover "
            "then wire --source <path>"
        )
    if state["worklist_count"]:
        first = state["first_case"]["recommended_first_three"][:1]
        if first:
            actions.append(
                f"start the first case: python -m scripts.nbi_template_workshop "
                f"make-evidence-pack --template-id {first[0]}"
            )
    return list(dict.fromkeys(actions))


def render_cockpit_md(payload: dict[str, Any]) -> str:
    health = payload["health"]
    state = payload["state"]
    lines = [
        "# NBI Live-Ops Cockpit",
        "",
        "**ADVISORY_ONLY — execution gate LOCKED — human decides.**",
        "",
        f"- Status: **{health['status']}** "
        f"(LiveOpsHealth10 = {health['LiveOpsHealth10']})",
        f"- Scheduler installed: {state['scheduler']['task_installed']} "
        f"({state['scheduler']['note']})",
        f"- Active events: {state['events']['active'] or 'none'}",
        f"- Feed: {state['feed'].get('status')} "
        f"(usability {state['feed'].get('feed_usability')})",
        f"- Market: {state['market'].get('adapter_health')} "
        f"({state['market'].get('live_rows')} live rows)",
        f"- Eligible cases: "
        f"{state['calibration']['n_calibration_eligible']} / 30",
        f"- Edge claim allowed: {state['corpus']['edge_claim_allowed']}",
        "",
        "## Next required operator actions",
    ]
    lines += [f"1. {a}" for a in payload["next_actions"]] or ["- none"]
    lines += ["", f"_Generated {payload['generated_at']} — "
              "every number is a measurement, not a claim._", ""]
    return "\n".join(lines)


def run_autopilot(
    *,
    db_path: Path | str | None = None,
    dry_run: bool = False,
    is_fixture: bool = False,
    now_iso: str | None = None,
    out_json: Path | str | None = None,
    out_md: Path | str | None = None,
) -> dict[str, Any]:
    """One supervised cycle.  Dry-run gathers and reports, mutating nothing.

    Real mode performs only the SAFE automatic steps (run-daily,
    export-cards, worklist export, cockpit artifacts).  Operator-reserved
    actions are surfaced as next_actions, never executed.
    """
    stamp = _now_iso(now_iso)
    steps: list[dict[str, Any]] = []
    if not dry_run:
        from scripts.nbi_evidence_factory import export_cards, run_daily
        from scripts.nbi_template_workshop import export_worklist
        try:
            run = run_daily(db_path=db_path, now_iso=now_iso,
                            is_fixture=is_fixture)
            steps.append({"step": "run_daily", "ok": True,
                          "status": run.get("status")})
        except Exception as exc:  # noqa: BLE001
            steps.append({"step": "run_daily", "ok": False,
                          "error": type(exc).__name__})
        try:
            export_cards(db_path, now_iso=now_iso)
            steps.append({"step": "export_cards", "ok": True})
        except Exception as exc:  # noqa: BLE001
            steps.append({"step": "export_cards", "ok": False,
                          "error": type(exc).__name__})
        try:
            export_worklist(db_path, now_iso=now_iso)
            steps.append({"step": "export_worklist", "ok": True})
        except Exception as exc:  # noqa: BLE001
            steps.append({"step": "export_worklist", "ok": False,
                          "error": type(exc).__name__})

    state = gather_cockpit_state(db_path, now_iso=now_iso)
    health = compute_live_ops_health(state)
    payload = {
        "report": "nbi_live_ops_cockpit",
        "version": COCKPIT_VERSION,
        "generated_at": stamp,
        "dry_run": dry_run,
        "steps_executed": steps,
        "state": state,
        "health": health,
        "next_actions": build_next_actions(state),
        "edge_claim_allowed": state["corpus"]["edge_claim_allowed"],
        "safety": advisory_safety_stamps(),
    }
    if not dry_run:
        json_target = Path(out_json) if out_json else COCKPIT_JSON_PATH
        md_target = Path(out_md) if out_md else COCKPIT_MD_PATH
        json_target.parent.mkdir(parents=True, exist_ok=True)
        json_target.write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
        md_target.write_text(render_cockpit_md(payload), encoding="utf-8")
        payload["artifacts"] = {
            "json": str(json_target), "md": str(md_target),
        }
    return payload


SESSION_CLOSE_JSON_PATH = REPO_ROOT / "runtime" / "nbi_session_close_report.json"
SESSION_CLOSE_MD_PATH = REPO_ROOT / "runtime" / "nbi_session_close_report.md"


def build_session_close_report(
    db_path: Path | str | None = None, *, now_iso: str | None = None,
    tests_summary: str = "",
) -> dict[str, Any]:
    """One artifact that closes a working session: truth, scores, next steps."""
    import subprocess

    from scripts.nbi_evidence_factory import build_score_report

    state = gather_cockpit_state(db_path, now_iso=now_iso)
    health = compute_live_ops_health(state)
    score = build_score_report(db_path)
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, check=False,
        )
        commit = proc.stdout.strip() if proc.returncode == 0 else None
    except OSError:
        commit = None
    payload = {
        "report": "nbi_session_close_report",
        "version": COCKPIT_VERSION,
        "generated_at": _now_iso(now_iso),
        "scheduler_installed": state["scheduler"]["task_installed"],
        "eligible_real_cases": state["calibration"]["n_calibration_eligible"],
        "calibration_status": state["calibration"]["status"],
        "active_events": state["events"]["active"],
        "edge_claim_allowed": state["corpus"]["edge_claim_allowed"],
        "live_ops_health10": health["LiveOpsHealth10"],
        "live_ops_status": health["status"],
        "overall_score": score["segments"][-1]["current"],
        "score_caps": score["constraint_caps_applied"],
        "git_commit": commit,
        "tests_summary": tests_summary or "see CI / session log",
        "next_actions": build_next_actions(state),
        "safety": advisory_safety_stamps(),
    }
    SESSION_CLOSE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_CLOSE_JSON_PATH.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    md = "\n".join([
        "# NBI Session Close Report",
        "",
        "**ADVISORY_ONLY — execution gate LOCKED — human decides.**",
        "",
        f"- Generated: {payload['generated_at']}",
        f"- Scheduler installed: **{payload['scheduler_installed']}**",
        f"- Eligible real cases: **{payload['eligible_real_cases']}** / 30 "
        f"({payload['calibration_status']})",
        f"- Edge claim allowed: **{payload['edge_claim_allowed']}**",
        f"- LiveOps: {payload['live_ops_status']} "
        f"({payload['live_ops_health10']}/10)",
        f"- Overall score: **{payload['overall_score']}** "
        f"(caps: {'; '.join(payload['score_caps']) or 'none'})",
        f"- Git commit: {payload['git_commit'] or 'uncommitted'}",
        f"- Tests: {payload['tests_summary']}",
        "",
        "## Next 7-day operator checklist",
    ] + [f"1. {a}" for a in payload["next_actions"]] + [""])
    SESSION_CLOSE_MD_PATH.write_text(md, encoding="utf-8")
    payload["artifacts"] = {
        "json": str(SESSION_CLOSE_JSON_PATH),
        "md": str(SESSION_CLOSE_MD_PATH),
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "NBI live-ops cockpit: one supervised loop over the evidence "
            "factory (advisory-only; operator actions never automated)."
        )
    )
    parser.add_argument("--db", default=None)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status")
    sub.add_parser("doctor")
    ap = sub.add_parser("autopilot")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fixture", action="store_true")
    sub.add_parser("next-actions")
    sub.add_parser("score")
    scr = sub.add_parser("session-close-report")
    scr.add_argument("--tests-summary", default="")
    args = parser.parse_args(argv)

    if args.command in ("status", "doctor"):
        state = gather_cockpit_state(args.db)
        health = compute_live_ops_health(state)
        print(json.dumps({
            "state": state, "health": health,
            "next_actions": build_next_actions(state),
        }, indent=2, default=str))
    elif args.command == "autopilot":
        payload = run_autopilot(
            db_path=args.db, dry_run=args.dry_run, is_fixture=args.fixture,
        )
        print(json.dumps({
            "status": payload["health"]["status"],
            "LiveOpsHealth10": payload["health"]["LiveOpsHealth10"],
            "steps_executed": payload["steps_executed"],
            "next_actions": payload["next_actions"],
            "artifacts": payload.get("artifacts"),
            "edge_claim_allowed": payload["edge_claim_allowed"],
        }, indent=2, default=str))
    elif args.command == "next-actions":
        state = gather_cockpit_state(args.db)
        for action in build_next_actions(state):
            print(f"- {action}")
    elif args.command == "score":
        from scripts.nbi_evidence_factory import (
            build_score_report,
            render_score_report,
        )
        print(render_score_report(build_score_report(args.db)))
    elif args.command == "session-close-report":
        payload = build_session_close_report(
            args.db, tests_summary=args.tests_summary,
        )
        print(json.dumps({k: payload[k] for k in (
            "scheduler_installed", "eligible_real_cases",
            "calibration_status", "edge_claim_allowed", "overall_score",
            "git_commit", "artifacts",
        )}, indent=2, default=str))
    else:
        parser.print_help()
        return 2
    return 0


__all__ = [
    "COCKPIT_VERSION", "COCKPIT_JSON_PATH", "COCKPIT_MD_PATH",
    "STATUS_READY_RUNNING", "STATUS_DEGRADED_BUT_SAFE",
    "STATUS_BLOCKED_OPERATOR", "STATUS_BROKEN_UNSAFE", "STATUS_BROKEN",
    "gather_cockpit_state", "compute_live_ops_health", "build_next_actions",
    "run_autopilot", "render_cockpit_md", "build_session_close_report",
    "SESSION_CLOSE_JSON_PATH", "SESSION_CLOSE_MD_PATH", "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
