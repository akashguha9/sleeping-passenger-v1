"""Stage 2 — Five Isolated Model Lanes.

The combined five-model synthesis used to do everything at once: generate fresh
candidates, review holdings, apply Moltbook memory, clean stale names, rank, and
produce the final decision. That single context let old trade-log names, the
static fallback universe, prior candidates and Moltbook memory leak into the
model-facing payload and re-appear as "fresh discovery".

This module is the fix. AFTER the Fresh Discovery Contract
(``scripts.fresh_discovery_contract``) has already decided which names are
live/verified/current-session, each of the five models runs as an *isolated
review lane* that can see ONLY the clean Fresh Discovery Payload — nothing else.
A lane cannot see old trade logs, Moltbook names, old watchlists, prior
candidates, the static fallback universe, seed data, fixtures, prompt examples,
or cache-only names unless that name was revalidated by today's live discovery
(in which case it is already in the clean payload).

Hard guarantees enforced here
-----------------------------
* The clean payload contains ONLY candidates the contract marked
  ``allowed_in_fresh_discovery`` (live, VERIFIED_LIVE, current-session, one of
  the three live evidence types, not from cache/fallback/moltbook/trade-log).
* ``validate_model_lane_input`` re-checks that predicate per candidate and
  raises ``MODEL_LANE_INPUT_PROVENANCE_VIOLATION`` if anything stale slipped in
  (defence in depth — the contract should already have excluded it).
* If ``fresh_discovery_status != FRESH_DISCOVERY_OK`` the lanes are SKIPPED; no
  prompts are built and no model is called.
* ``validate_model_lane_output`` drops any ticker a model emits that is not in
  the clean payload (``MODEL_OUTPUT_UNKNOWN_TICKER_VIOLATION``) and any known
  stale/Moltbook/static name a model dragged in
  (``MODEL_CONTEXT_CONTAMINATION_VIOLATION``). Invalid output is quarantined,
  never silently accepted.

Advisory-only. No broker, no order generation, no position sizing, no buy/sell
commands, no exact trade instructions. The human execution gate stays LOCKED.
Pure module: importing it has no side effects. Tests inject deterministic fake
model clients; no real external API call is required.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.advisory_contract import advisory_safety_stamps, human_only_stamp
    from scripts.daily_payload import normalize_ticker
    from scripts.fresh_discovery_contract import (
        BLOCKED_EVIDENCE_TYPES,
        LIVE_EVIDENCE_TYPES,
        STATUS_OK,
        VERIFIED_LIVE,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps, human_only_stamp
    from daily_payload import normalize_ticker
    from fresh_discovery_contract import (
        BLOCKED_EVIDENCE_TYPES,
        LIVE_EVIDENCE_TYPES,
        STATUS_OK,
        VERIFIED_LIVE,
    )


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

MODEL_LANES: tuple[str, ...] = ("gpt", "claude", "gemini", "grok", "mistral")

FRESH_DISCOVERY_OK = STATUS_OK  # "FRESH_DISCOVERY_OK"
LANES_SKIPPED = "MODEL_LANES_SKIPPED_NO_FRESH_DISCOVERY"
LANES_COMPLETED = "MODEL_LANES_COMPLETED"

# Violation codes
INPUT_PROVENANCE_VIOLATION = "MODEL_LANE_INPUT_PROVENANCE_VIOLATION"
UNKNOWN_TICKER_VIOLATION = "MODEL_OUTPUT_UNKNOWN_TICKER_VIOLATION"
CONTEXT_CONTAMINATION_VIOLATION = "MODEL_CONTEXT_CONTAMINATION_VIOLATION"
IGNORED_DEFENSE_VIOLATION = "MODEL_IGNORED_INTERPRETATION_DEFENSE_VIOLATION"
IGNORED_P2_DEFENSE_VIOLATION = "MODEL_IGNORED_P2_INTERPRETATION_DEFENSE_VIOLATION"

VALID_CLASSIFICATIONS = (
    "MANUAL_CONSIDERATION",
    "WATCH",
    "WAIT",
    "AVOID",
    "RISK_BLOCK",
)
VALID_GRADES = ("HIGH", "MEDIUM", "LOW")

# The output schema's classification lists, mapped to their per-item label.
_OUTPUT_LISTS: dict[str, str] = {
    "manual_consideration": "MANUAL_CONSIDERATION",
    "watch": "WATCH",
    "wait": "WAIT",
    "avoid": "AVOID",
    "risk_blocks": "RISK_BLOCK",
}


class ModelLaneInputProvenanceViolation(RuntimeError):
    """Raised when a model lane input candidate is not clean live evidence."""


# ---------------------------------------------------------------------------
# Stage 2a — the clean Fresh Discovery Payload
# ---------------------------------------------------------------------------

def _enrichment_for_ticker(payload: dict[str, Any] | None, ticker: str) -> dict[str, str]:
    """Best-effort country/region/sector/theme from the daily payload rows.

    These descriptive fields are not part of the provenance contract; when the
    live payload row carries them we pass them through, otherwise UNKNOWN. They
    are never used to admit a name — admission is the contract's job.
    """
    out = {
        "country": "UNKNOWN", "region": "UNKNOWN", "sector": "UNKNOWN",
        "theme": "UNKNOWN", "currency": "UNKNOWN", "catalyst": "",
    }
    if not isinstance(payload, dict):
        return out
    for key in ("price_movers", "news_events", "filings_events"):
        block = payload.get(key) or {}
        rows = block.get("movers") if key == "price_movers" else block.get("events")
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            if normalize_ticker(row.get("ticker") or row.get("symbol")) != ticker:
                continue
            for field in ("country", "region", "sector", "theme", "currency"):
                value = row.get(field)
                if value:
                    out[field] = str(value)
            catalyst = row.get("catalyst") or row.get("why_today") or row.get("headline")
            if catalyst:
                out["catalyst"] = str(catalyst)
    return out


def build_clean_fresh_discovery_payload(
    discovery_contract_result: dict[str, Any],
    run_date: str | None = None,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the single clean payload every model lane receives.

    The ONLY input is the Fresh Discovery Contract result. Candidates come
    strictly from ``fresh_discovery_provenance`` (the contract's already-vetted
    live board). When the contract produced no fresh discovery the payload
    carries the ``NO_FRESH_DISCOVERY_GENERATED`` status and an empty candidate
    list — never a padded/static board.
    """
    contract = discovery_contract_result or {}
    status = contract.get("status")
    session_date = run_date or contract.get("current_session_date")

    base = {
        "run_date": session_date,
        "fresh_discovery_status": FRESH_DISCOVERY_OK if status == STATUS_OK else status,
        "execution_gate": "LOCKED",
        "advisory_only": True,
        "candidates": [],
    }

    if status != STATUS_OK:
        return base

    candidates: list[dict[str, Any]] = []
    for prov in contract.get("fresh_discovery_provenance", []):
        if not prov.get("allowed_in_fresh_discovery"):
            continue
        ticker = normalize_ticker(prov.get("ticker"))
        enrich = _enrichment_for_ticker(payload, ticker)
        candidates.append(
            {
                "ticker": ticker,
                "country": enrich["country"],
                "region": enrich["region"],
                "sector": enrich["sector"],
                "theme": enrich["theme"],
                "currency": enrich["currency"],
                "catalyst": enrich["catalyst"],
                "source_payload": prov.get("source_payload"),
                "source_health": prov.get("source_health"),
                "is_live": bool(prov.get("is_live")),
                "generated_at": prov.get("generated_at"),
                "evidence_type": prov.get("evidence_type"),
                "live_evidence_count": int(prov.get("live_evidence_count") or 0),
                "last_live_seen_date": prov.get("last_live_seen_date"),
                "from_cache": bool(prov.get("from_cache")),
                "from_fallback": bool(prov.get("from_fallback")),
                "from_moltbook": bool(prov.get("from_moltbook")),
                "from_trade_log": bool(prov.get("from_trade_log")),
                "allowed_in_fresh_discovery": True,
            }
        )
    base["candidates"] = candidates
    return base


