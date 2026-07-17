"""Counterfactual shadow policies — advisory-only, historically immutable.

For each frozen prediction, record how a set of alternative advisory policies
would have classified the candidate. NONE of these executes anything. Later, once
outcomes resolve, the policies can be compared on calibration / false-risk-block /
tail recall / regret — empirical comparison WITHOUT placing a single trade.

A policy decision is frozen with an immutability hash so a policy can never
rewrite its own history (no hindsight).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.simulation_intelligence.contracts import AdvisoryVote, VOTE_DEFENSIVENESS
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from simulation_intelligence.contracts import AdvisoryVote, VOTE_DEFENSIVENESS  # type: ignore[no-redef]


def _hash(payload: Any) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ShadowPolicyDecision:
    policy: str
    twin_id: str
    candidate_id: str
    info_cutoff: str
    advisory_state: str
    rationale: str
    immutability_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


# Each policy maps a council result → one advisory state, deterministically.
def _council_policy(c: dict) -> tuple[str, str]:
    return c.get("aggregate_vote", "WATCH"), "council aggregate"


def _risk_first(c: dict) -> tuple[str, str]:
    if c.get("risk_block_engaged") or c.get("tail_warnings"):
        return AdvisoryVote.RISK_BLOCK.value, "any tail/risk signal → block"
    if float(c.get("fragility", 0) or 0) >= 0.6:
        return AdvisoryVote.AVOID.value, "high fragility → avoid"
    return AdvisoryVote.WAIT.value, "risk-first default is to wait"


def _wait_for_confirmation(c: dict) -> tuple[str, str]:
    if (c.get("freshness_status") or "").upper() in ("AGING", "STALE", "UNKNOWN"):
        return AdvisoryVote.WAIT.value, "unconfirmed/stale → wait"
    if c.get("aggregate_vote") in ("AVOID", "RISK_BLOCK"):
        return c["aggregate_vote"], "defensive council respected"
    return AdvisoryVote.WATCH.value, "confirmed & benign → watch"


def _highest_confidence_only(c: dict) -> tuple[str, str]:
    if float(c.get("aggregate_confidence", 0) or 0) >= 0.6:
        return c.get("aggregate_vote", "WATCH"), "high confidence → follow council"
    return AdvisoryVote.WAIT.value, "low confidence → wait"


def _no_action(c: dict) -> tuple[str, str]:
    return AdvisoryVote.WATCH.value, "no-action baseline (always watch)"


def _racr_weighted(c: dict) -> tuple[str, str]:
    # Approximate: defensive when disagreement is not robust consensus.
    dis = c.get("disagreement_class", "")
    if dis in ("SPLIT_DECISION", "MINORITY_TAIL_WARNING") or c.get("risk_block_engaged"):
        return AdvisoryVote.AVOID.value, "RACR-weighted: fragile/split → avoid"
    return c.get("aggregate_vote", "WATCH"), "RACR-weighted follows council on robust consensus"


_POLICIES = {
    "council": _council_policy,
    "risk_first": _risk_first,
    "wait_for_confirmation": _wait_for_confirmation,
    "highest_confidence_only": _highest_confidence_only,
    "no_action": _no_action,
    "racr_weighted": _racr_weighted,
}


def policy_names() -> list[str]:
    return list(_POLICIES.keys())


def evaluate_policies(council: dict[str, Any], twin_id: str) -> list[ShadowPolicyDecision]:
    """Classify a candidate under every shadow policy. Each decision is frozen."""
    cutoff = str(council.get("data_cutoff", ""))
    cand = str(council.get("ticker", ""))
    out: list[ShadowPolicyDecision] = []
    for name, fn in _POLICIES.items():
        state, rationale = fn(council)
        core = {"policy": name, "twin_id": twin_id, "info_cutoff": cutoff,
                "candidate_id": cand, "advisory_state": state}
        out.append(ShadowPolicyDecision(
            policy=name, twin_id=twin_id, candidate_id=cand, info_cutoff=cutoff,
            advisory_state=state, rationale=rationale, immutability_hash=_hash(core)))
    return out


def verify_decision(d: ShadowPolicyDecision) -> bool:
    core = {"policy": d.policy, "twin_id": d.twin_id, "info_cutoff": d.info_cutoff,
            "candidate_id": d.candidate_id, "advisory_state": d.advisory_state}
    return _hash(core) == d.immutability_hash


def compare_on_outcome(
    decisions: list[dict[str, Any]],
    adverse: bool,
    tail: bool,
) -> dict[str, Any]:
    """Given resolved outcome flags, score each policy's decision on THIS case.
    Aggregate across many cases externally; this is per-case credit/blame."""
    per_policy = {}
    for d in decisions:
        state = d.get("advisory_state", "WATCH")
        defensive = VOTE_DEFENSIVENESS.get(state, 0) >= 3  # AVOID/RISK_BLOCK
        # Good defensive call: adverse happened and policy was defensive.
        correct = (defensive and adverse) or (not defensive and not adverse)
        false_block = defensive and not adverse
        missed = (not defensive) and adverse
        per_policy[d.get("policy")] = {
            "advisory_state": state, "correct": correct,
            "false_risk_block": false_block, "missed_risk_block": missed,
            "tail_caught": bool(defensive and tail),
        }
    result = {"report": "shadow_policy_case", "adverse": adverse, "tail": tail,
              "per_policy": per_policy}
    result.update(advisory_safety_stamps())
    return result


__all__ = [
    "ShadowPolicyDecision", "policy_names", "evaluate_policies", "verify_decision",
    "compare_on_outcome",
]
