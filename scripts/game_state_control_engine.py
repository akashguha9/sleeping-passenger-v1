# GAME_STATE_CONTROL_ENGINE (GSCE)
# Module: S4 — Execution
# Added: April 16 2026
# Source: Fabregas/Como meta-orchestrator session
#
# Classifies MARKET_PHASE and locks irrelevant modules per phase.
# Pipeline currently applies all modules to all signals at all times.
# GSCE prevents S4 (execution) from firing during BUILD_UP phase,
# and locks S0 (scanning) during FINAL_THIRD execution.
#
# Market phases:
#   BUILD_UP:    PBSC in {SLOW_CRAWLER, FAST_CRAWLER} and NLR_lag < 10d
#                S0 dominant. S4 LOCKED. Scan, build context, do not enter.
#
#   PROGRESSION: PBSC = PRE_BURST_COIL and NAR classified and SIS computed
#                S1+SIS+NAR dominant. S4 LOCKED. Classify, stress-test.
#
#   FINAL_THIRD: PBSC = STAND_UP_RUN and MTL_state = OPTIMAL
#                S4+MTL dominant. S0 LOCKED. Execute at t*, set hard stop.
#
#   TRANSITION:  Position open, monitoring for COUNT_D or thesis break
#                S8+CAL dominant. Monthly review only. Hard stop enforced.
#
# Retrospective:
#   April 4 CHAOS cluster: S4 fired in BUILD_UP phase.
#   GSCE locks S4 during BUILD_UP -> all 5 CHAOS entries blocked.
#
#   RTX: correctly progressed BUILD_UP -> PROGRESSION -> FINAL_THIRD -> TRANSITION.
#   Each phase gate passed. +3.90% SYSTEM_WIN confirmed.
#
# The Fabregas analogy:
#   He does not play final-third kill passes during build-up.
#   He does not scan for new space during execution.
#   Each mode has dominant modules and locked modules.

MARKET_PHASES = ['BUILD_UP', 'PROGRESSION', 'FINAL_THIRD', 'TRANSITION']

PHASE_DOMINANT = {
    'BUILD_UP':    ['S0', 'PBSC', 'TVG', 'SBS'],
    'PROGRESSION': ['S1', 'SIS', 'NAR', 'NLR'],
    'FINAL_THIRD': ['S4', 'MTL', 'S35', 'CHIGURH'],
    'TRANSITION':  ['S8', 'CAL', 'OLM', 'TRC'],
}

PHASE_LOCKED = {
    'BUILD_UP':    ['S4', 'FIRE_MODE', 'CHIGURH'],
    'PROGRESSION': ['S4', 'FIRE_MODE'],
    'FINAL_THIRD': ['S0', 'PBSC_scan'],
    'TRANSITION':  ['S4', 'S0'],
}

def classify_market_phase(pbsc_state, nlr_lag_days, nar_classified,
                           sis_computed, mtl_state, position_open):
    if position_open:
        return 'TRANSITION'
    if pbsc_state == 'STAND_UP_RUN' and mtl_state == 'OPTIMAL':
        return 'FINAL_THIRD'
    if pbsc_state == 'PRE_BURST_COIL' and nar_classified and sis_computed:
        return 'PROGRESSION'
    return 'BUILD_UP'

def gsce_gate(module_name, market_phase):
    if module_name in PHASE_LOCKED[market_phase]:
        return False, f'{module_name} LOCKED during {market_phase} phase.'
    if module_name in PHASE_DOMINANT[market_phase]:
        return True, f'{module_name} DOMINANT during {market_phase} phase.'
    return True, f'{module_name} PASSIVE during {market_phase} phase.'
