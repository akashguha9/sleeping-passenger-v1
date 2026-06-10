"""Deterministic offline filing/evidence parser with lineage.

Converts raw filing text excerpts (10-K, 10-Q, annual report, earnings
call, investor presentation, manual excerpt) into structured evidence
items that feed ``FilingSignal`` and the embedded-proof layer.  Pure
keyword matching over lines — no network, no SEC dependency, no model
calls — so every parse is replayable byte-for-byte.

Evidence hardness: each matched item carries a hardness weight from
``EVIDENCE_HARDNESS_WEIGHTS`` (audited revenue segments are hard to
fake; logos are not), scaled by a source-type multiplier (a 10-K
statement outweighs the same sentence on an investor slide).

Proof math:
    proof_density        = weighted_verified_evidence / max(1, narrative_claim_count)
    embedded_proof_score = 100 × min(1, proof_density)
    substrate_score      = 100 × min(1, sum of substrate evidence fractions)
"""

from __future__ import annotations

from src.utils.math_utils import clip

SOURCE_TYPES = (
    "10-K",
    "10-Q",
    "annual_report",
    "earnings_call",
    "investor_presentation",
    "manual_excerpt",
    "manual_stub",
)

# How much a given document type discounts its own claims.  Audited
# filings carry full weight; slide decks and unknown sources are
# discounted hard.
SOURCE_TYPE_MULTIPLIER: dict[str, float] = {
    "10-K": 1.00,
    "10-Q": 0.95,
    "annual_report": 0.90,
    "earnings_call": 0.55,
    "investor_presentation": 0.45,
    "manual_excerpt": 0.60,
    "manual_stub": 0.50,
}
_UNKNOWN_SOURCE_MULTIPLIER = 0.40

# Hardness of the evidence *kind* itself (how hard it is to fake).
EVIDENCE_HARDNESS_WEIGHTS: dict[str, float] = {
    "audited_revenue_segment": 1.00,
    "contract_or_backlog": 0.90,
    "cash_flow_statement": 0.90,
    "regulatory_approval": 0.85,
    "capex_commitment": 0.75,
    "risk_disclosure": 0.70,
    "earnings_call_claim": 0.55,
    "investor_presentation_claim": 0.45,
    "marketing_claim": 0.25,
    "logo_or_collaboration_claim": 0.15,
}

# category -> (hardness key, deterministic lowercase keyword cues).
# A line matches a category when it contains any cue.
_POSITIVE_CATEGORY_RULES: dict[str, tuple[str, tuple[str, ...]]] = {
    "revenue_segment": (
        "audited_revenue_segment",
        ("segment revenue", "revenue by segment", "segment results",
         "reportable segment", "segment information"),
    ),
    "customer_contract": (
        "contract_or_backlog",
        ("signed a contract", "entered into a contract", "enter into a contract",
         "master agreement", "supply agreement", "long-term contract",
         "customer contract"),
    ),
    "order_backlog": (
        "contract_or_backlog",
        ("order backlog", "backlog of", "remaining performance obligations",
         "unfilled orders"),
    ),
    "capex_commitment": (
        "capex_commitment",
        ("capital expenditure", "capex", "capital spending",
         "purchase commitments for property"),
    ),
    "regulatory_approval": (
        "regulatory_approval",
        ("regulatory approval", "approved by the", "received clearance",
         "granted approval", "certification received"),
    ),
    "product_launch": (
        "earnings_call_claim",
        ("launched", "product launch", "commercially available",
         "began shipping", "general availability"),
    ),
    "geographic_expansion": (
        "earnings_call_claim",
        ("expanded into", "geographic expansion", "new markets in",
         "entered the", "international expansion"),
    ),
    "margin_improvement": (
        "cash_flow_statement",
        ("gross margin improved", "margin expansion", "operating margin increased",
         "margin improved"),
    ),
    "free_cash_flow": (
        "cash_flow_statement",
        ("free cash flow", "cash provided by operating activities",
         "operating cash flow"),
    ),
    "debt_reduction": (
        "cash_flow_statement",
        ("repaid", "debt reduction", "reduced our outstanding",
         "deleveraging", "retired debt"),
    ),
    "partnership": (
        "logo_or_collaboration_claim",
        ("partnership with", "collaboration with", "strategic alliance",
         "teamed up with", "co-branded"),
    ),
    "patent_or_ip": (
        "investor_presentation_claim",
        ("patent", "intellectual property", "trade secrets", "proprietary technology"),
    ),
}

# Risk categories: matched separately, scored into
# filing_risk_disclosure_score rather than proof.
_RISK_CATEGORY_RULES: dict[str, tuple[float, tuple[str, ...]]] = {
    "risk_disclosure": (
        0.50,
        ("risk factors", "could adversely affect", "may adversely affect",
         "subject to risks", "no assurance"),
    ),
    "customer_concentration": (
        0.75,
        ("customer concentration", "largest customer", "top customer",
         "significant portion of our revenue", "concentration of credit risk"),
    ),
    "supplier_dependency": (
        0.70,
        ("single source", "sole supplier", "depend on a limited number of suppliers",
         "supplier dependency", "limited number of suppliers"),
    ),
    "litigation_or_regulatory_risk": (
        0.80,
        ("litigation", "lawsuit", "regulatory investigation", "subpoena",
         "enforcement action", "class action"),
    ),
    "going_concern_or_liquidity_risk": (
        1.00,
        ("going concern", "substantial doubt", "liquidity risk",
         "may not have sufficient", "insufficient cash"),
    ),
}