# ---------------------------------------------------------------------------
# Stage 2b — hard input validation
# ---------------------------------------------------------------------------

def candidate_input_allowed(candidate: dict[str, Any]) -> bool:
    """The model-lane input predicate, verbatim from the spec.

    A candidate may enter a model lane ONLY when every provenance flag confirms
    it is genuine live, verified, current-session evidence.
    """
    evidence_type = candidate.get("evidence_type")
    return (
        candidate.get("source_health") == VERIFIED_LIVE
        and candidate.get("is_live") is True
        and evidence_type in LIVE_EVIDENCE_TYPES
        and evidence_type not in BLOCKED_EVIDENCE_TYPES
        and int(candidate.get("live_evidence_count") or 0) >= 1
        and candidate.get("from_cache") is False
        and candidate.get("from_fallback") is False
        and candidate.get("from_moltbook") is False
        and candidate.get("from_trade_log") is False
        and candidate.get("allowed_in_fresh_discovery") is True
    )


def validate_model_lane_input(model_name: str, payload: dict[str, Any]) -> str:
    """Validate the clean payload a lane is about to consume.

    Returns ``MODEL_LANES_SKIPPED_NO_FRESH_DISCOVERY`` when there is no fresh
    discovery (the lane must not run). Returns ``FRESH_DISCOVERY_OK`` when the
    payload is clean. Raises ``ModelLaneInputProvenanceViolation`` if any
    candidate fails the hard provenance predicate.
    """
    status = payload.get("fresh_discovery_status")
    if status != FRESH_DISCOVERY_OK:
        return LANES_SKIPPED

    offenders: list[dict[str, Any]] = []
    for candidate in payload.get("candidates", []):
        if not candidate_input_allowed(candidate):
            offenders.append(
                {
                    "ticker": candidate.get("ticker"),
                    "source_health": candidate.get("source_health"),
                    "evidence_type": candidate.get("evidence_type"),
                    "is_live": candidate.get("is_live"),
                    "from_cache": candidate.get("from_cache"),
                    "from_fallback": candidate.get("from_fallback"),
                    "from_moltbook": candidate.get("from_moltbook"),
                    "from_trade_log": candidate.get("from_trade_log"),
                }
            )
    if offenders:
        names = ", ".join(str(o["ticker"]) for o in offenders)
        raise ModelLaneInputProvenanceViolation(
            f"{INPUT_PROVENANCE_VIOLATION} [{model_name}]: {names}"
        )

    # Interpretation defense must be attached before a lane may run.
    missing_defense = [
        c.get("ticker")
        for c in payload.get("candidates", [])
        if not isinstance(c.get("interpretation_defense"), dict)
    ]
    if missing_defense:
        raise ModelLaneInputProvenanceViolation(
            f"{INPUT_PROVENANCE_VIOLATION} [{model_name}]: interpretation_defense "
            f"missing for {missing_defense}"
        )
    return FRESH_DISCOVERY_OK


