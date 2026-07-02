"""Chicken Gate v1.3 Evidence Repair Loop — the gate becomes a teacher.

v1.2 answered "why blocked?".  v1.3 answers "what would I need to PROVE to
unblock it?"  For every gated candidate this engine produces:

* an **Evidence Repair Plan** — every missing/weak/self-reported piece of
  evidence, the exact override field to fill, the confidence required, and
  the maximum gate reachable if fixed;
* an **Unlock Simulation** — re-runs the gate with threshold values filled
  in for MISSING repairable evidence only (present values are never
  replaced, non-repairable hard blocks are never touched), bounded by the
  existing gate's rank (demote-only doctrine survives simulation);
* **Repair priorities** — Priority = (gate_lift*2 + score_lift/10)
  * repairability * (1 - effort), so the operator sees the top 3 fixes
  worth doing first;
* an **Override Template** — a copy/fill JSON block per unlockable ticker,
  generated from the actual repair plan, with do-not-override warnings for
  the non-repairable blocks;
* a **Payload Health Score** — separates "bad candidates" from "bad data
  day" so mass BUY_BLOCKED is never misread as market-wide bearishness.

Hard contracts (tested):
  simulated rank <= existing gate rank; non-repairable hard block =>
  simulated gate BUY_BLOCKED; 0 <= payload health <= 10; priority >= 0;
  the repair plan is advisory — it never changes the live gate; only real
  evidence supplied via overrides changes a later run.

Advisory-only.  No broker calls, no order surface, no execution language.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.chicken_gate import (
        GATE_BUY_ALLOWED,
        GATE_BUY_BLOCKED,
        GATE_BUY_LIMITED,
        GATE_WATCHLIST,
        evaluate_chicken_gate,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from chicken_gate import (
        GATE_BUY_ALLOWED,
        GATE_BUY_BLOCKED,
        GATE_BUY_LIMITED,
        GATE_WATCHLIST,
        evaluate_chicken_gate,
    )

_RANK = {
    GATE_BUY_BLOCKED: 0, GATE_WATCHLIST: 1, GATE_BUY_LIMITED: 2, GATE_BUY_ALLOWED: 3,
}
_GATE = {v: k for k, v in _RANK.items()}

# Hard flags that no override may repair.  Spoilage must be disproven at
# the source (a new evaluation with spoilage_risk honestly False), a
# time-spoiled thesis needs a NEW catalyst (a new thesis, not an edit), and
# governance failure is not overridable by declaration.
NON_REPAIRABLE_HARD_FLAGS: frozenset[str] = frozenset({
    "SPOILAGE_RISK",
    "FRESHNESS_SPOILED",
    "PROCESS_INTEGRITY_BELOW_3",
})

DO_NOT_OVERRIDE_IF: tuple[str, ...] = (
    "spoiled thesis not disproven",
    "gambler fallacy with no causal node change",
    "net edge remains <= 0",
    "process integrity < 3",
)

# v1.3 metadata assertion: nothing in the shipped scoreboard is theoretical.
# Anything listed here would represent claimed-but-unshipped capability and
# is asserted empty by tests.  External DATA constraints (not code) are
# listed separately for honesty.
THEORETICAL_COMPONENTS: tuple[str, ...] = ()
EXTERNAL_DATA_CONSTRAINTS: tuple[str, ...] = (
    "live provider payload quality (null prices / zero CQS on degraded days)",
    "closed-outcome corpus < 50 rows: weights remain judgment-calibrated",
)

# Threshold values used by the unlock simulation for MISSING evidence only.
_SIM_NODE_FIX = {
    "load_bearing_node": "OPERATOR_TO_NAME_NODE",
    "load_bearing_node_score": 7.0,
    "load_bearing_node_evidence_confidence": 0.7,
    "thesis_touches_node": True,
}
_SIM_EDGE_FIX = {
    "model_probability": 0.60,
    "market_implied_probability": 0.50,
    "friction_leakage_estimate": 0.02,
}
_SIM_IAP_FIX = {
    "publicity_saturation_score": 4.0,
    "price_move_since_signal_pct": 5.0,
    "channel_premium_score": 3.0,
}
_SIM_CONFIDENCE_THRESHOLD = 0.7

_COMPONENT_FIELDS: tuple[tuple[str, str], ...] = (
    ("house_edge_score", "house_edge_confidence"),
    ("input_quality_score", "input_quality_confidence"),
    ("process_integrity_score", "process_integrity_confidence"),
    ("label_authenticity_score", "label_authenticity_confidence"),
    ("residual_bone_value_score", "residual_bone_value_confidence"),
)

_EFFORT: dict[str, float] = {
    "LOAD_BEARING_NODE": 0.4,       # real research
    "NET_EDGE": 0.5,                # probability work
    "IAP_EVIDENCE": 0.3,
    "FIRST_SIGNAL_DATE": 0.1,
    "COMPONENT_CONFIDENCE": 0.2,
    "CHANNEL_VERIFICATION": 0.2,
    "OPERATOR_HOLDINGS": 0.1,
    "FIVE_MODEL_SYNTHESIS": 0.3,
}


def _notes(gate_result: dict[str, Any]) -> list[str]:
    return [str(n) for n in gate_result.get("EVIDENCE_NOTES", [])]


def _hard_flags(gate_result: dict[str, Any]) -> list[str]:
    raw = str(gate_result.get("HARD_FLAG_TRIGGERED") or "NONE")
    return [] if raw == "NONE" else [f.strip() for f in raw.split(";")]


def has_non_repairable_block(gate_result: dict[str, Any]) -> bool:
    return any(f in NON_REPAIRABLE_HARD_FLAGS for f in _hard_flags(gate_result))


def _item(
    *, field: str, status: str, affected_score: str, affected_gate_rule: str,
    required_evidence: str, expected_data_type: str, min_confidence: float,
    override_field: str, max_gate_if_fixed: str, repairable: bool, reason: str,
    repair_key: str,
) -> dict[str, Any]:
    return {
        "missing_or_weak_field": field,
        "current_status": status,
        "affected_score": affected_score,
        "affected_gate_rule": affected_gate_rule,
        "required_evidence": required_evidence,
        "expected_data_type": expected_data_type,
        "minimum_confidence_to_unlock": min_confidence,
        "operator_override_field": override_field,
        "max_gate_if_fixed": max_gate_if_fixed,
        "repairable": repairable,
        "reason": reason,
        "repair_key": repair_key,
    }


def build_evidence_repair_plan(
    gate_result: dict[str, Any], thesis_inputs: dict[str, Any]
) -> list[dict[str, Any]]:
    """Derive every repair item from the gate's own flags, caps, and notes."""
    plan: list[dict[str, Any]] = []
    notes = _notes(gate_result)
    flags = _hard_flags(gate_result)
    cap_rules = {c.get("rule") for c in gate_result.get("CAP_RULES_TRIGGERED", [])}

    # -- Load-bearing node ---------------------------------------------------
    if gate_result.get("THESIS_TOUCHES_NODE") is not True:
        missing_name = gate_result.get("LOAD_BEARING_NODE") == "INSUFFICIENT_EVIDENCE"
        plan.append(_item(
            field="LOAD_BEARING_NODE",
            status="MISSING" if missing_name else "WEAK",
            affected_score="LOAD_BEARING_NODE_SCORE",
            affected_gate_rule="missing/unproven load-bearing node caps at BUY_LIMITED",
            required_evidence=(
                "Name the economic node carrying this thesis (distribution, "
                "order book, margin segment, pricing power, regulation, data) "
                "and show the thesis touches it."
            ),
            expected_data_type="string + score 0-10 + confidence 0-1 + bool",
            min_confidence=0.7,
            override_field=(
                "load_bearing_node / load_bearing_node_score / "
                "load_bearing_node_evidence_confidence / thesis_touches_node"
            ),
            max_gate_if_fixed="BUY_ALLOWED if no other caps/hard blocks remain",
            repairable=True,
            reason=(
                "The thesis cannot exceed BUY_LIMITED unless it touches the "
                "node doing the heavy lifting."
            ),
            repair_key="LOAD_BEARING_NODE",
        ))

    # -- Net edge -------------------------------------------------------------
    if "NET_EDGE_NON_POSITIVE" in flags:
        plan.append(_item(
            field="NET_EDGE", status="HARD_BLOCKED", affected_score="NET_EDGE",
            affected_gate_rule="NET_EDGE <= 0 hard-blocks",
            required_evidence=(
                "Model probability must exceed market-implied probability "
                "plus friction leakage.  Present values already fail this; "
                "only genuinely better evidence (not wishful edits) repairs it."
            ),
            expected_data_type=(
                "model_probability, market_implied_probability, "
                "friction_leakage_estimate (0-1 decimals)"
            ),
            min_confidence=0.8,
            override_field=(
                "model_probability / market_implied_probability / "
                "friction_leakage_estimate"
            ),
            max_gate_if_fixed="depends on recalculated edge",
            repairable=True,
            reason="No positive edge after friction.",
            repair_key="NET_EDGE",
        ))
    elif gate_result.get("NET_EDGE_STATUS") == "INSUFFICIENT_EVIDENCE":
        plan.append(_item(
            field="NET_EDGE", status="MISSING", affected_score="NET_EDGE",
            affected_gate_rule="NET_EDGE INSUFFICIENT_EVIDENCE caps at BUY_LIMITED",
            required_evidence=(
                "Supply a model probability and a market-implied probability "
                "(plus friction) so net edge is computable."
            ),
            expected_data_type=(
                "model_probability, market_implied_probability, "
                "friction_leakage_estimate (0-1 decimals)"
            ),
            min_confidence=0.8,
            override_field=(
                "model_probability / market_implied_probability / "
                "friction_leakage_estimate"
            ),
            max_gate_if_fixed="BUY_ALLOWED if computed edge > 0 and nothing else caps",
            repairable=True,
            reason="Edge is not computable, so the gate fails closed.",
            repair_key="NET_EDGE",
        ))

    # -- IAP evidence slots ----------------------------------------------------
    iap_slot_notes = [n for n in notes if n in (
        "INSUFFICIENT_EVIDENCE_CROWDING", "INSUFFICIENT_EVIDENCE_LATE_ADOPTION",
        "INSUFFICIENT_EVIDENCE_PRICE_MOVE_SINCE_SIGNAL",
        "INSUFFICIENT_EVIDENCE_SOURCE_CHANNEL",
    )]
    if iap_slot_notes:
        plan.append(_item(
            field="IAP_EVIDENCE", status="WEAK",
            affected_score="IAP_EFFECTIVE",
            affected_gate_rule=(
                "incomplete IAP evidence floors effective IAP at 5+3*(1-conf); "
                ">= 8 hard-blocks"
            ),
            required_evidence=(
                "Fill the missing lateness evidence slots: "
                + ", ".join(iap_slot_notes)
            ),
            expected_data_type=(
                "information_access_premium / publicity_saturation_score 0-10, "
                "price_move_since_signal_pct %, channel_premium_score 0-10"
            ),
            min_confidence=0.7,
            override_field=(
                "information_access_premium / publicity_saturation_score / "
                "price_move_since_signal_pct / channel_premium_score"
            ),
            max_gate_if_fixed="removes the silence floor; gate then follows real IAP",
            repairable=True,
            reason="Silence is suspicious: missing lateness evidence is penalised.",
            repair_key="IAP_EVIDENCE",
        ))

    # -- First-signal date -------------------------------------------------------
    if "INSUFFICIENT_EVIDENCE_FIRST_SIGNAL_DATE" in notes:
        plan.append(_item(
            field="THESIS_FIRST_SIGNAL_DATE", status="MISSING",
            affected_score="FRESHNESS_MULTIPLIER",
            affected_gate_rule="unknown first-signal date takes a x0.85 haircut",
            required_evidence="When did this thesis first become knowable to anyone?",
            expected_data_type="ISO date (thesis_first_signal_date) or thesis_age_days",
            min_confidence=0.7,
            override_field="thesis_first_signal_date",
            max_gate_if_fixed="restores true freshness (may also DEMOTE if actually old)",
            repairable=True,
            reason="Unknown age is never assumed fresh.",
            repair_key="FIRST_SIGNAL_DATE",
        ))

    # -- Self-reported / missing component confidences ---------------------------
    weak_components = [
        n for n in notes
        if ("_confidence: missing" in n) or ("INSUFFICIENT_EVIDENCE -> neutral" in n)
    ]
    if weak_components:
        plan.append(_item(
            field="COMPONENT_EVIDENCE_CONFIDENCE", status="SELF_REPORTED",
            affected_score="RAW_VALIDATED_SCORE",
            affected_gate_rule="score * (0.5 + 0.5*confidence) haircut on every component",
            required_evidence=(
                "Back each component score with cited evidence and a "
                "confidence: " + "; ".join(weak_components[:4])
                + ("..." if len(weak_components) > 4 else "")
            ),
            expected_data_type="per-component score 0-10 (or 0-1) + confidence 0-1",
            min_confidence=_SIM_CONFIDENCE_THRESHOLD,
            override_field=(
                "house_edge_score/_confidence, input_quality_score/_confidence, "
                "process_integrity_score/_confidence, label_authenticity_score/"
                "_confidence, residual_bone_value_score/_confidence"
            ),
            max_gate_if_fixed="recovers up to the raw inflation leakage "
            f"({gate_result.get('RAW_INFLATION_LEAKAGE')})",
            repairable=True,
            reason="Unverified merit is half-trusted by design.",
            repair_key="COMPONENT_CONFIDENCE",
        ))

    # -- Channel verification cap -------------------------------------------------
    if "CHANNEL_PREMIUM_GTE_8_UNVERIFIED" in cap_rules:
        plan.append(_item(
            field="RAW_EVIDENCE_INDEPENDENTLY_VERIFIED", status="CAPPED",
            affected_score="CHANNEL_MULTIPLIER",
            affected_gate_rule="packaged channel >= 8 without verification caps at WATCHLIST",
            required_evidence=(
                "Verify the underlying raw evidence independently of the "
                "packaged channel that delivered the idea."
            ),
            expected_data_type="bool (raw_evidence_independently_verified)",
            min_confidence=0.8,
            override_field="raw_evidence_independently_verified",
            max_gate_if_fixed="removes the WATCHLIST cap (channel demotion still applies)",
            repairable=True,
            reason="Restaurant-channel ideas need butcher-level verification.",
            repair_key="CHANNEL_VERIFICATION",
        ))

    # -- Operator holdings ----------------------------------------------------------
    if "INSUFFICIENT_EVIDENCE_HOLDINGS" in notes:
        plan.append(_item(
            field="OPERATOR_HOLDINGS", status="MISSING",
            affected_score="OPERATOR_FIT_SCORE",
            affected_gate_rule="missing holdings: neutral fit 5 with x0.90 haircut",
            required_evidence="Enable verified holdings so fit is computed, not assumed.",
            expected_data_type="use_verified_holdings: true (or holdings list)",
            min_confidence=1.0,
            override_field="use_verified_holdings",
            max_gate_if_fixed="removes the fit-confidence haircut",
            repairable=True,
            reason="Portfolio fit should come from canonical holdings truth.",
            repair_key="OPERATOR_HOLDINGS",
        ))

    # -- Five-model synthesis audit ---------------------------------------------------
    if "INSUFFICIENT_EVIDENCE_FIVE_MODEL_SYNTHESIS" in notes:
        plan.append(_item(
            field="FIVE_MODEL_SYNTHESIS", status="MISSING",
            affected_score="CHICKEN_SYNTH_FINAL_SCORE",
            affected_gate_rule=(
                "unaudited synthesized thesis caps BUY_ALLOWED at BUY_LIMITED"
            ),
            required_evidence=(
                "Run the five-model synthesis for this run date so the "
                "synthesized thesis language is audited by the gate."
            ),
            expected_data_type="five-model report for run_date (or structured outputs)",
            min_confidence=0.7,
            override_field="(run scripts/run_five_model_synthesis.ps1)",
            max_gate_if_fixed="BUY_ALLOWED becomes reachable again",
            repairable=True,
            reason="Model language must pass the same gate as the raw candidate.",
            repair_key="FIVE_MODEL_SYNTHESIS",
        ))

    # -- Non-repairable hard blocks ------------------------------------------------------
    for flag, reason in (
        ("SPOILAGE_RISK",
         "Toxic-transfer signature.  Not overridable by declaration — only a "
         "fresh evaluation with spoilage honestly disproven at source."),
        ("FRESHNESS_SPOILED",
         "Time already ate this thesis.  A new fresh catalyst is a NEW "
         "thesis, not an override of this one."),
        ("PROCESS_INTEGRITY_BELOW_3",
         "Governance failure.  Cannot be repaired by operator assertion."),
    ):
        if flag in flags:
            plan.append(_item(
                field=flag, status="HARD_BLOCKED", affected_score="FINAL_ACTION_GATE",
                affected_gate_rule=f"{flag} hard-blocks",
                required_evidence=reason,
                expected_data_type="not overridable",
                min_confidence=1.0,
                override_field="(none — do not override)",
                max_gate_if_fixed=GATE_BUY_BLOCKED,
                repairable=False,
                reason=reason,
                repair_key=flag,
            ))

    # -- Gambler's fallacy (guarded repair) -------------------------------------------------
    if "GAMBLERS_FALLACY_NO_NODE_CHANGE_EVIDENCE" in flags:
        plan.append(_item(
            field="NODE_CHANGE_EVIDENCE", status="HARD_BLOCKED",
            affected_score="GAMBLERS_FALLACY_FLAG",
            affected_gate_rule="reversal language without causal node change hard-blocks",
            required_evidence=(
                "Name the CAUSAL node change (SUPPLY/DEMAND/MANAGEMENT/"
                "REGULATORY/FLOW/FUNDAMENTAL) with real evidence — or drop "
                "the reversal thesis.  'It fell a lot' is not evidence."
            ),
            expected_data_type="node_change_evidence enum + supporting evidence",
            min_confidence=0.8,
            override_field="node_change_evidence",
            max_gate_if_fixed="unblocks with a REVERSAL_REQUIRES_NODE_CONFIRMATION warning",
            repairable=True,
            reason="The wheel owes you nothing; a node change might.",
            repair_key="GAMBLERS_FALLACY",
        ))

    return plan


