# BRANCH_PAYLOAD
# Module: S1 — Narrative Engine / HWE Extension
# Added: April 17 2026
# Source: Quantum mechanics interpretations session
#
# Extends HWE with per-branch consequence maps.
#
# HWE says: 'H1 weight = 0.82, state = COMMITTED'
# BRANCH_PAYLOAD says: 'H1 fires when X, yields Y, dies if Z, and when it fires,
#                       these 3 adjacent positions are affected in these directions'
#
# Many Worlds insight operationalised:
#   Not just WHICH world has the highest probability (HWE)
#   But WHAT EXACTLY HAPPENS in each world and HOW ARE WE POSITIONED (BRANCH_PAYLOAD)
#
# The quantum law: No collapse, no conviction.
# Know what kills each branch BEFORE you enter. The future is a tree, not a line.
#
# BRANCH_PAYLOAD integrates with:
#   CIS2: confirmation_triggers must match observable_links
#   SLT:  branch fires expected at VALIDATION or EXPANSION stage
#   TAT:  branch fires expected when TAT = PEAK
#   LPS:  if LPS = HIGH, all branch payoff_estimates discounted
#   NDM:  if NDM = DRIFTING, invalidation_conditions tightened
#   NII:  if NII >= INFLATED, payoff_estimate discounted
#   RTT:  payoff_estimate adjusted by CE_hostile
#   PES:  adjacent_asset_effects cross-checked with cluster entanglement
#
# Portfolio retrospectives:
#   RTX Day 3:   All 7 BRANCH_PAYLOAD fields well-specified.
#                Triggers met. Payoff matched. Invalidation not triggered.
#                Adjacent GLD + confirmed. SLT VALIDATION at collapse. +3.90% WIN.
#
#   CVX Day 80:  H1 branch INVALIDATION_CONDITION ALREADY MET at intake.
#                Polymarket Iran < 0.40 at entry evaluation. SLT=EXHAUSTION.
#                half_life_days = 0. BRANCH_PAYLOAD BLOCKS.
#                -8.82% avoided. The branch was dead before we tried to enter.
#
#   GLD current: H1 ongoing. Invalidation: ceasefire + Poly Iran < 0.25 + GLD < ,000.
#                None met. Adjacent: SGOL correlated (hold), RTX independent.
#                +8.17% confirms. Continue EXPANSION.
#
# BRANCH_PAYLOAD does NOT replace HWE. It extends it:
#   HWE computes:  probability weights, CONVERGING/COMMITTED/DISTRIBUTED state
#   BRANCH_PAYLOAD computes: per-branch operational consequence map
#
# 7 required fields per hypothesis branch:
#   1. confirmation_triggers    (list[str]) - specific measurable collapse events
#   2. payoff_estimate          (float)     - CE × position_size × expected_duration
#   3. invalidation_condition   (str)       - single observable that kills this branch
#   4. adjacent_asset_effects   (dict)      - {ticker: direction} for open positions
#   5. slt_stage_at_collapse    (str)       - expected SLT stage when branch fires
#   6. half_life_days           (int)       - max days branch stays valid without trigger
#   7. branch_status            (str)       - ACTIVE/INVALIDATED/FIRED/EXPIRED

from typing import TypedDict, Optional
from datetime import date

class BranchPayload(TypedDict):
    branch_id:               str             # 'H1', 'H2', 'H3'
    branch_description:      str
    hwe_weight:              float           # from HWE at time of construction
    hwe_state:               str             # CONVERGING / COMMITTED / DISTRIBUTED
    confirmation_triggers:   list            # specific measurable events for collapse
    payoff_estimate:         float           # estimated CE × size × duration
    invalidation_condition:  str             # single observable that kills branch
    adjacent_asset_effects:  dict            # {ticker: 'positive'/'negative'/'neutral'}
    slt_stage_at_collapse:   str             # expected SLT stage when branch fires
    half_life_days:          int             # max validity window in days
    created_date:            str             # ISO date
    branch_status:           str             # ACTIVE / INVALIDATED / FIRED / EXPIRED
    invalidation_met:        bool            # True if invalidation_condition is met
    days_elapsed:            int             # days since created

