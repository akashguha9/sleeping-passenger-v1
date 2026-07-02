"""Daily synthesis orchestrator — the corrected pipeline flow.

Wires the four layers into the corrected structure:

    verified_current_holdings + closed/sold + do_not_treat_as_open
    + fresh market scan + old ledger context
    -> Portfolio Truth Gate (Layer 1)
    -> Fresh Market Discovery Gate (Layer 2)
    -> Candidate / Executable split (Layer 3)
    -> Anti-staleness (Layer 4)
    -> rendered Portfolio Truth context block injected into the five prompts

Old ledger context may inform memory but NEVER overrides verified portfolio
truth. This module is advisory/visibility-only — no execution, no broker, no
file mutation beyond writing its own runtime context artifacts.

CLI:
    python scripts/daily_synthesis_pipeline.py            # print context block
    python scripts/daily_synthesis_pipeline.py --json     # print JSON summary
    python scripts/daily_synthesis_pipeline.py --write     # write runtime artifacts
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps, human_only_stamp
    from scripts.anti_staleness import build_anti_staleness
    from scripts.candidate_executable_split import build_candidate_executable_split
    from scripts.chicken_gate_daily_bridge import (
        build_chicken_gate_integration,
        write_override_template,
    )
    from scripts.daily_payload import load_daily_payload, normalize_ticker
    from scripts.fresh_discovery_contract import assert_no_provenance_violation
    from scripts.fresh_market_discovery import build_fresh_market_discovery
    from scripts.portfolio_truth_gate import build_portfolio_truth_gate
    from scripts.runtime_common import REPO_ROOT
    from scripts.why_today import why_today_score
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps, human_only_stamp
    from anti_staleness import build_anti_staleness
    from candidate_executable_split import build_candidate_executable_split
    from chicken_gate_daily_bridge import (
        build_chicken_gate_integration,
        write_override_template,
    )
    from daily_payload import load_daily_payload, normalize_ticker
    from fresh_discovery_contract import assert_no_provenance_violation
    from fresh_market_discovery import build_fresh_market_discovery
    from portfolio_truth_gate import build_portfolio_truth_gate
    from runtime_common import REPO_ROOT
    from why_today import why_today_score


CONTEXT_MD_PATH = REPO_ROOT / "runtime" / "daily_portfolio_truth_context.md"
CONTEXT_JSON_PATH = REPO_ROOT / "runtime" / "daily_synthesis_context.json"


def _compute_why_today_scores(
    payload: dict[str, Any], discovery: dict[str, Any]
) -> dict[str, float]:
    """Derive WHY_TODAY_SCORE per discovered ticker from the daily payload.

    A live news/filing event today is a fresh trigger (1.0). A mover row carries
    its own ``why_today``/``freshness``/``provider``. Yesterday's repeats with no
    fresh change decay toward the stale-repeat floor.
    """
    movers_by_ticker: dict[str, dict[str, Any]] = {}
    for mover in payload["price_movers"]["movers"]:
        ticker = normalize_ticker(mover.get("ticker") or mover.get("symbol"))
        if ticker:
            movers_by_ticker[ticker] = mover

    def _live_event_tickers(rows: list[dict[str, Any]]) -> set[str]:
        out: set[str] = set()
        for row in rows:
            if row.get("is_live") or str(row.get("freshness") or "").upper() in {
                "FRESH_TODAY",
                "UPDATED_TODAY",
            }:
                ticker = normalize_ticker(row.get("ticker") or row.get("symbol"))
                if ticker:
                    out.add(ticker)
        return out

    live_event_tickers = _live_event_tickers(payload["news_events"]["events"]) | _live_event_tickers(
        payload["filings_events"]["events"]
    )
    yesterday = set(payload["yesterday_candidates"]["final_candidates"]) | set(
        payload["yesterday_candidates"]["watchlist"]
    )

    scores: dict[str, float] = {}
    for score in discovery["scored_candidates"]:
        ticker = score["ticker"]
        mover = movers_by_ticker.get(ticker, {})
        provider = str(mover.get("provider") or "").upper()
        is_static = provider == "STATIC_UNIVERSE_FALLBACK" or not mover
        scores[ticker] = round(
            why_today_score(
                mover.get("why_today"),
                freshness=mover.get("freshness"),
                has_live_event_today=ticker in live_event_tickers,
                in_yesterday=ticker in yesterday,
                is_static_universe_only=is_static and ticker not in live_event_tickers,
            ),
            4,
        )
    return scores


def run_daily_synthesis(
    payload_dir: Path | None = None,
    model_candidates: list[str] | None = None,
    features: dict[str, dict[str, Any]] | None = None,
    eqs_features: dict[str, dict[str, Any]] | None = None,
    change_explanations: dict[str, str] | None = None,
    chicken_gate_enabled: bool = True,
    chicken_gate_debug_bypass: bool = False,
    chicken_thesis_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the corrected four-layer flow and return the full result object."""
    payload = load_daily_payload(payload_dir)
    truth_gate = build_portfolio_truth_gate(payload=payload)
    discovery = build_fresh_market_discovery(
        payload=payload, truth_gate=truth_gate,
        model_candidates=model_candidates, features=features,
    )
    why_today_scores = _compute_why_today_scores(payload, discovery)
    split = build_candidate_executable_split(
        discovery, truth_gate, eqs_features=eqs_features,
        why_today_scores=why_today_scores,
    )

    today_candidates = [
        s["ticker"] for s in discovery["buy_candidate_board"]
    ] + [s["ticker"] for s in discovery["watchlist_upgrade_board"]]
    cqs_by_ticker = {s["ticker"]: s["cqs"] for s in discovery["scored_candidates"]}
    anti_staleness = build_anti_staleness(
        payload, today_candidates, truth_gate,
        change_explanations=change_explanations, cqs_by_ticker=cqs_by_ticker,
    )

    # Final advisory layer: every buy-side classified candidate passes
    # through the chicken gate.  Demote-only — the split decision above is
    # never upgraded, never mutated.
    chicken_integration = build_chicken_gate_integration(
        split=split,
        discovery=discovery,
        payload=payload,
        why_today_scores=why_today_scores,
        enabled=chicken_gate_enabled,
        debug_bypass=chicken_gate_debug_bypass,
        thesis_overrides=chicken_thesis_overrides,
    )

    return {
        "run_date": payload["verified_holdings"].get("run_date"),
        "payload": payload,
        "portfolio_truth_gate": truth_gate,
        "fresh_market_discovery": discovery,
        # Top-level alias so callers/artifacts/tests reach the strict gate
        # without digging through the research discovery object.
        "fresh_discovery_contract": discovery.get("fresh_discovery", {}),
        "candidate_executable_split": split,
        "anti_staleness": anti_staleness,
        "why_today_scores": why_today_scores,
        "chicken_gate_integration": chicken_integration,
        "safety": advisory_safety_stamps(),
        "execution": human_only_stamp(),
    }