# ---------------------------------------------------------------------------
# Unlock simulation
# ---------------------------------------------------------------------------


def _apply_repair(thesis: dict[str, Any], repair_key: str) -> dict[str, Any]:
    """Fill threshold values for one repair key — MISSING evidence only.

    Present values are never replaced: simulation may complete the picture,
    never repaint it.
    """
    fixed = dict(thesis)

    def fill(defaults: dict[str, Any]) -> None:
        for key, value in defaults.items():
            if fixed.get(key) is None:
                fixed[key] = value

    if repair_key == "LOAD_BEARING_NODE":
        fill(_SIM_NODE_FIX)
        if fixed.get("thesis_touches_node") is not True:
            fixed["thesis_touches_node"] = True  # the one asserted threshold
    elif repair_key == "NET_EDGE":
        fill(_SIM_EDGE_FIX)
    elif repair_key == "IAP_EVIDENCE":
        fill(_SIM_IAP_FIX)
    elif repair_key == "FIRST_SIGNAL_DATE":
        if fixed.get("thesis_age_days") is None and not fixed.get("thesis_first_signal_date"):
            fixed["thesis_age_days"] = 1.0
    elif repair_key == "COMPONENT_CONFIDENCE":
        for score_key, conf_key in _COMPONENT_FIELDS:
            if fixed.get(score_key) is not None and fixed.get(conf_key) is None:
                fixed[conf_key] = _SIM_CONFIDENCE_THRESHOLD
            elif fixed.get(score_key) is None:
                fixed[score_key] = 5.0 if not score_key.startswith(
                    ("label_", "residual_")
                ) else 0.5
                fixed[conf_key] = _SIM_CONFIDENCE_THRESHOLD
    elif repair_key == "CHANNEL_VERIFICATION":
        fixed["raw_evidence_independently_verified"] = True
    elif repair_key == "OPERATOR_HOLDINGS":
        fixed["use_verified_holdings"] = True
    elif repair_key == "GAMBLERS_FALLACY":
        if str(fixed.get("node_change_evidence") or "NONE").upper() == "NONE":
            fixed["node_change_evidence"] = "FUNDAMENTAL_CHANGE"
    # FIVE_MODEL_SYNTHESIS and non-repairable keys change nothing here; the
    # synthesis cap is handled by the bridge (it is not a thesis field).
    return fixed


