# ZONE_PRECISION_DETECTOR (ZPD) — CLEAN_ZONE mode
# Module: S5 — Behavioral + precision gate (extended)
# Added: April 17-18 2026
# Source: Football cognition / positional identity session (second biker pass)
#
# Extended from ZOOCHOSIS detection (maladaptive operator patterns)
# to include CLEAN_ZONE detection — the opposite state.
#
# CLEAN_ZONE: when all 6 criteria simultaneously pass, all mechanics are justified.
# This is the 40-yard free kick earned by technique.
# Tactical defending: no assist. Responsibility-bearing. Skill exposed.
#
# The 6 ZPD CLEAN_ZONE gates (ALL must pass simultaneously):
#   Gate 1: SBE B_state = 'STRONG_FLOAT'       (signal floats strongly)
#   Gate 2: ASS Q_state = 'HIGH' (Q >= 0.64)   (opportunity × survival both strong)
#   Gate 3: RTT friction_tier = 'PORTABLE'      (thesis survives regime change)
#   Gate 4: CFD cfd_state = 'CONVERGING'        (consensus rising, not locked/saturated)
#   Gate 5: SF sf_state IN ('CLEAN', 'PRISTINE') (low noise intake)
#   Gate 6: REALM = 'HUMAN'                     (operator in clean state)
#
# ZPD states:
#   CLEAN_ZONE:          6/6 gates pass
#     -> drift_risk < 8:  HALF_UNIT allowed (size upgrade earned)
#     -> drift_risk >= 8: QUARTER_UNIT (current cap), CLEAN_ZONE LOGGED
#     -> note: at current portfolio drift_risk_score=8, CLEAN_ZONE logs but
#              does not yet trigger HALF_UNIT until drift normalises
#
#   NEAR_CLEAN:          5/6 gates pass
#     -> QUARTER_UNIT (normal cap)
#     -> contamination_source: the one failing gate named explicitly
#
#   NOISE_CONTAMINATION: 4 or fewer gates pass
#     -> QUARTER_UNIT with ALL failing gates named
#     -> size cannot be upgraded under any condition
#
# Contamination source tags (when exactly 1 gate fails):
#   'SBE_BELOW_STRONG'      - Gate 1 fail: signal only WEAK_FLOAT not STRONG_FLOAT
#   'ASS_BELOW_HIGH'        - Gate 2 fail: Q only MODERATE not HIGH
#   'RTT_CONDITIONAL_ONLY'  - Gate 3 fail: regime CONDITIONAL not PORTABLE
#   'CFD_LOCKED_SATURATION' - Gate 4 fail: CFD LOCKED (consensus already complete)
#   'SF_NOISY_INTAKE'       - Gate 5 fail: SF NOISY or HYPED (loud signal)
#   'REALM_ELEVATED'        - Gate 6 fail: operator in FIRE_MODE or ANIMAL state
#
# Portfolio retrospectives:
#   RTX Day 3:
#     SBE STRONG_FLOAT (✓), ASS HIGH Q=0.77 (✓), RTT PORTABLE (✓),
#     CFD CONVERGING (✓), SF CLEAN (✓), REALM HUMAN (✓)
#     ZPD: CLEAN_ZONE (6/6) -> at drift_risk=8 -> QUARTER_UNIT + LOGGED
#     Outcome: +3.90% WIN. CLEAN_ZONE recognition confirmed.
#     When drift_risk drops below 8, same setup = HALF_UNIT allowed.
#
#   CVX Day 80 (CHAOS_ENTRY):
#     SBE TRAP (✗), ASS REJECT Q=0.04 (✗), RTT HOSTILE (✗),
#     CFD LOCKED (✗), SF HYPED (✗), REALM [ELEVATED] (✗)
#     ZPD: NOISE_CONTAMINATION (2/6) - 4 contamination sources named
#     Sources: SBE_BELOW_STRONG, ASS_BELOW_HIGH, RTT_HOSTILE, CFD_LOCKED_SATURATION
#     CHAOS_ENTRY was entered anyway. ZPD would have named all 4 failures.
#
#   GLD current:
#     SBE WEAK_FLOAT (✗ borderline), ASS MODERATE Q=0.60 (✗),
#     RTT PORTABLE (✓), CFD CONVERGING (✓), SF CLEAN (✓), REALM HUMAN (✓)
#     ZPD: NEAR_CLEAN (4/6) - 2 contamination sources
#     Sources: SBE_BELOW_STRONG + ASS_BELOW_HIGH
#     -> QUARTER_UNIT confirmed (no size upgrade), +8.17% holds
#
# Football cognition mapping:
#   Back 3-4 (CB/WB) = S0: CFD + SF + PE raw signal foundation
#   Double pivot (6/8) = S1: HWE + BRANCH_PAYLOAD narrative structure
#   #10 (orchestrator) = S35: ASS + SBE decision quality gate (user's role)
#   LW/RW (winger)     = S4: IL + FIRE_MODE execution edge (friend's role)
#   Tactical defending = RTT + ZPD: responsibility-bearing, no assist
#   40-yard free kick  = ZPD CLEAN_ZONE: attempt only when all 6 earned
#
# The clean zone law:
#   Take the 40-yard free kick only when all mechanics justify it.
#   CLEAN_ZONE is the earned shot.
#   NOISE_CONTAMINATION is someone else's ball.
#   Craft first. No assist. Skill exposed.
#
# Note: HALF_UNIT sizing is currently LOCKED because drift_risk_score=8.
# When portfolio is restructured and drift_risk < 8 (post-ATOM retirement,
# post-T=10 calibration), CLEAN_ZONE will activate HALF_UNIT.

