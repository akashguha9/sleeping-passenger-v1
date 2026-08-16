"""Regime-transition sprint — candidate card assembler + report writer.

Composes the regime-transition stack into ONE human-auditable card per
security, with every field carrying a provenance class:

    OBSERVED      — measured from market/filing data
    INFERRED      — derived by a model from observed inputs
    EXPERIMENTAL  — uncalibrated research prior (flip prob, PMDS, …)
    UNKNOWN       — honestly unavailable (never rendered as zero)

Ranking philosophy (reflection "Final Security Selection"):
- HARD GATES first (no score can rescue a gate failure):
    G1  divergence inputs used only if the CES gate allowed comparison;
    G2  exposure must be cited (no narrative proxies);
    G3  fresh price data for any PEG-based claim.
- The research priority is a documented weighted blend of the passing
  components — a TRIAGE order for HUMAN research, never a BUY list, and
  it is stamped experimental because its weights are uncalibrated.

Output: reports/regime_transition_report_<date>.{json,md}.  Advisory-only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"
EXPERIMENTAL = "EXPERIMENTAL"
OBSERVED = "OBSERVED"
INFERRED = "INFERRED"
UNKNOWN = "UNKNOWN"
OK = "OK"

REPORT_VERSION = "regime-transition-v1.0"

# Research-priority weights (documented, uncalibrated; sum 1.0).
_PRIORITY_WEIGHTS = {
    "propagation_gap": 0.30,       # unabsorbed expected move (the point)
    "shock_conviction": 0.20,      # ΔP magnitude (conviction-weighted upstream)
    "instability": 0.15,           # regime fragility
    "evidence_confirmation": 0.15, # titration + filing confirmation
    "inertia_alignment": 0.10,     # shock aligned with existing trajectory
    "value_capture": 0.10,         # five-forces / capture-rate proxy
}
_MIN_PRIORITY_COVERAGE = 0.45

_GATE_FAIL_EXPOSURE = "GATE_FAIL_UNCITED_EXPOSURE"
_GATE_FAIL_PRICE = "GATE_FAIL_STALE_PRICE"
PASS = "PASS"


def _norm01(value: float | None, ceiling: float) -> float | None:
    if value is None:
        return None
    return max(0.0, min(1.0, abs(value) / ceiling))


def assemble_candidate_card(
    *,
    ticker: str,
    event_id: str,
    peg: dict[str, Any],
    ces_verdict: dict[str, Any] | None = None,
    divergence: dict[str, Any] | None = None,
    pmds: dict[str, Any] | None = None,
    instability: dict[str, Any] | None = None,
    flip: dict[str, Any] | None = None,
    inertia: dict[str, Any] | None = None,
    iir: dict[str, Any] | None = None,
    titration: dict[str, Any] | None = None,
    buffer: dict[str, Any] | None = None,
    tp: dict[str, Any] | None = None,
    wavefront_state: str | None = None,
    arrival_lag_days: int | None = None,
    value_capture_0_1: float | None = None,
    halflife_remaining_0_1: float | None = None,
) -> dict[str, Any]:
    """Build one auditable candidate card.  Missing layers stay UNKNOWN."""
    gates: dict[str, str] = {}
    # G2 — exposure must be cited (PEG enforces; reflect its verdict).
    if peg.get("status") == OK and peg.get("gap_state") not in (None, "NO_EXPOSURE"):
        gates["exposure_cited"] = PASS
    elif peg.get("reason") == "exposure unknown or uncited":
        gates["exposure_cited"] = _GATE_FAIL_EXPOSURE
    else:
        gates["exposure_cited"] = peg.get("gap_state") or UNKNOWN
    # G3 — price freshness.
    gates["price_fresh"] = (
        _GATE_FAIL_PRICE if peg.get("reason") == "price data missing or stale"
        else PASS)
    # G1 — CES gate (only relevant when divergence inputs were used).
    if ces_verdict is not None:
        gates["ces"] = ces_verdict.get("gate", UNKNOWN)

    hard_fail = any(g.startswith("GATE_FAIL") for g in gates.values())

    components: dict[str, float | None] = {
        "propagation_gap": (
            (peg.get("unabsorbed_fraction") or 0.0)
            * _norm01(peg.get("expected_move"), 0.10)
            if peg.get("status") == OK
            and peg.get("gap_state") in ("GAP_OPEN", "PARTIALLY_ABSORBED")
            else (0.0 if peg.get("status") == OK else None)),
        "shock_conviction": _norm01(
            (divergence or {}).get("divergence_latest"), 0.25)
        if divergence and divergence.get("status") == OK else None,
        "instability": ((instability or {}).get("instability_score") or 0) / 100.0
        if instability and instability.get("status") == OK else None,
        "evidence_confirmation": _norm01(
            (titration or {}).get("accumulated_pressure"), 2.0)
        if titration and titration.get("status") == OK else None,
        "inertia_alignment": ((inertia or {}).get("composite_inertia") or 0) / 100.0
        if inertia and inertia.get("composite_inertia") is not None else None,
        "value_capture": value_capture_0_1,
    }
    known_w = sum(_PRIORITY_WEIGHTS[k] for k, v in components.items()
                  if v is not None)
    coverage = known_w / sum(_PRIORITY_WEIGHTS.values())
    if hard_fail or coverage < _MIN_PRIORITY_COVERAGE:
        priority = None
    else:
        priority = round(100.0 * sum(
            _PRIORITY_WEIGHTS[k] * v for k, v in components.items()
            if v is not None) / known_w, 2)
        if halflife_remaining_0_1 is not None:
            priority = round(priority * max(0.0, min(1.0, halflife_remaining_0_1)), 2)

    weakest = sorted(k for k, v in components.items() if v is None)
    reasons_wrong = []
    if weakest:
        reasons_wrong.append(f"missing components: {', '.join(weakest)}")
    if peg.get("gap_state") == "PARTIALLY_ABSORBED":
        reasons_wrong.append("market may already be pricing the remainder in")
    if (flip or {}).get("status") == OK:
        reasons_wrong.append("flip probability is experimental and uncalibrated")
    if not reasons_wrong:
        reasons_wrong.append("exposure/sensitivity are analyst estimates, "
                             "not measured elasticities")

    return {
        "report_version": REPORT_VERSION,
        "ticker": ticker,
        "event_id": event_id,
        "gates": gates,
        "hard_gate_failed": hard_fail,
        "research_priority": priority,
        "priority_coverage": round(coverage, 4),
        "priority_components": {k: (None if v is None else round(v, 4))
                                for k, v in components.items()},
        "fields": {
            "propagation_gap": {"value": peg, "provenance": INFERRED},
            "contract_equivalence": {"value": ces_verdict,
                                     "provenance": INFERRED},
            "cross_market_divergence": {"value": divergence,
                                        "provenance": OBSERVED},
            "pmds": {"value": pmds, "provenance": EXPERIMENTAL},
            "narrative_instability": {"value": instability,
                                      "provenance": INFERRED},
            "regime_flip_probability": {"value": flip,
                                        "provenance": EXPERIMENTAL},
            "inertia_stack": {"value": inertia, "provenance": INFERRED},
            "impulse_to_inertia": {"value": iir, "provenance": INFERRED},
            "accumulated_evidence": {"value": titration,
                                     "provenance": INFERRED},
            "buffer_state": {"value": buffer, "provenance": INFERRED},
            "threshold_pressure": {"value": tp, "provenance": INFERRED},
            "wavefront_state": {"value": wavefront_state,
                                "provenance": INFERRED},
            "expected_arrival_lag_days": {"value": arrival_lag_days,
                                          "provenance": INFERRED},
            "value_capture": {"value": value_capture_0_1,
                              "provenance": INFERRED},
            "halflife_remaining": {"value": halflife_remaining_0_1,
                                   "provenance": EXPERIMENTAL},
        },
        "reason_for_inclusion": (
            f"PEG {peg.get('gap_state')} with "
            f"{peg.get('unabsorbed_fraction')} of expected move unabsorbed"
            if peg.get("status") == OK else "diagnostic card (no PEG)"),
        "reason_it_may_be_wrong": reasons_wrong,
        "signal_class": "RESEARCH_TRIAGE_ONLY",
        "experimental": True,
        "safety": {"advisory_status": ADVISORY_STATUS,
                   "real_money": REAL_MONEY,
                   "execution_gate": "LOCKED"},
    }


def write_report(cards: list[dict[str, Any]], *, report_date: str,
                 reports_dir: Path) -> dict[str, Path]:
    """Persist JSON + Markdown.  Ranked cards first, gated/diagnostic after."""
    ranked = sorted(
        [c for c in cards if c.get("research_priority") is not None],
        key=lambda c: -c["research_priority"])
    unranked = [c for c in cards if c.get("research_priority") is None]
    payload = {"report_version": REPORT_VERSION, "date": report_date,
               "signal_class": "RESEARCH_TRIAGE_ONLY",
               "legend": {"OBSERVED": "measured from data",
                          "INFERRED": "model-derived from observed inputs",
                          "EXPERIMENTAL": "uncalibrated research prior",
                          "UNKNOWN": "honestly unavailable"},
               "ranked": ranked, "unranked": unranked,
               "safety": {"advisory_status": ADVISORY_STATUS,
                          "real_money": REAL_MONEY}}
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / f"regime_transition_report_{report_date}.json"
    md_path = reports_dir / f"regime_transition_report_{report_date}.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [f"# Regime-Transition Research Triage — {report_date}", "",
             "**RESEARCH TRIAGE ONLY — advisory, experimental, no execution.**",
             "", "Legend: OBSERVED = measured | INFERRED = model-derived | "
             "EXPERIMENTAL = uncalibrated prior | UNKNOWN = unavailable.", ""]
    if ranked:
        lines.append("| # | Ticker | Event | Priority | PEG state | "
                     "Unabsorbed | Instability | Why it may be wrong |")
        lines.append("|---|--------|-------|----------|-----------|"
                     "------------|-------------|---------------------|")
        for i, c in enumerate(ranked, 1):
            peg = c["fields"]["propagation_gap"]["value"]
            inst = c["fields"]["narrative_instability"]["value"] or {}
            lines.append(
                f"| {i} | {c['ticker']} | {c['event_id']} | "
                f"{c['research_priority']} | {peg.get('gap_state')} | "
                f"{peg.get('unabsorbed_fraction')} | "
                f"{inst.get('instability_score', 'UNKNOWN')} | "
                f"{'; '.join(c['reason_it_may_be_wrong'])} |")
    else:
        lines.append("No candidates passed the hard gates today "
                     "(fail-closed is the correct behavior).")
    if unranked:
        lines += ["", "## Gated / diagnostic-only cards", ""]
        for c in unranked:
            lines.append(f"- **{c['ticker']}** ({c['event_id']}): "
                         f"gates={c['gates']}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "md": md_path}