def simulate_unlock(
    thesis_inputs: dict[str, Any],
    gate_result: dict[str, Any],
    existing_gate: str,
    *,
    repair_plan: list[dict[str, Any]] | None = None,
    holdings: list[dict[str, Any]] | None = None,
    now: Any = None,
) -> dict[str, Any]:
    """Best possible gate if all repairable MISSING evidence were supplied.

    Advisory prioritization only — never a recommendation, never changes the
    live gate.  Bounded by the existing gate rank; non-repairable hard
    blocks pin the simulation at BUY_BLOCKED.
    """
    plan = repair_plan if repair_plan is not None else build_evidence_repair_plan(
        gate_result, thesis_inputs
    )
    existing_rank = _RANK.get(str(existing_gate), 0)

    if has_non_repairable_block(gate_result):
        return {
            "simulated_max_repairable_gate": GATE_BUY_BLOCKED,
            "simulated_final_score": 0.0,
            "bounded_by_existing_gate": existing_gate,
            "non_repairable_blocks": [
                f for f in _hard_flags(gate_result) if f in NON_REPAIRABLE_HARD_FLAGS
            ],
            "repairs_applied": [],
        }

    repaired = dict(thesis_inputs)
    applied: list[str] = []
    for item in plan:
        if item["repairable"]:
            repaired = _apply_repair(repaired, item["repair_key"])
            applied.append(item["repair_key"])

    result = evaluate_chicken_gate(repaired, now=now, holdings=holdings)
    simulated_rank = min(existing_rank, _RANK[result["FINAL_ACTION_GATE"]])
    return {
        "simulated_max_repairable_gate": _GATE[simulated_rank],
        "simulated_final_score": result["FINAL_SCORE"],
        "bounded_by_existing_gate": existing_gate,
        "non_repairable_blocks": [],
        "repairs_applied": applied,
    }