def render_portfolio_truth_context(result: dict[str, Any]) -> str:
    """Render the Portfolio Truth context block injected into the five prompts.

    This is the text that REPLACES naive pasting of the stale
    moltbook/open_positions.json. It states the verified truth first.
    """
    gate = result["portfolio_truth_gate"]
    discovery = result["fresh_market_discovery"]
    split = result["candidate_executable_split"]
    stale = result["anti_staleness"]

    lines: list[str] = []
    lines.append("============================================================")
    lines.append("PORTFOLIO TRUTH GATE (authoritative — overrides stale rows)")
    lines.append("============================================================")
    lines.append("")
    lines.append("H = V MINUS (C UNION S UNION D) is the ONLY valid current-holdings set.")
    lines.append(f"verified_open_holdings (H): {gate['verified_open_holdings'] or 'NONE'}")
    lines.append(f"closed_or_sold (C UNION S): {gate['closed_or_sold'] or 'NONE'}")
    lines.append(f"do_not_treat_as_open (D): {gate['do_not_treat_as_open'] or 'NONE'}")
    lines.append(
        f"phantom_position_candidates (in stale ledger, NOT holdings): "
        f"{gate['phantom_position_candidates'] or 'NONE'}"
    )
    lines.append(f"can_manage_positions: {gate['can_manage_positions']}")
    lines.append(f"global_discovery_permission: {gate['global_discovery_permission']}")
    lines.append("")
    lines.append("HARD RULES:")
    lines.append("- Only tickers in H may receive exit / TP / stop / hold / runner treatment.")
    lines.append("- UNG, TIP, TLT, FCG, GLD are NOT open unless they appear in H above.")
    lines.append("- Phantom positions must NOT block fresh discovery.")
    lines.append("- Dirty hygiene may block EXECUTABLE buys, never candidate discovery.")
    for note in gate.get("notes", []):
        lines.append(f"  * {note}")
    if gate.get("portfolio_truth_errors"):
        lines.append("PORTFOLIO TRUTH ERRORS:")
        for err in gate["portfolio_truth_errors"]:
            lines.append(f"  ! {err}")
    lines.append("")
    lines.append("------------------------------------------------------------")
    lines.append("FRESH DISCOVERY BOARD (live-verified, current-session ONLY)")
    lines.append("------------------------------------------------------------")
    contract = discovery.get("fresh_discovery", {})
    status = contract.get("status", "NO_FRESH_DISCOVERY_GENERATED")
    lines.append(f"fresh_discovery_status: {status}")
    lines.append(f"current_session_date: {contract.get('current_session_date')}")
    lines.append(f"live_candidate_count: {contract.get('live_candidate_count', 0)}")
    lines.append(f"fresh_discovery_board: {contract.get('fresh_discovery_board') or 'NONE'}")
    if status == "NO_FRESH_DISCOVERY_GENERATED":
        nfd = contract.get("no_fresh_discovery") or {}
        lines.append("  >>> NO_FRESH_DISCOVERY_GENERATED <<<")
        lines.append(f"  reason: {nfd.get('reason')}")
        lines.append(f"  failed_payloads: {nfd.get('failed_payloads')}")
        lines.append(f"  source_health_by_payload: {nfd.get('source_health_by_payload')}")
        lines.append(f"  blocked_fallback_names: {nfd.get('blocked_fallback_names') or 'NONE'}")
        lines.append(f"  next_required_fix: {nfd.get('next_required_fix')}")
    lines.append("")
    lines.append("HARD DISCOVERY RULES (the five models MUST obey):")
    lines.append(
        "- ONLY tickers in fresh_discovery_board above may be presented as fresh "
        "candidates / buy-candidates today."
    )
    lines.append(
        "- If status is NO_FRESH_DISCOVERY_GENERATED, output NO_FRESH_DISCOVERY_GENERATED "
        "and DO NOT invent candidates."
    )
    lines.append(
        "- The names in blocked_fallback_names / the research universe below are "
        "static/fallback/prior/Moltbook/fixture context. They are NOT fresh discovery "
        "and MUST NOT be ranked, promoted, or treated as today's candidates."
    )
    lines.append(
        f"  blocked_fallback_names (NOT fresh): {contract.get('blocked_fallback_names') or 'NONE'}"
    )
    lines.append(
        f"  stale_revalidation_needed (diagnostics only): "
        f"{contract.get('stale_revalidation_needed') or 'NONE'}"
    )
    if contract.get("discovery_provenance_violation"):
        lines.append(
            f"  ! DISCOVERY_PROVENANCE_VIOLATION: {contract.get('provenance_violations')}"
        )
    lines.append("")
    lines.append("RESEARCH/DIAGNOSTIC UNIVERSE (NOT fresh discovery — do not promote):")
    lines.append(f"  research_universe: {discovery['discovery_universe'] or 'NONE'}")
    lines.append(f"  new_tickers_not_seen_yesterday: {discovery['new_tickers_not_seen_yesterday'] or 'NONE'}")
    lines.append(f"  discovery_underpowered: {discovery['discovery_underpowered']}")
    for note in discovery.get("discovery_notes", []):
        lines.append(f"  * {note}")
    lines.append("")
    lines.append("CANDIDATE vs EXECUTABLE SPLIT:")
    lines.append(f"  executable_paper_buys: {[r['ticker'] for r in split['executable_paper_buys']] or 'NONE'}")
    lines.append(
        "  buy_candidate_not_executable: "
        f"{[r['ticker'] for r in split['buy_candidate_not_executable']] or 'NONE'}"
    )
    lines.append(f"  watchlist: {[r['ticker'] for r in split['watchlist'] + split['watchlist_upgrades']] or 'NONE'}")
    lines.append(f"  avoid: {[r['ticker'] for r in split['avoid']] or 'NONE'}")
    lines.append("")
    lines.append("ANTI-STALENESS:")
    lines.append(f"  novelty_ratio: {stale['novelty_ratio']} (min {stale['novelty_ratio_min']})")
    lines.append(f"  stale_discovery_warning: {stale['stale_discovery_warning']}")
    for warning in stale.get("warnings", []):
        lines.append(f"  * {warning}")
    lines.append("")
    lines.append("WHY-TODAY GATE (executable requires why_today_score >= 0.70):")
    why_scores = result.get("why_today_scores", {})
    weak = sorted(t for t, s in why_scores.items() if s < 0.70)
    strong = sorted(t for t, s in why_scores.items() if s >= 0.70)
    lines.append(f"  strong_why_today (>=0.70): {strong or 'NONE'}")
    lines.append(f"  weak_why_today (<0.70, not executable): {weak or 'NONE'}")
    lines.append(
        "  Note: a weak why-today blocks EXECUTABLE but NOT discovery — such names "
        "stay BUY-CANDIDATE / NOT-EXECUTABLE."
    )
    lines.append("")
    chicken = result.get("chicken_gate_integration", {})
    lines.append("CHICKEN GATE (final advisory freshness/asymmetry/node layer):")
    lines.append(f"  mode: {chicken.get('mode')}")
    lines.append(f"  scoring_profile: {chicken.get('scoring_profile_version')}")
    lines.append(f"  final_gate_counts: {chicken.get('final_gate_counts')}")
    lines.append(f"  demotions: {chicken.get('demotions') or 'NONE'}")
    lines.append("  TICKER | existing -> chicken -> final | score | reason")
    for audit_line in chicken.get("audit_lines", []):
        lines.append(f"  {audit_line}")
    summary = chicken.get("chicken_gate_v1_3_summary") or {}
    if summary:
        lines.append("")
        lines.append("EVIDENCE REPAIR LOOP (v1.3):")
        health = chicken.get("payload_health") or {}
        lines.append(
            f"  payload_health_score: {health.get('payload_health_score')} "
            f"(degraded: {health.get('degraded')})"
        )
        if health.get("system_note"):
            lines.append(f"  ! {health['system_note']}")
        lines.append(
            f"  five_model_roundtrip_evaluated: "
            f"{summary.get('five_model_roundtrip_evaluated')}"
            f" (report: {chicken.get('five_model_report') or 'NONE for run_date'})"
        )
        lines.append(f"  top_blockers: {summary.get('top_blockers')}")
        lines.append(f"  top_repair_fields: {summary.get('top_repair_fields')}")
        lines.append(
            f"  top_unlockable_candidates: "
            f"{[u['ticker'] for u in summary.get('top_unlockable_candidates', [])] or 'NONE'}"
        )
        lines.append(
            f"  override_template: {summary.get('override_template_path')}"
        )
    lines.append("")
    lines.append("Reminder: advisory only. No broker action. No execution. Human review required.")
    lines.append("============================================================")
    return "\n".join(lines)


