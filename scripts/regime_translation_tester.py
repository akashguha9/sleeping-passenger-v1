# REGIME_TRANSLATION_TESTER (RTT)
# Module: S8 — Risk Layer
# Added: April 17 2026
# Source: Farke / Norwich / Pukki session
#
# Stress-tests whether a COMMITTED thesis survives a transition to a
# harsher environment. Formalises: paper trading = Championship,
# live markets = Premier League.
#
# Pipeline has EQS (current container quality), WMBRL (base-rates),
# SDI (current environment correction). None explicitly simulates:
# 'if friction increases by X, does this thesis survive?'
#
# RTT applies three explicit friction tiers to each COMMITTED thesis:
#   BENIGN:   current conditions (EQS, SDI, WMBRL as-is)
#   MODERATE: +1 friction tier (faster counter-parties, tighter spreads)
#   HOSTILE:  +2 friction tiers (adversarial adaptation, slippage spike,
#             emotional override, reduced fill quality)
#
# CE_benign    = CE_corrected (standard)
# CE_moderate  = CE_benign * (1 - friction_factor_1)
# CE_hostile   = CE_benign * (1 - friction_factor_1) * (1 - friction_factor_2)
#
# RTT_result classifications:
#   PORTABLE:        CE_hostile > ENTER_THRESHOLD -> scale after T>=10
#   CONDITIONAL:     CE_moderate OK, CE_hostile fails -> small size only
#   REGIME_BOUND:    CE_moderate < threshold -> paper-trading artefact, block
#   ELEGANT_FRAGILE: CE_benign HIGH, CE_hostile near zero -> Norwich pattern
#
# Portfolio retrospectives:
#   RTX Day 3:   WMBRL=0.71, CIS2=10, HWE COMMITTED. CE_hostile > threshold.
#                RTT=PORTABLE. Scale-ready after T>=10. +3.90% WIN confirms.
#   CVX Day 80:  WMBRL=0.08, NIS MOMENTUM_DOMINANT, NII HYPER.
#                CE_benign already degraded. RTT=REGIME_BOUND -> block.
#                -8.82% avoided. RTT fires before SDI/CIS2 reach thresholds.
#   GLD current: WMBRL=0.78, EDS CONFIRMING, mechanism clear.
#                Safe-haven not arbitrageable out. RTT=PORTABLE -> +8.17%.
#
# Norwich analogy:
#   Championship = BENIGN tier (T=6 paper phase, SCM_rate=0.17, epsilon=1.0)
#   Premier League = HOSTILE tier (live trading, adversarial adaptation)
#   ELEGANT_FRAGILE = beautiful system that collapses under pressure
#   ATOM retirement is required before RTT can run fast enough to be useful.
#
# Friction factors (heuristic until calibrated on live execution data at T=10+):
#   friction_factor_1 (MODERATE): 0.20 baseline (20% CE reduction)
#   friction_factor_2 (HOSTILE):  0.30 additional (30% of remaining CE)
#   These will be replaced by empirical data from live trade execution log.

RTT_ENTER_THRESHOLD  = 0.55   # minimum CE to enter
FRICTION_MODERATE    = 0.20   # 20% CE reduction for MODERATE tier
FRICTION_HOSTILE     = 0.30   # 30% further reduction for HOSTILE tier

def compute_rtt_tiers(ce_corrected: float) -> dict:
    ce_benign   = ce_corrected
    ce_moderate = ce_benign   * (1 - FRICTION_MODERATE)
    ce_hostile  = ce_moderate * (1 - FRICTION_HOSTILE)
    return {
        'ce_benign':   round(ce_benign,   3),
        'ce_moderate': round(ce_moderate, 3),
        'ce_hostile':  round(ce_hostile,  3),
    }

def classify_rtt_result(tiers: dict, hwe_committed: bool = True) -> str:
    b = tiers['ce_benign']
    m = tiers['ce_moderate']
    h = tiers['ce_hostile']
    if not hwe_committed:
        return 'NOT_COMMITTED'
    if h >= RTT_ENTER_THRESHOLD:
        return 'PORTABLE'
    elif m >= RTT_ENTER_THRESHOLD and h < RTT_ENTER_THRESHOLD:
        if b > 0.75:
            return 'ELEGANT_FRAGILE'
        return 'CONDITIONAL'
    elif m < RTT_ENTER_THRESHOLD:
        if b < RTT_ENTER_THRESHOLD:
            return 'REGIME_BOUND_WEAK'
        return 'REGIME_BOUND'
    return 'REGIME_BOUND'

def rtt_entry_gate(rtt_result: str) -> dict:
    gates = {
        'PORTABLE':          {'action': 'ENTER', 'size': 'FULL_QUARTER_UNIT',
                               'note': 'Survives all tiers. Scale after T>=10.'},
        'ELEGANT_FRAGILE':   {'action': 'SHADOW_BOOK',  'size': 'NO_ENTRY',
                               'note': 'Norwich pattern. Beautiful but fragile. Do not enter.'},
        'CONDITIONAL':       {'action': 'ENTER_SMALL',  'size': 'HALF_QUARTER_UNIT',
                               'note': 'Moderate only. Minimum size. No scaling.'},
        'REGIME_BOUND':      {'action': 'LEAVE',        'size': 'NO_ENTRY',
                               'note': 'Paper-trading artefact. Block.'},
        'REGIME_BOUND_WEAK': {'action': 'LEAVE',        'size': 'NO_ENTRY',
                               'note': 'Fails even in current conditions. Block.'},
        'NOT_COMMITTED':     {'action': 'WAIT',         'size': 'NO_ENTRY',
                               'note': 'HWE not at COMMITTED state. No RTT yet.'},
    }
    return gates.get(rtt_result, {'action': 'LEAVE', 'size': 'NO_ENTRY', 'note': 'Unknown.'})

def rtt_full_check(ce_corrected: float, hwe_committed: bool = True,
                   hwe_max_weight: float = 0.0) -> dict:
    if not hwe_committed or hwe_max_weight < 0.80:
        return {
            'rtt_result': 'NOT_COMMITTED',
            'tiers':      None,
            'gate':       rtt_entry_gate('NOT_COMMITTED'),
        }
    tiers  = compute_rtt_tiers(ce_corrected)
    result = classify_rtt_result(tiers, hwe_committed)
    gate   = rtt_entry_gate(result)
    return {
        'rtt_result':  result,
        'tiers':       tiers,
        'gate':        gate,
        'note':        gate['note'],
    }