def create_branch_payload(branch_id, description, hwe_weight, hwe_state,
                           confirmation_triggers, payoff_estimate,
                           invalidation_condition, adjacent_asset_effects,
                           slt_stage_at_collapse, half_life_days) -> BranchPayload:
    return BranchPayload(
        branch_id               = branch_id,
        branch_description      = description,
        hwe_weight              = hwe_weight,
        hwe_state               = hwe_state,
        confirmation_triggers   = confirmation_triggers,
        payoff_estimate         = payoff_estimate,
        invalidation_condition  = invalidation_condition,
        adjacent_asset_effects  = adjacent_asset_effects,
        slt_stage_at_collapse   = slt_stage_at_collapse,
        half_life_days          = half_life_days,
        created_date            = date.today().isoformat(),
        branch_status           = 'ACTIVE',
        invalidation_met        = False,
        days_elapsed            = 0,
    )

def evaluate_branch_payload(branch: BranchPayload, days_elapsed: int,
                             invalidation_triggered: bool,
                             confirmation_triggered: bool,
                             lps_state: str = 'MODERATE',
                             nii_state: str = 'GROUNDED',
                             rtt_result: str = 'PORTABLE') -> dict:
    branch['days_elapsed']    = days_elapsed
    branch['invalidation_met']= invalidation_triggered
    # Determine branch status
    if invalidation_triggered:
        branch['branch_status'] = 'INVALIDATED'
    elif confirmation_triggered:
        branch['branch_status'] = 'FIRED'
    elif days_elapsed > branch['half_life_days']:
        branch['branch_status'] = 'EXPIRED'
    else:
        branch['branch_status'] = 'ACTIVE'
    # Apply environment discounts to payoff
    payoff = branch['payoff_estimate']
    if lps_state in ('HIGH', 'EXTREME'):
        payoff *= 0.70   # loaded environment reduces expected payoff
    if nii_state in ('INFLATED', 'HYPER'):
        payoff *= 0.65   # inflated narrative reduces expected payoff
    if rtt_result in ('CONDITIONAL', ):
        payoff *= 0.80
    elif rtt_result in ('REGIME_BOUND', 'ELEGANT_FRAGILE'):
        payoff *= 0.0    # branch not tradeable in this regime
    return {
        'branch_id':        branch['branch_id'],
        'branch_status':    branch['branch_status'],
        'hwe_weight':       branch['hwe_weight'],
        'payoff_adj':       round(payoff, 3),
        'enterable':        (branch['branch_status'] == 'ACTIVE'
                             and branch['hwe_state'] == 'COMMITTED'
                             and payoff > 0),
        'block_reason':     (
            'INVALIDATED — branch dead'      if branch['branch_status'] == 'INVALIDATED' else
            'EXPIRED — half_life exceeded'   if branch['branch_status'] == 'EXPIRED' else
            'HWE not COMMITTED'              if branch['hwe_state'] != 'COMMITTED' else
            'Payoff zeroed by regime'        if payoff == 0.0 else
            None
        ),
        'adjacent_effects': branch['adjacent_asset_effects'],
    }

def branch_payload_gate(branches: list, require_committed: bool = True) -> dict:
    """Evaluate all branches for a thesis and determine entry decision."""
    active   = [b for b in branches if b['branch_status'] == 'ACTIVE']
    invalid  = [b for b in branches if b['branch_status'] == 'INVALIDATED']
    if not active:
        return {'action': 'BLOCK', 'reason': 'No active branches — all invalidated or expired'}
    if require_committed:
        committed = [b for b in active if b['hwe_state'] == 'COMMITTED']
        if not committed:
            return {'action': 'WAIT', 'reason': 'No COMMITTED branches yet'}
    best = max(active, key=lambda b: b.get('payoff_estimate', 0))
    return {
        'action':           'ENTER',
        'best_branch':      best['branch_id'],
        'payoff_estimate':  best.get('payoff_estimate', 0),
        'adjacent_effects': best.get('adjacent_asset_effects', {}),
        'active_count':     len(active),
        'invalidated_count':len(invalid),
    }