def _write_artifacts(result: dict[str, Any], context_md: str) -> None:
    CONTEXT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTEXT_MD_PATH.write_text(context_md, encoding="utf-8")
    # v1.3: persist the autogenerated operator override template (advisory).
    write_override_template(result.get("chicken_gate_integration", {}))
    contract = result.get("fresh_discovery_contract", {})
    summary = {
        "run_date": result["run_date"],
        "portfolio_truth_gate": result["portfolio_truth_gate"],
        "discovery_universe": result["fresh_market_discovery"]["discovery_universe"],
        "fresh_discovery": {
            "status": contract.get("status"),
            "current_session_date": contract.get("current_session_date"),
            "fresh_discovery_board": contract.get("fresh_discovery_board"),
            "live_candidate_count": contract.get("live_candidate_count"),
            "fallback_candidate_count": contract.get("fallback_candidate_count"),
            "blocked_fallback_names": contract.get("blocked_fallback_names"),
            "stale_revalidation_needed": contract.get("stale_revalidation_needed"),
            "discovery_provenance_violation": contract.get("discovery_provenance_violation"),
            "provenance_violations": contract.get("provenance_violations"),
            "no_fresh_discovery": contract.get("no_fresh_discovery"),
            "provenance_report": contract.get("provenance_report"),
        },
        "executable_paper_buys": [r["ticker"] for r in result["candidate_executable_split"]["executable_paper_buys"]],
        "buy_candidate_not_executable": [
            r["ticker"] for r in result["candidate_executable_split"]["buy_candidate_not_executable"]
        ],
        "anti_staleness": {
            "novelty_ratio": result["anti_staleness"]["novelty_ratio"],
            "stale_discovery_warning": result["anti_staleness"]["stale_discovery_warning"],
        },
        "chicken_gate": {
            "mode": result["chicken_gate_integration"].get("mode"),
            "scoring_profile_version": result["chicken_gate_integration"].get(
                "scoring_profile_version"
            ),
            "final_gate_counts": result["chicken_gate_integration"].get(
                "final_gate_counts"
            ),
            "demotions": result["chicken_gate_integration"].get("demotions"),
            "audit_lines": result["chicken_gate_integration"].get("audit_lines"),
        },
        "chicken_gate_v1_3_summary": result["chicken_gate_integration"].get(
            "chicken_gate_v1_3_summary"
        ),
        "safety": result["safety"],
    }
    CONTEXT_JSON_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily five-model synthesis truth/discovery pipeline.")
    parser.add_argument("--json", action="store_true", help="print the JSON summary instead of the context block")
    parser.add_argument("--write", action="store_true", help="write runtime context artifacts")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    result = run_daily_synthesis()
    context_md = render_portfolio_truth_context(result)
    if args.write:
        _write_artifacts(result, context_md)
    if args.json:
        sys.stdout.write(json.dumps({
            "run_date": result["run_date"],
            "portfolio_truth_gate": result["portfolio_truth_gate"],
            "anti_staleness_warnings": result["anti_staleness"]["warnings"],
            "fresh_discovery_status": result["fresh_discovery_contract"].get("status"),
            "fresh_discovery_board": result["fresh_discovery_contract"].get("fresh_discovery_board"),
        }, indent=2) + "\n")
    else:
        sys.stdout.write(context_md + "\n")

    # Regression guard: a contaminated Fresh Discovery Board fails the run.
    try:
        assert_no_provenance_violation(result["fresh_discovery_contract"])
    except Exception as exc:  # DiscoveryProvenanceViolation
        sys.stderr.write(f"{exc}\n")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
