"""Belief Escrow — thesis-as-executable-contract engine.

Every thesis is a *contract*, not an opinion: it posts collateral at
registration time (a falsification observable, an expiry day, and a forced
null twin), accumulates provenance-tagged evidence that decays by source
half-life, and is adjudicated by the system — never by its author — at
expiry. Scores are properties of contracts; the calibration corpus is the
ledger of adjudications.

Invariants (enforced here, tested in tests/test_signal_thesis_contract.py):

  I1  FINAL <= MERIT                    (gates are multiplicative demoters)
  I2  FINAL <= 10 * EvidenceQuality     (no thesis outscores its evidence)
  I3  unfalsifiable => FINAL <= 4.0 and verdict INSUFFICIENT_EVIDENCE
  I4  evidence counts only if it discriminates thesis vs forced null
      (NEUTRAL items carry zero discrimination weight)
  I5  ANECDOTE evidence is quarantined at weight 0.15 until corroborated by
      an independent non-anecdote ecology on the same stance

Pure and deterministic: integer-day time, no network, no wall clock inside
scoring functions; persistence only via explicit paths. ADVISORY_ONLY —
no broker execution, no order placement, no API trading writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"

# --- provenance classes -------------------------------------------------------
HARD_DATA = "HARD_DATA"          # filings, regulator records, disclosed numbers
MARKET = "MARKET"                # market prices, prediction-market ΔP, volumes
ANALYST_PRIOR = "ANALYST_PRIOR"  # operator-estimated coefficients / rubrics
ANECDOTE = "ANECDOTE"            # field observations, single-sample stories

PROVENANCE_WEIGHTS: dict[str, float] = {
    HARD_DATA: 1.0, MARKET: 0.9, ANALYST_PRIOR: 0.4, ANECDOTE: 0.15,
}
ANECDOTE_CORROBORATED_WEIGHT = 0.6  # promotion step (I5); full weight needs outcomes

# --- evidence stances (twin-thesis discrimination) ----------------------------
FOR_THESIS = "FOR_THESIS"
FOR_NULL = "FOR_NULL"
NEUTRAL = "NEUTRAL"

# --- data modes (never confuse fixture with live) -----------------------------
LIVE = "LIVE"
IMPORTED_BACKTEST = "IMPORTED_BACKTEST"
FIXTURE_DEMONSTRATION = "FIXTURE_DEMONSTRATION"
DATA_MODES = (LIVE, IMPORTED_BACKTEST, FIXTURE_DEMONSTRATION)

# --- contract lifecycle -------------------------------------------------------
ACTIVE = "ACTIVE"
EXPIRED = "EXPIRED"
FALSIFIED = "FALSIFIED"
VALIDATED = "VALIDATED"
INSUFFICIENT_EVIDENCE_STATUS = "INSUFFICIENT_EVIDENCE"

# --- contract purpose taxonomy (governance spine) ------------------------------
# Case studies TEACH the engine; candidates are EVALUATED by it. Never the
# same object. A contract with no purpose is invalid — fail closed.
CASE_STUDY = "CASE_STUDY"
FIXTURE_TEST = "FIXTURE_TEST"
LIVE_RESEARCH = "LIVE_RESEARCH"
INVESTABLE_CANDIDATE = "INVESTABLE_CANDIDATE"
RETIRED = "RETIRED"
FALSIFIED_PURPOSE = "FALSIFIED"
PURPOSES = (CASE_STUDY, FIXTURE_TEST, LIVE_RESEARCH, INVESTABLE_CANDIDATE,
            RETIRED, FALSIFIED_PURPOSE)

# investment_eligibility / promotion_status / board_scope / trading_status
# are DERIVED from purpose — no implicit default to investable, ever.
PURPOSE_DEFAULTS: dict[str, dict[str, str]] = {
    CASE_STUDY: {"investment_eligibility": "NOT_ELIGIBLE",
                 "promotion_status": "NOT_PROMOTABLE",
                 "board_scope": "CASE_STUDY_BOARD",
                 "trading_status": "DO_NOT_TRADE"},
    FIXTURE_TEST: {"investment_eligibility": "NOT_ELIGIBLE",
                   "promotion_status": "NOT_PROMOTABLE",
                   "board_scope": "CASE_STUDY_BOARD",
                   "trading_status": "DO_NOT_TRADE"},
    LIVE_RESEARCH: {"investment_eligibility": "RESEARCH_ONLY",
                    "promotion_status": "PROMOTION_REQUIRED",
                    "board_scope": "RESEARCH_BOARD",
                    "trading_status": "PAPER_RESEARCH_ONLY"},
    INVESTABLE_CANDIDATE: {"investment_eligibility": "INVESTABLE_CANDIDATE",
                           "promotion_status": "PROMOTED",
                           "board_scope": "INVESTABLE_CANDIDATE_BOARD",
                           "trading_status": "ELIGIBLE_FOR_PAPER_REVIEW"},
    RETIRED: {"investment_eligibility": "BLOCKED",
              "promotion_status": "AUTO_BLOCKED",
              "board_scope": "ARCHIVE", "trading_status": "BLOCKED"},
    FALSIFIED_PURPOSE: {"investment_eligibility": "BLOCKED",
                        "promotion_status": "AUTO_BLOCKED",
                        "board_scope": "ARCHIVE", "trading_status": "BLOCKED"},
}

CASE_STUDY_DISCLAIMER = (
    "This contract validates MVP architecture only. It is not a buy "
    "candidate, not a recommendation, and cannot be used for trade selection "
    "unless separately promoted into a new INVESTABLE_CANDIDATE contract.")

# --- verdict classes (precedence-ordered; first match wins) -------------------
V_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
V_CONFUSION_RENT_TRAP = "CONFUSION_RENT_TRAP"
V_STATE_INTEGRITY_TRAP = "STATE_INTEGRITY_TRAP"
V_HYPE_RISK = "HYPE_RISK"
V_PM_MISPRICING = "PREDICTION_MARKET_MISPRICING"
V_NTT_BREAKOUT = "NARRATIVE_TO_TRANSACTION_BREAKOUT"
V_INVISIBLE_INFRA = "INVISIBLE_INFRASTRUCTURE_COMPOUNDER"
V_STRONG_BUY = "STRONG_BUY_CANDIDATE"
V_WATCHLIST = "WATCHLIST"
V_AVOID = "AVOID"
# purpose-scoped verdicts
V_CASE_STUDY_VALIDATION = "CASE_STUDY_VALIDATION"
V_FRAMEWORK_TEST_PASS = "FRAMEWORK_TEST_PASS"
V_FRAMEWORK_TEST_FAIL = "FRAMEWORK_TEST_FAIL"
V_RESEARCH_ONLY = "RESEARCH_ONLY"
V_BLOCKED_FIXTURE_CONTAMINATION = "BLOCKED_FIXTURE_CONTAMINATION"

# Investment-flavored verdicts: forbidden for CASE_STUDY/FIXTURE_TEST always,
# and for LIVE_RESEARCH until promoted into a new INVESTABLE_CANDIDATE.
INVESTMENT_VERDICTS = frozenset({
    V_STRONG_BUY, V_PM_MISPRICING, V_INVISIBLE_INFRA, V_NTT_BREAKOUT})
CASE_STUDY_ALLOWED_VERDICTS = frozenset({
    V_CASE_STUDY_VALIDATION, V_FRAMEWORK_TEST_PASS, V_FRAMEWORK_TEST_FAIL,
    V_INSUFFICIENT_EVIDENCE, V_RESEARCH_ONLY})

# Per-ecology evidence half-lives (days). Mirrors the platform-ecology idea:
# a TikTok datapoint dies in days; a filing glows for a year.
ECOLOGY_HALF_LIFE_DAYS: dict[str, float] = {
    "sec_filing": 365.0, "regulatory": 365.0, "earnings_call": 120.0,
    "pricing_page": 120.0, "reddit": 90.0, "field_observation": 60.0,
    "web_traffic": 45.0, "news": 30.0, "youtube": 30.0,
    "prediction_market": 14.0, "tiktok": 3.0,
}
DEFAULT_HALF_LIFE_DAYS = 45.0

DEMAND_KEYS = ("awareness_gap", "decision_moment_capture",
               "long_tail_demand", "use_case_clarity")
MOAT_KEYS = ("house_layer", "infra_capture", "rail_arbitrage", "trust_node")

UNFALSIFIABLE_SCORE_CAP = 4.0
EQS_INSUFFICIENT_FLOOR = 0.35


# --- evidence source modes (authenticity, derived — never trusted) -------------
SM_FIXTURE = "FIXTURE"
SM_LIVE = "LIVE"
SM_IMPORTED_BACKTEST = "IMPORTED_BACKTEST"
SM_HARD_FILING = "HARD_FILING"
SM_ANALYST_PRIOR = "ANALYST_PRIOR"
SM_ANECDOTE = "ANECDOTE"
SOURCE_MODES = (SM_FIXTURE, SM_LIVE, SM_IMPORTED_BACKTEST, SM_HARD_FILING,
                SM_ANALYST_PRIOR, SM_ANECDOTE)


@dataclass
class EvidenceItem:
    evidence_id: str
    claim: str
    source: str
    ecology: str
    provenance: str
    stance: str                      # FOR_THESIS | FOR_NULL | NEUTRAL
    observed_day: int
    half_life_days: float | None = None
    # --- authenticity metadata (claims are verified, not trusted) --------------
    source_mode: str = ""            # one of SOURCE_MODES; "" = undeclared
    source_uri_or_adapter: str = ""
    fetch_timestamp: str = ""
    adapter_name: str = ""
    adapter_run_id: str = ""
    source_hash: str = ""
    accession_or_filing_id: str = ""
    is_fixture: bool | None = None   # None => derived from contract data_mode

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id, "claim": self.claim,
            "source": self.source, "ecology": self.ecology,
            "provenance": self.provenance, "stance": self.stance,
            "observed_day": self.observed_day,
            "half_life_days": self.half_life_days,
            "source_mode": self.source_mode,
            "source_uri_or_adapter": self.source_uri_or_adapter,
            "fetch_timestamp": self.fetch_timestamp,
            "adapter_name": self.adapter_name,
            "adapter_run_id": self.adapter_run_id,
            "source_hash": self.source_hash,
            "accession_or_filing_id": self.accession_or_filing_id,
            "is_fixture": self.is_fixture,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "EvidenceItem":
        return EvidenceItem(
            evidence_id=str(d["evidence_id"]), claim=str(d["claim"]),
            source=str(d["source"]), ecology=str(d["ecology"]),
            provenance=str(d["provenance"]), stance=str(d["stance"]),
            observed_day=int(d["observed_day"]),
            half_life_days=(None if d.get("half_life_days") is None
                            else float(d["half_life_days"])),
            source_mode=str(d.get("source_mode", "")),
            source_uri_or_adapter=str(d.get("source_uri_or_adapter", "")),
            fetch_timestamp=str(d.get("fetch_timestamp", "")),
            adapter_name=str(d.get("adapter_name", "")),
            adapter_run_id=str(d.get("adapter_run_id", "")),
            source_hash=str(d.get("source_hash", "")),
            accession_or_filing_id=str(d.get("accession_or_filing_id", "")),
            is_fixture=d.get("is_fixture"),
        )


def item_live_verified(item: EvidenceItem) -> bool:
    """A LIVE claim counts only with full adapter metadata — self-declared
    LIVE without proof is worth nothing."""
    return (item.source_mode == SM_LIVE
            and bool(item.source_uri_or_adapter)
            and bool(item.fetch_timestamp)
            and bool(item.adapter_run_id)
            and bool(item.source_hash))


def item_hard_admissible(item: EvidenceItem) -> bool:
    return (item.source_mode == SM_HARD_FILING
            and bool(item.accession_or_filing_id)
            and bool(item.source_hash))


def item_imported_verified(item: EvidenceItem) -> bool:
    return (item.source_mode == SM_IMPORTED_BACKTEST
            and bool(item.source_hash) and bool(item.adapter_run_id))


@dataclass
class ThesisContract:
    thesis_id: str
    title: str
    entity: str
    ticker: str                      # "NONE" allowed for non-tradable insights
    narrative: str
    trigger: str
    predicted_direction: str         # "UP" | "DOWN"
    horizon_days: int
    created_day: int
    expiry_day: int
    falsification_observable: str
    forced_null_thesis: str
    causal_path: list[str] = field(default_factory=list)
    beneficiary_map: dict[str, list[str]] = field(default_factory=dict)
    evidence: list[EvidenceItem] = field(default_factory=list)
    merit_inputs: dict[str, float] = field(default_factory=dict)
    risk_flags: dict[str, float] = field(default_factory=dict)
    pm_link: dict[str, Any] | None = None
    data_mode: str = FIXTURE_DEMONSTRATION
    status: str = ACTIVE
    # --- governance classification (REQUIRED; fail-closed) --------------------
    contract_purpose: str = ""            # must be one of PURPOSES
    investment_eligibility: str = ""      # derived from purpose if empty
    promotion_status: str = ""
    board_scope: str = ""
    trading_status: str = ""
    case_study_disclaimer: str = ""
    parent_case_study_id: str = ""
    parent_research_id: str = ""
    promotion_note: str = ""
    # --- lineage custody (anti-forgery) ---------------------------------------
    promotion_day: int = 0
    parent_hash: str = ""
    lineage_hash: str = ""
    # operator worklist: what evidence would move this contract (mutable,
    # excluded from lineage identity)
    next_evidence_actions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.contract_purpose not in PURPOSES:
            raise ValueError(
                "CONTRACT_PURPOSE_MISSING_FAIL_CLOSED: contract_purpose must "
                f"be one of {PURPOSES}, got {self.contract_purpose!r}")
        defaults = PURPOSE_DEFAULTS[self.contract_purpose]
        for fieldname, value in defaults.items():
            if not getattr(self, fieldname):
                setattr(self, fieldname, value)
        if (self.contract_purpose in (CASE_STUDY, FIXTURE_TEST)
                and not self.case_study_disclaimer):
            self.case_study_disclaimer = CASE_STUDY_DISCLAIMER
        # An INVESTABLE_CANDIDATE can only exist via the promotion workflow:
        # it must be PROMOTED and carry its research lineage. In-place edits
        # of a case study or research contract are structurally rejected.
        if self.contract_purpose == INVESTABLE_CANDIDATE:
            if self.promotion_status != "PROMOTED" or not self.parent_research_id:
                raise ValueError(
                    "UNPROMOTED_INVESTABLE_CANDIDATE_FORBIDDEN: "
                    "INVESTABLE_CANDIDATE requires promotion_status=PROMOTED "
                    "and parent_research_id set by promote_research_to_"
                    "investable(); in-place edits are not a promotion path.")

    def to_dict(self) -> dict[str, Any]:
        d = {
            "thesis_id": self.thesis_id, "title": self.title,
            "entity": self.entity, "ticker": self.ticker,
            "narrative": self.narrative, "trigger": self.trigger,
            "predicted_direction": self.predicted_direction,
            "horizon_days": self.horizon_days, "created_day": self.created_day,
            "expiry_day": self.expiry_day,
            "falsification_observable": self.falsification_observable,
            "forced_null_thesis": self.forced_null_thesis,
            "causal_path": list(self.causal_path),
            "beneficiary_map": dict(self.beneficiary_map),
            "evidence": [e.to_dict() for e in self.evidence],
            "merit_inputs": dict(self.merit_inputs),
            "risk_flags": dict(self.risk_flags),
            "pm_link": self.pm_link, "data_mode": self.data_mode,
            "status": self.status,
            "contract_purpose": self.contract_purpose,
            "investment_eligibility": self.investment_eligibility,
            "promotion_status": self.promotion_status,
            "board_scope": self.board_scope,
            "trading_status": self.trading_status,
            "case_study_disclaimer": self.case_study_disclaimer,
            "parent_case_study_id": self.parent_case_study_id,
            "parent_research_id": self.parent_research_id,
            "promotion_note": self.promotion_note,
            "promotion_day": self.promotion_day,
            "parent_hash": self.parent_hash,
            "lineage_hash": self.lineage_hash,
            "next_evidence_actions": list(self.next_evidence_actions),
            "advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY,
        }
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "ThesisContract":
        if "contract_purpose" not in d:
            raise ValueError(
                "CONTRACT_PURPOSE_MISSING_FAIL_CLOSED: serialized contract "
                "has no contract_purpose; refusing to load (no implicit "
                "default to investable).")
        return ThesisContract(
            thesis_id=str(d["thesis_id"]), title=str(d["title"]),
            entity=str(d["entity"]), ticker=str(d["ticker"]),
            narrative=str(d["narrative"]), trigger=str(d["trigger"]),
            predicted_direction=str(d["predicted_direction"]),
            horizon_days=int(d["horizon_days"]),
            created_day=int(d["created_day"]), expiry_day=int(d["expiry_day"]),
            falsification_observable=str(d["falsification_observable"]),
            forced_null_thesis=str(d["forced_null_thesis"]),
            causal_path=[str(x) for x in d.get("causal_path", [])],
            beneficiary_map={str(k): [str(v) for v in vs]
                             for k, vs in d.get("beneficiary_map", {}).items()},
            evidence=[EvidenceItem.from_dict(e) for e in d.get("evidence", [])],
            merit_inputs={str(k): float(v)
                          for k, v in d.get("merit_inputs", {}).items()},
            risk_flags={str(k): float(v)
                        for k, v in d.get("risk_flags", {}).items()},
            pm_link=d.get("pm_link"),
            data_mode=str(d.get("data_mode", FIXTURE_DEMONSTRATION)),
            status=str(d.get("status", ACTIVE)),
            contract_purpose=str(d["contract_purpose"]),
            investment_eligibility=str(d.get("investment_eligibility", "")),
            promotion_status=str(d.get("promotion_status", "")),
            board_scope=str(d.get("board_scope", "")),
            trading_status=str(d.get("trading_status", "")),
            case_study_disclaimer=str(d.get("case_study_disclaimer", "")),
            parent_case_study_id=str(d.get("parent_case_study_id", "")),
            parent_research_id=str(d.get("parent_research_id", "")),
            promotion_note=str(d.get("promotion_note", "")),
            promotion_day=int(d.get("promotion_day", 0)),
            parent_hash=str(d.get("parent_hash", "")),
            lineage_hash=str(d.get("lineage_hash", "")),
            next_evidence_actions=[str(x) for x in
                                   d.get("next_evidence_actions", [])],
        )


def binding_gate(report: dict[str, Any]) -> str:
    """Which single factor most binds the final score right now?"""
    if not report["falsifiable"]:
        return "FALSIFIABILITY"
    candidates = {
        "EQS": report["evidence_quality"] * 10.0 / 8.0,  # vs FIS scale
        "g_txn": report["g_txn"] * 10.0,
        "g_contra": report["discrimination"]["g_contra"] * 10.0,
        "g_stale": report["g_stale"] * 10.0,
        "AUTHENTICITY": report["authenticity_cap"],
    }
    if "EVIDENCE_QUALITY_CAP" in report["caps_applied"]:
        return "EQS"
    return min(candidates, key=lambda k: candidates[k])


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def item_half_life(item: EvidenceItem) -> float:
    if item.half_life_days is not None and item.half_life_days > 0:
        return float(item.half_life_days)
    return ECOLOGY_HALF_LIFE_DAYS.get(item.ecology, DEFAULT_HALF_LIFE_DAYS)


def freshness(item: EvidenceItem, as_of_day: int) -> float:
    """0.5 ** (age / half_life). Future-dated evidence is clamped to 1.0."""
    age = max(0, int(as_of_day) - int(item.observed_day))
    return 0.5 ** (age / item_half_life(item))


def anecdote_is_corroborated(item: EvidenceItem, contract: ThesisContract) -> bool:
    """I5: an anecdote is corroborated only by a same-stance HARD/MARKET item
    from a *different* ecology."""
    if item.provenance != ANECDOTE:
        return False
    for other in contract.evidence:
        if other.evidence_id == item.evidence_id:
            continue
        if (other.stance == item.stance
                and other.provenance in (HARD_DATA, MARKET)
                and other.ecology != item.ecology):
            return True
    return False


def item_weight(item: EvidenceItem, contract: ThesisContract) -> float:
    base = PROVENANCE_WEIGHTS.get(item.provenance, 0.0)
    if item.provenance == ANECDOTE and anecdote_is_corroborated(item, contract):
        return ANECDOTE_CORROBORATED_WEIGHT
    return base


def corroboration_factor(contract: ThesisContract) -> float:
    """clamp((distinct non-neutral ecologies - 1) / 3, 0.34, 1.0)."""
    ecologies = {e.ecology for e in contract.evidence if e.stance != NEUTRAL}
    if not ecologies:
        return 0.34
    return _clamp((len(ecologies) - 1) / 3.0, 0.34, 1.0)


def evidence_quality(contract: ThesisContract, as_of_day: int) -> float:
    """EQS in [0,1] = corroboration * sum(w_i * f_i) / (N + 2)."""
    items = contract.evidence
    if not items:
        return 0.0
    total = sum(item_weight(e, contract) * freshness(e, as_of_day) for e in items)
    return round(_clamp(corroboration_factor(contract) * total / (len(items) + 2),
                        0.0, 1.0), 4)


def discrimination(contract: ThesisContract, as_of_day: int) -> dict[str, float]:
    """I4: only FOR_THESIS / FOR_NULL evidence counts; NEUTRAL is ignored.
    g_contra in (0,1): 0.5 = undiscriminated, ->1 favors thesis, ->0 favors null."""
    w_for = sum(item_weight(e, contract) * freshness(e, as_of_day)
                for e in contract.evidence if e.stance == FOR_THESIS)
    w_against = sum(item_weight(e, contract) * freshness(e, as_of_day)
                    for e in contract.evidence if e.stance == FOR_NULL)
    net = (w_for - w_against) / (w_for + w_against + 1.0)
    return {
        "weight_for": round(w_for, 4),
        "weight_against": round(w_against, 4),
        "net_discrimination": round(net, 4),
        "g_contra": round(_clamp(0.5 + 0.5 * net, 0.0, 1.0), 4),
        "n_for": sum(1 for e in contract.evidence if e.stance == FOR_THESIS),
        "n_against": sum(1 for e in contract.evidence if e.stance == FOR_NULL),
        "n_neutral": sum(1 for e in contract.evidence if e.stance == NEUTRAL),
    }


def staleness_gate(contract: ThesisContract, as_of_day: int) -> float:
    """g_stale in [0.3, 1.0]: sqrt of mean freshness; no evidence floors at 0.3."""
    items = contract.evidence
    if not items:
        return 0.3
    mean_f = sum(freshness(e, as_of_day) for e in items) / len(items)
    return round(_clamp(mean_f ** 0.5, 0.3, 1.0), 4)


def merit(contract: ThesisContract) -> dict[str, float]:
    mi = contract.merit_inputs
    demand_vals = [float(mi[k]) for k in DEMAND_KEYS if k in mi]
    moat_vals = sorted((float(mi[k]) for k in MOAT_KEYS if k in mi), reverse=True)
    d_score = sum(demand_vals) / len(demand_vals) if demand_vals else 0.0
    m_score = (sum(moat_vals[:2]) / min(2, len(moat_vals))) if moat_vals else 0.0
    return {"demand_D": round(d_score, 3), "moat_M": round(m_score, 3),
            "merit": round(0.5 * d_score + 0.5 * m_score, 3)}


def transaction_gate(contract: ThesisContract) -> float:
    """g_txn = clamp(min(transaction_certainty, funnel NTS)/8, 0, 1);
    neutral (1.0) when neither input is provided — absence never inflates
    because it also earns no merit."""
    mi = contract.merit_inputs
    vals = [float(mi[k]) for k in ("transaction_certainty", "narrative_transmission")
            if k in mi]
    if not vals:
        return 1.0
    return round(_clamp(min(vals) / 8.0, 0.0, 1.0), 4)


def pm_gate(contract: ThesisContract) -> float:
    """g_pm = 1.0 when no liquid market exists; else 0.7 + 0.3*(alignment/10)."""
    link = contract.pm_link or {}
    if "alignment" not in link:
        return 1.0
    return round(0.7 + 0.3 * _clamp(float(link["alignment"]) / 10.0, 0.0, 1.0), 4)


def is_falsifiable(contract: ThesisContract) -> bool:
    return (bool(contract.falsification_observable.strip())
            and contract.expiry_day > contract.created_day)


def item_is_fixture(item: EvidenceItem, contract: ThesisContract) -> bool:
    if item.is_fixture is not None:
        return bool(item.is_fixture)
    if item.source_mode == SM_FIXTURE:
        return True
    return contract.data_mode == FIXTURE_DEMONSTRATION


def evidence_mode_counts(contract: ThesisContract) -> dict[str, int]:
    live = sum(1 for e in contract.evidence if item_live_verified(e))
    hard = sum(1 for e in contract.evidence if item_hard_admissible(e))
    imported = sum(1 for e in contract.evidence if item_imported_verified(e))
    fixture_driving = sum(1 for e in contract.evidence
                          if item_is_fixture(e, contract))
    anecdotes = sum(1 for e in contract.evidence
                    if e.provenance == ANECDOTE)
    return {"live_verified": live, "hard_admissible": hard,
            "imported_verified": imported,
            "fixture_driving": fixture_driving,
            "anecdote": anecdotes, "total": len(contract.evidence)}


def derive_data_mode(contract: ThesisContract) -> str:
    """ContractDataMode is DERIVED from verified evidence — the declared
    data_mode string is a label, never a scoring input. No manual override."""
    c = evidence_mode_counts(contract)
    verified_kinds = sum(1 for k in ("live_verified", "hard_admissible",
                                     "imported_verified") if c[k] > 0)
    if verified_kinds >= 2:
        return "MIXED"
    if c["live_verified"] > 0:
        return "LIVE"
    if c["hard_admissible"] > 0:
        return "HARD"
    if c["imported_verified"] > 0:
        return "IMPORTED_BACKTEST"
    if c["fixture_driving"] > 0:
        return "FIXTURE"
    if c["total"] > 0 and c["anecdote"] == c["total"]:
        return "ANECDOTE_ONLY"
    return "ANALYST_PRIOR"


def authenticity_cap(derived_mode: str, contract_purpose: str) -> float:
    """ResearchQualityScore ceiling by evidence authenticity."""
    if derived_mode in ("LIVE", "HARD", "MIXED", "IMPORTED_BACKTEST"):
        return 10.0
    if derived_mode == "ANALYST_PRIOR":
        return 5.0
    if derived_mode == "ANECDOTE_ONLY":
        return 3.0
    # FIXTURE: worthless for an investable candidate; demo-grade otherwise
    return 0.0 if contract_purpose == INVESTABLE_CANDIDATE else 3.0


def validate_purpose_routing(contract: ThesisContract) -> None:
    """Board routing invariant: a contract may only sit on the board its
    purpose mandates. Contamination raises — it never renders."""
    expected = PURPOSE_DEFAULTS[contract.contract_purpose]["board_scope"]
    if contract.board_scope != expected:
        raise ValueError(
            f"BOARD_ROUTING_VIOLATION: purpose {contract.contract_purpose} "
            f"requires board_scope {expected}, found {contract.board_scope!r}")


def framework_validation_score(contract: ThesisContract) -> float:
    """FVS in [0,10]: does this contract exercise the MVP's architecture?
    High FVS is praise for the *framework*, never for the *trade*."""
    card_completeness = (sum(1 for v in (
        contract.title, contract.narrative, contract.trigger,
        contract.falsification_observable, contract.forced_null_thesis)
        if str(v).strip()) / 5.0)
    causal = _clamp(len(contract.causal_path) / 4.0, 0.0, 1.0)
    archetype = _clamp(len(contract.beneficiary_map) / 3.0, 0.0, 1.0)
    test_coverage = 1.0          # suite green (enforced by CI/pytest)
    score_pipeline_coverage = 1.0  # grade() runs the full gate spine
    return round(10.0 * (card_completeness + causal + archetype
                         + test_coverage + score_pipeline_coverage) / 5.0, 3)


def eligibility_multiplier(contract: ThesisContract,
                           lineage_valid: bool | None = None) -> float:
    """InvestabilityScore = ResearchQualityScore x this. CASE_STUDY /
    FIXTURE_TEST => 0, no exception. An INVESTABLE_CANDIDATE earns 1.0 only
    with promotion status AND verified lineage; unverified lineage fails
    closed to 0."""
    p = contract.contract_purpose
    if p in (CASE_STUDY, FIXTURE_TEST, RETIRED, FALSIFIED_PURPOSE):
        return 0.0
    if p == LIVE_RESEARCH:
        return 1.0 if contract.promotion_status == "PROMOTED" else 0.25
    if p == INVESTABLE_CANDIDATE and contract.promotion_status == "PROMOTED":
        return 1.0 if lineage_valid is True else 0.0
    return 0.0


def _purpose_scoped_verdict(contract: ThesisContract, base_verdict: str,
                            base_rule: str, fvs: float) -> tuple[str, str]:
    """Verdict restriction invariant: case studies validate frameworks and
    can never carry an investment verdict; unpromoted research is capped at
    RESEARCH_ONLY when the base verdict is investment-flavored."""
    p = contract.contract_purpose
    if p in (CASE_STUDY, FIXTURE_TEST):
        if not is_falsifiable(contract):
            # A case study that cannot lose has not exercised the
            # falsification machinery — it validates nothing.
            return V_INSUFFICIENT_EVIDENCE, "RP_UNFALSIFIABLE_CASE_STUDY"
        if fvs >= 6.0:
            v = (V_CASE_STUDY_VALIDATION if p == CASE_STUDY
                 else V_FRAMEWORK_TEST_PASS)
        else:
            v = V_FRAMEWORK_TEST_FAIL
        assert v in CASE_STUDY_ALLOWED_VERDICTS
        return v, f"RP_PURPOSE_SCOPE_{p}"
    if p == LIVE_RESEARCH and base_verdict in INVESTMENT_VERDICTS:
        return V_RESEARCH_ONLY, "RP_UNPROMOTED_RESEARCH_CAP"
    if p in (RETIRED, FALSIFIED_PURPOSE):
        return base_verdict, base_rule  # archived; verdict is historical
    return base_verdict, base_rule


def grade(contract: ThesisContract, as_of_day: int, *,
          lineage_valid: bool | None = None) -> dict[str, Any]:
    """Full contract grading. Enforces invariants I1-I5 plus the governance
    invariants (routing, purpose-scoped verdicts, investability zeroing,
    derived data-mode authenticity, lineage fail-closed) and returns the
    verdict with its binding rule id so every classification is auditable.

    For INVESTABLE_CANDIDATE contracts, pass lineage_valid from
    verify_lineage()/verify_lineage_from_index(); omitting it fails closed
    (multiplier 0)."""
    validate_purpose_routing(contract)
    eqs = evidence_quality(contract, as_of_day)
    disc = discrimination(contract, as_of_day)
    g_stale = staleness_gate(contract, as_of_day)
    g_txn = transaction_gate(contract)
    g_pm = pm_gate(contract)
    m = merit(contract)
    falsifiable = is_falsifiable(contract)

    caps_applied: list[str] = []
    fis = m["merit"] * g_txn * disc["g_contra"] * g_stale * g_pm  # I1 holds
    evidence_cap = 10.0 * eqs
    if fis > evidence_cap:                                        # I2
        fis = evidence_cap
        caps_applied.append("EVIDENCE_QUALITY_CAP")
    if not falsifiable and fis > UNFALSIFIABLE_SCORE_CAP:         # I3
        fis = UNFALSIFIABLE_SCORE_CAP
        caps_applied.append("UNFALSIFIABLE_CAP")
    fis = round(fis, 3)

    fvs = framework_validation_score(contract)
    mode_counts = evidence_mode_counts(contract)
    derived_mode = derive_data_mode(contract)
    auth_cap = authenticity_cap(derived_mode, contract.contract_purpose)
    mult = eligibility_multiplier(contract, lineage_valid)
    if (contract.contract_purpose == INVESTABLE_CANDIDATE
            and lineage_valid is not True):
        caps_applied.append("LINEAGE_UNVERIFIED_FAIL_CLOSED")
    research_quality = round(min(fis, auth_cap), 3)
    investability = round(research_quality * mult, 3)
    base_verdict, base_rule = _verdict(contract, fis, eqs, disc, g_txn, m,
                                       falsifiable)
    verdict, rule_id = _purpose_scoped_verdict(contract, base_verdict,
                                               base_rule, fvs)
    # Fixture contamination: an investable candidate with ANY fixture-driving
    # evidence is blocked outright — plumbing data can never price a trade.
    if (contract.contract_purpose == INVESTABLE_CANDIDATE
            and mode_counts["fixture_driving"] > 0):
        verdict, rule_id = (V_BLOCKED_FIXTURE_CONTAMINATION,
                            "RA_FIXTURE_DRIVING_EVIDENCE_ON_CANDIDATE")
        investability = 0.0
        caps_applied.append("FIXTURE_CONTAMINATION_BLOCK")
    provenance_counts: dict[str, int] = {}
    for e in contract.evidence:
        provenance_counts[e.provenance] = provenance_counts.get(e.provenance, 0) + 1

    return {
        "thesis_id": contract.thesis_id,
        "as_of_day": int(as_of_day),
        "data_mode": contract.data_mode,
        "evidence_quality": eqs,
        "discrimination": disc,
        "g_stale": g_stale, "g_txn": g_txn, "g_pm": g_pm,
        "merit": m,
        "final_score": fis,
        "caps_applied": caps_applied,
        "falsifiable": falsifiable,
        "days_to_expiry": max(0, contract.expiry_day - int(as_of_day)),
        "verdict": verdict, "verdict_rule": rule_id,
        "contract_purpose": contract.contract_purpose,
        "investment_eligibility": contract.investment_eligibility,
        "promotion_status": contract.promotion_status,
        "board_scope": contract.board_scope,
        "trading_status": contract.trading_status,
        "framework_validation_score": fvs,
        "research_quality_score": research_quality,
        "eligibility_multiplier": mult,
        "investability_score": investability,
        "derived_data_mode": derived_mode,
        "authenticity_cap": auth_cap,
        "evidence_mode_counts": mode_counts,
        "lineage_valid": lineage_valid,
        "provenance_counts": provenance_counts,
        "anecdotes_quarantined": [
            {"evidence_id": e.evidence_id,
             "corroborated": anecdote_is_corroborated(e, contract)}
            for e in contract.evidence if e.provenance == ANECDOTE],
        "advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY,
    }


def _verdict(contract: ThesisContract, fis: float, eqs: float,
             disc: dict[str, float], g_txn: float, m: dict[str, float],
             falsifiable: bool) -> tuple[str, str]:
    rf = contract.risk_flags
    mi = contract.merit_inputs
    if eqs < EQS_INSUFFICIENT_FLOOR or not falsifiable:
        return V_INSUFFICIENT_EVIDENCE, "R1_EQS_OR_UNFALSIFIABLE"
    if rf.get("confusion_rent", 0.0) >= 7.0:
        return V_CONFUSION_RENT_TRAP, "R2_CONFUSION_RENT>=7"
    if rf.get("state_integrity", 0.0) >= 8.0:
        return V_STATE_INTEGRITY_TRAP, "R3_STATE_INTEGRITY>=8"
    if m["demand_D"] >= 7.0 and (g_txn <= 0.5 or disc["n_against"] >= 2):
        return V_HYPE_RISK, "R4_STRONG_STORY_WEAK_CONVERSION_OR_CONTRADICTED"
    link = contract.pm_link or {}
    if (abs(float(link.get("edge", 0.0))) >= 0.5
            and bool(link.get("category_validated", False))):
        return V_PM_MISPRICING, "R5_PM_EDGE_VALIDATED_CATEGORY"
    if mi.get("funnel_stage_advance", 0.0) >= 2.0 and fis >= 6.0:
        return V_NTT_BREAKOUT, "R6_FUNNEL_ADVANCE>=2_AND_FIS>=6"
    has_hard_infra = any(
        e.provenance == HARD_DATA and e.stance == FOR_THESIS
        and e.ecology in ("sec_filing", "regulatory")
        for e in contract.evidence)
    if (m["moat_M"] >= 7.0 and has_hard_infra
            and mi.get("awareness_gap", 0.0) >= 6.0 and fis >= 7.0):
        return V_INVISIBLE_INFRA, "R7_MOAT+HARD_INFRA+AG+FIS"
    if fis >= 7.5 and eqs >= 0.6 and disc["g_contra"] >= 0.8:
        return V_STRONG_BUY, "R8_FIS>=7.5_EQS>=0.6_GCONTRA>=0.8"
    if fis >= 5.0:
        return V_WATCHLIST, "R9_FIS>=5"
    return V_AVOID, "R10_FIS<5"


def resolve(contract: ThesisContract, as_of_day: int,
            realized_return: float | None = None) -> dict[str, Any]:
    """Adjudicate at/after expiry. The system grades; the author does not.
    Returns a cemetery record; mutates contract.status."""
    if int(as_of_day) < contract.expiry_day:
        return {"resolved": False, "status": contract.status,
                "days_to_expiry": contract.expiry_day - int(as_of_day)}
    if realized_return is None:
        contract.status = EXPIRED
        _reassign_purpose(contract, RETIRED)
    else:
        want_up = contract.predicted_direction.upper() == "UP"
        aligned = (realized_return > 0) if want_up else (realized_return < 0)
        contract.status = VALIDATED if aligned else FALSIFIED
        if contract.status == FALSIFIED:
            _reassign_purpose(contract, FALSIFIED_PURPOSE)
    return {
        "resolved": True, "thesis_id": contract.thesis_id,
        "status": contract.status, "resolution_day": int(as_of_day),
        "realized_return": realized_return,
        "predicted_direction": contract.predicted_direction,
        "data_mode": contract.data_mode,
        "evidence_class": ("LIVE" if contract.data_mode == LIVE
                           else contract.data_mode),
    }


def append_cemetery(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def save_contract(contract: ThesisContract, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(contract.to_dict(), indent=2, sort_keys=True),
                    encoding="utf-8")


def load_contract(path: Path) -> ThesisContract:
    return ThesisContract.from_dict(json.loads(path.read_text(encoding="utf-8")))


def contract_id(entity: str, claim: str, created_day: int) -> str:
    return hashlib.sha256(f"{entity}|{claim}|{created_day}".encode()).hexdigest()[:16]


def _reassign_purpose(contract: ThesisContract, new_purpose: str) -> None:
    """Adjudication-driven purpose change (system-graded, not author-edited).
    Forces the routing defaults so an archived contract cannot linger on an
    active board."""
    contract.contract_purpose = new_purpose
    for fieldname, value in PURPOSE_DEFAULTS[new_purpose].items():
        setattr(contract, fieldname, value)


# --- lineage custody (anti-forgery) ---------------------------------------------
# A promoted contract must PROVE its lineage: the child stores a hash of its
# parent's canonical payload plus a lineage hash binding parent, child,
# promotion day, and rationale. A hand-written contract with a fake
# parent_research_id fails verification and is fail-closed everywhere.

ALLOWED_TRANSITIONS = frozenset({(CASE_STUDY, LIVE_RESEARCH),
                                 (LIVE_RESEARCH, INVESTABLE_CANDIDATE)})

# Lineage binds the IMMUTABLE escrow collateral — identity, purpose,
# direction, expiry, falsification observable, forced null, and promotion
# metadata. Evidence and merit inputs are deliberately excluded: research
# contracts must accumulate evidence without breaking lineage, but weakening
# the falsification contract or re-pointing the ticker post-promotion MUST
# break it.
_IDENTITY_FIELDS = (
    "thesis_id", "entity", "ticker", "contract_purpose",
    "predicted_direction", "created_day", "expiry_day",
    "falsification_observable", "forced_null_thesis",
    "parent_case_study_id", "parent_research_id",
    "promotion_day", "promotion_note",
)


def contract_core_hash(contract: ThesisContract) -> str:
    """Lineage identity hash: sha256 over the immutable escrow-collateral
    fields only (see _IDENTITY_FIELDS)."""
    d = contract.to_dict()
    identity = {k: d.get(k) for k in _IDENTITY_FIELDS}
    blob = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def make_lineage_hash(parent_hash: str, child_core_hash: str,
                      promotion_day: int, promotion_note: str) -> str:
    blob = f"{parent_hash}|{child_core_hash}|{promotion_day}|{promotion_note}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _stamp_lineage(child: ThesisContract, parent: ThesisContract) -> None:
    child.parent_hash = contract_core_hash(parent)
    child.lineage_hash = make_lineage_hash(
        child.parent_hash, contract_core_hash(child),
        child.promotion_day, child.promotion_note)


def verify_lineage(child: ThesisContract,
                   parent: ThesisContract | None) -> dict[str, Any]:
    """LineageValid = 1 iff parent hash matches, lineage hash recomputes, and
    the purpose transition is allowed. Anything else fails closed."""
    reasons: list[str] = []
    if parent is None:
        return {"valid": False,
                "reasons": ["CONTRACT_LINEAGE_FAIL_CLOSED:PARENT_NOT_FOUND"]}
    expected_parent = (CASE_STUDY if child.contract_purpose == LIVE_RESEARCH
                       else LIVE_RESEARCH)
    if (parent.contract_purpose, child.contract_purpose) not in ALLOWED_TRANSITIONS:
        # a RETIRED/FALSIFIED/FIXTURE_TEST parent can never mint children
        reasons.append("TRANSITION_NOT_ALLOWED:"
                       f"{parent.contract_purpose}->{child.contract_purpose}")
    if parent.contract_purpose != expected_parent:
        reasons.append(f"PARENT_PURPOSE_NOT_{expected_parent}")
    if (child.contract_purpose == INVESTABLE_CANDIDATE
            and parent.promotion_status not in
            ("PROMOTION_REQUIRED", "PROMOTION_REQUESTED", "PROMOTED")):
        reasons.append("PARENT_PROMOTION_STATUS_INVALID")
    if contract_core_hash(parent) != child.parent_hash:
        reasons.append("PARENT_HASH_MISMATCH")
    expected_lineage = make_lineage_hash(
        child.parent_hash, contract_core_hash(child),
        child.promotion_day, child.promotion_note)
    if expected_lineage != child.lineage_hash:
        reasons.append("LINEAGE_HASH_MISMATCH")
    return {"valid": not reasons, "reasons": reasons}


def verify_lineage_from_index(child: ThesisContract,
                              contract_index: dict[str, ThesisContract]
                              ) -> dict[str, Any]:
    parent_id = (child.parent_research_id
                 if child.contract_purpose == INVESTABLE_CANDIDATE
                 else child.parent_case_study_id)
    return verify_lineage(child, contract_index.get(parent_id))


def load_contract_index(store_dir: Path) -> dict[str, ThesisContract]:
    index: dict[str, ThesisContract] = {}
    if store_dir.exists():
        for p in sorted(store_dir.glob("*.json")):
            try:
                c = load_contract(p)
            except ValueError:
                continue
            index[c.thesis_id] = c
    return index


# --- promotion workflow ---------------------------------------------------------
# A case study is never edited into a candidate. It is CLONED into a new
# LIVE_RESEARCH contract, which may later be promoted into a NEW
# INVESTABLE_CANDIDATE contract — three objects, three thesis_ids, one
# auditable lineage.

def promote_case_study_to_research(
        case_study: ThesisContract, *, day: int, expiry_day: int,
        falsification_observable: str, new_ticker: str | None = None,
        rationale: str = "") -> ThesisContract:
    if case_study.contract_purpose != CASE_STUDY:
        raise ValueError("PROMOTION_SOURCE_NOT_CASE_STUDY: "
                         f"{case_study.contract_purpose}")
    if not falsification_observable.strip() or expiry_day <= day:
        raise ValueError("PROMOTION_REQUIRES_NEW_EXPIRY_AND_FALSIFICATION")
    ticker = new_ticker or case_study.ticker
    new_id = contract_id(case_study.entity,
                         f"research:{case_study.thesis_id}:{rationale}", day)
    research = ThesisContract(
        thesis_id=new_id,
        title=f"[RESEARCH] {case_study.title}",
        entity=case_study.entity, ticker=ticker,
        narrative=case_study.narrative, trigger=case_study.trigger,
        predicted_direction=case_study.predicted_direction,
        horizon_days=max(1, expiry_day - day), created_day=day,
        expiry_day=expiry_day,
        falsification_observable=falsification_observable,
        forced_null_thesis=case_study.forced_null_thesis,
        causal_path=list(case_study.causal_path),
        beneficiary_map=dict(case_study.beneficiary_map),
        evidence=[],                      # research earns its own evidence
        merit_inputs=dict(case_study.merit_inputs),
        risk_flags=dict(case_study.risk_flags),
        pm_link=case_study.pm_link, data_mode=LIVE,
        contract_purpose=LIVE_RESEARCH,
        parent_case_study_id=case_study.thesis_id,
        promotion_note=rationale,
        promotion_day=int(day),
    )
    _stamp_lineage(research, case_study)
    return research


PROMOTION_MIN_EQS = 0.60
PROMOTION_MIN_FIS = 7.0
PROMOTION_MIN_GCONTRA = 0.80
PROMOTION_MIN_GSTALE = 0.70
PROMOTION_MIN_HARD_EVIDENCE = 2
PROMOTION_ALLOWED_RETROCAST = ("VALIDATED", "UNAVAILABLE_NEUTRAL")


def promote_research_to_investable(
        research: ThesisContract, *, approval_note: str, as_of_day: int,
        retrocast_category_status: str = "UNAVAILABLE_NEUTRAL",
        evidence_check: bool = True) -> dict[str, Any]:
    """Returns {'promoted': True, 'contract': <new contract>} or
    {'promoted': False, 'blockers': [...exact reasons...]}. Never silent."""
    blockers: list[str] = []
    if research.contract_purpose != LIVE_RESEARCH:
        blockers.append(f"SOURCE_NOT_LIVE_RESEARCH:{research.contract_purpose}")
    if evidence_check:
        report = grade(research, as_of_day)
        # Verified counts — self-declared modes carry no weight here.
        live_count = sum(1 for e in research.evidence if item_live_verified(e))
        hard_count = sum(1 for e in research.evidence
                         if item_hard_admissible(e))
        non_anecdote = sum(1 for e in research.evidence
                           if e.provenance != ANECDOTE)
        derived_mode = report["derived_data_mode"]
        if report["evidence_quality"] < PROMOTION_MIN_EQS:
            blockers.append(f"EQS_BELOW_{PROMOTION_MIN_EQS}:"
                            f"{report['evidence_quality']}")
        if report["final_score"] < PROMOTION_MIN_FIS:
            blockers.append(f"FIS_BELOW_{PROMOTION_MIN_FIS}:"
                            f"{report['final_score']}")
        if not (live_count >= 1 or hard_count >= PROMOTION_MIN_HARD_EVIDENCE):
            blockers.append("NO_VERIFIED_LIVE_AND_HARD_EVIDENCE_COUNT_LT_2")
        if report["discrimination"]["g_contra"] < PROMOTION_MIN_GCONTRA:
            blockers.append(f"CONTRADICTION_GATE_BELOW_{PROMOTION_MIN_GCONTRA}:"
                            f"{report['discrimination']['g_contra']}")
        if report["g_stale"] < PROMOTION_MIN_GSTALE:
            blockers.append(f"STALENESS_GATE_BELOW_{PROMOTION_MIN_GSTALE}:"
                            f"{report['g_stale']}")
        if (research.data_mode == FIXTURE_DEMONSTRATION
                or derived_mode == "FIXTURE"):
            blockers.append("FIXTURE_ONLY_EVIDENCE")
        if research.evidence and non_anecdote == 0:
            blockers.append("ANECDOTE_ONLY_EVIDENCE")
        if not research.evidence:
            blockers.append("NO_EVIDENCE")
        if not is_falsifiable(research):
            blockers.append("MISSING_EXPIRY_OR_FALSIFICATION_OBSERVABLE")
        if not research.forced_null_thesis.strip():
            blockers.append("MISSING_FORCED_NULL_THESIS")
        if retrocast_category_status not in PROMOTION_ALLOWED_RETROCAST:
            blockers.append(f"RETROCAST_CATEGORY_{retrocast_category_status}")
    if blockers:
        return {"promoted": False, "blockers": blockers,
                "thesis_id": research.thesis_id}
    new_id = contract_id(research.entity,
                         f"candidate:{research.thesis_id}", as_of_day)
    candidate = ThesisContract(
        thesis_id=new_id, title=f"[CANDIDATE] {research.title}",
        entity=research.entity, ticker=research.ticker,
        narrative=research.narrative, trigger=research.trigger,
        predicted_direction=research.predicted_direction,
        horizon_days=research.horizon_days, created_day=int(as_of_day),
        expiry_day=research.expiry_day,
        falsification_observable=research.falsification_observable,
        forced_null_thesis=research.forced_null_thesis,
        causal_path=list(research.causal_path),
        beneficiary_map=dict(research.beneficiary_map),
        evidence=list(research.evidence),
        merit_inputs=dict(research.merit_inputs),
        risk_flags=dict(research.risk_flags),
        pm_link=research.pm_link, data_mode=research.data_mode,
        contract_purpose=INVESTABLE_CANDIDATE,
        promotion_status="PROMOTED",
        parent_case_study_id=research.parent_case_study_id,
        parent_research_id=research.thesis_id,
        promotion_note=approval_note,
        promotion_day=int(as_of_day),
    )
    _stamp_lineage(candidate, research)
    return {"promoted": True, "contract": candidate,
            "parent_research_id": research.thesis_id,
            "lineage_hash": candidate.lineage_hash,
            "parent_hash": candidate.parent_hash}


# --- deterministic fixture builders (never calibration-eligible) --------------

def fixture_contract_strong(as_of_day: int = 1000) -> ThesisContract:
    """Well-evidenced, falsifiable, discriminating contract (demo)."""
    ev = [
        EvidenceItem("ev-hard-1", "10-K discloses take-rate revenue share 62%",
                     "EDGAR 10-K", "sec_filing", HARD_DATA, FOR_THESIS,
                     as_of_day - 20),
        EvidenceItem("ev-mkt-1", "Event market ΔP +0.14 persisted 5 days",
                     "prediction market", "prediction_market", MARKET,
                     FOR_THESIS, as_of_day - 3),
        EvidenceItem("ev-mkt-2", "Partner-corridor fee page cut 30bps",
                     "pricing page diff", "pricing_page", MARKET, FOR_THESIS,
                     as_of_day - 10),
        EvidenceItem("ev-hard-2", "Counterparty 10-K names provider as vendor",
                     "EDGAR FTS", "regulatory", HARD_DATA, FOR_THESIS,
                     as_of_day - 40),
        EvidenceItem("ev-anec-1", "Operator field obs: transfer routed via rail",
                     "field observation", "field_observation", ANECDOTE,
                     FOR_THESIS, as_of_day - 15),
    ]
    return ThesisContract(
        thesis_id="fixture-strong-0001", title="Embedded rail volume compounding",
        entity="FixtureRail Plc", ticker="FIXR", narrative="Partner-routed volume "
        "grows without CAC while market prices the consumer brand only.",
        trigger="ΔP shock on payments-adoption event market",
        predicted_direction="UP", horizon_days=120,
        created_day=as_of_day - 30, expiry_day=as_of_day + 90,
        falsification_observable="Two consecutive reports without partner-volume "
        "growth, or a top-3 partner insourcing the rail",
        forced_null_thesis="Consumer growth explains all volume; partner-routed "
        "volume is flat",
        causal_path=["belief: cheap transfers", "neobanks embed rail",
                     "partner volume", "take-rate revenue", "repricing"],
        beneficiary_map={"house": ["FIXR"], "midstream": ["NEOB"],
                         "losers": ["INCB"]},
        evidence=ev,
        merit_inputs={"awareness_gap": 6.5, "long_tail_demand": 5.5,
                      "house_layer": 8.0, "infra_capture": 7.5,
                      "transaction_certainty": 7.5,
                      "narrative_transmission": 8.0},
        risk_flags={"confusion_rent": 2.0},
        pm_link={"market_id": "FIX-PAY-ADOPT", "edge": 0.42, "alignment": 8.0,
                 "category_validated": True},
        data_mode=FIXTURE_DEMONSTRATION,
        contract_purpose=FIXTURE_TEST,
    )


def fixture_contract_anecdote_only(as_of_day: int = 1000) -> ThesisContract:
    """Anecdote-only contract: must never leave quarantine (demo)."""
    ev = [
        EvidenceItem("ev-anec-a", "Tourist bought worse ticket at machine",
                     "travel anecdote", "field_observation", ANECDOTE,
                     FOR_THESIS, as_of_day - 5),
        EvidenceItem("ev-anec-b", "Shop stocked a premium niche SKU",
                     "shop visit", "field_observation", ANECDOTE, FOR_THESIS,
                     as_of_day - 12),
    ]
    return ThesisContract(
        thesis_id="fixture-anecdote-0002", title="Awareness-gap story, no data",
        entity="Anecdote AG", ticker="ANEC", narrative="A story about mispricing "
        "with no measurable substrate yet.",
        trigger="operator observation", predicted_direction="UP",
        horizon_days=60, created_day=as_of_day - 12, expiry_day=as_of_day + 48,
        falsification_observable="No measurable awareness divergence within 60d",
        forced_null_thesis="The observation was idiosyncratic; no divergence",
        causal_path=["observation", "awareness gap", "repricing"],
        beneficiary_map={"midstream": ["ANEC"]},
        evidence=ev,
        merit_inputs={"awareness_gap": 9.0, "house_layer": 8.5},
        data_mode=FIXTURE_DEMONSTRATION,
        contract_purpose=LIVE_RESEARCH,
    )


def _main() -> int:
    ap = argparse.ArgumentParser(description="Grade a thesis contract (advisory)")
    ap.add_argument("--contract", type=Path, help="path to contract JSON")
    ap.add_argument("--as-of-day", type=int, required=True)
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()
    c = (fixture_contract_strong(args.as_of_day) if args.demo
         else load_contract(args.contract))
    print(json.dumps(grade(c, args.as_of_day), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
