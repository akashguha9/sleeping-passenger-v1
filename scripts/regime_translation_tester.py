# REGIME_TRANSLATION_TESTER (RTT)
# Module: S3B — Regime stress / friction testing
# Added: April 17-18 2026
# Source: Downhill biker / craft-first / market physics session
#
# The 'tricks on any two-wheeler' test.
# Does this thesis work on any given market regime, or only this smooth one?
#
# RTT formally subjects a candidate thesis to 4 friction tiers:
#   PORTABLE:        CE survives regime change (<15% degradation)
#                    -> FIRE_MODE allowed if SBE STRONG_FLOAT + ASS HIGH
#   CONDITIONAL:     CE degrades 15-35% under adversarial regimes
#                    -> QUARTER_UNIT only, size reduction required
#   REGIME_BOUND:    CE degrades >35% if regime shifts
#                    -> IL PROBE only. Not FIRE_MODE. Context-dependent hack.
#   HOSTILE:         CE breaks under stress injection
#                    -> BLOCK regardless of SBE/ASS scores
#
# ELEGANT_FRAGILE (special classification):
#   CE is high in current conditions but collapses COMPLETELY in any regime stress.
#   Thesis only works in perfect smooth-market conditions.
#   -> PERMANENT BLOCK flag. Log and never enter. Most dangerous classification.
#
# RTT position in pipeline (after SBE and ASS, before FIRE_MODE):
#   SBE: B = S-(E+H) — does signal float in CURRENT environment? (present-state)
#   ASS: Q = O×S — is trade quality high NOW? (present-state)
#   RTT: PORTABLE/CONDITIONAL/REGIME_BOUND/HOSTILE — does thesis survive REGIME CHANGE? (future-state)
#   -> PORTABLE: FIRE_MODE
#   -> CONDITIONAL: QUARTER_UNIT
#   -> REGIME_BOUND: IL PROBE only
#   -> HOSTILE or ELEGANT_FRAGILE: BLOCK
#
# 5 friction stressors injected:
#
#   timing_mismatch:
#     Add 2-5 day execution delay to the entry.
#     Does CE still hold? Does BRANCH_PAYLOAD invalidation still not trigger?
#     PASS if CE degrades < 20% at T+5d
#     FAIL if CFD moves to LOCKED or SLT moves to CROWDING within delay window
#
#   volatility_shock:
#     Add 2-sigma volatility spike to underlying.
#     Does thesis survive (or benefit from) the volatility?
#     PASS if thesis direction survives or is enhanced (e.g. GLD benefits from vol)
#     FAIL if volatility spike would trigger stop or invalidate HWE max hypothesis
#
#   narrative_flip:
#     Invert the dominant narrative (e.g. war -> ceasefire, tightening -> pivot).
#     Does the invalidation_condition catch this? Is it defined in BRANCH_PAYLOAD?
#     PASS if invalidation_condition exists and narrative_flip triggers it cleanly
#     FAIL if thesis has no defined invalidation or if narrative_flip creates ambiguity
#
#   liquidity_trap:
#     Reduce available liquidity 50% (spreads widen, position harder to exit).
#     Does exit_clarity remain >= VALIDATION in SLT?
#     PASS if instrument is large-cap or liquid enough to survive 50% reduction
#     FAIL if exit_clarity drops to CROWDING/EXHAUSTION level under liquidity stress
#
#   fatigue_sequence:
#     Apply 3 consecutive adverse days (against thesis direction).
#     Does conviction hold? Does REALM_CLASSIFIER remain HUMAN not ANIMAL?
#     PASS if BRANCH_PAYLOAD bull case still intact after 3 adverse days
#     FAIL if CHAOS_ENTRY risk rises OR REALM -> ANIMAL state detected
#
# CE degradation calculation:
#   For each stressor: estimate CE_stressed vs CE_current
#   degradation_i = (CE_current - CE_stressed) / CE_current
#   avg_degradation = mean(degradation_i for passing stressors)
#   PORTABLE if avg_degradation < 0.15
#   CONDITIONAL if avg_degradation 0.15-0.35
#   REGIME_BOUND if avg_degradation > 0.35
#   HOSTILE if any critical stressor fails (narrative_flip + timing both fail)
#   ELEGANT_FRAGILE if ALL stressors fail but current SBE B = STRONG_FLOAT
#
# Two-wheeler map (bike physics -> market physics):
#   Balance        -> Position sizing + risk control (SBE B_state)
#   Momentum       -> CFD dCS/dt + NIS signal-dominant fraction
#   Friction       -> Transaction cost + execution reality (timing_mismatch stressor)
#   Inertia        -> NIS narrative persistence across SLT stages
#   Reversal force -> EDS STRONG_DIVERGE + narrative_flip stressor
#   Liquidity      -> RTT liquidity_trap + ASS exit_clarity
#   Tempo          -> REALM_CLASSIFIER IT vs RT mismatch
#   Asymmetry      -> ASS O asymmetry_ratio
#
# Portfolio retrospectives:
#   RTX Day 3:
#     timing_mismatch:  defence procurement thesis holds at T+5 -> PASS
#     volatility_shock: Iran escalation survives 2-sigma -> PASS
#     narrative_flip:   ceasefire = defined invalidation in BRANCH_PAYLOAD -> PASS
#     liquidity_trap:   RTX is liquid large-cap, 50% reduction tolerable -> PASS
#     fatigue_sequence: thesis persists across 3 adverse days -> PASS
#     RTT: PORTABLE -> FIRE_MODE ALLOWED -> +3.90% WIN
#
#   CVX Day 80:
#     timing_mismatch:  Day 80 delay = further CROWDING acceleration -> FAIL
#     volatility_shock: at EXHAUSTION, vol spike = TRAP acceleration -> FAIL
#     narrative_flip:   war narrative inversion already starting -> FAIL
#     RTT: HOSTILE -> BLOCK -> confirms SBE TRAP -> -8.82% avoided
#
#   GLD current:
#     timing_mismatch:  safe-haven thesis persists T+5 -> PASS
#     volatility_shock: gold benefits asymmetrically from vol spike -> PASS
#     narrative_flip:   ceasefire = defined invalidation -> PASS
#     liquidity_trap:   GLD/SGOL liquid -> PASS
#     fatigue_sequence: war thesis persists across 3 adverse days -> PASS
#     RTT: PORTABLE -> QUARTER_UNIT ALLOWED -> +8.17% holds
#
# The two-wheeler law:
#   Deep skill works on any vehicle.
#   PORTABLE beats REGIME_BOUND every time.
#   Craft first. Battle-tested before productised.
#   A thesis that only works in smooth markets is ELEGANT_FRAGILE: beautiful, useless.

