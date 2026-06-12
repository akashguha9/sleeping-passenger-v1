"""Risk Convergence: the doubt committee.

Eleven layers can each raise warn-only findings — signal redundancy,
challenged overrides, calibration risk, fragile verdicts, marginal
expiry clocks, over-hedges, fake-exponential ceilings, loaded dice.
Each warns alone; none could see the others. A thesis carrying five
sub-threshold doubts sailed to buy_candidate because no SINGLE gate
fired: death by a thousand warns.

This layer convenes the doubts — with the signal refiner's own
doctrine applied to the model's warnings: **doubts cluster like
signals do; count root causes, not echoes.**

* Findings are grouped into root-cause FAMILIES (evidence quality,
  integrity/gaming, calibration, structural fragility, adaptation
  pressure, timing decay). Multiple findings inside one family count
  ONCE — two symptoms of the same disease are not two diseases.
* Families whose hard gate already capped the verdict are excluded —
  no double jeopardy; the doubt was already adjudicated.
* Convergence gates conservatively:

      2 independent families  -> cap at active_watch
      3+ independent families -> cap at watchlist

  (`RISK_CONVERGENCE_CAP`). The committee can only ever LOWER a
  verdict; zero findings change nothing. ADVISORY_ONLY.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.simulator.threshold_ladder import LADDER_STATES

FAMILY_DESCRIPTIONS: dict[str, str] = {
    "evidence_quality": "the evidence is thinner than it looks",
    "integrity_gaming": "someone tried to make it look better",
    "calibration": "the model's own confidence is suspect here",
    "structural_fragility": "the thesis hangs on few assumptions",
    "adaptation_pressure": "the market is closing in on this edge",
    "timing_decay": "the clock is the binding constraint",
}

# Warn-level reason codes -> root-cause family. Informational codes
# (OPPONENT_SELF_FED, CONSENT_EVIDENCE_*) and hard-gate codes are not
# doubts and never counted.
CODE_FAMILIES: dict[str, str] = {
    "SIGNAL_REDUNDANCY_HIGH": "evidence_quality",
    "OPPONENT_OVERRIDE_CHALLENGED": "integrity_gaming",
    "LOADED_DICE_SUSPECTED": "integrity_gaming",
    "DICE_CALIBRATION_RISK": "calibration",
    "SELF_FEED_LOW_COVERAGE": "calibration",
    "LIFECYCLE_FRAGILE": "structural_fragility",
}

# Hard-gate codes that mean a family was already adjudicated (capped):
# its findings are excluded — no double jeopardy.
ADJUDICATED: dict[str, str] = {
    "EDGE_EXHAUSTED": "adaptation_pressure",
    "FATAL_WEAK_SIDE": "structural_fragility",
    "EDGE_EXPIRED": "timing_decay",
    "SATURATION_PRICED_IN": "timing_decay",
}

CAP_TWO_FAMILIES = "active_watch"
CAP_THREE_FAMILIES = "watchlist"


@dataclass(slots=True)
class RiskFinding:
    """One warn-level doubt, attributed to its root-cause family."""

    family: str
    code: str
    source: str
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class RiskConvergenceReport:
    """The doubt committee's minutes for one evaluation."""

    finding_count: int
    family_count: int  # deduplicated root causes
    families: list[str] = field(default_factory=list)
    adjudicated_families: list[str] = field(default_factory=list)
    findings: list[RiskFinding] = field(default_factory=list)
    suppressed_echoes: int = 0  # findings beyond the first per family
    cap_applied: str = ""  # "" | active_watch | watchlist
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["findings"] = [f.to_dict() for f in self.findings]
        return payload