# Substrate evidence: fractions summed and capped at 1.0 — a company is
# substrate when the theme is its revenue, operations, and capital base.
_SUBSTRATE_CONTRIBUTIONS: dict[str, float] = {
    "revenue_segment": 0.35,        # segment_revenue_evidence
    "free_cash_flow": 0.25,         # recurring_revenue_evidence
    "customer_contract": 0.20,      # operating_dependency_evidence
    "order_backlog": 0.20,          # operating_dependency_evidence
    "capex_commitment": 0.20,       # capex_or_infrastructure_dependency
}

EVIDENCE_CATEGORIES = tuple(_POSITIVE_CATEGORY_RULES) + tuple(_RISK_CATEGORY_RULES)

# Marketing-flavoured cue words: lines matching ONLY these are claims,
# not evidence.
_CLAIM_CUES = (
    "world-class", "market-leading", "revolutionary", "best-in-class",
    "leading provider", "cutting-edge", "transformative", "industry leader",
)

# Negation/risk guard: deterministic token-window checks so "we do not
# generate revenue from AI" never counts as AI revenue proof and "no
# material customer concentration" reduces rather than raises risk.
_NEGATION_TOKENS = frozenset(
    {"not", "no", "never", "without", "neither", "nor", "none"}
)
_MODAL_TOKENS = frozenset({"may", "could", "might", "would", "if"})
_NEGATION_WINDOW_TOKENS = 8


def _window_before(lowered_line: str, cue: str) -> list[str]:
    """Tokens (max window size) immediately preceding the cue match."""
    index = lowered_line.find(cue)
    if index < 0:
        return []
    prefix = lowered_line[:index]
    # Strip punctuation so "No," still reads as a negation token.
    tokens = [token.strip(".,;:()\"'") for token in prefix.split()]
    return tokens[-_NEGATION_WINDOW_TOKENS:]


def _is_negated(lowered_line: str, cue: str) -> bool:
    return any(token in _NEGATION_TOKENS for token in _window_before(lowered_line, cue))


def _is_modal(lowered_line: str, cue: str) -> bool:
    return any(token in _MODAL_TOKENS for token in _window_before(lowered_line, cue))


def _evidence_item(
    *,
    category: str,
    claim: str,
    evidence_text: str,
    source_type: str,
    hardness_weight: float,
    confidence: float,
    line_number: int | None,
    source_date: str | None,
) -> dict[str, object]:
    return {
        "category": category,
        "claim": claim,
        "evidence_text": evidence_text,
        "source_type": source_type,
        "hardness_weight": round(hardness_weight, 4),
        "confidence": clip(confidence, 0.0, 100.0),
        "line_number": line_number,
        "source_date": source_date,
    }


