# PROPAGATION_SPREAD_ESTIMATOR (PSE)
# Module: S3B — Spread probability layer
# Added: April 17-18 2026
# Source: Chemical Brothers "Do It Again" / contagion / paint bucket session
#
# P(spread) = σ(β₀ + β₁×f1 + β₂×f2 + β₃×f3 + β₄×f4 + β₅×f5 + β₆×f6)
#
# The paint bucket law: not every paint bucket spreads.
# A signal can have CFD CONVERGING + SBE STRONG_FLOAT + ASS HIGH and
# still fail to propagate if network susceptibility is low, timing is off,
# amplification channels are absent, or narrative fit is poor.
#
# PSE asks: P(this signal will actually PROPAGATE into broad participant adoption)?
#
# PSE is distinct from:
#   CFD: measures consensus formation rate in raw corpus (necessary, not sufficient)
#   NSD: measures narrative vs structural depth gap (PSE uses NSD as input f5)
#   SBE: measures present-state signal buoyancy (PSE HIGH_SPREAD → SBE S += 0.05)
#   RTT: stress-tests regime survival (PSE uses RTT PORTABLE as input f6)
#
# 6 spread probability features:
#
# f1: SIGNAL_NOVELTY (0-1, β₁=+1.5)
#   = 1 - WMBRL_base_rate
#   Low base rate = novel = more spreadable.
#   Known/repeated themes (high base rate) have lower spread potential.
#   RTX Day 3: defence procurement angle = 0.55 (moderately novel)
#   CVX Day 80: war/oil = 0.05 (very low novelty by Day 80)
#
# f2: NETWORK_SUSCEPTIBILITY (0-1, β₂=+2.0)
#   = CFD CC_score * (1 - SBS_echo_density)
#   High context collapse (theme spreading across communities) AND
#   low echo density (not trapped in one chamber) = susceptible network.
#   This is the most predictive feature: can the crowd actually be reached?
#
# f3: TIMING_ALIGNMENT (0-1, β₃=+1.8)
#   = MTL state score:
#     OPENING  = 1.0  (most propagation window remaining)
#     BUILDING = 0.8  (still strong timing)
#     PEAK     = 0.6  (now or never)
#     CLOSING  = 0.3  (late, diminishing returns)
#     EXPIRED  = 0.0  (window closed, no propagation possible)
#   CVX Day 80: MTL EXPIRED = 0.0 -> f3 = 0.0 -> P(spread) collapses
#
# f4: AMPLIFIER_PRESENCE (0-1, β₄=+1.5)
#   = min(SPF_avg/10, 1.0) * (1 - NIS_momentum_fraction) * (1 - CFD_LOCKED)
#   Are high-credibility sources (SPF) already engaging?
#   Is signal-dominant vs momentum-driven (NIS SIGNAL_DOMINANT = low momentum)?
#   Is CFD still forming (not LOCKED/saturated)?
#   First dancers = high-SPF + signal-dominant = amplifier present
#
# f5: NARRATIVE_FIT (0-1, β₅=+1.2)
#   = 1 - abs(NSD_score)  -- inverted absolute NSD
#   NSD NEUTRAL (abs small) = best narrative fit for DURABLE spread
#   NSD OVEREXTENDED (Kingfisher): brittle burst, doesn't propagate durably
#   NSD UNDERVALUED: spreads but slowly (structure ahead of narrative)
#   Best spread probability when narrative and structure are in alignment
#
# f6: CONTEXT_READINESS (0-1, β₆=+1.0)
#   = RTT_portability_score * EDS_alignment
#   If thesis is regime-portable AND expected market response is aligned:
#   the environment is ready to receive and amplify the signal.
#   CVX Day 80: RTT HOSTILE = 0.0 -> f6 = 0.0
#
# PSE output thresholds:
#   HIGH_SPREAD:   P(spread) >= 0.65 -> full pipeline, SBE S += 0.05, IL STAGGER unlock
#   MODERATE:      P(spread) 0.40-0.65 -> IL STAGGER allowed, no FIRE_MODE boost
#   LOW:           P(spread) 0.20-0.40 -> IL PROBE only, flag for review
#   NO_SPREAD:     P(spread) < 0.20  -> IL SANDBOX or LEAVE
#
# β weights (heuristic until calibrated on T=10+ closed trades):
#   β₀ = -2.0   (intercept: most signals default to low spread probability)
#   β₁ = +1.5   (novelty)
#   β₂ = +2.0   (network susceptibility — most predictive)
#   β₃ = +1.8   (timing alignment)
#   β₄ = +1.5   (amplifier presence)
#   β₅ = +1.2   (narrative fit)
#   β₆ = +1.0   (context readiness)
#
# Portfolio retrospectives:
#   RTX Day 3:
#     f1=0.55, f2=0.70, f3=1.0 (OPENING), f4=0.80, f5=0.75, f6=0.85
#     P(spread) = σ(-2 + 0.82 + 1.40 + 1.80 + 1.20 + 0.90 + 0.85) = σ(4.97) ≈ 0.993
#     HIGH_SPREAD -> S boost +0.05 -> SBE B = STRONG_FLOAT -> +3.90% WIN
#
#   CVX Day 80:
#     f1=0.05, f2=0.10, f3=0.0 (EXPIRED), f4=0.15, f5=0.10, f6=0.0
#     P(spread) = σ(-2 + 0.08 + 0.20 + 0.00 + 0.23 + 0.12 + 0.00) = σ(-1.37) ≈ 0.20
#     NO_SPREAD -> LEAVE -> confirms SBE TRAP -> -8.82% avoided
#
#   SGOL April 16:
#     f1=0.35, f2=0.60, f3=1.0 (OPENING), f4=0.70, f5=0.75, f6=0.80
#     P(spread) = σ(-2 + 0.52 + 1.20 + 1.80 + 1.05 + 0.90 + 0.80) = σ(4.27) ≈ 0.986 -> HIGH_SPREAD
#     IL STAGGER tranche_1 confirmed -> +7.2% unrealised holds
#
# Song mapping (Chemical Brothers "Do It Again"):
#   'Let's turn this thing electric' = CFD CONVERGING (ignition trigger)
#   First dancer converts          = PSE f4 amplifier (DEUTERIUM first mover)
#   Crowd starts dancing           = PSE f2 susceptibility (network receptive)
#   'Do it again' loop             = NIS MOMENTUM_DOMINANT
#   Everyone dancing               = SLT CROWDING + MTL CLOSING + PSE LOW
#   Not every bucket spreads       = PSE < 0.20 -> LEAVE (the core law)
#
# Strategic law: your edge is not dancing. It is forecasting when dancing will spread.
# P(spread) is the quantification of that edge.