def collect_findings(
    reason_codes: list[str],
    *,
    opponent: dict[str, Any] | None = None,
    lifecycle: dict[str, Any] | None = None,
) -> list[RiskFinding]:
    """Sweep warn-level findings from the codes and the layer reports.

    Layer-report findings cover doubts that never become reason codes:
    a crowded (not yet exhausted) edge, an overused weapon, a marginal
    expiry clock, an over-hedge, a fake-exponential ceiling, an
    unsupported belief gap.
    """
    findings: list[RiskFinding] = []
    seen_codes: set[str] = set()
    for code in reason_codes or []:
        family = CODE_FAMILIES.get(code)
        if family and code not in seen_codes:
            seen_codes.add(code)
            findings.append(RiskFinding(
                family=family, code=code, source="decision.reason_codes",
                detail=FAMILY_DESCRIPTIONS[family],
            ))

    if opponent:
        adaptation = dict(opponent.get("adaptation") or {})
        if adaptation.get("state") == "crowded_edge":
            findings.append(RiskFinding(
                family="adaptation_pressure", code="CROWDED_EDGE_WARN",
                source="opponent.adaptation",
                detail="OAI in the crowded band — recognized, not yet "
                "exhausted",
            ))
        weapon = dict(opponent.get("weapon_map") or {})
        if weapon.get("overused"):
            findings.append(RiskFinding(
                family="adaptation_pressure", code="WEAPON_OVERUSED",
                source="opponent.weapon_map",
                detail="the strongest edge is strong AND crowded — "
                "predictability is attack surface",
            ))

    if lifecycle:
        expiry = dict(lifecycle.get("expiry") or {})
        if expiry.get("status") == "marginal":
            findings.append(RiskFinding(
                family="timing_decay", code="EXPIRY_MARGINAL",
                source="lifecycle.expiry",
                detail=f"{expiry.get('days_to_expiry', 0)} day(s) to "
                "expiry — under half a half-life of runway",
            ))
        capacity = dict(lifecycle.get("capacity") or {})
        if capacity.get("fake_exponential"):
            findings.append(RiskFinding(
                family="structural_fragility", code="FAKE_EXPONENTIAL",
                source="lifecycle.capacity",
                detail="claimed growth overruns its own evidenced "
                "ceiling within the horizon",
            ))
        hedge = dict(lifecycle.get("hedge") or {})
        if hedge.get("over_hedged"):
            findings.append(RiskFinding(
                family="structural_fragility", code="OVER_HEDGED",
                source="lifecycle.hedge",
                detail="the protection costs more than the edge it "
                "protects",
            ))
        arbitrage = dict(lifecycle.get("arbitrage") or {})
        if arbitrage.get("gap_unsupported"):
            findings.append(RiskFinding(
                family="evidence_quality", code="GAP_UNSUPPORTED",
                source="lifecycle.arbitrage",
                detail="the belief gap is heat, not evidence",
            ))
    return findings


def converge_risk(
    *,
    reason_codes: list[str],
    final_state: str,
    opponent: dict[str, Any] | None = None,
    lifecycle: dict[str, Any] | None = None,
) -> RiskConvergenceReport:
    """Convene the doubt committee and decide whether the swarm gates.

    Dedup first (echoes within a family count once), exclude families a
    hard gate already adjudicated, then apply the convergence rule:
    2 independent families cap at active_watch, 3+ cap at watchlist —
    conservative-only, fully cited.
    """
    findings = collect_findings(
        reason_codes, opponent=opponent, lifecycle=lifecycle,
    )
    adjudicated = sorted({
        family for code, family in ADJUDICATED.items()
        if code in (reason_codes or [])
    })
    live_findings = [f for f in findings if f.family not in adjudicated]
    families = sorted({f.family for f in live_findings})
    suppressed = len(live_findings) - len(families)

    cap_applied = ""
    if len(families) >= 3:
        cap_target = CAP_THREE_FAMILIES
    elif len(families) == 2:
        cap_target = CAP_TWO_FAMILIES
    else:
        cap_target = ""
    if cap_target and final_state in LADDER_STATES and (
        LADDER_STATES.index(final_state) > LADDER_STATES.index(cap_target)
    ):
        cap_applied = cap_target

    rationale = [
        f"{len(live_findings)} warn-level finding(s) across "
        f"{len(families)} independent root-cause family(ies); "
        f"{suppressed} echo(es) suppressed within families — doubts are "
        "deduplicated like signals: root causes, not echoes",
    ]
    if adjudicated:
        rationale.append(
            "excluded (already adjudicated by a hard gate): "
            + ", ".join(adjudicated)
        )
    if cap_applied:
        rationale.append(
            f"convergence cap -> {cap_applied}: no single doubt was "
            "disqualifying, but independent doubts that arrive together "
            "are not independent events for the thesis"
        )
    elif len(families) == 1:
        rationale.append(
            "a single root-cause family warns but does not gate — one "
            "doubt is a question, not a verdict"
        )
    elif not families:
        rationale.append("no warn-level findings — the committee is idle")
    elif cap_target:
        rationale.append(
            f"convergence threshold met but the state is already at or "
            f"below {cap_target} — nothing to cap"
        )
    return RiskConvergenceReport(
        finding_count=len(live_findings),
        family_count=len(families),
        families=families,
        adjudicated_families=adjudicated,
        findings=live_findings,
        suppressed_echoes=suppressed,
        cap_applied=cap_applied,
        rationale=rationale,
    )