def _ensure_interpretation_defense(clean_payload: dict[str, Any]) -> dict[str, Any]:
    """Attach interpretation defense to the clean payload if not already present.

    Lazily imports the engine to avoid a circular import (the engine imports this
    module for ``FRESH_DISCOVERY_OK``). The daily pipeline normally enriches the
    payload itself; this is the safety net for direct callers.
    """
    if clean_payload.get("fresh_discovery_status") != FRESH_DISCOVERY_OK:
        return clean_payload
    candidates = clean_payload.get("candidates", [])
    if candidates and all(isinstance(c.get("interpretation_defense"), dict) for c in candidates):
        return clean_payload
    try:
        from scripts.interpretation_defense_engine import enrich_clean_payload
    except ModuleNotFoundError:  # pragma: no cover - script-style env
        from interpretation_defense_engine import enrich_clean_payload
    return enrich_clean_payload(clean_payload)


def defense_grade_for(candidate: dict[str, Any]) -> str | None:
    defense = candidate.get("interpretation_defense")
    if isinstance(defense, dict):
        return defense.get("interpretation_defense_grade")
    return None


def effective_defense_grade(candidate: dict[str, Any]) -> tuple[str | None, bool]:
    """Return (grade, is_expanded). Expanded P2 grade wins when present."""
    expanded = candidate.get("expanded_interpretation_defense")
    if isinstance(expanded, dict) and expanded.get("expanded_grade"):
        return expanded.get("expanded_grade"), True
    return defense_grade_for(candidate), False


