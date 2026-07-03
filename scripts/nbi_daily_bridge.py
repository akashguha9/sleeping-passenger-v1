"""NBI daily bridge — event cards into daily synthesis, demote-only.

Closes "NBI not in daily synthesis".  Two responsibilities:

1. ``build_nbi_daily_section(reports)`` — the operator-facing daily block:
   one compact card summary per active event (branches, rumor verdict,
   disagreement, surviving/killed layers, rotated + downgraded tickers,
   hedge, action, verify-next, evidence links).  With no active events it
   returns a clean ``NO_ACTIVE_NBI_EVENTS`` block — never noise.

2. ``attach_nbi_to_integration(integration, reports)`` — composes NBI onto
   the chicken-gate integration rows via
   ``narrative_branch_engine.integrate_with_chicken_gate``:

       INTEGRATED_FINAL_SCORE_new = min(existing, NBI ticker final)
       FINAL_ACTION_GATE_new      = min-rank(existing, NBI cap)

   Strictly demote-only (tested): a row is never upgraded, rows unknown to
   NBI are untouched, and FINAL_EXECUTABLE can only flip True -> False.

``build_nbi_daily(integration, db_path=...)`` is the fail-closed wrapper the
daily synthesis pipeline calls: any storage error degrades to
NO_ACTIVE_NBI_EVENTS with the original integration returned byte-identical
in behaviour — the daily report can never be broken by NBI.

Advisory-only.  No broker calls, no execution surface.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from scripts.advisory_contract import advisory_safety_stamps
from scripts.narrative_branch_engine import (
    DEMO_EVENT,
    build_event_report,
    integrate_with_chicken_gate,
    render_event_card,
)

NBI_DAILY_VERSION = "nbi-daily-v1.0"
NO_ACTIVE_NBI_EVENTS = "NO_ACTIVE_NBI_EVENTS"

_GATE_RANK = {"BUY_BLOCKED": 0, "WATCHLIST": 1, "BUY_LIMITED": 2, "BUY_ALLOWED": 3}
GATE_BUY_ALLOWED = "BUY_ALLOWED"


def _card_summary(report: dict[str, Any]) -> dict[str, Any]:
    scores = report.get("scores", {})
    return {
        "event_id": report.get("event_id"),
        "event_name": report.get("event_name"),
        "state": report.get("EVENT_STATE"),
        "action": report.get("ACTION"),
        "action_why": report.get("action_why"),
        "branches": {
            name: info.get("p")
            for name, info in report.get("branches", {}).items()
        },
        "rumor_risk": scores.get("RUMOR_RISK"),
        "rumor_verdict": report.get("rumor", {}).get("verdict"),
        "source_disagreement": scores.get("SOURCE_DISAGREEMENT"),
        "narrative_confidence": scores.get("NARRATIVE_CONFIDENCE"),
        "operator_action_score": scores.get("OPERATOR_ACTION"),
        "surviving_layer": report.get("surviving_layer", {}).get("sentence"),
        "top_tickers": [
            {"ticker": t["ticker"], "score": t["FINAL_TICKER_SCORE"],
             "status": t["status"]}
            for t in report.get("tickers", [])[:5]
        ],
        "downgraded_tickers": report.get("downgraded_tickers", []),
        "hedge": report.get("hedge", {}),
        "verify_next": report.get("verify_next", []),
        "evidence_refs": sorted({
            ref for t in report.get("tickers", [])
            for ref in t.get("evidence_refs", [])
        })[:10],
    }


def build_nbi_daily_section(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """The daily operator block.  Quiet by design when nothing is active."""
    if not reports:
        return {
            "status": NO_ACTIVE_NBI_EVENTS,
            "version": NBI_DAILY_VERSION,
            "events": [],
            "cards_text": [],
            "safety": advisory_safety_stamps(),
        }
    return {
        "status": "ACTIVE",
        "version": NBI_DAILY_VERSION,
        "events": [_card_summary(r) for r in reports],
        "cards_text": [render_event_card(r) for r in reports],
        "safety": advisory_safety_stamps(),
    }


def attach_nbi_to_integration(
    integration: dict[str, Any],
    reports: list[dict[str, Any]],
) -> dict[str, Any]:
    """Demote-only composition of NBI onto chicken-gate integration rows."""
    out = copy.deepcopy(integration) if isinstance(integration, dict) else {}
    section = build_nbi_daily_section(reports)
    out["nbi"] = section
    if not reports:
        return out

    demoted: list[str] = []
    for row in out.get("rows", []):
        ticker = str(row.get("TICKER") or "")
        if not ticker:
            continue
        chicken_view = {
            "FINAL_SCORE": row.get("INTEGRATED_FINAL_SCORE"),
            "FINAL_ACTION_GATE": row.get("FINAL_ACTION_GATE"),
        }
        for report in reports:
            composed = integrate_with_chicken_gate(chicken_view, report, ticker)
            if not composed.get("nbi_applied"):
                continue
            before_score = row.get("INTEGRATED_FINAL_SCORE")
            before_gate = str(row.get("FINAL_ACTION_GATE") or "")
            new_score = composed["INTEGRATED_FINAL_SCORE"]
            new_gate = composed["INTEGRATED_GATE"]
            # Belt-and-braces demote-only: min() again against the row.
            if before_score is not None:
                new_score = min(float(before_score), float(new_score))
            if _GATE_RANK.get(new_gate, 0) > _GATE_RANK.get(before_gate, 0):
                new_gate = before_gate
            if (new_score != before_score) or (new_gate != before_gate):
                demoted.append(ticker)
                row["NBI_DEMOTION"] = {
                    "event_id": report.get("event_id"),
                    "nbi_ticker_status": composed.get("nbi_ticker_status"),
                    "nbi_action": composed.get("nbi_action"),
                    "score_before": before_score,
                    "gate_before": before_gate,
                }
            row["INTEGRATED_FINAL_SCORE"] = new_score
            row["FINAL_ACTION_GATE"] = new_gate
            row["FINAL_EXECUTABLE"] = bool(row.get("FINAL_EXECUTABLE")) and (
                new_gate == GATE_BUY_ALLOWED
            )
            chicken_view = {
                "FINAL_SCORE": new_score, "FINAL_ACTION_GATE": new_gate,
            }
    if demoted:
        out["nbi_demotions"] = sorted(set(demoted))
        existing = out.get("demotions")
        if isinstance(existing, list):
            out["demotions"] = sorted(set(existing) | set(demoted))
    return out


def build_nbi_daily(
    integration: dict[str, Any],
    *,
    db_path: Path | str | None = None,
    reports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fail-closed pipeline entry: NBI can never break the daily report.

    Loads active persisted reports (fixtures excluded) unless ``reports``
    is supplied; ANY loading failure degrades to NO_ACTIVE_NBI_EVENTS and
    leaves the integration untouched (an ``nbi.load_error`` note discloses
    the degradation — silent failure is not allowed either).
    """
    if reports is None:
        try:
            from scripts.nbi_store import load_active_nbi_reports
            reports = load_active_nbi_reports(db_path)
        except Exception as exc:  # noqa: BLE001 - disclose + degrade
            out = copy.deepcopy(integration) if isinstance(integration, dict) else {}
            out["nbi"] = {
                "status": NO_ACTIVE_NBI_EVENTS,
                "version": NBI_DAILY_VERSION,
                "events": [], "cards_text": [],
                "load_error": type(exc).__name__,
                "safety": advisory_safety_stamps(),
            }
            return out
    return attach_nbi_to_integration(integration, reports)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NBI daily bridge: print the daily NBI section."
    )
    parser.add_argument("--db", default=None, help="DB path (default canonical)")
    parser.add_argument(
        "--demo", action="store_true",
        help="Use the in-memory Guwahati->Delhi demo event instead of the DB",
    )
    args = parser.parse_args(argv)
    if args.demo:
        reports = [build_event_report(json.loads(json.dumps(DEMO_EVENT)))]
    else:
        from scripts.nbi_store import load_active_nbi_reports
        reports = load_active_nbi_reports(args.db)
    section = build_nbi_daily_section(reports)
    if section["status"] == NO_ACTIVE_NBI_EVENTS:
        print(NO_ACTIVE_NBI_EVENTS)
        return 0
    for card in section["cards_text"]:
        print(card)
        print()
    print(f"# {len(section['events'])} active NBI event(s) | ADVISORY_ONLY")
    return 0


__all__ = [
    "NBI_DAILY_VERSION", "NO_ACTIVE_NBI_EVENTS",
    "build_nbi_daily_section", "attach_nbi_to_integration",
    "build_nbi_daily", "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