def prioritize_repairs(
    thesis_inputs: dict[str, Any],
    gate_result: dict[str, Any],
    existing_gate: str,
    repair_plan: list[dict[str, Any]],
    *,
    holdings: list[dict[str, Any]] | None = None,
    now: Any = None,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """Priority = (gate_lift*2 + score_lift/10) * repairability * (1-effort)."""
    existing_rank = _RANK.get(str(existing_gate), 0)
    current_rank = min(existing_rank, _RANK[gate_result["FINAL_ACTION_GATE"]])
    current_score = float(gate_result["FINAL_SCORE"])

    ranked: list[dict[str, Any]] = []
    for item in repair_plan:
        if not item["repairable"]:
            ranked.append({**item, "priority": 0.0, "expected_gate_after_fix": None})
            continue
        fixed = _apply_repair(dict(thesis_inputs), item["repair_key"])
        result = evaluate_chicken_gate(fixed, now=now, holdings=holdings)
        after_rank = min(existing_rank, _RANK[result["FINAL_ACTION_GATE"]])
        gate_lift = max(0, after_rank - current_rank)
        score_lift = max(0.0, float(result["FINAL_SCORE"]) - current_score)
        effort = _EFFORT.get(item["repair_key"], 0.3)
        priority = (gate_lift * 2 + score_lift / 10.0) * (1.0 - effort)
        ranked.append({
            **item,
            "priority": round(max(0.0, priority), 4),
            "expected_gate_after_fix": _GATE[after_rank],
            "expected_score_after_fix": result["FINAL_SCORE"],
        })
    ranked.sort(key=lambda r: r["priority"], reverse=True)
    return ranked[:top_n]


# ---------------------------------------------------------------------------
# Override template autogeneration
# ---------------------------------------------------------------------------

_TEMPLATE_FIELDS: dict[str, Any] = {
    "thesis_override": "",
    "load_bearing_node": "",
    "load_bearing_node_score": None,
    "load_bearing_node_evidence_confidence": None,
    "thesis_touches_node": None,
    "node_change_evidence": "NONE",
    "model_probability": None,
    "market_implied_probability": None,
    "friction_leakage_estimate": None,
    "channel_premium_score": None,
    "raw_evidence_independently_verified": None,
    "thesis_first_signal_date": None,
    "catalyst_date": None,
    "catalyst_outcome_known": None,
    "information_access_premium": None,
    "publicity_saturation_score": None,
    "price_move_since_signal_pct": None,
    "label_authenticity_score": None,
    "label_authenticity_confidence": None,
    "house_edge_score": None,
    "house_edge_confidence": None,
    "input_quality_score": None,
    "input_quality_confidence": None,
    "process_integrity_score": None,
    "process_integrity_confidence": None,
    "residual_bone_value_score": None,
    "residual_bone_value_confidence": None,
    "use_verified_holdings": None,
    "operator_notes": "",
    "evidence_links_or_sources": [],
}


def build_override_template(
    rows: list[dict[str, Any]],
    payload_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One copy/fill template block per unlockable (repairable, sub-ALLOWED)
    candidate, generated from the actual repair plans.

    The ``_meta`` block carries operator instructions and the payload-health
    warning so a degraded data day is disclosed inside the template itself.
    """
    template: dict[str, Any] = {}
    for row in rows:
        gate = row.get("FINAL_ACTION_GATE")
        plan = row.get("EVIDENCE_REPAIR_PLAN") or []
        repairable_items = [p for p in plan if p.get("repairable")]
        if gate == GATE_BUY_ALLOWED or not repairable_items:
            continue
        block = dict(_TEMPLATE_FIELDS)
        block["_priority_repairs"] = [
            {
                "fix": p["missing_or_weak_field"],
                "fill": p["operator_override_field"],
                "why": p["reason"],
                "priority": p.get("priority"),
            }
            for p in (row.get("TOP_REPAIRS") or repairable_items)[:3]
        ]
        block["do_not_override_if"] = list(DO_NOT_OVERRIDE_IF)
        non_repairable = [p["missing_or_weak_field"] for p in plan if not p["repairable"]]
        if non_repairable:
            block["_non_repairable_do_not_touch"] = non_repairable
        sim = row.get("UNLOCK_SIMULATION") or {}
        if sim.get("simulated_max_repairable_gate") is not None:
            block["_max_simulated_repairable_gate"] = sim["simulated_max_repairable_gate"]
        template[row["TICKER"]] = block

    if template:
        meta: dict[str, Any] = {
            "instructions": (
                "Copy filled ticker blocks into "
                "runtime/chicken_gate_thesis_overrides.json.  Only supply "
                "evidence you can cite; declared confidence without evidence "
                "is still haircut.  Advisory-only: overrides change a LATER "
                "run's gate, never this one."
            ),
        }
        if isinstance(payload_health, dict):
            meta["payload_health_score"] = payload_health.get("payload_health_score")
            if payload_health.get("system_note"):
                meta["payload_health_warning"] = payload_health["system_note"]
        template["_meta"] = meta
    return template


# ---------------------------------------------------------------------------
# Payload health diagnostic
# ---------------------------------------------------------------------------


def _rate(hits: int, total: int) -> float:
    return (hits / total) if total > 0 else 0.0


def build_payload_health(
    payload: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Separates bad candidates from a bad data day.

    PayloadHealthScore = 10 * (0.25*price + 0.25*cqs_nonzero + 0.20*prob
                               + 0.15*thesis + 0.15*channel)
    """
    movers = payload.get("price_movers", {}).get("movers", []) or []
    n_movers = len(movers)
    price_ok = sum(1 for m in movers if m.get("price") is not None)
    channel_ok = sum(1 for m in movers if (m.get("provider") or m.get("source")))

    n_rows = len(rows)
    cqs_nonzero = sum(1 for r in rows if (r.get("EXISTING_SCORE") or 0) > 0)
    thesis_ok = 0
    prob_ok = 0
    node_missing = 0
    weak_why = 0
    for row in rows:
        inputs = row.get("chicken_gate_thesis_inputs") or {}
        if str(inputs.get("thesis_text") or "").strip():
            thesis_ok += 1
        if inputs.get("model_probability") is not None:
            prob_ok += 1
        if inputs.get("load_bearing_node") is None:
            node_missing += 1
        block = row.get("chicken_gate") or {}
        if float(block.get("iap_effective") or 0) >= 5.0:
            weak_why += 1

    score = 10.0 * (
        0.25 * _rate(price_ok, n_movers)
        + 0.25 * _rate(cqs_nonzero, n_rows)
        + 0.20 * _rate(prob_ok, n_rows)
        + 0.15 * _rate(thesis_ok, n_rows)
        + 0.15 * _rate(channel_ok, n_movers)
    )
    score = max(0.0, min(10.0, score))

    blocked = [r for r in rows if r.get("FINAL_ACTION_GATE") == GATE_BUY_BLOCKED]
    degraded = score < 5.0
    health = {
        "candidate_count": n_movers,
        "buy_side_count": n_rows,
        "blocked_count": len(blocked),
        "blocked_due_to_payload_quality": len(blocked) if degraded else 0,
        "null_price_count": n_movers - price_ok,
        "zero_cqs_count": n_rows - cqs_nonzero,
        "weak_why_today_count": weak_why,
        "missing_probability_count": n_rows - prob_ok,
        "missing_load_bearing_node_count": node_missing,
        "payload_health_score": round(score, 4),
        "degraded": degraded,
        "operator_action": (
            "Fix live providers / payload freshness before interpreting gates."
            if degraded else "Payload quality adequate; gates reflect candidate merit."
        ),
    }
    if degraded:
        health["system_note"] = (
            "DAILY_PAYLOAD_DEGRADED: Do not interpret mass BUY_BLOCKED as "
            "market-wide bearishness; interpret as insufficient evidence quality."
        )
    return health


# ---------------------------------------------------------------------------
# v1.3 daily summary
# ---------------------------------------------------------------------------


def build_v13_summary(
    integration: dict[str, Any],
    payload_health: dict[str, Any],
    *,
    version: str,
    override_template_path: str,
) -> dict[str, Any]:
    rows = integration.get("rows", [])
    blocker_counts: dict[str, int] = {}
    repair_counts: dict[str, int] = {}
    non_repairable: list[str] = []
    unlockable: list[dict[str, Any]] = []
    caps = 0
    hard_blocks = 0
    synth_evaluated = 0

    for row in rows:
        flags = str(row.get("CHICKEN_HARD_FLAG_TRIGGERED") or "NONE")
        if flags not in ("NONE", "CHICKEN_GATE_DISABLED_DEBUG_ONLY"):
            hard_blocks += 1
            for flag in flags.split(";"):
                flag = flag.strip()
                blocker_counts[flag] = blocker_counts.get(flag, 0) + 1
        if row.get("CHICKEN_CAP_RULES_TRIGGERED"):
            caps += 1
            for cap in row["CHICKEN_CAP_RULES_TRIGGERED"]:
                rule = cap.get("rule", "?")
                blocker_counts[rule] = blocker_counts.get(rule, 0) + 1
        if row.get("FIVE_MODEL_ROUNDTRIP"):
            synth_evaluated += 1
        for item in row.get("EVIDENCE_REPAIR_PLAN") or []:
            if item.get("repairable"):
                key = item["missing_or_weak_field"]
                repair_counts[key] = repair_counts.get(key, 0) + 1
            else:
                non_repairable.append(f"{row['TICKER']}:{item['missing_or_weak_field']}")
        sim = row.get("UNLOCK_SIMULATION") or {}
        sim_gate = sim.get("simulated_max_repairable_gate")
        if (
            sim_gate is not None
            and _RANK.get(sim_gate, 0) > _RANK.get(row.get("FINAL_ACTION_GATE"), 0)
        ):
            unlockable.append({
                "ticker": row["TICKER"],
                "current_gate": row["FINAL_ACTION_GATE"],
                "simulated_max_repairable_gate": sim_gate,
            })

    top = lambda d: [k for k, _ in sorted(d.items(), key=lambda kv: -kv[1])[:5]]  # noqa: E731
    return {
        "version": version,
        "candidate_count": payload_health.get("candidate_count"),
        "evaluated_count": len(rows),
        "excluded_count": len(integration.get("excluded_rows", [])),
        "demotions": len(integration.get("demotions", [])),
        "hard_blocks": hard_blocks,
        "caps": caps,
        "five_model_roundtrip_evaluated": synth_evaluated,
        "payload_health_score": payload_health.get("payload_health_score"),
        "payload_degraded": payload_health.get("degraded"),
        "top_blockers": top(blocker_counts),
        "top_repair_fields": top(repair_counts),
        "top_unlockable_candidates": unlockable[:10],
        "non_repairable_blocks": non_repairable[:20],
        "override_template_path": override_template_path,
        "audit_lines": integration.get("audit_lines", []),
        "safety": advisory_safety_stamps(),
    }


__all__ = [
    "NON_REPAIRABLE_HARD_FLAGS",
    "DO_NOT_OVERRIDE_IF",
    "THEORETICAL_COMPONENTS",
    "EXTERNAL_DATA_CONSTRAINTS",
    "has_non_repairable_block",
    "build_evidence_repair_plan",
    "simulate_unlock",
    "prioritize_repairs",
    "build_override_template",
    "build_payload_health",
    "build_v13_summary",
]