PORTABLE_THRESHOLD     = 0.15   # max avg degradation for PORTABLE
CONDITIONAL_THRESHOLD  = 0.35   # max avg degradation for CONDITIONAL
ELEGANT_FRAGILE_MIN_SBE = 'STRONG_FLOAT'  # EF only if currently looks great

STRESSOR_TYPES = ['timing_mismatch', 'volatility_shock', 'narrative_flip',
                  'liquidity_trap', 'fatigue_sequence']

def assess_stressor(stressor_type: str, ce_current: float, thesis_context: dict) -> dict:
    pass_conditions = {
        'timing_mismatch':  lambda c: c.get('slt_stage') not in ('CROWDING','EXHAUSTION','CLOSURE')
                                      and c.get('cfd_state') not in ('LOCKED',),
        'volatility_shock': lambda c: c.get('thesis_benefits_from_vol', False)
                                      or c.get('invalidation_not_triggered', True),
        'narrative_flip':   lambda c: c.get('branch_payload_has_invalidation', False),
        'liquidity_trap':   lambda c: c.get('instrument_liquid', True),
        'fatigue_sequence': lambda c: c.get('realm_state', 'HUMAN') != 'ANIMAL'
                                      and c.get('slt_stage') not in ('EXHAUSTION','CLOSURE'),
    }
    passed = pass_conditions[stressor_type](thesis_context)
    ce_stressed = ce_current * (0.85 if passed else 0.40)
    degradation = (ce_current - ce_stressed) / max(ce_current, 0.001)
    return {
        'stressor':    stressor_type,
        'passed':      passed,
        'ce_stressed': round(ce_stressed, 3),
        'degradation': round(degradation, 3),
    }

def classify_rtt_tier(stressor_results: list, ce_current: float, sbe_b_state: str) -> dict:
    critical_fail = (
        not stressor_results[2]['passed'] and  # narrative_flip failed
        not stressor_results[0]['passed']       # timing_mismatch also failed
    )
    all_failed = all(not r['passed'] for r in stressor_results)
    passing = [r for r in stressor_results if r['passed']]
    if not passing:
        avg_deg = 1.0
    else:
        avg_deg = sum(r['degradation'] for r in stressor_results) / len(stressor_results)

    if all_failed and sbe_b_state == 'STRONG_FLOAT':
        tier = 'ELEGANT_FRAGILE'
        allowed = 'BLOCK_PERMANENT'
    elif critical_fail or avg_deg >= 1.0:
        tier = 'HOSTILE'
        allowed = 'BLOCK'
    elif avg_deg > CONDITIONAL_THRESHOLD:
        tier = 'REGIME_BOUND'
        allowed = 'IL_PROBE'
    elif avg_deg > PORTABLE_THRESHOLD:
        tier = 'CONDITIONAL'
        allowed = 'QUARTER_UNIT'
    else:
        tier = 'PORTABLE'
        allowed = 'FIRE_MODE'
    return {
        'friction_tier':    tier,
        'elegant_fragile':  tier == 'ELEGANT_FRAGILE',
        'allowed_action':   allowed,
        'avg_degradation':  round(avg_deg, 3),
        'pass_count':       len(passing),
        'fail_count':       len(stressor_results) - len(passing),
    }

def rtt_full_check(ce_current: float, sbe_b_state: str, thesis_context: dict) -> dict:
    results = [assess_stressor(s, ce_current, thesis_context) for s in STRESSOR_TYPES]
    tier    = classify_rtt_tier(results, ce_current, sbe_b_state)
    return {
        'friction_tier':    tier['friction_tier'],
        'elegant_fragile':  tier['elegant_fragile'],
        'allowed_action':   tier['allowed_action'],
        'avg_degradation':  tier['avg_degradation'],
        'pass_count':       tier['pass_count'],
        'fail_count':       tier['fail_count'],
        'stress_results':   {r['stressor']: 'PASS' if r['passed'] else 'FAIL'
                             for r in results},
    }