import math

PSE_BETA_INTERCEPT    = -2.0
PSE_BETAS = {
    'novelty':       1.5,
    'susceptibility':2.0,
    'timing':        1.8,
    'amplifier':     1.5,
    'narrative_fit': 1.2,
    'context':       1.0,
}

MTL_TIMING_SCORES = {
    'OPENING': 1.0, 'BUILDING': 0.8, 'PEAK': 0.6,
    'CLOSING': 0.3, 'EXPIRED': 0.0,
}
RTT_PORTABILITY = {
    'PORTABLE': 1.0, 'CONDITIONAL': 0.7, 'REGIME_BOUND': 0.3,
    'HOSTILE': 0.0, 'ELEGANT_FRAGILE': 0.0,
}

def pse_features(wmbrl_base_rate, cfd_cc_score, sbs_echo_density,
                 mtl_state, spf_avg, nis_momentum_fraction,
                 cfd_locked, nsd_score, rtt_tier, eds_alignment_score) -> dict:
    f1 = max(0.0, min(1.0, 1 - wmbrl_base_rate))
    f2 = max(0.0, min(1.0, cfd_cc_score * (1 - sbs_echo_density)))
    f3 = MTL_TIMING_SCORES.get(mtl_state, 0.5)
    f4 = max(0.0, min(1.0, (spf_avg/10) * (1 - nis_momentum_fraction) * (1 - float(cfd_locked))))
    f5 = max(0.0, min(1.0, 1 - abs(nsd_score)))
    f6 = max(0.0, min(1.0, RTT_PORTABILITY.get(rtt_tier, 0.5) * eds_alignment_score))
    return {'novelty': round(f1,3), 'susceptibility': round(f2,3),
            'timing': round(f3,3), 'amplifier': round(f4,3),
            'narrative_fit': round(f5,3), 'context': round(f6,3)}

def pse_probability(features: dict) -> float:
    linear = PSE_BETA_INTERCEPT
    for k, beta in PSE_BETAS.items():
        linear += beta * features.get(k, 0.0)
    return round(1 / (1 + math.exp(-linear)), 3)

def classify_pse_state(p_spread: float) -> str:
    if p_spread >= 0.65:  return 'HIGH_SPREAD'
    elif p_spread >= 0.40: return 'MODERATE'
    elif p_spread >= 0.20: return 'LOW'
    else:                 return 'NO_SPREAD'

def pse_effects(pse_state: str) -> dict:
    effects = {
        'HIGH_SPREAD': {'sbe_s_boost': 0.05, 'il_unlock': 'STAGGER',
                        'note': 'HIGH_SPREAD. Crowd ready to dance. S boost + STAGGER unlock.'},
        'MODERATE':    {'sbe_s_boost': 0.0,  'il_unlock': 'STAGGER',
                        'note': 'MODERATE. STAGGER allowed but no FIRE_MODE boost.'},
        'LOW':         {'sbe_s_boost': 0.0,  'il_unlock': 'PROBE',
                        'note': 'LOW. IL PROBE only. Not every bucket spreads.'},
        'NO_SPREAD':   {'sbe_s_boost': 0.0,  'il_unlock': 'SANDBOX_OR_LEAVE',
                        'note': 'NO_SPREAD. LEAVE or SANDBOX. CVX Day 80 pattern.'},
    }
    return effects.get(pse_state, {'sbe_s_boost': 0.0, 'il_unlock': 'LEAVE'})

def pse_full_check(wmbrl_base_rate, cfd_cc_score, sbs_echo_density,
                   mtl_state, spf_avg, nis_momentum_fraction, cfd_locked,
                   nsd_score, rtt_tier, eds_alignment_score) -> dict:
    feats  = pse_features(wmbrl_base_rate, cfd_cc_score, sbs_echo_density,
                          mtl_state, spf_avg, nis_momentum_fraction,
                          cfd_locked, nsd_score, rtt_tier, eds_alignment_score)
    p      = pse_probability(feats)
    state  = classify_pse_state(p)
    effects = pse_effects(state)
    return {
        'p_spread':  p,
        'pse_state': state,
        'features':  feats,
        'effects':   effects,
    }
