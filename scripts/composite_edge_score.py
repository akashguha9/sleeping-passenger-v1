# COMPOSITE_EDGE_SCORE (CES)
# Module: S3A — Scoring synthesis layer
# Added: April 17-18 2026
# Source: Markets as chemistry / titration / reaction systems session
#
# CE = final weighted synthesis of all pipeline scoring dimensions.
# The single number that answers: 'is this reaction worth proceeding?'
#
# The chemistry insight: reaction outcome depends on temperature + concentration +
# purity + activation energy + container ALL SIMULTANEOUSLY.
# You cannot know whether to proceed from any one dimension alone.
#
# Pipeline scores each dimension separately:
#   SBE: B = S-(E+H) — signal buoyancy (reaction environment)
#   ASS: Q = O×S — trade quality (reagent concentration)
#   PSE: P(spread) — propagation probability (activation energy)
#   MTL: snap_window_score — intra-stage timing (temperature)
#   NSD: NS-SS — narrative vs structural gap (purity)
#   RTT: portability score — regime survival (container)
#   ZPD: gates_passing/6 — all-gates fraction (endpoint check)
#
# CES synthesises them into one number:
#
# CE = (w_SBE × SBE_B_norm) +
#      (w_ASS × ASS_Q) +
#      (w_PSE × PSE_p_spread) +
#      (w_MTL × MTL_snap_window_score) +
#      (w_NSD × NSD_structural_premium) +
#      (w_RTT × RTT_portability_score) +
#      (w_ZPD × ZPD_gate_fraction)
#
# Component weights (heuristic until calibrated on T=10+ outcomes):
#   w_SBE = 0.25   (most direct reaction-environment fit, highest weight)
#   w_ASS = 0.20   (opportunity quality)
#   w_PSE = 0.20   (propagation — activation energy)
#   w_MTL = 0.15   (timing — reaction temperature)
#   w_NSD = 0.10   (structural premium — purity signal)
#   w_RTT = 0.05   (regime container)
#   w_ZPD = 0.05   (all-gates simultaneous check)
#
# Component transformations:
#   SBE_B_norm: normalise B score to 0-1 range
#     B roughly in range -1 to +1; use (B + 1) / 2 as normalisation
#     STRONG_FLOAT ≈ 0.80-0.90, WEAK_FLOAT ≈ 0.50-0.65, TRAP ≈ 0.10-0.20
#
#   NSD_structural_premium: max(0, -NSD_score)
#     UNDERVALUED (NSD=-0.50) → premium = 0.50 (structure ahead = cleaner reagent)
#     NEUTRAL (NSD=0.0) → premium = 0.0 (no adjustment)
#     OVEREXTENDED (NSD=+0.60) → premium = 0.0 (no boost but H penalty already in SBE)
#     NOTE: NSD OVEREXTENDED already penalises SBE via H penalty — no double-penalise here
#
#   RTT_portability_score: PORTABLE=1.0, CONDITIONAL=0.7, REGIME_BOUND=0.3, HOSTILE=0.0
#
#   ZPD_gate_fraction: gates_passing / 6 (0 to 1)
#
# CE thresholds and IL routing:
#   STRONG_EDGE:   CE >= 0.70 → FIRE_MODE eligible (when ZPD CLEAN_ZONE also passes)
#   GOOD_EDGE:     CE 0.55-0.70 → IL STAGGER (controlled titration)
#   MARGINAL_EDGE: CE 0.40-0.55 → IL PROBE (small test entry)
#   WEAK_EDGE:     CE < 0.40  → IL SANDBOX or LEAVE (do not initiate reaction)
#
# Chemistry-to-component mapping:
#   Temperature (volatility/timing)    = MTL snap_window_score
#   Concentration (liquidity quality)  = ASS Q
#   Purity (signal cleanliness)        = NSD structural_premium
#   Activation energy (catalyst/prop)  = PSE P(spread)
#   Container (regime)                 = RTT portability
#   Reaction environment               = SBE B_normalised
#   Endpoint check                     = ZPD gate_fraction
#
# Portfolio retrospectives:
#   RTX Day 3: STRONG_EDGE
#     SBE_norm=0.83 (STRONG_FLOAT), ASS_Q=0.77, PSE=0.993, MTL=0.80 (OPENING),
#     NSD_prem=0.53 (UNDERVALUED), RTT=1.0 (PORTABLE), ZPD=1.0 (6/6)
#     CE = 0.25×0.83 + 0.20×0.77 + 0.20×0.993 + 0.15×0.80 +
#          0.10×0.53 + 0.05×1.0 + 0.05×1.0
#        = 0.208 + 0.154 + 0.199 + 0.120 + 0.053 + 0.050 + 0.050 = 0.834
#     STRONG_EDGE → FIRE_MODE eligible → EQS=0.94 → +3.90% WIN
#
#   CVX Day 80: WEAK_EDGE (CHAOS_ENTRY despite CE=0.040)
#     SBE_norm=0.15 (TRAP), ASS_Q=0.04, PSE=0.20, MTL=0.0 (EXPIRED),
#     NSD_prem=0.0 (OVEREXTENDED already in SBE), RTT=0.0 (HOSTILE), ZPD=0.33 (2/6)
#     CE = 0.25×0.15 + 0.20×0.04 + 0.20×0.20 + 0.15×0.0 +
#          0.10×0.0 + 0.05×0.0 + 0.05×0.33
#        = 0.038 + 0.008 + 0.040 + 0.000 + 0.000 + 0.000 + 0.017 = 0.103
#     WEAK_EDGE → LEAVE → CHAOS_ENTRY anyway → consequence_persistence=2.5
#     CE=0.103 was the cleanest possible signal to not proceed. Pipeline was ignored.
#
#   GLD current: GOOD_EDGE
#     SBE_norm=0.68 (WEAK_FLOAT), ASS_Q=0.60, PSE=0.85, MTL=0.50 (BUILDING),
#     NSD_prem=0.38 (UNDERVALUED), RTT=1.0 (PORTABLE), ZPD=0.67 (4/6)
#     CE = 0.25×0.68 + 0.20×0.60 + 0.20×0.85 + 0.15×0.50 +
#          0.10×0.38 + 0.05×1.0 + 0.05×0.67
#        = 0.170 + 0.120 + 0.170 + 0.075 + 0.038 + 0.050 + 0.033 = 0.656
#     GOOD_EDGE → IL STAGGER → QUARTER_UNIT → +8.17% holds
#
# The chemistry law:
#   You do not need the exact drop. You need CE >= 0.70.
#   The lab result replaces the last-straw obsession.
#   Readiness (CE) matters more than the catalyst (exact trigger).

