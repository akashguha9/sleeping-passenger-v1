"""Thesis card renderer + purpose-routed boards — the Belief Escrow surface.

Governance principle rendered visible: **case studies teach the engine;
live candidates are evaluated by the engine.** Every card prints its
contract purpose, board scope, investment eligibility, trading status, and
promotion status; case-study cards carry a NOT-INVESTABLE banner and an
InvestabilityScore of exactly 0.

Boards are split by purpose and routing is validated before rendering —
a case study on the investable board is an exception, not a layout bug:

  CASE_STUDY_BOARD.md            CASE_STUDY + FIXTURE_TEST (never investable)
  RESEARCH_BOARD.md              LIVE_RESEARCH (not a buy list)
  INVESTABLE_CANDIDATE_BOARD.md  PROMOTED candidates only (empty = success)
  ARCHIVE_BOARD.md               RETIRED / FALSIFIED / EXPIRED

ADVISORY_ONLY output; real-money execution prohibited repo-wide.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.signal_thesis_contract import (
    ADVISORY_STATUS, ANECDOTE, CASE_STUDY, EXPIRED, FALSIFIED,
    FALSIFIED_PURPOSE, FIXTURE_TEST, FOR_NULL, FOR_THESIS,
    INVESTABLE_CANDIDATE, LIVE_RESEARCH, REAL_MONEY, RETIRED,
    ThesisContract, binding_gate, grade, load_contract, load_contract_index,
    validate_purpose_routing, verify_lineage_from_index,
)

REQUIRED_SECTIONS = (
    "DATA MODE", "DERIVED DATA MODE", "AUTHENTICITY", "LINEAGE",
    "CONTRACT PURPOSE", "BOARD SCOPE", "INVESTMENT ELIGIBILITY",
    "TRADING STATUS", "PROMOTION STATUS", "VERDICT", "FINAL SCORE",
    "FRAMEWORK VALIDATION", "RESEARCH QUALITY", "INVESTABILITY SCORE",
    "EVIDENCE QUALITY", "CONTRADICTION", "EXPIRY", "CAUSAL PATH",
    "WHO GETS PAID", "PREDICTION-MARKET LINK", "WOULD VALIDATE",
    "WOULD FALSIFY", "SCORE BREAKDOWN", "PROVENANCE", "BINDING GATE",
    "NEXT EVIDENCE ACTIONS", "NEXT ACTION",
)

CASE_STUDY_BANNER = (
    "⚠️ CASE STUDY ONLY — NOT INVESTABLE\n"
    "This card validates MVP architecture and scoring logic. It is not a "
    "buy candidate, not a recommendation, and not eligible for trading or "
    "portfolio selection.")
RESEARCH_BANNER = (
    "RESEARCH ONLY — NOT A BUY LIST\n"
    "This card is under evidence collection. It cannot be used as an "
    "investable candidate unless promoted through the promotion workflow.")
CANDIDATE_BANNER = (
    "PROMOTED INVESTABLE CANDIDATE — PAPER REVIEW ONLY\n"
    "This card passed promotion rules but remains advisory-only and "
    "paper-review-only.")
ARCHIVE_BANNER = (
    "ARCHIVED — RETIRED OR FALSIFIED\n"
    "This contract has been adjudicated. It carries no eligibility of any "
    "kind and is retained as a lesson record.")


def _banner(contract: ThesisContract) -> str:
    p = contract.contract_purpose
    if p in (CASE_STUDY, FIXTURE_TEST):
        return CASE_STUDY_BANNER
    if p == LIVE_RESEARCH:
        return RESEARCH_BANNER
    if p == INVESTABLE_CANDIDATE:
        return CANDIDATE_BANNER
    return ARCHIVE_BANNER


def _next_action(report: dict[str, Any], contract: ThesisContract) -> str:
    if contract.contract_purpose in (CASE_STUDY, FIXTURE_TEST):
        return ("None for investment: case studies are not promotable in "
                "place. To pursue the idea, clone via "
                "promote_case_study_to_research() with new expiry, new "
                "falsification observable, and live/hard evidence.")
    if not report["falsifiable"]:
        return ("Register a falsification observable and an expiry day — "
                "the contract is inadmissible until it can lose.")
    if report["evidence_quality"] < 0.35:
        return ("Add MARKET/HARD_DATA evidence from a new ecology — EQS is "
                "below the admissibility floor.")
    if (report["discrimination"]["n_against"] == 0
            and report["discrimination"]["n_for"] > 0):
        return ("Hunt one piece of evidence FOR the null — an empty AGAINST "
                "column means the null was never tested.")
    if report["g_stale"] < 0.7:
        return "Refresh the oldest evidence items — staleness is the binding gate."
    if report["days_to_expiry"] == 0:
        return ("Adjudicate now: attach realized outcome and move the "
                "contract to the cemetery.")
    return ("Monitor the falsification observable; next review before day "
            f"{contract.expiry_day}.")


def render_thesis_card(contract: ThesisContract, report: dict[str, Any],
                       as_of_day: int) -> str:
    validate_purpose_routing(contract)
    disc = report["discrimination"]
    lines: list[str] = []
    add = lines.append
    add(f"# THESIS CARD — {contract.title}")
    add("")
    add("```")
    add(_banner(contract))
    add("```")
    add("")
    add(f"**Entity:** {contract.entity} ({contract.ticker})")
    add("")
    add("| governance field | value |\n|---|---|")
    add(f"| DATA MODE (declared label) | `{contract.data_mode}` |")
    add(f"| DERIVED DATA MODE (from verified evidence) | "
        f"`{report['derived_data_mode']}` |")
    add(f"| AUTHENTICITY cap | `{report['authenticity_cap']}` |")
    lineage_txt = ("n/a (root contract)" if not contract.parent_hash else
                   f"parent={contract.parent_case_study_id or contract.parent_research_id} "
                   f"verified={report['lineage_valid']}")
    add(f"| LINEAGE | `{lineage_txt}` |")
    add(f"| CONTRACT PURPOSE | `{contract.contract_purpose}` |")
    add(f"| BOARD SCOPE | `{contract.board_scope}` |")
    add(f"| INVESTMENT ELIGIBILITY | `{contract.investment_eligibility}` |")
    add(f"| TRADING STATUS | `{contract.trading_status}` |")
    add(f"| PROMOTION STATUS | `{contract.promotion_status}` |")
    add(f"| lifecycle status | `{contract.status}` |")
    add("")
    if contract.contract_purpose in (CASE_STUDY, FIXTURE_TEST):
        add("DATA PURPOSE: CASE STUDY / MVP VALIDATION  ")
        add("INVESTABILITY STATUS: NOT ELIGIBLE  ")
        add("TRADING STATUS: DO NOT TRADE")
        add("")
        add(f"> {contract.case_study_disclaimer}")
        add("")
    add(f"**Status:** {ADVISORY_STATUS} · real money: {REAL_MONEY}")
    add("")
    add(f"## VERDICT: {report['verdict']}")
    add(f"Binding rule: `{report['verdict_rule']}`")
    add("")
    add(f"## FINAL SCORE: {report['final_score']} / 10")
    caps = ", ".join(report["caps_applied"]) or "none"
    add(f"Caps applied: {caps}")
    add("")
    add("## SCORE FAMILIES")
    add(f"- FRAMEWORK VALIDATION score: {report['framework_validation_score']}"
        " / 10 (praise for the framework, never the trade)")
    add(f"- RESEARCH QUALITY score: {report['research_quality_score']} / 10")
    add(f"- INVESTABILITY SCORE: {report['investability_score']} / 10 "
        f"(eligibility multiplier = {report['eligibility_multiplier']})")
    add("")
    add(f"## EVIDENCE QUALITY: {report['evidence_quality']:.3f} "
        f"(cap = {10 * report['evidence_quality']:.2f})")
    add(f"## CONTRADICTION: g_contra = {disc['g_contra']:.3f} "
        f"(for {disc['n_for']} / against {disc['n_against']} / "
        f"neutral-ignored {disc['n_neutral']})")
    add(f"## EXPIRY: {report['days_to_expiry']} days remaining "
        f"(day {contract.expiry_day}; as-of day {as_of_day})")
    add("")
    add("## NARRATIVE")
    add(contract.narrative)
    add("")
    add(f"Trigger: {contract.trigger}  \nPredicted direction: "
        f"{contract.predicted_direction} over {contract.horizon_days}d")
    add("")
    add("## CAUSAL PATH")
    add(" -> ".join(contract.causal_path) if contract.causal_path
        else "NOT REGISTERED")
    add("")
    add("## WHO GETS PAID")
    if contract.beneficiary_map:
        for layer, names in contract.beneficiary_map.items():
            add(f"- **{layer}**: {', '.join(names)}")
    else:
        add("- NOT MAPPED")
    add("")
    add("## PREDICTION-MARKET LINK")
    if contract.pm_link:
        link = contract.pm_link
        add(f"- market: `{link.get('market_id', 'n/a')}` · edge: "
            f"{link.get('edge', 'n/a')} · alignment: "
            f"{link.get('alignment', 'n/a')} · category validated: "
            f"{link.get('category_validated', False)}")
    else:
        add("- none (no liquid event market — gate is neutral, never a bonus)")
    add("")
    add("## WOULD VALIDATE")
    if contract.contract_purpose in (CASE_STUDY, FIXTURE_TEST):
        add("- The framework modules exercised by this card behave per spec "
            "(validation target is the ARCHITECTURE, not the ticker).")
    else:
        add(f"- Realized move in predicted direction by day "
            f"{contract.expiry_day} with the causal observable confirming.")
    add("## WOULD FALSIFY")
    add(f"- {contract.falsification_observable}")
    add(f"- Forced null: *{contract.forced_null_thesis}*")
    add("")
    add("## SCORE BREAKDOWN")
    m = report["merit"]
    add("| component | value |\n|---|---|")
    add(f"| demand D | {m['demand_D']} |")
    add(f"| moat M (top-2) | {m['moat_M']} |")
    add(f"| MERIT | {m['merit']} |")
    add(f"| g_txn | {report['g_txn']} |")
    add(f"| g_contra | {disc['g_contra']} |")
    add(f"| g_stale | {report['g_stale']} |")
    add(f"| g_pm | {report['g_pm']} |")
    add(f"| FINAL | {report['final_score']} |")
    add(f"| eligibility multiplier | {report['eligibility_multiplier']} |")
    add(f"| INVESTABILITY | {report['investability_score']} |")
    add("")
    add("## PROVENANCE")
    for prov, n in sorted(report["provenance_counts"].items()):
        add(f"- {prov}: {n} item(s)")
    add("")
    add("### Contradiction board")
    add("**FOR thesis:**")
    for e in contract.evidence:
        if e.stance == FOR_THESIS:
            add(f"- [{e.provenance}] {e.claim} ({e.source}, day {e.observed_day})")
    add("**AGAINST (for null):**")
    against = [e for e in contract.evidence if e.stance == FOR_NULL]
    if against:
        for e in against:
            add(f"- [{e.provenance}] {e.claim} ({e.source}, day {e.observed_day})")
    else:
        add("- (empty — the null has not been tested)")
    add("")
    add("### Anecdote quarantine")
    tray = [e for e in contract.evidence if e.provenance == ANECDOTE]
    if tray:
        for e in tray:
            corro = next((a["corroborated"] for a in
                          report["anecdotes_quarantined"]
                          if a["evidence_id"] == e.evidence_id), False)
            add(f"- {e.claim} — weight "
                f"{'0.60 (corroborated)' if corro else '0.15 (quarantined)'}")
    else:
        add("- none")
    add("")
    add("## BINDING GATE")
    gate = binding_gate(report)
    add(f"BindingGate = **{gate}**"
        + (f" (EQS = {report['evidence_quality']:.3f})" if gate == "EQS"
           else ""))
    add("")
    add("## NEXT EVIDENCE ACTIONS")
    if contract.next_evidence_actions:
        for action in contract.next_evidence_actions:
            add(f"- {action}")
    else:
        add("- (none registered — add next_evidence_actions to the contract)")
    add("")
    add("## NEXT ACTION")
    add(_next_action(report, contract))
    add("")
    card = "\n".join(lines)
    missing = [s for s in REQUIRED_SECTIONS if s not in card]
    if missing:
        raise ValueError(f"thesis card missing required sections: {missing}")
    return card


def write_card(contract: ThesisContract, as_of_day: int, out_dir: Path,
               lineage_valid: bool | None = None) -> Path:
    report = grade(contract, as_of_day, lineage_valid=lineage_valid)
    card = render_thesis_card(contract, report, as_of_day)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{contract.thesis_id}.md"
    path.write_text(card, encoding="utf-8")
    return path


# --- purpose-routed boards ------------------------------------------------------

def route_board(contract: ThesisContract) -> str:
    validate_purpose_routing(contract)
    if contract.status in (EXPIRED, FALSIFIED):
        return "ARCHIVE"
    return contract.board_scope


def _row(c: ThesisContract, r: dict[str, Any]) -> dict[str, Any]:
    return {"thesis_id": c.thesis_id, "title": c.title, "ticker": c.ticker,
            "verdict": r["verdict"],
            "framework_validation_score": r["framework_validation_score"],
            "research_quality_score": r["research_quality_score"],
            "investability_score": r["investability_score"],
            "evidence_quality": r["evidence_quality"],
            "days_to_expiry": r["days_to_expiry"],
            "data_mode": c.data_mode,
            "contract_purpose": c.contract_purpose,
            "trading_status": c.trading_status,
            "status": c.status}


def build_boards(items: list[tuple[ThesisContract, dict[str, Any]]],
                 contract_index: dict[str, ThesisContract] | None = None
                 ) -> dict[str, list[dict[str, Any]]]:
    boards: dict[str, list[dict[str, Any]]] = {
        "CASE_STUDY_BOARD": [], "RESEARCH_BOARD": [],
        "INVESTABLE_CANDIDATE_BOARD": [], "ARCHIVE": []}
    for c, r in sorted(items, key=lambda t: -t[1]["final_score"]):
        scope = route_board(c)
        if scope not in boards:
            raise ValueError(f"UNROUTABLE_BOARD_SCOPE: {scope}")
        if scope == "INVESTABLE_CANDIDATE_BOARD":
            if (c.contract_purpose != INVESTABLE_CANDIDATE
                    or c.promotion_status != "PROMOTED"):
                raise ValueError(
                    f"BOARD_CONTAMINATION: {c.thesis_id} "
                    f"({c.contract_purpose}/{c.promotion_status}) may not "
                    "appear on INVESTABLE_CANDIDATE_BOARD")
            lineage = verify_lineage_from_index(c, contract_index or {})
            if not lineage["valid"]:
                raise ValueError(
                    f"CONTRACT_LINEAGE_FAIL_CLOSED: {c.thesis_id} cannot sit "
                    "on INVESTABLE_CANDIDATE_BOARD with unverified lineage: "
                    f"{lineage['reasons']}")
        boards[scope].append(_row(c, r))
    return boards


def _md_table(rows: list[dict[str, Any]], cols: list[tuple[str, str]]) -> list[str]:
    out = ["| " + " | ".join(h for h, _ in cols) + " |",
           "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(r[k]) for _, k in cols) + " |")
    return out


def render_board_markdown(boards: dict[str, list[dict[str, Any]]]
                          ) -> dict[str, str]:
    md: dict[str, str] = {}

    lines = ["# CASE STUDY BOARD", "",
             "Purpose: validate MVP modules and archetypes.",
             "Investability: zero by design.", "",
             "```", "NOT INVESTABLE — CASE STUDY ONLY", "```", ""]
    rows = boards["CASE_STUDY_BOARD"]
    if rows:
        lines += _md_table(rows, [
            ("case study", "title"), ("ticker", "ticker"),
            ("verdict", "verdict"), ("FVS", "framework_validation_score"),
            ("RQS", "research_quality_score"),
            ("InvestabilityScore", "investability_score"),
            ("mode", "data_mode")])
    else:
        lines.append("(no case studies registered)")
    lines += ["", f"{ADVISORY_STATUS} · real money: {REAL_MONEY}"]
    md["CASE_STUDY_BOARD"] = "\n".join(lines)

    lines = ["# RESEARCH BOARD", "",
             "Purpose: collect evidence and track live research.",
             "Investability: blocked until promotion.", "",
             "```", "RESEARCH ONLY — NOT A BUY LIST", "```", ""]
    rows = boards["RESEARCH_BOARD"]
    if rows:
        lines += _md_table(rows, [
            ("thesis", "title"), ("ticker", "ticker"),
            ("verdict", "verdict"), ("RQS", "research_quality_score"),
            ("EQS", "evidence_quality"), ("expiry (d)", "days_to_expiry"),
            ("mode", "data_mode")])
    else:
        lines.append("(no live research contracts)")
    lines += ["", f"{ADVISORY_STATUS} · real money: {REAL_MONEY}"]
    md["RESEARCH_BOARD"] = "\n".join(lines)

    lines = ["# INVESTABLE CANDIDATE BOARD", "",
             "Purpose: promoted paper-review candidates only.",
             "Current status: no candidates unless promotion rules passed.",
             ""]
    rows = boards["INVESTABLE_CANDIDATE_BOARD"]
    if rows:
        lines += _md_table(rows, [
            ("candidate", "title"), ("ticker", "ticker"),
            ("verdict", "verdict"),
            ("InvestabilityScore", "investability_score"),
            ("EQS", "evidence_quality"), ("expiry (d)", "days_to_expiry"),
            ("trading", "trading_status")])
    else:
        lines.append("No investable candidates currently promoted. "
                     "System is working correctly.")
    lines += ["", f"{ADVISORY_STATUS} · real money: {REAL_MONEY} · "
              "paper review only"]
    md["INVESTABLE_CANDIDATE_BOARD"] = "\n".join(lines)

    lines = ["# ARCHIVE BOARD", "",
             "Retired, falsified, expired, and rejected contracts — the "
             "cemetery is a product feature.", ""]
    rows = boards["ARCHIVE"]
    if rows:
        lines += _md_table(rows, [
            ("thesis", "title"), ("ticker", "ticker"),
            ("lifecycle", "status"), ("verdict", "verdict"),
            ("purpose", "contract_purpose"), ("mode", "data_mode")])
    else:
        lines.append("(archive empty)")
    lines += ["", f"{ADVISORY_STATUS} · real money: {REAL_MONEY}"]
    md["ARCHIVE_BOARD"] = "\n".join(lines)
    return md


def render_board(items: list[tuple[ThesisContract, dict[str, Any]]]) -> str:
    """Legacy single-board view — now explicitly a RESEARCH-style summary
    with banner; kept for compatibility with existing callers/tests."""
    lines = ["# THESIS BOARD (summary view)", "",
             "```", "RESEARCH ONLY — NOT A BUY LIST", "```", "",
             "| thesis | ticker | purpose | verdict | FIS | Investability |"
             " EQS | expiry (d) | mode |",
             "|---|---|---|---|---|---|---|---|---|"]
    for c, r in sorted(items, key=lambda t: -t[1]["final_score"]):
        lines.append(
            f"| {c.title} | {c.ticker} | {c.contract_purpose} | "
            f"{r['verdict']} | {r['final_score']} | "
            f"{r['investability_score']} | {r['evidence_quality']:.2f} | "
            f"{r['days_to_expiry']} | {c.data_mode} |")
    lines.append("")
    lines.append(f"{ADVISORY_STATUS} · real money: {REAL_MONEY}")
    return "\n".join(lines)


def write_all_boards(items: list[tuple[ThesisContract, dict[str, Any]]],
                     md_dir: Path, json_dir: Path,
                     contract_index: dict[str, ThesisContract] | None = None
                     ) -> dict[str, Any]:
    boards = build_boards(items, contract_index=contract_index)
    md = render_board_markdown(boards)
    md_dir.mkdir(parents=True, exist_ok=True)
    json_dir.mkdir(parents=True, exist_ok=True)
    for name, text in md.items():
        (md_dir / f"{name}.md").write_text(text, encoding="utf-8")
    json_names = {"CASE_STUDY_BOARD": "case_study_board.json",
                  "RESEARCH_BOARD": "research_board.json",
                  "INVESTABLE_CANDIDATE_BOARD": "investable_candidate_board.json",
                  "ARCHIVE": "archive_board.json"}
    for scope, fname in json_names.items():
        (json_dir / fname).write_text(
            json.dumps({"board": scope, "rows": boards[scope],
                        "advisory_status": ADVISORY_STATUS,
                        "real_money": REAL_MONEY},
                       indent=2, sort_keys=True), encoding="utf-8")
    routing = {
        "counts": {scope: len(rows) for scope, rows in boards.items()},
        "violations": [],  # build_boards raises on contamination
        "invariant": "CASE_STUDY/FIXTURE_TEST -> CASE_STUDY_BOARD; "
                     "LIVE_RESEARCH -> RESEARCH_BOARD; "
                     "INVESTABLE_CANDIDATE(PROMOTED) -> "
                     "INVESTABLE_CANDIDATE_BOARD; RETIRED/FALSIFIED -> ARCHIVE",
        "advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY,
    }
    (json_dir / "purpose_routing_report.json").write_text(
        json.dumps(routing, indent=2, sort_keys=True), encoding="utf-8")
    return {"boards": {k: len(v) for k, v in boards.items()},
            "routing_report": str(json_dir / "purpose_routing_report.json")}


def _main() -> int:
    ap = argparse.ArgumentParser(description="Render thesis cards + boards")
    ap.add_argument("--contracts-dir", type=Path,
                    default=Path("data/evidence/thesis_contracts"))
    ap.add_argument("--out-dir", type=Path,
                    default=Path("data/reports/thesis_cards"))
    ap.add_argument("--json-dir", type=Path, default=Path("runtime"))
    ap.add_argument("--as-of-day", type=int, required=True)
    args = ap.parse_args()
    contract_index = load_contract_index(args.contracts_dir)
    items: list[tuple[ThesisContract, dict[str, Any]]] = []
    for contract in contract_index.values():
        lineage_valid: bool | None = None
        if contract.contract_purpose == INVESTABLE_CANDIDATE:
            lineage_valid = verify_lineage_from_index(
                contract, contract_index)["valid"]
        report = grade(contract, args.as_of_day, lineage_valid=lineage_valid)
        write_card(contract, args.as_of_day, args.out_dir,
                   lineage_valid=lineage_valid)
        items.append((contract, report))
    summary = write_all_boards(items, args.out_dir, args.json_dir,
                               contract_index=contract_index)
    summary["cards_written"] = len(items)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
