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
    from scripts.discovery_bias_metrics import (
        compute_contamination_ratios,
        compute_usa_bias,
        render_bias_markdown,
    )
    from scripts.fresh_market_discovery import build_fresh_market_discovery
    from scripts.minimum_daily_universe import minimum_universe_metadata
    from scripts.portfolio_truth_gate import build_portfolio_truth_gate
    from scripts.runtime_common import REPO_ROOT
    from scripts.top30_country_coverage import (
        build_country_coverage_from_payload,
        country_from_ticker,
        render_country_coverage_markdown,
    )
    from scripts.why_today import why_today_score
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps, human_only_stamp
    from anti_staleness import build_anti_staleness
    from candidate_executable_split import build_candidate_executable_split
    from daily_payload import load_daily_payload, normalize_ticker
    from discovery_bias_metrics import (
        compute_contamination_ratios,
        compute_usa_bias,
        render_bias_markdown,
    )
    from fresh_market_discovery import build_fresh_market_discovery
    from minimum_daily_universe import minimum_universe_metadata
    from portfolio_truth_gate import build_portfolio_truth_gate
    from runtime_common import REPO_ROOT
    from top30_country_coverage import (
        build_country_coverage_from_payload,
        country_from_ticker,
        render_country_coverage_markdown,
    )
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

    discovery_metrics = _build_discovery_metrics(payload, discovery)

    return {
        "run_date": payload["verified_holdings"].get("run_date"),
        "payload": payload,
        "portfolio_truth_gate": truth_gate,
        "fresh_market_discovery": discovery,
        "candidate_executable_split": split,
        "anti_staleness": anti_staleness,
        "why_today_scores": why_today_scores,
        "country_coverage": discovery_metrics["country_coverage"],
        "usa_bias": discovery_metrics["usa_bias"],
        "contamination": discovery_metrics["contamination"],
        "l_today": discovery.get("l_today", []),
        "safety": advisory_safety_stamps(),
        "execution": human_only_stamp(),
    }