def clean_payload_tickers(payload: dict[str, Any]) -> set[str]:
    return {normalize_ticker(c.get("ticker")) for c in payload.get("candidates", [])}


# ---------------------------------------------------------------------------
# Stage 2c — deterministic prompt builders (no example tickers)
# ---------------------------------------------------------------------------

_SHARED_GUARDRAILS = (
    "You are reviewing only the attached live fresh discovery payload. You are "
    "not allowed to introduce any ticker not present in the payload. You are not "
    "allowed to use old watchlists, Moltbook memory, static universe names, "
    "famous tickers, or prior positions. This is advisory-only. Do not provide "
    "broker actions, position sizes, order types, buy/sell commands, or "
    "execution instructions. Return JSON only using the required schema."
)

# Each lens is descriptive only and deliberately contains NO ticker symbols, so
# a prompt example can never become an output candidate.
_MODEL_LENS: dict[str, str] = {
    "gpt": (
        "GPT lens — decision-hygiene analyst. Judge each payload candidate on "
        "evidence strength, catalyst freshness, contradiction risk and whether "
        "it could teach the operator something. Punish fake confidence."
    ),
    "claude": (
        "Claude lens — repo-aware interpreter. Judge each payload candidate on "
        "whether the live evidence genuinely supports it and on invalidation "
        "clarity. Stay strictly read-only and within the payload."
    ),
    "gemini": (
        "Gemini lens — structural/regime analyst. Judge each payload candidate "
        "on durability, regime fit and chaos risk using only the payload."
    ),
    "grok": (
        "Grok lens — narrative/attention analyst. Judge each payload candidate "
        "on crowd attention, narrative freshness and trap risk using only the "
        "payload."
    ),
    "mistral": (
        "Mistral lens — adversarial auditor. Try to refute each payload "
        "candidate: missing evidence, weak invalidation, overfit narrative. "
        "Default to caution using only the payload."
    ),
}

_REQUIRED_OUTPUT_SCHEMA = {
    "model": "<gpt|claude|gemini|grok|mistral>",
    "run_date": "<run_date>",
    "input_candidate_count": 0,
    "provenance_violations_detected": [],
    "manual_consideration": [],
    "watch": [],
    "wait": [],
    "avoid": [],
    "risk_blocks": [],
    "rejected_due_to_missing_evidence": [],
    "notes": [],
    "model_confidence": "HIGH | MEDIUM | LOW",
}