def parse_filing_text(
    text: str,
    *,
    source_type: str = "manual_excerpt",
    narrative_claims: list[str] | None = None,
    source_date: str | None = None,
) -> dict[str, object]:
    """Parse a filing excerpt into evidence with lineage, deterministically.

    ``narrative_claims`` are the theme claims under test (e.g. "AI revenue
    growth"); if omitted, marketing-cue lines found in the text are
    counted as claims so proof density still has a denominator.
    """
    missing_inputs: list[str] = []
    source = source_type if source_type in SOURCE_TYPES else source_type
    multiplier = SOURCE_TYPE_MULTIPLIER.get(source_type)
    if multiplier is None:
        multiplier = _UNKNOWN_SOURCE_MULTIPLIER
        missing_inputs.append(f"unknown source_type '{source_type}'")

    lines = (text or "").splitlines()
    if not (text or "").strip():
        missing_inputs.append("filing_text")

    evidence: list[dict[str, object]] = []
    risks: list[dict[str, object]] = []
    marketing_claims: list[str] = []
    negated_statements: list[dict[str, object]] = []
    forward_looking_claims: list[str] = []
    risk_mitigations: list[dict[str, object]] = []

    for index, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        matched_positive = False
        for category, (hardness_key, cues) in _POSITIVE_CATEGORY_RULES.items():
            matched_cue = next((cue for cue in cues if cue in lowered), None)
            if matched_cue is None:
                continue
            if _is_negated(lowered, matched_cue):
                # "we do not generate revenue from AI" is the opposite of
                # proof — record it so the auditor sees what was rejected.
                negated_statements.append(
                    {"category": category, "line_number": index, "text": line}
                )
                continue
            if _is_modal(lowered, matched_cue):
                # "we may enter into a contract" is forward-looking talk,
                # not evidence; count it on the claim side of density.
                forward_looking_claims.append(line)
                continue
            hardness = EVIDENCE_HARDNESS_WEIGHTS[hardness_key] * multiplier
            evidence.append(
                _evidence_item(
                    category=category,
                    claim=category.replace("_", " "),
                    evidence_text=line,
                    source_type=source,
                    hardness_weight=hardness,
                    confidence=100.0 * hardness,
                    line_number=index,
                    source_date=source_date,
                )
            )
            matched_positive = True
        for category, (severity, cues) in _RISK_CATEGORY_RULES.items():
            matched_cue = next((cue for cue in cues if cue in lowered), None)
            if matched_cue is None:
                continue
            if _is_negated(lowered, matched_cue):
                # "no material customer concentration" mitigates risk
                # rather than raising it.
                risk_mitigations.append(
                    {"category": category, "line_number": index, "text": line}
                )
                continue
            risks.append(
                _evidence_item(
                    category=category,
                    claim=category.replace("_", " "),
                    evidence_text=line,
                    source_type=source,
                    hardness_weight=EVIDENCE_HARDNESS_WEIGHTS["risk_disclosure"]
                    * multiplier,
                    confidence=100.0 * severity,
                    line_number=index,
                    source_date=source_date,
                )
            )
        if not matched_positive and any(cue in lowered for cue in _CLAIM_CUES):
            marketing_claims.append(line)

    claims = list(narrative_claims or [])
    if not claims:
        claims = marketing_claims + forward_looking_claims
        if not claims and evidence:
            # Evidence with no claim under test: density measured against
            # one implicit claim so the score stays defined and bounded.
            missing_inputs.append("narrative_claims")

    weighted_evidence = sum(float(item["hardness_weight"]) for item in evidence)
    claim_count = max(1, len(claims))
    proof_density = weighted_evidence / claim_count
    embedded_proof_score = clip(100.0 * min(1.0, proof_density), 0.0, 100.0)

    substrate_fraction = 0.0
    seen_substrate: set[str] = set()
    for item in evidence:
        category = str(item["category"])
        if category in _SUBSTRATE_CONTRIBUTIONS and category not in seen_substrate:
            seen_substrate.add(category)
            substrate_fraction += _SUBSTRATE_CONTRIBUTIONS[category] * multiplier
    substrate_score = clip(100.0 * min(1.0, substrate_fraction), 0.0, 100.0)

    # Risk disclosures: severity-weighted, two max-severity findings
    # saturate; each explicit "no material ..." mitigation offsets a
    # quarter-point of risk load (floor 0).
    risk_load = sum(float(item["confidence"]) / 100.0 for item in risks)
    risk_load = max(0.0, risk_load - 0.25 * len(risk_mitigations))
    filing_risk_disclosure_score = clip(100.0 * min(1.0, risk_load / 2.0), 0.0, 100.0)

    if not evidence and not claims:
        classification = "insufficient_evidence"
    elif substrate_score >= 60.0:
        classification = "substrate"
    elif not evidence or embedded_proof_score < 25.0:
        classification = "simulated"
    else:
        classification = "embedded"

    return {
        "source_type": source,
        "line_count": len(lines),
        "narrative_claims": claims,
        "evidence": evidence,
        "risk_disclosures": risks,
        "marketing_claims": marketing_claims,
        "forward_looking_claims": forward_looking_claims,
        "negated_statements": negated_statements,
        "risk_mitigations": risk_mitigations,
        "proof_density": proof_density,
        "embedded_proof_score": embedded_proof_score,
        "substrate_score": substrate_score,
        "filing_risk_disclosure_score": filing_risk_disclosure_score,
        "classification": classification,
        "missing_inputs": missing_inputs,
        "explanation": [
            f"{len(evidence)} evidence item(s), {len(risks)} risk disclosure(s), "
            f"{len(marketing_claims)} marketing claim(s) across {len(lines)} line(s).",
            f"Weighted evidence {weighted_evidence:.2f} over {claim_count} "
            f"claim(s): proof density {proof_density:.2f} -> embedded proof "
            f"{embedded_proof_score:.1f}/100.",
            f"Substrate {substrate_score:.1f}/100; risk disclosure "
            f"{filing_risk_disclosure_score:.1f}/100; classification: {classification}.",
            f"Source '{source}' multiplier {multiplier:.2f} applied to all hardness weights.",
        ],
    }


def to_filing_signal(
    parsed: dict[str, object],
    *,
    company: str,
    ticker: str,
    source_date: str = "",
    filing_type: str | None = None,
) -> "FilingSignal":
    """Build a ``FilingSignal`` from a ``parse_filing_text`` result."""
    from src.alpha.signals import FilingSignal

    confidence = clip(
        0.6 * float(parsed["embedded_proof_score"])
        + 0.4 * float(parsed["substrate_score"]),
        0.0,
        100.0,
    )
    return FilingSignal(
        company=company,
        ticker=ticker,
        filing_type=filing_type or str(parsed["source_type"]),
        claims=[str(c) for c in parsed["narrative_claims"]],
        verified_evidence=[
            f"{item['category']} (line {item['line_number']}): {item['evidence_text']}"
            for item in parsed["evidence"]
        ],
        embedded_proof_score=float(parsed["embedded_proof_score"]),
        source_date=source_date,
        confidence=confidence,
    )