def _build_discovery_metrics(
    payload: dict[str, Any], discovery: dict[str, Any]
) -> dict[str, Any]:
    """Compute country coverage + USA bias + contamination over the candidate set."""
    metadata = minimum_universe_metadata()

    candidate_set: list[dict[str, Any]] = []
    for score in discovery["scored_candidates"]:
        ticker = score["ticker"]
        meta = metadata.get(ticker, {})
        country = meta.get("country") or country_from_ticker(ticker)
        candidate_set.append(
            {
                "ticker": ticker,
                "country": country,
                "exchange": meta.get("exchange", ""),
                "source_class": score.get("source_class", "STATIC_FALLBACK"),
                "in_l_today": bool(score.get("in_l_today")),
                "phantom": score.get("source_class") == "PHANTOM",
            }
        )

    usa_bias = compute_usa_bias(candidate_set)
    contamination = compute_contamination_ratios(candidate_set)

    # Price rows + mapping rows for coverage derivation.
    price_rows = payload.get("price_movers", {}).get("movers", [])
    mapping_rows: list[dict[str, Any]] = []
    for key in ("news_events", "filings_events"):
        for row in payload.get(key, {}).get("events", []) or []:
            if row.get("ticker"):
                mapping_rows.append(
                    {
                        "ticker": row.get("ticker"),
                        "country": row.get("country"),
                        "mapping_confidence": row.get("mapping_confidence", 0.0),
                    }
                )
    country_coverage = build_country_coverage_from_payload(
        payload, price_rows=price_rows, mapping_rows=mapping_rows
    )
    return {
        "country_coverage": country_coverage,
        "usa_bias": usa_bias,
        "contamination": contamination,
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
    payload = result["payload"]

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
    lines.append("")

    # --- L_today invariant (live-discovered set) ---
    l_today = result.get("l_today") or discovery.get("l_today", [])
    scored = discovery.get("scored_candidates", [])
    static_universe = sorted(s["ticker"] for s in scored if s.get("source_class") == "STATIC_FALLBACK")
    memory_only = sorted(s["ticker"] for s in scored if s.get("source_class") == "MEMORY_OR_STALE")
    phantom_only = sorted(s["ticker"] for s in scored if s.get("source_class") == "PHANTOM")
    lines.append("------------------------------------------------------------")
    lines.append("L_TODAY INVARIANT (live-discovered candidate set)")
    lines.append("------------------------------------------------------------")
    lines.append(f"L_today (live-discovered today): {sorted(l_today) or 'NONE'}")
    lines.append(f"static_universe (RESEARCH_ONLY_STATIC): {static_universe or 'NONE'}")
    lines.append(f"memory_only_stale (MEMORY_ONLY_STALE): {memory_only or 'NONE'}")
    lines.append(f"phantom/closed/sold (PHANTOM_QUARANTINE): {phantom_only or 'NONE'}")
    lines.append(f"verified holdings H (EXISTING_POSITION_REVIEW): {gate['verified_open_holdings'] or 'NONE'}")
    lines.append("")
    lines.append("HARD INVARIANT FOR EVERY MODEL CANDIDATE c:")
    lines.append("  - c in L_today        -> may be LIVE_DISCOVERED_CANDIDATE")
    lines.append("  - c in H (not L_today)-> EXISTING_POSITION_REVIEW only")
    lines.append("  - c in static_universe-> RESEARCH_ONLY_STATIC / WATCHLIST_STATIC only")
    lines.append("  - c in phantom/closed/sold -> PHANTOM_QUARANTINE / DO_NOT_MANAGE")
    lines.append("  - c invented, absent from all payloads -> MODEL_PRIOR_ONLY (never executable)")
    lines.append(
        "  Do NOT treat any candidate as live-discovered unless it appears in L_today. "
        "If country coverage proof is missing/weak, say global discovery is degraded or "
        "failed. Do NOT fill missing countries from your own priors. A prior-only stock "
        "may appear ONLY under MODEL_PRIOR_ONLY / RESEARCH_ONLY_STATIC, never as executable."
    )
    lines.append("")

    # --- Top-30 country coverage proof ---
    coverage = result.get("country_coverage")
    if coverage:
        lines.append("------------------------------------------------------------")
        lines.append(render_country_coverage_markdown(coverage))
        lines.append("")

    # --- USA bias + fallback contamination ---
    usa_bias = result.get("usa_bias")
    contamination = result.get("contamination")
    if usa_bias and contamination:
        lines.append("------------------------------------------------------------")
        lines.append(render_bias_markdown(usa_bias, contamination))
        lines.append("")

    # --- Price validity + existing-risk visibility (Section 9) ---
    movers_meta = payload.get("price_movers", {})
    unmapped = 0
    for key in ("news_events", "filings_events"):
        for row in payload.get(key, {}).get("events", []) or []:
            if str(row.get("mapping_status") or "").upper() == "UNMAPPED":
                unmapped += 1
    lines.append("PRICE VALIDITY + UNMAPPED EVENTS:")
    lines.append(f"  unmapped_event_count: {unmapped} (retained, not dropped)")
    lines.append(
        "  price_movers source_health: "
        f"{movers_meta.get('source_health', 'UNVERIFIED')} is_live={movers_meta.get('is_live', False)}"
    )
    missing_prices = movers_meta.get("existing_holdings_missing_price", [])
    if movers_meta.get("existing_risk_visibility_degraded") or missing_prices:
        lines.append(
            f"  EXISTING_RISK_VISIBILITY_DEGRADED: holdings missing live price: {missing_prices or 'see manifest'}. "
            "Manage existing risk before any new risk."
        )
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
        "l_today": result.get("l_today", []),
        "executable_paper_buys": [r["ticker"] for r in result["candidate_executable_split"]["executable_paper_buys"]],
        "buy_candidate_not_executable": [
            r["ticker"] for r in result["candidate_executable_split"]["buy_candidate_not_executable"]
        ],
        "anti_staleness": {
            "novelty_ratio": result["anti_staleness"]["novelty_ratio"],
            "stale_discovery_warning": result["anti_staleness"]["stale_discovery_warning"],
        },
        "country_coverage_ratios": (result.get("country_coverage") or {}).get("ratios", {}),
        "global_discovery_status": (result.get("country_coverage") or {}).get("global_discovery_status"),
        "usa_bias": result.get("usa_bias", {}),
        "contamination": result.get("contamination", {}),
        "safety": result["safety"],
    }
    CONTEXT_JSON_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    coverage = result.get("country_coverage")
    if coverage:
        try:
            try:
                from scripts.top30_country_coverage import write_country_coverage
            except ModuleNotFoundError:  # pragma: no cover
                from top30_country_coverage import write_country_coverage
            write_country_coverage(coverage)
        except Exception:
            pass


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
        }, indent=2) + "\n")
    else:
        sys.stdout.write(context_md + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