def _defense_prompt_lines(clean_payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for candidate in clean_payload.get("candidates", []):
        defense = candidate.get("interpretation_defense") or {}
        lines.append(
            f"  {normalize_ticker(candidate.get('ticker'))}: "
            f"grade={defense.get('interpretation_defense_grade')} "
            f"ids={defense.get('interpretation_defense_score')} "
            f"iqs={defense.get('iqs')} mtr={defense.get('mtr')} "
            f"stress_failure_risk={defense.get('stress_failure_risk')} "
            f"hard_blocks={defense.get('hard_blocks') or []} "
            f"warnings={defense.get('warnings') or []}"
        )
    return lines or ["  (none)"]


def _expanded_defense_prompt_lines(clean_payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for candidate in clean_payload.get("candidates", []):
        exp = candidate.get("expanded_interpretation_defense")
        if not isinstance(exp, dict):
            continue
        lines.append(
            f"  {normalize_ticker(candidate.get('ticker'))}: "
            f"expanded_grade={exp.get('expanded_grade')} expanded_ids={exp.get('expanded_ids')} "
            f"amplification={exp.get('distribution_amplification_grade')} "
            f"narrative_substance={exp.get('narrative_substance_gap_grade')} "
            f"incentive={exp.get('incentive_risk_grade')} "
            f"audience_misread={exp.get('audience_misinterpretation_grade')} "
            f"warnings={exp.get('warnings') or []}"
        )
    return lines


def build_model_lane_prompt(model_name: str, clean_payload: dict[str, Any]) -> str:
    """Build the deterministic, isolated prompt for one model lane.

    The prompt embeds ONLY the clean payload. It contains no example tickers and
    no Moltbook/holding/static context. Identical input + output contract across
    all five models; only the lens line differs.
    """
    model = model_name.lower()
    lens = _MODEL_LENS.get(model, "Independent analyst lens.")
    tickers = sorted(clean_payload_tickers(clean_payload))
    lines = [
        f"MODEL LANE: {model.upper()} (isolated fresh-discovery review)",
        "",
        _SHARED_GUARDRAILS,
        "",
        lens,
        "",
        f"fresh_discovery_status: {clean_payload.get('fresh_discovery_status')}",
        f"run_date: {clean_payload.get('run_date')}",
        f"execution_gate: {clean_payload.get('execution_gate')}",
        f"advisory_only: {clean_payload.get('advisory_only')}",
        "",
        "The ONLY tickers you may classify are exactly these "
        f"({len(tickers)}): {tickers or 'NONE'}",
        "Any ticker you output that is not in this list will be dropped and "
        "recorded as a provenance violation.",
        "",
        "INTERPRETATION DEFENSE (advisory quality/risk layer — read before classifying):",
        *_defense_prompt_lines(clean_payload),
        "You must consider interpretation_defense. You may NOT override hard "
        "blocks. You may NOT promote (MANUAL_CONSIDERATION or WATCH) any candidate "
        "whose interpretation_defense_grade is BLOCKED. You must explain if you "
        "disagree with a CAUTION or DEFENSIVE_REVIEW grade, but you cannot ignore it.",
        "",
        "P2 INTERPRETATION EXPANSION (amplification / narrative-substance / "
        "incentive / audience-misread):",
        *(_expanded_defense_prompt_lines(clean_payload) or ["  (not attached)"]),
        "For each candidate you must explicitly consider: (1) Is this signal being "
        "amplified beyond substance? (2) Who benefits if the operator believes it? "
        "(3) Could the operator/model/retail audience misread it? (4) Is the "
        "narrative stronger than the underlying evidence? You may NOT promote "
        "(MANUAL_CONSIDERATION or WATCH) a candidate whose expanded_grade is BLOCKED "
        "or DEFENSIVE_REVIEW.",
        "",
        "CLEAN FRESH DISCOVERY PAYLOAD (JSON — your only allowed input):",
        json.dumps(clean_payload, indent=2, sort_keys=True),
        "",
        "REQUIRED OUTPUT SCHEMA (JSON only):",
        json.dumps(_REQUIRED_OUTPUT_SCHEMA, indent=2, sort_keys=True),
        "",
        "Per-candidate object schema for every classification list:",
        json.dumps(
            {
                "ticker": "<from payload only>",
                "classification": " | ".join(VALID_CLASSIFICATIONS),
                "evidence_strength": "HIGH | MEDIUM | LOW",
                "model_confidence": "HIGH | MEDIUM | LOW",
                "catalyst_freshness": "HIGH | MEDIUM | LOW | MISSING",
                "contradiction_risk": "HIGH | MEDIUM | LOW",
                "chaos_risk": "HIGH | MEDIUM | LOW",
                "reason": "<concise, evidence-based>",
                "invalidation_condition": "missing / not provided OR concise condition",
                "what_must_be_true_before_manual_review": "<concise>",
                "no_action_reason": "<concise>",
            },
            indent=2,
            sort_keys=True,
        ),
        "",
        "Advisory only. No broker action. No execution. Human review required.",
    ]
    return "\n".join(lines)


def build_all_lane_prompts(clean_payload: dict[str, Any]) -> dict[str, str]:
    """Return {model_name: prompt} for all five lanes (empty when skipped)."""
    if clean_payload.get("fresh_discovery_status") != FRESH_DISCOVERY_OK:
        return {}
    return {m: build_model_lane_prompt(m, clean_payload) for m in MODEL_LANES}


# ---------------------------------------------------------------------------
# Stage 2d — output validation / quarantine
# ---------------------------------------------------------------------------

def _grade(value: Any, default: str = "LOW", *, allow_missing: bool = False) -> str:
    text = str(value or "").strip().upper()
    allowed = set(VALID_GRADES) | ({"MISSING"} if allow_missing else set())
    return text if text in allowed else default


def _clean_candidate_item(raw: dict[str, Any], classification: str) -> dict[str, Any]:
    return {
        "ticker": normalize_ticker(raw.get("ticker")),
        "classification": classification,
        "evidence_strength": _grade(raw.get("evidence_strength")),
        "model_confidence": _grade(raw.get("model_confidence")),
        "catalyst_freshness": _grade(raw.get("catalyst_freshness"), default="MISSING", allow_missing=True),
        "contradiction_risk": _grade(raw.get("contradiction_risk")),
        "chaos_risk": _grade(raw.get("chaos_risk")),
        "reason": str(raw.get("reason") or "").strip(),
        "invalidation_condition": str(raw.get("invalidation_condition") or "missing / not provided").strip(),
        "what_must_be_true_before_manual_review": str(
            raw.get("what_must_be_true_before_manual_review") or ""
        ).strip(),
        "no_action_reason": str(raw.get("no_action_reason") or "").strip(),
    }


def validate_model_lane_output(
    model_name: str,
    output: dict[str, Any],
    clean_payload: dict[str, Any],
    *,
    contamination_names: set[str] | None = None,
) -> dict[str, Any]:
    """Quarantine a raw model output against the clean payload.

    * Any ticker not present in the clean payload is dropped. If the dropped
      name is a known stale/Moltbook/static name it is recorded as
      ``MODEL_CONTEXT_CONTAMINATION_VIOLATION``; otherwise as
      ``MODEL_OUTPUT_UNKNOWN_TICKER_VIOLATION``.
    * The returned output is always schema-shaped; invalid input degrades to an
      empty, fully-flagged structure rather than being trusted.
    """
    allowed = clean_payload_tickers(clean_payload)
    contamination = {normalize_ticker(t) for t in (contamination_names or set())}
    # Effective interpretation-defense grade per ticker (expanded P2 wins).
    defense_by_ticker: dict[str, tuple[str | None, bool]] = {
        normalize_ticker(c.get("ticker")): effective_defense_grade(c)
        for c in clean_payload.get("candidates", [])
    }
    output = output if isinstance(output, dict) else {}

    cleaned: dict[str, Any] = {
        "model": model_name.lower(),
        "run_date": output.get("run_date") or clean_payload.get("run_date"),
        "input_candidate_count": len(allowed),
        "provenance_violations_detected": [],
        "manual_consideration": [],
        "watch": [],
        "wait": [],
        "avoid": [],
        "risk_blocks": [],
        "rejected_due_to_missing_evidence": [],
        "notes": [str(n) for n in (output.get("notes") or []) if str(n).strip()],
        "model_confidence": _grade(output.get("model_confidence")),
    }
    violations: list[dict[str, Any]] = []

    def _record(ticker: str, where: str) -> None:
        code = (
            CONTEXT_CONTAMINATION_VIOLATION
            if ticker in contamination
            else UNKNOWN_TICKER_VIOLATION
        )
        violations.append({"ticker": ticker, "list": where, "code": code, "model": model_name.lower()})

    for list_key, classification in _OUTPUT_LISTS.items():
        for raw in output.get(list_key) or []:
            if not isinstance(raw, dict):
                continue
            ticker = normalize_ticker(raw.get("ticker"))
            if not ticker:
                continue
            if ticker not in allowed:
                _record(ticker, list_key)
                continue
            # A model may not promote a BLOCKED candidate (P1 or expanded), nor a
            # candidate the expanded P2 layer capped at DEFENSIVE_REVIEW.
            grade, is_expanded = defense_by_ticker.get(ticker, (None, False))
            if classification in ("MANUAL_CONSIDERATION", "WATCH"):
                if grade == "BLOCKED":
                    violations.append({
                        "ticker": ticker, "list": list_key, "model": model_name.lower(),
                        "code": IGNORED_P2_DEFENSE_VIOLATION if is_expanded else IGNORED_DEFENSE_VIOLATION,
                    })
                    q = _clean_candidate_item(raw, "RISK_BLOCK")
                    q["no_action_reason"] = "interpretation_defense_grade=BLOCKED; promotion quarantined"
                    cleaned["risk_blocks"].append(q)
                    continue
                if is_expanded and grade == "DEFENSIVE_REVIEW":
                    violations.append({
                        "ticker": ticker, "list": list_key, "model": model_name.lower(),
                        "code": IGNORED_P2_DEFENSE_VIOLATION,
                    })
                    q = _clean_candidate_item(raw, "WAIT")
                    q["no_action_reason"] = "expanded_grade=DEFENSIVE_REVIEW; promotion quarantined to WAIT"
                    cleaned["wait"].append(q)
                    continue
            cleaned[list_key].append(_clean_candidate_item(raw, classification))

    # rejected_due_to_missing_evidence may name in-payload tickers only.
    for raw in output.get("rejected_due_to_missing_evidence") or []:
        if isinstance(raw, dict):
            ticker = normalize_ticker(raw.get("ticker"))
            item: Any = _clean_candidate_item(raw, "RISK_BLOCK") if ticker else None
        else:
            ticker = normalize_ticker(raw)
            item = {"ticker": ticker}
        if not ticker:
            continue
        if ticker not in allowed:
            _record(ticker, "rejected_due_to_missing_evidence")
            continue
        cleaned["rejected_due_to_missing_evidence"].append(item)

    cleaned["provenance_violations_detected"] = violations
    return cleaned


# ---------------------------------------------------------------------------
# Stage 2e — running the lanes (injectable clients)
# ---------------------------------------------------------------------------

# A model client is any callable: (model_name, prompt, clean_payload) -> raw dict
ModelClient = Callable[[str, str, dict[str, Any]], dict[str, Any]]


def _default_lane_adapter(model_name: str, prompt: str, clean_payload: dict[str, Any]) -> dict[str, Any]:
    """Deterministic, no-LLM placeholder lane output.

    When no real model client is injected, the pipeline still produces a clean,
    honest structure: every live candidate is parked on WATCH at LOW confidence
    and explicitly flagged ``DETERMINISTIC_PLACEHOLDER_NO_LLM_CALLED``. It never
    invents a name (it only echoes the verified payload) and never fabricates
    conviction. Real model outputs replace this via injected clients or
    ``load_model_lane_outputs_from_artifacts``.
    """
    watch = []
    for c in clean_payload.get("candidates", []):
        watch.append(
            {
                "ticker": c.get("ticker"),
                "classification": "WATCH",
                "evidence_strength": "MEDIUM" if int(c.get("live_evidence_count") or 0) >= 2 else "LOW",
                "model_confidence": "LOW",
                "catalyst_freshness": "MEDIUM",
                "contradiction_risk": "LOW",
                "chaos_risk": "LOW",
                "reason": "Live current-session evidence present; no LLM lane executed.",
                "invalidation_condition": "missing / not provided",
                "what_must_be_true_before_manual_review": "An actual model lane must review this candidate.",
                "no_action_reason": "Deterministic placeholder, advisory only.",
            }
        )
    return {
        "model": model_name.lower(),
        "run_date": clean_payload.get("run_date"),
        "watch": watch,
        "notes": ["DETERMINISTIC_PLACEHOLDER_NO_LLM_CALLED"],
        "model_confidence": "LOW",
    }


def run_isolated_model_lanes(
    clean_payload: dict[str, Any],
    model_clients: dict[str, ModelClient] | None = None,
    *,
    contamination_names: set[str] | None = None,
) -> dict[str, Any]:
    """Run all five lanes over the same clean payload, in isolation.

    Returns a result object with the validated per-lane outputs and an overall
    status. When there is no fresh discovery the lanes are SKIPPED: no prompt is
    built and no client is called.
    """
    status = clean_payload.get("fresh_discovery_status")
    if status != FRESH_DISCOVERY_OK:
        return {
            "status": LANES_SKIPPED,
            "reason": f"fresh_discovery_status={status}; model lanes not run.",
            "run_date": clean_payload.get("run_date"),
            "model_lane_outputs": [],
            "prompts_built": 0,
            "models_called": 0,
            "input_candidate_count": 0,
            "safety": advisory_safety_stamps(),
            "execution": human_only_stamp(),
        }

    # Attach interpretation defense (idempotent) then re-validate provenance +
    # defense presence before any model is called.
    clean_payload = _ensure_interpretation_defense(clean_payload)
    validate_model_lane_input("aggregate", clean_payload)

    clients = dict(model_clients or {})
    outputs: list[dict[str, Any]] = []
    prompts_built = 0
    models_called = 0
    for model in MODEL_LANES:
        prompt = build_model_lane_prompt(model, clean_payload)
        prompts_built += 1
        client = clients.get(model) or _default_lane_adapter
        raw = client(model, prompt, clean_payload)
        models_called += 1
        outputs.append(
            validate_model_lane_output(
                model, raw, clean_payload, contamination_names=contamination_names
            )
        )

    return {
        "status": LANES_COMPLETED,
        "run_date": clean_payload.get("run_date"),
        "model_lane_outputs": outputs,
        "prompts_built": prompts_built,
        "models_called": models_called,
        "input_candidate_count": len(clean_payload.get("candidates", [])),
        "total_provenance_violations": sum(
            len(o.get("provenance_violations_detected", [])) for o in outputs
        ),
        "safety": advisory_safety_stamps(),
        "execution": human_only_stamp(),
    }


# ---------------------------------------------------------------------------
# Stage 2f — artifacts
# ---------------------------------------------------------------------------

def write_model_lane_artifacts(
    lane_result: dict[str, Any],
    runtime_dir: Path,
) -> list[Path]:
    """Write per-model lane outputs (or a SKIPPED marker) under ``runtime_dir``.

    ``runtime_dir`` is the run's ``model_lanes/`` directory. Returns the list of
    written paths.
    """
    runtime_dir = Path(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if lane_result.get("status") != LANES_COMPLETED:
        marker = runtime_dir / "SKIPPED_NO_FRESH_DISCOVERY.json"
        marker.write_text(
            json.dumps(
                {
                    "status": lane_result.get("status", LANES_SKIPPED),
                    "reason": lane_result.get("reason"),
                    "run_date": lane_result.get("run_date"),
                    "model_lane_outputs": [],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return [marker]

    for output in lane_result.get("model_lane_outputs", []):
        model = str(output.get("model") or "unknown").lower()
        path = runtime_dir / f"{model}_output.json"
        path.write_text(json.dumps(output, indent=2), encoding="utf-8")
        written.append(path)
    return written


def load_model_lane_outputs_from_artifacts(path: Path) -> list[dict[str, Any]]:
    """Load previously-written lane outputs from a ``model_lanes/`` directory.

    Returns the list of validated output dicts (empty when the run was skipped
    or the directory is absent). The outputs are returned as stored; callers who
    want to re-validate should pass them through ``validate_model_lane_output``.
    """
    path = Path(path)
    if not path.exists():
        return []
    outputs: list[dict[str, Any]] = []
    for model in MODEL_LANES:
        candidate = path / f"{model}_output.json"
        if not candidate.exists():
            continue
        try:
            outputs.append(json.loads(candidate.read_text(encoding="utf-8-sig")))
        except (json.JSONDecodeError, OSError):
            continue
    return outputs


__all__ = [
    "MODEL_LANES",
    "FRESH_DISCOVERY_OK",
    "LANES_SKIPPED",
    "LANES_COMPLETED",
    "INPUT_PROVENANCE_VIOLATION",
    "UNKNOWN_TICKER_VIOLATION",
    "CONTEXT_CONTAMINATION_VIOLATION",
    "IGNORED_DEFENSE_VIOLATION",
    "IGNORED_P2_DEFENSE_VIOLATION",
    "VALID_CLASSIFICATIONS",
    "ModelLaneInputProvenanceViolation",
    "build_clean_fresh_discovery_payload",
    "candidate_input_allowed",
    "validate_model_lane_input",
    "defense_grade_for",
    "effective_defense_grade",
    "clean_payload_tickers",
    "build_model_lane_prompt",
    "build_all_lane_prompts",
    "validate_model_lane_output",
    "run_isolated_model_lanes",
    "write_model_lane_artifacts",
    "load_model_lane_outputs_from_artifacts",
]
