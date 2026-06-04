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
    from scripts.daily_payload import load_daily_payload, normalize_ticker
    from scripts.fresh_market_discovery import build_fresh_market_discovery
    from scripts.portfolio_truth_gate import build_portfolio_truth_gate
    from scripts.runtime_common import REPO_ROOT
    from scripts.why_today import why_today_score
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps, human_only_stamp
    from anti_staleness import build_anti_staleness
    from candidate_executable_split import build_candidate_executable_split
    from daily_payload import load_daily_payload, normalize_ticker
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

    return {
        "run_date": payload["verified_holdings"].get("run_date"),
        "payload": payload,
        "portfolio_truth_gate": truth_gate,
        "fresh_market_discovery": discovery,
        "candidate_executable_split": split,
        "anti_staleness": anti_staleness,
        "why_today_scores": why_today_scores,
        "safety": advisory_safety_stamps(),
        "execution": human_only_stamp(),
    }


def attach_daily_governance(
    result: dict[str, Any],
    governance_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the fail-closed Daily Governance Gate and attach it to ``result``.

    The governance gate is the single source of truth for the daily board:
    whether a Manual Add Consideration is allowed, whether it is a no-new-risk
    day, which tickers are quarantined, and which holdings require review.

    ``governance_inputs`` is the five-model synthesis snapshot (see
    ``scripts/governance/daily_governance_runner``). When it is None the gate is
    skipped and the result is returned unchanged, so the existing four-layer
    flow keeps working unmodified. This is additive and advisory-only.
    """
    if governance_inputs is None:
        return result
    try:
        from scripts.governance.daily_governance_runner import run_from_inputs
    except ModuleNotFoundError:  # pragma: no cover - script-style env
        from governance.daily_governance_runner import run_from_inputs  # type: ignore[no-redef]
    gov = run_from_inputs(governance_inputs)
    result["daily_governance"] = gov.to_dict()
    return result


def _render_governance_labels(result: dict[str, Any]) -> list[str]:
    """Render advisory status labels from an attached governance result."""
    gov = result.get("daily_governance")
    if not gov:
        return []
    labels: list[str] = ["EXECUTION_GATE_LOCKED"]
    if gov.get("source_health_status") == "FAILED":
        labels.append("SOURCE_HEALTH_FAILED")
    if gov.get("no_new_risk_day") == "YES":
        labels.append("NO_NEW_RISK_DAY")
    if gov.get("final_regime") == "EXISTING_POSITION_MANAGEMENT_ONLY":
        labels.append("EXISTING_POSITION_MANAGEMENT_ONLY")
    elif gov.get("final_regime") == "WATCHLIST_ONLY":
        labels.append("WATCHLIST_ONLY")
    if gov.get("names_to_quarantine"):
        labels.append("PHANTOM_QUARANTINE")
    lines = ["", "------------------------------------------------------------",
             "DAILY GOVERNANCE GATE (single source of truth — advisory only)",
             "------------------------------------------------------------",
             f"  status_labels: {labels}",
             f"  no_new_risk_day: {gov.get('no_new_risk_day')}",
             f"  new_risk_permission: {gov.get('new_risk_permission')}",
             f"  final_regime: {gov.get('final_regime')}",
             f"  names_to_quarantine: {gov.get('names_to_quarantine') or 'NONE'}",
             f"  manual_add_consideration: {gov.get('top_manual_add_consideration') or 'NONE'}",
             f"  best_watch: {gov.get('best_watch') or 'NONE'}",
             f"  execution_gate_status: {gov.get('execution_gate_status')} (human execution required)"]
    return lines


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
    lines.append("FRESH MARKET DISCOVERY (must run even if execution blocked)")
    lines.append("------------------------------------------------------------")
    lines.append(f"discovery_universe: {discovery['discovery_universe'] or 'NONE'}")
    lines.append(f"new_tickers_not_seen_yesterday: {discovery['new_tickers_not_seen_yesterday'] or 'NONE'}")
    lines.append(f"discovery_underpowered: {discovery['discovery_underpowered']}")
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
    lines.extend(_render_governance_labels(result))
    lines.append("")
    lines.append("Reminder: advisory only. No broker action. No execution. Human review required.")
    lines.append("============================================================")
    return "\n".join(lines)


def _write_artifacts(result: dict[str, Any], context_md: str) -> None:
    CONTEXT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTEXT_MD_PATH.write_text(context_md, encoding="utf-8")
    summary = {
        "run_date": result["run_date"],
        "portfolio_truth_gate": result["portfolio_truth_gate"],
        "discovery_universe": result["fresh_market_discovery"]["discovery_universe"],
        "executable_paper_buys": [r["ticker"] for r in result["candidate_executable_split"]["executable_paper_buys"]],
        "buy_candidate_not_executable": [
            r["ticker"] for r in result["candidate_executable_split"]["buy_candidate_not_executable"]
        ],
        "anti_staleness": {
            "novelty_ratio": result["anti_staleness"]["novelty_ratio"],
            "stale_discovery_warning": result["anti_staleness"]["stale_discovery_warning"],
        },
        "safety": result["safety"],
    }
    CONTEXT_JSON_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily five-model synthesis truth/discovery pipeline.")
    parser.add_argument("--json", action="store_true", help="print the JSON summary instead of the context block")
    parser.add_argument("--write", action="store_true", help="write runtime context artifacts")
    parser.add_argument(
        "--governance-inputs",
        default=None,
        help="path to a governance-inputs JSON snapshot; runs the Daily Governance Gate and writes its artifacts",
    )
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    result = run_daily_synthesis()
    if args.governance_inputs:
        gov_inputs = json.loads(Path(args.governance_inputs).read_text(encoding="utf-8"))
        attach_daily_governance(result, gov_inputs)
        if args.write:
            try:
                from scripts.governance.artifacts import write_governance_artifacts
                from scripts.governance.daily_governance_runner import run_from_inputs
            except ModuleNotFoundError:  # pragma: no cover - script-style env
                from governance.artifacts import write_governance_artifacts  # type: ignore[no-redef]
                from governance.daily_governance_runner import run_from_inputs  # type: ignore[no-redef]
            gov_result = run_from_inputs(gov_inputs)
            write_governance_artifacts(
                gov_result, REPO_ROOT / "runtime", run_id=(gov_inputs.get("config") or {}).get("run_id")
            )
    context_md = render_portfolio_truth_context(result)
    if args.write:
        _write_artifacts(result, context_md)
    if args.json:
        sys.stdout.write(json.dumps({
            "run_date": result["run_date"],
            "portfolio_truth_gate": result["portfolio_truth_gate"],
            "anti_staleness_warnings": result["anti_staleness"]["warnings"],
        }, indent=2) + "\n")
    else:
        sys.stdout.write(context_md + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