CE_STRONG_EDGE   = 0.70
CE_GOOD_EDGE     = 0.55
CE_MARGINAL_EDGE = 0.40
# Below CE_MARGINAL_EDGE = WEAK_EDGE

CE_WEIGHTS = {
    'sbe_b_norm':           0.25,
    'ass_q':                0.20,
    'pse_p_spread':         0.20,
    'mtl_snap_window':      0.15,
    'nsd_structural_prem':  0.10,
    'rtt_portability':      0.05,
    'zpd_gate_fraction':    0.05,
}

RTT_PORTABILITY_SCORES = {
    'PORTABLE': 1.0, 'CONDITIONAL': 0.7,
    'REGIME_BOUND': 0.3, 'HOSTILE': 0.0, 'ELEGANT_FRAGILE': 0.0,
}

def normalise_sbe_b(b_score: float) -> float:
    return round(max(0.0, min(1.0, (b_score + 1.0) / 2.0)), 3)

def nsd_structural_premium(nsd_score: float) -> float:
    return round(max(0.0, -nsd_score), 3)

def compute_ce(sbe_b: float, ass_q: float, pse_p_spread: float,
               mtl_snap_window: float, nsd_score: float,
               rtt_tier: str, zpd_gates_passing: int) -> dict:
    sbe_norm = normalise_sbe_b(sbe_b)
    nsd_prem = nsd_structural_premium(nsd_score)
    rtt_port = RTT_PORTABILITY_SCORES.get(rtt_tier, 0.5)
    zpd_frac = zpd_gates_passing / 6.0
    components = {
        'sbe_b_norm':          sbe_norm,
        'ass_q':               round(min(1.0, max(0.0, ass_q)), 3),
        'pse_p_spread':        round(min(1.0, max(0.0, pse_p_spread)), 3),
        'mtl_snap_window':     round(min(1.0, max(0.0, mtl_snap_window)), 3),
        'nsd_structural_prem': nsd_prem,
        'rtt_portability':     rtt_port,
        'zpd_gate_fraction':   round(zpd_frac, 3),
    }
    ce = round(sum(CE_WEIGHTS[k] * components[k] for k in CE_WEIGHTS), 3)
    if ce >= CE_STRONG_EDGE:   tier = 'STRONG_EDGE'
    elif ce >= CE_GOOD_EDGE:   tier = 'GOOD_EDGE'
    elif ce >= CE_MARGINAL_EDGE: tier = 'MARGINAL_EDGE'
    else:                      tier = 'WEAK_EDGE'
    il_actions = {
        'STRONG_EDGE':   'FIRE_MODE_ELIGIBLE (requires ZPD CLEAN_ZONE)',
        'GOOD_EDGE':     'IL_STAGGER',
        'MARGINAL_EDGE': 'IL_PROBE',
        'WEAK_EDGE':     'IL_SANDBOX_OR_LEAVE',
    }
    return {
        'ce':          ce,
        'ce_tier':     tier,
        'il_action':   il_actions[tier],
        'components':  components,
        'note':        f'CE={ce:.3f} {tier}. {il_actions[tier]}.',
    }