CLEAN_ZONE_CRITERIA_COUNT = 6
CLEAN_ZONE_NEAR_THRESHOLD = 5    # 5/6 = NEAR_CLEAN
CLEAN_ZONE_MIN_THRESHOLD  = 4    # < 4 = NOISE_CONTAMINATION
HALF_UNIT_DRIFT_CEILING   = 8    # drift_risk must be below this for HALF_UNIT

CONTAMINATION_TAGS = {
    'sbe':   'SBE_BELOW_STRONG',
    'ass':   'ASS_BELOW_HIGH',
    'rtt':   'RTT_CONDITIONAL_ONLY',
    'cfd':   'CFD_LOCKED_SATURATION',
    'sf':    'SF_NOISY_INTAKE',
    'realm': 'REALM_ELEVATED',
}

def zpd_clean_zone_check(sbe_b_state: str, ass_q_state: str, rtt_friction_tier: str,
                          cfd_state: str, sf_state: str, realm_state: str,
                          current_drift_risk: int = 8) -> dict:
    gates = {
        'sbe':   sbe_b_state == 'STRONG_FLOAT',
        'ass':   ass_q_state == 'HIGH',
        'rtt':   rtt_friction_tier == 'PORTABLE',
        'cfd':   cfd_state == 'CONVERGING',
        'sf':    sf_state in ('CLEAN', 'PRISTINE'),
        'realm': realm_state == 'HUMAN',
    }
    passing = [k for k, v in gates.items() if v]
    failing = [k for k, v in gates.items() if not v]
    count = len(passing)

    if count == CLEAN_ZONE_CRITERIA_COUNT:
        zone_state = 'CLEAN_ZONE'
        half_unit_allowed = current_drift_risk < HALF_UNIT_DRIFT_CEILING
        allowed_size = 'HALF_UNIT' if half_unit_allowed else 'QUARTER_UNIT'
        note = ('CLEAN_ZONE. 40-yard free kick earned. HALF_UNIT allowed.' if half_unit_allowed
                else f'CLEAN_ZONE. All mechanics justified but drift_risk={current_drift_risk}>=8. '
                     f'QUARTER_UNIT cap applies. CLEAN_ZONE logged for future calibration.')
    elif count >= CLEAN_ZONE_NEAR_THRESHOLD:
        zone_state = 'NEAR_CLEAN'
        allowed_size = 'QUARTER_UNIT'
        note = f'NEAR_CLEAN. One criterion failing. QUARTER_UNIT.'
    else:
        zone_state = 'NOISE_CONTAMINATION'
        allowed_size = 'QUARTER_UNIT'
        note = f'NOISE_CONTAMINATION. {CLEAN_ZONE_CRITERIA_COUNT - count} criteria failing. No size upgrade.'

    contamination_sources = [CONTAMINATION_TAGS[k] for k in failing]
    return {
        'zpd_zone_state':        zone_state,
        'gates_passing':         count,
        'gates_failing':         CLEAN_ZONE_CRITERIA_COUNT - count,
        'allowed_size':          allowed_size,
        'half_unit_unlocked':    (zone_state == 'CLEAN_ZONE' and
                                  current_drift_risk < HALF_UNIT_DRIFT_CEILING),
        'contamination_sources': contamination_sources,
        'gate_detail':           gates,
        'note':                  note,
    }
